"""Single-user authentication (2026-08-16, src/auth.py + routers/auth.py).
2026-08-29: forced first-run /setup for production deploys, CSRF
middleware, and login rate limiting -- all added to this same file.

The app runs with NO login by default (CC_DEPLOY_MODE="local", the
default); configure CC_AUTH_USERNAME + CC_AUTH_PASSWORD and every request
except /login, /setup and /static requires a signed session cookie.
Coverage, following this suite's usual conventions:

  - config: load_settings maps the CC_AUTH_*/CC_DEPLOY_MODE env vars onto
    Settings.
  - src/auth.py's pure functions: auth_enabled, verify_credentials
    (constant-time, disabled install), and the signed-cookie round trip
    (valid, tampered, wrong-secret, malformed, expired).
  - src/auth.py's password hashing (hash_password/_verify_password_hash)
    and persisted-credential helpers (get/set/has_persisted_credentials),
    plus setup_required's deploy_mode gating.
  - src/auth.py's AuthMiddleware over a real (minimal) FastAPI app via
    TestClient -- the middleware is the one layer this suite can't reach
    through router-function calls, so it gets its own tiny ASGI app with
    settings pointed at a test secret (no DB needed). Covers: 302-to-login
    for a signed-out page request, 401 JSON for /api/fetch requests, the
    public-path exemptions, a valid cookie passing through, and the forced
    /setup redirect for an unconfigured production install.
  - src/auth.py's CSRFMiddleware over the same kind of tiny app: same-origin
    POST passes, cross-origin POST is rejected, GET is never checked, and a
    request with no session cookie is never checked either.
  - src/auth.py's login rate limiting (login_rate_limited/
    record_failed_login/clear_login_attempts): a sliding window, keyed by
    client IP.
  - routers/auth.py's login/logout/setup routes via direct calls (the
    suite's router-function-call convention): disabled-install redirect,
    renders the form, already-logged-in redirect, successful login sets
    the cookie and honors a safe `next`, wrong credentials get a 401 +
    error message, rate-limited attempts get a 429, logout clears the
    cookie, `next` open-redirect safety, and the /setup flow (rendered
    only when required, validates the chosen password, persists it
    hashed, logs the browser in, and refuses to re-run once configured).
"""

from __future__ import annotations

import tempfile
import uuid
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
from src.routers import settings as settings_router


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """The login rate limiter is a module-level dict (src/auth.py) --
    process-wide state that would otherwise leak between tests (and
    between test files, though only this one exercises login_submit
    directly)."""
    auth.reset_rate_limits()
    yield
    auth.reset_rate_limits()


def _settings(*, enabled=True, **overrides) -> Settings:
    # db_path is a fresh, uniquely-named file under the system tmpdir on
    # every call (2026-08-30) -- since auth_enabled() now consults the DB
    # in every deploy mode, not just production (see its own docstring), a
    # single shared literal path here would let one test's persisted
    # credentials leak into every other test that builds its own
    # `_settings()` without overriding db_path (most of them). uuid4 keeps
    # this a plain function (no fixture plumbing needed at ~60 call sites)
    # while still giving each Settings instance its own isolated file.
    base = Settings(
        radicale_base_url="http://127.0.0.1:5232/devuser/",
        radicale_username="devuser",
        radicale_password="devpass",
        calendar_collection="calendar",
        tasks_collection="tasks",
        contacts_collection="contacts",
        db_path=Path(tempfile.gettempdir()) / f"cc-auth-test-{uuid.uuid4().hex}.sqlite",
        sync_interval_seconds=60,
        backup_dir=Path(tempfile.gettempdir()) / f"cc-auth-test-backups-{uuid.uuid4().hex}",
    )
    if enabled:
        base = replace(
            base,
            auth_username="alice",
            auth_password="s3cret",
            auth_session_secret="test-signing-secret",
        )
    return replace(base, **overrides)


def _request(
    settings, *, cookies=None, path="/login", state_extra=None, client_host=None, scheme="http"
) -> Request:
    headers = []
    if cookies:
        cookie = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers.append((b"cookie", cookie.encode()))
    state = SimpleNamespace(settings=settings, **(state_extra or {}))
    fake_app = SimpleNamespace(state=state)
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "scheme": scheme,
        "server": ("testserver", 80),
        "root_path": "",
        "headers": headers,
        "app": fake_app,
    }
    if client_host:
        scope["client"] = (client_host, 12345)
    return Request(scope)


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

    def test_deploy_mode_defaults_to_local(self, monkeypatch):
        monkeypatch.delenv("CC_DEPLOY_MODE", raising=False)
        from src.config import load_settings

        assert load_settings().deploy_mode == "local"

    def test_deploy_mode_reads_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "c.sqlite"))
        monkeypatch.setenv("CC_DEPLOY_MODE", "production")
        from src.config import load_settings

        assert load_settings().deploy_mode == "production"

    def test_radicale_env_configured_false_by_default(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "c.sqlite"))
        monkeypatch.delenv("CC_RADICALE_URL", raising=False)
        from src.config import load_settings

        assert load_settings().radicale_env_configured is False

    def test_radicale_env_configured_true_when_url_set(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "c.sqlite"))
        monkeypatch.setenv("CC_RADICALE_URL", "http://127.0.0.1:5232/me/")
        from src.config import load_settings

        assert load_settings().radicale_env_configured is True


class TestApplyPersistedRadicaleOverrides:
    def test_no_op_when_env_configured(self, conn):
        from src.config import apply_persisted_radicale_overrides
        from src import db

        db.set_app_meta(conn, "radicale_base_url", "http://persisted/")
        db.set_app_meta(conn, "radicale_username", "persisted-user")
        db.set_app_meta(conn, "radicale_password", "persisted-pass")
        settings = _settings(radicale_env_configured=True)
        result = apply_persisted_radicale_overrides(settings, conn)
        assert result is settings

    def test_no_op_when_nothing_persisted(self, conn):
        from src.config import apply_persisted_radicale_overrides

        settings = _settings(radicale_env_configured=False)
        result = apply_persisted_radicale_overrides(settings, conn)
        assert result.radicale_base_url == settings.radicale_base_url
        assert result.radicale_username == settings.radicale_username

    def test_overrides_when_persisted_and_not_env_configured(self, conn):
        from src.config import apply_persisted_radicale_overrides
        from src import db

        db.set_app_meta(conn, "radicale_base_url", "http://persisted/me/")
        db.set_app_meta(conn, "radicale_username", "persisted-user")
        db.set_app_meta(conn, "radicale_password", "persisted-pass")
        settings = _settings(radicale_env_configured=False)
        result = apply_persisted_radicale_overrides(settings, conn)
        assert result.radicale_base_url == "http://persisted/me/"
        assert result.radicale_username == "persisted-user"
        assert result.radicale_password == "persisted-pass"

    def test_partial_persisted_data_is_ignored(self, conn):
        from src.config import apply_persisted_radicale_overrides
        from src import db

        db.set_app_meta(conn, "radicale_base_url", "http://persisted/me/")
        # username/password never saved -- a partial/corrupt app_meta
        # state must not half-apply.
        settings = _settings(radicale_env_configured=False)
        result = apply_persisted_radicale_overrides(settings, conn)
        assert result.radicale_base_url == settings.radicale_base_url


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

    def test_local_deploy_mode_honors_persisted_credentials(self, conn):
        # 2026-08-30: local mode (the default) used to ignore the DB
        # entirely here -- only the env-var pair could turn login on for a
        # local/dev install. Changed so Settings > General's password form
        # (routers/settings.py::change_login_password) actually takes
        # effect locally too, not just in production -- see auth_enabled's
        # own docstring for the tradeoff.
        settings = _settings(enabled=False)
        assert not auth.auth_enabled(settings, conn)
        auth.set_persisted_credentials(conn, "alice", "s3cret123")
        assert auth.auth_enabled(settings, conn)

    def test_production_deploy_mode_honors_persisted_credentials(self, conn):
        settings = _settings(enabled=False, deploy_mode="production")
        assert not auth.auth_enabled(settings, conn)
        auth.set_persisted_credentials(conn, "alice", "s3cret123")
        assert auth.auth_enabled(settings, conn)

    def test_production_deploy_mode_opens_own_connection(self, tmp_path):
        settings = _settings(
            enabled=False, deploy_mode="production", db_path=tmp_path / "cache.sqlite"
        )
        assert not auth.auth_enabled(settings)
        with db.connect(settings.db_path) as c:
            auth.set_persisted_credentials(c, "alice", "s3cret123")
        assert auth.auth_enabled(settings)

    def test_env_pair_wins_even_in_production(self, conn):
        # Both configured -- the env pair is enough on its own, no DB hit
        # needed (and none happens, since conn is never touched here).
        settings = _settings(enabled=True, deploy_mode="production")
        assert auth.auth_enabled(settings, conn)


class TestPersistedCredentials:
    def test_none_when_unset(self, conn):
        assert auth.get_persisted_credentials(conn) is None
        assert not auth.has_persisted_credentials(_settings(deploy_mode="production"), conn)

    def test_set_then_get(self, conn):
        auth.set_persisted_credentials(conn, "alice", "s3cret123")
        username, password_hash = auth.get_persisted_credentials(conn)
        assert username == "alice"
        assert password_hash.startswith("pbkdf2_sha256$")
        assert auth.has_persisted_credentials(
            _settings(deploy_mode="production"), conn
        )

    def test_password_is_never_stored_in_the_clear(self, conn):
        auth.set_persisted_credentials(conn, "alice", "s3cret123")
        _, password_hash = auth.get_persisted_credentials(conn)
        assert "s3cret123" not in password_hash


class TestPasswordHashing:
    def test_round_trip(self):
        encoded = auth.hash_password("s3cret123")
        assert auth._verify_password_hash("s3cret123", encoded)

    def test_wrong_password_fails(self):
        encoded = auth.hash_password("s3cret123")
        assert not auth._verify_password_hash("nope", encoded)

    def test_different_salts_for_the_same_password(self):
        assert auth.hash_password("s3cret123") != auth.hash_password("s3cret123")

    def test_malformed_hash_fails_closed(self):
        assert not auth._verify_password_hash("anything", "garbage")
        assert not auth._verify_password_hash("anything", "pbkdf2_sha256$not-an-int$aa$bb")
        assert not auth._verify_password_hash("anything", "bcrypt$12$salt$hash")


class TestSetupRequired:
    def test_local_deploy_mode_never_requires_setup(self, conn):
        assert not auth.setup_required(_settings(enabled=False), conn)
        assert not auth.setup_required(_settings(enabled=True), conn)

    def test_production_with_no_account_requires_setup(self, conn):
        assert auth.setup_required(_settings(enabled=False, deploy_mode="production"), conn)

    def test_production_with_env_pair_does_not_require_setup(self, conn):
        assert not auth.setup_required(_settings(enabled=True, deploy_mode="production"), conn)

    def test_production_with_persisted_account_does_not_require_setup(self, conn):
        settings = _settings(enabled=False, deploy_mode="production")
        auth.set_persisted_credentials(conn, "alice", "s3cret123")
        assert not auth.setup_required(settings, conn)

    def test_no_settings_never_requires_setup(self):
        assert not auth.setup_required(None)


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

    def test_persisted_account(self, conn):
        settings = _settings(enabled=False)
        auth.set_persisted_credentials(conn, "bob", "hunter22")
        assert auth.verify_credentials(settings, "bob", "hunter22", conn)
        assert not auth.verify_credentials(settings, "bob", "wrong", conn)
        assert not auth.verify_credentials(settings, "mallory", "hunter22", conn)

    def test_env_pair_checked_before_persisted_account(self, conn):
        # Both an env pair and a (different) persisted account exist --
        # the env pair alone is sufficient and checked first.
        settings = _settings(enabled=True)
        auth.set_persisted_credentials(conn, "bob", "hunter22")
        assert auth.verify_credentials(settings, "alice", "s3cret", conn)
        assert auth.verify_credentials(settings, "bob", "hunter22", conn)


class TestIsSecureRequest:
    def test_https_scheme(self):
        assert auth.is_secure_request(_request(_settings(), scheme="https"))

    def test_http_scheme(self):
        assert not auth.is_secure_request(_request(_settings(), scheme="http"))


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


def _prod_settings(tmp_path, **overrides):
    return _settings(
        enabled=False, deploy_mode="production", db_path=tmp_path / "cache.sqlite", **overrides
    )


class TestAuthMiddlewareForcedSetup:
    """2026-08-29: a production deploy (CC_DEPLOY_MODE=production) with no
    account yet is forced to GET/POST /setup instead of staying open."""

    def test_unconfigured_production_redirects_to_setup(self, tmp_path):
        client = TestClient(_auth_app(_prod_settings(tmp_path)), follow_redirects=False)
        resp = client.get("/hello")
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("/setup?next=")

    def test_unconfigured_production_setup_path_passes_through(self, tmp_path):
        client = TestClient(_auth_app(_prod_settings(tmp_path)), follow_redirects=False)
        # No /setup route on this tiny test app -- a 404 (not a 302/401)
        # proves the middleware let the request through to the app instead
        # of redirecting/denying it.
        resp = client.get("/setup")
        assert resp.status_code == 404

    def test_unconfigured_production_api_gets_401_json(self, tmp_path):
        client = TestClient(_auth_app(_prod_settings(tmp_path)), follow_redirects=False)
        resp = client.get("/api/ping")
        assert resp.status_code == 401

    def test_configured_production_behaves_like_normal_auth(self, tmp_path):
        settings = _prod_settings(tmp_path)
        with db.connect(settings.db_path) as c:
            auth.set_persisted_credentials(c, "alice", "s3cret123")
        client = TestClient(_auth_app(settings), follow_redirects=False)
        resp = client.get("/hello")
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("/login?next=")

    def test_configured_production_with_valid_session_passes(self, tmp_path):
        settings = _prod_settings(tmp_path, auth_session_secret="test-signing-secret")
        with db.connect(settings.db_path) as c:
            auth.set_persisted_credentials(c, "alice", "s3cret123")
        client = TestClient(_auth_app(settings), follow_redirects=False)
        client.cookies.set(
            auth.SESSION_COOKIE,
            auth.make_session_token(settings.auth_session_secret, "alice"),
        )
        assert client.get("/hello").json() == {"hello": "world"}

    def test_configured_cache_is_sticky(self, tmp_path):
        # Once the middleware has seen a configured install, it doesn't
        # re-check the DB -- deleting the persisted account afterwards
        # must not flip the install back to "needs setup" mid-process.
        settings = _prod_settings(tmp_path)
        with db.connect(settings.db_path) as c:
            auth.set_persisted_credentials(c, "alice", "s3cret123")
        client = TestClient(_auth_app(settings), follow_redirects=False)
        first = client.get("/hello")
        assert first.status_code == 302 and "/login?next=" in first.headers["location"]
        with db.connect(settings.db_path) as c:
            db.set_app_meta(c, auth.AUTH_USERNAME_KEY, "")
            db.set_app_meta(c, auth.AUTH_PASSWORD_HASH_KEY, "")
        second = client.get("/hello")
        assert second.status_code == 302 and "/login?next=" in second.headers["location"]


# --------------------------------------------------------------------- #
# src/auth.py -- CSRFMiddleware over a real ASGI app
# --------------------------------------------------------------------- #


def _csrf_app(settings):
    app = FastAPI()
    app.state.settings = settings
    app.state.bridge = None

    @app.get("/hello")
    def hello():
        return JSONResponse({"hello": "world"})

    @app.post("/mutate")
    def mutate():
        return JSONResponse({"ok": True})

    app.add_middleware(auth.CSRFMiddleware)
    return app


class TestCSRFMiddleware:
    def test_get_is_never_checked(self):
        client = TestClient(_csrf_app(_settings()))
        assert client.get("/hello").status_code == 200

    def test_post_without_session_cookie_passes(self):
        # Nothing for a forged request to exploit yet (e.g. the login POST
        # itself, before any cookie exists).
        client = TestClient(_csrf_app(_settings()))
        assert client.post("/mutate").status_code == 200

    def test_post_with_session_and_matching_origin_passes(self):
        client = TestClient(_csrf_app(_settings()), base_url="http://testserver")
        client.cookies.set(auth.SESSION_COOKIE, "any-value")
        resp = client.post("/mutate", headers={"Origin": "http://testserver"})
        assert resp.status_code == 200

    def test_post_with_session_and_cross_origin_is_rejected(self):
        client = TestClient(_csrf_app(_settings()), base_url="http://testserver")
        client.cookies.set(auth.SESSION_COOKIE, "any-value")
        resp = client.post("/mutate", headers={"Origin": "https://evil.example"})
        assert resp.status_code == 403
        assert resp.json()["ok"] is False

    def test_post_with_session_and_matching_referer_passes(self):
        client = TestClient(_csrf_app(_settings()), base_url="http://testserver")
        client.cookies.set(auth.SESSION_COOKIE, "any-value")
        resp = client.post(
            "/mutate", headers={"Referer": "http://testserver/tasks"}
        )
        assert resp.status_code == 200

    def test_post_with_session_and_no_origin_or_referer_is_rejected(self):
        client = TestClient(_csrf_app(_settings()), base_url="http://testserver")
        client.cookies.set(auth.SESSION_COOKIE, "any-value")
        assert client.post("/mutate").status_code == 403

    def test_disabled_auth_skips_the_check_entirely(self):
        # Auth off means no ambient credential worth protecting -- a
        # cross-origin POST goes through untouched, same as today.
        client = TestClient(_csrf_app(_settings(enabled=False)), base_url="http://testserver")
        client.cookies.set(auth.SESSION_COOKIE, "any-value")
        resp = client.post("/mutate", headers={"Origin": "https://evil.example"})
        assert resp.status_code == 200


# --------------------------------------------------------------------- #
# src/auth.py -- login rate limiting
# --------------------------------------------------------------------- #


class TestLoginRateLimiting:
    def test_not_limited_before_the_threshold(self):
        key = "203.0.113.1"
        for _ in range(auth.RATE_LIMIT_MAX_ATTEMPTS - 1):
            auth.record_failed_login(key)
        assert not auth.login_rate_limited(key)

    def test_limited_at_the_threshold(self):
        key = "203.0.113.2"
        for _ in range(auth.RATE_LIMIT_MAX_ATTEMPTS):
            auth.record_failed_login(key)
        assert auth.login_rate_limited(key)

    def test_different_keys_are_independent(self):
        key_a, key_b = "203.0.113.3", "203.0.113.4"
        for _ in range(auth.RATE_LIMIT_MAX_ATTEMPTS):
            auth.record_failed_login(key_a)
        assert auth.login_rate_limited(key_a)
        assert not auth.login_rate_limited(key_b)

    def test_clear_resets_the_window(self):
        key = "203.0.113.5"
        for _ in range(auth.RATE_LIMIT_MAX_ATTEMPTS):
            auth.record_failed_login(key)
        assert auth.login_rate_limited(key)
        auth.clear_login_attempts(key)
        assert not auth.login_rate_limited(key)

    def test_client_ip_falls_back_to_unknown(self):
        assert auth.client_ip(_request(_settings())) == "unknown"

    def test_client_ip_reads_the_real_client(self):
        req = _request(_settings(), client_host="198.51.100.7")
        assert auth.client_ip(req) == "198.51.100.7"


# --------------------------------------------------------------------- #
# routers/auth.py -- login/logout routes
# --------------------------------------------------------------------- #


class TestLoginPage:
    def test_disabled_install_redirects_home(self, conn):
        resp = auth_router.login_page(_request(_settings(enabled=False)), conn=conn)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    def test_renders_the_form(self, conn):
        resp = auth_router.login_page(_request(_settings()), conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert "name=\"username\"" in body
        assert "name=\"password\"" in body
        assert "action=\"/login\"" in body

    def test_already_logged_in_redirects(self, conn):
        settings = _settings()
        resp = auth_router.login_page(
            _request(settings, cookies={auth.SESSION_COOKIE: _token(settings)}), conn=conn
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    def test_already_logged_in_with_next(self, conn):
        settings = _settings()
        resp = auth_router.login_page(
            _request(settings, cookies={auth.SESSION_COOKIE: _token(settings)}),
            next="/tasks",
            conn=conn,
        )
        assert resp.headers["location"] == "/tasks"

    def test_strips_open_redirect_next(self, conn):
        settings = _settings()
        resp = auth_router.login_page(
            _request(settings, cookies={auth.SESSION_COOKIE: _token(settings)}),
            next="https://evil.example/",
            conn=conn,
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
        # Plain HTTP request -- no Secure flag (see auth.is_secure_request's
        # own docstring on why: it would just get the cookie dropped).
        assert "Secure" not in set_cookie

    def test_success_over_https_sets_secure_flag(self, conn):
        settings = _settings()
        resp = auth_router.login_submit(
            _request(settings, scheme="https"), username="alice", password="s3cret", next="", conn=conn
        )
        assert "Secure" in resp.headers["set-cookie"]

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

    def test_rate_limited_after_repeated_failures(self, conn):
        settings = _settings()
        req = _request(settings, client_host="198.51.100.9")
        for _ in range(auth.RATE_LIMIT_MAX_ATTEMPTS):
            resp = auth_router.login_submit(
                req, username="alice", password="nope", next="", conn=conn
            )
            assert resp.status_code == 401
        locked = auth_router.login_submit(
            req, username="alice", password="s3cret", next="", conn=conn
        )
        assert locked.status_code == 429
        assert "Too many attempts" in locked.body.decode()
        assert "set-cookie" not in locked.headers

    def test_successful_login_clears_the_rate_limit(self, conn):
        settings = _settings()
        req = _request(settings, client_host="198.51.100.10")
        auth_router.login_submit(req, username="alice", password="nope", next="", conn=conn)
        resp = auth_router.login_submit(
            req, username="alice", password="s3cret", next="", conn=conn
        )
        assert resp.status_code == 303
        assert not auth.login_rate_limited("198.51.100.10")


class TestLogout:
    def test_clears_cookie_and_returns_to_login(self, conn):
        resp = auth_router.logout(_request(_settings()))
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"
        set_cookie = resp.headers["set-cookie"]
        assert auth.SESSION_COOKIE in set_cookie
        # An expiry header (max-age=0 / expires in the past) means "clear".
        assert "max-age=0" in set_cookie.lower() or "expires=" in set_cookie.lower()

    def test_clears_with_secure_flag_over_https(self):
        resp = auth_router.logout(_request(_settings(), scheme="https"))
        assert "Secure" in resp.headers["set-cookie"]


# --------------------------------------------------------------------- #
# routers/auth.py -- the forced first-run /setup flow (2026-08-29)
# --------------------------------------------------------------------- #


def _prod_no_account_settings(**overrides) -> Settings:
    return _settings(enabled=False, deploy_mode="production", **overrides)


class TestSetupPage:
    def test_renders_when_required(self, conn):
        resp = auth_router.setup_page(_request(_prod_no_account_settings(), path="/setup"), conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert "name=\"username\"" in body
        assert "name=\"password\"" in body
        assert "name=\"password_confirm\"" in body
        assert "action=\"/setup\"" in body

    def test_redirects_home_when_local_deploy_mode(self, conn):
        resp = auth_router.setup_page(_request(_settings(enabled=False)), conn=conn)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    def test_redirects_to_login_once_configured_via_env(self, conn):
        resp = auth_router.setup_page(
            _request(_prod_no_account_settings(auth_username="alice", auth_password="s3cret")),
            conn=conn,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"

    def test_redirects_to_login_once_configured_via_persisted_account(self, conn):
        settings = _prod_no_account_settings()
        auth.set_persisted_credentials(conn, "alice", "s3cret123")
        resp = auth_router.setup_page(_request(settings), conn=conn)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"


class TestSetupSubmit:
    def test_success_persists_hashed_account_and_logs_in(self, conn):
        settings = _prod_no_account_settings(auth_session_secret="test-signing-secret")
        resp = auth_router.setup_submit(
            _request(settings),
            username="alice",
            password="s3cret123",
            password_confirm="s3cret123",
            radicale_url="",
            radicale_username="",
            radicale_password="",
            conn=conn,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
        set_cookie = resp.headers["set-cookie"]
        assert auth.SESSION_COOKIE in set_cookie
        username, password_hash = auth.get_persisted_credentials(conn)
        assert username == "alice"
        assert auth._verify_password_hash("s3cret123", password_hash)
        token = set_cookie.split(auth.SESSION_COOKIE + "=", 1)[1].split(";", 1)[0]
        assert auth.read_session_token(settings.auth_session_secret, token) == "alice"

    def test_marks_app_state_configured(self, conn):
        settings = _prod_no_account_settings()
        req = _request(settings)
        auth_router.setup_submit(
            req,
            username="alice",
            password="s3cret123",
            password_confirm="s3cret123",
            radicale_url="",
            radicale_username="",
            radicale_password="",
            conn=conn,
        )
        assert req.app.state._cc_auth_configured is True

    def test_secure_cookie_flag_over_https(self, conn):
        settings = _prod_no_account_settings()
        resp = auth_router.setup_submit(
            _request(settings, scheme="https"),
            username="alice",
            password="s3cret123",
            password_confirm="s3cret123",
            radicale_url="",
            radicale_username="",
            radicale_password="",
            conn=conn,
        )
        assert "Secure" in resp.headers["set-cookie"]

    def test_optional_radicale_fields_persisted_when_filled_in(self, conn):
        settings = _prod_no_account_settings()
        auth_router.setup_submit(
            _request(settings),
            username="alice",
            password="s3cret123",
            password_confirm="s3cret123",
            radicale_url="http://127.0.0.1:5232/alice/",
            radicale_username="alice",
            radicale_password="hunter2",
            conn=conn,
        )
        assert db.get_app_meta(conn, "radicale_base_url") == "http://127.0.0.1:5232/alice/"
        assert db.get_app_meta(conn, "radicale_username") == "alice"
        assert db.get_app_meta(conn, "radicale_password") == "hunter2"

    def test_radicale_fields_skipped_when_partially_filled(self, conn):
        settings = _prod_no_account_settings()
        auth_router.setup_submit(
            _request(settings),
            username="alice",
            password="s3cret123",
            password_confirm="s3cret123",
            radicale_url="http://127.0.0.1:5232/alice/",
            radicale_username="",
            radicale_password="",
            conn=conn,
        )
        assert db.get_app_meta(conn, "radicale_base_url") is None

    def test_radicale_fields_skipped_when_env_already_configured(self, conn):
        settings = _prod_no_account_settings(radicale_env_configured=True)
        auth_router.setup_submit(
            _request(settings),
            username="alice",
            password="s3cret123",
            password_confirm="s3cret123",
            radicale_url="http://127.0.0.1:5232/alice/",
            radicale_username="alice",
            radicale_password="hunter2",
            conn=conn,
        )
        assert db.get_app_meta(conn, "radicale_base_url") is None

    def test_rejects_blank_username(self, conn):
        resp = auth_router.setup_submit(
            _request(_prod_no_account_settings()),
            username="  ",
            password="s3cret123",
            password_confirm="s3cret123",
            conn=conn,
        )
        assert resp.status_code == 400
        assert "Choose a username" in resp.body.decode()
        assert auth.get_persisted_credentials(conn) is None

    def test_rejects_short_password(self, conn):
        resp = auth_router.setup_submit(
            _request(_prod_no_account_settings()),
            username="alice",
            password="short",
            password_confirm="short",
            conn=conn,
        )
        assert resp.status_code == 400
        assert "at least 8 characters" in resp.body.decode()

    def test_rejects_mismatched_confirmation(self, conn):
        resp = auth_router.setup_submit(
            _request(_prod_no_account_settings()),
            username="alice",
            password="s3cret123",
            password_confirm="different",
            conn=conn,
        )
        assert resp.status_code == 400
        assert "do not match" in resp.body.decode()
        assert auth.get_persisted_credentials(conn) is None

    def test_refuses_to_run_again_once_configured(self, conn):
        settings = _prod_no_account_settings()
        auth.set_persisted_credentials(conn, "alice", "s3cret123")
        resp = auth_router.setup_submit(
            _request(settings),
            username="mallory",
            password="hijacked1",
            password_confirm="hijacked1",
            conn=conn,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"
        # The original account is untouched.
        username, _ = auth.get_persisted_credentials(conn)
        assert username == "alice"

    def test_disabled_in_local_deploy_mode(self, conn):
        resp = auth_router.setup_submit(
            _request(_settings(enabled=False)),
            username="alice",
            password="s3cret123",
            password_confirm="s3cret123",
            conn=conn,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"
        assert auth.get_persisted_credentials(conn) is None


# --------------------------------------------------------------------- #
# Settings > Purge all + the session (Settings > Advanced). A purge wipes
# app_meta -- where the auto-generated session signing secret lives -- so it
# must behave like a fresh install: the memoized secret is dropped and the
# cookie cleared, which forces a re-login when auth is enabled.
# --------------------------------------------------------------------- #


class TestPurgeAllInvalidatesSession:
    def test_drops_secret_cache_and_clears_cookie(self, conn):
        req = _request(
            _settings(),
            state_extra={"_cc_auth_secret": "old-secret", "_cc_auth_configured": True},
        )
        resp = settings_router.purge_all(req, conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/data-maintenance"
        # The session cookie is cleared and the memoized secret dropped.
        header = resp.headers["set-cookie"]
        assert auth.SESSION_COOKIE in header
        assert "max-age=0" in header.lower()
        assert req.app.state._cc_auth_secret is None
        # app_meta is wiped, so an auto-generated secret is gone with it.
        assert db.get_app_meta(conn, auth.AUTH_SECRET_KEY) is None
        # 2026-08-29: the "install is configured" cache (a /setup-created
        # account) is dropped too, so a purged production install is
        # forced back through /setup like a genuinely fresh database.
        assert req.app.state._cc_auth_configured is False

    def test_clears_with_secure_flag_over_https(self, conn):
        req = _request(_settings(), scheme="https")
        resp = settings_router.purge_all(req, conn=conn)
        assert "Secure" in resp.headers["set-cookie"]

    def test_auto_generated_secret_re_mints_after_purge(self, tmp_path):
        settings = _settings(auth_session_secret=None, db_path=tmp_path / "cache.sqlite")
        app = _auth_app(settings)
        client = TestClient(app, follow_redirects=False)

        # The login flow mints the secret once and persists it to app_meta.
        with db.connect(settings.db_path) as conn:
            old_secret = auth.session_secret(settings, conn)
        client.cookies.set(auth.SESSION_COOKIE, auth.make_session_token(old_secret, "alice"))

        # A valid pre-purge cookie passes through (and primes the cache).
        assert client.get("/hello").json() == {"hello": "world"}

        # Purge all: wipe every table (incl. app_meta) and drop the
        # memoized secret -- exactly what purge_all now does.
        with db.connect(settings.db_path) as conn:
            db.purge_all_data(conn)
        app.state._cc_auth_secret = None

        # The same cookie no longer verifies against the freshly re-minted
        # secret, so the signed-in browser is back at /login.
        assert client.get("/hello").status_code == 302
        with db.connect(settings.db_path) as conn:
            new_secret = db.get_app_meta(conn, auth.AUTH_SECRET_KEY)
        assert new_secret and new_secret != old_secret