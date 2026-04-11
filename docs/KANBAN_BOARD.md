# Kanban Board

The first board surface is available at:

```text
http://127.0.0.1:8000/board
```

It requires a logged-in browser session. The root path redirects logged-in users to `/board`;
anonymous users are sent to `/login`.

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
- Supports dragging cards within and across columns.
- Persists drag-and-drop ordering with `PATCH /api/jobs/board`.

The buttons and dropdown remain available as the keyboard-friendly fallback.

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
http://127.0.0.1:8000/login
```

4. Sign in with the user credentials.

5. Confirm the captured job appears in `Saved`.

6. Drag the card to another stage, or use the card controls.

7. Refresh the page and confirm the job remains in the new stage.

## Terminal Check

After moving a job in the browser, verify the persisted state:

```bash
curl -s \
  -b cookies.txt \
  "$BASE_URL/api/jobs/$JOB_UUID"
```

The response should include the updated `status`.
