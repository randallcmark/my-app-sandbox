# Job Detail

Job detail pages are available at:

```text
http://127.0.0.1:8000/jobs/job-uuid
```

The page requires a logged-in browser session and is owner-scoped. Another user's job returns
`404`.

## Current Behavior

- Shows the captured job title, company, status, board position, source, location, salary,
  captured timestamp, source URL, and apply URL.
- Shows the captured description.
- Shows the job timeline, including `stage_change` events recorded from board movement.
- Adds notes to the timeline.
- Marks a job applied and creates or updates the application record.
- Schedules interviews and shows scheduled interview records.
- Archives a job with an optional timeline note.
- Links back to `/board`.

## Browser Test

1. Start the app:

```bash
source .venv/bin/activate
make run
```

2. Sign in at:

```text
http://127.0.0.1:8000/login
```

3. Open the board:

```text
http://127.0.0.1:8000/board
```

4. Click a card title.

5. Confirm the detail page shows the job fields and timeline.

6. Add a note and confirm it appears in the timeline.

7. Use Mark Applied and confirm the page shows an application record and a timeline event.

8. Schedule an interview and confirm the page shows an interview record and timeline event.

9. Use Archive and confirm the job is archived with a timeline event.

10. Move another job to a different stage on the board, then open the detail page again and confirm the
   new `stage_change` event appears in the timeline.
