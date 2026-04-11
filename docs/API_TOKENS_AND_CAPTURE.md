# API Tokens And Capture

API tokens are intended for browser extensions, bookmarklets, and local automation.

Tokens are scoped. The first supported scope is:

```text
capture:jobs
```

Token secrets are shown once when created. The database stores only a hash.

## Create A Token

Log in with a browser session first:

```bash
curl -i \
  -c cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"your-password"}' \
  http://127.0.0.1:8000/auth/login
```

Create a token:

```bash
curl -s \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"name":"Browser extension","scopes":["capture:jobs"]}' \
  http://127.0.0.1:8000/auth/api-tokens
```

Response:

```json
{
  "uuid": "token-uuid",
  "name": "Browser extension",
  "scopes": ["capture:jobs"],
  "token": "ats_secret_shown_once"
}
```

Store the `token` value somewhere safe. It cannot be retrieved again.

## Revoke A Token

```bash
curl -i \
  -X DELETE \
  -b cookies.txt \
  http://127.0.0.1:8000/auth/api-tokens/token-uuid
```

Revocation is owner-scoped. A logged-in user cannot revoke another user's token.

## Capture A Job

Use the token as a bearer token:

```bash
curl -i \
  -H "Authorization: Bearer ats_secret_shown_once" \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "https://jobs.example.com/product-manager",
    "apply_url": "https://jobs.example.com/product-manager/apply",
    "title": "Product Manager",
    "company": "Example Co",
    "location": "Remote",
    "description": "Own the roadmap.",
    "selected_text": "Interesting role",
    "source_platform": "example_jobs",
    "raw_extraction_metadata": {"extractor": "generic"}
  }' \
  http://127.0.0.1:8000/api/capture/jobs
```

New captures return `201` and `created: true`.

Duplicate captures with the same `source_url` for the same user update the existing job,
return `200`, and include `created: false`.

Response:

```json
{
  "uuid": "job-uuid",
  "title": "Product Manager",
  "company": "Example Co",
  "status": "saved",
  "source_url": "https://jobs.example.com/product-manager",
  "apply_url": "https://jobs.example.com/product-manager/apply",
  "created": true
}
```

## Terminal Smoke Test

This sequence verifies login, token creation, bearer-token capture, duplicate detection, job
listing, and board-state updates.

Start the app in one terminal:

```bash
source .venv/bin/activate
make run
```

In another terminal, set test credentials:

```bash
source .venv/bin/activate
export BASE_URL="http://127.0.0.1:8000"
export EMAIL="you@example.com"
export PASSWORD="change-me"
```

Create the admin user if needed. Skip this if the user already exists:

```bash
.venv/bin/python -m app.cli users create-admin \
  --email "$EMAIL" \
  --password "$PASSWORD"
```

Log in and save the session cookie:

```bash
curl -s -i \
  -c cookies.txt \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
  "$BASE_URL/auth/login"
```

Create a scoped API token and store the returned secret in `TOKEN`:

```bash
TOKEN_RESPONSE=$(
  curl -s \
    -b cookies.txt \
    -H "Content-Type: application/json" \
    -d '{"name":"Terminal smoke test","scopes":["capture:jobs"]}' \
    "$BASE_URL/auth/api-tokens"
)

printf '%s\n' "$TOKEN_RESPONSE"

TOKEN=$(
  printf '%s' "$TOKEN_RESPONSE" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])'
)
```

Capture a job and store its UUID:

```bash
JOB_RESPONSE=$(
  curl -s -i \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "source_url": "https://jobs.example.com/application-tracker-smoke",
      "apply_url": "https://jobs.example.com/application-tracker-smoke/apply",
      "title": "Application Tracker Smoke Test",
      "company": "Example Co",
      "location": "Remote",
      "description": "Created from the terminal smoke test.",
      "selected_text": "Smoke test selected text",
      "source_platform": "terminal",
      "raw_extraction_metadata": {"test": true}
    }' \
    "$BASE_URL/api/capture/jobs"
)

printf '%s\n' "$JOB_RESPONSE"

JOB_UUID=$(
  printf '%s' "$JOB_RESPONSE" |
    python3 -c 'import json,sys; body=sys.stdin.read().split("\r\n\r\n",1)[1]; print(json.loads(body)["uuid"])'
)
```

Run the same capture again. It should return `200 OK` with `"created": false`:

```bash
curl -s -i \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "https://jobs.example.com/application-tracker-smoke",
    "title": "Application Tracker Smoke Test Updated",
    "company": "Example Co"
  }' \
  "$BASE_URL/api/capture/jobs"
```

List visible jobs with the browser session cookie:

```bash
curl -s \
  -b cookies.txt \
  "$BASE_URL/api/jobs"
```

Move the captured job to `interviewing` at board position `4`:

```bash
curl -s \
  -X PATCH \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"status":"interviewing","board_position":4}' \
  "$BASE_URL/api/jobs/$JOB_UUID/board"
```

Fetch that job directly:

```bash
curl -s \
  -b cookies.txt \
  "$BASE_URL/api/jobs/$JOB_UUID"
```

Revoke the API token when finished:

```bash
TOKEN_UUID=$(
  printf '%s' "$TOKEN_RESPONSE" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["uuid"])'
)

curl -i \
  -X DELETE \
  -b cookies.txt \
  "$BASE_URL/auth/api-tokens/$TOKEN_UUID"
```
