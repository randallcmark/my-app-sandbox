# Application Tracker Composite Product Vision

## Document purpose

This document combines the current product thinking into one concise artifact that can be used for product alignment, design direction, and implementation guidance.

It intentionally balances:
- the near-term product that must be proven in practical use
- the longer-term vision that could extend beyond a single job search
- explicit product tenets
- clear boundaries around what the product is and is not
- research notes that support the current strategic direction

---

## Product ambition

Application Tracker begins as a goal-aware job-seeking workspace.

If proven through real usage and users, it could evolve into a broader career opportunity tool that stays useful beyond a single search cycle.

That long-term outcome should not be assumed. It must be earned.

The immediate goal is to solve a specific and painful problem well:

**Help a jobseeker identify, assess, pursue, and learn from the right opportunities with less friction and better judgement.**

---

## Core product vision

**Application Tracker is a user-first opportunity workspace that helps a person move from intent to next role, and potentially over time from one career opportunity cycle to the next.**

It should combine:

- clear workflow management
- practical execution support
- AI guidance grounded in the user’s goals, artefacts, and captured jobs
- low-friction transitions to the external systems where applications are actually completed
- durable memory so the user does not have to start from zero each time they re-enter the market

---

## Product thesis

A job search has two equally important sides:

### 1. Workflow orchestration
The user needs a clean, action-oriented way to organise work, maintain momentum, and know what deserves attention now.

### 2. Real application graft work
The user needs help doing the actual work:
- finding the right roles
- deciding what is worth pursuing
- shaping stronger applications
- selecting and improving artefacts
- managing the fragmented external systems involved in applying

Most products emphasise one side and under-serve the other.

Application Tracker should do both.

---

## Longer-term vision

The longer-term opportunity is not simply “be a better job tracker.”

It is to become a **career opportunity companion** that remains useful across changing goals and career cycles.

That does not mean trying to keep the user in permanent job-search mode.

It means preserving enough relevance that the product can still provide value when the user is:

- actively searching
- quietly exploring
- settled in a role but open to exceptional opportunities
- not open to interruption and wanting only minimal background monitoring

This longer-term vision depends on proving that the product can do two things well:

1. deliver strong immediate utility during active search
2. remain trusted and non-intrusive between searches

---

## User modes

The product should behave differently depending on the user’s current mode.

### Active search
The user wants:
- frequent workflow support
- recommendation intake
- application help
- task management
- follow-up support
- execution velocity

### Quiet exploration
The user is not fully searching but is open to relevant possibilities.
The product should:
- reduce noise
- surface only stronger matches
- preserve lightweight awareness
- ask for occasional feedback

### Settled / monitoring
The user has found a role and does not want to be pushed back into stressful search behaviour.
The product should:
- continue background monitoring only if enabled
- apply a much higher relevance threshold
- communicate rarely
- focus on “worth knowing” rather than “apply now”

### Unavailable / do not disturb
The product should:
- remain quiet
- preserve data and memory
- avoid active opportunity prompting
- allow the user to return later without rebuilding context

---

## Product tenets

### 1. The user’s current goal is the primary anchor
The product should either infer or explicitly capture what the user is trying to achieve now.

This goal must shape:
- recommendations
- AI guidance
- prioritisation
- suggested artefacts
- timing and tone of notifications

### 2. Organisation and execution are equal citizens
The board matters, but the product is not just a board.
The user must be helped not only to organise work, but to complete meaningful work.

### 3. AI must be embedded in the flow of work
AI should appear where the user is already deciding or doing work:
- intake
- triage
- job workspace
- artefact selection
- application shaping
- follow-up support

It should not feel like a detached novelty feature.

### 4. The user’s artefact corpus is a strategic asset
Over time, the user builds a valuable body of material:
- resumes
- cover letters
- tailored variants
- notes
- applications
- interviews
- responses
- outcomes

This corpus should improve the quality and relevance of guidance.

### 5. External systems are part of the product journey
The real job application process is fragmented across:
- job boards
- employer sites
- ATS flows
- document editors
- email

The product should design for those transitions rather than pretending they do not exist.

### 6. Entry paths should reflect user intent
Not all jobs should enter the same way.

- system-sourced recommendations should flow into Inbox or triage
- user-curated roles saved intentionally from outside should enter a more appropriate active stage

### 7. The product must earn the right to interrupt
Especially between searches, the product should only surface opportunities when there is a strong reason to do so.

Noise destroys trust.

### 8. Privacy and user ownership are strategic, not decorative
This product handles deeply personal and sensitive material.
User control, clear boundaries, and data ownership should remain core to the architecture and positioning.

---

## Product is / is not

### The product is
- a goal-aware job-seeking workspace
- a user-first opportunity system
- a place to organise workflow and complete real work
- an AI-assisted layer grounded in user goals, artefacts, and opportunity context
- a continuity tool across fragmented external systems
- potentially, if proven, a longer-term career opportunity companion

### The product is not
- just a kanban board
- just a resume scorer
- just a job alert engine
- just a browser clipper
- a recruiter marketplace
- an employer-first sourcing platform
- a social network
- a tool that should read through a user’s unrelated private inbox by default
- a product that should pressure settled users into unnecessary job churn

---

## Opportunity intake model

The product should support multiple intake paths.

### 1. System-recommended opportunities
These are not yet user-qualified.
They should enter Inbox or a review surface for triage.

### 2. User-curated opportunities
If the user actively saves a role from LinkedIn, a job board, or an employer site, they have already performed a meaningful level of curation.
These should not be forced back to the very start of the flow.

### 3. Email-derived opportunities
Notifications, employer replies, ATS responses, and other career-related email can be ingested where relevant.

### 4. Browser and API ingestion
Capture remains an important practical wedge because the ecosystem is fragmented and direct native integrations may not exist initially.

---

## Email direction

A dedicated career inbox is strategically attractive because it reduces contamination of the user’s private inbox and keeps career communications in a bounded domain.

### Email principles

#### The product should support a dedicated career mailbox concept
This could be:
- a dedicated Gmail or other mailbox chosen by the user
- a user-owned alias or routing setup
- a future product-assisted inbox model if proven necessary

#### The product should not require scanning a user’s unrelated private email
The application should not sift through personal mail that has nothing to do with career activity.

#### The user should retain choice
The user should be able to choose:
- their own inbox
- a dedicated career inbox
- a forwarding or routing strategy
- whether the product monitors email at all

### Current strategic preference
Prefer user-chosen or user-owned inbox patterns over a centrally hosted mailbox service, at least initially.

Centralised mailbox ownership may create too much operational, privacy, and trust burden too early.

---

## Between-search stickiness hypothesis

The likely answer to between-search stickiness is not “more jobs.”
It is **quiet opportunity vigilance**.

The product keeps scanning in the background, uses the user’s goals and corpus to assess relevance, and interrupts very rarely when something appears genuinely worth considering.

The product should aim to become:
- useful memory
- quiet monitoring
- selective opportunity awareness
- lightweight career readiness support

It should not become a constant source of recruiter-style stress.

---

## What must be proven

### Near-term
- users actually get value from a goal-aware workflow and execution tool
- AI guidance grounded in user artefacts is perceived as useful
- browser and email ingestion reduce friction enough to matter
- the product helps users create stronger applications and maintain momentum

### Medium-term
- the system can learn enough from feedback and outcomes to improve relevance
- users trust the product to hold and reuse their artefacts
- selective recommendations are better than generic job alerts

### Long-term
- users want the product to stay with them after a successful job move
- quiet monitoring is perceived as useful rather than intrusive
- career opportunity value can persist between active search cycles

---

## Strategic positioning

The strongest current positioning is:

**An open, user-first, goal-aware opportunity workspace for jobseekers.**

Possible longer-term positioning, if proven:

**A personal career opportunity companion that helps a user move through changing goals and opportunity cycles over time.**

The second should remain aspirational until the first is clearly validated.

---

## Research notes supporting current decisions

These notes summarise adjacent products and infrastructure that inform the current strategy.

### Job-board and network-led models
LinkedIn’s public job features focus heavily on search, saved jobs, job alerts, and personalized recommendations based on profile details, searches, and platform activity. This is useful, but it remains centred on search-and-apply behaviour rather than a user-owned career workspace.

LinkedIn also has a Career Hub model focused on helping employees explore internal career paths, including next-role exploration, role guides, and career goal setting. This is closer to the long-term vision, but it is sold primarily in an employer and internal-mobility context rather than as a user-first public career tool.

### Job-search operating tools
Simplify positions itself as “your entire job search,” combining personalized recommendations, tailored resumes, autofill, and a job tracker. It also supports bookmarking jobs from 50+ job boards.

Huntr is similarly closer to an operating tool than a job board. It combines job tracking, AI resume and cover letter support, autofill, a Chrome clipper, interview tracking, and private notes. Huntr also supports saving jobs from hundreds or thousands of sites.

These products validate that there is demand for workflow and execution support outside of any single job board.

### Application optimisation tools
Jobscan is a strong example of a point solution around ATS optimisation. It focuses on keyword matching, match rates, ATS parsing, and formatting compatibility. That validates the need for application-quality support, but it is not a full longitudinal opportunity system.

### Career-goal continuity tools
Teal is the clearest public example of a product trying to stay useful beyond a single job application cycle. Its Career Goal Tracker asks users to define goals, target titles, dates, and salary ranges, and explicitly says it is designed to be used throughout the user’s career journey.

This is important because it suggests there is real demand for goal-aware career continuity, even if the overall category remains fragmented.

### Email and mailbox architecture notes
Cloudflare Email Routing is available on all plans and allows custom addresses to route incoming emails either to verified destination addresses or to Workers with an `email` handler. This supports user-owned forwarding and processing patterns well.

Cloudflare documents Email Routing as free and private by design, and states that it will not store or access emails routed to the user’s inbox.

Cloudflare Email Service is currently in beta and available on the Workers Paid plan. Its pricing page states that inbound email routing is unlimited, and on the free side outbound email sending is restricted to account-owned verified addresses.

AWS SES remains a possible pay-as-you-go option, but its pricing page states that the commonly cited free use is limited and time-bound rather than a permanent free mailbox solution.

### Strategic implication from the research
The current landscape supports the following conclusions:

- workflow-plus-execution products are real and useful
- explicit career goal support exists but is not yet the dominant public model
- the market is still fragmented across boards, trackers, resume tools, and employer-facing systems
- there is still room for a user-first product that combines goal awareness, artefact intelligence, execution support, and quiet long-term opportunity vigilance
- a dedicated career inbox concept appears productively distinct from mining a user’s private mailbox, but infrastructure choices should preserve user control where possible

---

## Product summary

Application Tracker should be built first as a strong, goal-aware job-seeking workspace.

It may later become something broader: a quiet, trusted, career opportunity companion.

To earn that future, it must first prove that it can help users:
- spend time on the right opportunities
- complete stronger applications with less wasted effort
- move through fragmented workflows with less friction
- preserve and reuse their career memory effectively

That is the current strategic direction.
