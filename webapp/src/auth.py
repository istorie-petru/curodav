"""Single-user authentication (side work, 2026-08-16).

The app runs with NO login by default -- the exact behavior it has always
had (local dev, trusted networks; see deploy/README.md's security note).
Configure BOTH `CC_AUTH_USERNAME` and `CC_AUTH_PASSWORD` (webapp/src/
config.py) and every request except `/login` and `/static` requires a
signed session cookie proving the browser logged in with those
credentials.

Everything here is stdlib-only (`hmac`/`hashlib`/`secrets`/`base64`) -- the
session is a *stateless signed cookie*, not a server-side session table, so
there is no schema change and no new runtime dependency (the deployment
image's pinned dependency set stays untouched). The signing secret is
`CC_AUTH_SECRET` when set; otherwise it is auto-generated once and
persisted in `app_meta` (survives restarts; wipe that row or change
`CC_AUTH_SECRET` to force everyone to re-login).

The cookie carries `{"sub": <username>, "exp": <unix ts>}` base64-encoded
plus an HMAC-SHA256 signature over the payload. It is signed, not
encrypted -- a signed cookie is enough here because the payload is
non-sensitive (the username and an expiry), and signing is what prevents
forging a session. Cookie flags: `HttpOnly` (JS never needs to read it),
`SameSite=Lax` (CSRF-safe for a form POST on the same origin), `Path=/`
(every route), a `Max-Age` matching the token's own `exp`.

Requests that want JSON (the `/api/*` routes, the async-CRUD `X-Requested-
With: fetch` header, or an `Accept: application/json`) get a clean 401
instead of a redirect so fetch-driven surfaces never try to parse the
login page as JSON -- everything else gets a 302 to `/login?next=<path>`.

2026-08-29: three additions, all still stdlib-only.
  - A production deploy (`CC_DEPLOY_MODE=production` -- systemd/docker set
    this; local dev/manual runs default to "local" and are unaffected)
    with no account configured is forced through `GET/POST /setup`
    instead of staying open: see `setup_required`, `AuthMiddleware`'s
    forced-setup branch, and `routers/auth.py`'s setup routes. A
    /setup-created account is persisted hashed (PBKDF2-HMAC-SHA256,
    `hash_password`) in `app_meta`, not an env var.
  - `CSRFMiddleware`: Origin/Referer verification for state-changing
    requests carrying a session cookie (see its own docstring).
  - `login_rate_limited`/`record_failed_login`: an in-memory per-IP
    sliding-window lockout on `POST /login`.
  - `is_secure_request`: whether the session cookie should carry the
    `Secure` flag for this request (see its own docstring) -- both deploy
    configs already pass uvicorn `--proxy-headers`, so this reflects the
    real scheme even behind a TLS-terminating reverse proxy.

2026-08-30: Settings > General gained an old/new/confirm "Login &
security" password-change form (`routers/settings.py::
change_login_password`) -- the always-available counterpart to /setup's
one-time account creation, since that page only ever renders once per
install (and, in local/dev mode, never at all -- see setup_required).
Works whether or not an account exists yet: with none, it creates one
under a fixed "admin" username with no old-password check; with one, the
current password must verify first. This is also why `auth_enabled` no
longer special-cases `deploy_mode == "local"` -- a password set through
this form has to actually take effect immediately, in every deploy mode,
not just production (see `auth_enabled`'s own docstring for the tradeoff
that change makes).

2026-09-07: audit fix (session revocation, `documentation/reports/
full-app-audit-2026-09-07.md`) -- `rotate_session_secret` is now called
whenever persisted credentials are (re)established (both /setup and
change_login_password), reusing the exact mechanism `routers/settings.py
::purge_all` already used to force a re-login after a purge: an
auto-generated session secret lives in `app_meta`, so replacing it makes
`read_session_token`'s HMAC check fail for every cookie signed under the
old one. Previously a stolen cookie or the just-replaced password itself
stayed valid for the rest of the 30-day session, even after the account
owner changed their password -- see SESSION_MAX_AGE_SECONDS's own
docstring for the narrower caveat that remains (a fixed `CC_AUTH_SECRET`
can't be rotated this way).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode, urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from . import db

# The cookie name + the app_meta key the auto-generated signing secret is
# persisted under (see module docstring). Both are module-level constants
# so src/routers/auth.py (the login/logout routes) and main.py (middleware
# wiring) can reference them without importing each other.
SESSION_COOKIE = "cc_session"
AUTH_SECRET_KEY = "auth_session_secret"

# app_meta keys the forced first-run /setup flow persists its
# operator-chosen account under (2026-08-29). Unlike CC_AUTH_USERNAME/
# CC_AUTH_PASSWORD (plaintext env vars, still supported for local/manual
# overrides -- see auth_enabled), a /setup-created account only ever exists
# hashed in the database -- the same "persist in app_meta, not disk config"
# convention AUTH_SECRET_KEY already uses for the auto-generated session
# secret.
AUTH_USERNAME_KEY = "auth_username"
AUTH_PASSWORD_HASH_KEY = "auth_password_hash"

# The route the forced first-run flow lives at. Public only conditionally
# (see setup_required) -- unlike PUBLIC_PATHS below, which is unconditional.
SETUP_PATH = "/setup"

# PBKDF2-HMAC-SHA256 iteration count for hashing a /setup-chosen password.
# 260_000 matches Django's current default (a well-reviewed, still-current
# figure for this primitive as of 2024) -- stdlib-only (hashlib), so no new
# runtime dependency, consistent with the rest of this module.
PBKDF2_ITERATIONS = 260_000

# How long a login stays valid. 30 days -- a personal single-user app where
# "log me in once, keep me logged in" is the expected UX; the deploy's own
# threat model is a trusted network / authenticated proxy anyway (see
# deploy/README.md). Early revocation is narrow, not general-purpose: a
# credentials change (rotate_session_secret) or Settings > Purge all
# invalidates every outstanding session, but there is no way to revoke one
# specific session/device without touching the others, and a fixed
# CC_AUTH_SECRET can't be rotated at all (see rotate_session_secret's own
# docstring).
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30

# Paths that must never require a session. /login is the whole point;
# /static is shared, cacheable, non-sensitive assets (a signed-out browser
# still needs the CSS to render the login page itself).
PUBLIC_PATHS = {"/login"}


def auth_enabled(settings, conn=None) -> bool:
    """Whether login is enforced for this install: true when EITHER the
    env-var pair (CC_AUTH_USERNAME/PASSWORD, see config.py's docstring) is
    configured, OR a first-run /setup account (or a password set later
    through Settings > General, routers/settings.py::change_login_password)
    has been persisted (has_persisted_credentials). A `None` settings
    (middleware before the lifespan set it, or a bare test app) counts as
    disabled.

    `conn` is optional -- pass one in when the caller already holds it
    (routers do); otherwise a short-lived connection is opened only when
    the env pair is absent, the same "conn optional, opened on demand"
    convention session_secret uses.

    2026-08-30: local/dev installs (deploy_mode == "local") now consult the
    DB here too, same as production -- previously this short-circuited to
    False for local mode unconditionally, on the reasoning that the env-var
    pair was the only way to turn login on there. That made Settings >
    General's password form silently no-op for the common "just run it
    locally" case: a password would save to app_meta but never actually be
    checked. AuthMiddleware._configured still caches the "is this
    configured" answer on app.state once it flips True (see its own
    docstring), so the steady-state cost of this change is one extra DB
    read per request only for the genuinely-still-unconfigured window --
    zero once an account exists, same as production always paid."""
    if not settings:
        return False
    if settings.auth_username and settings.auth_password:
        return True
    return has_persisted_credentials(settings, conn)


def has_persisted_credentials(settings, conn=None) -> bool:
    """Whether a /setup-created account exists in app_meta, regardless of
    the env-var pair."""
    if not settings:
        return False
    if conn is not None:
        return get_persisted_credentials(conn) is not None
    with db.connect(settings.db_path) as c:
        return get_persisted_credentials(c) is not None


def get_persisted_credentials(conn) -> tuple[str, str] | None:
    """The (username, password_hash) pair /setup persisted, or None when no
    account has been created yet."""
    username = db.get_app_meta(conn, AUTH_USERNAME_KEY)
    password_hash = db.get_app_meta(conn, AUTH_PASSWORD_HASH_KEY)
    if username and password_hash:
        return username, password_hash
    return None


def set_persisted_credentials(conn, username: str, password: str) -> None:
    """Persists a /setup-chosen account: the username in the clear (it's
    not a secret) and the password hashed (hash_password)."""
    db.set_app_meta(conn, AUTH_USERNAME_KEY, username)
    db.set_app_meta(conn, AUTH_PASSWORD_HASH_KEY, hash_password(password))


def setup_required(settings, conn=None) -> bool:
    """Whether an unconfigured install must be forced through GET/POST
    /setup before anything else works. Only true for a deploy_mode other
    than "local" (systemd/docker set CC_DEPLOY_MODE=production -- see
    config.py) that has neither the env-var pair nor a persisted account
    yet. Local dev/manual runs (deploy_mode == "local") are never forced --
    they keep the original "open unless you configure it" default."""
    if not settings:
        return False
    if settings.deploy_mode == "local":
        return False
    return not auth_enabled(settings, conn)


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256, self-describing so the iteration count/salt
    travel with the hash: `pbkdf2_sha256$<iterations>$<salt-hex>$<hash-hex>`.
    stdlib-only (hashlib), no new runtime dependency."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password_hash(password: str, encoded: str) -> bool:
    """Constant-time check of `password` against a hash_password() value.
    Any malformed/unrecognized encoding fails closed (False), never
    raises -- a corrupted app_meta row must not crash the login path."""
    try:
        algo, iterations_s, salt_hex, hash_hex = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def verify_credentials(
    settings, username: str | None, password: str | None, conn=None
) -> bool:
    """Constant-time comparison of a login attempt against whichever
    account is configured: the env-var pair first (if both are set), else
    the persisted /setup account (hashed). `hmac.compare_digest` on the
    username too (not just the password/hash) so a wrong username doesn't
    short-circuit with a measurable timing difference. Returns False for
    anything missing/empty, and for a disabled install."""
    if not username or not password or not settings:
        return False
    if settings.auth_username and settings.auth_password:
        if hmac.compare_digest(username, settings.auth_username) and hmac.compare_digest(
            password, settings.auth_password
        ):
            return True
    if conn is not None:
        persisted = get_persisted_credentials(conn)
    else:
        with db.connect(settings.db_path) as c:
            persisted = get_persisted_credentials(c)
    if persisted:
        stored_user, stored_hash = persisted
        if hmac.compare_digest(username, stored_user) and _verify_password_hash(
            password, stored_hash
        ):
            return True
    return False


def session_secret(settings, conn=None) -> str:
    """The HMAC key used to sign session cookies. `CC_AUTH_SECRET` when the
    operator configured one; otherwise an auto-generated value persisted in
    `app_meta` under AUTH_SECRET_KEY (generated on first use). A `conn` may
    be passed in when the caller already holds one (the login route does);
    otherwise a short-lived connection is opened here -- the same
    convention as deps.py's `_cached_app_meta`."""
    if settings.auth_session_secret:
        return settings.auth_session_secret
    if conn is None:
        with db.connect(settings.db_path) as conn:
            return _persisted_secret(conn)
    return _persisted_secret(conn)


def _persisted_secret(conn) -> str:
    secret = db.get_app_meta(conn, AUTH_SECRET_KEY)
    if secret:
        return secret
    secret = secrets.token_urlsafe(32)
    db.set_app_meta(conn, AUTH_SECRET_KEY, secret)
    return secret


def rotate_session_secret(settings, conn) -> str:
    """Generates and persists a new session-signing secret, invalidating
    every session cookie already issued: `read_session_token`'s HMAC check
    fails for a cookie signed under a secret that no longer matches what's
    in `app_meta`. This is the same mechanism `routers/settings.py::
    purge_all` already relies on to force a re-login after a purge -- see
    its comment -- generalized to a second trigger: call this whenever
    persisted login credentials are (re)established (`set_persisted_
    credentials`, from either /setup or Settings > General's password-change
    form), so a stolen cookie -- or a session started under the
    just-replaced password -- can't keep working past the moment the
    account owner changes their password. Closes the gap flagged by the
    2026-09-07 audit (`documentation/reports/full-app-audit-2026-09-07.md`):
    previously nothing invalidated an outstanding session early, so it
    stayed valid for the rest of its full 30-day `SESSION_MAX_AGE_SECONDS`
    regardless of a later password change.

    A no-op returning the existing value when `CC_AUTH_SECRET` is
    configured (`settings.auth_session_secret`) -- that secret is
    operator-fixed, never stored in `app_meta`, and can't be rotated from
    here; the module docstring's "change CC_AUTH_SECRET to force everyone
    to re-login" is the equivalent action for that configuration.

    The caller is responsible for updating any in-process cache of the old
    value the same way `purge_all` does (`AuthMiddleware` caches the secret
    on `app.state._cc_auth_secret`) -- otherwise the very request that
    triggered the rotation would look unauthenticated to itself on its next
    hit, since the middleware would still be comparing against the secret
    this call just replaced."""
    if settings and settings.auth_session_secret:
        return settings.auth_session_secret
    secret = secrets.token_urlsafe(32)
    db.set_app_meta(conn, AUTH_SECRET_KEY, secret)
    return secret


def make_session_token(secret: str, username: str, max_age: int = SESSION_MAX_AGE_SECONDS) -> str:
    """Builds a signed session cookie value for `username` valid `max_age`
    seconds from now: `base64url(json({"sub","exp"})).hmac_sha256_hex`."""
    payload = json.dumps(
        {"sub": username, "exp": int(time.time()) + max_age}, separators=(",", ":")
    ).encode()
    b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    sig = hmac.new(secret.encode("utf-8"), b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def read_session_token(secret: str, token: str | None) -> str | None:
    """Verifies a session cookie value and returns the username it was
    issued to, or None when missing/malformed/tampered/expired. The
    signature is checked with constant-time comparison before anything in
    the payload is trusted."""
    if not isinstance(token, str):
        return None
    try:
        b64, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret.encode("utf-8"), b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        # base64.urlsafe_b64decode wants padding; the token strips it, so
        # re-add the "=" padding it omitted.
        payload = json.loads(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)))
    except Exception:
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < time.time():
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None


def _wants_json(scope: dict) -> bool:
    """Whether an unauthenticated request to a protected route should get a
    401 JSON instead of a login redirect -- true for the `/api/*` surface
    and any fetch-based request (the async-CRUD `X-Requested-With: fetch`
    header, or an explicit JSON Accept)."""
    if scope["path"].startswith("/api/"):
        return True
    headers = dict(scope.get("headers") or [])
    if headers.get(b"x-requested-with") == b"fetch":
        return True
    accept = headers.get(b"accept", b"")
    return b"application/json" in accept


def _settings_from_scope(scope: dict):
    """The app's Settings, read off `scope["app"].state.settings` -- the
    lifespan sets them there (main.py). A bare/no-lifespan app (this
    suite's tests, or a misconfiguration) yields None, which auth_enabled
    treats as "login not enforced" rather than crashing every request."""
    app = scope.get("app")
    state = getattr(app, "state", None)
    return getattr(state, "settings", None) if state is not None else None


class AuthMiddleware:
    """Pure-ASGI gate in front of the whole app. Runs for every HTTP
    request; when auth is enabled and the request isn't to a public path
    and carries no valid session cookie, it answers 302-to-/login (or 401
    JSON for API/fetch requests) instead of letting the route run. A
    middleware (rather than a per-router dependency) is the only layer
    that provably covers every route -- including ones registered in the
    future -- so no router can silently forget to require auth."""

    def __init__(self, app, *, get_settings=_settings_from_scope):
        self.app = app
        self._get_settings = get_settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        settings = self._get_settings(scope)
        path = scope["path"]
        if path in PUBLIC_PATHS or path.startswith("/static/") or path.startswith("/public/"):
            # 2026-08-29: Published Lists' standalone public feed
            # (routers/public_lists.py) -- deliberately exempt even from
            # the forced-first-run-setup branch below, not just the
            # normal login gate: a link already shared with someone
            # outside the household must keep working while the operator
            # is mid-setup, same as /static already does for the login
            # page's own CSS.
            return await self.app(scope, receive, send)

        # Forced first-run setup (2026-08-29): a production deploy
        # (deploy_mode != "local", see config.py) with no account
        # configured yet -- env pair or persisted -- must be walked through
        # GET/POST /setup before anything else is reachable. This check
        # comes before the session-cookie check below on purpose: an
        # unconfigured production install is NOT "auth disabled", it's
        # "not set up yet." Local dev/manual runs skip the forced-/setup
        # redirect (they're never walked through /setup), but as of
        # 2026-08-30 they use the *same* self._configured() check as
        # production to decide whether a session is required at all --
        # previously this branch called the module-level auth_enabled()
        # directly, which special-cased local mode to ignore persisted
        # credentials entirely (see auth_enabled's own docstring for why
        # that changed): a password set through Settings > General while
        # running locally now actually locks the app down, same as it
        # always has in production.
        if settings and settings.deploy_mode != "local":
            if not self._configured(settings, scope):
                if path == SETUP_PATH:
                    return await self.app(scope, receive, send)
                return await self._deny(scope, receive, send, SETUP_PATH)
        elif not self._configured(settings, scope):
            return await self.app(scope, receive, send)

        request = Request(scope)
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            secret = self._get_secret(settings, scope)
            if read_session_token(secret, token):
                return await self.app(scope, receive, send)

        return await self._deny(scope, receive, send, "/login")

    async def _deny(self, scope, receive, send, target: str):
        if _wants_json(scope):
            response = JSONResponse(
                {"ok": False, "detail": "Authentication required"}, status_code=401
            )
        else:
            path = scope["path"]
            query = scope.get("query_string") or b""
            qs = f"?{query.decode('latin-1')}" if query else ""
            response = RedirectResponse(
                url=f"{target}?{urlencode({'next': path + qs})}", status_code=302
            )
        return await response(scope, receive, send)

    def _configured(self, settings, scope) -> bool:
        """Cached "does this install have an account yet" check (env pair,
        a persisted /setup account, or a password set later through
        Settings > General) -- used by both deploy modes now (2026-08-30):
        production uses it to decide whether to force /setup, local mode
        uses it to decide whether a session is required at all. Once True,
        it stays True for the process lifetime except for Settings > Purge
        all, which resets the cache (see routers/settings.py::purge_all) --
        a fresh install then needs to reconfigure, matching a wiped
        database's actual state. The False path (genuinely not configured
        yet) re-checks the DB every request, same as _get_secret's own
        on-demand connection; for production that's expected only for the
        brief window between install and finishing /setup, and for a local
        install that never configures anything it's the permanent (if
        cheap) steady state -- see auth_enabled's docstring for that
        tradeoff."""
        app = scope.get("app")
        state = getattr(app, "state", None)
        if state is not None and getattr(state, "_cc_auth_configured", False):
            return True
        configured = auth_enabled(settings)
        if configured and state is not None:
            state._cc_auth_configured = True
        return configured

    def _get_secret(self, settings, scope) -> str:
        """The signing secret, cached on `app.state` for the process
        lifetime so the per-request middleware check doesn't open a DB
        connection on every hit after the first (the same memoized-once
        reasoning deps.py documents for `_cached_app_meta`)."""
        if settings.auth_session_secret:
            return settings.auth_session_secret
        app = scope.get("app")
        state = getattr(app, "state", None)
        cached = getattr(state, "_cc_auth_secret", None)
        if cached:
            return cached
        secret = session_secret(settings)
        if state is not None:
            state._cc_auth_secret = secret
        return secret


# --------------------------------------------------------------------- #
# Login attempt rate limiting (2026-08-29)
# --------------------------------------------------------------------- #
#
# A plain in-memory sliding window, keyed by client IP -- this is a
# single-process app (uvicorn, no reload/workers in the deploy configs), so
# a module-level dict is a real, if not restart-durable, lockout: exactly
# the tradeoff the auto-generated session secret already makes for
# simplicity (stdlib-only, no schema/dependency). Losing the counters on a
# restart is an acceptable gap for a personal single-user app -- the
# threat this defends against (a slow online guessing loop) still has to
# survive the window in one process lifetime to matter.

RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 15 * 60

_login_attempts: dict[str, list[float]] = {}


def _prune(key: str, now: float) -> list[float]:
    attempts = [t for t in _login_attempts.get(key, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
    _login_attempts[key] = attempts
    return attempts


def login_rate_limited(key: str) -> bool:
    """True once `key` (a client IP) has RATE_LIMIT_MAX_ATTEMPTS failed
    logins within the last RATE_LIMIT_WINDOW_SECONDS. A locked-out key
    stays locked until its oldest attempt ages out of the window (a
    rolling lockout, not a fixed one -- each new attempt while locked
    keeps pushing it back out, same as most login-throttling
    implementations)."""
    return len(_prune(key, time.time())) >= RATE_LIMIT_MAX_ATTEMPTS


def record_failed_login(key: str) -> None:
    now = time.time()
    _prune(key, now)
    _login_attempts.setdefault(key, []).append(now)


def clear_login_attempts(key: str) -> None:
    _login_attempts.pop(key, None)


def reset_rate_limits() -> None:
    """Test-only escape hatch: the module-level dict above is process-wide
    state, so a test suite exercising login_submit repeatedly needs a way
    to start each test with a clean slate rather than tripping a lockout
    left over from an earlier test."""
    _login_attempts.clear()


def client_ip(request: Request) -> str:
    """The rate-limit bucket key. `request.client` is None for a
    hand-built scope with no "client" entry (this suite's direct
    router-function-call tests) -- "unknown" groups those together, which
    is fine for tests (reset_rate_limits clears it between them) and never
    happens for a real request, where an ASGI server always sets it."""
    return request.client.host if request.client else "unknown"


def is_secure_request(request: Request) -> bool:
    """Whether the session cookie should carry the `Secure` flag for this
    request -- true when the request's own scheme is "https". Both deploy
    configs (deploy/systemd/curodav.service, the Docker image's uvicorn
    CMD) already pass `--proxy-headers`, which makes uvicorn trust a
    reverse proxy's `X-Forwarded-Proto` header and set the ASGI scope's
    scheme accordingly -- so this reflects the real, original scheme even
    when the app itself only ever speaks plain HTTP to the proxy sitting
    in front of it. A bare HTTP install (the common LAN/Tailscale case
    with no reverse proxy) gets `Secure` omitted, exactly as before this
    existed -- `Secure` on a cookie sent over plain HTTP would just get
    the cookie silently dropped by the browser, locking the operator out."""
    return request.url.scheme == "https"


# --------------------------------------------------------------------- #
# CSRF protection (2026-08-29)
# --------------------------------------------------------------------- #
#
# Origin/Referer verification for state-changing requests, enforced only
# when a session cookie is riding along -- see CSRFMiddleware's own
# docstring for the full reasoning. Deliberately NOT a per-form token: this
# app's forms/JS live across dozens of templates and a token would need
# threading through every one of them (plus every fetch() call) for
# comparatively little extra protection over Origin verification, which
# OWASP lists as an accepted primary defense in its own right (see the CSRF
# prevention cheat sheet's "Verifying Origin with Standard Headers"
# section) and needs zero template changes.

CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _request_origin_host(request: Request) -> str | None:
    """The host:port a same-origin browser request's Origin (preferred) or
    Referer header would carry. None when neither header is present."""
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        return None
    try:
        return urlsplit(source).netloc or None
    except ValueError:
        return None


def is_same_origin_request(request: Request) -> bool:
    """False (reject) whenever the Origin/Referer host doesn't match the
    request's own Host -- including when both headers are absent, since
    every modern browser sends at least one on a cross-origin or
    same-origin POST; a mutating request with neither is itself
    suspicious enough to fail closed rather than assume same-origin."""
    host = request.headers.get("host")
    origin_host = _request_origin_host(request)
    return bool(host) and bool(origin_host) and origin_host == host


class CSRFMiddleware:
    """Rejects cross-origin state-changing requests (POST/PUT/PATCH/
    DELETE/...) that carry this app's session cookie. Only relevant when
    auth is enabled and a session exists: without a cookie-based session,
    there is no ambient credential for a forged cross-site request to ride
    on, so the check is a no-op on a fully-open install -- consistent with
    this app's existing "disabled auth changes nothing" convention
    (AuthMiddleware). SameSite=Lax on the session cookie already blocks
    most of this in current browsers; this is the second, explicit layer
    the still-open "CSRF protection is genuinely missing" gap called for,
    without threading a token through every form/fetch() in the app."""

    def __init__(self, app, *, get_settings=_settings_from_scope):
        self.app = app
        self._get_settings = get_settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in CSRF_SAFE_METHODS:
            return await self.app(scope, receive, send)
        settings = self._get_settings(scope)
        if not auth_enabled(settings):
            return await self.app(scope, receive, send)
        request = Request(scope)
        if request.cookies.get(SESSION_COOKIE) is None:
            # Nothing for a forged request to exploit yet -- covers the
            # login/setup POSTs themselves, which run before any session
            # cookie exists.
            return await self.app(scope, receive, send)
        if is_same_origin_request(request):
            return await self.app(scope, receive, send)
        response = JSONResponse(
            {"ok": False, "detail": "CSRF check failed: request origin does not match host"},
            status_code=403,
        )
        return await response(scope, receive, send)