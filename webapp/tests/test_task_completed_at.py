"""tasks.completed_at (2026-08-07, plans/widget-consolidation-design.md's
Streak widget) -- the one thing this table couldn't answer before: which
day a plain (non-recurring) task was completed. Auto-managed by
db.upsert_task based on the done/not-done status transition; a JSON
backup restore overrides it with the real historical value instead (see
routers/export.py's _restore)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_task(conn, uid, status="active", **overrides):
    row = {
        "uid": uid, "title": uid, "description": "", "status": status,
        "created_at": _now(), "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_task(conn, row)
    return uid


class TestCompletedAtTransitions:
    def test_creating_an_active_task_leaves_completed_at_unset(self, conn):
        _make_task(conn, "t1", status="active")
        assert db.get_task(conn, "t1")["completed_at"] is None

    def test_transitioning_to_done_sets_completed_at(self, conn):
        _make_task(conn, "t1", status="active")
        existing = db.get_task(conn, "t1")
        row = dict(existing)
        row["status"] = "done"
        db.upsert_task(conn, row)
        assert db.get_task(conn, "t1")["completed_at"] is not None

    def test_transitioning_to_archived_also_sets_completed_at(self, conn):
        _make_task(conn, "t1", status="active")
        row = dict(db.get_task(conn, "t1"))
        row["status"] = "archived"
        db.upsert_task(conn, row)
        assert db.get_task(conn, "t1")["completed_at"] is not None

    def test_uncompleting_a_task_clears_completed_at(self, conn):
        _make_task(conn, "t1", status="active")
        row = dict(db.get_task(conn, "t1"))
        row["status"] = "done"
        db.upsert_task(conn, row)
        assert db.get_task(conn, "t1")["completed_at"] is not None

        row = dict(db.get_task(conn, "t1"))
        row["status"] = "active"
        db.upsert_task(conn, row)
        assert db.get_task(conn, "t1")["completed_at"] is None

    def test_editing_an_already_done_task_does_not_restamp_completed_at(self, conn):
        _make_task(conn, "t1", status="active")
        row = dict(db.get_task(conn, "t1"))
        row["status"] = "done"
        db.upsert_task(conn, row)
        first_stamp = db.get_task(conn, "t1")["completed_at"]

        # Edit something unrelated while status stays "done".
        row = dict(db.get_task(conn, "t1"))
        row["title"] = "Renamed"
        row["status"] = "done"
        db.upsert_task(conn, row)
        assert db.get_task(conn, "t1")["completed_at"] == first_stamp

    def test_creating_a_task_already_done_sets_completed_at_immediately(self, conn):
        # A brand-new task created directly as done/archived (no prior
        # "active" state to transition from) still gets a completed_at --
        # not just tasks that visibly flip status after already existing.
        _make_task(conn, "t1", status="done")
        assert db.get_task(conn, "t1")["completed_at"] is not None


class TestCompletedAtRestore:
    def test_restore_preserves_the_backups_historical_completed_at(self, conn):
        from src.routers import export as export_router

        historical = "2026-01-15T10:00:00+00:00"
        payload = {
            "tasks": [
                {
                    "uid": "t1", "title": "Old completed task", "description": "",
                    "status": "done", "completed_at": historical,
                    "created_at": "2026-01-01T00:00:00+00:00", "updated_at": historical,
                }
            ]
        }
        export_router._restore(conn, payload)
        assert db.get_task(conn, "t1")["completed_at"] == historical
