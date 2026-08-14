"""Integration test: spins up a real local Radicale instance (not a mock)
and exercises CalDavBridge + sync.full_refresh + db.py against it end to
end. This is the test that actually matters for this app -- the pure unit
tests in test_row_translators.py catch translation bugs, but the real risk
in this codebase is protocol/library-integration mistakes (wrong method
names, wrong URL joining, etc.), which only a live server can catch. This
exact approach (manually spinning up Radicale) is what caught two real
bugs during development: a URL-doubling bug in the hand-rolled CardDAV
client, and a stale-reference bug from using the wrong `caldav` library
listing method.

Requires the `radicale` package (dev dependency). Skipped automatically if
it isn't installed.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

radicale = pytest.importorskip("radicale")

from src import db, sync  # noqa: E402
from src.caldav_bridge import CalDavBridge  # noqa: E402
from src.config import Settings  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"Radicale did not start listening on port {port} in time")


@pytest.fixture
def radicale_settings(tmp_path: Path) -> Settings:
    port = _free_port()
    storage = tmp_path / "collections"
    storage.mkdir()
    htpasswd = tmp_path / "users"
    htpasswd.write_text("testuser:testpass\n", encoding="utf-8")

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "radicale",
            f"--server-hosts=127.0.0.1:{port}",
            "--auth-type=htpasswd",
            f"--auth-htpasswd_filename={htpasswd}",
            "--auth-htpasswd_encryption=plain",
            f"--storage-filesystem_folder={storage}",
            "--rights-type=owner_only",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_port(port)
        yield Settings(
            radicale_base_url=f"http://127.0.0.1:{port}/testuser/",
            radicale_username="testuser",
            radicale_password="testpass",
            calendar_collection="calendar",
            tasks_collection="tasks",
            contacts_collection="contacts",
            db_path=tmp_path / "cache.sqlite",
            sync_interval_seconds=9999,
            backup_dir=tmp_path / "backups",
        )
    finally:
        proc.terminate()
        proc.wait(timeout=5)


class TestCalDavBridgeLive:
    def test_event_crud(self, radicale_settings: Settings):
        bridge = CalDavBridge(radicale_settings)
        row = {
            "uid": "event-1",
            "title": "Team standup",
            "start_at": "2026-08-05T09:00:00",
            "end_at": "2026-08-05T09:30:00",
            "status": "active",
            "tags": ["work"],
        }
        bridge.save_event_row(row)
        listed = bridge.list_event_rows("calendar")
        assert len(listed) == 1
        assert listed[0]["title"] == "Team standup"

        row["title"] = "Team standup (renamed)"
        bridge.save_event_row(row)
        listed = bridge.list_event_rows("calendar")
        assert listed[0]["title"] == "Team standup (renamed)"

        bridge.delete_event("event-1", "calendar")
        assert bridge.list_event_rows("calendar") == []

    def test_save_event_row_recovers_when_lookup_wrongly_says_not_found(
        self, radicale_settings: Settings
    ):
        """Regression test for a real crash: `event_by_uid` said
        NotFoundError for a UID that actually already existed on the
        server (root cause unconfirmed -- a near-simultaneous duplicate
        save is the most likely explanation, but the fix is correct
        regardless of *why* the lookup was stale), so `save_event_row`
        took the "create" branch and Radicale correctly rejected the PUT
        as a 409 conflict, which propagated up as an unhandled
        `caldav.lib.error.PutError` and crashed the request. Simulates the
        stale lookup directly rather than trying to race two real
        requests against each other, which would be flaky by nature."""
        from unittest.mock import patch

        from caldav.lib.error import NotFoundError

        from src.ical_rows import event_row_to_ical

        bridge = CalDavBridge(radicale_settings)
        row = {"uid": "race-1", "title": "Race", "start_at": "2026-08-05T09:00:00"}

        # Create it directly against the real Calendar object, bypassing
        # our own save_event_row -- this is the "something else already
        # wrote it" half of the race.
        cal = bridge._event_calendar("calendar")
        cal.save_event(ical=event_row_to_ical(row).decode())

        # Now make our own lookup lie exactly once, so save_event_row
        # takes the create path against a UID that's actually taken.
        real_lookup = cal.event_by_uid
        call_count = {"n": 0}

        def flaky_lookup(uid):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise NotFoundError("simulated stale lookup")
            return real_lookup(uid)

        row["title"] = "Race (updated via recovery)"
        with patch.object(cal, "event_by_uid", side_effect=flaky_lookup):
            result = bridge.save_event_row(row)  # must not raise PutError

        assert result["title"] == "Race (updated via recovery)"
        matching = [r for r in bridge.list_event_rows("calendar") if r["uid"] == "race-1"]
        assert len(matching) == 1, "should recover in place, not create a duplicate"

    def test_task_crud(self, radicale_settings: Settings):
        bridge = CalDavBridge(radicale_settings)
        row = {
            "uid": "task-1",
            "title": "Write report",
            "due_at": "2026-08-10",
            "urgency": 2,
            "status": "active",
        }
        bridge.save_task_row(row)
        listed = bridge.list_task_rows("tasks")
        assert len(listed) == 1
        assert listed[0]["title"] == "Write report"

        bridge.delete_task("task-1")
        assert bridge.list_task_rows("tasks") == []

    def test_contact_crud(self, radicale_settings: Settings):
        bridge = CalDavBridge(radicale_settings)
        row = {
            "uid": "person-1",
            "full_name": "Jane Doe",
            "email": "jane@example.com",
        }
        bridge.save_contact_row(row)
        listed = bridge.list_contact_rows("contacts")
        assert len(listed) == 1
        assert listed[0]["full_name"] == "Jane Doe"

        bridge.delete_contact("person-1")
        assert bridge.list_contact_rows("contacts") == []


class TestFullRefreshSync:
    def test_full_refresh_is_a_noop_since_the_base_pool_is_plain_sql(self, radicale_settings: Settings):
        """Phase 1 (label-space rework, 2026-08-06): the base pool
        (tasks/events/contacts) is plain SQL now, no Radicale relationship
        at all (see features/architecture.md §1 and sync.py's own
        module docstring) -- sync.full_refresh no longer mirrors Radicale
        into the cache; it's a deliberate no-op until Phase 6 (published
        Lists) gives it a real body again. Writing straight to Radicale
        via the bridge (still exercised here, for Phase 6's sake) must
        NOT appear in the SQLite cache via a full_refresh call anymore."""
        bridge = CalDavBridge(radicale_settings)
        bridge.save_event_row(
            {"uid": "e1", "title": "Event one", "start_at": "2026-08-05T09:00:00"}
        )

        with db.connect(radicale_settings.db_path) as conn:
            sync.full_refresh(bridge, conn)
            assert db.get_event(conn, "e1") is None
            assert db.list_events(conn) == []
