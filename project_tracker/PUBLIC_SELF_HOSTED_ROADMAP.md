# Public Self-Hosted Roadmap

This document is the resumable plan for turning Application Tracker from a personal MVP into a polished, self-hostable application for jobseekers managing job applications through the full lifecycle.

It is written for future contributors and future AI sessions. Start here when resuming product planning or implementation work.

Status key:

- Done: implemented and verified enough to build on.
- In progress: partially implemented or present but not yet dependable.
- Planned: not started or needs a substantial rebuild.
- Deferred: intentionally out of scope until the core product is stable.

Last planning update: 2026-04-12

---

## Current Checkpoint

As of 2026-04-11, the Stage 3 board workflow is browser-tested through:

- Login/logout.
- Manual job creation from `/jobs/new`.
- Board workflow dropdown views for prospects, in progress, outcomes, all active, and archived jobs.
- Drag/drop and `Move to column` dropdown stage movement.
- Job detail notes, status-change timeline, mark applied, schedule interview, archive, and unarchive.
- Job detail editing for core job fields.
- Job-level artefact upload/download.
- Stage-aging, stale-card, and follow-up due indicators on board cards.

Known next product focus:

- Board filter controls for company, source, remote policy, keywords, and date added.
- UI polish for the board and job detail page now that the core workflow is usable.
- Prospects may become a row-list triage view rather than kanban cards, with quick action to mark
  interesting jobs for a focused interested/progression workflow.
- Editing still needs to expand beyond core job fields into notes, applications, interviews, and
  artefact metadata.
- Future job detail overlay/modal instead of full navigation away from the board.

Known bugs:

- Timeline/journal timestamps are stored in UTC and currently rendered as UTC on server-rendered pages.
  Browser users should see times in their local timezone, for example BST instead of UTC during daylight
  savings.

---

## Updated Product Direction

The next public-release plan adds these workstreams to the original staged roadmap:

- Containerized scheduler/worker service:
  - trigger job searches/imports;
  - perform follow-up notifications;
  - run optional AI processing and recommendation tasks.
- Guided AI provider setup:
  - first version uses user-supplied API keys;
  - prioritize OpenAI/ChatGPT and Anthropic/Claude;
  - later support OpenAI-compatible local endpoints and other providers.
- AI assistance:
  - build a user profile from applications, notes, outcomes, and artefacts;
  - review current jobs and recommend next actions;
  - tailor future applications using job descriptions, past successes/failures, notes, and artefacts;
  - generate editable cover letters, attestations, and application narratives.
- Capture/import:
  - use browser plugins for bot-blocked pages;
  - preserve raw page dumps for extraction;
  - prefer official feeds/APIs/search alerts for scheduled importers.
- Packaging:
  - web plus worker Docker Compose services;
  - HTTPS-native deployment, starting with self-signed local certificates and supporting real certs;
  - documented clone-to-running self-host flow.
- Admin and agent operations:
  - hidden admin UI for users, tokens, scheduler runs, backups, and system health;
  - repo-native Codex/Claude skills or command docs for tests, migrations, admin, backups, and smoke checks.

---

## 1. Product Context

Application Tracker began as a personal ATS used during an active job search. The MVP proved the core workflow but was paused after the original user found work. The intended next version is broader:

- A container-based, self-hosted job application tracker.
- Potentially multi-user within one contained deployment, for households, coaches, small peer groups, or local teams.
- A kanban-first workflow for smooth stage management.
- Browser-assisted job capture with low-friction import from job pages.
- Automatic sourcing and profile-aware matching over time.
- Private storage for resumes, cover letters, interview notes, communications, and outcomes.

The product should remain local-first and self-hostable. It can support optional external services, LLMs, and S3-compatible storage, but the core tracker must work without them.

---

## 2. Product North Star

A jobseeker should be able to run one command, open the app, capture jobs from the web, move them through a visual pipeline, manage every artefact and communication in context, and keep a private record of what worked until they find work.

The first public version should feel like a focused job-search workspace, not a generic CRUD admin tool.

---

## 3. Target Users

### 3.1 Primary User: Individual Jobseeker

Needs:

- Save interesting jobs quickly.
- Track applications across many sources.
- Avoid losing cover letters, resumes, recruiter emails, and interview notes.
- See what stage each opportunity is in.
- Understand where the search is working or stalling.
- Export or back up all data.

Constraints:

- May not be highly technical.
- May use a laptop, NAS, homelab, or small VPS.
- Needs privacy because the data includes resumes, salary expectations, and interview history.

### 3.2 Secondary User: Small Contained Group

Examples:

- A household where more than one person is job hunting.
- A career coach supporting a few people.
- A trusted peer group running one private deployment.

Needs:

- Separate user workspaces inside one deployment.
- Admin setup and recovery.
- Clear ownership boundaries.
- No accidental data leaks between users.

This is not a SaaS multi-tenant plan. The boundary is one self-hosted deployment.

---

## 4. Current Product Snapshot

The app is currently a FastAPI monolith with:

- SQLAlchemy models for jobs, applications, interviews, communications, artefacts, feedback, and users.
- SQLite/local filesystem defaults.
- Optional MariaDB and S3-compatible storage support.
- Server-rendered Jinja UI.
- A first kanban board.
- Job URL ingestion.
- Browser extension source and build targets under `extensions/`.
- Placeholder header-based auth.
- Admin screens.
- A pytest suite covering core API/UI/storage paths.

Known design debt:

- Placeholder auth is unsafe outside trusted local environments.
- Authorization is inconsistent across UI/API paths.
- Schema, docs, and model definitions have drifted.
- No migration system.
- `app/api/ui.py` is too large and mixes route handling with domain logic.
- JSON API and UI behavior diverge in places, especially ingestion.
- S3 path semantics need tightening.
- Delete flows do not reliably clean stored files.
- Runtime DBs and artefacts appear in the working tree and need cleanup before public release.

---

## 5. Product Principles

Use these principles when choosing between implementation options.

1. Local-first by default.
   The tracker must be useful without cloud services.

2. Container-first deployment.
   The default installation path should be Docker Compose with persistent volumes.

3. Privacy over convenience.
   Resumes, salary notes, and interview history are sensitive. Avoid external calls unless explicitly configured.

4. Kanban is the primary workflow.
   Stage movement should be drag-and-drop first, form editing second.

5. Capture should be frictionless.
   The user should be able to save a job from a browser page faster than copying details into a spreadsheet.

6. AI is optional and inspectable.
   LLM outputs should be stored as visible recommendations or drafts, never hidden state that silently changes the workflow.

7. Export and backup are core features.
   A job search archive should be portable and recoverable.

---

## 6. Deployment Model

### 6.1 Supported First-Class Deployment

Docker Compose:

- `app` service running FastAPI.
- Persistent `data` volume for SQLite and local artefacts.
- Environment variables from `.env`.
- Optional reverse proxy in front of the app.

Default stack:

```text
FastAPI container
  -> SQLite database in mounted volume
  -> local artefacts in mounted volume
```

Optional stack:

```text
FastAPI container
  -> MariaDB/Postgres-compatible database
  -> S3-compatible object storage
```

### 6.2 Multi-User Boundary

For the public self-hosted product, "multi-user" means multiple users inside one trusted deployment, not internet-scale multi-tenancy.

Required:

- Real login/session or reverse-proxy auth integration.
- Per-user ownership scoping.
- Admin user management.
- API tokens for browser capture.

Deferred:

- Billing.
- Organization plans.
- Cross-deployment federation.
- Hosted SaaS operation.

---

## 7. Target Workflow

### 7.1 Job Lifecycle Stages

Canonical stages for the public product:

1. Saved
2. Interested
3. Preparing
4. Applied
5. Interviewing
6. Offer
7. Rejected
8. Archived

Notes:

- `Archived` is a visibility state as much as a lifecycle state.
- Historical/legacy statuses should be migrated or mapped.
- Stage changes should create timeline events.

### 7.2 Main User Flow

1. User captures a job from the browser, URL form, or manual form.
2. Job appears on the kanban board in `Saved` or `Interested`.
3. User reviews the job, edits core fields, and attaches relevant artefacts.
4. User moves the card to `Preparing`.
5. User creates an application record and uploads resume/cover letter versions.
6. User moves the card to `Applied`.
7. Communications and interviews are recorded against the same job.
8. User moves the card to `Offer`, `Rejected`, or `Archived`.
9. Analytics help the user understand response rate, stage aging, source quality, and search momentum.

---

## 8. Stage Plan

## Stage 0: Repository Hygiene And Baseline

Status: In progress

Goal: make the repo safe to publish and easy to resume.

Why this matters:

Public users and contributors should not inherit private runtime data, generated artefacts, or an unclear project state.

Tasks:

- Remove committed runtime databases and uploaded artefacts from version control.
- Confirm `.gitignore` covers DBs, local artefacts, caches, notebooks checkpoints, virtualenvs, and generated extension build outputs if they are not source of truth.
- Decide whether extension build targets are tracked release artefacts or generated files.
- Add a short `CONTRIBUTING.md` with local setup and test commands.
- Add a `SECURITY.md` explaining supported deployment assumptions and where to report issues.
- Add a public-facing `ROADMAP.md` or link this file from `README.md`.
- Run the existing test suite in a clean environment.
- Record any failing tests with exact commands and errors.

Acceptance criteria:

- Fresh clone does not contain personal DBs, resumes, cover letters, or private job-search data.
- `git status --short` is understandable after setup and test runs.
- A new contributor can identify the current roadmap, setup instructions, and safety warnings.

Resume prompts:

- "Continue Stage 0 from `project_tracker/PUBLIC_SELF_HOSTED_ROADMAP.md`."
- "Audit git-tracked runtime artefacts and update ignore rules."

---

## Stage 1: Durable Core Platform

Status: Planned

Goal: make the current app safe to use long term.

Why this matters:

Job search data accumulates over weeks or months. Users need reliable upgrades, backups, and storage semantics before more features are added.

Tasks:

- Add Alembic migrations. Done in clean rebuild.
- Generate a baseline migration from the current SQLAlchemy models. Done for the initial clean schema.
- Replace unconditional startup `create_all` with explicit dev/test behavior. Done by starting the clean repo without startup table creation.
- Align ORM models, Pydantic schemas, UI forms, and docs.
- Choose canonical timestamp names for applications and communications.
- Choose canonical relationship semantics for interviews:
  - Either job-owned interviews with optional application link, or
  - application-owned interviews with derived job.
- Fix S3 path handling:
  - Prefer provider-relative keys in DB. Chosen as the storage invariant in the clean rebuild.
  - consistently parse provider URIs in each provider.
- Add best-effort storage deletion when artefact records are deleted.
- Add backup and restore commands:
  - SQLite DB backup.
  - Artefact directory archive.
  - Combined export bundle.
- Pin or bound dependencies.

Acceptance criteria:

- Schema changes are represented by migrations.
- Fresh install and upgraded install paths are documented.
- Artefact upload/download works on local storage and has tests for S3 key parsing logic.
- The app can export a restorable backup from the default local deployment.

Resume prompts:

- "Continue Stage 1 by adding Alembic and a baseline migration."
- "Continue Stage 1 by fixing storage path semantics and artefact deletion."

---

## Stage 2: Real Auth And Authorization

Status: Planned

Goal: replace placeholder auth and make ownership rules consistent.

Why this matters:

The current header-based auth is suitable only for local development. Public self-hosted users will reasonably expect private data separation, even inside one deployment.

Tasks:

- Decide supported auth modes:
  - Local username/password with sessions.
  - Reverse-proxy auth mode.
  - Optional OIDC later.
- Remove default admin behavior from production mode.
- Add first-run admin creation flow or documented bootstrap command.
- Add password hashing if local auth is implemented.
- Add CSRF protection for server-rendered forms if cookie/session auth is used.
- Add API token model for browser extension capture.
- Add reusable authorization helpers:
  - `get_owned_job_or_404`
  - `get_owned_application_or_404`
  - `get_owned_interview_or_404`
  - `get_owned_artefact_or_404`
- Apply ownership checks consistently to UI and JSON API mutating routes.
- Add admin impersonation/debug tools only if explicitly needed and clearly marked.

Acceptance criteria:

- A non-admin user cannot read, mutate, download, or delete another user's data.
- Browser extension can use a scoped token without sharing a login cookie.
- Production mode cannot silently become admin by omitting headers.
- Tests cover representative cross-user access failures.

Resume prompts:

- "Continue Stage 2 by designing the auth modes and bootstrap flow."
- "Continue Stage 2 by adding ownership helper functions and applying them to UI routes."

---

## Stage 3: Kanban-First Workflow

Status: In progress

Goal: make the board the main product surface.

Why this matters:

The user interface should support rapid daily job-search triage. Dragging cards between stages should be faster than opening forms and clicking through detail pages.

Tasks:

- Make the board the primary landing page after login. Done for logged-in root redirects.
- Add owner-scoped jobs API for board reads and updates. Done.
- Add first server-rendered board view. Done.
- Add job detail pages with timeline visibility. Done.
- Add browser manual job creation. Done from `/jobs/new`.
- Add core job detail editing. Done for primary job fields; related records remain planned.
- Implement drag-and-drop stage changes. Done.
- Persist card order within each column. Done with `PATCH /api/jobs/board`.
- Add optimistic UI updates with clear failure rollback.
- Add quick actions on cards:
  - Add note. Done on job detail pages and timeline API.
  - Mark applied. Done on job detail pages and jobs API.
  - Schedule interview. Done on job detail pages and jobs API.
  - Upload artefact. Done for job-level artefacts on job detail pages and jobs API.
  - Archive. Done on job detail pages and jobs API.
  - Unarchive. Done on job detail pages and jobs API.
- Add stage-aging indicators:
  - Days in current stage. Done on board cards.
  - Stale cards. Done on board cards with conservative thresholds.
  - Follow-up due. Done from timeline note follow-up dates.
- Add filters:
  - owner/user.
  - source.
  - company.
  - remote/hybrid/onsite.
  - role keywords.
  - date added.
  - archived visibility. Done through the archived workflow view.
- Add timeline event creation for stage changes. Done for job `stage_change` events.
- Normalize status naming across application and job stages.

Implementation notes:

- This can remain server-rendered with focused JavaScript.
- Consider SortableJS or another small proven drag-and-drop library.
- Avoid a full frontend rewrite until the server-rendered UX is proven insufficient.

Acceptance criteria:

- User can move jobs across all lifecycle stages by dragging cards.
- Board state persists after reload.
- Card order persists after reload.
- Stage changes are visible in the job timeline.
- Keyboard or non-drag fallback exists for accessibility.

Resume prompts:

- "Continue Stage 3 by adding drag-and-drop persistence to the kanban board."
- "Continue Stage 3 by adding board filters and archived visibility."

---

## Stage 4: Job Capture And Browser Extension

Status: In progress

Goal: make saving jobs from the web nearly frictionless.

Why this matters:

Jobseekers discover opportunities across many job boards and ATS pages. Capture must be faster than manual copying or the tracker will not become the daily workflow.

Current repo context:

- This checkout currently does not contain the previously referenced `extensions/` tree.
- A bookmarklet setup page exists at `/api/capture/bookmarklet` as the first browser capture path.
- Chrome, Firefox, and Safari extension work should either restore the prior extension source or
  scaffold a new extension against the stable capture API.

Tasks:

- Define a stable capture API. In progress:
  - `POST /api/capture/jobs`. Done.
  - Bearer token auth. Done.
  - Idempotency/dedupe by canonical URL. Started with owner-scoped `source_url` dedupe.
- Accept payload fields:
  - source URL.
  - apply URL.
  - title.
  - company.
  - location.
  - description.
  - selected text.
  - source platform.
  - raw extraction metadata.
- Add extension settings UI for:
  - tracker base URL.
  - API token.
  - default stage.
  - capture selected text vs full page.
- Add supported extractor strategy:
  - generic DOM extraction.
  - JSON-LD extraction.
  - Greenhouse.
  - Lever.
  - Ashby.
  - Workday where feasible.
- Add failure states:
  - tracker unreachable.
  - auth failed.
  - unsupported page.
  - duplicate job found.
- Add a bookmarklet as a low-friction alternative before polished extension packaging. Done with
  `/api/capture/bookmarklet`, token-authenticated capture, JSON-LD fallback extraction, selected
  text, and body text fallback.
- Decide extension packaging policy:
  - developer sideload only for first public version, or
  - packaged browser store submissions.

Acceptance criteria:

- User can save a job from a supported page into the tracker without copying fields manually.
- Extension works against a local tracker URL.
- Capture endpoint is authenticated by scoped token.
- Duplicate capture of the same URL updates or links to the existing job predictably.
- Unsupported pages fall back to URL/title/selected-text capture.

Resume prompts:

- "Continue Stage 4 by defining and implementing the capture API."
- "Continue Stage 4 by wiring the existing browser extension to token-based capture."

---

## Stage 5: Ingestion And Structured Extraction

Status: In progress

Goal: convert captured job pages into useful structured records.

Why this matters:

Captured data drives filtering, matching, analytics, and writing assistance. The app should preserve raw source data while presenting readable, editable job records.

Tasks:

- Consolidate API and UI ingestion into one shared service.
- Parse JSON-LD `JobPosting` where present.
- Resolve relative URLs with `urljoin`.
- Extract:
  - title.
  - company.
  - location.
  - remote/hybrid/onsite policy.
  - salary range and currency.
  - employment type.
  - seniority.
  - apply URL.
  - closing date where available.
  - description sections.
- Preserve:
  - raw HTML or raw extension payload.
  - clean description text.
  - structured extraction metadata.
  - warnings and confidence.
- Add source-specific extractors only after generic structured extraction.
- Add fixture-based tests for representative pages.

Acceptance criteria:

- Ingestion produces a readable job description for common job pages.
- Structured extraction can be inspected and manually corrected.
- Raw source data is preserved for debugging.
- API and UI ingestion return consistent results.

Resume prompts:

- "Continue Stage 5 by consolidating UI and API ingestion into one service."
- "Continue Stage 5 by adding JSON-LD JobPosting extraction."

---

## Stage 6: Profile, Matching, And Search Strategy

Status: Planned

Goal: help users prioritize jobs and improve application strategy.

Why this matters:

A tracker becomes more valuable when it helps the user decide where to spend limited time, not just record what happened.

Tasks:

- Add user profile model:
  - target roles.
  - target locations.
  - remote preference.
  - salary expectations.
  - skills.
  - industries.
  - seniority range.
  - dealbreakers.
  - authorization/work eligibility notes if user chooses to store them.
- Add resume/profile artefact types.
- Add deterministic matching first:
  - keyword match.
  - skill overlap.
  - missing skill hints.
  - compensation fit.
  - location fit.
- Add user-editable fit notes.
- Add optional LLM provider interface later:
  - local model.
  - OpenAI-compatible endpoint.
  - disabled by default.
- Store AI outputs as explicit records:
  - job fit summary.
  - tailoring suggestions.
  - cover letter draft.
  - interview prep notes.

Acceptance criteria:

- User can maintain a profile without enabling AI.
- Jobs can be filtered/sorted by deterministic fit indicators.
- AI features are optional, configurable, and visible.
- No sensitive data is sent externally unless the user explicitly configures an external provider.

Resume prompts:

- "Continue Stage 6 by designing the user profile schema."
- "Continue Stage 6 by implementing deterministic skill matching."

---

## Stage 7: Analytics, Reminders, And Outcomes

Status: Planned

Goal: help users understand search progress and act on stale opportunities.

Why this matters:

Job searches are long and emotionally expensive. Good analytics should answer practical questions: where am I getting responses, what needs follow-up, and where am I spending effort with no return?

Tasks:

- Add analytics dashboard:
  - applications by stage.
  - response rate by source.
  - interview conversion rate.
  - offer/rejection rate.
  - time from saved to applied.
  - time from applied to first response.
  - stale applications.
- Add follow-up reminders:
  - due date field.
  - next action field.
  - board badges.
  - optional email/webhook notification later.
- Add outcome taxonomy:
  - rejected no response.
  - rejected after screen.
  - rejected after interview.
  - withdrawn.
  - offer declined.
  - offer accepted.
- Add exportable reports.

Acceptance criteria:

- User can see which stages and sources are producing results.
- User can identify stale jobs and follow-up actions from the board.
- Outcomes are structured enough to support future learning and analytics.

Resume prompts:

- "Continue Stage 7 by adding basic analytics queries and `/ui/analytics`."
- "Continue Stage 7 by adding next-action and follow-up due fields."

---

## Stage 8: Public Release Packaging

Status: Planned

Goal: prepare the project for external users to deploy and trust.

Why this matters:

Public release is as much about installability, documentation, and recovery as feature count.

Tasks:

- Write public README flow:
  - what the app does.
  - who it is for.
  - quick start.
  - screenshots or demo GIF.
  - deployment modes.
  - security notes.
- Add example `.env` for local-only and reverse-proxy deployments.
- Add versioned Docker image publishing plan.
- Add release checklist.
- Add upgrade notes and migration instructions.
- Add backup/restore documentation.
- Add browser extension installation docs.
- Add license.
- Add issue templates:
  - bug report.
  - feature request.
  - extractor request for a job board/ATS.
- Add minimal telemetry policy:
  - default no telemetry.
  - any future telemetry must be opt-in.

Acceptance criteria:

- A user can deploy from a fresh clone using documented commands.
- A user can back up and restore their data.
- A user can understand security limitations before exposing the app.
- The project has a clear version number and release notes.

Resume prompts:

- "Continue Stage 8 by drafting the public README quick start."
- "Continue Stage 8 by writing the release checklist."

---

## 9. Cross-Cutting Engineering Work

These workstreams should be folded into the stage plan rather than treated as separate features.

### 9.1 Service Extraction

Move shared behavior out of route files:

- `app/services/authorization.py`
- `app/services/workflow.py`
- `app/services/ingestion/`
- `app/services/artefacts.py`
- `app/services/capture.py`
- `app/services/profile_matching.py`

Primary goal:

- UI routes and JSON APIs should call the same domain operations.

### 9.2 API Shape

Keep two surfaces:

- Human UI: server-rendered pages.
- Integration API: browser extension, scripts, and future automation.

The integration API should be stable, token-authenticated, and documented.

### 9.3 Test Strategy

Test levels:

- Unit tests for extraction, storage paths, workflow transitions, and authorization helpers.
- API tests for capture, CRUD, auth, and cross-user access.
- UI smoke tests for board and detail pages.
- Fixture tests for supported job sites.
- Optional browser extension tests later.

### 9.4 Accessibility

Minimum requirements:

- Keyboard fallback for stage changes.
- Visible focus states.
- Form labels for all inputs.
- Color contrast in light and dark themes.
- No drag-only critical workflow.

### 9.5 Data Portability

Required:

- Export JSON/CSV for jobs and applications.
- Export artefact archive.
- Backup and restore docs.

Desirable:

- Full import from previous export.
- Redaction option for sharing bug reports.

---

## 10. Suggested Immediate Next Actions

Start with these unless a more urgent bug exists:

1. Clean repository hygiene for public release readiness.
2. Add Alembic baseline migration.
3. Replace placeholder auth or clearly isolate it to dev mode.
4. Implement reusable ownership checks.
5. Make kanban drag-and-drop persistent.
6. Define token-authenticated capture API.
7. Wire existing extension to the capture API.

The best first implementation slice is:

```text
Stage 0 -> Stage 1 migrations -> Stage 2 ownership helpers -> Stage 3 board drag/drop
```

This sequence makes the app safer before expanding capture and automation.

---

## 11. Decision Log

### 11.1 Keep FastAPI Monolith For Now

Decision:

Keep the backend and server-rendered UI in one FastAPI application through the first public release.

Rationale:

The app is still small enough that a monolith is cheaper to reason about. A separate frontend would add deployment and build complexity before the workflow is fully proven.

### 11.2 Do Not Lead With AI

Decision:

Profile matching can start deterministic. LLM support should be optional and adapter-based.

Rationale:

The product must first be a dependable private tracker. AI becomes useful only after capture, workflow, and data quality are solid.

### 11.3 Browser Capture Should Use API Tokens

Decision:

The extension should authenticate with a scoped API token, not a user password or implicit admin header.

Rationale:

This keeps browser capture compatible with local deployments, reverse proxies, and future auth modes.

### 11.4 Multi-User Means One Deployment, Many Local Users

Decision:

The public product may support multiple users in one contained deployment, but not SaaS-style multi-tenancy.

Rationale:

This matches the self-hosted goal and avoids introducing account, billing, tenancy, and compliance complexity.

### 11.5 Board Views Should Follow Workflow Tiers

Decision:

The board should not permanently present every lifecycle status as equal top-level columns. The
statuses remain important, but they should be grouped into workflow-focused views:

- Prospects / Discovery:
  - `saved`
  - `interested`
- In Progress:
  - `preparing`
  - `applied`
  - `interviewing`
- Decision / Outcome:
  - `offer`
  - `rejected`
- Archived:
  - `archived`
  - Hidden from active workflows by default.

Rationale:

The daily workflow changes by task. Discovery is about triage and deciding whether a captured job
is worth pursuing. In Progress is about preparing, applying, interviewing, and following up.
Decision / Outcome is about closing opportunities and recording final results. Archived jobs are
not an active workflow tier; they should be searchable or restorable but removed from the default
board.

Implementation guidance:

- Keep the canonical statuses as the durable database values.
- Add workflow modes such as `prospects`, `in_progress`, `outcomes`, and `all`. Done.
- Prefer URLs like `/board?workflow=prospects` or `/board?workflow=in_progress`. Done.
- Default `/board` should eventually open the most useful daily workflow, likely `in_progress`,
  with a fallback to `prospects` when no active jobs exist. Default `in_progress` is done; fallback
  remains planned.
- Drag-and-drop should normally stay within the selected workflow view, while an explicit `all`
  view can remain available for power users or maintenance. Done for current server-rendered board.

### 11.6 Interview Scheduling Is Usually An Inbound Outcome

Decision:

The base interview quick action should model the result as "interview scheduled", not as the
application controlling the scheduling workflow.

Rationale:

In most job searches, the hiring entity, recruiter, or coordinator controls scheduling. The
applicant is usually responding with availability, preferences, or confirmations. Application
Tracker should record the scheduled interview outcome first, then later support helper workflows
for finding and sharing availability.

Implementation guidance:

- Use `interview_events` for the durable scheduled event:
  - `stage`
  - `scheduled_at`
  - `location`
  - `participants`
  - `notes`
  - `outcome`
- Creating an interview should move the job to `interviewing` when appropriate.
- Creating an interview should add a timeline event such as `event_type="interview"`.
- Future availability features should be designed separately from the base scheduled event.
- Potential future integrations:
  - applicant-defined availability windows;
  - acceptable scheduling rules such as outside working hours;
  - limited calendar integration, likely starting with one provider;
  - generated availability options to send to a recruiter;
  - eventual inbound calendar confirmation import.

---

## 12. Resume Checklist For Future Sessions

When resuming work:

1. Read this file.
2. Run `git status --short` and identify pre-existing user changes.
3. Read `PLAN.md`, `project_tracker/STATUS.md`, and relevant code before editing.
4. Pick exactly one stage slice.
5. Update this document if scope or status changes.
6. Run focused tests.
7. Record commands run and unresolved risks in the final response or a tracking file.

Suggested first prompt:

```text
Read project_tracker/PUBLIC_SELF_HOSTED_ROADMAP.md, inspect the current repo state, and continue the next unchecked Stage 0/1 task without touching unrelated files.
```
