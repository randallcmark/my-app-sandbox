# Application Tracker

Application Tracker is a self-hosted, goal-aware job-search workspace for capturing roles, deciding what deserves attention, preparing applications, managing artefacts, and learning what works during a job search.

This repository is a clean rebuild of the original personal MVP. The previous implementation has been preserved locally at:

```text
/Volumes/Media/Repository/application_tracker_old
```

## Product Direction

The target product is:

- container-first and easy to self-host;
- local-first, with SQLite and local storage defaults;
- optionally multi-user inside one contained deployment;
- organised around Focus, Inbox, Active Work, Job Workspace, Artefacts, Capture, and Admin surfaces;
- uses a shared application shell with primary workflow navigation and a user-context menu for
  settings, capture setup, help, sign-out, and admin tools;
- workflow-board friendly for stage management without making kanban the product centre;
- browser-capture friendly for importing jobs from job pages;
- profile-aware over time, with optional matching and writing assistance;
- private by default, with no required external services.

The board remains an important workflow view, especially for active applications, but the planned product direction is a focus-led workspace: the app should help the user understand what matters today, triage new opportunities, prepare strong applications, preserve context across external systems, and reuse artefacts intelligently.

The detailed staged roadmap lives in:

- `project_tracker/PUBLIC_SELF_HOSTED_ROADMAP.md`
- `docs/PRODUCT_VISION.md`
- `docs/DELIVERY_PLAN.md`

### Product strategy and design docs

For the current product framing, longer-term opportunity thinking, and UI handoff artifacts, see:

- `docs/product/application_tracker_product_doc_set_index.md`
- `docs/product/application_tracker_composite_product_vision.md`
- `docs/product/application_tracker_inbox_monitoring_decision_memo.md`
- `docs/ui/application_tracker_ui_mockup_inspectable.html`
- `docs/ui/handoff/README.md`

API token and browser capture examples live in:

- `docs/API_TOKENS_AND_CAPTURE.md`
- `docs/FIREFOX_EXTENSION.md`

Jobs API examples live in:

- `docs/JOBS_API.md`

User profile and intent notes live in:

- `docs/USER_PROFILE.md`

Focus surface notes live in:

- `docs/FOCUS.md`

Inbox notes live in:

- `docs/INBOX.md`

The visual design system lives in:

- `docs/design/DESIGN_SYSTEM.md`

Workflow board notes live in:

- `docs/KANBAN_BOARD.md`

Job detail page notes live in:

- `docs/JOB_DETAIL.md`

## Current State

This clean repo now contains a usable authenticated tracker:

- local login/logout and first admin bootstrap command;
- scoped API tokens for capture integrations;
- owner-scoped jobs API and browser capture endpoint;
- Focus home surface for due follow-ups, stale work, upcoming interviews, and recent prospects;
- Inbox review surface for captured jobs that need acceptance before active workflow views;
- shared server-rendered layout across the main authenticated pages, with a top-right user menu for
  User Settings, Capture Settings, Help, Sign out, and admin-only Admin/API Docs;
- built-in Help page with task-oriented guidance for the main workflow;
- manual job creation and editable job detail pages;
- workflow board views with drag/drop and a `Move to column` fallback;
- status-change timeline, notes, follow-up dates, applications, interviews, archive/unarchive;
- job-level artefact upload/download;
- stage-aging, stale-card, and follow-up indicators;
- Alembic migrations, Dockerfile, Docker Compose file, and pytest coverage.

The next implementation work should follow the refreshed delivery plan: mobile shell validation,
Inbox/provider-backed intake follow-ups, Job Workspace refinements, Artefact Library follow-ups,
embedded AI rendering, scheduler/worker support, and self-hosted operations.

## Local Development

Create a virtual environment and install development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run the API:

```bash
make run
```

Open the app:

```text
http://127.0.0.1:8000/login
```

If you prefer to call Uvicorn directly, use the virtualenv binary:

```bash
.venv/bin/uvicorn app.main:app --reload
```

Run tests:

```bash
make test
```

Run all local checks:

```bash
make check
```

### Rebuild A Broken Virtualenv

If imports fail with an `incompatible architecture` error from `pydantic_core`, the virtualenv
contains binary wheels from a different Mac CPU architecture. Recreate it from scratch; running
`python -m venv .venv` over an existing environment does not remove old packages.

```bash
deactivate 2>/dev/null || true
rm -rf .venv
python3 -c "import platform; print(platform.machine())"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --no-cache-dir -e ".[dev]"
make run
```

Apply database migrations:

```bash
make migrate
```

Create the first local admin user from the browser:

```text
http://127.0.0.1:8000/setup
```

The setup page is only available while no users exist. A command-line fallback is also available:

```bash
EMAIL=you@example.com make create-admin
```

## Docker

Build and run locally:

```bash
docker compose up -d --build
```

Apply database migrations inside the container:

```bash
docker compose exec app alembic upgrade head
```

Then create the first local admin user in the browser:

```text
http://localhost:8000/setup
```

The setup page is only available while no users exist. After setup, sign in at `/login`.

A command-line fallback is also available:

```bash
docker compose exec app python -m app.cli users create-admin --email you@example.com
```

Admin setup and maintenance tasks are available from the username menu for admin users, or directly:

```text
http://localhost:8000/admin
```

The admin page can create and revoke capture API tokens across users, open capture setup, check
health, and download a backup ZIP containing the SQLite database and local artefact files.

For a NAS or homelab deployment, keep `/app/data` on persistent storage. That directory contains
the SQLite database and uploaded artefacts. The bundled Compose file uses a named volume:

```yaml
volumes:
  - app_data:/app/data
```

On QNAP Container Station or similar systems, an explicit bind mount can make backups easier:

```yaml
volumes:
  - /share/Container/application_tracker/data:/app/data
```

Use a non-default `SESSION_SECRET_KEY` before creating real data:

```bash
openssl rand -hex 32
```

Set it in `.env` next to `docker-compose.yml`:

```env
APP_ENV=development
AUTH_MODE=local
SESSION_SECRET_KEY=replace-with-the-generated-secret
PUBLIC_BASE_URL=http://your-nas-hostname-or-ip:8000
DATABASE_URL=sqlite:////app/data/app.db
STORAGE_BACKEND=local
LOCAL_STORAGE_PATH=/app/data/artefacts
```

After pulling updates, rebuild and rerun migrations:

```bash
git pull
docker compose up -d --build
docker compose exec app alembic upgrade head
```

Download periodic backups from `/admin`, or back up the persistent `/app/data` mount directly from
the host.

For `APP_ENV=production`, `PUBLIC_BASE_URL` must be HTTPS and the default session secret is
rejected. Put the app behind QNAP's reverse proxy, another reverse proxy, or a TLS terminator, then
set `PUBLIC_BASE_URL=https://...`.

## Repository Policy

Do not commit runtime databases, uploaded resumes, cover letters, screenshots, or generated local artefacts. The app should remain safe to publish and sync to GitHub as development continues.

## Security

See `SECURITY.md` before deploying this app beyond local development.

The detailed auth model and implementation sequence lives in `docs/AUTHENTICATION.md`.
