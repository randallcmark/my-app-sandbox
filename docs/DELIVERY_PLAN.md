# Delivery Plan

This plan turns Application Tracker from a board-centred tracker into a goal-aware job-search workspace. Phases are ordered so each one creates useful product value and prepares the next.

All new UI work should reference `docs/design/DESIGN_SYSTEM.md` for the intended visual language, design tokens, component states, AI guidance treatment, and external-transition patterns.

## Phase 1: Intent/Profile Foundation

Status: implemented for the first manual profile slice.

Goal: give the app a model of what the user is trying to achieve.

Implementation targets:

- Add a user-owned profile/intent model for target roles, locations, remote preference, salary range, preferred industries, constraints, urgency, and positioning notes.
- Add a simple settings/profile UI.
- Add authenticated read/update API support for the current user's profile.
- Keep the feature manual; no AI dependency.

Acceptance criteria:

- A logged-in user can create and edit their job-search profile.
- Profile data is owner-scoped.
- The app works if no profile exists.
- Docs explain that the profile later drives Focus, Inbox, search, and AI recommendations.

Test expectations:

- Unit/API tests for owner scoping and profile create/update.
- UI smoke test for the profile/settings page.
- Migration test for any schema changes.

## Phase 2: Focus Surface

Status: implemented for the first no-new-schema Focus slice.

Goal: make the default home page answer what the user should work on now.

Implementation targets:

- Add `/focus` as the default post-login destination.
- Summarise due and overdue follow-ups, stale active jobs, recent captures needing review, interviews, active applications, and jobs without a clear next action.
- Keep `/board` available from navigation.
- Use existing data first; do not require scheduler or AI.

Acceptance criteria:

- Root path redirects authenticated users to `/focus`.
- Focus items link to relevant job workspaces.
- Empty states guide the user to add/capture jobs or complete their profile.
- Existing board behaviour remains available.

Test expectations:

- UI smoke tests for focus with empty and populated data.
- Regression tests for login redirects and board access.

## Phase 2.5: Navigation And Responsive Shell

Goal: make every page feel like part of one product and usable across desktop, tablet, and mobile.

Status: implemented and manually verified for the core authenticated server-rendered surfaces. A shared shell now
provides a consistent product anchor, stable page framing, primary workflow navigation, page action
links, and a user-context menu across Focus, Inbox, Paste email, Artefacts, Board, Job Workspace,
Add Job, Settings, Capture setup, Help, and Admin. User-context operations now live under the
top-right username menu: User Settings, Capture Settings, Help, Sign out, and Admin/API Docs for
admin users. The first responsive hardening pass improves mobile navigation, board workflow
controls, job workspace editing/save controls, tables, and stacked actions. Manual browser testing
has passed on desktop, mobile portrait, and mobile landscape layouts.

Implementation targets:

- Add a shared navigation shell or shared navigation helper for server-rendered pages. Done for the
  core authenticated server-rendered pages.
- Include a consistent top-left product/home anchor that returns to Focus. Done for Focus, Inbox,
  Paste email, Artefacts, Board, Job Workspace, Add Job, Settings, Capture setup, Help, and Admin.
- Expose the same primary workflow destinations consistently: Focus, Inbox, Board, and Artefacts.
  User-context destinations live in the username menu: User Settings, Capture Settings, Help, Sign
  out, and admin-only Admin/API Docs.
- Bring Board fully onto the same visual language as Focus, Inbox, Job Workspace, Artefacts, and
  Settings. Done for the current refined board experience.
- Add first-party Help content for the core user workflow and admin operations. Done at `/help`.
- Add responsive breakpoints for narrow portrait screens so content does not scroll behind form
  controls or action bars. Started with shared nav overflow handling, job workspace savebar
  placement, and table/action stacking.
- Define stable mobile behaviour for large forms, action bars, board/list views, and card grids.
  Started for board tabs/metrics, settings/admin tables, Inbox actions, and Artefact actions.

Acceptance criteria:

- A user can reach the primary surfaces from any authenticated page without remembering URLs.
- Board visually aligns with the design system tokens and component style.
- User-context operations are grouped under the logged-in username and respect admin visibility.
- Help is available to all authenticated users from the user-context menu.
- Mobile portrait pages remain readable and actionable without overlapping text or hidden controls.
- Existing route tests continue to pass.

Test expectations:

- UI smoke tests for shared navigation links and user-context menu access on Focus, Inbox, Board,
  Job Workspace, Artefacts, Settings, Capture setup, Help, and Admin.
- Current regression coverage: Focus, Inbox, Artefacts, Board, Job Workspace, Capture setup,
  Settings, Help, and Admin route tests.
- Browser/manual tests passed at desktop, mobile portrait, and mobile landscape widths.
- Regression tests for fixed/sticky controls where present.

## Phase 3: Inbox And Intake Semantics

Status: implemented for browser/API capture, the first manual paste email-to-Inbox slice, and
Inbox review/enrichment before acceptance. Provider-backed email ingestion, multi-candidate email
review, and system recommendations remain planned follow-ons.

Goal: separate unreviewed intake from intentional prospects.

Implementation targets:

- Add intake metadata for source type, confidence, and review state.
- Add `/inbox` for unreviewed or low-confidence jobs.
- Add an email-to-Inbox capture path for job-board or recruiter emails that catch the user's eye.
- Route future system recommendations and low-confidence captures into Inbox.
- Preserve manual Add Job as an intentional user entry path.

Acceptance criteria:

- User can accept, dismiss, or enrich an inbox item.
- Accepted jobs move into the appropriate workflow state.
- Dismissed jobs do not appear in active board views.
- Existing capture flow continues to work.
- Email-captured jobs preserve the original email subject/source context and land in Inbox before becoming Active Work.

Test expectations:

- Unit/API tests for intake transitions and owner scoping.
- Unit/API tests for email intake parsing and provenance storage.
- UI smoke tests for inbox accept/dismiss/enrich paths.
- Capture regression tests.

Implementation note:

- Start with user-initiated capture, such as paste/forward/share-to-app, rather than background mailbox access. IMAP, Gmail, Microsoft 365, and notification-driven mailbox integrations can follow once Inbox semantics are stable.
- Store email provenance separately from the extracted job fields: subject, sender/source, received date when known, original text/html when available, extracted links, and extraction confidence.
- Treat one email as capable of producing zero, one, or many Inbox candidates, since job-board alert emails often contain several roles.

## Phase 4: Job Workspace Refresh

Goal: make job detail a working surface, not a record form.

Status: first workspace refresh implemented. Job detail now has a workspace header, next-action
panel, role overview, readable description, readiness checklist, activity section, contextual aside,
collapsed journal, collapsed provenance, and existing inline editing/actions. Remaining follow-on
work is to add richer external workflow actions such as blockers, return notes, and application
started.

Implementation targets:

- Reorganise job detail around role overview, current state, next action, application readiness, artefacts, notes, journal, external links, and timeline.
- Keep focused inline editing for individual fields.
- Keep journal collapsed by default.
- Add explicit external workflow actions: open source, open apply link, mark application started, mark submitted, record blocker, and record return note.

Acceptance criteria:

- User can progress a job without returning to the board.
- The page makes the next likely action obvious.
- Large job descriptions remain readable.
- Editing remains focused and unobtrusive.

Test expectations:

- UI smoke tests for status movement, external actions, inline editing, and journal collapse.
- API tests for any new job action routes.

## Phase 5: Artefact Library

Goal: make files reusable assets rather than passive attachments.

Status: metadata and reuse groundwork implemented. Users can now view all owned artefacts outside
an individual job, edit purpose/version/notes/outcome metadata, open linked job workspaces, download
owned artefacts from an owner-scoped library route, and attach an existing artefact to another job
without copying the file. Application/interview-level reuse, extraction, and AI suggestions remain
planned follow-on work.

Detailed resumable planning for AI-assisted artefact selection, tailoring, draft generation, and
outcome-aware learning now lives in `docs/ARTEFACT_AI_PLAN.md`. The next recommended slice is
Phase B from that document: existing artefact suggestion in Job Workspace before tailoring or
generation. Phase B sub-slice 1 is now implemented in the service layer: deterministic artefact
shortlist and compact AI summary helpers, and sub-slice 2 is now implemented in the AI service
layer: a dedicated `artefact_suggestion` prompt contract and generation entry point. Sub-slice 3 is
also now implemented: Job Workspace exposes `Suggest artefacts` and renders visible
`artefact_suggestion` output. Sub-slice 4 is also implemented: when no candidate artefacts exist,
the app now creates a visible local fallback suggestion without requiring a provider. Optional
linking affordances and thin-metadata output polish are now also implemented. Phase B is complete
for the first intended artefact suggestion slice; the next recommended step is Phase C tailoring
guidance. The detailed implementation spec for that next phase now lives in
`docs/ARTEFACT_AI_PLAN.md`, including the proposed `tailoring_guidance` output contract, service
boundaries, Job Workspace trigger model, sparse-content behavior, and handoff to later draft
generation. Phase C sub-slice 1 is now implemented in the AI layer: the `tailoring_guidance`
output contract, prompt contract, and service entry point now exist. Phase C sub-slice 2 is also
implemented: Job Workspace now exposes a per-artefact tailoring action with ownership-safe
retrieval and route wiring. Phase C sub-slices 3 and 4 are now also implemented: tailoring
guidance renders through the shared visible AI output surface with a selected artefact link, and
thin metadata artefacts now degrade to a visible local fallback instead of forcing a weak provider
call. Phase C sub-slice 5 is now also implemented: text-like artefacts can contribute a verified
excerpt to tailoring prompts, and tailoring outputs now carry draft-handoff metadata for later
generation. Phase D has now started: the first visible draft slice is implemented for one selected
artefact in Job Workspace, beginning with `resume_draft` and an explicit document context strategy
that prefers extracted text and falls back to metadata-only drafting when necessary. Cover-letter
drafting is now also exposed from the same route, metadata-only drafts are labelled as
low-confidence scaffolds in the shared output surface, and visible drafts can now be promoted
explicitly into new markdown artefacts without overwriting the baseline. Supporting statement and
attestation draft kinds now also share the same route and promotion flow, with saved artefact kind
and filename matching the selected draft type. The artefact library now surfaces saved-draft
provenance so promoted drafts retain a visible link back to their source draft and baseline. The
document context layer now also supports DOCX extraction plus best-effort host-backed extraction
for legacy Word/RTF and PDF files when available. A narrow Gemini-backed `provider_document` path
now also exists for draft generation when no extracted text is available but a supported binary
artefact can be passed directly, reducing unnecessary metadata-only fallbacks on non-text files.

Implementation targets:

- Add artefact metadata for type, purpose, version label, notes, associated jobs/applications, and outcome linkage where known.
- Add an artefact library page.
- Keep job-level upload while allowing existing artefacts to be associated with jobs.
- Prepare for future text extraction without requiring it in this phase.

Acceptance criteria:

- User can see all artefacts outside an individual job.
- User can associate an existing artefact with a job.
- Existing job artefact downloads continue to work.
- Docs explain artefact strategy for future AI tailoring.

Test expectations:

- Unit/API tests for artefact ownership, metadata, and associations.
- UI smoke tests for library listing and job association.
- Storage regression tests for existing downloads.

## Phase 6: Embedded AI Readiness

Goal: create stable places for AI outputs before enabling heavy AI features.

Status: schema and settings support are implemented for the first explicit Job Workspace AI
generation slice. The app now has owner-scoped AI provider records for OpenAI, Anthropic, and
OpenAI-compatible endpoints, encrypted-at-rest API key storage, owner-scoped AI output records, and
visible Job Workspace generation actions for fit summaries and recommendations. OpenAI, Gemini, and
OpenAI-compatible execution are available; Anthropic remains planned. AI does not mutate workflow
state.

Visible AI output rendering now also exists on Inbox review and Focus. Focus uses a distinct
surface-specific prompt contract for its AI nudge so the recommendation remains tied to the
Focus-mode "one immediate next move" use case.

Implementation targets:

- Add visible records for recommendations, fit summaries, drafts, profile observations, and artefact suggestions.
- Add provider settings placeholders for OpenAI, Anthropic, and OpenAI-compatible local endpoints.
- Store AI outputs visibly and auditably.
- Prevent AI from silently mutating jobs, profile, artefacts, or workflow state.

Acceptance criteria:

- AI can be disabled with no product degradation.
- AI outputs are visible, editable or dismissible where appropriate, and tied to source context.
- No external AI calls happen unless a provider is configured.

Test expectations:

- Unit/API tests for AI output ownership and visibility.
- Settings tests proving disabled AI makes no external calls.
- UI smoke tests for visible recommendations/drafts once records exist.

## Phase 7: Scheduler And Worker

Goal: support recurring search, reminders, notifications, and AI processing.

Implementation targets:

- Add a worker service to Docker Compose.
- Add scheduler run records and admin visibility.
- Support scheduled tasks for job search/import, optional mailbox or email-rule ingestion, stale job detection, follow-up notification generation, and AI review/recommendation generation.
- Feed results into Focus and Inbox.

Acceptance criteria:

- Scheduler can be disabled.
- Admin can see recent runs and failures.
- Failed worker jobs do not break the web app.
- Docker docs explain app plus worker deployment.

Test expectations:

- Unit tests for scheduler run recording.
- Admin UI smoke tests for run history.
- Docker smoke test for worker-disabled startup.

## Phase 8: Admin, Restore, And Operations

Goal: round out self-hosted manageability.

Implementation targets:

- Add admin object management pages for users, jobs, and API tokens.
- Add backup restore with dry-run validation.
- Add password reset groundwork using one-time reset tokens.
- Improve HTTPS and reverse-proxy guidance.
- Add repo-native command docs or Codex/Claude skill docs for common admin, test, migration, backup, and smoke tasks.

Acceptance criteria:

- Admin dashboard counts link to object lists.
- Restore validates archive shape before replacing data.
- Deployment docs cover migration, first admin, backup, restore, and upgrade flow.
- Public repo remains safe from runtime databases and private artefacts.

Test expectations:

- Admin route authorization tests.
- Restore validation tests.
- Docker deployment smoke test covering migration, first-run setup, login, backup, and worker-disabled startup.

## Interface Additions

Planned public additions:

- User profile/intent API for authenticated read/update.
- Server-rendered `/focus`.
- Server-rendered `/inbox`.
- Intake metadata for source, confidence, and review state.
- Job workspace actions for external application workflow.
- Artefact library and association flows.
- Shared server-rendered shell with user-context menu.
- Authenticated `/help` page.
- Visible AI output records.
- Scheduler run records and admin views.

Existing board, capture, auth, job APIs, and Docker setup should remain backward compatible unless a migration explicitly documents otherwise.
