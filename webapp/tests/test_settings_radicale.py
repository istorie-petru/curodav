"""Settings > Data & Maintenance's "CalDAV / Radicale sync" card
(2026-09-08 -- read-only now; see routers/settings.py::account_settings'
docstring for the merge that superseded the old editable 3-field form this
file used to test, POST /settings/radicale, which is gone). The card just
shows the current URL and points at Settings > Your Profile (2026-09-11:
moved off General) for the actual connection (username/password/URL,
merged with the app's own login)."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request

from src import db
from src.routers import settings as settings_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


class TestSettingsDataMaintenanceRadicaleCard:
    def test_shows_current_url_and_points_to_your_profile(self, conn, tmp_path):
        from test_data_health import _request as _dm_request

        req = _dm_request(path="/settings/data-maintenance", db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups")
        body = settings_router.settings_data_maintenance(req, conn=conn).body.decode()
        assert 'href="/settings/your-profile"' in body
        # No POST form/action for this card any more -- it's a plain
        # read-only display now.
        assert 'action="/settings/radicale"' not in body

    def test_env_configured_note_shown(self, conn, tmp_path):
        from test_data_health import _request as _dm_request

        req = _dm_request(path="/settings/data-maintenance", db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups")
        req.app.state.settings.radicale_env_configured = True
        body = settings_router.settings_data_maintenance(req, conn=conn).body.decode()
        assert "CC_RADICALE_URL" in body


def _settings(**overrides):
    """Minimal stand-in for config.Settings, radicale-related fields only
    -- same SimpleNamespace-fake convention every other test file in this
    suite uses (see test_data_health.py's/test_phase8_settings_hub.py's own
    _request(_with_radicale) helpers)."""
    from types import SimpleNamespace

    base = dict(
        radicale_base_url="http://127.0.0.1:5232/devuser/",
        radicale_username="devuser",
        radicale_password="devpass",
        radicale_env_configured=False,
        radicale_public_base_url=None,
        env_file_path=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestRadicaleConfigSource:
    """2026-09-13 direct request: "I don't know if [the Radicale env vars]
    are set correctly if set in app or in the app setup" -- these three
    helpers are what Data & Maintenance's CalDAV card now reads to answer
    that without leaving the browser."""

    def test_dev_default_when_nothing_configured(self, conn):
        result = settings_router._radicale_config_source(_settings(), conn)
        assert "dev default" in result

    def test_database_when_persisted_via_settings(self, conn):
        from src import config

        db.set_app_meta(conn, config.RADICALE_URL_KEY, "http://127.0.0.1:5232/alice/")
        result = settings_router._radicale_config_source(_settings(), conn)
        assert "database" in result

    def test_environment_file_when_env_configured_with_known_path(self, conn):
        result = settings_router._radicale_config_source(
            _settings(radicale_env_configured=True, env_file_path="/srv/curodav/shared/.env"), conn
        )
        assert "environment file" in result
        assert "CC_RADICALE_URL" in result

    def test_environment_var_with_no_known_file(self, conn):
        result = settings_router._radicale_config_source(_settings(radicale_env_configured=True), conn)
        assert "environment variable" in result


class TestRadicaleEnvDrift:
    def test_none_when_not_env_configured(self):
        assert settings_router._env_file_drift(_settings()) is None

    def test_none_when_no_env_file_path_known(self):
        assert settings_router._env_file_drift(_settings(radicale_env_configured=True)) is None

    def test_none_when_file_matches_running_process(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text('CC_RADICALE_URL="http://127.0.0.1:5232/devuser/"\nCC_RADICALE_USER="devuser"\n')
        result = settings_router._env_file_drift(
            _settings(radicale_env_configured=True, env_file_path=str(env_path))
        )
        assert result is None

    def test_flags_drift_when_file_disagrees_with_running_process(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text('CC_RADICALE_URL="http://127.0.0.1:5232/bob/"\n')
        result = settings_router._env_file_drift(
            _settings(radicale_env_configured=True, env_file_path=str(env_path))
        )
        assert result is not None
        assert "CC_RADICALE_URL" in result
        assert "restart" in result.lower()


class TestRadicalePublicUrlMismatch:
    def test_none_when_public_url_unset(self):
        assert settings_router._radicale_public_url_mismatch(_settings()) is None

    def test_none_when_users_match(self):
        result = settings_router._radicale_public_url_mismatch(
            _settings(radicale_public_base_url="https://app.example.com/radicale/devuser/")
        )
        assert result is None

    def test_flags_mismatch_when_users_differ(self):
        result = settings_router._radicale_public_url_mismatch(
            _settings(radicale_public_base_url="https://app.example.com/radicale/someoneelse/")
        )
        assert result is not None
        assert "devuser" in result
        assert "someoneelse" in result


class TestCheckRadicaleConnection:
    def test_reports_friendly_message_when_unreachable(self):
        # An address nothing is listening on -- loopback, an arbitrary
        # high port -- fails fast (connection refused) without needing a
        # real Radicale instance or any network access in the test sandbox.
        ok, message = settings_router._check_radicale_connection(
            _settings(radicale_base_url="http://127.0.0.1:59991/devuser/")
        )
        assert ok is False
        assert "Could not reach Radicale" in message

    def test_route_redirects_with_error_note_on_failure(self, tmp_path):
        from test_phase8_settings_hub import _request_with_radicale

        req = _request_with_radicale("/settings/data-maintenance")
        req.app.state.settings.radicale_base_url = "http://127.0.0.1:59991/devuser/"
        req.app.state.settings.radicale_username = "devuser"
        req.app.state.settings.radicale_password = "devpass"
        resp = settings_router.test_radicale_connection(req)
        assert resp.status_code == 303
        assert "error=" in resp.headers["location"]
