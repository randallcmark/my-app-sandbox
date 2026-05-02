# Execution Plan: Job Detail Section Workbenches

Status: Active

Owner: Agent

Created: 2026-05-02

Last Updated: 2026-05-02

## Goal

Turn the Job Detail secondary sections into compact workbenches that answer what exists, what needs
 action, what the next step is, and what local AI help is available without reintroducing copy
 bloat or scattered utility cards.

## Non-Goals

- changing workflow semantics or job state rules
- expanding AI autonomy or hidden automation
- redesigning the whole Job Workspace shell in one slice
- merging all sections into one generic layout

## Context

- `docs/JOB_DETAIL.md`
- `docs/JOB_WORKSPACE_REDUCTION_PLAN.md`
- `docs/PRODUCT_VISION.md`
- `docs/roadmap/implementation-sequencing.md`
- `docs/roadmap/task-map.md`
- `docs/design/DESIGN_SYSTEM.md`
- `docs/product/user-journeys.md`
- `docs/exec-plans/active/job-workspace-reduction.md`
- Origin triage input: `/Users/markrandall/Documents/application_tracker_ui_qa_backlog.md` (`UI-017`)

## Acceptance Criteria

- Each section has a clear workbench purpose before large layout changes land.
- Each section identifies:
  - what already exists
  - what needs action
  - what the user can do next
  - what AI help is available, if any
  - what external system transition exists, if any
- Repeated explanatory copy is reduced rather than moved around.
- Section work lands in reviewable slices with route-level validation and browser/manual checks
  where feasible.

## Section Intent

1. Application:
   foreground current application state, deadlines, submission evidence, and the next concrete step
   without duplicating board-level status summaries.
2. Interviews:
   foreground upcoming interviews, preparation notes, and immediate preparation actions.
3. Follow-Ups:
   foreground due outreach, recent communications, and the next outbound action.
4. Tasks:
   foreground open execution work and quick capture/completion.
5. Notes:
   foreground active working notes, recent journal/context, and concise add/edit flows.

## Slice Plan

1. Define the workbench contract for each section and keep this document as the canonical plan.
2. Rework Application first because it is the broadest section and still carries the most generic
   summary weight.
3. Rework Interviews and Follow-Ups next as action-first timeline surfaces.
4. Rework Tasks and Notes last, keeping them compact and local to execution rather than turning them
   into general-purpose databases.
5. Validate each section on desktop and narrow/mobile widths before moving to the next slice.

## Progress Log

- 2026-05-02: Created the section-workbench execution plan from `UI-017` after completing the
  broader UI density cleanup, Job Workspace AI cleanup, Competency Evidence workspace redesign, and
  artefact Markdown preview quality pass. No large section redesign should proceed without landing
  against this plan.
- 2026-05-02 (session 2): All five section workbenches implemented and wired.
  - Application: `_application_state_bar()` + two-up role/route grid + submission history inline +
    record/start-application forms in `<details>` disclosure.
  - Interviews: `_interview_card()` / `_interview_cards()` sorted by scheduled_at; upcoming state
    bar when next interview known; schedule form secondary.
  - Follow-Ups: `_follow_up_card()` / `_follow_up_cards()` with overdue highlight; note form
    inline; blocker/return-note/start-application collapsed in disclosures.
  - Tasks: tightened to next-action + readiness checklist; all workflow action forms collapsed
    behind `<details>` disclosures.
  - Notes: add-note at top, recent activity below, journal collapsible, provenance always last.
  - CSS for `.app-state-bar`, `.interview-card`, `.follow-up-card`, `.workspace-form-disclosure`,
    `.workspace-inline-link` added to job_detail.py extra_styles.
  - Dead duplicate `_workspace_tools_section()` removed.
  - Status: Workstream 4 complete.

## Decisions

- Treat `UI-017` as a planned multi-slice redesign, not a one-off patch list.
- Keep section-level AI local and discrete. AI may assist inside a section, but must not dominate
  the primary workbench layout.
- Preserve the distinction between board status, workspace execution, and external-system actions.

## Validation

Commands to run before completing implementation slices:

```sh
bash scripts/validate-harness.sh
git diff --check
```

Run focused route tests for touched sections. Include browser/manual checks for desktop and mobile
 widths when layout changes.

## Risks

- Section redesign can easily drift back into summary-heavy dashboards instead of execution
  workbenches.
- Application and Notes are the easiest places to overgrow scope because they touch many adjacent
  workflows.
