"""Data-layer tests for Timeline (Phase 11) storage: tasks.timeline_lane
and task_lists.timeline_row_names_json, plus the write-through-safety
properties (ordinary task/list edits must not clobber either)."""

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


class TestTimelineLane:
    def test_set_and_read_back(self, conn):
        db.upsert_task(conn, {
            "uid": "t1", "href": "/t1", "calendar_path": "tasks", "title": "X",
            "description": "", "status": "active", "tags": [], "created_at": _now(),
        })
        db.set_task_timeline_lane(conn, "t1", 3)
        assert db.get_task(conn, "t1")["timeline_lane"] == 3

    def test_clear_with_none(self, conn):
        db.upsert_task(conn, {
            "uid": "t1", "href": "/t1", "calendar_path": "tasks", "title": "X",
            "description": "", "status": "active", "tags": [], "created_at": _now(),
        })
        db.set_task_timeline_lane(conn, "t1", 2)
        db.set_task_timeline_lane(conn, "t1", None)
        assert db.get_task(conn, "t1")["timeline_lane"] is None

    def test_ordinary_task_edit_preserves_lane(self, conn):
        """The write-through-safety property: upsert_task deliberately
        excludes timeline_lane from its column set, so an ordinary edit
        (built from dict(existing), same pattern every router/tasks.py
        write uses) can never clobber it -- this simulates that pattern
        directly rather than going through the router."""
        db.upsert_task(conn, {
            "uid": "t1", "href": "/t1", "calendar_path": "tasks", "title": "X",
            "description": "", "status": "active", "tags": [], "created_at": _now(),
        })
        db.set_task_timeline_lane(conn, "t1", 2)
        existing = db.get_task(conn, "t1")
        row = dict(existing)
        row["title"] = "Renamed"
        db.upsert_task(conn, row)
        assert db.get_task(conn, "t1")["timeline_lane"] == 2
        assert db.get_task(conn, "t1")["title"] == "Renamed"


class TestTimelineRowNames:
    def test_set_and_read_back(self, conn):
        db.ensure_default_task_list(conn)
        db.set_task_list_row_name(conn, db.DEFAULT_TASK_LIST_UID, 1, "Assignments")
        tl = db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)
        assert tl["timeline_row_names"] == {"1": "Assignments"}

    def test_clear_with_empty_string(self, conn):
        db.ensure_default_task_list(conn)
        db.set_task_list_row_name(conn, db.DEFAULT_TASK_LIST_UID, 1, "Assignments")
        db.set_task_list_row_name(conn, db.DEFAULT_TASK_LIST_UID, 1, "")
        tl = db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)
        assert tl["timeline_row_names"] == {}

    def test_row_zero_overridable_too(self, conn):
        """Desktop: 'this now includes row 0 -- the project's own display
        name in this gutter can now be overridden independently of the
        project's actual title.' Same here for the list's own name."""
        db.ensure_default_task_list(conn)
        db.set_task_list_row_name(conn, db.DEFAULT_TASK_LIST_UID, 0, "Custom Display Name")
        tl = db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)
        assert tl["timeline_row_names"]["0"] == "Custom Display Name"

    def test_ordinary_list_rename_preserves_row_names(self, conn):
        db.ensure_default_task_list(conn)
        db.set_task_list_row_name(conn, db.DEFAULT_TASK_LIST_UID, 1, "Assignments")
        db.upsert_task_list(conn, {"uid": db.DEFAULT_TASK_LIST_UID, "name": "Renamed", "color": "green"})
        tl = db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)
        assert tl["name"] == "Renamed"
        assert tl["timeline_row_names"] == {"1": "Assignments"}

    def test_missing_list_is_a_noop(self, conn):
        db.set_task_list_row_name(conn, "does-not-exist", 0, "X")  # must not raise
