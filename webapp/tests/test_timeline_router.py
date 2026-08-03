"""Tests for routers/timeline.py: context-building (_build_context wiring
timeline_layout.py's output into template-ready pixel geometry), and the
four endpoints the drag interactions (static/timeline.js) call --
reschedule, manual lane, click-create, and gutter-row rename."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db
from src.routers import timeline as timeline_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FakeBridge:
    def save_task_row(self, row):
        row = dict(row)
        row.setdefault("href", f"/{row['uid']}")
        row.setdefault("calendar_path", "tasks")
        return row


@pytest.fixture()
def bridge():
    return FakeBridge()


def _seed_task(conn, uid, list_path="tasks", start_at=None, due_at="2026-08-10", status="active"):
    db.upsert_task(conn, {
        "uid": uid, "href": f"/{uid}", "calendar_path": "tasks", "list_path": list_path,
        "title": uid, "description": "", "status": status, "start_at": start_at, "due_at": due_at,
        "tags": [], "created_at": _now(),
    })


class TestBuildContext:
    def test_empty_still_renders(self, conn):
        ctx = timeline_router._build_context(conn)
        assert ctx["bars"] == []
        assert ctx["total_days"] >= 14

    def test_tasks_without_due_date_excluded(self, conn):
        db.upsert_task(conn, {
            "uid": "t1", "href": "/t1", "calendar_path": "tasks", "title": "No due date",
            "description": "", "status": "active", "tags": [], "created_at": _now(),
        })
        ctx = timeline_router._build_context(conn)
        assert ctx["bars"] == []

    def test_archived_tasks_excluded(self, conn):
        _seed_task(conn, "t1", status="archived")
        ctx = timeline_router._build_context(conn)
        assert ctx["bars"] == []

    def test_done_tasks_included(self, conn):
        """Unlike the Table view (Phase 9), the timeline doesn't hide
        completed work -- a Gantt chart showing a project's history is
        more useful with what's already done still visible."""
        _seed_task(conn, "t1", status="done")
        ctx = timeline_router._build_context(conn)
        assert len(ctx["bars"]) == 1

    def test_bar_carries_own_local_idx_and_group_lanes(self, conn):
        _seed_task(conn, "t1")
        ctx = timeline_router._build_context(conn)
        bar = ctx["bars"][0]
        assert bar["local_idx"] == 0
        assert bar["group_lanes"] >= 1
        assert bar["list_path"] == "tasks"

    def test_multiple_lists_produce_separate_swimlane_blocks(self, conn):
        db.upsert_task_list(conn, {"uid": "hw", "name": "Homework", "color": "blue", "created_at": _now()})
        _seed_task(conn, "t1", list_path="hw")
        _seed_task(conn, "t2", list_path="tasks")
        ctx = timeline_router._build_context(conn)
        rows_by_list = {}
        for row in ctx["rows"]:
            rows_by_list.setdefault(row["list_uid"], []).append(row["global_row"])
        assert set(rows_by_list["hw"]).isdisjoint(set(rows_by_list["tasks"]))

    def test_row_label_uses_custom_name_when_set(self, conn):
        db.ensure_default_task_list(conn)
        db.set_task_list_row_name(conn, db.DEFAULT_TASK_LIST_UID, 0, "My Custom List Name")
        _seed_task(conn, "t1")
        ctx = timeline_router._build_context(conn)
        header_row = next(r for r in ctx["rows"] if r["list_uid"] == db.DEFAULT_TASK_LIST_UID and r["is_header"])
        assert header_row["label"] == "My Custom List Name"


class TestTimelineViewRoute:
    def test_renders(self, conn):
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/tasks/timeline", "headers": []})
        resp = timeline_router.timeline_view(req, conn=conn)
        assert resp.status_code == 200


class TestReschedule:
    def test_move_updates_both_dates(self, conn, bridge):
        import asyncio
        from starlette.requests import Request

        _seed_task(conn, "t1", start_at="2026-08-01", due_at="2026-08-03")

        async def _call():
            req = Request({"type": "http", "method": "POST", "path": "/x", "headers": [(b"content-type", b"application/json")]})

            async def receive():
                import json as _json
                body = _json.dumps({"start_at": "2026-08-05", "due_at": "2026-08-07"}).encode()
                return {"type": "http.request", "body": body, "more_body": False}

            req._receive = receive
            return await timeline_router.timeline_reschedule("t1", req, bridge=bridge, conn=conn)

        resp = asyncio.run(_call())
        assert resp.status_code == 200
        task = db.get_task(conn, "t1")
        assert task["start_at"] == "2026-08-05"
        assert task["due_at"] == "2026-08-07"

    def test_missing_task_returns_404(self, conn, bridge):
        import asyncio
        from starlette.requests import Request

        async def _call():
            req = Request({"type": "http", "method": "POST", "path": "/x", "headers": [(b"content-type", b"application/json")]})

            async def receive():
                import json as _json
                body = _json.dumps({"start_at": "2026-08-05", "due_at": "2026-08-07"}).encode()
                return {"type": "http.request", "body": body, "more_body": False}

            req._receive = receive
            return await timeline_router.timeline_reschedule("does-not-exist", req, bridge=bridge, conn=conn)

        resp = asyncio.run(_call())
        assert resp.status_code == 404


def _json_request(payload: dict):
    from starlette.requests import Request
    import json as _json

    req = Request({"type": "http", "method": "POST", "path": "/x", "headers": [(b"content-type", b"application/json")]})

    async def receive():
        return {"type": "http.request", "body": _json.dumps(payload).encode(), "more_body": False}

    req._receive = receive
    return req


class TestSetLane:
    def test_sets_and_clears(self, conn):
        import asyncio

        _seed_task(conn, "t1")
        asyncio.run(timeline_router.timeline_set_lane("t1", _json_request({"lane": 2}), conn=conn))
        assert db.get_task(conn, "t1")["timeline_lane"] == 2
        asyncio.run(timeline_router.timeline_set_lane("t1", _json_request({"lane": None}), conn=conn))
        assert db.get_task(conn, "t1")["timeline_lane"] is None


class TestCreate:
    def test_creates_task_with_lane(self, conn, bridge):
        import asyncio

        db.ensure_default_task_list(conn)
        resp = asyncio.run(
            timeline_router.timeline_create(
                _json_request({"list_path": db.DEFAULT_TASK_LIST_UID, "start_at": "2026-08-10", "due_at": "2026-08-12", "local_idx": 2}),
                bridge=bridge, conn=conn,
            )
        )
        assert resp.status_code == 200
        tasks = db.list_tasks(conn)
        assert len(tasks) == 1
        assert tasks[0]["start_at"] == "2026-08-10"
        assert tasks[0]["due_at"] == "2026-08-12"
        assert tasks[0]["timeline_lane"] == 2
        assert tasks[0]["title"] == "New task"


class TestRowName:
    def test_sets_row_name(self, conn):
        import asyncio

        db.ensure_default_task_list(conn)
        asyncio.run(
            timeline_router.timeline_row_name(
                db.DEFAULT_TASK_LIST_UID, _json_request({"local_idx": 1, "name": "Assignments"}), conn=conn
            )
        )
        tl = db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)
        assert tl["timeline_row_names"] == {"1": "Assignments"}

    def test_empty_name_clears(self, conn):
        import asyncio

        db.ensure_default_task_list(conn)
        db.set_task_list_row_name(conn, db.DEFAULT_TASK_LIST_UID, 1, "Assignments")
        asyncio.run(
            timeline_router.timeline_row_name(
                db.DEFAULT_TASK_LIST_UID, _json_request({"local_idx": 1, "name": ""}), conn=conn
            )
        )
        tl = db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)
        assert tl["timeline_row_names"] == {}
