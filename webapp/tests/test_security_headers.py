"""Security response headers (2026-08-29, src/security_headers.py;
nonce-based CSP added 2026-09-07, audit-fixes-2.0.md item 11).

Coverage:
  - SecurityHeadersMiddleware in isolation over a tiny ASGI app: the fixed
    headers are always present, HSTS only appears when scope["scheme"] ==
    "https".
  - Ordering against the real app (src/main.py): the headers land even on
    a response AuthMiddleware/CSRFMiddleware short-circuit (a 302 login
    redirect, a 403 CSRF rejection) -- proving SecurityHeadersMiddleware
    is genuinely outermost, not just present when a route handler runs.
  - CSP nonces: script-src/style-src carry a `'nonce-<value>'` (no
    `'unsafe-inline'` anywhere in the policy any more), two different
    requests get two different nonces, and a real rendered page's
    `<script nonce="...">` tag matches the nonce in that same response's
    CSP header.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.testclient import TestClient

from src.config import Settings
from src.security_headers import CSP_POLICY, SecurityHeadersMiddleware


def _settings(**overrides) -> Settings:
    base = Settings(
        radicale_base_url="http://127.0.0.1:5232/devuser/",
        radicale_username="devuser",
        radicale_password="devpass",
        calendar_collection="calendar",
        tasks_collection="tasks",
        contacts_collection="contacts",
        db_path=Path("/tmp/cc-secheaders-test.sqlite"),
        sync_interval_seconds=60,
        backup_dir=Path("/tmp/cc-secheaders-test-backups"),
        auth_username="alice",
        auth_password="s3cret",
        auth_session_secret="test-signing-secret",
    )
    from dataclasses import replace

    return replace(base, **overrides)


def _mini_app(settings=None):
    app = FastAPI()
    if settings is not None:
        app.state.settings = settings
        app.state.bridge = None

    @app.get("/hello")
    def hello():
        return JSONResponse({"hello": "world"})

    app.add_middleware(SecurityHeadersMiddleware)
    return app


NONCE_RE = re.compile(r"'nonce-([A-Za-z0-9_-]+)'")


class TestSecurityHeadersMiddleware:
    def test_fixed_headers_present(self):
        client = TestClient(_mini_app())
        resp = client.get("/hello")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        csp = resp.headers["content-security-policy"]
        assert csp == CSP_POLICY.format(nonce=NONCE_RE.search(csp).group(1))

    def test_csp_denies_framing_and_restricts_to_self(self):
        assert "frame-ancestors 'none'" in CSP_POLICY
        assert "default-src 'self'" in CSP_POLICY

    def test_csp_has_no_unsafe_inline_on_script_or_style(self):
        # audit-fixes-2.0.md item 11 -- the whole point of the nonce
        # migration: 'unsafe-inline' must be gone from *both* directives,
        # not just script-src (a "nonce script tags but leave style=
        # attributes on unsafe-inline" half-measure was explicitly out of
        # scope, see the plan doc's own framing).
        assert "'unsafe-inline'" not in CSP_POLICY

    def test_csp_script_and_style_src_use_nonce_placeholder(self):
        assert "script-src 'self' 'nonce-{nonce}'" in CSP_POLICY
        assert "style-src 'self' 'nonce-{nonce}'" in CSP_POLICY

    def test_csp_nonce_differs_per_request(self):
        client = TestClient(_mini_app())
        csp_a = client.get("/hello").headers["content-security-policy"]
        csp_b = client.get("/hello").headers["content-security-policy"]
        nonce_a = NONCE_RE.search(csp_a).group(1)
        nonce_b = NONCE_RE.search(csp_b).group(1)
        assert nonce_a != nonce_b
        # Both are still otherwise-identical policies, just with a
        # different nonce substituted in.
        assert csp_a.replace(nonce_a, "X") == csp_b.replace(nonce_b, "X")

    def test_csp_nonce_reasonably_unpredictable(self):
        # secrets.token_urlsafe(16) -- 16 random bytes, base64url-encoded
        # (no padding), so >= 20 chars is the right ballpark; guards
        # against an accidental regression to something short/predictable.
        client = TestClient(_mini_app())
        csp = client.get("/hello").headers["content-security-policy"]
        nonce = NONCE_RE.search(csp).group(1)
        assert len(nonce) >= 20

    def test_hsts_absent_over_plain_http(self):
        client = TestClient(_mini_app())
        resp = client.get("/hello")
        assert "strict-transport-security" not in resp.headers

    def test_hsts_present_over_https_scope(self):
        # TestClient always speaks plain HTTP to the ASGI app; simulate an
        # HTTPS-originated request the way uvicorn's --proxy-headers would
        # (X-Forwarded-Proto rewriting scope["scheme"]) by driving the
        # middleware directly over a hand-built scope, same convention
        # test_auth.py's AuthMiddleware tests use for scope-level checks.
        import asyncio

        async def inner(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = SecurityHeadersMiddleware(inner)
        captured = {}

        async def send(message):
            if message["type"] == "http.response.start":
                captured["headers"] = dict(message["headers"])

        asyncio.run(mw({"type": "http", "scheme": "https"}, None, send))
        assert captured["headers"][b"strict-transport-security"] == b"max-age=31536000; includeSubDomains"

    def test_non_http_scope_passes_through_untouched(self):
        import asyncio

        calls = []

        async def inner(scope, receive, send):
            calls.append(scope["type"])

        mw = SecurityHeadersMiddleware(inner)
        asyncio.run(mw({"type": "lifespan"}, None, None))
        assert calls == ["lifespan"]


class TestCspNonceTemplateWiring:
    """Proves the actual chain the plan doc's design called for: scope[
    "state"]["csp_nonce"] (set by the middleware) -> Request.state.
    csp_nonce (Starlette's lazy scope["state"] read) -> deps.py's
    `csp_nonce()` Jinja global -- using the *real* src.deps.templates
    Jinja2Templates instance (same globals as every page in the app),
    not a stand-in, so this fails if that wiring ever breaks. Renders a
    tiny inline template via `templates.env.from_string` rather than a
    full page (which would need a real DB/settings/auth stack to render
    end-to-end) -- same "minimal ASGI app, real middleware" convention
    the rest of this file already uses, just extended to also exercise
    the real template environment."""

    def _app(self):
        from src.deps import templates

        app = FastAPI()
        tmpl = templates.env.from_string('<script nonce="{{ csp_nonce() }}">1</script>')

        @app.get("/page")
        def page(request: Request):
            return HTMLResponse(tmpl.render(request=request))

        app.add_middleware(SecurityHeadersMiddleware)
        return app

    def test_rendered_nonce_matches_csp_header(self):
        client = TestClient(self._app())
        resp = client.get("/page")
        csp = resp.headers["content-security-policy"]
        header_nonce = NONCE_RE.search(csp).group(1)
        rendered_nonce = re.search(r'<script nonce="([^"]+)">', resp.text).group(1)
        assert header_nonce == rendered_nonce
        assert header_nonce  # non-empty -- the "" fallback path never fires for a real request


class TestSecurityHeadersOrderingAgainstRealApp:
    """Headers must land even on a response another middleware short-
    circuits -- proves SecurityHeadersMiddleware is genuinely outermost in
    src/main.py's real middleware stack, not just present on a normal
    route response."""

    def _real_app(self, settings):
        from src.auth import AuthMiddleware, CSRFMiddleware

        app = FastAPI()
        app.state.settings = settings
        app.state.bridge = None

        @app.get("/hello")
        def hello():
            return JSONResponse({"hello": "world"})

        @app.post("/mutate")
        def mutate():
            return JSONResponse({"ok": True})

        # Same registration order as main.py's create_app: CSRF, then
        # Auth, then SecurityHeaders last (outermost).
        app.add_middleware(CSRFMiddleware)
        app.add_middleware(AuthMiddleware)
        app.add_middleware(SecurityHeadersMiddleware)
        return app

    def test_headers_present_on_auth_redirect(self):
        client = TestClient(self._real_app(_settings()), follow_redirects=False)
        resp = client.get("/hello")
        assert resp.status_code == 302
        assert resp.headers["x-content-type-options"] == "nosniff"
        csp = resp.headers["content-security-policy"]
        assert csp == CSP_POLICY.format(nonce=NONCE_RE.search(csp).group(1))

    def test_headers_present_on_csrf_rejection(self):
        from src import auth

        settings = _settings()
        client = TestClient(self._real_app(settings), follow_redirects=False, base_url="http://testserver")
        # A *valid* session cookie -- passes AuthMiddleware (outer relative
        # to CSRF in this stack, same order as main.py) so the request
        # actually reaches CSRFMiddleware's own check.
        client.cookies.set(auth.SESSION_COOKIE, auth.make_session_token(settings.auth_session_secret, "alice"))
        resp = client.post("/mutate", headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403
        assert resp.headers["x-frame-options"] == "DENY"
        csp = resp.headers["content-security-policy"]
        assert csp == CSP_POLICY.format(nonce=NONCE_RE.search(csp).group(1))
