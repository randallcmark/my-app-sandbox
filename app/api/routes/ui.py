from html import escape
from typing import Literal

from app.db.models.user import User


NavLink = tuple[str, str, str]

PRIMARY_NAV: tuple[NavLink, ...] = (
    ("Focus", "/focus", "focus"),
    ("Inbox", "/inbox", "inbox"),
    ("Board", "/board", "board"),
    ("Artefacts", "/artefacts", "artefacts"),
)


def app_shell_styles() -> str:
    return """
    .app-topbar {
      display: grid;
      gap: 12px;
      grid-template-columns: 1fr;
      margin-bottom: 24px;
    }

    .app-topbar-main {
      align-items: start;
      display: grid;
      gap: 12px;
      grid-template-columns: minmax(0, 1fr) auto;
    }

    .app-topbar-left {
      display: grid;
      gap: 4px;
      min-width: 0;
    }

    .app-topbar h1 {
      font-size: 1.5rem;
      font-weight: 500;
      letter-spacing: -0.01em;
      line-height: 1.3;
      margin: 0;
    }

    .app-brand {
      align-items: center;
      color: var(--accent-strong);
      display: inline-flex;
      gap: 8px;
      font-size: 0.82rem;
      font-weight: 500;
      margin: 0;
      text-decoration: none;
    }

    .app-brand-mark {
      border-radius: 6px;
      display: block;
      height: 18px;
      width: 18px;
    }

    .app-subtitle {
      color: var(--muted);
      display: block;
      line-height: 1.45;
      margin: 0;
      max-width: 80ch;
      overflow-wrap: anywhere;
    }

    .user-menu {
      position: relative;
    }

    .user-menu > summary {
      align-items: center;
      border: 0.5px solid var(--line);
      border-radius: 10px;
      cursor: pointer;
      display: inline-flex;
      font-size: 0.92rem;
      font-weight: 500;
      gap: 8px;
      list-style: none;
      min-height: 34px;
      padding: 0 10px;
      white-space: nowrap;
    }

    .user-menu > summary::-webkit-details-marker {
      display: none;
    }

    .user-menu[open] > summary {
      background: #ffffff;
      border-color: rgba(0, 0, 0, 0.22);
    }

    .user-menu-panel {
      background: #ffffff;
      border: 0.5px solid var(--line);
      border-radius: 10px;
      box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
      display: grid;
      gap: 2px;
      margin-top: 8px;
      min-width: 220px;
      padding: 6px;
      position: absolute;
      right: 0;
      top: 100%;
      z-index: 30;
    }

    .user-menu-head {
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 500;
      overflow-wrap: anywhere;
      padding: 6px 8px 8px;
    }

    .user-menu-panel a,
    .user-menu-panel button {
      align-items: center;
      background: transparent;
      border: 0;
      border-radius: 8px;
      color: var(--ink);
      cursor: pointer;
      display: inline-flex;
      font: inherit;
      font-size: 0.9rem;
      font-weight: 500;
      min-height: 34px;
      padding: 0 8px;
      text-decoration: none;
      text-align: left;
      width: 100%;
    }

    .user-menu-panel a:hover,
    .user-menu-panel button:hover {
      background: #f1f0ed;
    }

    .user-menu-panel form {
      margin: 0;
    }

    .app-nav {
      align-items: center;
      display: flex;
      flex-wrap: nowrap;
      gap: 8px;
      justify-content: start;
      max-width: 100%;
      overflow-x: auto;
      padding-bottom: 4px;
      -webkit-overflow-scrolling: touch;
    }

    .app-nav a,
    .app-nav button {
      align-items: center;
      background: transparent;
      border: 0.5px solid var(--line);
      border-radius: 10px;
      color: var(--accent-strong);
      cursor: pointer;
      display: inline-flex;
      font: inherit;
      font-size: 0.92rem;
      font-weight: 500;
      min-height: 34px;
      padding: 0 10px;
      text-decoration: none;
      white-space: nowrap;
    }

    .app-nav form {
      flex: 0 0 auto;
      margin: 0;
    }

    .app-nav a.active {
      background: #E8EBF8;
      border-color: #C3CCF0;
      color: var(--accent);
    }

    .app-nav a.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #ffffff;
    }

    .app-nav a:hover,
    .app-nav button:hover {
      border-color: rgba(0, 0, 0, 0.22);
    }

    @media (max-width: 760px) {
      .app-topbar-main {
        grid-template-columns: 1fr;
      }

      .user-menu {
        justify-self: start;
      }

      .app-subtitle {
        max-width: none;
      }
    }
    """


def compact_content_rhythm_styles() -> str:
    return """
    h2 { font-size: 1.05rem; font-weight: 500; margin: 0 0 8px; line-height: 1.25; }
    p, .muted { color: var(--muted); line-height: 1.35; margin: 0; }
    a { color: var(--accent-strong); font-weight: 500; }
    section {
      background: var(--panel);
      border: 0.5px solid var(--line);
      border-radius: 10px;
      display: grid;
      gap: 10px;
      margin-bottom: 12px;
      padding: 16px;
    }
    form { display: grid; gap: 4px; }
    label { display: grid; font-weight: 500; gap: 4px; }
    """


def render_shell_page(
    user: User,
    *,
    page_title: str,
    title: str,
    subtitle: str,
    body: str,
    active: str | None = None,
    actions: tuple[NavLink, ...] = (),
    container: Literal["narrow", "standard", "wide", "kanban"] = "standard",
    extra_styles: str = "",
    scripts: str = "",
) -> str:
    container_class = f"page-content {container}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(page_title)} - Application Tracker</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="shortcut icon" href="/favicon.ico">
  <style>
    :root {{
      color-scheme: light;
      --page: #f9f9f7;
      --panel: #ffffff;
      --ink: #111111;
      --muted: #5f5e5a;
      --line: rgba(0, 0, 0, 0.10);
      --accent: #4f67e4;
      --accent-strong: #2d3a9a;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      background: var(--page);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      overflow-y: scroll;
      scrollbar-gutter: stable;
    }}

    .page-shell {{
      margin: 0 auto;
      max-width: 1280px;
      min-height: 100vh;
      padding: 24px;
    }}

    .page-content {{
      width: 100%;
    }}

    .page-content.narrow {{
      max-width: 860px;
    }}

    .page-content.standard {{
      max-width: 1120px;
    }}

    .page-content.wide {{
      max-width: 1280px;
    }}

    .page-content.kanban {{
      max-width: 1280px;
    }}

    @media (max-width: 760px) {{
      .page-shell {{
        padding: 16px;
      }}
    }}
    {app_shell_styles()}
    {extra_styles}
  </style>
</head>
<body>
  <main class="page-shell">
    {app_header(user, title=title, subtitle=subtitle, active=active, actions=actions)}
    <section class="{container_class}">
      {body}
    </section>
  </main>
  {scripts}
</body>
</html>"""


def app_header(
    user: User,
    *,
    title: str,
    subtitle: str,
    active: str | None = None,
    actions: tuple[NavLink, ...] = (),
) -> str:
    links = _render_links(actions, active=active, primary=True)
    links.extend(_render_links(PRIMARY_NAV, active=active, primary=False))
    menu_links: list[str] = [_render_user_menu_link("User Settings", "/settings", active=active == "settings")]
    menu_links.append(
        _render_user_menu_link("Capture Settings", "/api/capture/bookmarklet", active=active == "capture")
    )
    if user.is_admin:
        menu_links.append(_render_user_menu_link("Admin", "/admin", active=active == "admin"))
        menu_links.append(_render_user_menu_link("API Docs", "/docs", active=False))
    menu_links.append(_render_user_menu_link("Help", "/help", active=False))
    menu_links.append(
        """
        <form method="post" action="/logout">
          <button type="submit">Sign out</button>
        </form>
        """
    )

    return f"""
    <header class="app-topbar">
      <div class="app-topbar-main">
        <div class="app-topbar-left">
        <a class="app-brand" href="/focus">
          <img class="app-brand-mark" src="/favicon.svg" alt="" aria-hidden="true">
          <span>Application Tracker</span>
        </a>
        <h1>{escape(title)}</h1>
        <p class="app-subtitle">{escape(subtitle)}</p>
        </div>
        <details class="user-menu">
          <summary aria-label="User menu">
            <span>{escape(user.email)}</span>
            <span aria-hidden="true">▾</span>
          </summary>
          <div class="user-menu-panel">
            <p class="user-menu-head">{escape(user.email)}</p>
            {"".join(menu_links)}
          </div>
        </details>
      </div>
      <nav class="app-nav" aria-label="Primary navigation">
        {"".join(links)}
      </nav>
    </header>
    """


def _render_links(
    links: tuple[NavLink, ...],
    *,
    active: str | None,
    primary: bool,
) -> list[str]:
    return [
        _render_link(label, href, key, active=active, primary=primary)
        for label, href, key in links
    ]


def _render_link(
    label: str,
    href: str,
    key: str,
    *,
    active: str | None,
    primary: bool,
) -> str:
    classes = []
    if primary:
        classes.append("primary")
    if active == key:
        classes.append("active")
    class_attr = f' class="{" ".join(classes)}"' if classes else ""
    escaped_href = escape(href, quote=True).replace("&amp;", "&")
    return f'<a{class_attr} href="{escaped_href}">{escape(label)}</a>'


def _render_user_menu_link(label: str, href: str, *, active: bool) -> str:
    class_attr = ' class="active"' if active else ""
    escaped_href = escape(href, quote=True).replace("&amp;", "&")
    return f'<a{class_attr} href="{escaped_href}">{escape(label)}</a>'
