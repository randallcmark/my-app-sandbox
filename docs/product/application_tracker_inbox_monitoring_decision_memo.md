# Application Tracker Decision Memo
## Dedicated inbox, quiet monitoring, and user-owned communication strategy

## Purpose

This memo captures the current recommendation for how Application Tracker should handle:

- dedicated career inbox concepts
- active search versus quiet monitoring modes
- user-owned versus centralised email handling
- what to prototype and prove before committing to a heavier architecture

This is a decision-guidance artifact, not a final product specification.

---

## Decision summary

### Recommended direction

Application Tracker should support a **dedicated career inbox model** while keeping the user in control of where career mail lives.

The product should prefer:

- a user-chosen dedicated inbox
- a user-owned alias or routing setup where possible
- bounded career-related email processing only
- explicit product modes that govern how actively the system searches, monitors, and interrupts

The product should avoid, at least initially:

- scanning a user’s unrelated private inbox
- owning or operating a full central mailbox service for all users
- behaving like a constant recruiter feed once a user has landed a job

### Core recommendation

Build toward a model where the product is:

**goal-aware, quiet by default when appropriate, and respectful of inbox boundaries**

---

## Problem statement

The product wants to help users across the full application journey and potentially beyond their next successful move.

That introduces two related challenges:

### 1. Between-search usefulness
When a user is no longer actively searching, the product risks losing relevance unless it can still provide value in a low-noise way.

### 2. Communication overload
Job-seeking communication can become noisy, fragmented, and fatiguing.
Using a user’s main private inbox for this may create the wrong experience and the wrong trust boundary.

The product therefore needs a way to:

- preserve continuity
- support email-derived workflow
- avoid intruding into unrelated personal communications
- remain useful without becoming noisy

---

## Product stance

### Dedicated inbox is desirable
A dedicated inbox or bounded career-mail channel is strategically valuable because it:

- separates career communication from private life
- reduces email fatigue
- creates a cleaner ingestion boundary
- makes parsing and timeline capture more trustworthy
- preserves user confidence that the product is not reading unrelated personal messages

### But central mailbox ownership is high burden
Operating a shared mailbox service for users would introduce significant extra complexity:

- trust and privacy burden
- abuse handling
- deliverability and reputation management
- operational support
- stronger compliance expectations
- drift away from the principle that the user owns their app and data

That makes full central mailbox ownership a poor early default.

---

## Product modes

The communication model should follow the user’s current mode.

### Active search
The product can be more operational:
- higher volume of workflow support
- more intake
- more reminders
- more application assistance

### Quiet exploration
The product should:
- reduce prompts
- surface fewer opportunities
- ask for lighter feedback
- preserve awareness without pressure

### Settled / monitoring
The product should:
- monitor quietly in the background if enabled
- use a much higher threshold before surfacing anything
- favour “worth knowing” over “act now”
- preserve trust by being sparse and selective

### Unavailable / do not disturb
The product should:
- remain quiet
- keep memory intact
- avoid active prompting
- let the user re-enter later without rebuilding context

---

## Option analysis

## Option A: Use the user’s main private inbox

### Description
The product connects to the user’s existing personal mailbox and filters career-relevant content.

### Pros
- easiest for the user in theory
- no need for a second mailbox
- captures all relevant traffic if configured correctly

### Cons
- weak privacy boundary
- user may not want unrelated personal mail processed
- filtering logic becomes complicated and fragile
- user trust may be damaged even if processing is technically bounded
- feels misaligned with the product’s user-first positioning

### Recommendation
Do not use this as the default model.

---

## Option B: User-chosen dedicated inbox

### Description
The user creates or connects a separate inbox used only for job search and career communications.
Examples:
- dedicated Gmail account
- dedicated mailbox with another provider
- workstream-specific personal alias

### Pros
- clear privacy boundary
- simpler user mental model
- easier parsing and timeline capture
- reduces contamination of private mail
- aligns well with user ownership

### Cons
- some user setup friction
- mailbox creation and maintenance live outside the app
- user may not follow through unless guided clearly

### Recommendation
This is the preferred early product direction.

---

## Option C: User-owned alias or routing layer

### Description
The user sets up a dedicated alias or custom address that routes into a mailbox or processing path they control.

### Pros
- preserves user ownership
- supports cleaner addressing
- can route mail through structured processing
- aligns with a self-hosted or Cloudflare-style model

### Cons
- more technical setup
- best suited to users with domains or willingness to configure routing
- not universal enough to be the only path

### Recommendation
Support this as a stronger, more configurable option after the simpler dedicated inbox path.

---

## Option D: App-managed shared-domain aliases

### Description
The product issues addresses on a shared product-managed domain and processes the traffic centrally.

### Pros
- very smooth user experience
- cleaner product-controlled workflow
- easier to standardise

### Cons
- centralises trust and responsibility
- increases operational risk significantly
- introduces abuse and deliverability concerns
- weakens the user-owns-their-instance principle

### Recommendation
Treat as a later-stage option only if demand clearly justifies it.

---

## Option E: Full central mailbox service

### Description
The product becomes the mailbox provider for career communications.

### Pros
- maximum product control
- potentially elegant end-to-end experience

### Cons
- very high complexity
- very high privacy and trust burden
- operationally expensive
- strategically drifts the product into running an email platform

### Recommendation
Do not pursue early.

---

## Recommended phased path

## Phase 1: Dedicated inbox support
Support the user in using a dedicated inbox they choose.

Product responsibilities:
- explain why a dedicated career inbox is useful
- encourage a clean boundary from private mail
- support forwarding or direct monitoring of that inbox
- parse only bounded career-related content

Success criteria:
- users understand the value
- users can connect or use a dedicated inbox with low friction
- email-derived timeline and workflow value is clear

## Phase 2: Alias and routing support
Add support for user-owned aliases or routing patterns where appropriate.

Product responsibilities:
- support cleaner routing setups
- allow structured capture from dedicated addresses
- preserve user ownership and explicit consent

Success criteria:
- more advanced users can create cleaner career-mail channels
- ingestion quality improves
- support burden remains low

## Phase 3: Evaluate whether centralisation is truly needed
Only after real user validation should the product revisit whether shared-domain aliases or hosted mailbox features are justified.

Questions to answer:
- are users blocked without a centrally managed mailbox?
- does the additional convenience materially improve adoption or retention?
- is there enough trust and operational maturity to justify the step?

---

## Quiet monitoring strategy

The longer-term between-search answer should not be frequent recommendation spam.

The proposed model is **quiet opportunity vigilance**.

### What this means
- the product continues polling if the user enables it
- AI-assisted background tasks assess relevance
- the system only surfaces unusually strong opportunities
- notifications become sparse and trust-sensitive
- some notifications may ask for lightweight feedback rather than immediate action

### Why this matters
This preserves the possibility of long-term value without forcing the user back into the stress of active job search.

### Design implication
The product must make it easy for the user to control:
- whether monitoring is on
- how quiet it should be
- what counts as worth surfacing
- whether feedback loops are enabled

---

## What must be proven before heavier architecture

### Product questions
- do users actually want a dedicated inbox model?
- do they trust the product more when inbox boundaries are explicit?
- does email-derived workflow materially improve the product experience?
- does quiet monitoring feel useful rather than intrusive?

### Behaviour questions
- how often do settled users want to hear from the system?
- what threshold makes an alert feel valuable?
- what kinds of feedback requests are acceptable between searches?

### Architecture questions
- can the user-chosen inbox path deliver enough value without centralised mail ownership?
- is alias or routing support sufficient for most users?
- does centralisation solve a real user problem or mainly a product neatness problem?

---

## Decision guardrails

The product should not:

- mine unrelated private inbox content
- default users into noisy recommendations after landing a role
- centralise mail handling just because it is architecturally neat
- create a trust burden before product value is proven

The product should:

- preserve clear boundaries
- keep the user in control
- remain useful without being intrusive
- prefer reversible and low-burden architecture choices first

---

## Current recommendation in one sentence

**Support a dedicated career inbox chosen by the user, pair it with quiet monitoring modes, and delay any centralised mailbox model until real user demand proves it is necessary.**

---

## Next steps

1. Add product language and onboarding support for a dedicated career inbox concept.
2. Define explicit user modes: active search, quiet exploration, settled/monitoring, unavailable.
3. Prototype bounded email ingestion against a dedicated inbox only.
4. Test whether users value quiet monitoring after landing a role.
5. Revisit alias, routing, or centralised mailbox options only after those behaviours are validated.
