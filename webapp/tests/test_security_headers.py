"""Security response headers (2026-08-29, src/security_headers.py).

Coverage:
  - SecurityHeadersMiddleware in isolation over a tiny ASGI app: the fixed
    headers are always present, HSTS only appears when scope["scheme"] ==
    "https".
  - Ordering against the real app (src/main.py): the headers land even on
    a response AuthMiddleware/CSRFMiddleware short-circuit (a 302 login
    redirect, a 403 CSRF rejection) -- proving SecurityHeadersMiddleware
    is genuinely outermost, not just present when a route handler runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
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


class TestSecurityHeadersMiddleware:
    def test_fixed_headers_present(self):
        client = TestClient(_mini_app())
        resp = client.get("/hello")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert resp.headers["content-security-policy"] == CSP_POLICY

    def test_csp_denies_framing_and_restricts_to_self(self):
        assert "frame-ancestors 'none'" in CSP_POLICY
        assert "default-src 'self'" in CSP_POLICY

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
        assert resp.headers["content-security-policy"] == CSP_POLICY

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
        assert resp.headers["content-security-policy"] == CSP_POLICY
