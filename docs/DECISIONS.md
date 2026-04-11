# Decisions

## 2026-04-11: Fresh Rebuild

The original personal MVP has been moved to:

```text
/Volumes/Media/Repository/application_tracker_old
```

This repository starts clean so it can be safely synced to GitHub as work progresses.

Rationale:

- Avoid publishing personal runtime data, resumes, cover letters, and old generated artefacts.
- Avoid carrying MVP implementation debt directly into the public product.
- Keep the useful planning and domain lessons while rebuilding deliberately.

## 2026-04-11: FastAPI Monolith First

The first public version will remain a FastAPI monolith.

Rationale:

- The product is workflow-heavy but not yet large enough to justify a split frontend/backend architecture.
- Docker Compose deployment should remain simple.
- Server-rendered pages plus focused JavaScript are enough for the initial kanban workflow.

## 2026-04-11: Alembic From The First Schema

The rebuild starts with Alembic migrations instead of app-startup `create_all`.

Rationale:

- Job-search history becomes valuable user data quickly.
- Public self-hosted users need a documented upgrade path.
- Schema drift was one of the main issues in the original MVP.

The baseline schema includes users, API tokens, jobs, applications, interviews, communications, and artefacts.

## 2026-04-11: Store Provider-Relative Artefact Keys

Artefact records should store provider-relative keys, not absolute local paths or full provider URIs.

Rationale:

- The same database record can be interpreted by local and S3-compatible storage providers.
- Backups and restores are more portable.
- Path traversal checks can be centralized before providers touch the filesystem or object store.

Example:

```text
jobs/<job-uuid>/applications/<application-uuid>/resume.pdf
```
