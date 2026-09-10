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
