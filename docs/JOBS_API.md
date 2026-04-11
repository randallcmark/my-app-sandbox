# Jobs API

The jobs API is the owner-scoped read and board-update surface for the kanban workflow.

All routes require a logged-in browser session cookie.

## List Jobs

```bash
curl -s \
  -b cookies.txt \
  http://127.0.0.1:8000/api/jobs
```

Archived jobs are hidden by default. Include them with:

```bash
curl -s \
  -b cookies.txt \
  "http://127.0.0.1:8000/api/jobs?include_archived=true"
```

Filter by status:

```bash
curl -s \
  -b cookies.txt \
  "http://127.0.0.1:8000/api/jobs?status=applied"
```

Supported statuses:

```text
saved
interested
preparing
applied
interviewing
offer
rejected
archived
```

## Get One Job

```bash
curl -s \
  -b cookies.txt \
  http://127.0.0.1:8000/api/jobs/job-uuid
```

Jobs are owner-scoped. Another user's job returns `404`.

## Get Job Timeline

```bash
curl -s \
  -b cookies.txt \
  http://127.0.0.1:8000/api/jobs/job-uuid/timeline
```

Status changes are recorded as `stage_change` events. Timeline entries are owner-scoped with
the job.

## Add A Timeline Note

```bash
curl -s \
  -X POST \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"subject":"Recruiter call","notes":"Follow up next week."}' \
  http://127.0.0.1:8000/api/jobs/job-uuid/timeline
```

Notes are stored as `note` events in the same timeline.

## Update Board State

Use this endpoint for kanban stage changes and card ordering:

```bash
curl -s \
  -X PATCH \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"status":"interviewing","board_position":4}' \
  http://127.0.0.1:8000/api/jobs/job-uuid/board
```

Moving a job to `archived` sets `archived_at`. Moving it back to another status clears
`archived_at`. Changing status also creates a `stage_change` timeline event.

## Update Full Board Order

Use this endpoint after dragging cards between columns. Every UUID must belong to the logged-in
user, and a UUID may appear only once.

```bash
curl -s \
  -X PATCH \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{
    "columns": {
      "saved": ["saved-job-uuid"],
      "interested": [],
      "preparing": [],
      "applied": ["applied-job-uuid"],
      "interviewing": [],
      "offer": [],
      "rejected": []
    }
  }' \
  http://127.0.0.1:8000/api/jobs/board
```

The array order in each column becomes the stored `board_position`.
Jobs moved between columns create `stage_change` timeline events.
