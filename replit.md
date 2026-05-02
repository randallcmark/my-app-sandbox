# Application Tracker

A self-hosted, goal-aware job-search workspace for capturing roles, managing applications, and tracking progress through the job search process.

## Architecture

- **Framework**: FastAPI (Python 3.11)
- **Database**: PostgreSQL (Replit-managed, via `DATABASE_URL` secret)
- **ORM/Migrations**: SQLAlchemy 2 + Alembic
- **Server**: Uvicorn (dev) / Gunicorn (prod)
- **Auth**: Local session-based auth with argon2 password hashing
- **Storage**: Local file storage for artefacts (`./data/artefacts`)
- **Template rendering**: Server-side HTML via Jinja2-style templates in routes

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

## First Admin User

Visit `/setup` in the browser to create the first admin user (only available while no users exist).

## Workflow

The "Start application" workflow runs:
```
uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```
on port 5000.

## Notes

- Uses Replit-managed PostgreSQL (not SQLite as documented in original README)
- `psycopg2-binary` added as a dependency for PostgreSQL support
- The app's SQLite documentation applies to Docker/local deployments; Replit uses the managed PostgreSQL
