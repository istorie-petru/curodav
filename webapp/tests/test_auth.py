"""Single-user authentication (2026-08-16, src/auth.py + routers/auth.py).

The app runs with NO login by default; configure CC_AUTH_USERNAME +
CC_AUTH_PASSWORD and every request except /login and /static requires a
signed session cookie. Coverage, following this suite's usual conventions:

  - config: load_settings maps the CC_AUTH_* env vars onto Settings.
  - src/auth.py's pure functions: auth_enabled, verify_credentials
    (constant-time, disabled install), and the signed-cookie round trip
    (valid, tampered, wrong-secret, malformed, expired).
  - src/auth.py's AuthMiddleware over a real (minimal) FastAPI app via
    TestClient -- the middleware is the one layer this suite can't reach
    through router-function calls, so it gets its own tiny ASGI app with
    settings pointed at a test secret (no DB needed). Covers: 302-to-login
    for a signed-out page request, 401 JSON for /api/fetch requests, the
    public-path exemptions, and a valid cookie passing through.
  - routers/auth.py's login/logout routes via direct calls (the suite's
    router-function-call convention): disabled-install redirect, renders
    the form, already-logged-in redirect, successful login sets the cookie
    and honors a safe `next`, wrong credentials get a 401 + error message,
    logout clears the cookie, and `next` open-redirect safety.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.testclient import TestClient

from src import auth, db
from src.config import Settings
from src.routers import auth as auth_router


def _settings(*, enabled=True, **overrides) -> Settings:
    base = Settings(
        radicale_base_url="http://127.0.0.1:5232/devuser/",
        radicale_username="devuser",
        radicale_password="devpass",
        calendar_collection="calendar",
        tasks_collection="tasks",
        contacts_collection="contacts",
        db_path=Path("/tmp/cc-auth-test.sqlite"),
        sync_interval_seconds=60,
        backup_dir=Path("/tmp/cc-auth-test-backups"),
    )
    if enabled:
        base = replace(
            base,
            auth_username="alice",
            auth_password="s3cret",
            auth_session_secret="test-signing-secret",
        )
    return replace(base, **overrides)


def _request(settings, *, cookies=None, path="/login") -> Request:
    headers = []
    if cookies:
        cookie = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers.append((b"cookie", cookie.encode()))
    fake_app = SimpleNamespace(state=SimpleNamespace(settings=settings))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": headers,
            "app": fake_app,
        }
    )


def _token(settings, username="alice", **overrides) -> str:
    return auth.make_session_token(settings.auth_session_secret, username, **overrides)


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


# --------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------- #


class TestConfig:
    def test_auth_fields_default_to_none(self, monkeypatch):
        for var in ("CC_AUTH_USERNAME", "CC_AUTH_PASSWORD", "CC_AUTH_SECRET"):
            monkeypatch.delenv(var, raising=False)
        from src.config import load_settings

        s = load_settings()
        assert s.auth_username is None
        assert s.auth_password is None
        assert s.auth_session_secret is None

    def test_auth_fields_read_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "c.sqlite"))
        monkeypatch.setenv("CC_AUTH_USERNAME", "bob")
        monkeypatch.setenv("CC_AUTH_PASSWORD", "hunter2")
        monkeypatch.setenv("CC_AUTH_SECRET", "env-secret")
        from src.config import load_settings

        s = load_settings()
        assert s.auth_username == "bob"
        assert s.auth_password == "hunter2"
        assert s.auth_session_secret == "env-secret"


# --------------------------------------------------------------------- #
# src/auth.py -- pure functions
# --------------------------------------------------------------------- #


class TestAuthEnabled:
    def test_both_configured(self):
        assert auth.auth_enabled(_settings(enabled=True))

    def test_missing_one_side_disables(self):
        assert not auth.auth_enabled(_settings(auth_username=None))
        assert not auth.auth_enabled(_settings(auth_password=None))

    def test_no_settings_disables(self):
        assert not auth.auth_enabled(None)


class TestVerifyCredentials:
    def test_correct_pair(self):
        assert auth.verify_credentials(_settings(), "alice", "s3cret")

    def test_wrong_password(self):
        assert not auth.verify_credentials(_settings(), "alice", "nope")

    def test_wrong_username(self):
        assert not auth.verify_credentials(_settings(), "mallory", "s3cret")

    def test_missing_fields(self):
        assert not auth.verify_credentials(_settings(), "", "s3cret")
        assert not auth.verify_credentials(_settings(), "alice", "")

    def test_disabled_install(self):
        assert not auth.verify_credentials(_settings(enabled=False), "alice", "s3cret")


class TestSessionToken:
    def test_round_trip(self):
        settings = _settings()
        token = _token(settings)
        assert auth.read_session_token(settings.auth_session_secret, token) == "alice"

    def test_tampered_payload(self):
        settings = _settings()
        token = _token(settings)
        tampered = ("A" if token[0] != "A" else "B") + token[1:]
        assert auth.read_session_token(settings.auth_session_secret, tampered) is None

    def test_wrong_secret(self):
        settings = _settings()
        token = _token(settings)
        assert auth.read_session_token("different-secret", token) is None

    def test_malformed(self):
        assert auth.read_session_token("s", None) is None
        assert auth.read_session_token("s", "no-dot-here") is None
        assert auth.read_session_token("s", "") is None

    def test_expired(self):
        settings = _settings()
        token = _token(settings, max_age=-10)
        assert auth.read_session_token(settings.auth_session_secret, token) is None

    def test_different_usernames(self):
        settings = _settings()
        assert auth.read_session_token(
            settings.auth_session_secret, _token(settings, username="alice")
        ) == "alice"
        assert auth.read_session_token(
            settings.auth_session_secret, _token(settings, username="bob")
        ) == "bob"


class TestSessionSecret:
    def test_env_secret_wins(self, conn):
        settings = _settings(auth_session_secret="explicit")
        assert auth.session_secret(settings, conn) == "explicit"

    def test_persisted_secret_is_stable(self, conn):
        settings = _settings(auth_session_secret=None)
        first = auth.session_secret(settings, conn)
        second = auth.session_secret(settings, conn)
        assert first == second
        assert len(first) >= 32
        assert db.get_app_meta(conn, auth.AUTH_SECRET_KEY) == first

    def test_persisted_secret_opens_own_conn(self, tmp_path):
        settings = _settings(
            auth_session_secret=None, db_path=tmp_path / "cache.sqlite"
        )
        secret = auth.session_secret(settings)
        assert secret
        with db.connect(settings.db_path) as conn:
            assert db.get_app_meta(conn, auth.AUTH_SECRET_KEY) == secret


# --------------------------------------------------------------------- #
# src/auth.py -- AuthMiddleware over a real ASGI app
# --------------------------------------------------------------------- #


def _auth_app(settings):
    app = FastAPI()
    app.state.settings = settings
    app.state.bridge = None

    @app.get("/hello")
    def hello():
        return JSONResponse({"hello": "world"})

    @app.get("/api/ping")
    def ping():
        return JSONResponse({"pong": True})

    app.add_middleware(auth.AuthMiddleware)
    return app


class TestAuthMiddleware:
    def test_signed_out_page_redirects_to_login(self):
        client = TestClient(_auth_app(_settings()), follow_redirects=False)
        resp = client.get("/hello")
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("/login?next=")
        # The path is URL-encoded in the query string, so "/hello" reads as
        # "%2Fhello" there.
        assert "%2Fhello" in resp.headers["location"]

    def test_signed_out_api_gets_401_json(self):
        client = TestClient(_auth_app(_settings()), follow_redirects=False)
        resp = client.get("/api/ping")
        assert resp.status_code == 401
        assert resp.json()["ok"] is False

    def test_valid_cookie_passes_through(self):
        client = TestClient(_auth_app(_settings()), follow_redirects=False)
        client.cookies.set(auth.SESSION_COOKIE, _token(_settings()))
        assert client.get("/hello").json() == {"hello": "world"}
        assert client.get("/api/ping").json() == {"pong": True}

    def test_invalid_cookie_redirects(self):
        client = TestClient(_auth_app(_settings()), follow_redirects=False)
        client.cookies.set(auth.SESSION_COOKIE, "garbage.not-a-signature")
        assert client.get("/hello").status_code == 302

    def test_login_is_public(self):
        client = TestClient(_auth_app(_settings()), follow_redirects=False)
        assert client.get("/login").status_code != 401
        assert client.get("/login").status_code != 302

    def test_disabled_auth_passes_everything(self):
        client = TestClient(_auth_app(_settings(enabled=False)), follow_redirects=False)
        assert client.get("/hello").json() == {"hello": "world"}
        assert client.get("/api/ping").json() == {"pong": True}

    def test_fetch_header_gets_401_json_not_redirect(self):
        client = TestClient(_auth_app(_settings()), follow_redirects=False)
        resp = client.get("/hello", headers={"X-Requested-With": "fetch"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Authentication required"


# --------------------------------------------------------------------- #
# routers/auth.py -- login/logout routes
# --------------------------------------------------------------------- #


class TestLoginPage:
    def test_disabled_install_redirects_home(self, conn):
        resp = auth_router.login_page(_request(_settings(enabled=False)))
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    def test_renders_the_form(self, conn):
        resp = auth_router.login_page(_request(_settings()))
        assert resp.status_code == 200
        body = resp.body.decode()
        assert "name=\"username\"" in body
        assert "name=\"password\"" in body
        assert "action=\"/login\"" in body

    def test_already_logged_in_redirects(self, conn):
        settings = _settings()
        resp = auth_router.login_page(
            _request(settings, cookies={auth.SESSION_COOKIE: _token(settings)})
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    def test_already_logged_in_with_next(self, conn):
        settings = _settings()
        resp = auth_router.login_page(
            _request(settings, cookies={auth.SESSION_COOKIE: _token(settings)}),
            next="/tasks",
        )
        assert resp.headers["location"] == "/tasks"

    def test_strips_open_redirect_next(self, conn):
        settings = _settings()
        resp = auth_router.login_page(
            _request(settings, cookies={auth.SESSION_COOKIE: _token(settings)}),
            next="https://evil.example/",
        )
        assert resp.headers["location"] == "/"


class TestLoginSubmit:
    def test_success_sets_cookie_and_redirects(self, conn):
        settings = _settings()
        resp = auth_router.login_submit(
            _request(settings), username="alice", password="s3cret", next="", conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
        set_cookie = resp.headers["set-cookie"]
        assert auth.SESSION_COOKIE in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie

    def test_success_honors_safe_next(self, conn):
        settings = _settings()
        resp = auth_router.login_submit(
            _request(settings), username="alice", password="s3cret", next="/tasks", conn=conn
        )
        assert resp.headers["location"] == "/tasks"

    def test_success_rejects_open_redirect(self, conn):
        settings = _settings()
        resp = auth_router.login_submit(
            _request(settings),
            username="alice",
            password="s3cret",
            next="//evil.example",
            conn=conn,
        )
        assert resp.headers["location"] == "/"

    def test_wrong_password_is_401_with_error(self, conn):
        settings = _settings()
        resp = auth_router.login_submit(
            _request(settings), username="alice", password="nope", next="", conn=conn
        )
        assert resp.status_code == 401
        assert "Incorrect username or password" in resp.body.decode()
        assert "set-cookie" not in resp.headers

    def test_disabled_install_redirects_home(self, conn):
        resp = auth_router.login_submit(
            _request(_settings(enabled=False)), username="alice", password="s3cret", next="", conn=conn
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    def test_issued_token_verifies(self, conn):
        settings = _settings()
        resp = auth_router.login_submit(
            _request(settings), username="alice", password="s3cret", next="", conn=conn
        )
        # Extract the token from the Set-Cookie header.
        header = resp.headers["set-cookie"]
        token = header.split(auth.SESSION_COOKIE + "=", 1)[1].split(";", 1)[0]
        assert auth.read_session_token(settings.auth_session_secret, token) == "alice"


class TestLogout:
    def test_clears_cookie_and_returns_to_login(self, conn):
        resp = auth_router.logout(_request(_settings()))
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"
        set_cookie = resp.headers["set-cookie"]
        assert auth.SESSION_COOKIE in set_cookie
        # An expiry header (max-age=0 / expires in the past) means "clear".
        assert "max-age=0" in set_cookie.lower() or "expires=" in set_cookie.lower()