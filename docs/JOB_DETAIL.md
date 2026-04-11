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

7. Move the job to another stage on the board, then open the detail page again and confirm the
   new `stage_change` event appears in the timeline.
