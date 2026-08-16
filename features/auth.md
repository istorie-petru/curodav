# Authentication

Single-user login (2026-08-16). The app ships with **no login at all** — the
exact behavior it always had — and gains one only when the operator asks for
it by configuring a single username/password pair.

## How to turn it on

Set both in the environment (the deploy config file, `/etc/curodav/
curodav.env`, or plain shell env for a manual run):

```
CC_AUTH_USERNAME=you
CC_AUTH_PASSWORD=your-password
CC_AUTH_SECRET=optional-long-random-string
```

- **`CC_AUTH_USERNAME` + `CC_AUTH_PASSWORD`** — the one and only account.
  Login is enforced **only when both are set**; either alone (or neither)
  keeps the app fully open, exactly as before (local dev, trusted networks).
- **`CC_AUTH_SECRET`** — optional. The session cookie's signing key. When
  unset it's auto-generated once and stored in the app database (`app_meta`),
  so sessions survive restarts. Set it explicitly if you want to rotate
  sessions by changing the value, or keep it unset and wipe the
  `auth_session_secret` app_meta row instead.

## What it looks like

- A signed-out visitor to any page gets redirected to `GET /login` — a
  minimal standalone page (same `style.css`, no app chrome) with a
  username/password form. A `?next=` query param carries the original
  destination through the login so the user lands back where they were
  headed.
- `POST /login` verifies the pair (constant-time comparison) and sets a
  signed, `HttpOnly`, `SameSite=Lax` session cookie (`cc_session`) valid for
  30 days. Wrong credentials re-render the form with a generic error — 401 —
  without distinguishing "bad username" vs "bad password".
- `POST /logout` clears the cookie and returns to `/login`.

## What's protected

A pure-ASGI middleware (`src/auth.py::AuthMiddleware`, wired in `main.py`)
gates **every** route: pages, `/api/*` (search, quick capture, sync), the
calendar/tasks/contacts export endpoints, everything. It's a middleware —
not a per-router dependency — because that's the only layer that provably
covers routes registered in the future too, so no router can silently forget
auth. Exempt:

- `GET/POST /login` — the point of the feature.
- `/static/*` — shared, cacheable, non-sensitive assets (the browser needs
  the CSS to render the login page itself).
- `GET /sw.js` — the service-worker script, effectively a static asset too
  (its precache list contains no private data); keeping it public lets the
  PWA update while signed out.

For requests that want JSON — any `/api/*` path, the async-CRUD
`X-Requested-With: fetch` header, or an `Accept: application/json` — the
middleware answers **401 JSON** instead of a redirect, so fetch-driven
surfaces never try to parse the login page as JSON. Everything else gets a
**302** to `/login?next=<path>`.

## Session format

Stateless signed cookie, stdlib only (`hmac`/`hashlib`/`secrets`/`base64`):
`base64url(json({"sub": <username>, "exp": <unix ts>})) + "." + HMAC-SHA256`.
Signed, not encrypted — the payload is non-sensitive (a username + expiry)
and signing is what prevents forging a session. No schema change, no new
runtime dependency.

## The `?next=` redirect

Validated by the same `_safe_next` rule routers/tasks.py's work-session
actions use: same-origin relative path only (`/...`), rejecting schemes and
`//host`, so a client-supplied target can't be an open redirect.

## Deploy integration

Both installers' env examples (`deploy/*/curodav.env.example`) now include
commented `CC_AUTH_*` lines. The deploy README's "no authentication" warning
was rewritten: with auth configured, the app protects itself; without it, the
old trusted-network/Tailscale/reverse-proxy guidance still applies.

## Out of scope

- No user management — one account, by design (this is a single-user app;
  see features/README.md's "single-user by design" line).
- No per-path roles or sharing.
- No HTTPS/`Secure` cookie flag handling — the deploy's own threat model is
  a trusted network (Tailscale) or an authenticated reverse proxy; put TLS in
  front if you want `Secure` cookies. The session is a front-door check, not
  a session-revocation mechanism (revoke by changing `CC_AUTH_SECRET` /
  wiping the persisted secret, which invalidates every existing cookie).