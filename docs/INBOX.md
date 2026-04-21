# Inbox

Inbox is the review surface for jobs that entered the tracker but are not yet accepted into active work.

```text
http://127.0.0.1:8000/inbox
```

## Intake Metadata

Jobs now carry three intake fields:

- `intake_source`: where the opportunity came from, such as `manual`, `browser_capture`, `api_capture`, `email_capture`, `system_recommendation`, or `scheduled_import`.
- `intake_confidence`: `high`, `medium`, `low`, or `unknown`.
- `intake_state`: `needs_review`, `accepted`, `dismissed`, or `enriched`.

Existing jobs and manual Add Job entries are treated as intentional and use:

```text
intake_source=manual
intake_confidence=high
intake_state=accepted
```

Browser/API captures use:

```text
intake_state=needs_review
```

They appear in Inbox before they show on workflow board views.

## Actions

Accept:

- marks the job as `accepted`;
- moves it to `interested`;
- records an `Inbox accepted` journal entry.

Dismiss:

- marks the job as `dismissed`;
- archives it;
- records an `Inbox dismissed` journal entry.

Review:

- opens a dedicated Inbox review page without changing intake state;
- lets the user clean up title, company, location, source, source/apply URL, and description;
- preserves captured provenance separately from the edited fields;
- records an `Inbox enriched` journal entry when fields change.

Accepting after review uses the edited candidate fields.

## Email Capture

The first email-to-Inbox slice supports manual paste:

```text
http://127.0.0.1:8000/inbox/email/new
```

The pasted email creates an owner-scoped email provenance record and one Inbox candidate.

Captured provenance includes:

- subject;
- sender;
- received timestamp when provided;
- plain text body;
- optional HTML body;
- source provider, currently `manual_paste`.

The created job uses:

```text
intake_source=email_capture
intake_confidence=unknown
intake_state=needs_review
```

Deterministic extraction:

- job title defaults to the email subject;
- description uses the plain text body, falling back to HTML-stripped text;
- source/apply URL uses the first meaningful `http` or `https` URL;
- all extracted URLs are preserved in job structured data;
- obvious unsubscribe, preference, privacy, terms, and tracking-pixel URLs are ignored when selecting the source URL.

If the selected source URL already belongs to one of the user's jobs, the app links the new email
provenance record to that job, records an `Email captured` journal entry, and does not create a
duplicate job.

## Test Instructions

1. Capture a job with the Firefox extension, bookmarklet, or capture API.
2. Open `/inbox`.
3. Confirm the captured job appears.
4. Open `/board?workflow=prospects` and confirm it is not visible there yet.
5. Accept the job from Inbox.
6. Confirm it disappears from Inbox and appears in Prospects as `interested`.
7. Capture another job and dismiss it.
8. Confirm it disappears from Inbox and is archived.
9. Paste a job-board email at `/inbox/email/new`.
10. Confirm the pasted email job appears in Inbox and stays out of Prospects until accepted.
11. Open Review for the pasted email job.
12. Edit title, company, location, source/apply URL, or description.
13. Save review and confirm captured context remains visible.
14. Accept the reviewed job and confirm the active job uses the edited values.
