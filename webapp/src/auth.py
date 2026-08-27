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
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from . import db

# The cookie name + the app_meta key the auto-generated signing secret is
# persisted under (see module docstring). Both are module-level constants
# so src/routers/auth.py (the login/logout routes) and main.py (middleware
# wiring) can reference them without importing each other.
SESSION_COOKIE = "cc_session"
AUTH_SECRET_KEY = "auth_session_secret"

# How long a login stays valid. 30 days -- a personal single-user app where
# "log me in once, keep me logged in" is the expected UX; the deploy's own
# threat model is a trusted network / authenticated proxy anyway (see
# deploy/README.md), this is a front-door check, not a session-revocation
# mechanism.
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30

# Paths that must never require a session. /login is the whole point;
# /static is shared, cacheable, non-sensitive assets (a signed-out browser
# still needs the CSS to render the login page itself).
PUBLIC_PATHS = {"/login"}


def auth_enabled(settings) -> bool:
    """Whether login is enforced for this install: only when BOTH the
    username and password are configured (see config.py's docstring on the
    pair). A `None` settings (middleware before the lifespan set it, or a
    bare test app) counts as disabled."""
    return bool(settings and settings.auth_username and settings.auth_password)


def verify_credentials(settings, username: str | None, password: str | None) -> bool:
    """Constant-time comparison of a login attempt against the configured
    single user. `hmac.compare_digest` on both fields (not just the
    password) so a wrong username doesn't short-circuit with a measurable
    timing difference. Returns False for anything missing/empty."""
    if not auth_enabled(settings):
        return False
    expected_user = settings.auth_username
    expected_pass = settings.auth_password
    if not username or not password:
        return False
    return hmac.compare_digest(username, expected_user) and hmac.compare_digest(
        password, expected_pass
    )


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
        if not auth_enabled(settings):
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path in PUBLIC_PATHS or path.startswith("/static/"):
            return await self.app(scope, receive, send)

        request = Request(scope)
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            secret = self._get_secret(settings, scope)
            if read_session_token(secret, token):
                return await self.app(scope, receive, send)

        if _wants_json(scope):
            response = JSONResponse(
                {"ok": False, "detail": "Authentication required"}, status_code=401
            )
        else:
            query = scope.get("query_string") or b""
            qs = f"?{query.decode('latin-1')}" if query else ""
            response = RedirectResponse(
                url=f"/login?{urlencode({'next': path + qs})}", status_code=302
            )
        return await response(scope, receive, send)

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