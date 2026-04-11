# Application Tracker

Application Tracker is a self-hosted job-search workspace for capturing roles, managing applications through a kanban lifecycle, storing application artefacts, and learning what works during a job search.

This repository is a clean rebuild of the original personal MVP. The previous implementation has been preserved locally at:

```text
/Volumes/Media/Repository/application_tracker_old
```

## Product Direction

The target product is:

- container-first and easy to self-host;
- local-first, with SQLite and local storage defaults;
- optionally multi-user inside one contained deployment;
- kanban-first for daily stage management;
- browser-capture friendly for importing jobs from job pages;
- profile-aware over time, with optional matching and writing assistance;
- private by default, with no required external services.

The detailed staged roadmap lives in:

- `project_tracker/PUBLIC_SELF_HOSTED_ROADMAP.md`
- `ROADMAP.md`

## Current State

This clean repo currently contains the minimal application skeleton:

- FastAPI app factory
- `/health` endpoint
- settings module
- pytest health check
- Dockerfile
- Docker Compose file
- public roadmap

The next implementation slice should follow Stage 0 and Stage 1 of the roadmap: repository hygiene, baseline architecture, migrations, auth boundaries, and durable deployment assumptions.

## Local Development

Create a virtual environment and install development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run the API:

```bash
uvicorn app.main:app --reload
```

Run tests:

```bash
make test
```

Run all local checks:

```bash
make check
```

Apply database migrations:

```bash
make migrate
```

## Docker

Build and run locally:

```bash
docker compose up --build
```

Then open:

```text
http://localhost:8000/health
```

## Repository Policy

Do not commit runtime databases, uploaded resumes, cover letters, screenshots, or generated local artefacts. The app should remain safe to publish and sync to GitHub as development continues.

## Security

See `SECURITY.md` before deploying this app beyond local development.
