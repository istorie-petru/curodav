"""Settings > General's "Account" card (2026-09-08, routers/settings.py::
account_settings) -- one username/password form governing both the app's
own login and the app's stored Radicale connection credential (direct
request: "merge the concept of radicale username to the app username, and
merge the app password with the radicale password"). Replaces the old
separate change_login_password/change_radicale_password routes this file
used to test (see git history for that coverage) -- see account_settings'
own docstring for the full storage-backend split (env file vs app_meta)
this class exercises.

Also covers the new `POST /settings/restart` route (routers/settings.py::
restart_app) -- the "have a button actually restarting the app" half of
the same request. It's tested only for its *gating* and response shape;
the actual `os._exit` call is scheduled on a background thread half a
second out and is not exercised here (killing the test process would be
a bit much) -- `test_restart_schedules_exit_but_does_not_call_it_inline`
confirms the thread is what's deferring it, not a synchronous call.

Coverage, following this suite's usual conventions (direct router-function
calls, a bare SimpleNamespace settings stand-in, a tmp_path-backed conn):
  - account_settings: refuses to edit when env-configured with no
    CC_ENV_FILE known; writes the env file (uncommenting/replacing/
    appending, via env_file.update_env_file) when one is; otherwise
    persists to app_meta (hashed login, retrievable Radicale copy) same
    as the routes it replaces. Requires the current password to verify
    for any change on an existing account (username, password, or just
    the Radicale URL); creates a first account when none exists yet
    (password required, current_password not checked). Validation
    (empty/too short/mismatch), session re-mint + secret rotation on the
    app_meta path.
  - restart_app: no-op error outside deploy_mode == "production";
    otherwise a redirect note and a scheduled background exit.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.requests import Request

from src import auth, config, db, env_file
from src.routers import settings as settings_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _request(
    *,
    path="/settings/account",
    auth_username=None,
    auth_password=None,
    auth_session_secret="test-signing-secret",
    radicale_env_configured=False,
    radicale_base_url="http://127.0.0.1:5232/devuser/",
    radicale_password="devpass",
    env_file_path=None,
    deploy_mode="local",
):
    app = Starlette()
    app.state.settings = SimpleNamespace(
        auth_username=auth_username,
        auth_password=auth_password,
        auth_session_secret=auth_session_secret,
        radicale_env_configured=radicale_env_configured,
        radicale_base_url=radicale_base_url,
        radicale_username="devuser",
        radicale_password=radicale_password,
        env_file_path=env_file_path,
        deploy_mode=deploy_mode,
    )
    scope = {
        "type": "http", "method": "POST", "path": path, "query_string": b"",
        "scheme": "http", "server": ("testserver", 80), "root_path": "",
        "headers": [], "app": app,
    }
    return Request(scope)


class TestAccountSettingsAppMetaPath:
    """Neither auth nor Radicale env-configured -- the app_meta storage
    path, same shape the old change_login_password/change_radicale_password
    tests exercised."""

    def test_rejects_blank_username(self, conn):
        resp = settings_router.account_settings(
            _request(), username="  ", current_password="", new_password="newpassword1",
            new_password_confirm="newpassword1", radicale_url="", conn=conn,
        )
        assert "error=" in resp.headers["location"]
        assert auth.get_persisted_credentials(conn) is None

    def test_creates_first_account_with_no_current_password(self, conn):
        resp = settings_router.account_settings(
            _request(), username="alice", current_password="", new_password="newpassword1",
            new_password_confirm="newpassword1", radicale_url="", conn=conn,
        )
        assert resp.status_code == 303
        assert "note=" in resp.headers["location"]
        username, password_hash = auth.get_persisted_credentials(conn)
        assert username == "alice"
        assert auth._verify_password_hash("newpassword1", password_hash)
        # Merged: the same username/password also become the stored
        # Radicale credential.
        assert db.get_app_meta(conn, config.RADICALE_USERNAME_KEY) == "alice"
        assert db.get_app_meta(conn, config.RADICALE_PASSWORD_KEY) == "newpassword1"

    def test_first_account_requires_a_password(self, conn):
        resp = settings_router.account_settings(
            _request(), username="alice", current_password="", new_password="",
            new_password_confirm="", radicale_url="", conn=conn,
        )
        assert "error=" in resp.headers["location"]
        assert auth.get_persisted_credentials(conn) is None

    def test_first_account_marks_app_state_configured_and_sets_cookie(self, conn):
        req = _request()
        resp = settings_router.account_settings(
            req, username="alice", current_password="", new_password="newpassword1",
            new_password_confirm="newpassword1", radicale_url="", conn=conn,
        )
        assert req.app.state._cc_auth_configured is True
        set_cookie = resp.headers["set-cookie"]
        token = set_cookie.split(auth.SESSION_COOKIE + "=", 1)[1].split(";", 1)[0]
        assert auth.read_session_token("test-signing-secret", token) == "alice"

    def test_changing_requires_correct_current_password(self, conn):
        auth.set_persisted_credentials(conn, "alice", "oldpassword1")
        resp = settings_router.account_settings(
            _request(), username="alice", current_password="wrong", new_password="newpassword1",
            new_password_confirm="newpassword1", radicale_url="", conn=conn,
        )
        assert "error=" in resp.headers["location"]
        username, password_hash = auth.get_persisted_credentials(conn)
        assert auth._verify_password_hash("oldpassword1", password_hash)

    def test_changing_username_only_requires_current_password_too(self, conn):
        """Any change through this form -- not just a password change --
        needs the current password on an existing account, since it now
        also controls the Radicale connection."""
        auth.set_persisted_credentials(conn, "alice", "oldpassword1")
        resp = settings_router.account_settings(
            _request(), username="alice2", current_password="wrong", new_password="",
            new_password_confirm="", radicale_url="", conn=conn,
        )
        assert "error=" in resp.headers["location"]
        assert db.get_app_meta(conn, auth.AUTH_USERNAME_KEY) == "alice"

    def test_changing_with_correct_current_password_succeeds(self, conn):
        auth.set_persisted_credentials(conn, "alice", "oldpassword1")
        resp = settings_router.account_settings(
            _request(), username="alice", current_password="oldpassword1", new_password="newpassword1",
            new_password_confirm="newpassword1", radicale_url="", conn=conn,
        )
        assert "note=" in resp.headers["location"]
        username, password_hash = auth.get_persisted_credentials(conn)
        assert username == "alice"
        assert auth._verify_password_hash("newpassword1", password_hash)
        assert db.get_app_meta(conn, config.RADICALE_PASSWORD_KEY) == "newpassword1"

    def test_username_only_change_keeps_existing_password(self, conn):
        auth.set_persisted_credentials(conn, "alice", "oldpassword1")
        resp = settings_router.account_settings(
            _request(), username="alicia", current_password="oldpassword1", new_password="",
            new_password_confirm="", radicale_url="", conn=conn,
        )
        assert "note=" in resp.headers["location"]
        username, password_hash = auth.get_persisted_credentials(conn)
        assert username == "alicia"
        assert auth._verify_password_hash("oldpassword1", password_hash)
        assert db.get_app_meta(conn, config.RADICALE_USERNAME_KEY) == "alicia"
        # Radicale password key is untouched -- never silently persists
        # settings.radicale_password's dev-default fallback.
        assert db.get_app_meta(conn, config.RADICALE_PASSWORD_KEY) is None

    def test_radicale_url_saved_and_defaults_to_current_when_blank(self, conn):
        auth.set_persisted_credentials(conn, "alice", "oldpassword1")
        settings_router.account_settings(
            _request(radicale_base_url="http://127.0.0.1:5232/fallback/"),
            username="alice", current_password="oldpassword1", new_password="",
            new_password_confirm="", radicale_url="http://127.0.0.1:5232/me/", conn=conn,
        )
        assert db.get_app_meta(conn, config.RADICALE_URL_KEY) == "http://127.0.0.1:5232/me/"

        settings_router.account_settings(
            _request(radicale_base_url="http://127.0.0.1:5232/fallback/"),
            username="alice", current_password="oldpassword1", new_password="",
            new_password_confirm="", radicale_url="", conn=conn,
        )
        assert db.get_app_meta(conn, config.RADICALE_URL_KEY) == "http://127.0.0.1:5232/fallback/"

    def test_rejects_short_new_password(self, conn):
        resp = settings_router.account_settings(
            _request(), username="alice", current_password="", new_password="short",
            new_password_confirm="short", radicale_url="", conn=conn,
        )
        assert "error=" in resp.headers["location"]
        assert auth.get_persisted_credentials(conn) is None

    def test_rejects_mismatched_confirmation(self, conn):
        resp = settings_router.account_settings(
            _request(), username="alice", current_password="", new_password="newpassword1",
            new_password_confirm="different1", radicale_url="", conn=conn,
        )
        assert "error=" in resp.headers["location"]
        assert auth.get_persisted_credentials(conn) is None

    def test_rotates_session_secret_so_old_sessions_are_revoked(self, conn):
        """2026-09-07 audit fix, carried over from change_login_password
        -- see auth.rotate_session_secret's docstring."""
        auth.set_persisted_credentials(conn, "alice", "oldpassword1")
        old_secret = auth.session_secret(SimpleNamespace(auth_session_secret=None), conn)
        old_token = auth.make_session_token(old_secret, "alice")

        req = _request(auth_session_secret=None)
        resp = settings_router.account_settings(
            req, username="alice", current_password="oldpassword1", new_password="newpassword1",
            new_password_confirm="newpassword1", radicale_url="", conn=conn,
        )
        assert resp.status_code == 303

        new_secret = db.get_app_meta(conn, auth.AUTH_SECRET_KEY)
        assert new_secret and new_secret != old_secret
        assert auth.read_session_token(new_secret, old_token) is None
        set_cookie = resp.headers["set-cookie"]
        new_token = set_cookie.split(auth.SESSION_COOKIE + "=", 1)[1].split(";", 1)[0]
        assert auth.read_session_token(new_secret, new_token) == "alice"
        assert req.app.state._cc_auth_secret == new_secret


class TestAccountSettingsEnvPath:
    """Either half env-configured, with a CC_ENV_FILE known -- writes the
    real env file instead of app_meta."""

    def test_writes_env_file_for_auth_env_configured(self, conn, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text(
            "CC_AUTH_SECRET=abc\n"
            "# CC_AUTH_USERNAME=you\n"
            "# CC_AUTH_PASSWORD=change-me\n"
            "# CC_RADICALE_URL=http://127.0.0.1:5232/curodav/\n"
            "# CC_RADICALE_USER=curodav\n"
            "# CC_RADICALE_PASSWORD=\n"
        )
        resp = settings_router.account_settings(
            _request(
                auth_username="you", auth_password="change-me", env_file_path=str(env_path),
            ),
            username="petru", current_password="change-me", new_password="newpassword1",
            new_password_confirm="newpassword1", radicale_url="http://127.0.0.1:5232/petru/", conn=conn,
        )
        assert "note=" in resp.headers["location"]
        written = env_file.read_env_file(env_path)
        assert written["CC_AUTH_USERNAME"] == "petru"
        assert written["CC_AUTH_PASSWORD"] == "newpassword1"
        assert written["CC_RADICALE_USER"] == "petru"
        assert written["CC_RADICALE_PASSWORD"] == "newpassword1"
        assert written["CC_RADICALE_URL"] == "http://127.0.0.1:5232/petru/"
        # Nothing persisted to app_meta on this path.
        assert auth.get_persisted_credentials(conn) is None

    def test_writes_env_file_for_radicale_only_env_configured(self, conn, tmp_path):
        """Only CC_RADICALE_URL was ever env-configured -- saving through
        this form still writes the WHOLE account (including
        CC_AUTH_USERNAME/PASSWORD) to the env file, converting login from
        app_meta-managed to env-managed too. See account_settings'
        docstring for why this is deliberate, not a bug."""
        env_path = tmp_path / ".env"
        env_path.write_text("CC_RADICALE_URL=http://127.0.0.1:5232/curodav/\n")
        resp = settings_router.account_settings(
            _request(radicale_env_configured=True, env_file_path=str(env_path)),
            username="petru", current_password="", new_password="newpassword1",
            new_password_confirm="newpassword1", radicale_url="", conn=conn,
        )
        assert "note=" in resp.headers["location"]
        written = env_file.read_env_file(env_path)
        assert written["CC_AUTH_USERNAME"] == "petru"
        assert written["CC_AUTH_PASSWORD"] == "newpassword1"
        assert written["CC_RADICALE_USER"] == "petru"

    def test_current_password_verified_against_env_value(self, conn, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("CC_AUTH_SECRET=abc\n")
        resp = settings_router.account_settings(
            _request(auth_username="you", auth_password="change-me", env_file_path=str(env_path)),
            username="petru", current_password="wrong", new_password="newpassword1",
            new_password_confirm="newpassword1", radicale_url="", conn=conn,
        )
        assert "error=" in resp.headers["location"]
        assert env_file.read_env_file(env_path) == {"CC_AUTH_SECRET": "abc"}

    def test_username_only_env_change_does_not_require_new_password(self, conn, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("CC_AUTH_SECRET=abc\n")
        resp = settings_router.account_settings(
            _request(auth_username="you", auth_password="change-me", env_file_path=str(env_path)),
            username="petru", current_password="change-me", new_password="",
            new_password_confirm="", radicale_url="", conn=conn,
        )
        assert "note=" in resp.headers["location"]
        written = env_file.read_env_file(env_path)
        assert written["CC_AUTH_USERNAME"] == "petru"
        assert "CC_AUTH_PASSWORD" not in written

    def test_refuses_to_edit_when_env_configured_with_no_env_file_known(self, conn):
        resp = settings_router.account_settings(
            _request(auth_username="you", auth_password="change-me", env_file_path=None),
            username="petru", current_password="change-me", new_password="newpassword1",
            new_password_confirm="newpassword1", radicale_url="", conn=conn,
        )
        assert "error=" in resp.headers["location"]
        assert "curodav.env" in resp.headers["location"]

    def test_write_failure_surfaces_as_error_not_500(self, conn, tmp_path):
        """A directory where the env file should be -- update_env_file's
        open()/rename() raise OSError, which the route must catch."""
        bad_path = tmp_path / "not-a-file"
        bad_path.mkdir()
        resp = settings_router.account_settings(
            _request(auth_username="you", auth_password="change-me", env_file_path=str(bad_path)),
            username="petru", current_password="change-me", new_password="newpassword1",
            new_password_confirm="newpassword1", radicale_url="", conn=conn,
        )
        assert "error=" in resp.headers["location"]


class TestRestartApp:
    def test_no_op_outside_production(self, conn):
        resp = settings_router.restart_app(_request(deploy_mode="local"))
        assert "error=" in resp.headers["location"]

    def test_no_op_when_deploy_mode_missing(self, conn):
        req = _request()
        req.app.state.settings = SimpleNamespace()
        resp = settings_router.restart_app(req)
        assert "error=" in resp.headers["location"]

    def test_schedules_restart_in_production(self, conn, monkeypatch):
        scheduled = {}

        class _FakeTimer:
            def __init__(self, interval, function, args=()):
                scheduled["interval"] = interval
                scheduled["function"] = function
                scheduled["args"] = args

            def start(self):
                scheduled["started"] = True

        monkeypatch.setattr("src.routers.settings.threading.Timer", _FakeTimer)
        resp = settings_router.restart_app(_request(deploy_mode="production"))
        assert resp.status_code == 303
        assert "note=" in resp.headers["location"]
        # Deferred, not called inline -- the test process is still alive
        # to make this assertion at all.
        assert scheduled["started"] is True
        assert scheduled["interval"] > 0
