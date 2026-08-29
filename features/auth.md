# Authentication

Single-user login (2026-08-16). The app's **local-dev/manual-run default**
still has no login at all — the exact behavior it always had — and gains one
only when the operator asks for it by configuring a single username/password
pair. **2026-08-29:** the two real deploy paths (systemd, Docker) now default
to *requiring* an account instead, via a forced first-run setup page — see
"Deploy-mode default" below.

## How to turn it on manually (local dev, or a pre-configured deploy)

Set both in the environment (the deploy config file, `/etc/curodav/
curodav.env`, or plain shell env for a manual run):

```
CC_AUTH_USERNAME=you
CC_AUTH_PASSWORD=your-password
CC_AUTH_SECRET=optional-long-random-string
```

- **`CC_AUTH_USERNAME` + `CC_AUTH_PASSWORD`** — the one and only account.
  Login is enforced **whenever both are set** (or a first-run setup account
  exists, see below); for `CC_DEPLOY_MODE=local` (the default — local dev,
  manual runs), leaving both unset keeps the app fully open, exactly as
  before.
- **`CC_AUTH_SECRET`** — optional. The session cookie's signing key. When
  unset it's auto-generated once and stored in the app database (`app_meta`),
  so sessions survive restarts. Set it explicitly if you want to rotate
  sessions by changing the value, or keep it unset and wipe the
  `auth_session_secret` app_meta row instead.

## Deploy-mode default (2026-08-29)

`CC_DEPLOY_MODE` (`src/config.py`) controls whether an unconfigured install
is allowed to stay open:

- **`local`** (the default for any manual/unrecognized run) — unchanged:
  open unless you set the `CC_AUTH_*` pair yourself.
- **`production`** — baked into `deploy/systemd/curodav.service` and the
  `deploy/docker/Dockerfile` image, *not* meant to be set casually in the
  env file. An install in this mode with no account configured (neither the
  env pair nor a persisted one, below) is forced to `GET/POST /setup` —
  every other route redirects there (or, for `/api/*`/fetch requests, a
  401) until an account is created. `src/auth.py::setup_required` is the
  single source of truth for this; `AuthMiddleware` enforces it and caches
  "already configured" on `app.state` once true (reset by Settings > Purge
  all).

## First-run setup (`/setup`)

The page a forced-production install lands on: pick a username and password
(8+ characters, confirmed twice) and submit. `routers/auth.py::setup_submit`
persists the account **hashed** (PBKDF2-HMAC-SHA256, 260k iterations,
`src/auth.py::hash_password`) in `app_meta` — `auth_username` +
`auth_password_hash`, the same "persist in app_meta, not disk config"
convention the auto-generated session secret already uses — then logs the
browser straight in and redirects home. Once an account exists this way (or
via the env pair), `/setup` refuses to run again: both the middleware (a
configured install requires a valid session to even reach `/setup`) and the
route itself (`setup_required()` re-checked on every call) treat it as
already done, so it can never be used to overwrite an existing account.

`/setup` also offers an optional, skippable "Connect to a CalDAV/CardDAV
server" section (Radicale URL/username/password) when the environment
hasn't already configured one (`config.py::radicale_env_configured`, true
when `CC_RADICALE_URL` was set — e.g. by `--with-radicale`'s auto-generated
credentials). Submitted values are persisted in `app_meta`
(`config.RADICALE_URL_KEY`/`RADICALE_USERNAME_KEY`/`RADICALE_PASSWORD_KEY`)
and applied on the *next* restart (`main.py`'s lifespan calls
`config.apply_persisted_radicale_overrides` before building the
`CalDavBridge`, which itself is only ever constructed once at process
start — no live reload). Unlike the app's own login password, the Radicale
password is stored retrievable, not hashed: the app has to replay it as an
HTTP Basic Auth credential on every sync request. Since `/setup` only ever
renders once per install, the same fields are also editable later from
Settings > Data & Maintenance's "CalDAV / Radicale sync" card
(`routers/settings.py::settings_radicale`) — same persistence, same
"takes effect after a restart" caveat, and also a no-op display when
env-configured.

## What it looks like

- A signed-out visitor to any page gets redirected to `GET /login` — a
  minimal standalone page (same `style.css`, no app chrome) with a
  username/password form. A `?next=` query param carries the original
  destination through the login so the user lands back where they were
  headed.
- `POST /login` verifies the pair (constant-time comparison, either the env
  pair or a persisted /setup account) and sets a signed, `HttpOnly`,
  `SameSite=Lax` session cookie (`cc_session`) valid for 30 days. Wrong
  credentials re-render the form with a generic error — 401 — without
  distinguishing "bad username" vs "bad password".
- `POST /login` is rate-limited per client IP (`src/auth.py::
  login_rate_limited`/`record_failed_login`) — 5 failed attempts within a
  15-minute rolling window get a 429 instead of a credential check. In-memory
  only (module-level, no schema change); counters reset on a process
  restart, an accepted gap for a personal single-user app.
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
- `GET/POST /setup` — conditionally public: only reachable when
  `setup_required()` is true (see "Deploy-mode default" above); once an
  account exists it requires a valid session like everything else.
- `/public/*` (2026-08-29) — Published Lists' standalone public feed
  (`routers/public_lists.py`, `features/published-lists.md`). Unlike every
  other exemption above, this one is checked *before* the forced-setup
  redirect too, so a link already shared with someone outside the
  household keeps working even while the operator is mid-setup.

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
runtime dependency. Cookie flags: `HttpOnly`, `SameSite=Lax`, `Path=/`, and
(2026-08-29) `Secure` whenever the request's own scheme is `"https"`
(`src/auth.py::is_secure_request`) — both deploys already pass uvicorn
`--proxy-headers`, so this is accurate behind a TLS-terminating reverse
proxy too, not just for the app serving TLS directly. Omitted over plain
HTTP (the common LAN/Tailscale case) since a `Secure` cookie sent over HTTP
would just get silently dropped by the browser, locking the operator out.

## The `?next=` redirect

Validated by the same `_safe_next` rule routers/tasks.py's work-session
actions use: same-origin relative path only (`/...`), rejecting schemes and
`//host`, so a client-supplied target can't be an open redirect.

## CSRF protection (2026-08-29)

`src/auth.py::CSRFMiddleware`, wired in `main.py` just inside
`AuthMiddleware` (Auth runs first, so an unauthenticated forged request
gets Auth's normal 401/redirect and never reaches this check). For any
state-changing request (not GET/HEAD/OPTIONS/TRACE) that carries the
`cc_session` cookie, it verifies the `Origin` (or, failing that, `Referer`)
header's host matches the request's own `Host`, rejecting with a 403 JSON
response when it doesn't (or when both headers are missing — a mutating
request with neither is treated as suspicious rather than assumed
same-origin). A request with no session cookie skips the check entirely —
without a cookie there's no ambient credential for a forged cross-site
request to ride on, so the check is a no-op exactly like the rest of this
feature on a fully-open install.

This is Origin/Referer verification, not a per-form CSRF token — no
template or `fetch()` call anywhere in the app needed to change. OWASP's
CSRF prevention cheat sheet lists Origin verification as an accepted
primary defense in its own right, and it's a second, explicit layer on top
of what `SameSite=Lax` (the session cookie's own flag) already blocks in
current browsers. One known gap: the `/login` and `/setup` POSTs
themselves run before any session cookie exists, so they're not covered by
this middleware (a "login CSRF" is a narrower, lower-severity concern than
what this protects — a signed-in session being used to mutate data — and
is out of scope here).

## Security response headers (2026-08-29)

`src/security_headers.py::SecurityHeadersMiddleware`, wired in `main.py` as
the outermost middleware (added last, after CSRF and Auth) so these land on
*every* response, including a 302/401/403 another middleware short-circuits
— a denied response is still one a browser renders/acts on. Unconditional,
no settings dependency, applies whether or not login is even configured:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY` + CSP's `frame-ancestors 'none'` (clickjacking —
  this app has no legitimate reason to render inside another site's iframe;
  two headers for the same protection since some older user agents only
  honor the first)
- `Referrer-Policy: strict-origin-when-cross-origin` — tightened now that
  Published Lists' public links (`features/published-lists.md`) put an
  unguessable token in a URL path; cross-origin navigation only gets the
  origin, same-origin still gets the full path (needed for this app's own
  `?next=`/`?note=` conventions)
- `Content-Security-Policy` — `default-src 'self'` plus `'unsafe-inline'`
  on `script-src`/`style-src`. Stated tradeoff, not an oversight: this
  app's templates use inline `<script>`/`<style>` and inline event-handler
  attributes throughout, and a strict nonce-based CSP would need threading
  a per-request nonce through every template — out of scope for this
  slice. The policy still meaningfully restricts a successful XSS (no
  cross-origin script/object loading, no arbitrary `form-action`, no
  framing).
- `Strict-Transport-Security` — only when the request's own scheme is
  `"https"` (same `--proxy-headers`-aware check as the `Secure` cookie
  flag above); omitted over plain HTTP since browsers ignore it there
  anyway and it would be confusing noise on this app's common LAN/Tailscale
  HTTP deployment.

## Deploy integration

Both installers' env examples (`deploy/*/curodav.env.example`) now include
commented `CC_AUTH_*` lines. The deploy README's "no authentication" warning
was rewritten for the 2026-08-29 default-on-by-default-in-production change:
`deploy/systemd/curodav.service` and the `deploy/docker/Dockerfile` image
both set `CC_DEPLOY_MODE=production`, forcing the first-run `/setup` flow
above on an unconfigured install; pre-configuring `CC_AUTH_*` in the env
file skips it. See `deploy/README.md`'s "Security first" callout and its
configuration table.

## Out of scope

- No user management — one account, by design (this is a single-user app;
  see features/README.md's "single-user by design" line).
- No per-path roles or sharing (Published Lists' public links are a
  separate, deliberately unauthenticated feature — see
  `features/published-lists.md` — not a role/permission system for this
  app itself).
- No HTTPS termination — the deploy's own threat model is a trusted
  network (Tailscale) or an authenticated/TLS-terminating reverse proxy;
  this app never speaks TLS itself. The `Secure` cookie flag and HSTS
  header (above) activate automatically once something in front of it
  does, they don't provide TLS on their own. The session is a front-door
  check, not a session-revocation mechanism (revoke by changing
  `CC_AUTH_SECRET` / wiping the persisted secret, which invalidates every
  existing cookie).
- Login rate limiting is a simple in-memory per-IP window (see "What it
  looks like" above), not account lockout, CAPTCHA, or anything persisted
  across restarts.