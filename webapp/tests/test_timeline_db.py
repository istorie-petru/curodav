"""Data-layer tests for Timeline (Phase 11) storage: tasks.timeline_lane,
plus the write-through-safety property (an ordinary task edit must not
clobber it).

Phase 1 (label-space rework, 2026-08-06) dropped `task_lists` (and with
it `timeline_row_names_json`/`set_task_list_row_name`) -- there's no more
per-list swimlane block to carry a custom row-name map (see db.py's
Phase 1 comments and routers/timeline.py's `_build_context` comment).
`TestTimelineRowNames` below is gone with that table; `TestTimelineLane`
survives unchanged in spirit."""

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
            "uid": "t1", "title": "X",
            "description": "", "status": "active", "tags": [], "created_at": _now(),
        })
        db.set_task_timeline_lane(conn, "t1", 3)
        assert db.get_task(conn, "t1")["timeline_lane"] == 3

    def test_clear_with_none(self, conn):
        db.upsert_task(conn, {
            "uid": "t1", "title": "X",
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
            "uid": "t1", "title": "X",
            "description": "", "status": "active", "tags": [], "created_at": _now(),
        })
        db.set_task_timeline_lane(conn, "t1", 2)
        existing = db.get_task(conn, "t1")
        row = dict(existing)
        row["title"] = "Renamed"
        db.upsert_task(conn, row)
        assert db.get_task(conn, "t1")["timeline_lane"] == 2
        assert db.get_task(conn, "t1")["title"] == "Renamed"
