"""A slow Radicale sync must not hold up app startup (the deploy health check
waits for the port, which only opens once the lifespan has started)."""

from __future__ import annotations

import time

from starlette.testclient import TestClient

from src import main, sync


class _Bridge:
    def __init__(self, settings):
        pass


def test_startup_finishes_while_the_first_sync_is_still_running(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "c.sqlite"))
    monkeypatch.setenv("CC_BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setenv("CC_SKIP_AUTH", "1")
    monkeypatch.setattr(main, "CalDavBridge", _Bridge)
    monkeypatch.setattr(sync, "full_refresh", lambda bridge, conn: time.sleep(5))

    started = time.monotonic()
    with TestClient(main.create_app()):
        assert time.monotonic() - started < 4
