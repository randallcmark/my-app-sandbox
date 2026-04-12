from datetime import datetime
from html import escape
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from app.api.deps import DbSession, get_current_user, require_admin
from app.api.routes.auth import authenticate_local_user, create_login_session
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

router = APIRouter(tags=["session-ui"])


def _value(value: object) -> str:
    if value is None or value == "":
        return "Not set"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def login_page(*, error: str | None = None) -> HTMLResponse:
    error_block = f'<p class="error">{escape(error)}</p>' if error else ""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login - Application Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f6f7f9;
      --panel: #ffffff;
      --ink: #1d1f24;
      --muted: #626b76;
      --line: #d7dce2;
      --accent: #147a5c;
      --accent-strong: #0f5d47;
      --error: #a43d2b;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      align-items: center;
      background: var(--page);
      color: var(--ink);
      display: grid;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      min-height: 100vh;
      padding: 24px;
    }}

    main {{
      margin: 0 auto;
      max-width: 420px;
      width: 100%;
    }}

    h1 {{
      font-size: 2rem;
      line-height: 1.1;
      margin: 0 0 8px;
    }}

    p {{
      color: var(--muted);
      line-height: 1.45;
      margin: 0 0 20px;
    }}

    form {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 14px;
      padding: 20px;
    }}

    label {{
      display: grid;
      font-weight: 700;
      gap: 6px;
    }}

    input {{
      border: 1px solid var(--line);
      border-radius: 8px;
      font: inherit;
      min-height: 42px;
      padding: 8px 10px;
      width: 100%;
    }}

    button {{
      background: var(--accent);
      border: 0;
      border-radius: 8px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      min-height: 44px;
    }}

    button:hover {{
      background: var(--accent-strong);
    }}

    .error {{
      color: var(--error);
      font-weight: 700;
      margin: 0;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Application Tracker</h1>
    <p>Sign in to manage your job search.</p>
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
  </main>
</body>
</html>"""
    )


def setup_page(*, error: str | None = None) -> HTMLResponse:
    error_block = f'<p class="error">{escape(error)}</p>' if error else ""
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Set Up - Application Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f6f7f9;
      --panel: #ffffff;
      --ink: #1d1f24;
      --muted: #626b76;
      --line: #d7dce2;
      --accent: #147a5c;
      --accent-strong: #0f5d47;
      --error: #a43d2b;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      align-items: center;
      background: var(--page);
      color: var(--ink);
      display: grid;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      min-height: 100vh;
      padding: 24px;
    }}

    main {{
      margin: 0 auto;
      max-width: 480px;
      width: 100%;
    }}

    h1 {{
      font-size: 2rem;
      line-height: 1.1;
      margin: 0 0 8px;
    }}

    p {{
      color: var(--muted);
      line-height: 1.45;
      margin: 0 0 20px;
    }}

    form {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 14px;
      padding: 20px;
    }}

    label {{
      display: grid;
      font-weight: 700;
      gap: 6px;
    }}

    input {{
      border: 1px solid var(--line);
      border-radius: 8px;
      font: inherit;
      min-height: 42px;
      padding: 8px 10px;
      width: 100%;
    }}

    button {{
      background: var(--accent);
      border: 0;
      border-radius: 8px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      min-height: 44px;
    }}

    button:hover {{
      background: var(--accent-strong);
    }}

    .error {{
      color: var(--error);
      font-weight: 700;
      margin: 0;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Set up Application Tracker</h1>
    <p>Create the first local administrator. This page is only available before any users exist.</p>
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
  </main>
</body>
</html>"""
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


def settings_page(user: User, api_tokens: list[ApiToken], *, new_token: str | None = None) -> HTMLResponse:
    token_rows = "\n".join(_api_token_row(api_token) for api_token in api_tokens)
    if not token_rows:
        token_rows = '<tr><td colspan="6" class="muted">No API tokens yet.</td></tr>'
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
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Settings - Application Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f6f7f9;
      --panel: #ffffff;
      --ink: #1d1f24;
      --muted: #626b76;
      --line: #d7dce2;
      --accent: #147a5c;
      --accent-strong: #0f5d47;
      --warn: #a43d2b;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      background: var(--page);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
    }}

    main {{
      margin: 0 auto;
      max-width: 980px;
      min-height: 100vh;
      padding: 24px;
    }}

    .topbar {{
      align-items: center;
      display: flex;
      gap: 16px;
      justify-content: space-between;
      margin-bottom: 24px;
    }}

    h1, h2, p {{
      margin: 0;
    }}

    h1 {{
      font-size: 2rem;
      line-height: 1.1;
    }}

    h2 {{
      font-size: 1.1rem;
    }}

    p,
    .muted {{
      color: var(--muted);
    }}

    a {{
      color: var(--accent-strong);
      font-weight: 700;
    }}

    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 14px;
      margin-bottom: 16px;
      padding: 18px;
    }}

    label {{
      display: grid;
      font-weight: 700;
      gap: 6px;
    }}

    input {{
      border: 1px solid var(--line);
      border-radius: 8px;
      font: inherit;
      padding: 8px 10px;
      width: 100%;
    }}

    button {{
      background: var(--accent);
      border: 0;
      border-radius: 8px;
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      min-height: 38px;
      padding: 0 14px;
    }}

    button:hover {{
      background: var(--accent-strong);
    }}

    button.secondary {{
      background: #ffffff;
      border: 1px solid var(--line);
      color: var(--warn);
    }}

    table {{
      border-collapse: collapse;
      width: 100%;
    }}

    th,
    td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      text-align: left;
      vertical-align: middle;
    }}

    th {{
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
    }}

    td form {{
      margin: 0;
    }}

    .secret {{
      border-color: var(--accent);
    }}

    @media (max-width: 760px) {{
      main {{
        padding: 16px;
      }}

      .topbar {{
        align-items: start;
        display: grid;
      }}

      table {{
        display: block;
        overflow-x: auto;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="topbar">
      <div>
        <h1>Settings</h1>
        <p>{escape(user.email)}</p>
      </div>
      <nav>
        {'<a href="/admin">Admin</a>' if user.is_admin else ""}
        <a href="/board">Board</a>
      </nav>
    </header>

    {new_token_block}

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
  </main>
</body>
</html>"""
    )


def admin_page(user: User, *, user_count: int, job_count: int, token_count: int) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Admin - Application Tracker</title>
  <style>
    :root {{
      color-scheme: light;
      --page: #f6f7f9;
      --panel: #ffffff;
      --ink: #1d1f24;
      --muted: #626b76;
      --line: #d7dce2;
      --accent: #147a5c;
      --accent-strong: #0f5d47;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      background: var(--page);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
    }}

    main {{
      margin: 0 auto;
      max-width: 980px;
      min-height: 100vh;
      padding: 24px;
    }}

    .topbar,
    nav,
    .stats {{
      align-items: center;
      display: flex;
      gap: 12px;
    }}

    .topbar {{
      justify-content: space-between;
      margin-bottom: 24px;
    }}

    h1, h2, p {{
      margin: 0;
    }}

    h1 {{
      font-size: 2rem;
      line-height: 1.1;
    }}

    h2 {{
      font-size: 1.1rem;
    }}

    p,
    .muted {{
      color: var(--muted);
    }}

    a {{
      color: var(--accent-strong);
      font-weight: 700;
    }}

    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 14px;
      margin-bottom: 16px;
      padding: 18px;
    }}

    .stats {{
      align-items: stretch;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}

    .stat {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}

    .stat strong {{
      display: block;
      font-size: 1.7rem;
      line-height: 1;
      margin-bottom: 6px;
    }}

    .link-list {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}

    @media (max-width: 760px) {{
      main {{
        padding: 16px;
      }}

      .topbar,
      nav,
      .stats,
      .link-list {{
        align-items: start;
        display: grid;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="topbar">
      <div>
        <h1>Admin</h1>
        <p>{escape(user.email)}</p>
      </div>
      <nav>
        <a href="/board">Board</a>
        <a href="/settings">Settings</a>
        <a href="/docs">API docs</a>
      </nav>
    </header>

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
        <a href="/settings">Create or revoke capture API tokens</a>
        <a href="/api/capture/bookmarklet">Capture setup</a>
        <a href="/health">Health check</a>
        <a href="/docs">Open API documentation</a>
      </div>
    </section>
  </main>
</body>
</html>"""
    )


def _list_user_api_tokens(db: DbSession, user: User) -> list[ApiToken]:
    return list(
        db.scalars(
            select(ApiToken)
            .where(ApiToken.owner_user_id == user.id)
            .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
        ).all()
    )


def _has_users(db: DbSession) -> bool:
    return db.scalar(select(User.id).limit(1)) is not None


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

    response = RedirectResponse(url="/board", status_code=status.HTTP_303_SEE_OTHER)
    create_login_session(db, user, request=request, response=response)
    return response


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
def settings_form(
    db: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    return settings_page(current_user, _list_user_api_tokens(db, current_user))


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
    return settings_page(current_user, _list_user_api_tokens(db, current_user), new_token=raw_token)


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

    response = RedirectResponse(url="/board", status_code=status.HTTP_303_SEE_OTHER)
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
