# Component Notes

## Purpose

This package breaks the desktop concept into reusable implementation guidance for engineering work.

It is not a production-ready design system. It is a structured reconstruction intended to accelerate implementation.

## Suggested build order

1. App shell
2. Top navigation
3. Focus action cards
4. Recommendation rail
5. Tips card
6. Resume strip
7. Mini work panels
8. Responsive adjustments
9. Motion and micro-interactions

## Component inventory

### AppShell
A glass-like desktop shell over a scenic background.
- rounded corners
- elevated shadow
- translucent top bar
- two-column content layout

### TopNav
Three zones:
- left: nav tabs
- center: current target or goal chip
- right: global actions and profile affordances

### FocusCard
Primary action card for daily momentum.
- header with label and small status icon
- body with context and one dominant action
- should feel operational, not form-like

### RecommendationCard
AI-assisted suggested job unit.
- role
- company/location/salary line
- fit signal
- one primary action
- optional matched skill pills

### TipsCard
A stronger visual treatment for AI drafting or coaching prompts.
- blue gradient
- concise advice
- single clear CTA

### ResumeStrip
Low-height reminder banner for artefact maintenance.

### MiniPanel
Small preview modules representing recent work surfaces or in-progress artefacts.

## Interaction guidance

### Primary interaction model
The home screen should be action-led.
Each card should answer:
- what is this?
- why does it matter now?
- what is the next action?

### Visual behaviour
- avoid excessive colour
- use colour mainly for state and emphasis
- preserve clear hierarchy
- rely on spacing and typography for calmness

### Motion suggestions
- hover rise on actionable cards
- subtle background shift on button hover
- card transitions should clarify state change, not entertain

## Practical guidance for Codex

Codex should treat this package as:
- a reference implementation target
- a component decomposition guide
- a token starting point
- a structural hint for HTML and CSS organisation

It should not treat every value here as mandatory or exact.
