# Artefact AI Plan

This document is the resumable implementation reference for AI-assisted artefact selection,
tailoring, and generation.

It is intentionally more detailed than the roadmap. Use it when resuming work on artefact-aware AI
so implementation can move forward in discrete slices without redefining the problem each time.

Status summary:

- Artefact library and metadata groundwork: implemented.
- Visible AI records and provider execution: implemented for job/workspace, Inbox review, and
  Focus nudge.
- Artefact-aware AI: planned.

## Product Intent

Artefacts are strategic working assets, not passive attachments. The system should help the user:

- understand what artefacts they already have;
- identify which existing artefacts are the strongest starting point for a given job;
- understand what should be adapted before submission;
- generate usable draft artefacts or required supporting documents when needed;
- preserve learning from outcomes over time.

Non-negotiables:

- AI remains optional.
- AI output remains visible and inspectable.
- AI must not silently attach artefacts, create persistent files, mutate jobs, or alter workflow
  state.
- The app must remain useful when no provider is configured.

## The Problem Decomposed

This work is deliberately split into separate capabilities. Do not merge them into one broad
"artefact AI" feature.

### 1. Artefact Understanding

What do we know about each stored artefact?

### 2. Artefact Suggestion

For one job, which existing artefacts are the best candidates and why?

### 3. Tailoring Guidance

For a chosen artefact, what should be changed to fit the current role?

### 4. Draft Generation

Can the app produce a usable draft resume variant, cover letter, attestation, supporting statement,
or application-answer draft?

### 5. Outcome-Aware Learning

Over time, what kinds of artefacts correlate with interviews, stalls, rejection, or offers for
similar work?

These are separate slices with different risks, inputs, and UI surfaces.

## Artefact AI Roadmap

### Phase A: Artefact Intelligence Foundation

Goal: make artefacts legible to the system before trying to generate new ones.

Implementation targets:

- define the artefact summary contract used by AI prompts;
- support visible artefact analysis records as `AiOutput`;
- add cheap, reliable outcome summaries for linked artefacts;
- keep the system useful even when no extracted document text exists.

Expected result:

- the system can describe what an artefact is for, where it has been used, and what is known about
  its outcomes.

### Phase B: Existing Artefact Suggestion

Goal: for one job, recommend which existing artefacts should be reused or adapted.

Implementation targets:

- add a job-scoped `Suggest artefacts` action in Job Workspace;
- generate visible `artefact_suggestion` outputs;
- rank existing artefacts with reasons;
- detect when no current artefact is a good fit;
- surface when a new artefact type is probably required.

Expected result:

- the user can ask "what should I use for this job?" before they start writing.

This is the recommended first implementation slice.

Current status:

- sub-slice 1 implemented: deterministic shortlist and compact artefact summary helpers now exist
  in the service layer;
- sub-slice 2 implemented: dedicated `artefact_suggestion` prompt contract and service entry point
  now exist in the AI layer, using shortlisted artefact summaries rather than the generic job
  prompt path;
- sub-slice 3 implemented: Job Workspace now exposes `Suggest artefacts` and renders visible
  `artefact_suggestion` output through the existing AI output panel;
- sub-slice 4 implemented: empty shortlist / no-artefact cases now create a visible local fallback
  `artefact_suggestion` record without requiring a configured provider, guiding the user on what to
  prepare first;
- sub-slice 5 implemented: artefact suggestion outputs now expose shortlisted artefact links in Job
  Workspace, and artefact summaries now explicitly mark thin metadata/evidence cases for better AI
  reasoning and clearer user expectations;
- Phase B is now complete for the intended first implementation slice. Further work should move to
  Phase C tailoring guidance rather than expanding more foundation logic here unless a concrete gap
  appears in real use.

### Phase C: Tailoring Guidance

Goal: compare one selected artefact against the job and explain what to change.

Current status:

- sub-slice 1 implemented: the `tailoring_guidance` output contract now exists in the AI layer,
  with a dedicated `artefact_tailoring_v1` prompt path, visible output type support, and a service
  entry point for one selected artefact;
- sub-slice 2 implemented: Job Workspace now exposes an explicit per-artefact tailoring action with
  ownership-safe retrieval and route wiring for one selected artefact;
- sub-slice 3 implemented: tailoring guidance now renders as a first-class visible output in the
  shared AI panel, including a direct link back to the selected artefact so the guidance stays
  actionable in Job Workspace;
- sub-slice 4 implemented: thin metadata artefacts now use a visible local fallback
  `tailoring_guidance` record instead of forcing a low-confidence provider call, while stronger
  artefacts continue through the provider-backed path;
- sub-slice 5 implemented: text-like artefacts can now contribute a verified extracted excerpt to
  tailoring prompts, and tailoring outputs now carry draft-handoff metadata so later draft
  generation can reuse the selected artefact and guidance contract cleanly;
- recommended next step: move into Phase D draft generation planning and implementation, starting
  with visible draft output rather than direct artefact mutation.

Implementation targets:

- add explicit `Suggest tailoring changes`;
- produce visible keep/add/remove/de-emphasise guidance;
- identify missing evidence or required supporting material.

Expected result:

- the user gets a concrete adaptation plan without automatic document mutation.

### Phase D: Draft Generation

Goal: produce usable draft artefacts or required supporting documents.

Current status:

- sub-slice 1 implemented: Phase D now has a provider-backed `draft` generation path in Job
  Workspace for one selected artefact, beginning with `resume_draft`;
- sub-slice 2 implemented: Job Workspace now also exposes `cover_letter_draft` from the same
  selected artefact baseline and shared draft route;
- sub-slice 3 implemented: metadata-only drafts are now labelled explicitly as low-confidence in
  the shared output surface so the user can distinguish scaffolds from text-grounded drafts;
- sub-slice 4 implemented: visible draft outputs can now be promoted explicitly into new markdown
  artefacts linked to the same job, with provenance back to the originating draft and baseline
  artefact, while leaving the baseline untouched;
- sub-slice 5 implemented: Phase D now also supports `supporting_statement_draft` and
  `attestation_draft`, and saved artefact kind/filename mapping now follows the selected draft
  type rather than defaulting to resume-shaped output;
- sub-slice 6 implemented: the artefact library now surfaces saved-draft provenance, including the
  originating AI draft output id and baseline artefact link when available, so promoted drafts stay
  auditable after they leave the job page;
- sub-slice 7 implemented: document extraction support now extends beyond plain text to include
  cross-platform DOCX parsing and best-effort host-backed adapters for legacy Word/RTF and PDF
  files when the runtime can provide text, raising the ceiling on non-text draft quality without
  requiring provider-native document upload yet;
- sub-slice 8 implemented: a narrow `provider_document` path now exists for Gemini-backed drafts
  when no extracted text is available but a supported binary artefact payload can be supplied,
  allowing PDFs and similar documents to be passed directly as model input instead of falling back
  immediately to metadata-only mode;
- draft generation now uses an explicit document context strategy with `content_mode`:
  `extracted_text` when a verified text excerpt is available, `provider_document` when Gemini can
  accept a supported binary artefact directly, otherwise `metadata_only`;
- draft outputs remain visible `AiOutput` records by default, and artefact creation now happens
  only through an explicit user-controlled promotion action; no overwrite path exists.

Target outputs:

- resume variant;
- cover letter;
- supporting statement;
- attestation;
- narrative response;
- application-question draft.

Implementation targets:

- generate visible `draft` outputs first;
- let the user review before saving or exporting;
- support "create from baseline artefact + tailoring guidance" flows.
- prefer canonical extracted text over metadata-only drafting;
- keep provider-native document input as a later adapter, not the first implementation path.

Expected result:

- draft generation exists, but persistent artefact creation remains user-controlled.

Document context strategy:

1. `extracted_text`
   - use verified text excerpts from text-like artefacts such as markdown or plain text;
   - this is the preferred path for higher-confidence drafting.
2. `provider_document`
   - now implemented narrowly for Gemini-backed draft generation when no extracted text is
     available and the artefact is a supported document type;
   - current supported payloads are provider-document handoff for PDFs and compatible document
     formats where raw bytes are available;
   - other providers still fall back to extraction or metadata-only mode.
3. `metadata_only`
   - use artefact metadata, tailoring guidance, and job context when no text extraction exists;
   - drafts from this mode must remain more cautious and scaffold-like.

### Phase E: Outcome-Aware Learning

Goal: use historic outcomes to improve future suggestions.

Implementation targets:

- summarise artefact-outcome patterns conservatively;
- support similarity reasoning without overstating confidence;
- surface evidence counts and uncertainty.

Expected result:

- artefact suggestions improve over time using the user's own history.

## Detailed Plan: Phase B Existing Artefact Suggestion

This phase should be implemented before Phase C or D.

### User Value

When viewing a job, the user should be able to ask:

- which artefact should I start from?
- which other artefacts might still be usable?
- do I need a tailored version?
- am I missing a required artefact type entirely?

The answer should help them move into application preparation with less guesswork.

### Surface

Primary surface:

- Job Workspace, within or adjacent to the artefact section.

Not first surface:

- Artefact Library.
- Focus.
- Inbox.

Reason:

- artefact choice is most useful once a job is accepted into active work and the user is preparing
  for execution.

### Scope

In scope for Phase B:

- rank owned artefacts for a single job;
- produce visible reasons;
- identify missing artefact types;
- identify whether an artefact is suitable as-is vs needs tailoring;
- keep everything advisory only.

Out of scope for Phase B:

- automatic attachment of suggested artefacts;
- automatic file generation;
- full text extraction for every file type;
- semantic search over raw document embeddings;
- application-level or interview-level artefact selection;
- user-editable scoring formulas;
- auto-learning loops.

### Inputs

Phase B should use only inputs that are already available or cheap to derive.

#### Job Context

Use:

- title;
- company;
- status;
- location;
- remote policy;
- source;
- source URL;
- apply URL;
- description;
- known application/interview state if present.

#### User Context

Use the current profile fields:

- target roles;
- target locations;
- remote preference;
- salary range;
- preferred industries;
- excluded industries;
- constraints;
- urgency;
- positioning notes.

#### Artefact Context

For each owned artefact, use:

- filename;
- kind;
- purpose;
- version label;
- notes;
- outcome context;
- updated timestamp;
- linked jobs;
- linked applications or interviews when available;
- coarse outcome summary derived from linked job/application state.

#### Historic Outcome Signals

Keep this lightweight in Phase B.

Candidate signals:

- linked job count;
- count of linked jobs that reached interviewing;
- count of linked jobs that reached offer;
- count of linked jobs that were rejected or archived;
- recency of successful use;
- whether linked jobs resemble the current job by role family or workflow context.

Do not claim strong causality. Present as "used in jobs that later reached interview" rather than
"this artefact causes interviews."

#### Optional Extracted Artefact Text

If text extraction exists later, it can improve quality. It must not be required in Phase B.

The phase should work without extracted content by relying on metadata and linked outcomes.

### Retrieval Strategy

Do not send the whole artefact corpus to the model.

Phase B should use a two-step retrieval process:

#### Step 1: Deterministic Preselection

Gather all artefacts owned by the user, then build a shortlist using deterministic filters:

- prefer artefacts of kinds relevant to submission, such as resume, cover_letter, attestation,
  writing_sample, or other job-facing materials;
- prefer artefacts already linked to jobs;
- prefer artefacts with purpose/version metadata;
- optionally bias towards more recently updated artefacts;
- optionally bias towards artefacts linked to jobs that reached interview/offer.

The shortlist should be capped, for example top 5 to 8 artefacts.

#### Step 2: AI Ranking Over Compact Summaries

Pass the job context, user context, and compact summaries for the shortlisted artefacts to AI.

The AI should:

- name the best starting artefact if one exists;
- name secondary candidates if they are plausible;
- say when none of the candidates is strong enough;
- identify missing artefact types;
- describe what kind of tailoring is likely required before submission.

### Prompt Contract

Phase B should use a dedicated `artefact_suggestion` prompt shape, not reuse fit summary or generic
recommendation prompts.

The prompt should instruct the model to produce sections like:

- `Best starting artefact`
- `Other usable candidates`
- `Missing artefacts`
- `Why`
- `What to adapt before submission`

Prompt rules:

- be concrete;
- do not invent unseen document content;
- distinguish strong match vs partial match;
- prefer "no suitable artefact" over weak guesswork;
- use metadata and outcome summaries conservatively;
- mention uncertainty when artefact metadata is thin.

### Output Contract

Store results as visible `AiOutput` with:

- `output_type = "artefact_suggestion"`
- `job_id` set
- `artefact_id = null` for the top-level suggestion record
- `source_context` including:
  - `surface = "job_workspace"`
  - target `job_uuid`
  - shortlisted artefact UUIDs
  - provider label/model
  - prompt contract version

Suggested source context shape:

```json
{
  "surface": "job_workspace",
  "job_uuid": "job-uuid",
  "shortlisted_artefact_uuids": ["a1", "a2", "a3"],
  "prompt_contract": "artefact_suggestion_v1",
  "provider_label": "Gemini"
}
```

The body should be markdown, following the same safe-render subset already supported elsewhere.

### UI Plan

Primary UI location:

- Job Workspace artefact area.

Controls:

- `Suggest artefacts`

Potential later follow-ups, but not in the first slice:

- `Suggest cover letter approach`
- `Suggest supporting documents`
- `Suggest tailoring changes`

Display:

- show the visible AI output near the artefact section;
- include links to recommended existing artefacts where the output references them;
- include a clear advisory note:
  - no artefacts were attached automatically;
  - no new files were created automatically.

### Missing Artefact Handling

The feature must handle the case where the user has no useful artefacts.

Expected behavior:

- if no artefacts exist, say that clearly and suggest what to prepare first;
- if artefacts exist but none fit well, say so and identify the missing type;
- if a role appears to need extra materials like cover letters, attestations, or supporting
  statements, mention those as recommended next preparation steps.

### Data Model and Service Boundaries

Phase B should avoid schema churn unless the existing models prove insufficient.

Preferred approach:

- keep using `AiOutput` for the visible suggestion record;
- add deterministic artefact summarisation helpers under `app/services/artefacts.py` or a related
  helper module;
- add one AI service entry point for artefact suggestion rather than overloading generic job prompt
  code with large conditionals.

Recommended service split:

- `list_candidate_artefacts_for_job(...)`
- `summarise_artefact_for_ai(...)`
- `generate_job_artefact_suggestion(...)`

This keeps retrieval, summarisation, and AI execution separable and testable.

### Acceptance Criteria

Phase B is complete when:

- a user can generate an artefact suggestion from Job Workspace;
- the suggestion is stored visibly as `artefact_suggestion`;
- only owned artefacts are considered;
- the suggestion explains best candidate, secondary candidates, or missing artefacts;
- no artefact is attached automatically;
- no new file is created automatically;
- the page remains useful when no provider is configured, with a clear visible error.

### Test Plan

#### Unit and Service Tests

Add tests for:

- owner-scoped artefact retrieval;
- deterministic shortlist behavior;
- artefact summary generation from metadata/outcome context;
- jobs with no artefacts;
- jobs with several plausible artefacts;
- jobs where one artefact has stronger prior outcomes than others.

#### Route Tests

Add tests for:

- visible `Suggest artefacts` control in Job Workspace;
- creation of visible `artefact_suggestion` output;
- provider missing/disabled error path;
- no auto-linking or file creation after suggestion.

#### Manual Checks

Verify:

- suggestion appears on the correct job;
- suggested artefacts are all owned by the current user;
- linked/job-relevant artefacts rank above obviously unrelated ones;
- missing artefact advice appears when appropriate;
- markdown output renders cleanly.

### Implementation Order

Recommended sub-slices inside Phase B:

1. Deterministic artefact shortlist and summary helpers. Implemented.
2. AI service prompt contract for `artefact_suggestion`. Implemented.
3. Job Workspace action and visible output rendering. Implemented.
4. Error handling and no-artefact UX. Implemented.
5. Optional linking affordances from suggestion output back to artefact cards. Implemented.

### Risks and Controls

Risk: weak metadata leads to poor suggestions.

Control:

- make uncertainty explicit;
- encourage better metadata;
- avoid overclaiming relevance.

Risk: prompt bloat from too many artefacts.

Control:

- deterministic shortlist before AI call.

Risk: user assumes suggestions auto-attach artefacts.

Control:

- clear UI copy and no hidden workflow mutation.

Risk: outcome-aware reasoning becomes pseudo-scientific.

Control:

- present evidence conservatively as prior usage context, not causal truth.

## Later Phases in More Detail

### Phase C Tailoring Guidance

After Phase B is stable, add artefact-specific adaptation guidance:

- compare one selected artefact against the job;
- highlight what to keep, change, strengthen, or remove;
- identify where extra supporting documents are needed.

This should still produce visible `AiOutput`, not document mutation.

## Detailed Plan: Phase C Tailoring Guidance

This phase should begin now that Phase B is complete for the first artefact suggestion slice.

### User Value

Once the user knows which artefact is the best starting point, they should be able to ask:

- what in this artefact already fits this job?
- what should I strengthen?
- what should I cut or de-emphasise?
- what evidence is missing?
- do I need a supporting document in addition to this artefact?

The answer should help the user adapt one selected artefact without forcing them to rewrite from
scratch.

### Surface

Primary surface:

- Job Workspace, launched from one selected artefact.

Secondary trigger source:

- the user may arrive here directly from a Phase B artefact suggestion, but the tailoring action
  itself should still operate on one explicit artefact choice.

Not first surface:

- Artefact Library bulk actions;
- Focus;
- Inbox.

Reason:

- tailoring is specific to one job and one chosen artefact, so Job Workspace remains the correct
  execution surface.

### Scope

In scope for Phase C:

- select one artefact for one job;
- generate visible tailoring guidance;
- compare artefact context against the job and user profile;
- identify strengths to preserve;
- identify gaps and missing evidence;
- identify likely extra document requirements;
- keep everything advisory only.

Out of scope for Phase C:

- automatic file editing;
- automatic creation of a new artefact record;
- exporting a rewritten file;
- multi-artefact merge logic;
- full document generation;
- automatic attachment of extra supporting documents.

### Inputs

Phase C should use richer context than Phase B, but it must still degrade safely when extracted
document text is unavailable.

#### Job Context

Use:

- title;
- company;
- status;
- location;
- remote policy;
- source;
- source URL;
- apply URL;
- description;
- known application/interview state if present.

#### User Context

Use the existing profile fields:

- target roles;
- target locations;
- remote preference;
- salary range;
- preferred industries;
- excluded industries;
- constraints;
- urgency;
- positioning notes.

#### Selected Artefact Context

Always include:

- filename;
- kind;
- purpose;
- version label;
- notes;
- outcome context;
- linked jobs/applications/interviews;
- coarse linked outcome summary;
- metadata quality / missing metadata fields.

#### Optional Extracted Artefact Content

If a text extraction path exists later, Phase C should use it. Until then:

- the phase must still work from metadata alone;
- when extracted content is unavailable, the AI must be told that it is reasoning from artefact
  metadata and history only;
- the output should state uncertainty plainly in those cases.

#### Prior Phase B Suggestion Context

When present, Phase C can consume the latest `artefact_suggestion` record for the job as optional
supporting context, especially:

- why the artefact was shortlisted;
- what type of adaptation was suggested;
- whether the job seemed to require extra materials.

This should be treated as supporting context, not as authoritative truth.

### Selection Contract

Phase C should be driven by an explicit artefact choice, not a hidden heuristic.

Recommended trigger patterns:

1. From a currently linked artefact in Job Workspace:
   - `Suggest tailoring changes`
2. From a Phase B shortlisted artefact reference:
   - `Tailor this artefact`

The action should carry:

- `job_uuid`
- `artefact_uuid`

If the artefact is not owned by the current user or not available in the user’s scope, the route
must fail safely.

### Prompt Contract

Phase C should use a dedicated prompt contract, not `artefact_suggestion` and not generic
recommendation.

Suggested prompt contract name:

- `artefact_tailoring_v1`

Prompt intent:

- compare one selected artefact against one job;
- explain what already fits;
- explain what to add, strengthen, remove, or de-emphasise;
- identify likely missing supporting materials;
- acknowledge when the system lacks extracted artefact text and is reasoning from metadata/history.

Suggested section structure:

- `Keep`
- `Strengthen`
- `De-emphasise or remove`
- `Missing evidence`
- `Supporting documents`
- `How to use this artefact for this submission`

Prompt rules:

- do not invent document content;
- do not claim the artefact already contains evidence unless that is explicitly present in extracted
  text or clearly inferable from metadata/history;
- separate "likely useful emphasis" from "verified present content";
- be concrete and job-specific;
- prefer short, usable guidance over broad editorial theory.

### Output Contract

Store results as visible `AiOutput` with a dedicated output type:

- recommended new output type: `tailoring_guidance`

Store:

- `job_id` set
- `artefact_id` set to the selected artefact
- `source_context` including:
  - `surface = "job_workspace"`
  - `job_uuid`
  - `artefact_uuid`
  - `prompt_contract = "artefact_tailoring_v1"`
  - optional `artefact_suggestion_output_id`
  - flag for whether extracted artefact text was available

Suggested source context shape:

```json
{
  "surface": "job_workspace",
  "job_uuid": "job-uuid",
  "artefact_uuid": "artefact-uuid",
  "prompt_contract": "artefact_tailoring_v1",
  "artefact_suggestion_output_id": 123,
  "used_extracted_text": false
}
```

The body should remain markdown and use the same safe-render subset already used elsewhere.

### UI Plan

Primary location:

- Job Workspace artefact section.

Controls:

- one tailoring action per artefact, for example:
  - `Suggest tailoring changes`

Optional additional entry point:

- when Phase B output lists shortlisted artefacts, each one may later expose a nearby
  `Tailor this artefact` action.

Display:

- render visible tailoring guidance in the common AI output panel;
- label it distinctly so it does not read like a fit summary or generic recommendation;
- keep the selected artefact visible in the card header or supporting metadata.

### Sparse Content / No Extraction Behavior

Phase C must handle three cases clearly:

1. Artefact has extracted text:
   - give stronger content-level guidance.
2. Artefact has no extracted text but rich metadata/history:
   - give higher-level guidance and say that reasoning is metadata-based.
3. Artefact has neither extracted text nor meaningful metadata:
   - say that the adaptation plan is limited;
   - recommend improving metadata or starting with a better baseline artefact.

This should not be treated as an error case unless the artefact cannot be resolved at all.

### Data Model and Service Boundaries

Recommended service split:

- `get_tailoring_target_artefact(...)`
- `summarise_selected_artefact_for_tailoring(...)`
- `generate_job_artefact_tailoring_guidance(...)`

Keep separation between:

- artefact retrieval and ownership checks;
- summarisation/context assembly;
- AI prompt construction;
- provider execution;
- visible record persistence.

If a new output type is added, update:

- AI service constants;
- badge/rendering helpers;
- tests for visible AI output rendering.

### Acceptance Criteria

Phase C is complete when:

- a user can request tailoring guidance for one selected artefact from Job Workspace;
- the resulting guidance is stored visibly and tied to both the job and the artefact;
- ownership boundaries are preserved;
- the guidance distinguishes what to keep, strengthen, remove/de-emphasise, and what is missing;
- sparse/no-extraction cases remain useful and explicit;
- no artefact file is modified automatically;
- no new artefact file is created automatically.

### Test Plan

#### Unit and Service Tests

Add tests for:

- explicit artefact selection and owner scoping;
- prompt assembly for metadata-only vs extracted-text cases;
- output/source-context contract;
- sparse metadata behavior;
- optional inclusion of supporting Phase B suggestion context.

#### Route Tests

Add tests for:

- tailoring action renders on Job Workspace artefacts;
- successful guidance creation for a selected artefact;
- missing/foreign artefact access fails safely;
- visible output appears on return to Job Workspace.

#### Manual Checks

Verify:

- the selected artefact is obvious in the resulting guidance;
- metadata-only artefacts produce cautious guidance;
- richer artefacts produce more concrete adaptation advice;
- no auto-modification occurs;
- markdown output remains readable.

### Implementation Order

Recommended sub-slices inside Phase C:

1. Decide and add the output contract for `tailoring_guidance`. Implemented.
2. Artefact selection and ownership-safe retrieval from Job Workspace. Implemented.
3. Tailoring prompt/service path using selected artefact + job + profile context. Implemented.
4. Job Workspace action and visible rendering. Implemented.
5. Sparse/extraction fallback behavior. Implemented for thin metadata without extracted text.
6. Optional handoff path to future draft generation. Implemented as source-context preparation.

### Risks and Controls

Risk: the model overstates what is already in the artefact.

Control:

- separate verified context from inferred recommendations;
- include an explicit metadata-only mode in the prompt.

Risk: users expect the document itself to be rewritten.

Control:

- keep the output framed as guidance only;
- reserve actual rewritten output for Phase D draft generation.

Risk: the feature becomes noisy if every artefact gets its own large guidance block.

Control:

- require explicit action per artefact;
- keep the output tied to one selected artefact.

Risk: output type ambiguity between guidance and drafts.

Control:

- add a dedicated `tailoring_guidance` output type rather than overloading `draft`.

### Phase D Draft Generation

When generation is added, the draft should remain a visible AI output first.

User-controlled follow-up actions can later include:

- copy/export draft;
- save draft as new artefact;
- replace nothing automatically.

### Phase E Outcome-Aware Learning

Only after the earlier phases are stable should the system generalise from history.

This phase should rely on:

- enough historic outcome density;
- explicit uncertainty;
- concise summarised evidence rather than opaque scoring.

## Resume Protocol

When resuming this work in a future session:

1. Start with this document.
2. Confirm which phase is in scope.
3. If Phase B, begin with the deterministic shortlist/service layer before UI work.
4. Keep AI output visible and non-mutating.
5. Update this document and `project_tracker/PUBLIC_SELF_HOSTED_ROADMAP.md` when a slice lands.
