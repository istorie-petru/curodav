"""Settings > Data & Maintenance's "CalDAV / Radicale sync" card
(2026-08-29, routers/settings.py::settings_radicale) -- the always-
available counterpart to /setup's one-time "connect to Radicale" step
(routers/auth.py::setup_submit), since that page only ever renders once
per install. Env-configured installs (CC_RADICALE_URL set) are read-only
here; everyone else can save/update a connection, persisted the same way
/setup does (config.RADICALE_*_KEY in app_meta, applied on the next
restart -- see config.py::apply_persisted_radicale_overrides)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.requests import Request

from src import config, db
from src.routers import settings as settings_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _request(*, radicale_env_configured=False):
    app = Starlette()
    app.state.settings = SimpleNamespace(
        radicale_env_configured=radicale_env_configured,
        radicale_username="",
        radicale_base_url="http://127.0.0.1:5232/devuser/",
    )
    scope = {
        "type": "http", "method": "POST", "path": "/settings/radicale", "query_string": b"",
        "scheme": "http", "server": ("testserver", 80), "root_path": "",
        "headers": [], "app": app,
    }
    return Request(scope)


class TestSettingsRadicale:
    def test_saves_when_all_fields_filled(self, conn):
        resp = settings_router.settings_radicale(
            _request(),
            radicale_url="http://127.0.0.1:5232/me/",
            radicale_username="me",
            radicale_password="hunter2",
            conn=conn,
        )
        assert resp.status_code == 303
        assert db.get_app_meta(conn, config.RADICALE_URL_KEY) == "http://127.0.0.1:5232/me/"
        assert db.get_app_meta(conn, config.RADICALE_USERNAME_KEY) == "me"
        assert db.get_app_meta(conn, config.RADICALE_PASSWORD_KEY) == "hunter2"

    def test_skips_when_partially_filled(self, conn):
        settings_router.settings_radicale(
            _request(), radicale_url="http://127.0.0.1:5232/me/", radicale_username="", radicale_password="", conn=conn
        )
        assert db.get_app_meta(conn, config.RADICALE_URL_KEY) is None

    def test_no_op_when_env_configured(self, conn):
        settings_router.settings_radicale(
            _request(radicale_env_configured=True),
            radicale_url="http://127.0.0.1:5232/me/",
            radicale_username="me",
            radicale_password="hunter2",
            conn=conn,
        )
        assert db.get_app_meta(conn, config.RADICALE_URL_KEY) is None

    def test_data_maintenance_page_shows_env_configured_note(self, conn, tmp_path):
        from test_data_health import _request as _dm_request

        req = _dm_request(path="/settings/data-maintenance", db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups")
        # The shared test_data_health._request helper's SimpleNamespace
        # predates these fields -- confirms the route's getattr-guarded
        # defaults (routers/settings.py::settings_data_maintenance) don't
        # crash against it.
        body = settings_router.settings_data_maintenance(req, conn=conn).body.decode()
        # 2026-09-08 (direct request): the "CalDAV / Radicale sync"
        # h2.section-label is gone (every Settings section-label was
        # removed) -- the editable form's own action attribute is what
        # this test actually needs to confirm.
        assert 'action="/settings/radicale"' in body  # falls back to the editable form
