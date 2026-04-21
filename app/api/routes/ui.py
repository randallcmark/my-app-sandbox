from html import escape
from typing import Literal

from app.db.models.user import User


NavLink = tuple[str, str, str]

PRIMARY_NAV: tuple[NavLink, ...] = (
    ("Focus", "/focus", "focus"),
    ("Inbox", "/inbox", "inbox"),
    ("Board", "/board", "board"),
)


def shell_token_styles() -> str:
    return """
    :root {
      color-scheme: light;
      --bg-start: #0f3b65;
      --bg-mid: #143f69;
      --bg-end: #edf2f6;
      --shell-bg: rgba(247, 249, 252, 0.88);
      --shell-line: rgba(255, 255, 255, 0.38);
      --surface: #ffffff;
      --surface-soft: #f7f9fc;
      --surface-muted: #f2f5f9;
      --panel: rgba(255, 255, 255, 0.95);
      --ink: #1f3447;
      --muted: #5d7085;
      --soft-text: #7e90a5;
      --line: #d7dee8;
      --line-soft: #e7edf3;
      --accent: #1e73d9;
      --accent-strong: #105ec0;
      --accent-soft: #edf5ff;
      --danger: #e25b4c;
      --danger-soft: rgba(226, 91, 76, 0.12);
      --amber: #e39b3d;
      --amber-soft: rgba(227, 155, 61, 0.14);
      --success: #3ba786;
      --success-soft: rgba(59, 167, 134, 0.14);
      --ai-bg: #e8efff;
      --ai-line: #c6d6f4;
      --shadow-xl: 0 28px 70px rgba(16, 34, 52, 0.20);
      --shadow-lg: 0 16px 40px rgba(16, 34, 52, 0.12);
      --shadow-md: 0 10px 24px rgba(16, 34, 52, 0.10);
      --shadow-sm: 0 2px 8px rgba(16, 34, 52, 0.08);
      --radius-shell: 22px;
      --radius-2xl: 18px;
      --radius-xl: 16px;
      --radius-lg: 14px;
      --radius-md: 12px;
      --radius-sm: 8px;
      --topbar-h: 78px;
      --content-gap: 22px;
      --main-pad: 28px;
      --font-stack: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    * {
      box-sizing: border-box;
    }

    html, body {
      min-height: 100%;
      margin: 0;
    }

    body {
      background:
        radial-gradient(circle at top center, rgba(255,255,255,0.55), transparent 38%),
        linear-gradient(90deg, var(--bg-start), var(--bg-mid) 18%, #dbe6ef 58%, #f2f4f7 100%);
      color: var(--ink);
      font-family: var(--font-stack);
      overflow-y: scroll;
      scrollbar-gutter: stable;
    }

    a {
      color: var(--accent-strong);
      text-decoration: none;
    }

    .scenic-backdrop {
      position: fixed;
      inset: auto 0 0 0;
      height: 38vh;
      background:
        linear-gradient(to top, rgba(21, 40, 34, 0.55), transparent 80%),
        radial-gradient(110% 90% at 10% 100%, rgba(31, 59, 42, 0.65), transparent 38%),
        radial-gradient(90% 80% at 40% 100%, rgba(67, 92, 58, 0.45), transparent 42%),
        radial-gradient(90% 80% at 75% 100%, rgba(87, 90, 54, 0.42), transparent 44%);
      filter: blur(1px);
      pointer-events: none;
    }

    .page-shell {
      min-height: 100vh;
      padding: 34px;
      position: relative;
      z-index: 1;
    }

    .app-window {
      background: var(--shell-bg);
      backdrop-filter: blur(14px);
      border: 1px solid var(--shell-line);
      border-radius: var(--radius-shell);
      box-shadow: var(--shadow-xl);
      margin: 0 auto;
      min-height: calc(100vh - 68px);
      overflow: hidden;
      width: min(1410px, calc(100vw - 68px));
    }

    .app-window.auth-window {
      max-width: 620px;
      min-height: 0;
      width: min(620px, calc(100vw - 68px));
    }

    .app-topbar {
      align-items: center;
      background: rgba(255,255,255,0.78);
      border-bottom: 1px solid var(--line);
      display: grid;
      gap: 20px;
      grid-template-columns: minmax(0, 1fr) minmax(0, clamp(180px, 28vw, 420px)) auto;
      min-height: var(--topbar-h);
      padding: 14px 18px 14px 18px;
    }

    .app-nav-left {
      align-items: center;
      display: flex;
      gap: 14px;
      min-width: 0;
    }

    .app-brand {
      align-items: center;
      color: var(--ink);
      display: inline-flex;
      gap: 10px;
      font-size: 0.88rem;
      font-weight: 700;
      min-width: 0;
      white-space: nowrap;
    }

    .app-brand-mark {
      border-radius: 8px;
      box-shadow: var(--shadow-sm);
      display: block;
      height: 24px;
      width: 24px;
    }

    .app-nav {
      align-items: center;
      display: flex;
      gap: 18px;
      min-width: 0;
      overflow-x: auto;
      padding-bottom: 2px;
      -webkit-overflow-scrolling: touch;
    }

    .app-nav a {
      border-radius: 10px;
      color: var(--muted);
      display: inline-flex;
      font-size: 0.98rem;
      font-weight: 600;
      min-height: 42px;
      padding: 0 12px;
      position: relative;
      white-space: nowrap;
      align-items: center;
    }

    .app-nav a.active {
      color: var(--ink);
      font-weight: 800;
    }

    .app-nav a.active::after {
      background: var(--accent);
      border-radius: 999px;
      bottom: -15px;
      content: "";
      height: 3px;
      left: 12px;
      position: absolute;
      right: 12px;
    }

    .goal-chip {
      align-items: center;
      background: rgba(255,255,255,0.78);
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      display: inline-flex;
      gap: 8px;
      justify-self: end;
      max-width: 100%;
      min-height: 40px;
      min-width: 0;
      overflow: hidden;
      padding: 0 14px;
      box-shadow: var(--shadow-sm);
    }

    .goal-chip strong {
      color: var(--ink);
      font-weight: 800;
    }

    .goal-chip span,
    .goal-chip strong {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .goal-chip-label {
      flex: 0 0 auto;
    }

    .goal-chip-primary {
      flex: 1 1 auto;
    }

    .goal-chip-secondary,
    .goal-chip-tertiary {
      flex: 0 0 auto;
    }

    .goal-chip-sep {
      color: var(--soft-text);
      flex: 0 0 auto;
    }

    .goal-chip[data-collapse="tertiary"] .goal-chip-tertiary,
    .goal-chip[data-collapse="tertiary"] .goal-chip-sep.tertiary {
      display: none;
    }

    .goal-chip[data-collapse="secondary"] .goal-chip-secondary,
    .goal-chip[data-collapse="secondary"] .goal-chip-tertiary,
    .goal-chip[data-collapse="secondary"] .goal-chip-sep.secondary,
    .goal-chip[data-collapse="secondary"] .goal-chip-sep.tertiary {
      display: none;
    }

    .topbar-actions {
      align-items: center;
      display: flex;
      gap: 10px;
      justify-self: end;
    }

    .button,
    .btn,
    button,
    .secondary,
    .ghost,
    .icon-btn,
    .user-menu > summary {
      align-items: center;
      border-radius: var(--radius-md);
      display: inline-flex;
      font: inherit;
      font-weight: 700;
      justify-content: center;
      min-height: 40px;
      padding: 0 16px;
    }

    .button,
    .btn,
    button {
      background: linear-gradient(180deg, #2a81e7, var(--accent));
      border: 1px solid #1b6fce;
      box-shadow: var(--shadow-sm);
      color: #ffffff;
      cursor: pointer;
    }

    .button.secondary,
    .btn.secondary,
    .secondary,
    button.secondary {
      background: rgba(255,255,255,0.78);
      border: 1px solid var(--line);
      box-shadow: var(--shadow-sm);
      color: var(--ink);
    }

    .ghost,
    button.ghost {
      background: transparent;
      border: 1px solid var(--line);
      color: var(--danger);
    }

    .icon-btn {
      background: rgba(255,255,255,0.78);
      border: 1px solid var(--line);
      box-shadow: var(--shadow-sm);
      color: var(--soft-text);
      min-width: 40px;
      padding: 0;
      position: relative;
    }

    .icon-badge {
      align-items: center;
      background: var(--danger);
      border: 2px solid #ffffff;
      border-radius: 999px;
      color: #ffffff;
      display: inline-flex;
      font-size: 0.68rem;
      font-weight: 800;
      height: 18px;
      justify-content: center;
      min-width: 18px;
      padding: 0 4px;
      position: absolute;
      right: -2px;
      top: -3px;
    }

    .user-menu {
      position: relative;
    }

    .user-menu > summary {
      background: rgba(255,255,255,0.78);
      border: 1px solid var(--line);
      box-shadow: var(--shadow-sm);
      color: var(--ink);
      cursor: pointer;
      gap: 10px;
      list-style: none;
      padding: 0 12px;
      white-space: nowrap;
    }

    .user-menu > summary::-webkit-details-marker {
      display: none;
    }

    .avatar-mark {
      align-items: center;
      background: linear-gradient(180deg, #f0f3f8, #dfe7ef);
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--ink);
      display: inline-flex;
      font-size: 0.8rem;
      font-weight: 800;
      height: 28px;
      justify-content: center;
      width: 28px;
    }

    .user-menu-panel {
      background: rgba(255,255,255,0.96);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow-lg);
      display: grid;
      gap: 3px;
      margin-top: 8px;
      min-width: 240px;
      padding: 8px;
      position: absolute;
      right: 0;
      top: 100%;
      z-index: 50;
    }

    .user-menu-head {
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 600;
      margin: 0;
      padding: 6px 8px 8px;
    }

    .user-menu-panel a,
    .user-menu-panel button {
      background: transparent;
      border: 0;
      color: var(--ink);
      justify-content: flex-start;
      min-height: 36px;
      padding: 0 10px;
      width: 100%;
      box-shadow: none;
    }

    .user-menu-panel a:hover,
    .user-menu-panel button:hover {
      background: var(--surface-soft);
    }

    .user-menu-panel form {
      margin: 0;
    }

    .app-content-shell {
      display: grid;
      gap: var(--content-gap);
      min-height: calc(100vh - 68px - var(--topbar-h));
      padding: var(--main-pad);
    }

    .app-content-shell.standard {
      grid-template-columns: minmax(0, 1fr);
    }

    .app-content-shell.split,
    .app-content-shell.workspace {
      grid-template-columns: minmax(0, 1fr) minmax(300px, 380px);
    }

    .app-content-shell.kanban {
      grid-template-columns: minmax(0, 1fr);
    }

    .page-main,
    .page-aside {
      min-width: 0;
    }

    .page-main.narrow {
      max-width: 860px;
    }

    .page-main.standard,
    .page-main.split,
    .page-main.workspace {
      max-width: 100%;
    }

    .page-main.wide,
    .page-main.kanban {
      max-width: 1280px;
    }

    .page-aside {
      align-content: start;
      display: grid;
      gap: 18px;
    }

    .page-hero {
      display: grid;
      gap: 8px;
      margin-bottom: 18px;
    }

    .page-kicker {
      color: var(--soft-text);
      font-size: 0.84rem;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .page-hero h1 {
      font-size: clamp(1.95rem, 3vw, 2.55rem);
      font-weight: 800;
      letter-spacing: -0.02em;
      line-height: 1.05;
      margin: 0;
      overflow-wrap: anywhere;
    }

    .page-subtitle {
      color: var(--muted);
      font-size: 1.05rem;
      line-height: 1.5;
      margin: 0;
      max-width: 72ch;
    }

    .page-panel,
    section {
      background: var(--panel);
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-md);
      display: grid;
      gap: 12px;
      overflow: hidden;
      padding: 18px;
    }

    .page-panel.soft {
      background: rgba(255,255,255,0.84);
      box-shadow: var(--shadow-sm);
    }

    .page-panel.ai {
      background: linear-gradient(180deg, rgba(232, 239, 255, 0.98), rgba(241, 245, 255, 0.98));
      border-color: var(--ai-line);
    }

    .page-panel.emphasis {
      background: linear-gradient(135deg, #175eb6 0%, #1d74da 48%, #207fe7 72%, #1b66c4 100%);
      border-color: rgba(255,255,255,0.14);
      color: #ffffff;
    }

    .page-panel.emphasis a,
    .page-panel.emphasis p,
    .page-panel.emphasis h2 {
      color: inherit;
    }

    .panel-header {
      align-items: start;
      display: flex;
      gap: 12px;
      justify-content: space-between;
    }

    .panel-title {
      font-size: 1.08rem;
      font-weight: 800;
      line-height: 1.2;
      margin: 0;
    }

    .panel-copy,
    p,
    .muted {
      color: var(--muted);
      line-height: 1.5;
      margin: 0;
    }

    .panel-micro {
      color: var(--soft-text);
      font-size: 0.84rem;
      font-weight: 700;
      letter-spacing: 0.02em;
    }

    h2 {
      font-size: 1.12rem;
      font-weight: 800;
      letter-spacing: -0.01em;
      line-height: 1.2;
      margin: 0;
    }

    h3 {
      font-size: 0.98rem;
      font-weight: 800;
      margin: 0;
    }

    form {
      display: grid;
      gap: 8px;
    }

    label {
      display: grid;
      font-weight: 700;
      gap: 6px;
    }

    input,
    select,
    textarea {
      background: rgba(255,255,255,0.92);
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      color: var(--ink);
      font: inherit;
      min-height: 40px;
      padding: 10px 12px;
      width: 100%;
    }

    textarea {
      min-height: 120px;
      resize: vertical;
    }

    table {
      border-collapse: collapse;
      width: 100%;
    }

    th, td {
      border-bottom: 1px solid var(--line-soft);
      padding: 12px 10px;
      text-align: left;
      vertical-align: middle;
    }

    th {
      color: var(--soft-text);
      font-size: 0.78rem;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .metric-grid {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }

    .metric-card {
      background: rgba(255,255,255,0.86);
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-sm);
      display: grid;
      gap: 6px;
      padding: 16px;
    }

    .metric-card strong {
      font-size: 1.65rem;
      font-weight: 800;
      letter-spacing: -0.02em;
    }

    .metric-card span {
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.4;
    }

    .status-pill,
    .pill {
      align-items: center;
      background: var(--surface-muted);
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      display: inline-flex;
      font-size: 0.76rem;
      font-weight: 800;
      min-height: 28px;
      padding: 0 10px;
      white-space: nowrap;
    }

    .status-pill.accent,
    .pill.accent {
      background: var(--accent-soft);
      border-color: #c9daf3;
      color: var(--accent-strong);
    }

    .status-pill.success,
    .pill.success {
      background: var(--success-soft);
      border-color: rgba(59,167,134,0.28);
      color: #257a61;
    }

    .status-pill.warn,
    .pill.warn {
      background: var(--amber-soft);
      border-color: rgba(227,155,61,0.32);
      color: #b06c18;
    }

    .status-pill.danger,
    .pill.danger {
      background: var(--danger-soft);
      border-color: rgba(226,91,76,0.32);
      color: #c94d3e;
    }

    .card-list {
      display: grid;
      gap: 14px;
    }

    .elevated-card {
      background: linear-gradient(180deg, rgba(255,255,255,1), rgba(249,251,253,0.98));
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-md);
      display: grid;
      gap: 14px;
      overflow: hidden;
      padding: 18px;
    }

    .card-header {
      align-items: start;
      display: flex;
      gap: 12px;
      justify-content: space-between;
    }

    .card-header h2,
    .card-header h3 {
      margin: 0;
    }

    .split-row {
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .mobile-stack {
      display: grid;
      gap: 14px;
    }

    .auth-shell {
      padding: 28px;
    }

    .auth-panel {
      background: rgba(255,255,255,0.94);
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-2xl);
      box-shadow: var(--shadow-lg);
      display: grid;
      gap: 18px;
      padding: 24px;
    }

    .error {
      color: #bb4538;
      font-weight: 700;
      margin: 0;
    }

    @media (max-width: 1280px) {
      .app-content-shell.split,
      .app-content-shell.workspace {
        grid-template-columns: minmax(0, 1fr) minmax(280px, 340px);
      }
    }

    @media (max-width: 1120px) {
      .goal-chip {
        max-width: 320px;
      }

      .app-content-shell.split,
      .app-content-shell.workspace {
        grid-template-columns: 1fr;
      }

      .page-aside {
        order: -1;
      }

      .metric-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }

    @media (max-width: 860px) {
      .page-shell {
        padding: 16px;
      }

      .app-window,
      .app-window.auth-window {
        width: calc(100vw - 32px);
      }

      .app-topbar {
        grid-template-columns: 1fr;
        min-height: 0;
      }

      .app-nav-left,
      .topbar-actions {
        flex-wrap: wrap;
        justify-self: start;
      }

      .goal-chip {
        display: none;
      }

      .app-nav a.active::after {
        bottom: -4px;
      }

      .app-content-shell {
        padding: 18px;
      }

      .metric-grid,
      .split-row {
        grid-template-columns: 1fr;
      }
    }

    """


def app_shell_styles() -> str:
    return ""


def compact_content_rhythm_styles() -> str:
    return """
    section { gap: 12px; }
    h2 { font-size: 1.08rem; }
    p, .muted { line-height: 1.5; }
    """


def render_public_shell_page(
    *,
    page_title: str,
    title: str,
    subtitle: str,
    body: str,
    extra_styles: str = "",
    scripts: str = "",
) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(page_title)} - Application Tracker</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="shortcut icon" href="/favicon.ico">
  <style>
    {shell_token_styles()}
    {extra_styles}
  </style>
</head>
<body>
  <div class="scenic-backdrop" aria-hidden="true"></div>
  <main class="page-shell">
    <section class="app-window auth-window">
      <div class="auth-shell">
        <div class="page-hero">
          <p class="page-kicker">Application Tracker</p>
          <h1>{escape(title)}</h1>
          <p class="page-subtitle">{escape(subtitle)}</p>
        </div>
        {body}
      </div>
    </section>
  </main>
  {scripts}
</body>
</html>"""


def render_shell_page(
    user: User,
    *,
    page_title: str,
    title: str,
    subtitle: str,
    body: str,
    active: str | None = None,
    actions: tuple[NavLink, ...] = (),
    container: Literal["narrow", "standard", "wide", "split", "workspace", "kanban"] = "standard",
    extra_styles: str = "",
    scripts: str = "",
    aside: str | None = None,
    goal: str | None = None,
    kicker: str | None = None,
) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(page_title)} - Application Tracker</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="shortcut icon" href="/favicon.ico">
  <style>
    {shell_token_styles()}
    {extra_styles}
  </style>
</head>
<body>
  <div class="scenic-backdrop" aria-hidden="true"></div>
  <main class="page-shell">
    <div class="app-window" data-shell="rich-shell">
      {app_header(user, active=active, actions=actions, goal=goal)}
      <div class="app-content-shell {container}">
        <section class="page-main {container}">
          <div class="page-hero">
            {f'<p class="page-kicker">{escape(kicker)}</p>' if kicker else ""}
            <h1>{escape(title)}</h1>
            <p class="page-subtitle">{escape(subtitle)}</p>
          </div>
          {body}
        </section>
        {f'<aside class="page-aside">{aside}</aside>' if aside else ""}
      </div>
    </div>
  </main>
  <script>
    (() => {{
      const chip = document.querySelector(".goal-chip");
      if (!chip) {{
        return;
      }}
      const primary = chip.querySelector(".goal-chip-primary");
      if (!primary) {{
        return;
      }}

      function setCollapse(level) {{
        if (level) {{
          chip.dataset.collapse = level;
        }} else {{
          chip.removeAttribute("data-collapse");
        }}
      }}

      function titleIsTruncated() {{
        return primary.scrollWidth > primary.clientWidth + 1;
      }}

      function refreshGoalChip() {{
        setCollapse("");
        if (!titleIsTruncated()) {{
          return;
        }}

        setCollapse("tertiary");
        if (!titleIsTruncated()) {{
          return;
        }}

        setCollapse("secondary");
      }}

      window.addEventListener("resize", refreshGoalChip);
      refreshGoalChip();
    }})();
  </script>
  {scripts}
</body>
</html>"""


def app_header(
    user: User,
    *,
    active: str | None = None,
    actions: tuple[NavLink, ...] = (),
    goal: str | None = None,
) -> str:
    primary_links = "".join(_render_link(label, href, key, active=active) for label, href, key in PRIMARY_NAV)
    action_links = "".join(_render_action_link(label, href) for label, href, _key in actions)
    menu_links: list[str] = [_render_user_menu_link("User Settings", "/settings", active=active == "settings")]
    menu_links.append(_render_user_menu_link("Artefacts", "/artefacts", active=active == "artefacts"))
    menu_links.append(
        _render_user_menu_link("Capture Settings", "/api/capture/bookmarklet", active=active == "capture")
    )
    menu_links.append(_render_user_menu_link("Help", "/help", active=active == "help"))
    if user.is_admin:
        menu_links.append(_render_user_menu_link("Admin", "/admin", active=active == "admin"))
        menu_links.append(_render_user_menu_link("API Docs", "/docs", active=False))
    menu_links.append(
        """
        <form method="post" action="/logout">
          <button type="submit">Sign out</button>
        </form>
        """
    )
    goal_chip = f'<div class="goal-chip">{goal}</div>' if goal else ""

    return f"""
    <header class="app-topbar">
      <div class="app-nav-left">
        <a class="app-brand" href="/focus">
          <img class="app-brand-mark" src="/favicon.svg" alt="" aria-hidden="true">
          <span>Application Tracker</span>
        </a>
        <nav class="app-nav" aria-label="Primary navigation">
          {primary_links}
        </nav>
      </div>
      {goal_chip}
      <div class="topbar-actions">
        {action_links}
        <details class="user-menu">
          <summary aria-label="User menu">
            <span class="avatar-mark">{escape(_initials(user.email))}</span>
            <span>{escape(user.email)}</span>
            <span aria-hidden="true">⌄</span>
          </summary>
          <div class="user-menu-panel">
            <p class="user-menu-head">{escape(user.email)}</p>
            {"".join(menu_links)}
          </div>
        </details>
      </div>
    </header>
    """


def _initials(value: str) -> str:
    stem = value.split("@", 1)[0]
    parts = [part for part in stem.replace(".", " ").replace("-", " ").split() if part]
    if not parts:
        return "AT"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _render_link(label: str, href: str, key: str, *, active: str | None) -> str:
    class_attr = ' class="active"' if active == key else ""
    escaped_href = escape(href, quote=True).replace("&amp;", "&")
    return f'<a{class_attr} href="{escaped_href}">{escape(label)}</a>'


def _render_action_link(label: str, href: str) -> str:
    escaped_href = escape(href, quote=True).replace("&amp;", "&")
    return f'<a class="btn" href="{escaped_href}">{escape(label)}</a>'


def _render_user_menu_link(label: str, href: str, *, active: bool) -> str:
    class_attr = ' class="active"' if active else ""
    escaped_href = escape(href, quote=True).replace("&amp;", "&")
    return f'<a{class_attr} href="{escaped_href}">{escape(label)}</a>'
