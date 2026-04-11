# Authentication Design

This document is the resumable authentication plan for Application Tracker.

The application is self-hosted, but deployments may still be exposed to the public internet. Treat authentication and authorization as production requirements, not optional polish.

Last updated: 2026-04-11

---

## 1. Security Model

Application Tracker owns:

- local user records;
- roles;
- browser sessions;
- API tokens;
- ownership checks.

External identity providers prove identity, but they do not replace local authorization.

Canonical flow:

```text
external identity or local password
        |
        v
local user
        |
        v
role + ownership checks
        |
        v
session cookie or scoped API token
```

This keeps the app flexible across local password auth, Google, Apple, generic OIDC, and reverse-proxy auth.

---

## 2. Supported Auth Modes

### 2.1 Local

`AUTH_MODE=local`

Built-in email/password login.

Required capabilities:

- password hashing with Argon2id;
- DB-backed opaque sessions;
- secure HTTP-only cookies;
- CSRF protection for server-rendered forms;
- first-run admin bootstrap command;
- login rate limiting;
- admin user management;
- session revocation.

This should be the first complete auth mode because self-hosters should not be forced to configure an external identity provider.

### 2.2 OIDC

`AUTH_MODE=oidc`

Generic OpenID Connect login.

Provider-specific documentation should cover:

- Google;
- Apple ID;
- Microsoft;
- Authentik;
- Authelia;
- Keycloak;
- Zitadel.

The implementation should be generic OIDC first, not hard-coded Google or Apple auth.

Core config:

```env
AUTH_MODE=oidc
OIDC_PROVIDER_NAME=Google
OIDC_ISSUER_URL=https://accounts.google.com
OIDC_CLIENT_ID=...
OIDC_CLIENT_SECRET=...
OIDC_SCOPES=openid email profile
OIDC_REQUIRE_VERIFIED_EMAIL=true
OIDC_ALLOW_SIGNUP=true
OIDC_ALLOWED_EMAILS=
OIDC_ALLOWED_EMAIL_DOMAINS=
```

### 2.3 Mixed

`AUTH_MODE=mixed`

Local auth plus OIDC.

Use case:

- normal users use Google/Apple/OIDC;
- admin keeps a local break-glass account.

### 2.4 Reverse Proxy

`AUTH_MODE=proxy`

For advanced self-hosters using a trusted proxy or access gateway.

This mode must be explicit and guarded:

```env
AUTH_MODE=proxy
TRUSTED_PROXY_AUTH=true
PROXY_USER_EMAIL_HEADER=X-Forwarded-Email
PROXY_USER_NAME_HEADER=X-Forwarded-User
```

Never trust user/role headers in default mode.

### 2.5 None

`AUTH_MODE=none`

Development only. Production startup must fail if this is selected.

---

## 3. Data Model

Current auth-related tables:

- `users`
- `api_tokens`
- `auth_sessions`

Planned table:

- `auth_identities`

### 3.1 Users

Local authorization anchor.

Fields:

- email;
- display name;
- password hash, nullable for external-only users;
- admin flag;
- active flag;
- login timestamps.

### 3.2 Auth Identities

External provider linkage.

Recommended fields:

- user id;
- provider;
- provider subject;
- provider email;
- email verified flag;
- display name;
- last used timestamp.

Uniqueness should be based on:

```text
provider + provider_subject
```

not email alone.

### 3.3 Sessions

Browser UI sessions.

Rules:

- browser receives an opaque random token;
- database stores only a hash of the token;
- cookie is HTTP-only;
- cookie is secure in production;
- expired or revoked sessions are invalid.

### 3.4 API Tokens

Browser extension and automation auth.

Rules:

- token secret is shown once;
- database stores only hash;
- tokens are scoped;
- first scope should be `capture:jobs`;
- tokens belong to a user;
- captured jobs inherit that user as owner.

Endpoint usage examples live in `docs/API_TOKENS_AND_CAPTURE.md`.

---

## 4. Production Guardrails

When `APP_ENV=production`, startup must fail if:

- `AUTH_MODE=none`;
- `SESSION_SECRET_KEY` is missing or still set to the development default;
- `PUBLIC_BASE_URL` is not HTTPS, except explicit localhost/dev exceptions should not apply in production;
- proxy auth is enabled without `TRUSTED_PROXY_AUTH=true`.

Future guardrails:

- local auth cannot be enabled without password hashing available;
- OIDC cannot be enabled without issuer, client id, client secret, and public callback URL;
- cookie secure flag cannot be disabled in production.

---

## 5. Implementation Order

### Slice 1: Foundations

Status: Done

- Add auth settings. Done.
- Add production guardrails. Done.
- Add password hashing service. Done.
- Add opaque token hashing helpers. Done.
- Add DB-backed session table. Done.
- Add tests for guardrails, password hashing, and sessions. Done.

### Slice 2: Local Login

Status: Done

- Add first-run admin bootstrap command. Done.
- Add local login/logout routes. Done for JSON and browser form endpoints.
- Add current-user dependency. Done.
- Add secure session cookie issue/clear behavior. Done.
- Add admin/user role checks. Done with `require_admin`.

### Slice 3: CSRF And Ownership

Status: Done

- Add CSRF tokens for server-rendered forms. Done.
- Add centralized ownership helpers. Done.
- Add cross-user access tests. Done.

### Slice 4: API Tokens

Status: Done

- Add API token creation/revocation. Done.
- Add bearer-token auth dependency. Done.
- Add `capture:jobs` scope. Done.

### Slice 5: Generic OIDC

Status: Planned

- Add OIDC configuration.
- Add login/callback flow.
- Add auth identity table.
- Add provider docs for Google.
- Add provider docs for Apple.

### Slice 6: Reverse Proxy Auth

Status: Deferred

- Add explicit trusted proxy mode.
- Add proxy header mapping.
- Add deployment docs for common proxy auth systems.

---

## 6. Resume Notes

When resuming auth work:

1. Read this file.
2. Check `project_tracker/PUBLIC_SELF_HOSTED_ROADMAP.md`.
3. Run `git status -sb`.
4. Continue the next incomplete slice.
5. Keep each slice small and pushed to `main`.

Suggested prompt:

```text
Continue the next incomplete auth slice from docs/AUTHENTICATION.md.
```
