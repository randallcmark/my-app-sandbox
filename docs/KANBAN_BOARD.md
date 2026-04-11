# Kanban Board

The first board surface is available at:

```text
http://127.0.0.1:8000/board
```

It requires a logged-in browser session. The root path redirects logged-in users to `/board`;
anonymous users are still sent to `/docs`.

## Current Behavior

- Shows owner-scoped jobs only.
- Hides `archived` jobs.
- Groups cards into the current workflow stages:
  - `saved`
  - `interested`
  - `preparing`
  - `applied`
  - `interviewing`
  - `offer`
  - `rejected`
- Provides previous/next buttons and a status dropdown on each card.
- Persists stage changes with `PATCH /api/jobs/{job_uuid}/board`.

Drag-and-drop ordering is still planned. The current controls are the accessible fallback that
the drag-and-drop behavior can build on.

## Browser Test

1. Start the app:

```bash
source .venv/bin/activate
make run
```

2. In another terminal, create a user, log in, create a token, and capture a job using the smoke
   test in `docs/API_TOKENS_AND_CAPTURE.md`.

3. Open:

```text
http://127.0.0.1:8000/board
```

4. Confirm the captured job appears in `Saved`.

5. Use the card controls to move it to another stage.

6. Refresh the page and confirm the job remains in the new stage.

## Terminal Check

After moving a job in the browser, verify the persisted state:

```bash
curl -s \
  -b cookies.txt \
  "$BASE_URL/api/jobs/$JOB_UUID"
```

The response should include the updated `status`.
