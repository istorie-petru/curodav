"""Settings > General's "Login & security" cards (2026-08-30,
routers/settings.py::change_login_password / change_radicale_password) --
old/new/confirm password forms for the app's own login and the app's
stored Radicale connection credential. Both are the always-available
counterparts to a one-time setup step (respectively /setup and
/settings/radicale's plain 3-field form): see each route's own docstring.

Coverage, following this suite's usual conventions (direct router-function
calls, a bare SimpleNamespace settings stand-in, a tmp_path-backed conn):
  - change_login_password: no-op when env-configured, creates a first
    ("admin") account when none exists yet, requires+verifies the current
    password when one does, validation (empty/too short/mismatch/
    unchanged), re-mints the session cookie and marks app.state.
    _cc_auth_configured on success.
  - change_radicale_password: no-op when env-configured, requires the
    current password to match settings.radicale_password, validation
    (wrong current/empty/mismatch/unchanged), persists all three app_meta
    keys (url/username/password) on success -- same as the plain form,
    just with a verified password swap instead of a blind overwrite.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.requests import Request

from src import auth, config, db
from src.routers import settings as settings_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _request(
    *,
    path="/settings/change-password",
    auth_username=None,
    auth_password=None,
    auth_session_secret="test-signing-secret",
    radicale_env_configured=False,
    radicale_password="devpass",
):
    app = Starlette()
    app.state.settings = SimpleNamespace(
        auth_username=auth_username,
        auth_password=auth_password,
        auth_session_secret=auth_session_secret,
        radicale_env_configured=radicale_env_configured,
        radicale_base_url="http://127.0.0.1:5232/devuser/",
        radicale_username="devuser",
        radicale_password=radicale_password,
    )
    scope = {
        "type": "http", "method": "POST", "path": path, "query_string": b"",
        "scheme": "http", "server": ("testserver", 80), "root_path": "",
        "headers": [], "app": app,
    }
    return Request(scope)


class TestChangeLoginPassword:
    def test_no_op_when_env_configured(self, conn):
        resp = settings_router.change_login_password(
            _request(auth_username="alice", auth_password="s3cret"),
            current_password="",
            new_password="newpassword1",
            new_password_confirm="newpassword1",
            conn=conn,
        )
        assert resp.status_code == 303
        assert "error=" in resp.headers["location"]
        assert auth.get_persisted_credentials(conn) is None

    def test_creates_first_account_with_no_current_password(self, conn):
        resp = settings_router.change_login_password(
            _request(),
            current_password="",
            new_password="newpassword1",
            new_password_confirm="newpassword1",
            conn=conn,
        )
        assert resp.status_code == 303
        assert "note=" in resp.headers["location"]
        username, password_hash = auth.get_persisted_credentials(conn)
        assert username == "admin"
        assert auth._verify_password_hash("newpassword1", password_hash)

    def test_first_account_marks_app_state_configured_and_sets_cookie(self, conn):
        req = _request()
        resp = settings_router.change_login_password(
            req,
            current_password="",
            new_password="newpassword1",
            new_password_confirm="newpassword1",
            conn=conn,
        )
        assert req.app.state._cc_auth_configured is True
        set_cookie = resp.headers["set-cookie"]
        token = set_cookie.split(auth.SESSION_COOKIE + "=", 1)[1].split(";", 1)[0]
        assert auth.read_session_token("test-signing-secret", token) == "admin"

    def test_changing_requires_correct_current_password(self, conn):
        auth.set_persisted_credentials(conn, "alice", "oldpassword1")
        resp = settings_router.change_login_password(
            _request(),
            current_password="wrong",
            new_password="newpassword1",
            new_password_confirm="newpassword1",
            conn=conn,
        )
        assert "error=" in resp.headers["location"]
        username, password_hash = auth.get_persisted_credentials(conn)
        assert auth._verify_password_hash("oldpassword1", password_hash)

    def test_changing_with_correct_current_password_succeeds(self, conn):
        auth.set_persisted_credentials(conn, "alice", "oldpassword1")
        resp = settings_router.change_login_password(
            _request(),
            current_password="oldpassword1",
            new_password="newpassword1",
            new_password_confirm="newpassword1",
            conn=conn,
        )
        assert "note=" in resp.headers["location"]
        username, password_hash = auth.get_persisted_credentials(conn)
        assert username == "alice"
        assert auth._verify_password_hash("newpassword1", password_hash)

    def test_rejects_short_new_password(self, conn):
        resp = settings_router.change_login_password(
            _request(), current_password="", new_password="short", new_password_confirm="short", conn=conn
        )
        assert "error=" in resp.headers["location"]
        assert auth.get_persisted_credentials(conn) is None

    def test_rejects_mismatched_confirmation(self, conn):
        resp = settings_router.change_login_password(
            _request(),
            current_password="",
            new_password="newpassword1",
            new_password_confirm="different1",
            conn=conn,
        )
        assert "error=" in resp.headers["location"]
        assert auth.get_persisted_credentials(conn) is None

    def test_rejects_unchanged_password(self, conn):
        auth.set_persisted_credentials(conn, "alice", "samepassword1")
        resp = settings_router.change_login_password(
            _request(),
            current_password="samepassword1",
            new_password="samepassword1",
            new_password_confirm="samepassword1",
            conn=conn,
        )
        assert "error=" in resp.headers["location"]


class TestChangeRadicalePassword:
    def test_no_op_when_env_configured(self, conn):
        resp = settings_router.change_radicale_password(
            _request(radicale_env_configured=True),
            current_password="devpass",
            new_password="newpass1",
            new_password_confirm="newpass1",
            conn=conn,
        )
        assert "error=" in resp.headers["location"]
        assert db.get_app_meta(conn, config.RADICALE_PASSWORD_KEY) is None

    def test_requires_correct_current_password(self, conn):
        resp = settings_router.change_radicale_password(
            _request(),
            current_password="wrong",
            new_password="newpass1",
            new_password_confirm="newpass1",
            conn=conn,
        )
        assert "error=" in resp.headers["location"]
        assert db.get_app_meta(conn, config.RADICALE_PASSWORD_KEY) is None

    def test_succeeds_with_correct_current_password(self, conn):
        resp = settings_router.change_radicale_password(
            _request(),
            current_password="devpass",
            new_password="newpass1",
            new_password_confirm="newpass1",
            conn=conn,
        )
        assert "note=" in resp.headers["location"]
        assert db.get_app_meta(conn, config.RADICALE_PASSWORD_KEY) == "newpass1"
        assert db.get_app_meta(conn, config.RADICALE_URL_KEY) == "http://127.0.0.1:5232/devuser/"
        assert db.get_app_meta(conn, config.RADICALE_USERNAME_KEY) == "devuser"

    def test_rejects_mismatched_confirmation(self, conn):
        resp = settings_router.change_radicale_password(
            _request(),
            current_password="devpass",
            new_password="newpass1",
            new_password_confirm="different1",
            conn=conn,
        )
        assert "error=" in resp.headers["location"]
        assert db.get_app_meta(conn, config.RADICALE_PASSWORD_KEY) is None

    def test_rejects_unchanged_password(self, conn):
        resp = settings_router.change_radicale_password(
            _request(),
            current_password="devpass",
            new_password="devpass",
            new_password_confirm="devpass",
            conn=conn,
        )
        assert "error=" in resp.headers["location"]

    def test_rejects_empty_new_password(self, conn):
        resp = settings_router.change_radicale_password(
            _request(), current_password="devpass", new_password="", new_password_confirm="", conn=conn
        )
        assert "error=" in resp.headers["location"]
