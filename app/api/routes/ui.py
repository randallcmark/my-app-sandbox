from html import escape
from typing import Literal

from app.db.models.user import User


NavLink = tuple[str, str, str]
HeroVariant = Literal["standard", "workspace", "compact"]

PRIMARY_NAV: tuple[NavLink, ...] = (
    ("Focus", "/focus", "focus"),
    ("Inbox", "/inbox", "inbox"),
    ("Board", "/board", "board"),
)


def _icon(path: str, *, w: int = 15, h: int = 15) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 20 20" fill="none" stroke="currentColor" '
        f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{path}</svg>'
    )


ICON_PLUS = _icon(
    '<line x1="10" y1="3" x2="10" y2="17"/>'
    '<line x1="3" y1="10" x2="17" y2="10"/>',
    w=14, h=14,
)
ICON_FOCUS = _icon(
    '<circle cx="10" cy="10" r="2.5"/>'
    '<circle cx="10" cy="10" r="7.5"/>'
    '<line x1="10" y1="1" x2="10" y2="4.5"/>'
    '<line x1="10" y1="15.5" x2="10" y2="19"/>'
    '<line x1="1" y1="10" x2="4.5" y2="10"/>'
    '<line x1="15.5" y1="10" x2="19" y2="10"/>',
    w=14, h=14,
)
ICON_INBOX = _icon(
    '<path d="M3 10h4l1.5 2.5h3L13 10h4"/>'
    '<rect x="2" y="4" width="16" height="13" rx="1.5"/>',
    w=14, h=14,
)
ICON_BOARD = _icon(
    '<rect x="2" y="2" width="6" height="16" rx="1.5"/>'
    '<rect x="12" y="2" width="6" height="10" rx="1.5"/>',
    w=14, h=14,
)
ICON_SETTINGS = _icon(
    '<circle cx="10" cy="10" r="2.5"/>'
    '<path d="M10 1.5v2.5M10 16v2.5M1.5 10H4M16 10h2.5'
    'M4.4 4.4l1.8 1.8M13.8 13.8l1.8 1.8M4.4 15.6l1.8-1.8M13.8 6.2l1.8-1.8"/>',
    w=14, h=14,
)
ICON_USER = _icon(
    '<circle cx="10" cy="6.5" r="3.5"/>'
    '<path d="M2.5 18a7.5 7.5 0 0115 0"/>',
    w=14, h=14,
)
ICON_CHEVRON_DOWN = _icon(
    '<polyline points="5 8 10 13 15 8"/>',
    w=13, h=13,
)

_NAV_ICONS: dict[str, str] = {
    "focus": ICON_FOCUS,
    "inbox": ICON_INBOX,
    "board": ICON_BOARD,
}


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
      --accent: #4F67E4;
      --accent-strong: #2D3A9A;
      --accent-soft: #E8EBF8;
      --danger: #D64535;
      --danger-soft: #FDEFED;
      --amber: #E8A020;
      --amber-soft: #FDF3E6;
      --success: #2A8A58;
      --success-soft: #EAF4EE;
      --ai-bg: #E8EBF8;
      --ai-line: #C3CCF0;
      --border-width: 0.5px;
      --border-default: 0.5px solid rgba(0,0,0,0.10);
      --border-hover: 0.5px solid rgba(0,0,0,0.22);
      --transition-fast: 120ms ease-out;
      --transition-base: 200ms ease-out;
      --transition-slow: 350ms ease-out;
      --space-xs: 4px;
      --space-sm: 8px;
      --space-md: 12px;
      --space-lg: 16px;
      --space-xl: 24px;
      --space-2xl: 32px;
      --space-3xl: 48px;
      --shadow-xl: 0 28px 70px rgba(16, 34, 52, 0.20);
      --shadow-lg: 0 16px 40px rgba(16, 34, 52, 0.12);
      --shadow-md: 0 10px 24px rgba(16, 34, 52, 0.10);
      --shadow-sm: 0 2px 8px rgba(16, 34, 52, 0.08);
      --radius-shell: 22px;
      --radius-2xl: 18px;
      --radius-xl: 16px;
      --radius-lg: 14px;
      --radius-md: 10px;
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
      border-bottom: var(--border-default);
      display: flex;
      gap: 16px;
      min-height: var(--topbar-h);
      padding: 14px 18px;
    }

    .app-nav-left {
      align-items: center;
      display: flex;
      flex: 1 1 auto;
      gap: 12px;
      min-width: 0;
    }

    .app-brand {
      align-items: center;
      color: var(--ink);
      display: inline-flex;
      flex: 0 0 auto;
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
      flex: 1 1 auto;
      gap: 14px;
      min-width: 0;
      overflow: hidden;
      padding-bottom: 2px;
    }

    .app-nav a {
      align-items: center;
      border: 0.5px solid transparent;
      border-radius: 10px;
      color: var(--muted);
      display: inline-flex;
      flex: 0 0 auto;
      font-size: 0.9rem;
      font-weight: 400;
      gap: 6px;
      min-height: 34px;
      padding: 0 10px;
      transition: color var(--transition-fast), background var(--transition-fast);
      white-space: nowrap;
    }

    .app-nav a:hover:not(.active) {
      background: var(--surface-muted);
      color: var(--ink);
    }

    .app-nav a svg {
      flex-shrink: 0;
      opacity: 0.72;
      transition: opacity var(--transition-fast);
    }

    .app-nav a:hover svg,
    .app-nav a.active svg {
      opacity: 1;
    }

    .app-nav a.active {
      background: var(--accent-soft);
      border-color: #C3CCF0;
      color: var(--accent-strong);
      font-weight: 500;
    }

    .app-nav a.active::after {
      display: none;
    }

    .header-context {
      align-items: center;
      display: flex;
      flex: 0 1 360px;
      justify-content: end;
      min-width: 0;
    }

    .header-context-chip {
      align-items: center;
      background: rgba(255,255,255,0.78);
      border: var(--border-default);
      border-radius: 999px;
      color: var(--muted);
      display: inline-flex;
      gap: 8px;
      justify-self: end;
      max-width: 100%;
      min-height: 32px;
      min-width: 0;
      overflow: hidden;
      padding: 0 12px;
    }

    .header-context-chip strong {
      color: var(--ink);
      font-weight: 500;
    }

    .header-context-chip span,
    .header-context-chip strong {
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

    .app-topbar[data-chip-state="tertiary"] .goal-chip-tertiary,
    .app-topbar[data-chip-state="tertiary"] .goal-chip-sep.tertiary {
      display: none;
    }

    .app-topbar[data-chip-state="secondary"] .goal-chip-secondary,
    .app-topbar[data-chip-state="secondary"] .goal-chip-tertiary,
    .app-topbar[data-chip-state="secondary"] .goal-chip-sep.secondary,
    .app-topbar[data-chip-state="secondary"] .goal-chip-sep.tertiary {
      display: none;
    }

    .app-topbar[data-chip-state="hidden"] .header-context {
      display: none;
    }

    .topbar-actions {
      align-items: center;
      display: flex;
      flex: 0 0 auto;
      gap: 8px;
      justify-content: end;
      min-width: 0;
    }

    .shell-topbar-action {
      min-width: 112px;
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
      font-weight: 500;
      gap: 6px;
      justify-content: center;
      padding: 6px 14px;
      white-space: nowrap;
    }

    .button svg,
    .btn svg,
    button svg,
    .secondary svg,
    .ghost svg,
    .icon-btn svg {
      flex-shrink: 0;
    }

    .button,
    .btn,
    button {
      background: var(--accent);
      border: 0.5px solid var(--accent-strong);
      box-shadow: none;
      color: #ffffff;
      cursor: pointer;
      transition: background var(--transition-fast);
    }

    .button:hover,
    .btn:hover,
    button:hover:not(:disabled) {
      background: var(--accent-strong);
    }

    .button.secondary,
    .btn.secondary,
    .secondary,
    button.secondary {
      background: rgba(255,255,255,0.78);
      border: var(--border-default);
      box-shadow: none;
      color: var(--ink);
    }

    .ghost,
    button.ghost {
      background: transparent;
      border: var(--border-default);
      color: var(--danger);
    }

    .icon-btn {
      background: rgba(255,255,255,0.78);
      border: var(--border-default);
      color: var(--soft-text);
      min-width: 34px;
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
      min-width: 0;
      position: relative;
    }

    .user-menu > summary {
      background: rgba(255,255,255,0.78);
      border: var(--border-default);
      color: var(--ink);
      cursor: pointer;
      gap: 10px;
      list-style: none;
      max-width: 100%;
      min-width: 0;
      padding: 0 12px;
      white-space: nowrap;
    }

    .user-menu > summary span:not(.avatar-mark) {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .user-menu > summary::-webkit-details-marker {
      display: none;
    }

    .avatar-mark {
      align-items: center;
      background: linear-gradient(180deg, #f0f3f8, #dfe7ef);
      border: var(--border-default);
      border-radius: 999px;
      color: var(--ink);
      display: inline-flex;
      font-size: 0.8rem;
      font-weight: 500;
      height: 28px;
      justify-content: center;
      width: 28px;
    }

    .user-menu-panel {
      background: rgba(255,255,255,0.96);
      border: var(--border-default);
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
      font-size: 0.78rem;
      font-weight: 400;
      letter-spacing: 0.05em;
      margin: 0;
      padding: 6px 8px 8px;
      text-transform: uppercase;
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

    .page-main {
      align-content: start;
      display: grid;
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
      gap: 6px;
      margin-bottom: 18px;
    }

    .page-hero[data-hero-variant="compact"] {
      gap: 4px;
      margin-bottom: 14px;
    }

    .page-hero[data-hero-variant="workspace"] {
      gap: 8px;
      margin-bottom: 22px;
    }

    .page-kicker {
      color: var(--soft-text);
      font-size: 0.78rem;
      font-weight: 400;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .page-hero h1 {
      font-size: clamp(1.65rem, 2.6vw, 2.1rem);
      font-weight: 500;
      letter-spacing: -0.02em;
      line-height: 1.1;
      margin: 0;
      overflow-wrap: anywhere;
    }

    .page-subtitle {
      color: var(--muted);
      font-size: 1.05rem;
      line-height: 1.4;
      margin: 0;
      max-width: 72ch;
    }

    .page-panel {
      background: var(--panel);
      border: var(--border-default);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-sm);
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
      font-size: 1rem;
      font-weight: 500;
      line-height: 1.25;
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
      font-size: 0.76rem;
      font-weight: 400;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }

    h2 {
      font-size: 1.05rem;
      font-weight: 500;
      letter-spacing: -0.01em;
      line-height: 1.3;
      margin: 0;
    }

    h3 {
      font-size: 0.9rem;
      font-weight: 500;
      margin: 0;
    }

    form {
      display: grid;
      gap: 8px;
    }

    label {
      display: grid;
      font-size: 0.88rem;
      font-weight: 500;
      gap: 5px;
    }

    input,
    select,
    textarea {
      background: rgba(255,255,255,0.92);
      border: var(--border-default);
      border-radius: var(--radius-md);
      color: var(--ink);
      font: inherit;
      height: 36px;
      padding: 0 12px;
      width: 100%;
    }

    textarea {
      height: auto;
      min-height: 100px;
      padding: 8px 12px;
      resize: vertical;
    }

    table {
      border-collapse: collapse;
      width: 100%;
    }

    th, td {
      border-bottom: var(--border-default);
      padding: 10px;
      text-align: left;
      vertical-align: middle;
    }

    th {
      color: var(--soft-text);
      font-size: 0.76rem;
      font-weight: 500;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }

    .metric-grid {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }

    .metric-card {
      background: rgba(255,255,255,0.86);
      border: var(--border-default);
      border-radius: var(--radius-xl);
      box-shadow: none;
      display: grid;
      gap: 5px;
      padding: 14px 16px;
    }

    .metric-card strong {
      font-size: 1.5rem;
      font-weight: 500;
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
      border: var(--border-default);
      border-radius: 999px;
      color: var(--muted);
      display: inline-flex;
      font-size: 0.73rem;
      font-weight: 500;
      padding: 3px 8px;
      white-space: nowrap;
    }

    .status-pill.accent,
    .pill.accent {
      background: var(--accent-soft);
      border-color: #C3CCF0;
      color: var(--accent-strong);
    }

    .status-pill.success,
    .pill.success {
      background: var(--success-soft);
      border-color: #b6dfc5;
      color: var(--success);
    }

    .status-pill.warn,
    .pill.warn {
      background: var(--amber-soft);
      border-color: #f9d9a0;
      color: #8c5000;
    }

    .status-pill.danger,
    .pill.danger {
      background: var(--danger-soft);
      border-color: #f8c4be;
      color: var(--danger);
    }

    .card-list {
      display: grid;
      gap: 14px;
    }

    .elevated-card {
      background: #ffffff;
      border: var(--border-default);
      border-radius: var(--radius-xl);
      box-shadow: none;
      display: grid;
      gap: 14px;
      overflow: hidden;
      padding: 16px 18px;
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
      border: var(--border-default);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow-md);
      display: grid;
      gap: 16px;
      padding: 22px 24px;
    }

    .auth-panel button {
      width: 100%;
    }

    .error {
      color: var(--danger);
      font-weight: 500;
      margin: 0;
    }

    @media (max-width: 1280px) {
      .app-content-shell.split,
      .app-content-shell.workspace {
        grid-template-columns: minmax(0, 1fr) minmax(280px, 340px);
      }
    }

    @media (min-width: 861px) {
      html,
      body {
        height: 100%;
        overflow: hidden;
      }

      .page-shell {
        height: 100vh;
        overflow: hidden;
      }

      .app-window {
        display: flex;
        flex-direction: column;
        height: calc(100vh - 68px);
        min-height: 0;
      }

      .app-content-shell {
        flex: 1 1 auto;
        min-height: 0;
        overflow: hidden;
      }

      .page-main,
      .page-aside {
        min-height: 0;
        overflow: auto;
        overscroll-behavior: contain;
        scrollbar-gutter: stable;
      }

      .page-main {
        padding-right: 4px;
      }

      .page-aside {
        padding-right: 2px;
      }
    }

    @media (max-width: 1120px) {
      .header-context {
        flex-basis: 280px;
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
        align-items: start;
        flex-wrap: wrap;
        min-height: 0;
      }

      .app-nav-left,
      .topbar-actions {
        width: 100%;
      }

      .app-nav-left {
        flex-wrap: wrap;
      }

      .app-nav {
        overflow-x: auto;
        padding-bottom: 4px;
        -webkit-overflow-scrolling: touch;
      }

      .topbar-actions {
        justify-content: flex-start;
        flex-wrap: wrap;
        min-width: 0;
      }

      .shell-topbar-action {
        min-width: 0;
      }

      .topbar-actions .user-menu {
        flex: 1 1 190px;
      }

      .user-menu > summary {
        width: 100%;
      }

      .header-context {
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

    /* ── Preset colour themes ───────────────────────────────────────── */
    [data-theme="ocean"]  { --accent:#0B9090; --accent-strong:#065f5f; --accent-soft:#d6f2f2; --ai-bg:#d6f2f2; --ai-line:#8fd6d6; --bg-start:#083840; --bg-mid:#0a4550; }
    [data-theme="forest"] { --accent:#2E7D46; --accent-strong:#1a5230; --accent-soft:#e0f0e8; --ai-bg:#e0f0e8; --ai-line:#90c8a8; --bg-start:#183828; --bg-mid:#1c4030; }
    [data-theme="rose"]   { --accent:#C0395D; --accent-strong:#8a1f3f; --accent-soft:#fde8ef; --ai-bg:#fde8ef; --ai-line:#e8a0b8; --bg-start:#481220; --bg-mid:#58192c; }
    [data-theme="amber"]  { --accent:#B06000; --accent-strong:#7a4000; --accent-soft:#fde8c0; --ai-bg:#fde8c0; --ai-line:#d4a060; --bg-start:#3a2200; --bg-mid:#462a00; }
    [data-theme="slate"]  { --accent:#3D5475; --accent-strong:#243550; --accent-soft:#dde4ef; --ai-bg:#dde4ef; --ai-line:#9aaac0; --bg-start:#1c2a3c; --bg-mid:#22344a; }
    [data-theme="violet"] { --accent:#7C4DDB; --accent-strong:#5530a0; --accent-soft:#ede6fb; --ai-bg:#ede6fb; --ai-line:#b898e8; --bg-start:#281250; --bg-mid:#321a62; }

    /* ── Dark mode ──────────────────────────────────────────────────── */
    html[data-scheme="dark"] {
      color-scheme: dark;
      --shell-bg: rgba(12,20,34,0.97);
      --shell-line: rgba(255,255,255,0.08);
      --surface: #16243a;
      --surface-soft: #1a2c40;
      --surface-muted: #121e2e;
      --panel: rgba(18,28,44,0.99);
      --ink: #dce8f2;
      --muted: #7888a2;
      --soft-text: #4e647e;
      --line: rgba(255,255,255,0.07);
      --line-soft: rgba(255,255,255,0.04);
      --border-default: 0.5px solid rgba(255,255,255,0.07);
      --border-hover: 0.5px solid rgba(255,255,255,0.15);
      --success-soft: #0e2618;
      --danger-soft: #2c1012;
      --amber-soft: #281c06;
      --accent-soft: #18205c;
      --ai-bg: #18205c;
      --ai-line: #283488;
      --shadow-xl: 0 28px 70px rgba(0,0,0,0.55);
      --shadow-lg: 0 16px 40px rgba(0,0,0,0.42);
      --shadow-md: 0 10px 24px rgba(0,0,0,0.36);
      --shadow-sm: 0 2px 8px rgba(0,0,0,0.32);
    }
    html[data-scheme="dark"] body {
      background:
        radial-gradient(circle at top center, rgba(18,38,70,0.15), transparent 38%),
        linear-gradient(90deg, #07111e 0%, #0a1624 18%, #0e1a2c 58%, #0b1520 100%);
    }
    html[data-scheme="dark"] .scenic-backdrop {
      background:
        linear-gradient(to top, rgba(0,6,16,0.9), transparent 80%),
        radial-gradient(110% 90% at 10% 100%, rgba(0,10,30,0.95), transparent 38%);
    }
    html[data-scheme="dark"] .app-topbar {
      background: rgba(12,20,34,0.96);
      border-bottom-color: rgba(255,255,255,0.06);
    }
    html[data-scheme="dark"] .app-window {
      background: rgba(10,18,30,0.99);
      border-color: rgba(255,255,255,0.06);
    }
    html[data-scheme="dark"] .app-brand { color: var(--ink); }
    html[data-scheme="dark"] .app-nav a { color: var(--muted); }
    html[data-scheme="dark"] .app-nav a.active {
      background: rgba(79,103,228,0.18);
      border-color: rgba(79,103,228,0.35);
      color: #90a8ff;
    }
    html[data-scheme="dark"] .shell-topbar-action,
    html[data-scheme="dark"] .user-menu > summary,
    html[data-scheme="dark"] .icon-btn {
      background: rgba(22,34,52,0.92);
      border-color: rgba(255,255,255,0.09);
      color: var(--ink);
    }
    html[data-scheme="dark"] .secondary,
    html[data-scheme="dark"] button.secondary {
      background: rgba(22,34,52,0.92);
      border-color: rgba(255,255,255,0.09);
      color: var(--ink);
    }
    html[data-scheme="dark"] .avatar-mark {
      background: linear-gradient(180deg, #1c3050, #142440);
      border-color: rgba(255,255,255,0.09);
      color: var(--ink);
    }
    html[data-scheme="dark"] .user-menu-panel {
      background: rgba(16,26,42,0.99);
      border-color: rgba(255,255,255,0.09);
    }
    html[data-scheme="dark"] .user-menu-panel a,
    html[data-scheme="dark"] .user-menu-panel button { color: var(--ink); }
    html[data-scheme="dark"] .user-menu-panel a:hover,
    html[data-scheme="dark"] .user-menu-panel button:hover { background: rgba(255,255,255,0.06); }
    html[data-scheme="dark"] input,
    html[data-scheme="dark"] select,
    html[data-scheme="dark"] textarea {
      background: var(--surface-soft);
      border-color: rgba(255,255,255,0.08);
      color: var(--ink);
    }
    html[data-scheme="dark"] .page-panel { background: var(--panel); }
    html[data-scheme="dark"] .inbox-card,
    html[data-scheme="dark"] .focus-section,
    html[data-scheme="dark"] .aside-panel,
    html[data-scheme="dark"] .stat-card,
    html[data-scheme="dark"] .inbox-empty { background: var(--surface); }
    html[data-scheme="dark"] .section-head { border-bottom-color: rgba(255,255,255,0.06); }
    html[data-scheme="dark"] .focus-row { border-bottom-color: rgba(255,255,255,0.05); }
    html[data-scheme="dark"] .aside-nav-list li { border-bottom-color: rgba(255,255,255,0.05); }
    html[data-scheme="dark"] .focus-row:hover,
    html[data-scheme="dark"] .aside-nav-item:hover { background: rgba(255,255,255,0.04); }
    html[data-scheme="dark"] .header-context-chip {
      background: rgba(22,34,52,0.92);
      border-color: rgba(255,255,255,0.09);
    }

    /* ── Scheme toggle button ───────────────────────────────────────── */
    #at-scheme-btn {
      align-items: center;
      background: rgba(255,255,255,0.78);
      border: var(--border-default);
      border-radius: var(--radius-md);
      color: var(--soft-text);
      cursor: pointer;
      display: inline-flex;
      flex-shrink: 0;
      font: inherit;
      height: 34px;
      justify-content: center;
      padding: 0;
      transition: background var(--transition-fast), color var(--transition-fast), border-color var(--transition-fast);
      width: 34px;
    }
    #at-scheme-btn:hover { color: var(--ink); }
    html[data-scheme="dark"] #at-scheme-btn {
      background: rgba(22,34,52,0.92);
      border-color: rgba(255,255,255,0.09);
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
  {_fouc_script()}
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


def _fouc_script() -> str:
    return (
        "<script>try{"
        "var _s=localStorage.getItem('at-scheme')||'system',"
        "_p=window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';"
        "document.documentElement.dataset.scheme=_s==='system'?_p:_s;"
        "var _t=localStorage.getItem('at-theme')||'';"
        "if(_t&&_t!=='custom')document.documentElement.dataset.theme=_t;"
        "var _ca=localStorage.getItem('at-custom-accent')||'';"
        "if(_ca){"
        "document.documentElement.style.setProperty('--accent',_ca);"
        "document.documentElement.style.setProperty('--accent-strong',_ca);}"
        "}catch(e){}</script>"
    )


def _scheme_js() -> str:
    sun = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 20 20"'
        ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"'
        ' stroke-linejoin="round" aria-hidden="true">'
        '<circle cx="10" cy="10" r="3.5"/>'
        '<line x1="10" y1="1.5" x2="10" y2="4"/><line x1="10" y1="16" x2="10" y2="18.5"/>'
        '<line x1="1.5" y1="10" x2="4" y2="10"/><line x1="16" y1="10" x2="18.5" y2="10"/>'
        '<line x1="4.4" y1="4.4" x2="6.2" y2="6.2"/>'
        '<line x1="13.8" y1="13.8" x2="15.6" y2="15.6"/>'
        '<line x1="4.4" y1="15.6" x2="6.2" y2="13.8"/>'
        '<line x1="13.8" y1="6.2" x2="15.6" y2="4.4"/></svg>'
    )
    moon = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 20 20"'
        ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"'
        ' stroke-linejoin="round" aria-hidden="true">'
        '<path d="M16 10.8A7 7 0 019.2 4c0-.9.1-1.8.4-2.6A7.5 7.5 0 1018.6 10.4 7 7 0 0116 10.8z"/>'
        '</svg>'
    )
    monitor = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 20 20"'
        ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"'
        ' stroke-linejoin="round" aria-hidden="true">'
        '<rect x="2" y="3" width="16" height="11" rx="1.5"/>'
        '<line x1="7" y1="18" x2="13" y2="18"/>'
        '<line x1="10" y1="14" x2="10" y2="18"/></svg>'
    )
    return f"""  <script>
    (() => {{
      const ICONS = {{ light: `{sun}`, system: `{monitor}`, dark: `{moon}` }};
      const btn = document.getElementById('at-scheme-btn');
      if (!btn) return;
      function getScheme() {{ try {{ return localStorage.getItem('at-scheme') || 'system'; }} catch(e) {{ return 'system'; }} }}
      function setScheme(s) {{
        try {{ localStorage.setItem('at-scheme', s); }} catch(e) {{}}
        const pref = window.matchMedia && window.matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light';
        document.documentElement.dataset.scheme = s === 'system' ? pref : s;
        updateBtn(s);
      }}
      function updateBtn(s) {{
        btn.innerHTML = ICONS[s] || ICONS.system;
        const labels = {{ light: 'Light mode', system: 'System mode', dark: 'Dark mode' }};
        btn.title = labels[s] || 'Colour scheme';
        btn.setAttribute('aria-label', btn.title);
      }}
      btn.addEventListener('click', () => {{
        const order = ['light', 'system', 'dark'];
        const cur = getScheme();
        const next = order[(order.indexOf(cur) + 1) % order.length];
        setScheme(next);
      }});
      if (window.matchMedia) {{
        window.matchMedia('(prefers-color-scheme:dark)').addEventListener('change', e => {{
          if (getScheme() === 'system') document.documentElement.dataset.scheme = e.matches ? 'dark' : 'light';
        }});
      }}
      updateBtn(getScheme());
    }})();
  </script>"""


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
    hero_variant: HeroVariant = "standard",
    show_hero: bool = True,
) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {_fouc_script()}
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
          {render_page_hero(title=title, subtitle=subtitle, kicker=kicker, hero_variant=hero_variant) if show_hero else ""}
          {body}
        </section>
        {f'<aside class="page-aside">{aside}</aside>' if aside else ""}
      </div>
    </div>
  </main>
  <script>
    (() => {{
      const topbar = document.querySelector(".app-topbar");
      const nav = document.querySelector(".app-nav");
      if (!topbar || !nav) {{
        return;
      }}

      const chip = topbar.querySelector(".header-context-chip");
      if (!chip) {{
        topbar.dataset.chipState = "none";
        return;
      }}

      function setState(level) {{
        topbar.dataset.chipState = level;
      }}

      function navIsCompressed() {{
        return nav.scrollWidth > nav.clientWidth + 1;
      }}

      function refreshTopbar() {{
        setState("full");
        if (!navIsCompressed()) {{
          return;
        }}

        setState("tertiary");
        if (!navIsCompressed()) {{
          return;
        }}

        setState("secondary");
        if (!navIsCompressed()) {{
          return;
        }}

        setState("hidden");
      }}

      window.addEventListener("resize", refreshTopbar);
      requestAnimationFrame(refreshTopbar);
    }})();
  </script>
  <script>
    (() => {{
      const EDITABLE = new Set(["INPUT", "TEXTAREA", "SELECT"]);
      function inEditable() {{
        const el = document.activeElement;
        return el && (EDITABLE.has(el.tagName) || el.isContentEditable);
      }}
      let pending = null;
      document.addEventListener("keydown", e => {{
        if (e.altKey || e.ctrlKey || e.metaKey) {{
          if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {{
            const form = document.activeElement && document.activeElement.closest("form");
            if (form) {{
              const btn = form.querySelector('button[type="submit"]');
              if (btn) {{ btn.click(); }}
            }}
          }}
          return;
        }}
        if (inEditable()) return;
        const key = e.key;
        if (pending === "g") {{
          pending = null;
          const map = {{ f: "/focus", i: "/inbox", b: "/board", h: "/help" }};
          if (map[key]) {{ e.preventDefault(); location.href = map[key]; }}
          return;
        }}
        if (key === "g") {{ pending = "g"; setTimeout(() => {{ pending = null; }}, 1200); return; }}
        if (key === "n") {{ e.preventDefault(); location.href = "/jobs/new"; return; }}
        if (key === "?") {{ e.preventDefault(); location.href = "/help"; return; }}
      }});
    }})();
  </script>
  {_scheme_js()}
  {scripts}
</body>
</html>"""


def render_page_hero(*, title: str, subtitle: str, kicker: str | None = None, hero_variant: HeroVariant) -> str:
    return f"""
          <div class="page-hero" data-shell-hero="shared" data-hero-variant="{escape(hero_variant, quote=True)}">
            {f'<p class="page-kicker">{escape(kicker)}</p>' if kicker else ""}
            <h1>{escape(title)}</h1>
            {f'<p class="page-subtitle">{escape(subtitle)}</p>' if subtitle else ""}
          </div>
    """


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
        _render_user_menu_link(
            "Competency Evidence",
            "/competencies",
            active=active == "competencies",
        )
    )
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
    goal_slot = (
        f'<div class="header-context" data-shell-chip="context"><div class="header-context-chip">{goal}</div></div>'
        if goal
        else ""
    )
    chip_present = "true" if goal else "false"

    return f"""
    <header class="app-topbar" data-chip-state="full" data-has-chip="{chip_present}" data-shell-topbar="protected">
      <div class="app-nav-left" data-shell-cluster="nav">
        <a class="app-brand" href="/focus">
          <img class="app-brand-mark" src="/favicon.svg" alt="" aria-hidden="true">
          <span>Application Tracker</span>
        </a>
        <nav class="app-nav" aria-label="Primary navigation" data-shell-nav="primary">
          {primary_links}
        </nav>
      </div>
      {goal_slot}
      <div class="topbar-actions" data-shell-actions="primary">
        {action_links}
        <button id="at-scheme-btn" type="button" title="Colour scheme" aria-label="Toggle colour scheme"></button>
        <details class="user-menu">
          <summary class="shell-topbar-action" aria-label="User menu">
            <span class="avatar-mark">{escape(_initials(user.email))}</span>
            <span>{escape(user.email)}</span>
            {ICON_CHEVRON_DOWN}
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
    icon = _NAV_ICONS.get(key, "")
    return f'<a{class_attr} href="{escaped_href}">{icon}<span>{escape(label)}</span></a>'


def _render_action_link(label: str, href: str) -> str:
    escaped_href = escape(href, quote=True).replace("&amp;", "&")
    return f'<a class="btn shell-topbar-action" href="{escaped_href}">{ICON_PLUS}<span>{escape(label)}</span></a>'


def _render_user_menu_link(label: str, href: str, *, active: bool) -> str:
    class_attr = ' class="active"' if active else ""
    escaped_href = escape(href, quote=True).replace("&amp;", "&")
    return f'<a{class_attr} href="{escaped_href}">{escape(label)}</a>'
