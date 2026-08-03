"""Tests for routers/tasks.py's Inbox view (spaces-home-pipeline,
2026-08-02): GET /tasks/inbox is a filtered view, not new storage -- a
task is "in the Inbox" iff its list_path resolves to a task_lists row
with no project_uid. No bridge/Radicale dependency for read-only listing;
the "move to a project-linked list" triage step reuses the existing bulk
move_list action (routers/tasks.py's bulk_action), same pattern as
test_tasks_view_rework.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task_list(conn, uid, name, project_uid=None):
    db.upsert_task_list(conn, {"uid": uid, "name": name, "color": "blue", "created_at": _now()})
    if project_uid:
        db.set_task_list_project(conn, uid, project_uid)


def _seed_task(conn, uid, list_path, status="active"):
    db.upsert_task(conn, {
        "uid": uid, "href": f"/{uid}", "calendar_path": "tasks", "list_path": list_path,
        "title": uid, "description": "", "status": status, "tags": [], "created_at": _now(),
    })


def _request():
    return Request({"type": "http", "method": "GET", "path": "/tasks/inbox", "headers": []})


class TestInboxView:
    def test_only_shows_tasks_from_unassigned_lists(self, conn):
        db.upsert_project(conn, {"uid": "p1", "name": "Uni", "created_at": _now(), "updated_at": _now()})
        _seed_task_list(conn, "hw", "Homework", project_uid="p1")
        _seed_task_list(conn, "misc", "Misc")  # no project -- unassigned

        _seed_task(conn, "assigned", "hw")
        _seed_task(conn, "unassigned", "misc")

        resp = tasks_router.inbox_tasks(_request(), conn=conn)
        open_uids = {t["uid"] for t in resp.context["open_tasks"]}
        assert open_uids == {"unassigned"}

    def test_default_list_with_no_project_counts_as_inbox(self, conn):
        # The default task list (db.DEFAULT_TASK_LIST_UID, 'tasks') is what
        # a Home Quick Capture with no list_path lands in -- see Step 4.
        # No project_uid set on it here, same as a brand-new install.
        _seed_task_list(conn, db.DEFAULT_TASK_LIST_UID, "Tasks")
        _seed_task(conn, "captured", db.DEFAULT_TASK_LIST_UID)

        resp = tasks_router.inbox_tasks(_request(), conn=conn)
        assert {t["uid"] for t in resp.context["open_tasks"]} == {"captured"}

    def test_empty_when_every_list_is_project_linked(self, conn):
        db.upsert_project(conn, {"uid": "p1", "name": "Uni", "created_at": _now(), "updated_at": _now()})
        _seed_task_list(conn, "hw", "Homework", project_uid="p1")
        _seed_task(conn, "assigned", "hw")

        resp = tasks_router.inbox_tasks(_request(), conn=conn)
        assert resp.context["open_tasks"] == []

    def test_moving_to_a_project_linked_list_removes_it_from_inbox(self, conn):
        import asyncio

        class FakeRequestBody:
            def __init__(self, payload):
                self._payload = payload

            async def json(self):
                return self._payload

        db.upsert_project(conn, {"uid": "p1", "name": "Uni", "created_at": _now(), "updated_at": _now()})
        _seed_task_list(conn, "hw", "Homework", project_uid="p1")
        _seed_task_list(conn, "misc", "Misc")
        _seed_task(conn, "t1", "misc")

        # Confirm it starts in the Inbox.
        resp = tasks_router.inbox_tasks(_request(), conn=conn)
        assert {t["uid"] for t in resp.context["open_tasks"]} == {"t1"}

        # Triage via the existing bulk "Move to list" action (tasks_list.html's
        # #bulk-list-select) -- no new mechanism per the plan doc.
        class FakeBridge:
            def save_task_row(self, row):
                return dict(row)

            def delete_task(self, uid, list_path):
                pass

        payload = FakeRequestBody({"action": "move_list", "uids": ["t1"], "list_path": "hw"})
        asyncio.run(tasks_router.bulk_action(payload, bridge=FakeBridge(), conn=conn))

        resp = tasks_router.inbox_tasks(_request(), conn=conn)
        assert resp.context["open_tasks"] == []
        assert db.get_task(conn, "t1")["list_path"] == "hw"
