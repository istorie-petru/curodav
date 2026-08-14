"""1.7 slice 2 acceptance tests (plans/open-priority.md § Information
architecture & view surfaces' "Week -- planning" bullet) -- `GET /week`
(`routers/week.py::week_view`): the cross-project scheduling surface.
Unscheduled work (any open task with no allocation, across every project or
none) draggable onto a real week grid; create/move/delete allocation
endpoints mirror routers/projects.py's own trio but without the "must
belong to this project" scoping. Same direct-router-call convention as
test_project_calendar.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import week as week_router

_MONDAY = "2026-08-17"  # a real Monday


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(query_string=b""):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/week",
            "query_string": query_string,
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _task(conn, uid, tags=None, status="active", **overrides):
    row = {
        "uid": uid, "title": uid, "description": "", "status": status,
        "tags": tags or [], "created_at": _now(),
    }
    row.update(overrides)
    db.upsert_task(conn, row)
    return db.get_task(conn, uid)


def _project(conn, name):
    db.upsert_label_config(
        conn, {"name": name, "is_project": 1, "start_date": "2026-08-01", "end_date": "2026-09-01", "created_at": _now()}
    )


class TestWeekPlanningRoute:
    def test_renders_grid_and_unscheduled_panel(self, conn):
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert "Unscheduled work" in body

    def test_open_task_with_no_allocation_is_unscheduled(self, conn):
        _task(conn, "t1", title="Research")
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert "Research" in body

    def test_task_with_allocation_drops_off_unscheduled_list(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        body = week_router.week_view(_request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn).body.decode()
        # "Research" legitimately appears once, as the work-allocation
        # block's own title on the grid -- it must NOT also appear in the
        # "Unscheduled work" list (unscheduled-task-item), which is what
        # this test actually checks.
        assert "unscheduled-task-item" not in body

    def test_completed_task_never_appears_unscheduled(self, conn):
        _task(conn, "t1", title="Done thing", status="done")
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert "Done thing" not in body

    def test_unscheduled_task_shows_its_project_label(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert "Conference XYZ &gt; Research" in body or "Conference XYZ > Research" in body

    def test_task_with_no_project_shows_without_a_prefix(self, conn):
        _task(conn, "t1", title="Standalone task")
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert "Standalone task" in body
        assert "&gt; Standalone task" not in body

    def test_two_projects_allocations_both_render_prominently(self, conn):
        """Unlike routers/projects.py::project_calendar (which only
        prominents ONE project's own allocations), every work allocation is
        prominent here regardless of which task/project it belongs to."""
        _project(conn, "Conference XYZ")
        _project(conn, "Other Project")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        _task(conn, "t2", tags=["Other Project"], title="Other work")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T09:00:00", f"{_MONDAY}T10:00:00")
        db.create_work_allocation(conn, "t2", f"{_MONDAY}T11:00:00", f"{_MONDAY}T12:00:00")
        body = week_router.week_view(_request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn).body.decode()
        assert "Research" in body
        assert "Other work" in body
        assert body.count("work-allocation") >= 2

    def test_ordinary_event_renders_as_subdued_context(self, conn):
        db.upsert_event(
            conn,
            {
                "uid": "e-plain", "title": "Ordinary meeting", "description": "",
                "start_at": f"{_MONDAY}T12:00:00", "end_at": f"{_MONDAY}T13:00:00",
                "all_day": False, "status": "active", "tags": [],
                "created_at": _now(), "updated_at": _now(),
            },
        )
        body = week_router.week_view(_request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn).body.decode()
        assert "context-event" in body
        assert "Ordinary meeting" in body

    def test_due_task_shows_as_a_chip_on_its_day(self, conn):
        _task(conn, "t1", title="Deadline task", due_at=f"{_MONDAY}T00:00:00")
        body = week_router.week_view(_request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn).body.decode()
        assert "Deadline task" in body


class TestCreateAllocation:
    def test_dragging_any_open_task_creates_an_allocation(self, conn):
        _task(conn, "t1", title="Research")
        resp = week_router.create_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T18:00:00", date_=_MONDAY, conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/week?date_={_MONDAY}"
        allocations = db.list_work_allocations_for_task(conn, "t1")
        assert len(allocations) == 1

    def test_no_project_membership_check_unlike_project_calendar(self, conn):
        """The whole point of this global page: a task doesn't need to
        belong to any particular project to be scheduled here."""
        _project(conn, "Some Project")
        _task(conn, "t1", title="Unaffiliated task")  # no tags at all
        week_router.create_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T18:00:00", date_=_MONDAY, conn=conn
        )
        assert len(db.list_work_allocations_for_task(conn, "t1")) == 1

    def test_completed_task_is_rejected(self, conn):
        _task(conn, "t1", title="Done", status="done")
        week_router.create_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T18:00:00", date_=_MONDAY, conn=conn
        )
        assert db.list_work_allocations_for_task(conn, "t1") == []

    def test_end_before_start_is_rejected(self, conn):
        _task(conn, "t1", title="Research")
        week_router.create_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T18:00:00", end_at=f"{_MONDAY}T16:00:00", date_=_MONDAY, conn=conn
        )
        assert db.list_work_allocations_for_task(conn, "t1") == []


class TestMoveAllocation:
    def test_move_changes_start_and_end(self, conn):
        _task(conn, "t1", title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        tuesday = (datetime.fromisoformat(_MONDAY) + timedelta(days=1)).date().isoformat()
        resp = week_router.move_allocation(
            event_uid, start_at=f"{tuesday}T09:00:00", end_at=f"{tuesday}T11:30:00", date_=_MONDAY, conn=conn
        )
        assert resp.status_code == 303
        event = db.get_event(conn, event_uid)
        assert event["start_at"] == f"{tuesday}T09:00:00"
        assert event["end_at"] == f"{tuesday}T11:30:00"

    def test_moving_a_non_allocation_event_is_rejected(self, conn):
        db.upsert_event(
            conn,
            {
                "uid": "e-plain", "title": "Ordinary meeting", "description": "",
                "start_at": f"{_MONDAY}T12:00:00", "end_at": f"{_MONDAY}T13:00:00",
                "all_day": False, "status": "active", "tags": [],
                "created_at": _now(), "updated_at": _now(),
            },
        )
        week_router.move_allocation(
            "e-plain", start_at=f"{_MONDAY}T14:00:00", end_at=f"{_MONDAY}T15:00:00", date_=_MONDAY, conn=conn
        )
        event = db.get_event(conn, "e-plain")
        assert event["start_at"] == f"{_MONDAY}T12:00:00"


class TestDeleteAllocation:
    def test_delete_removes_only_the_block_not_the_task(self, conn):
        _task(conn, "t1", title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        resp = week_router.delete_allocation(event_uid, date_=_MONDAY, conn=conn)
        assert resp.status_code == 303
        assert db.get_event(conn, event_uid) is None
        assert db.get_task(conn, "t1") is not None
