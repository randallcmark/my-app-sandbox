# Product Vision

Application Tracker is a private, self-hosted job-search workspace. It helps a jobseeker decide what matters, capture and triage opportunities, prepare applications, manage reusable artefacts, and keep a record of what worked.

The product is not just a kanban board. The board is one workflow view inside a broader environment for doing the work of a job search.

## North Star

A jobseeker should be able to run the app, state what they are trying to achieve, capture roles from the web, see what needs attention today, work through applications with the right artefacts and context, and preserve a private learning record across the full search.

The first public version should feel like a focused job-search workspace, not a generic CRUD admin tool or a project-management board with job labels.

## Target Users

Primary user:

- An individual jobseeker running a private local, NAS, homelab, or small VPS deployment.
- Needs fast capture, practical triage, application preparation, follow-up tracking, and portable backups.
- Cares about privacy because the data includes resumes, salary expectations, job preferences, interview notes, and outcomes.

Secondary user:

- A small trusted group in one contained self-hosted deployment, such as a household, coach, or peer group.
- Needs separate user workspaces, admin recovery, and clear ownership boundaries.
- Does not need SaaS-scale tenancy, billing, or cross-organisation administration.

## Primary Surfaces

Focus is the default command surface. It answers what needs attention now: due follow-ups, stale jobs, active applications, interviews, recent captures, and work that has no clear next action.

Inbox is the intake and judgement surface. It holds system-recommended jobs, email-captured jobs, low-confidence captures, scheduled imports, and partially enriched opportunities until the user accepts, dismisses, or enriches them.

Active Work is the workflow view for jobs already worth effort. It can use board, lane, and list views, but those views exist to support the job search rather than define the product.

Job Workspace is the execution surface for one opportunity. It combines role overview, current state, next action, application readiness, artefacts, notes, journal, and external application links.

Artefacts are working assets, not passive attachments. Resumes, cover letters, narratives, attestations, portfolios, and writing samples should be reusable, attributable to jobs, and connected to outcomes over time.

Capture brings jobs into the system from manual entry, browser extensions, APIs, email capture, and future scheduled search/import jobs.

Admin supports self-hosted operation: users, API tokens, backups, restore, scheduler runs, health, and deployment maintenance.

Help is a lightweight product guide available to every authenticated user. It should explain how
the surfaces relate, reinforce Focus-first daily use, and keep self-hosted/admin guidance visible
without turning the main workflow into documentation.

## Design Principles

The canonical visual system is `docs/design/DESIGN_SYSTEM.md`. New UI work should use that document for colour, typography, spacing, component, AI guidance, and external-transition decisions.

- User goal first: product surfaces should be organised around what the user is trying to achieve.
- Next action over raw status: status matters, but the app should make the next useful step visible.
- Calm and precise: avoid noisy, gamified, or oversized controls; emphasise role quality, metadata, and readiness.
- External systems are first-class: employer sites, ATS pages, email, calendars, and document tools remain part of the workflow.
- Artefacts are strategic: the system should help select, tailor, and learn from application materials.
- AI is embedded and inspectable: recommendations and drafts should appear where work happens, never as hidden state or silent mutation.
- Local-first by default: the core tracker must work without external services.

## What This Product Is Not

- Not a hosted SaaS product.
- Not a generic CRM or project-management board.
- Not an AI agent that acts without review.
- Not a scraper-only tool.
- Not a document repository detached from job outcomes.

## Surface Relationships

Focus points the user to the right work.

Inbox decides which opportunities enter the workflow.

Email capture feeds Inbox when a job-board or recruiter email catches the user's eye. The first version should prioritise an easy user-initiated path, such as forwarding or pasting selected email content, before attempting full mailbox polling.

Active Work shows the jobs already being pursued.

Job Workspace is where a specific application is prepared, submitted, followed up, and learned from.

The board remains useful for stage movement and visual scanning, but it is no longer the strategic centre. It is one lens over Active Work.

User-context operations such as User Settings, Capture Settings, Help, Sign out, and admin-only
Admin/API Docs belong under the logged-in username rather than in the primary workflow navigation.
