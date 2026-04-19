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

## 2026-04-15: Focus-Led Workspace Supersedes Board-Centred Planning

The board remains a supported workflow view, but it is no longer the default strategic centre of the product. Future planning should treat Application Tracker as a goal-aware job-search workspace organised around Focus, Inbox, Active Work, Job Workspace, Artefacts, Capture, and Admin surfaces.

Rationale:

- A job search is not just stage movement; it also requires triage, preparation, follow-up, artefact reuse, external application work, and learning from outcomes.
- The UI should surface the user's goal and next useful action before raw workflow status.
- Board, lane, and list views are useful lenses over active work, but they should not define the product architecture.

## 2026-04-15: AI Is Embedded, Optional, And Inspectable

AI features should be planned as embedded guidance where work happens, not as a standalone assistant page or hidden automation layer.

Rationale:

- Recommendations, fit summaries, artefact suggestions, cover-letter drafts, and profile observations are most useful in context.
- AI output must be stored as visible records or drafts that users can review, edit, dismiss, or act on.
- The core tracker must continue to work without configured AI providers, and AI must not silently mutate jobs, artefacts, profile data, or workflow state.

## 2026-04-15: Intake Paths Distinguish User-Curated And System-Recommended Jobs

Future intake planning should distinguish manually added or user-captured jobs from system-recommended, scheduled-imported, or low-confidence captured jobs.

Rationale:

- A user-curated job may already represent intent and can enter Active Work or prospects directly.
- A system-recommended or low-confidence job needs validation before it consumes application effort.
- Inbox should become the judgement surface for accepting, dismissing, or enriching uncertain opportunities.

## 2026-04-15: Email-Captured Jobs Enter Inbox First

Jobs discovered in job-board alerts, recruiter emails, or forwarded opportunity emails should have a low-friction path into Inbox.

Rationale:

- Email is a common discovery channel, but an email mention is not yet an intentional application decision.
- Inbox preserves the lightweight judgement step before the job enters Active Work.
- The first implementation should be user-initiated, such as paste/forward/share-to-app, before adding mailbox polling or provider-specific integrations.
- Email capture should preserve provenance, including subject, sender/source where available, received date where available, extracted links, and raw text for later review or enrichment.

## 2026-04-17: Use The Design System For New UI Work

New UI work should reference `docs/design/DESIGN_SYSTEM.md` before implementation.

Rationale:

- The product needs a consistent visual language as it moves from functional bootstrap screens to Focus, Inbox, Job Workspace, and Artefact Library surfaces.
- The design system defines the intended calm-precision personality, semantic colour use, type scale, spacing, component states, fit/confidence treatment, contextual AI blocks, and external-transition convention.
- Existing screens can migrate incrementally; new surfaces should not introduce another visual style.

## 2026-04-19: Navigation And Responsive Shell Are Product Infrastructure

The product should gain a consistent navigation shell and explicit responsive behaviour before
additional feature-heavy surfaces are added.

Rationale:

- Focus, Inbox, Board, Job Workspace, Artefacts, Capture, Settings, and Admin are now distinct
  surfaces; users should not need to remember direct URLs to move between them.
- A top-left home/product anchor should consistently return to Focus.
- Mobile portrait usability is currently uneven and should be treated as core product quality, not
  cosmetic polish.
- Board visual alignment should be completed so Active Work does not feel like a separate product.
