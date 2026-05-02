# Application Tracker

A self-hosted, goal-aware job-search workspace for capturing roles, managing applications, and tracking progress through the job search process.

## Architecture

- **Framework**: FastAPI (Python 3.11)
- **Database**: PostgreSQL (Replit-managed, via `DATABASE_URL` secret)
- **ORM/Migrations**: SQLAlchemy 2 + Alembic
- **Server**: Uvicorn (dev) / Gunicorn (prod)
- **Auth**: Local session-based auth with argon2 password hashing
- **Storage**: Local file storage for artefacts (`./data/artefacts`)
- **Template rendering**: Server-side HTML via Python string concatenation in routes (no template engine)

## Project Structure

```
app/
  api/routes/     - FastAPI route handlers (focus, inbox, jobs, board, auth, etc.)
  auth/           - Session management, CSRF, tokens, password hashing
  core/config.py  - Pydantic settings (reads from environment variables)
  db/             - SQLAlchemy models and session management
  services/       - Business logic (jobs, artefacts, capture, AI, etc.)
  storage/        - File storage abstraction (local backend)
  assets/         - Static assets (favicon, etc.)
migrations/       - Alembic migration scripts
tests/            - pytest test suite
extensions/       - Firefox browser extension for job capture
docs/             - Product docs, UI handoff, API docs
```

## Design System

All styles are inline CSS in Python strings — no separate CSS files.

- **Entry point**: `shell_token_styles()` in `app/api/routes/ui.py` — loaded on every page
- **Design language**: "calm precision" — 400/500 weights only, 0.5px borders, no heavy shadows
- **Color tokens**: Slate Blue `#4F67E4` (accent), Sage Green `#2A8A58` (success), Amber `#E8A020`, Coral `#D64535` (danger)
- **Borders**: `var(--border-default)` = `0.5px solid rgba(0,0,0,0.10)` throughout
- **Radius**: `--radius-md: 10px`, `--radius-xl: 16px`, `--radius-2xl: 18px`
- **Buttons**: `padding: 6px 14px`, weight 500, solid accent bg, hover darkens, no gradient
- **Inputs**: `height: 36px`, 0.5px border, `--radius-md`
- **Typography**: h1 weight 500 at `clamp(1.65rem, 2.6vw, 2.1rem)`, h2/h3 weight 500
- **Status pills**: `padding: 3px 8px`, weight 500, 0.5px border, contextual color variants
- **Cards/panels**: `border: var(--border-default)`, no box-shadow (or `--shadow-sm` only)

### Per-surface CSS locations

| Surface | File | CSS location |
|---------|------|------|
| Shell/global | `app/api/routes/ui.py` | `shell_token_styles()` |
| Job workspace | `app/api/routes/job_detail.py` | `render_job_detail()` extra_styles (~line 2409) |
| Board/kanban | `app/api/routes/board.py` | `render_refined_board()` extra_styles |
| Focus | `app/api/routes/focus.py` | `render_focus()` extra_styles |
| Inbox | `app/api/routes/inbox.py` | `render_inbox()` extra_styles |

## Key Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (Replit-managed secret) |
| `SESSION_SECRET_KEY` | Secret for session signing |
| `APP_ENV` | `development` or `production` |
| `AUTH_MODE` | `local`, `oidc`, `mixed`, `proxy`, or `none` |
| `PUBLIC_BASE_URL` | Base URL for the app |
| `STORAGE_BACKEND` | `local` (default) |
| `LOCAL_STORAGE_PATH` | Path for artefact storage |

## Running the App

**Development:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```

**Production:**
```bash
gunicorn --bind 0.0.0.0:5000 --reuse-port --workers 2 -k uvicorn.workers.UvicornWorker app.main:app
```

## Database Setup

Migrations run automatically via Alembic:
```bash
python -m alembic upgrade head
```

13 migrations applied. Schema includes: users, jobs, communications, artefacts, interview_events, ai_outputs, user_profiles, competencies, competency_evidence.

## First Admin User

Visit `/setup` in the browser to create the first admin user (only available while no users exist).

## Workflow

The "Start application" workflow runs:
```
uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```
on port 5000.

## Section Workbench Pattern (Workstream 4 — complete)

Each Job Detail section follows the workbench contract:
1. **State bar** (`app-state-bar`) — pill + next-action title + hint + CTA buttons
2. **Content grid** (`workspace-two-up`) — what exists left, action form right
3. **Action forms** — collapsed in `<details class="workspace-form-disclosure">` disclosures

| Section | State bar | Primary content | Secondary actions |
|---------|-----------|-----------------|-------------------|
| Application | Status + contextual next-action hint | Role details two-up + submission history | Record submission, Advance status (in disclosures) |
| Interviews | Upcoming interview date/stage | `_interview_card()` list sorted by date | Schedule form (inline right) |
| Follow-Ups | Follow-up count | `_follow_up_card()` list (overdue highlighted) | Note form inline; blocker/return/started in disclosures |
| Tasks | — | Next-action + readiness checklist | Workflow actions, maintenance in disclosures |
| Notes | — | Add-note top; recent activity; journal collapsible | Provenance last |

CSS for all workbench patterns lives in `render_job_detail()` extra_styles in `job_detail.py`:
- `.app-state-bar`, `.app-state-context`, `.app-state-title`, `.app-state-cta`
- `.interview-card`, `.interview-card-list`, `.interview-card-head`
- `.follow-up-card`, `.follow-up-card-list`, `.follow-up-card-head`, `.follow-up-card.overdue`
- `.workspace-form-disclosure` (collapsible `<details>` forms)
- `.workspace-inline-link`

## Focus Surface — "No Next Action" Nudge (Workstream 5)

`_list_jobs_with_no_next_action()` in `focus.py` queries active jobs with no pending `Communication.follow_up_at` and surfaces them in a new "No next action" card on the Focus grid. The aside navigation pill links to `#no-next-action`.

## Notes

- Uses Replit-managed PostgreSQL (not SQLite as documented in original README)
- `psycopg2-binary` added as a dependency for PostgreSQL support
- All CSS is embedded in Python strings via `extra_styles` passed to `render_shell_page()`
- Board uses discrete `.refined-action` buttons with positive/negative/quiet intent classes
- Inbox cards use a footer row with `.inbox-act` compact action buttons (accept/review/dismiss)
- Job workspace uses a 3-column grid: left rail (nav), center (workbench), right rail (AI sidebar)
- Dead duplicate `_workspace_tools_section()` removed in Workstream 4 session 2
