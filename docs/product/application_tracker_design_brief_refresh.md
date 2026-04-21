# Application Tracker Design Brief Refresh

## Design objective

Design a product experience that helps a jobseeker move from goal to next role with less friction, stronger judgement, and clearer momentum.

The design must support both:

- action-oriented workflow management
- practical execution of real application work

## Experience principles

### 1. Design around the user’s current goal
The interface should reflect what the user is trying to achieve now.

Goal context should influence:

- recommendations
- guidance
- prioritisation
- suggested artefacts
- next-step prompts

### 2. Keep workflow calm and action-oriented
The product should always make the next action feel obvious and manageable.

### 3. Put AI where work happens
AI guidance should appear in context, not as a detached feature.

### 4. Treat artefacts as working assets
Resumes, cover letters, tailored variants, notes, and outcomes should actively inform the experience.

### 5. Design transitions across tools
Offboard actions are part of the product journey and should feel deliberate, not broken.

## Core product surfaces

## 1. Focus
The home surface should answer:

- what needs attention today
- what is worth acting on now
- what work is blocked, stale, or urgent
- where the user should resume

This is the command surface for daily momentum.

## 2. Inbox
Inbox is for opportunities that still need user judgement.

This includes:

- system-recommended jobs
- low-confidence captures
- partially enriched roles

Inbox actions should be simple and decisive:

- save for later
- progress to interested or active
- dismiss
- enrich or review

## 3. Active workspace
The active workflow surface should support preparation, application, follow-up, interview progress, and next actions.

It should feel operational, not administrative.

## 4. Job workspace
Each job should open into a real work surface, not just a detail record.

This surface should combine:

- role overview
- fit and confidence guidance
- artefact recommendations
- application progress
- notes and timeline
- contextual next steps
- clean transition points to external tools

## Guidance model

AI guidance should be integrated into specific moments.

### On recommended jobs
- confidence or relevance signal
- brief explanation of fit
- suggested reason to review now

### On curated jobs
- fast readiness assessment
- suggested next stage
- likely artefacts to use

### In the job workspace
- fit assessment
- strengths and gaps
- suggested resume or cover letter starting point
- tailored recommendations
- likely next actions

### During follow-up
- timing suggestions
- reminder prompts
- contextual communication support

## Artefact-aware design

The user’s corpus should be visible and useful.

The design should support:

- seeing which artefacts already exist
- identifying the most relevant artefact for a job
- understanding what can be reused versus tailored
- linking artefacts to outcomes over time

The system should feel increasingly informed as the corpus grows.

## Offboard and integration design language

Many user actions will happen outside the tracker.

The design should support clean movement into:

- employer sites
- ATS application flows
- job boards
- document tools
- email

### Principles for these transitions
- make the next external action explicit
- preserve context before handoff
- make return and continuation easy
- avoid forcing duplicate effort where possible

## Intake logic and stage design

The design must reflect different entry points.

### System-recommended jobs
These should enter **Inbox** because they still need user validation.

### User-saved jobs
These are already user-curated and should enter a more suitable active stage, not reset to the beginning.

This distinction should be reflected clearly in the UI and interaction model.

## Visual direction

The visual design should communicate calm competence.

### Tone
- quiet
- precise
- modern
- supportive
- never noisy or gamified

### Hierarchy
The interface should privilege:

1. user goal
2. next action
3. role and opportunity quality
4. work artefacts and guidance
5. secondary metadata

### Motion
Motion should clarify state changes, transitions, and continuity of work.

### Density
Support both focused reading and high-throughput triage.

## What good looks like

A strong design outcome would allow the user to:

- understand their current goal context at a glance
- triage recommended jobs quickly
- move curated jobs straight into meaningful work
- get contextual AI help without hunting for it
- reuse prior artefacts intelligently
- transition smoothly into external systems
- return to the tracker without losing momentum

## Design summary

The refreshed design direction is not simply “make the board better.”

It is:

**Build a goal-aware job-seeking workspace that combines workflow clarity, embedded guidance, artefact intelligence, and seamless external transitions.**
