# Application Tracker — Design Language & Visual System

**Version 1.1 · April 2026**  
Confidential — design team use

---

## Table of contents

1. [Design philosophy](#1-design-philosophy)
2. [Colour system](#2-colour-system)
3. [Typography](#3-typography)
4. [Spacing and layout](#4-spacing-and-layout)
5. [Design tokens](#5-design-tokens)
6. [Component system](#6-component-system)
7. [Fit and confidence system](#7-fit-and-confidence-system)
8. [AI guidance design](#8-ai-guidance-design)
9. [Offboard and external transitions](#9-offboard-and-external-transitions)
10. [Surface inventory](#10-surface-inventory)
11. [Elevation model](#11-elevation-model)
12. [Implementation notes](#12-implementation-notes)

---

## 1. Design philosophy

Application Tracker is designed around a single visual personality: **calm precision**. The interface should feel like a well-organised desk — never dashboard-dense, never productivity-app busy. Every surface communicates quiet competence: the user always knows where they are, what needs doing, and what the system thinks without being overwhelmed.

The current implementation also supports a **two-layer visual model**:

- **Outer shell** — scenic backdrop, glass shell, controlled gradients, and selected shadows that frame the workspace.
- **Inner content** — readable token-led cards, forms, tables, and workflow panels that stay calm and structured.

Reference artifact:

- `docs/design/reference/application_tracker_ui_mockup_inspectable.html`

### Core personality traits

- **Quiet** — generous whitespace, muted secondary tones, no decorative noise
- **Precise** — tight typographic hierarchy, consistent component sizing, 0.5px borders
- **Modern** — clean geometry with restrained gradients and shadows only where they clarify shell framing, depth, or emphasis
- **Supportive** — AI guidance that appears in context, never as a feature to hunt for
- **Never noisy or gamified** — no confetti, streaks, scores, or achievement mechanics

### Closest design references

Linear, Notion, and Pitch. Tools that feel intelligent without performing intelligence. The experience should feel native and calm — not like an embedded third-party widget.

Reference fidelity rules:

- Keep closely: scenic backdrop, frosted shell, larger radii, stronger card hierarchy, richer primary CTA treatment.
- Adapt rather than copy literally: illustrative icons, avatar and notification affordances, placeholder content, and personal-dashboard framing.
- Constrain: gradients to shell framing, emphasis surfaces, and primary actions; shadows to shell, elevated cards, and overlays.

---

## 2. Colour system

The palette is structured around semantic roles, not decoration. Each colour communicates something specific. Use them consistently across components, states, and surfaces.

In addition to semantic workflow colours, the shell uses a small framing palette for backdrop, glass, soft elevation, and richer text tiers. Those colours should still be expressed as named tokens rather than one-off literals in route modules.

### Brand — Slate Blue

The primary brand and interactive colour. Used sparingly: interactive elements, active navigation states, focus rings, primary buttons, AI touches. The rest of the UI defers to neutrals.

| Swatch | Hex | Usage |
|--------|-----|-------|
| Slate 50 | `#E8EBF8` | Tinted surfaces, AI block backgrounds |
| Slate 100 | `#C3CCF0` | Borders, chip outlines |
| Slate 300 | `#8EA0E3` | Mid-tone accents |
| **Slate 600** | `#4F67E4` | **Primary interactive — buttons, active nav, links** |
| Slate 800 | `#2D3A9A` | Headings, strong emphasis |
| Slate 950 | `#1A2156` | Darkest text on light surfaces |

### Sage Green — Active / Success

Used for positive workflow states: Interview stage, Offer received, completed steps in progress trackers, positive fit indicators.

| Swatch | Hex | Usage |
|--------|-----|-------|
| Sage 50 | `#EAF4EE` | Stage pill background |
| Sage 100 | `#B6DFC5` | Border |
| Sage 400 | `#6CBB91` | Mid-tone |
| **Sage 600** | `#2A8A58` | **Active stage pills, success states** |
| Sage 800 | `#1A5C38` | Text on sage-light backgrounds |

### Amber — Urgent / Follow-up

Used to signal time pressure: items due today, overdue follow-ups, stale applications. Never used for success or failure — only for urgency.

| Swatch | Hex | Usage |
|--------|-----|-------|
| Amber 50 | `#FDF3E6` | Pill background |
| Amber 100 | `#F9D9A0` | Border |
| Amber 500 | `#E8A020` | Mid-tone |
| **Amber 700** | `#B87800` | **Urgent label text** |

### Coral — Closed / Rejected

Reserved for negative outcomes: closed applications, rejected stages, skill gap indicators. Use only when something has definitively ended.

| Swatch | Hex | Usage |
|--------|-----|-------|
| Coral 50 | `#FDEFED` | Pill background |
| Coral 100 | `#F8C4BE` | Border |
| **Coral 600** | `#D64535` | **Rejection labels, closed stage** |

### Neutrals — Adaptive

The majority of the UI. These adapt automatically to light and dark mode via CSS custom properties. Never hardcode hex values for neutral surfaces.

| Token | Light mode hex | Usage |
|-------|---------------|-------|
| `--color-background-tertiary` | `#F9F9F7` | Page background |
| `--color-background-secondary` | `#F1F0ED` | Section panels, sidebar |
| `--color-background-primary` | `#FFFFFF` | Cards, main content |
| `--color-text-tertiary` | `#888780` | Placeholder, hint text |
| `--color-text-secondary` | `#5F5E5A` | Secondary body text |
| `--color-text-primary` | `#111111` | Primary body text |
| `--color-border-tertiary` | `rgba(0,0,0,0.10)` | Default component borders |
| `--color-border-secondary` | `rgba(0,0,0,0.22)` | Hover and focus borders |

---

## 3. Typography

Two weights only: `400` (regular) and `500` (medium). Never use bold (`700`) — it is too heavy against the quiet UI. Letter-spacing is negative at larger sizes and slightly positive at label sizes for legibility.

### Type scale

| Style | Size | Weight | Tracking | Line height | Usage |
|-------|------|--------|----------|-------------|-------|
| Display | 28px | 500 | −0.02em | 1.2 | Job title in workspace header |
| Heading 1 | 20px | 500 | −0.01em | 1.3 | Page and section headings |
| Heading 2 | 16px | 500 | 0 | 1.4 | Card titles, subsection headings |
| Body | 14px | 400 | 0 | 1.6 | All descriptive and body copy |
| Label / Meta | 12px | 400 | +0.02em | 1.4 | Dates, metadata, secondary labels |
| Caption | 11px | 400 | +0.04em | 1.4 | Overline labels (uppercase), footnotes |

### Rules

- Two weights only — `400` regular and `500` medium. Never use `600` or `700`.
- Sentence case everywhere — never Title Case, never ALL CAPS (except `11px` caption overlines).
- Negative tracking at display and heading sizes (`−0.02em`, `−0.01em`).
- Slightly positive tracking on labels and metadata (`+0.02em`) for small-size legibility.
- Line height: `1.6` for body, `1.2–1.4` for headings, `1.0` for single-line UI labels.
- No mid-sentence bolding — use `code` style for technical names, headings for structural emphasis.

---

## 4. Spacing and layout

All spacing values are multiples of 4px. Use named tokens — never arbitrary values.

### Spacing scale

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | 4px | Icon-to-label gap, badge internal padding |
| `--space-sm` | 8px | Within-component gaps |
| `--space-md` | 12px | Between related elements |
| `--space-lg` | 16px | Between components within a card |
| `--space-xl` | 24px | Card internal padding, section gaps |
| `--space-2xl` | 32px | Between major sections |
| `--space-3xl` | 48px | Page-level vertical rhythm |

### Page layout

- **Sidebar:** 220px fixed — navigation, goal chip, library links
- **Content area:** fluid, 24px horizontal padding
- **Job workspace:** `1fr` main content + `280px` contextual aside panel
- **Max content width:** 1280px — never full-bleed on large screens
- Vertical rhythm is driven by `0.5px` section dividers, not excess whitespace

---

## 5. Design tokens

### Border radius

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-sm` | 6px | Inline chips, badges, small pills |
| `--radius-md` | 10px | Buttons, inputs, small controls |
| `--radius-lg` | 14px | Cards, job tiles |
| `--radius-xl` | 20px | Drawers, modals, large containers |

### Border width

| Token | Value | Notes |
|-------|-------|-------|
| `--border-width` | 0.5px | All component borders — thin borders feel refined |
| `--border-default` | `0.5px solid rgba(0,0,0,0.10)` | Default state |
| `--border-hover` | `0.5px solid rgba(0,0,0,0.22)` | Hover and focus states |
| `--border-featured` | `2px solid (semantic color)` | The only 2px exception — featured cards only |

### Motion

| Token | Value | Usage |
|-------|-------|-------|
| `--transition-fast` | 120ms ease-out | Hover, focus ring appearance |
| `--transition-base` | 200ms ease-out | State changes, pill colour transitions |
| `--transition-slow` | 350ms ease-out | Panel slide, expand/collapse |

Motion should clarify state changes — never animate for decoration. Use easing curves that feel physical, not springy. Always respect `prefers-reduced-motion`.

---

## 6. Component system

### 6.1 Cards and tiles

Cards are the primary container for job opportunities. Two levels of visual weight create hierarchy.

| State | Appearance |
|-------|------------|
| Default | White background · 0.5px `--border-default` · `radius-lg` · 14–16px padding |
| Hovered | Background shifts to `--surface-secondary` · border strengthens to `--border-hover` |
| Active / selected | 2px slate-blue border · 3px left accent strip |
| Featured (inbox) | 2px border on the semantic colour ramp of the job source |

### 6.2 Stage pill system

Stage pills use colour-coded semantic backgrounds. Always fully rounded (`border-radius: 20px`). Never use plain grey for an active stage.

| Stage | Background | Text colour |
|-------|------------|-------------|
| Inbox | `#E8EBF8` | `#2D3A9A` |
| Interested | `#FDF3E6` | `#8C4A00` |
| Applying | `#E8EBF8` | `#4F67E4` |
| Interview | `#EAF4EE` | `#1A5C38` |
| Offer | `#EAF4EE` | `#2A8A58` |
| Closed | `#F1F0ED` | `#888780` |

### 6.3 Buttons

Three variants — use the minimum weight required for the context.

| Variant | Appearance | Usage |
|---------|------------|-------|
| Primary | Filled slate-600 · white text · no border · hover darkens 8% | Primary CTA per surface |
| Outline | 0.5px `--border-secondary` · transparent bg · secondary text | Secondary actions |
| Ghost | No border · no background · secondary text | Tertiary, destructive-confirm |
| Destructive | Filled coral-600 · white text | Irreversible delete actions only |

- All buttons: `radius-md` (10px), 6px vertical padding, 14px horizontal padding
- External link buttons: always append `↗` to communicate the user is leaving the app
- Disabled state: 40% opacity, no hover effect, `cursor: not-allowed`

### 6.4 Inputs and form elements

| Property | Value |
|----------|-------|
| Height | 36px (single-line) |
| Border | 0.5px `--border-default` |
| Border (focus) | 0.5px + 2px focus ring in `slate-200` |
| Border (error) | 0.5px `coral-600` + `coral-50` background |
| Radius | `radius-md` (10px) |
| Padding | 0 12px horizontal |
| Placeholder colour | `gray-400` |

### 6.5 Navigation

| State | Appearance |
|-------|------------|
| Default | Secondary text · transparent bg · 8px vertical, 18px horizontal padding |
| Hover | Primary text · `--surface-primary` background |
| Active | Slate-600 text · slate-50 background · weight 500 |

- Unread counts: small filled badge on the right edge — slate-600 background, white text
- Section labels: 11px uppercase `gray-400` — not interactive

---

## 7. Fit and confidence system

The fit signal communicates AI-assessed relevance between a job and the user's profile. It uses a 5-dot system — simple, non-gamified, readable at small sizes.

| Dots | Meaning |
|------|---------|
| ●●●●● | Strong fit — high confidence recommendation |
| ●●●○○ | Partial fit — worth reviewing with noted gaps |
| ●○○○○ | Low confidence — system-sourced, needs user validation |

| Property | Value |
|----------|-------|
| Dot size | 7px diameter |
| Gap between dots | 2px |
| Filled colour | `slate-600` (`#4F67E4`) |
| Empty colour | `--color-border-tertiary` (neutral adaptive) |

Never show a percentage or score. The dot count communicates enough without creating false precision. The system should feel qualitative, not algorithmic.

---

## 8. AI guidance design

AI guidance is embedded and contextual — it appears where a decision is happening, not as a separate feature or notification. There is no "AI assistant" page or chat interface.

### AI block design

| Property | Value |
|----------|-------|
| Background | `#E8EBF8` (slate-50) |
| Border | `0.5px #C3CCF0` (slate-100) |
| Text colour | `#2D3A9A` (slate-800) |
| Icon marker | `✦` or small circle-dot — consistent across all AI-generated content |
| Border radius | `radius-lg` (14px) |
| Padding | 14px |

### Where AI guidance appears

- **Focus surface** — one daily nudge above the active list. Always dismissible.
- **Inbox** — confidence signal and brief fit rationale on each recommended job tile.
- **Job workspace** — full fit assessment, strengths/gaps list, quick action chips.
- **Artefact selection** — "best match" suggestion when more than one artefact exists.
- **Follow-up** — timing suggestion when a role has gone quiet.

### Tone of AI copy

Direct and specific — never hedged or over-qualified. Write what the system actually thinks.

> ✓ "Your mobile portfolio examples are limited — the interview may probe this."  
> ✗ "You may want to consider reviewing your portfolio examples for mobile coverage."

AI copy should read as if written by a smart colleague, not a chatbot. Short sentences. Present tense. Specific claims backed by what the system can actually see.

### The AI contract with the user

- Every AI block must have at least one actionable chip or button
- Every AI block must be dismissible without penalty
- AI guidance never blocks the user's workflow — it accompanies it
- The system never pretends certainty it does not have

---

## 9. Offboard and external transitions

A significant portion of real application work happens outside the tracker — in ATS systems, job boards, email, and document tools. The design must make these transitions deliberate, contextual, and recoverable.

### The ↗ convention

Any action that navigates outside the tracker uses the `↗` arrow consistently. This is the universal signal that the user is leaving the app. It must appear on all external CTAs without exception.

### External CTA format

External CTAs use a two-line format to preserve context before handoff:

```
Confirm interview slot          ↗
Open Ashby to confirm date
```

- Line 1 (14px medium): the action
- Line 2 (12px secondary): the destination
- `↗` on the right edge

### Return design

When the user returns from an external tool, the tracker resumes context cleanly. The job workspace retains scroll position. Application steps completed externally are updatable in one tap. A subtle "just returned?" nudge can prompt the user to log what happened.

---

## 10. Surface inventory

### 10.1 Focus (home)

The daily command surface. Answers: what needs attention today, what is worth acting on, where to resume.

Structure (top to bottom):
1. Topbar — surface title, today's date, utility actions
2. Stat band — 3 metric cards: active applications / actions due today / new in inbox
3. AI nudge — one contextual prompt, dismissible, with action chips
4. Needs action — jobs with overdue or due-today tasks
5. Worth reviewing — top inbox recommendations ordered by fit score

### 10.2 Inbox

Triage surface for system-recommended and unreviewed opportunities.

Each tile shows: company, title, location, fit dots, brief AI rationale.  
Actions: save for later · progress to interested · dismiss · open for review.  
Bulk triage mode available for power users.

### 10.3 Active workspace

Kanban-style or list view of in-progress applications. Filterable by stage. Card-level detail includes stage pill, next action prompt, and days since last update. Stale items (7+ days inactive) receive a subtle amber border.

### 10.4 Job workspace

The core execution surface. Opens on job tap. Two-panel layout: main content (left) + contextual aside (right).

**Main panel:**
- Header: company logo, title, location, salary band, stage pill, primary CTA
- AI assessment block: fit summary, strengths list, gaps list, action chips
- Application progress: step-by-step timeline with done / active / todo states

**Aside panel:**
- Artefacts in use, with suggested additions
- Timeline log of key events
- External next-step CTA

### 10.5 Artefact library

All user artefacts — resumes, cover letters, tailored variants, notes, interview prep. Each artefact shows: type, version label, last updated date, and which active applications it is linked to. Suggested artefacts for a given job appear in the workspace aside with a `Suggested` badge.

---

## 11. Elevation model

Elevation is expressed entirely through background contrast and border weight — never through shadows. This keeps the visual language flat and precise across light and dark mode.

| Level | Token | Description |
|-------|-------|-------------|
| 0 — Page | `--color-background-tertiary` | Outermost page surface |
| 1 — Panel | `--color-background-secondary` | Sidebar, section panels, drawer backgrounds |
| 2 — Card | `--color-background-primary` + 0.5px border | Job tiles, artefact cards |
| 3 — Hovered | `--color-background-secondary` + stronger border | Visual hover feedback |
| 4 — Modal | `--color-background-primary` + 1px border + body overlay | Modals and drawers |

---

## 12. Implementation notes

### Dark mode

All colour tokens use the adaptive CSS variable system. Never hardcode hex values for UI colours — always use the token layer. The semantic colour palette (sage, amber, coral, slate) has explicit light/dark stop pairs and must be tested in both modes before shipping any new component.

### Accessibility

- Minimum contrast ratio 4.5:1 for body text, 3:1 for large text and UI components
- All interactive elements have visible focus rings — 2px offset, `slate-200`
- Do not rely on colour alone to convey state — pair with iconography or text labels
- All AI-generated content must be labelled as such for screen reader users

### Motion and animation

- All transitions reference the motion token system — no ad-hoc duration values
- Wrap all non-essential animations in `prefers-reduced-motion: no-preference`
- If removing an animation breaks comprehension, keep it. If not, remove it.

### Design handoff

- Export component specs at 1× with all design tokens mapped
- Include all state variations (default, hover, focus, active, disabled, error) for every interactive component
- AI guidance copy is written by product — designers provide the structural template, not the final strings
- Stage colours and semantic tokens must be documented in the Figma token plugin before implementation begins

---

*End of document — Application Tracker Design Language v1.0*
