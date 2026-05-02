from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
from typing import Annotated
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.api.deps import DbSession, get_current_user, require_admin
from app.api.routes.auth import authenticate_local_user, create_login_session
from app.api.routes.ui import compact_content_rhythm_styles, render_public_shell_page, render_shell_page
from app.auth.api_tokens import (
    CAPTURE_JOBS_SCOPE,
    create_user_api_token,
    decode_scopes,
    revoke_user_api_token,
)
from app.auth.csrf import clear_csrf_cookie
from app.auth.sessions import revoke_session
from app.auth.users import UserAlreadyExists, create_local_user
from app.core.config import settings
from app.db.models.api_token import ApiToken
from app.db.models.job import Job
from app.db.models.user import User
from app.db.models.user_profile import UserProfile
from app.services.ai import (
    KNOWN_PROVIDERS,
    enable_ai_provider_model,
    list_user_ai_provider_settings,
    provider_default_base_url,
    provider_default_model,
    save_ai_provider_key_and_discover_models,
    upsert_ai_provider_setting,
)
from app.services.profiles import get_or_create_user_profile, get_user_profile

router = APIRouter(tags=["session-ui"])

OPENAI_BILLING_HELP_URL = "https://help.openai.com/en/articles/9039756-billing-settings-in-chatgpt-vs-platform"
OPENAI_API_QUICKSTART_URL = "https://platform.openai.com/docs/quickstart/using-the-api"
ANTHROPIC_API_OVERVIEW_URL = "https://docs.anthropic.com/en/api/getting-started"
GEMINI_API_KEYS_URL = "https://ai.google.dev/gemini-api/docs/api-key"
GEMINI_API_OVERVIEW_URL = "https://ai.google.dev/docs/gemini_api_overview/"


def _value(value: object) -> str:
    if value is None or value == "":
        return "Not set"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _form_value(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def login_page(*, error: str | None = None) -> HTMLResponse:
    error_block = f'<p class="error">{escape(error)}</p>' if error else ""
    extra_styles = """
    .auth-panel form { display: grid; gap: 14px; }
    .auth-panel .page-subtitle { max-width: none; }
    """
    body = f"""
    <section class="auth-panel">
      <form method="post" action="/login">
        {error_block}
        <label>
          Email
          <input name="email" type="email" autocomplete="email" required>
        </label>
        <label>
          Password
          <input name="password" type="password" autocomplete="current-password" required>
        </label>
        <button type="submit">Sign in</button>
      </form>
    </section>
    """
    return HTMLResponse(
        render_public_shell_page(
            page_title="Login",
            title="Application Tracker",
            subtitle="Sign in to manage your job search.",
            body=body,
            extra_styles=extra_styles,
        )
    )


def setup_page(*, error: str | None = None) -> HTMLResponse:
    error_block = f'<p class="error">{escape(error)}</p>' if error else ""
    extra_styles = """
    .auth-panel form { display: grid; gap: 14px; }
    """
    body = f"""
    <section class="auth-panel">
      <form method="post" action="/setup">
        {error_block}
        <label>
          Email
          <input name="email" type="email" autocomplete="email" required>
        </label>
        <label>
          Display name
          <input name="display_name" autocomplete="name" maxlength="200">
        </label>
        <label>
          Password
          <input name="password" type="password" autocomplete="new-password" minlength="8" required>
        </label>
        <label>
          Confirm password
          <input name="confirm_password" type="password" autocomplete="new-password" minlength="8" required>
        </label>
        <button type="submit">Create admin</button>
      </form>
    </section>
    """
    return HTMLResponse(
        render_public_shell_page(
            page_title="Set Up",
            title="Set up Application Tracker",
            subtitle="Create the first local administrator. This page is only available before any users exist.",
            body=body,
            extra_styles=extra_styles,
        )
    )


def _api_token_row(api_token: ApiToken) -> str:
    revoked = api_token.revoked_at is not None
    status_label = "Revoked" if revoked else "Active"
    revoke_form = (
        '<span class="muted">Revoked</span>'
        if revoked
        else f"""
        <form method="post" action="/settings/api-tokens/{escape(api_token.uuid, quote=True)}/revoke">
          <button type="submit" class="secondary">Revoke</button>
        </form>
        """
    )
    return f"""
    <tr>
      <td>{escape(api_token.name)}</td>
      <td>{escape(", ".join(decode_scopes(api_token.scopes)))}</td>
      <td>{escape(status_label)}</td>
      <td>{escape(_value(api_token.created_at))}</td>
      <td>{escape(_value(api_token.last_used_at))}</td>
      <td>{revoke_form}</td>
    </tr>
    """


def _ai_provider_rows(provider_settings) -> str:
    by_provider = {setting.provider: setting for setting in provider_settings}
    rows = []
    labels = {
        "openai": "OpenAI",
        "gemini": "Google Gemini (AI Studio)",
        "anthropic": "Anthropic",
        "openai_compatible": "OpenAI-compatible local endpoint",
    }
    for provider in KNOWN_PROVIDERS:
        setting = by_provider.get(provider)
        model_name = setting.model_name if setting and setting.model_name else provider_default_model(provider) or "Not set"
        base_url = setting.base_url if setting and setting.base_url else provider_default_base_url(provider) or "Not set"
        api_key_hint = setting.api_key_hint if setting and setting.api_key_hint else "Not saved"
        status = "Enabled" if setting and setting.is_enabled else "Disabled"
        rows.append(
            f"""
            <tr>
              <td>{escape(labels[provider])}</td>
              <td>{escape(model_name)}</td>
              <td>{escape(base_url)}</td>
              <td>{escape(api_key_hint)}</td>
              <td>{escape(status)}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def _model_select(setting) -> str:
    models = setting.discovered_models if setting and isinstance(setting.discovered_models, list) else []
    if not models:
        if setting and setting.provider == "openai_compatible" and setting.model_discovery_status == "failed":
            return f"""
            <label>
              Model
              <input name="model_name" maxlength="200" value="{escape(setting.model_name or '', quote=True)}" placeholder="Enter model manually">
            </label>
            <p class="muted">Model discovery failed for this custom endpoint: {escape(setting.model_discovery_error or 'unknown error')}</p>
            """
        return '<p class="muted">Save API key to discover available models.</p>'
    options = []
    selected_model = setting.model_name if setting else ""
    for model in models:
        if not isinstance(model, dict):
            continue
        model_id = model.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        label = model.get("display_name") if isinstance(model.get("display_name"), str) else model_id
        selected = " selected" if model_id == selected_model else ""
        option_label = f"{label} ({model_id})" if label != model_id else model_id
        options.append(
            f'<option value="{escape(model_id, quote=True)}"{selected}>{escape(option_label)}</option>'
        )
    if not options:
        return '<p class="muted">No usable models were returned.</p>'
    return f"""
    <label>
      Model
      <select name="model_name">
        {''.join(options)}
      </select>
    </label>
    """


def _provider_enable_form(provider: str, setting) -> str:
    if setting is None or not setting.api_key_encrypted:
        return ""
    return f"""
    <form method="post" action="/settings/ai-provider/enable">
      <input type="hidden" name="provider" value="{escape(provider, quote=True)}">
      {_model_select(setting)}
      <button type="submit">Enable selected model</button>
    </form>
    """


def _standard_ai_provider_form(provider: str, label: str, help_text: str) -> str:
    return f"""
    <div class="provider-card">
      <h3>{escape(label)}</h3>
      <p class="muted">{escape(help_text)}</p>
      <form method="post" action="/settings/ai-provider/discover">
        <input type="hidden" name="provider" value="{escape(provider, quote=True)}">
        <label>
          Friendly name
          <input name="label" maxlength="200" placeholder="{escape(label, quote=True)}">
        </label>
        <label>
          API key
          <input name="api_key" type="password" maxlength="400" placeholder="Leave blank to reuse saved key">
        </label>
        <button type="submit">Save key and discover models</button>
      </form>
      {{enable_form}}
    </div>
    """


def _custom_ai_provider_form(enable_form: str = "") -> str:
    return f"""
    <div class="provider-card">
      <h3>Custom OpenAI-compatible</h3>
      <p class="muted">Use this for local or third-party endpoints that expose an OpenAI-compatible chat completions API.</p>
      <form method="post" action="/settings/ai-provider/discover">
        <input type="hidden" name="provider" value="openai_compatible">
        <label>
          Friendly name
          <input name="label" maxlength="200" placeholder="Local Ollama, LM Studio, private gateway">
        </label>
        <label>
          Base URL
          <input name="base_url" maxlength="1000" placeholder="http://localhost:11434/v1">
        </label>
        <label>
          API key
          <input name="api_key" type="password" maxlength="400" placeholder="Leave blank to reuse saved key">
        </label>
        <button type="submit">Save key and discover models</button>
      </form>
      {enable_form}
    </div>
    """


def _ai_provider_setup_forms(provider_settings=None) -> str:
    by_provider = {setting.provider: setting for setting in provider_settings or []}
    return (
        '<div class="provider-grid">'
        + _standard_ai_provider_form(
            "openai",
            "OpenAI",
            "Preconfigured for the OpenAI API. Supply an API key; the model can be changed if needed.",
        ).replace("{enable_form}", _provider_enable_form("openai", by_provider.get("openai")))
        + _standard_ai_provider_form(
            "gemini",
            "Google Gemini",
            "Preconfigured for Google AI Studio. Supply a Gemini API key; endpoint details are handled by the app.",
        ).replace("{enable_form}", _provider_enable_form("gemini", by_provider.get("gemini")))
        + _standard_ai_provider_form(
            "anthropic",
            "Anthropic",
            "Preconfigured for the Anthropic Messages API. Supply an Anthropic API key to use Claude.",
        ).replace("{enable_form}", _provider_enable_form("anthropic", by_provider.get("anthropic")))
        + _custom_ai_provider_form(_provider_enable_form("openai_compatible", by_provider.get("openai_compatible")))
        + "</div>"
    )


def _admin_api_token_row(api_token: ApiToken) -> str:
    revoked = api_token.revoked_at is not None
    status_label = "Revoked" if revoked else "Active"
    revoke_form = (
        '<span class="muted">Revoked</span>'
        if revoked
        else f"""
        <form method="post" action="/admin/api-tokens/{escape(api_token.uuid, quote=True)}/revoke">
          <button type="submit" class="secondary">Revoke</button>
        </form>
        """
    )
    return f"""
    <tr>
      <td>{escape(api_token.owner.email)}</td>
      <td>{escape(api_token.name)}</td>
      <td>{escape(", ".join(decode_scopes(api_token.scopes)))}</td>
      <td>{escape(status_label)}</td>
      <td>{escape(_value(api_token.created_at))}</td>
      <td>{escape(_value(api_token.last_used_at))}</td>
      <td>{revoke_form}</td>
    </tr>
    """


def _appearance_js() -> str:
    return """<script>
  (() => {
    const THEMES = [
      { id: 'default', label: 'Default', accent: '#4F67E4' },
      { id: 'ocean',   label: 'Ocean',   accent: '#0B9090' },
      { id: 'forest',  label: 'Forest',  accent: '#2E7D46' },
      { id: 'rose',    label: 'Rose',    accent: '#C0395D' },
      { id: 'amber',   label: 'Amber',   accent: '#B06000' },
      { id: 'slate',   label: 'Slate',   accent: '#3D5475' },
      { id: 'violet',  label: 'Violet',  accent: '#7C4DDB' },
      { id: 'custom',  label: 'Custom',  accent: null },
    ];
    function darken(hex, amt) {
      var n = parseInt(hex.slice(1), 16);
      var r = Math.max(0, (n >> 16) - amt);
      var g = Math.max(0, ((n >> 8) & 0xff) - amt);
      var b = Math.max(0, (n & 0xff) - amt);
      return '#' + ((r << 16) | (g << 8) | b).toString(16).padStart(6, '0');
    }
    function lighten(hex) {
      var n = parseInt(hex.slice(1), 16);
      var r = Math.min(255, Math.round(((n >> 16)) * 0.08 + 234));
      var g = Math.min(255, Math.round((((n >> 8) & 0xff)) * 0.08 + 234));
      var b = Math.min(255, Math.round(((n & 0xff)) * 0.08 + 234));
      return '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('');
    }
    function applyTheme(id, customColor) {
      try { localStorage.setItem('at-theme', id); } catch(e) {}
      delete document.documentElement.dataset.theme;
      document.documentElement.style.removeProperty('--accent');
      document.documentElement.style.removeProperty('--accent-strong');
      document.documentElement.style.removeProperty('--accent-soft');
      if (id === 'custom') {
        var c = customColor || '#4F67E4';
        try { localStorage.setItem('at-custom-accent', c); } catch(e) {}
        document.documentElement.style.setProperty('--accent', c);
        document.documentElement.style.setProperty('--accent-strong', darken(c, 40));
        document.documentElement.style.setProperty('--accent-soft', lighten(c));
      } else if (id !== 'default') {
        document.documentElement.dataset.theme = id;
      }
    }
    const container = document.getElementById('at-theme-swatches');
    const customRow = document.getElementById('at-theme-custom-row');
    const customInput = document.getElementById('at-theme-custom-color');
    if (!container) return;
    const current = (() => { try { return localStorage.getItem('at-theme') || 'default'; } catch(e) { return 'default'; } })();
    const customAccent = (() => { try { return localStorage.getItem('at-custom-accent') || '#4F67E4'; } catch(e) { return '#4F67E4'; } })();
    if (customInput) customInput.value = customAccent;
    function updateActive(id) {
      container.querySelectorAll('.theme-swatch').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.theme === id);
        btn.setAttribute('aria-pressed', btn.dataset.theme === id ? 'true' : 'false');
      });
      if (customRow) customRow.style.display = id === 'custom' ? 'flex' : 'none';
    }
    container.querySelectorAll('.theme-swatch').forEach(btn => {
      btn.addEventListener('click', () => {
        applyTheme(btn.dataset.theme, customInput ? customInput.value : null);
        updateActive(btn.dataset.theme);
      });
    });
    if (customInput) {
      customInput.addEventListener('input', () => {
        var cur = (() => { try { return localStorage.getItem('at-theme') || 'default'; } catch(e) { return 'default'; } })();
        if (cur === 'custom') applyTheme('custom', customInput.value);
      });
    }
    updateActive(current);
  })();
</script>"""


def settings_page(
    user: User,
    api_tokens: list[ApiToken],
    *,
    profile: UserProfile | None = None,
    ai_provider_settings=None,
    new_token: str | None = None,
) -> HTMLResponse:
    token_rows = "\n".join(_api_token_row(api_token) for api_token in api_tokens)
    if not token_rows:
        token_rows = '<tr><td colspan="6" class="muted">No API tokens yet.</td></tr>'
    ai_provider_rows = _ai_provider_rows(ai_provider_settings or [])
    new_token_block = (
        f"""
        <section class="secret">
          <h2>New token</h2>
          <p>This secret is shown once. Paste it into Capture setup now.</p>
          <input value="{escape(new_token, quote=True)}" readonly>
          <p><a href="/api/capture/bookmarklet">Open Capture setup</a></p>
        </section>
        """
        if new_token
        else ""
    )
    profile_values = {
        "target_roles": escape(_form_value(profile.target_roles if profile else None)),
        "target_locations": escape(_form_value(profile.target_locations if profile else None)),
        "remote_preference": escape(_form_value(profile.remote_preference if profile else None)),
        "salary_min": escape(_form_value(profile.salary_min if profile else None)),
        "salary_max": escape(_form_value(profile.salary_max if profile else None)),
        "salary_currency": escape(_form_value(profile.salary_currency if profile else None)),
        "preferred_industries": escape(_form_value(profile.preferred_industries if profile else None)),
        "excluded_industries": escape(_form_value(profile.excluded_industries if profile else None)),
        "constraints": escape(_form_value(profile.constraints if profile else None)),
        "urgency": escape(_form_value(profile.urgency if profile else None)),
        "positioning_notes": escape(_form_value(profile.positioning_notes if profile else None)),
    }
    extra_styles = compact_content_rhythm_styles() + """
    .checkbox-label { align-items: center; display: flex; }
    .checkbox-label input { width: auto; }
    .inline-help {
      background: rgba(255,255,255,0.72);
      border: 1px solid var(--line-soft);
      border-radius: 12px;
      margin-top: 12px;
      padding: 12px 14px;
    }
    .inline-help summary {
      color: var(--ink);
      cursor: pointer;
      font-weight: 700;
      list-style: none;
    }
    .inline-help summary::-webkit-details-marker { display: none; }
    .inline-help-body {
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }
    .inline-help-links {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .inline-help-links a {
      border: 0.5px solid var(--line);
      border-radius: 10px;
      color: var(--accent-strong);
      display: inline-flex;
      min-height: 32px;
      padding: 0 10px;
      align-items: center;
    }
    input, select, textarea {
      border: 0.5px solid var(--line);
      border-radius: 10px;
      font: inherit;
      padding: 8px 10px;
      width: 100%;
    }
    textarea { min-height: 96px; resize: vertical; }
    .field-grid { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .provider-grid { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 14px; }
    .provider-card {
      border: 0.5px solid var(--line-soft);
      border-radius: 12px;
      display: grid;
      gap: 10px;
      padding: 14px;
    }
    .provider-card h3 { margin: 0; }
    button {
      background: var(--accent);
      border: 0;
      border-radius: 10px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 500;
      min-height: 38px;
      padding: 0 14px;
    }
    button:hover { background: var(--accent-strong); }
    button.secondary {
      background: #ffffff;
      border: 0.5px solid var(--line);
      color: var(--warn);
    }
    table { border-collapse: collapse; width: 100%; }
    th, td {
      border-bottom: 0.5px solid var(--line);
      padding: 10px 8px;
      text-align: left;
      vertical-align: middle;
    }
    th { color: var(--muted); font-size: 0.82rem; text-transform: uppercase; }
    td form { margin: 0; }
    .secret { border-color: var(--accent); }
    @media (max-width: 760px) {
      .field-grid, .provider-grid { grid-template-columns: 1fr; }
      table {
        display: block;
        max-width: 100%;
        overflow-x: auto;
        white-space: nowrap;
        -webkit-overflow-scrolling: touch;
      }
    }
    /* ── Appearance section ─────────────────────────────── */
    .theme-grid {
      align-items: flex-start;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 4px;
    }
    .theme-swatch {
      align-items: center;
      background: none;
      border: 2px solid transparent;
      border-radius: 14px;
      color: inherit;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      font: inherit;
      gap: 6px;
      min-height: 0;
      padding: 8px 10px;
      transition: border-color 120ms ease-out;
    }
    .theme-swatch:hover { background: none; border-color: var(--line); }
    .theme-swatch:hover:not(:disabled) { background: none; }
    .theme-swatch.active { border-color: var(--accent); }
    .theme-swatch.active:hover { background: none; }
    .swatch-dot {
      border: 1.5px solid rgba(0,0,0,0.10);
      border-radius: 50%;
      display: block;
      height: 26px;
      width: 26px;
    }
    .swatch-label {
      color: var(--muted);
      font-size: 0.75rem;
      font-weight: 500;
      text-align: center;
    }
    .theme-custom-row {
      align-items: center;
      display: none;
      gap: 10px;
      margin-top: 8px;
    }
    .theme-custom-row label { color: var(--muted); font-size: 0.86rem; width: auto; }
    .theme-custom-row input[type="color"] {
      border: var(--border-default);
      border-radius: 8px;
      cursor: pointer;
      height: 34px;
      padding: 2px 3px;
      width: 52px;
    }
    html[data-scheme="dark"] .swatch-dot { border-color: rgba(255,255,255,0.10); }
    """
    body = f"""
    <section id="appearance">
      <h2>Appearance</h2>
      <p>Choose a colour theme. Changes take effect immediately and are saved in your browser.</p>
      <div class="theme-grid" id="at-theme-swatches" role="group" aria-label="Choose colour theme">
        <button class="theme-swatch" type="button" data-theme="default" aria-pressed="false">
          <span class="swatch-dot" style="background:#4F67E4"></span>
          <span class="swatch-label">Default</span>
        </button>
        <button class="theme-swatch" type="button" data-theme="ocean" aria-pressed="false">
          <span class="swatch-dot" style="background:#0B9090"></span>
          <span class="swatch-label">Ocean</span>
        </button>
        <button class="theme-swatch" type="button" data-theme="forest" aria-pressed="false">
          <span class="swatch-dot" style="background:#2E7D46"></span>
          <span class="swatch-label">Forest</span>
        </button>
        <button class="theme-swatch" type="button" data-theme="rose" aria-pressed="false">
          <span class="swatch-dot" style="background:#C0395D"></span>
          <span class="swatch-label">Rose</span>
        </button>
        <button class="theme-swatch" type="button" data-theme="amber" aria-pressed="false">
          <span class="swatch-dot" style="background:#B06000"></span>
          <span class="swatch-label">Amber</span>
        </button>
        <button class="theme-swatch" type="button" data-theme="slate" aria-pressed="false">
          <span class="swatch-dot" style="background:#3D5475"></span>
          <span class="swatch-label">Slate</span>
        </button>
        <button class="theme-swatch" type="button" data-theme="violet" aria-pressed="false">
          <span class="swatch-dot" style="background:#7C4DDB"></span>
          <span class="swatch-label">Violet</span>
        </button>
        <button class="theme-swatch" type="button" data-theme="custom" aria-pressed="false">
          <span class="swatch-dot" style="background:conic-gradient(#ff6b6b,#ffd93d,#6bcb77,#4d96ff,#c77dff,#ff6b6b)"></span>
          <span class="swatch-label">Custom</span>
        </button>
      </div>
      <div class="theme-custom-row" id="at-theme-custom-row">
        <label for="at-theme-custom-color">Accent colour</label>
        <input type="color" id="at-theme-custom-color" value="#4F67E4">
      </div>
    </section>
    {new_token_block}
    <section id="profile">
      <h2>Job-search profile</h2>
      <p>This manual profile gives future Focus, Inbox, search, and AI guidance a stable record of what you are trying to achieve.</p>
      <form method="post" action="/settings/profile">
        <div class="field-grid">
          <label>
            Target roles
            <textarea name="target_roles" placeholder="One role or theme per line">{profile_values["target_roles"]}</textarea>
          </label>
          <label>
            Target locations
            <textarea name="target_locations" placeholder="Cities, countries, remote regions">{profile_values["target_locations"]}</textarea>
          </label>
          <label>
            Remote preference
            <input name="remote_preference" value="{profile_values["remote_preference"]}" maxlength="100" placeholder="remote, hybrid, onsite, flexible">
          </label>
          <label>
            Urgency
            <input name="urgency" value="{profile_values["urgency"]}" maxlength="100" placeholder="actively searching, open, exploratory">
          </label>
          <label>
            Salary minimum
            <input name="salary_min" value="{profile_values["salary_min"]}" inputmode="decimal" placeholder="90000">
          </label>
          <label>
            Salary maximum
            <input name="salary_max" value="{profile_values["salary_max"]}" inputmode="decimal" placeholder="120000">
          </label>
          <label>
            Salary currency
            <input name="salary_currency" value="{profile_values["salary_currency"]}" maxlength="3" placeholder="GBP">
          </label>
        </div>
        <label>
          Preferred industries
          <textarea name="preferred_industries" placeholder="Industries, sectors, company types">{profile_values["preferred_industries"]}</textarea>
        </label>
        <label>
          Industries to avoid
          <textarea name="excluded_industries" placeholder="Industries, sectors, company types to de-prioritise">{profile_values["excluded_industries"]}</textarea>
        </label>
        <label>
          Constraints
          <textarea name="constraints" placeholder="Travel, notice period, working hours, sponsorship, deal breakers">{profile_values["constraints"]}</textarea>
        </label>
        <label>
          Positioning notes
          <textarea name="positioning_notes" placeholder="Strengths, preferred narrative, differentiators, reusable application themes">{profile_values["positioning_notes"]}</textarea>
        </label>
        <button type="submit">Save profile</button>
      </form>
    </section>
    <section id="ai">
      <h2>AI readiness</h2>
      <p>AI is optional, inspectable, and disabled by default. Provider setup should stay explicit and easy to audit. Only one provider is active at a time.</p>
      <details class="inline-help">
        <summary>API key setup help</summary>
        <div class="inline-help-body">
          <p>OpenAI, Gemini, and Anthropic use API keys from their developer platforms. Consumer chat subscriptions do not configure this app by themselves.</p>
          <p>For OpenAI, create an API key in the platform dashboard. For Gemini, create a Gemini API key in Google AI Studio. The key is stored encrypted at rest and only used for explicit generation actions.</p>
          <div class="inline-help-links">
            <a href="{OPENAI_BILLING_HELP_URL}" target="_blank" rel="noreferrer">ChatGPT vs API billing</a>
            <a href="{OPENAI_API_QUICKSTART_URL}" target="_blank" rel="noreferrer">OpenAI API key quickstart</a>
            <a href="{GEMINI_API_KEYS_URL}" target="_blank" rel="noreferrer">Gemini API key setup</a>
            <a href="{GEMINI_API_OVERVIEW_URL}" target="_blank" rel="noreferrer">Gemini API overview</a>
            <a href="{ANTHROPIC_API_OVERVIEW_URL}" target="_blank" rel="noreferrer">Anthropic API overview</a>
            <a href="/help#ai-setup">Open AI setup help</a>
          </div>
        </div>
      </details>
      {_ai_provider_setup_forms(ai_provider_settings or [])}
      <table>
        <thead>
          <tr>
            <th>Provider</th>
            <th>Model</th>
            <th>Base URL</th>
            <th>API key</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {ai_provider_rows}
        </tbody>
      </table>
    </section>
    <section>
      <h2>Create API token</h2>
      <p>Use capture tokens for the browser bookmarklet and future extensions.</p>
      <form method="post" action="/settings/api-tokens">
        <label>
          Token name
          <input name="name" value="Browser bookmarklet" maxlength="200" required>
        </label>
        <input type="hidden" name="scope" value="{CAPTURE_JOBS_SCOPE}">
        <button type="submit">Create capture token</button>
      </form>
    </section>
    <section>
      <h2>API tokens</h2>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Scopes</th>
            <th>Status</th>
            <th>Created</th>
            <th>Last used</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {token_rows}
        </tbody>
      </table>
    </section>
    """
    return HTMLResponse(
        render_shell_page(
            user,
            page_title="Settings",
            title="Settings",
            subtitle="",
            active="settings",
            body=body,
            container="standard",
            extra_styles=extra_styles,
            scripts=_appearance_js(),
        )
    )


def admin_page(
    user: User,
    *,
    user_count: int,
    job_count: int,
    token_count: int,
    api_tokens: list[ApiToken],
    new_token: str | None = None,
) -> HTMLResponse:
    token_rows = "\n".join(_admin_api_token_row(api_token) for api_token in api_tokens)
    if not token_rows:
        token_rows = '<tr><td colspan="7" class="muted">No API tokens yet.</td></tr>'
    new_token_block = (
        f"""
        <section class="secret">
          <h2>New admin token</h2>
          <p>This secret is shown once. Paste it into Capture setup now.</p>
          <input value="{escape(new_token, quote=True)}" readonly>
          <p><a href="/api/capture/bookmarklet">Open Capture setup</a></p>
        </section>
        """
        if new_token
        else ""
    )
    extra_styles = compact_content_rhythm_styles() + """
    input {
      border: 0.5px solid var(--line);
      border-radius: 10px;
      font: inherit;
      padding: 8px 10px;
      width: 100%;
    }
    button {
      background: var(--accent);
      border: 0;
      border-radius: 10px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 500;
      min-height: 38px;
      padding: 0 14px;
    }
    button:hover { background: var(--accent-strong); }
    button.secondary {
      background: #ffffff;
      border: 0.5px solid var(--line);
      color: #a43d2b;
    }
    .stats {
      align-items: stretch;
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .stat {
      border: 0.5px solid var(--line);
      border-radius: 10px;
      padding: 14px;
    }
    .stat strong {
      display: block;
      font-size: 1.6rem;
      line-height: 1;
      margin-bottom: 6px;
    }
    .link-list {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    table { border-collapse: collapse; width: 100%; }
    th, td {
      border-bottom: 0.5px solid var(--line);
      padding: 10px 8px;
      text-align: left;
      vertical-align: middle;
    }
    th { color: var(--muted); font-size: 0.82rem; text-transform: uppercase; }
    td form { margin: 0; }
    .secret { border-color: var(--accent); }
    @media (max-width: 760px) {
      .stats, .link-list { grid-template-columns: 1fr; }
      table {
        display: block;
        max-width: 100%;
        overflow-x: auto;
        white-space: nowrap;
        -webkit-overflow-scrolling: touch;
      }
    }
    """
    body = f"""
    {new_token_block}
    <section>
      <h2>System</h2>
      <div class="stats">
        <div class="stat"><strong>{user_count}</strong><span class="muted">Users</span></div>
        <div class="stat"><strong>{job_count}</strong><span class="muted">Jobs</span></div>
        <div class="stat"><strong>{token_count}</strong><span class="muted">API tokens</span></div>
      </div>
      <p>Environment: {escape(settings.app_env)} · Auth: {escape(settings.auth_mode)}</p>
      <p>Public URL: {escape(str(settings.public_base_url))}</p>
      <p>Storage: {escape(settings.storage_backend)} at {escape(settings.local_storage_path)}</p>
    </section>
    <section>
      <h2>Admin Tasks</h2>
      <div class="link-list">
        <a href="/api/capture/bookmarklet">Capture setup</a>
        <a href="/health">Health check</a>
        <a href="/docs">Open API documentation</a>
        <a href="/admin/backup">Download backup</a>
      </div>
    </section>
    <section>
      <h2>Create Capture Token</h2>
      <p>Create a scoped capture token owned by your admin account.</p>
      <form method="post" action="/admin/api-tokens">
        <label>
          Token name
          <input name="name" value="Browser capture" maxlength="200" required>
        </label>
        <input type="hidden" name="scope" value="{CAPTURE_JOBS_SCOPE}">
        <button type="submit">Create capture token</button>
      </form>
    </section>
    <section>
      <h2>API Tokens</h2>
      <table>
        <thead>
          <tr>
            <th>Owner</th>
            <th>Name</th>
            <th>Scopes</th>
            <th>Status</th>
            <th>Created</th>
            <th>Last used</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {token_rows}
        </tbody>
      </table>
    </section>
    """
    return HTMLResponse(
        render_shell_page(
            user,
            page_title="Admin",
            title="Admin",
            subtitle="Self-hosted operations and capture token management",
            active="admin",
            body=body,
            kicker="Operations",
            container="standard",
            extra_styles=extra_styles,
        )
    )


def help_page(user: User) -> HTMLResponse:
    extra_styles = compact_content_rhythm_styles() + """
    .help-links {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .help-links a {
      border: 0.5px solid var(--line);
      border-radius: 10px;
      color: var(--accent-strong);
      display: inline-flex;
      min-height: 34px;
      padding: 0 10px;
      text-decoration: none;
      align-items: center;
    }
    .help-grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .help-grid section {
      margin-bottom: 0;
    }
    .checklist {
      display: grid;
      gap: 6px;
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .checklist li {
      border-left: 3px solid var(--line);
      padding-left: 8px;
    }
    .kbd-table {
      border-collapse: collapse;
      font-size: 0.88rem;
      width: 100%;
    }
    .kbd-table th {
      color: var(--muted);
      font-size: 0.76rem;
      font-weight: 500;
      letter-spacing: 0.05em;
      padding: 0 10px 6px 0;
      text-align: left;
      text-transform: uppercase;
    }
    .kbd-table td {
      border-top: var(--border-default);
      padding: 7px 10px 7px 0;
      vertical-align: middle;
    }
    .kbd-table td:first-child { white-space: nowrap; }
    kbd {
      background: var(--surface-soft);
      border: var(--border-default);
      border-radius: 5px;
      box-shadow: 0 1px 0 var(--line);
      display: inline-block;
      font-family: inherit;
      font-size: 0.8rem;
      font-weight: 600;
      line-height: 1;
      padding: 3px 7px;
    }
    .next-steps {
      display: grid;
      gap: 8px;
      list-style: decimal;
      margin: 0;
      padding-left: 20px;
    }
    @media (max-width: 760px) {
      .help-grid { grid-template-columns: 1fr; }
    }
    """
    admin_section = (
        """
    <section>
      <h2>Admin Operations</h2>
      <p>Admin tools are for self-hosted maintenance and recovery. They do not change ownership boundaries.</p>
      <ul class="checklist">
        <li><strong>Admin page:</strong> review users, jobs, token counts, and create scoped capture tokens.</li>
        <li><strong>Backup:</strong> use the Admin backup action for portable restore material.</li>
        <li><strong>API Docs:</strong> available from your user menu and at <a href="/docs">/docs</a>.</li>
      </ul>
    </section>
        """
        if user.is_admin
        else ""
    )
    body = f"""
    <section>
      <h2>What This App Is For</h2>
      <p>Application Tracker is a private, local-first workspace for managing opportunities from capture through outcomes. It is not board-first: Focus, Inbox, and Job Workspace are the primary working surfaces.</p>
      <div class="help-links">
        <a href="/focus">Open Focus</a>
        <a href="/inbox">Open Inbox</a>
        <a href="/board">Open Board</a>
        <a href="/artefacts">Open Artefacts</a>
        <a href="/api/capture/bookmarklet">Open Capture Setup</a>
        <a href="/settings">Open Settings</a>
      </div>
    </section>
    <section>
      <h2>Daily Workflow</h2>
      <ol class="next-steps">
        <li>Start in Focus and work top-to-bottom on due follow-ups and stale items.</li>
        <li>Review Inbox candidates, then accept into workflow or dismiss.</li>
        <li>Use Job Workspace to execute one opportunity: next action, edits, artefacts, notes, timeline.</li>
        <li>Use Board for stage movement and visual scanning of active work.</li>
        <li>Capture new jobs as you browse, and keep Settings profile current to improve triage relevance.</li>
      </ol>
    </section>
    <div class="help-grid">
      <section>
        <h2>Focus</h2>
        <p>Focus answers what needs attention now.</p>
        <ul class="checklist">
          <li>Use this as your default landing page each session.</li>
          <li>Follow direct links into the relevant job workspace.</li>
          <li>If Focus is sparse, capture more opportunities or complete profile settings.</li>
        </ul>
      </section>
      <section>
        <h2>Inbox</h2>
        <p>Inbox is for unreviewed intake, including pasted email opportunities.</p>
        <ul class="checklist">
          <li>Review extracted fields before acceptance.</li>
          <li>Accept moves items into active workflow states.</li>
          <li>Dismiss keeps low-quality intake out of active views.</li>
        </ul>
      </section>
      <section>
        <h2>Board</h2>
        <p>Board is a workflow lens over active work, not the strategic center.</p>
        <ul class="checklist">
          <li>Use drag or quick actions to update stage status.</li>
          <li>Switch workflows to narrow attention (Prospects, In Progress, Outcomes).</li>
          <li>Open Job Workspace for details and execution.</li>
        </ul>
      </section>
      <section>
        <h2>Job Workspace</h2>
        <p>Job Workspace is where execution happens for one opportunity.</p>
        <ul class="checklist">
          <li>Maintain title, source links, description, and status in one place.</li>
          <li>Track applications and interviews without leaving the page.</li>
          <li>Use notes and timeline as your private learning record.</li>
        </ul>
      </section>
      <section>
        <h2>Artefacts</h2>
        <p>Artefacts are reusable working assets tied to outcomes.</p>
        <ul class="checklist">
          <li>Store resumes, cover letters, and prep files for reuse across jobs.</li>
          <li>Keep purpose/version metadata updated.</li>
          <li>Attach existing artefacts from Job Workspace when preparing submissions.</li>
        </ul>
      </section>
      <section>
        <h2>Capture</h2>
        <p>Capture brings external jobs into Inbox with provenance.</p>
        <ul class="checklist">
          <li>Use the bookmarklet/token flow for browser intake.</li>
          <li>Use Paste email from Inbox when a recruiter or job-board email is relevant.</li>
          <li>Review all captured items in Inbox before active workflow entry.</li>
        </ul>
      </section>
    </div>
    <section>
      <h2>Settings And Privacy</h2>
      <ul class="checklist">
        <li><strong>Profile:</strong> update target roles, locations, and constraints to guide decisions.</li>
        <li><strong>AI providers:</strong> optional and inspectable. No hidden job/profile mutations.</li>
        <li><strong>API tokens:</strong> create only what you need and revoke unused tokens promptly.</li>
      </ul>
    </section>
    <section id="ai-setup">
      <h2>AI setup</h2>
      <p>AI generation uses provider API access, not a consumer chat subscription sign-in.</p>
      <ul class="checklist">
        <li><strong>OpenAI:</strong> ChatGPT and the OpenAI API are separate billing systems. Create an API key in the OpenAI platform dashboard before enabling the provider here.</li>
        <li><strong>Gemini:</strong> create a Gemini API key in Google AI Studio, then enable the Gemini provider here.</li>
        <li><strong>Anthropic:</strong> create an API key from the Anthropic Console before enabling that provider.</li>
        <li><strong>Local/OpenAI-compatible:</strong> use the base URL and model name for your local endpoint.</li>
        <li><strong>Storage:</strong> provider API keys are stored encrypted at rest and are never re-displayed in full.</li>
        <li><strong>Current product rule:</strong> AI stays user-triggered, visible, and non-mutating.</li>
      </ul>
      <div class="help-links">
        <a href="{OPENAI_BILLING_HELP_URL}" target="_blank" rel="noreferrer">OpenAI billing help</a>
        <a href="{OPENAI_API_QUICKSTART_URL}" target="_blank" rel="noreferrer">OpenAI API quickstart</a>
        <a href="{GEMINI_API_KEYS_URL}" target="_blank" rel="noreferrer">Gemini API key setup</a>
        <a href="{GEMINI_API_OVERVIEW_URL}" target="_blank" rel="noreferrer">Gemini API overview</a>
        <a href="{ANTHROPIC_API_OVERVIEW_URL}" target="_blank" rel="noreferrer">Anthropic API overview</a>
        <a href="/settings#ai">Open AI settings</a>
      </div>
    </section>
    <section id="keyboard-shortcuts">
      <h2>Keyboard shortcuts</h2>
      <p>Shortcuts are active when you are not typing in a field. Press <kbd>g</kbd> then a second key to jump to a page.</p>
      <table class="kbd-table">
        <thead>
          <tr>
            <th>Key(s)</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          <tr><td><kbd>g</kbd> <kbd>f</kbd></td><td>Go to Focus</td></tr>
          <tr><td><kbd>g</kbd> <kbd>i</kbd></td><td>Go to Inbox</td></tr>
          <tr><td><kbd>g</kbd> <kbd>b</kbd></td><td>Go to Board</td></tr>
          <tr><td><kbd>g</kbd> <kbd>h</kbd></td><td>Go to Help</td></tr>
          <tr><td><kbd>n</kbd></td><td>New job</td></tr>
          <tr><td><kbd>?</kbd></td><td>Open Help</td></tr>
          <tr><td><kbd>Ctrl</kbd> <kbd>Enter</kbd> / <kbd>⌘</kbd> <kbd>Enter</kbd></td><td>Submit the current form</td></tr>
        </tbody>
      </table>
    </section>
    {admin_section}
    """
    return HTMLResponse(
        render_shell_page(
            user,
            page_title="Help",
            title="Help",
            subtitle="How to use Application Tracker",
            active=None,
            body=body,
            kicker="Product guide",
            container="standard",
            extra_styles=extra_styles,
        )
    )


def _list_user_api_tokens(db: DbSession, user: User) -> list[ApiToken]:
    return list(
        db.scalars(
            select(ApiToken)
            .where(ApiToken.owner_user_id == user.id)
            .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
        ).all()
    )


def _list_all_api_tokens(db: DbSession) -> list[ApiToken]:
    return list(
        db.scalars(
            select(ApiToken).join(ApiToken.owner).order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
        ).all()
    )


def _has_users(db: DbSession) -> bool:
    return db.scalar(select(User.id).limit(1)) is not None


def _sqlite_database_path() -> Path | None:
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).resolve()


def _write_sqlite_backup(archive: ZipFile) -> None:
    database_path = _sqlite_database_path()
    if database_path is None or not database_path.exists():
        archive.writestr("database/README.txt", "SQLite database file was not available for backup.\n")
        return

    with tempfile.NamedTemporaryFile(suffix=".db") as backup_file:
        source = sqlite3.connect(database_path)
        destination = sqlite3.connect(backup_file.name)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        archive.write(backup_file.name, "database/app.db")


def _write_local_artefacts_backup(archive: ZipFile) -> None:
    if settings.storage_backend != "local":
        archive.writestr(
            "artefacts/README.txt",
            f"Artefact backup is not supported for storage backend: {settings.storage_backend}.\n",
        )
        return

    storage_root = Path(settings.local_storage_path)
    if not storage_root.exists():
        archive.writestr("artefacts/README.txt", "No local artefact storage directory exists yet.\n")
        return

    for path in sorted(storage_root.rglob("*")):
        if not path.is_file():
            continue
        archive.write(path, Path("artefacts") / path.relative_to(storage_root))


def _build_backup_zip() -> bytes:
    buffer = BytesIO()
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "MANIFEST.txt",
            "\n".join(
                [
                    "Application Tracker backup",
                    f"Created at: {timestamp}",
                    f"Database URL: {settings.database_url}",
                    f"Storage backend: {settings.storage_backend}",
                    f"Local storage path: {settings.local_storage_path}",
                    "",
                ]
            ),
        )
        _write_sqlite_backup(archive)
        _write_local_artefacts_backup(archive)
    buffer.seek(0)
    return buffer.getvalue()


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_form() -> HTMLResponse:
    return login_page()


@router.get("/setup", response_class=HTMLResponse, response_model=None, include_in_schema=False)
def setup_form(db: DbSession) -> HTMLResponse | RedirectResponse:
    if _has_users(db):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return setup_page()


@router.post("/setup", response_class=HTMLResponse, response_model=None, include_in_schema=False)
def setup_form_submit(
    request: Request,
    db: DbSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
) -> HTMLResponse | RedirectResponse:
    if _has_users(db):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Application is already set up")
    if password != confirm_password:
        return setup_page(error="Passwords do not match")
    if len(password) < 8:
        return setup_page(error="Password must be at least 8 characters")

    try:
        user = create_local_user(
            db,
            email=email,
            password=password,
            display_name=display_name.strip() or None,
            is_admin=True,
        )
    except UserAlreadyExists:
        return setup_page(error="A user already exists")

    response = RedirectResponse(url="/focus", status_code=status.HTTP_303_SEE_OTHER)
    create_login_session(db, user, request=request, response=response)
    return response


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
def settings_form(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    return settings_page(
        current_user,
        _list_user_api_tokens(db, current_user),
        profile=get_user_profile(db, current_user),
        ai_provider_settings=list_user_ai_provider_settings(db, current_user),
    )


@router.get("/help", response_class=HTMLResponse, include_in_schema=False)
def help_view(
    current_user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    return help_page(current_user)


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_form(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> HTMLResponse:
    user_count = db.scalar(select(func.count(User.id))) or 0
    job_count = db.scalar(select(func.count(Job.id))) or 0
    token_count = db.scalar(select(func.count(ApiToken.id))) or 0
    return admin_page(
        current_user,
        user_count=user_count,
        job_count=job_count,
        token_count=token_count,
        api_tokens=_list_all_api_tokens(db),
    )


@router.post("/admin/api-tokens", response_class=HTMLResponse, include_in_schema=False)
def admin_create_api_token(
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
    name: Annotated[str, Form()] = "Browser capture",
    scope: Annotated[str, Form()] = CAPTURE_JOBS_SCOPE,
) -> HTMLResponse:
    token_name = name.strip()
    if not token_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token name is required")
    try:
        raw_token, _ = create_user_api_token(
            db,
            current_user,
            name=token_name,
            scopes=[scope],
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    user_count = db.scalar(select(func.count(User.id))) or 0
    job_count = db.scalar(select(func.count(Job.id))) or 0
    token_count = db.scalar(select(func.count(ApiToken.id))) or 0
    return admin_page(
        current_user,
        user_count=user_count,
        job_count=job_count,
        token_count=token_count,
        api_tokens=_list_all_api_tokens(db),
        new_token=raw_token,
    )


@router.post("/admin/api-tokens/{token_uuid}/revoke", include_in_schema=False)
def admin_revoke_api_token(
    token_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> RedirectResponse:
    _ = current_user
    api_token = db.scalar(select(ApiToken).where(ApiToken.uuid == token_uuid))
    if api_token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API token not found")
    if api_token.revoked_at is None:
        api_token.revoked_at = datetime.now(UTC)
    db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/backup", include_in_schema=False)
def admin_backup(
    current_user: Annotated[User, Depends(require_admin)],
) -> Response:
    _ = current_user
    backup = _build_backup_zip()
    filename = f'application-tracker-backup-{datetime.now(UTC).strftime("%Y%m%d-%H%M%S")}.zip'
    return Response(
        backup,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/settings/api-tokens", response_class=HTMLResponse, include_in_schema=False)
def settings_create_api_token(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    name: Annotated[str, Form()] = "Browser bookmarklet",
    scope: Annotated[str, Form()] = CAPTURE_JOBS_SCOPE,
) -> HTMLResponse:
    token_name = name.strip()
    if not token_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token name is required")
    try:
        raw_token, _ = create_user_api_token(
            db,
            current_user,
            name=token_name,
            scopes=[scope],
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    return settings_page(
        current_user,
        _list_user_api_tokens(db, current_user),
        profile=get_user_profile(db, current_user),
        ai_provider_settings=list_user_ai_provider_settings(db, current_user),
        new_token=raw_token,
    )


@router.post("/settings/ai-provider", include_in_schema=False)
def settings_update_ai_provider(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    provider: Annotated[str, Form()] = "openai",
    label: Annotated[str, Form()] = "",
    base_url: Annotated[str, Form()] = "",
    model_name: Annotated[str, Form()] = "",
    api_key: Annotated[str, Form()] = "",
    is_enabled: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    try:
        upsert_ai_provider_setting(
            db,
            current_user,
            provider=provider,
            label=label,
            base_url=base_url,
            model_name=model_name,
            api_key=api_key,
            is_enabled=is_enabled == "true",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(url="/settings#ai", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/settings/ai-provider/discover", include_in_schema=False)
def settings_discover_ai_provider_models(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    provider: Annotated[str, Form()] = "openai",
    label: Annotated[str, Form()] = "",
    base_url: Annotated[str, Form()] = "",
    api_key: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        save_ai_provider_key_and_discover_models(
            db,
            current_user,
            provider=provider,
            label=label,
            base_url=base_url,
            api_key=api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(url="/settings#ai", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/settings/ai-provider/enable", include_in_schema=False)
def settings_enable_ai_provider_model(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    provider: Annotated[str, Form()] = "openai",
    model_name: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        enable_ai_provider_model(
            db,
            current_user,
            provider=provider,
            model_name=model_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(url="/settings#ai", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/settings/profile", include_in_schema=False)
def settings_update_profile(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    target_roles: Annotated[str, Form()] = "",
    target_locations: Annotated[str, Form()] = "",
    remote_preference: Annotated[str, Form()] = "",
    salary_min: Annotated[str, Form()] = "",
    salary_max: Annotated[str, Form()] = "",
    salary_currency: Annotated[str, Form()] = "",
    preferred_industries: Annotated[str, Form()] = "",
    excluded_industries: Annotated[str, Form()] = "",
    constraints: Annotated[str, Form()] = "",
    urgency: Annotated[str, Form()] = "",
    positioning_notes: Annotated[str, Form()] = "",
) -> RedirectResponse:
    def clean(value: str) -> str | None:
        stripped = value.strip()
        return stripped or None

    def clean_decimal(value: str) -> Decimal | None:
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return Decimal(stripped)
        except InvalidOperation as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Salary values must be valid numbers",
            ) from exc

    profile = get_or_create_user_profile(db, current_user)
    profile.target_roles = clean(target_roles)
    profile.target_locations = clean(target_locations)
    profile.remote_preference = clean(remote_preference)
    profile.salary_min = clean_decimal(salary_min)
    profile.salary_max = clean_decimal(salary_max)
    profile.salary_currency = clean(salary_currency.upper())
    profile.preferred_industries = clean(preferred_industries)
    profile.excluded_industries = clean(excluded_industries)
    profile.constraints = clean(constraints)
    profile.urgency = clean(urgency)
    profile.positioning_notes = clean(positioning_notes)
    db.commit()
    return RedirectResponse(url="/settings#profile", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/settings/api-tokens/{token_uuid}/revoke", include_in_schema=False)
def settings_revoke_api_token(
    token_uuid: str,
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> RedirectResponse:
    if not revoke_user_api_token(db, current_user, token_uuid):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API token not found")

    db.commit()
    return RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/login",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
def login_form_submit(
    request: Request,
    db: DbSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    try:
        user = authenticate_local_user(db, email, password)
    except HTTPException:
        return login_page(error="Invalid email or password")

    response = RedirectResponse(url="/focus", status_code=status.HTTP_303_SEE_OTHER)
    create_login_session(db, user, request=request, response=response)
    return response


@router.post("/logout", include_in_schema=False)
def logout_form(
    db: DbSession,
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    if session_token:
        revoke_session(db, session_token)
        db.commit()

    response.delete_cookie(settings.session_cookie_name, path="/")
    clear_csrf_cookie(response)
    return response
