"""Acceptance tests for the Calendar page's "Timetable" sub-view
(`routers/calendar.py::timetable_view`, `GET /calendar/timetable`): the
global Week (planning) surface (1.7, routers/week.py::week_view) folded into
the main Calendar page. A real week grid with the same mouse actions as
week_view (ordinary events draggable, drag-to-create on empty space) PLUS the
/ week scheduling affordances -- the "Unscheduled work" sidebar that drags
onto the grid to create a work allocation, and every scheduled work-allocation
block rendered prominently with its own move/resize/delete (block only). The
create/move/delete allocation endpoints mirror routers/week.py's trio but
redirect back to /calendar/timetable. Same direct-router-call convention as
test_week_planning.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router

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
            "path": "/calendar/timetable",
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


class TestTimetableViewRoute:
    def test_renders_grid_and_unscheduled_panel(self, conn):
        body = calendar_router.timetable_view(_request(), conn=conn).body.decode()
        assert "Unscheduled work" in body
        assert "project-calendar-col" in body
        assert "calendar-create-col" not in body

    def test_open_task_with_no_allocation_is_unscheduled(self, conn):
        _task(conn, "t1", title="Research")
        body = calendar_router.timetable_view(_request(), conn=conn).body.decode()
        assert "Research" in body

    def test_task_with_allocation_drops_off_unscheduled_list(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        body = calendar_router.timetable_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "unscheduled-task-item" not in body

    def test_task_with_undated_session_stays_on_unscheduled_panel(self, conn):
        """A session added from the task modal's Work sessions "+" button has
        no date yet -- the task is still unscheduled work and must remain in
        the drag-source panel until the session is placed onto a slot."""
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")
        body = calendar_router.timetable_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "unscheduled-task-item" in body
        assert "Research" in body

    def test_completed_task_never_appears_unscheduled(self, conn):
        _task(conn, "t1", title="Done thing", status="done")
        body = calendar_router.timetable_view(_request(), conn=conn).body.decode()
        assert "Done thing" not in body

    def test_unscheduled_task_shows_its_project_label(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        body = calendar_router.timetable_view(_request(), conn=conn).body.decode()
        assert "Conference XYZ &gt; Research" in body or "Conference XYZ > Research" in body

    def test_work_allocation_renders_prominent_and_owned_by_project_calendar_js(self, conn):
        """A scheduled block is a .work-allocation (project_calendar.js's
        form-POST move/resize/delete) that shares .time-event styling -- but
        calendar.js must not double-own it (it uses
        `.time-event:not(.work-allocation)`)."""
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        body = calendar_router.timetable_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "work-allocation" in body
        assert "/calendar/timetable/allocations" in body

    def test_scheduled_block_links_to_its_task_view(self, conn):
        """A scheduled work block is one target for the task it belongs to:
        its title links to the task's edit view (where more work sessions
        can be added), the block carries the task uid as data-task-uid so a
        click anywhere on the block body reaches the same view
        (project_calendar.js interaction 4, taskEditUrlBase config), and the
        delete form still targets the allocation endpoint."""
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        body = calendar_router.timetable_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert 'data-task-uid="t1"' in body
        assert 'href="/tasks/t1/edit"' in body
        assert 'taskEditUrlBase: "/tasks/"' in body
        assert "/calendar/timetable/allocations/" in body

    def test_ordinary_event_renders_as_subdued_context_like_week(self, conn):
        """The Timetable is the Week (planning) surface -- same as
        week_planning.html, ordinary events render as subdued .context-event
        blocks (the scheduling grid's context), not draggable calendar
        events; only work allocations are prominent/draggable."""
        db.upsert_event(
            conn,
            {
                "uid": "e-plain", "title": "Ordinary meeting", "description": "",
                "start_at": f"{_MONDAY}T12:00:00", "end_at": f"{_MONDAY}T13:00:00",
                "all_day": False, "status": "active", "tags": [],
                "created_at": _now(), "updated_at": _now(),
            },
        )
        body = calendar_router.timetable_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "context-event" in body
        assert "Ordinary meeting" in body

    def test_label_filter_applies_to_events(self, conn):
        db.upsert_event(
            conn,
            {
                "uid": "e-a", "title": "Blue meeting", "description": "",
                "start_at": f"{_MONDAY}T12:00:00", "end_at": f"{_MONDAY}T13:00:00",
                "all_day": False, "status": "active", "tags": ["work"],
                "created_at": _now(), "updated_at": _now(),
            },
        )
        db.upsert_event(
            conn,
            {
                "uid": "e-b", "title": "Personal thing", "description": "",
                "start_at": f"{_MONDAY}T14:00:00", "end_at": f"{_MONDAY}T15:00:00",
                "all_day": False, "status": "active", "tags": ["personal"],
                "created_at": _now(), "updated_at": _now(),
            },
        )
        body = calendar_router.timetable_view(
            _request(query_string=f"date_={_MONDAY}&label=work".encode()), date_=_MONDAY, label="work", conn=conn
        ).body.decode()
        assert "Blue meeting" in body
        assert "Personal thing" not in body


class TestCreateTimetableAllocation:
    def test_dragging_any_open_task_creates_an_allocation(self, conn):
        _task(conn, "t1", title="Research")
        resp = calendar_router.create_timetable_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T18:00:00", date_=_MONDAY, conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/calendar/timetable?date_={_MONDAY}"
        assert len(db.list_work_allocations_for_task(conn, "t1")) == 1

    def test_no_project_membership_check(self, conn):
        _project(conn, "Some Project")
        _task(conn, "t1", title="Unaffiliated task")
        calendar_router.create_timetable_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T18:00:00", date_=_MONDAY, conn=conn
        )
        assert len(db.list_work_allocations_for_task(conn, "t1")) == 1

    def test_completed_task_is_rejected(self, conn):
        _task(conn, "t1", title="Done", status="done")
        calendar_router.create_timetable_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T18:00:00", date_=_MONDAY, conn=conn
        )
        assert db.list_work_allocations_for_task(conn, "t1") == []

    def test_dragging_task_with_undated_session_places_that_session(self, conn):
        """Dragging a task that has an undated session placeholder places
        THAT session onto the dropped slot instead of creating yet another
        block -- so repeated "+" sessions each get placed by a drag, not
        multiplied."""
        _task(conn, "t1", title="Research")
        undated_uid = db.create_work_allocation(conn, "t1")
        calendar_router.create_timetable_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T18:00:00", date_=_MONDAY, conn=conn
        )
        allocations = db.list_work_allocations_for_task(conn, "t1")
        assert len(allocations) == 1
        assert allocations[0]["uid"] == undated_uid
        assert allocations[0]["start_at"] == f"{_MONDAY}T16:00:00"
        assert allocations[0]["end_at"] == f"{_MONDAY}T18:00:00"


class TestMoveTimetableAllocation:
    def test_move_changes_start_and_end(self, conn):
        _task(conn, "t1", title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        tuesday = (datetime.fromisoformat(_MONDAY) + timedelta(days=1)).date().isoformat()
        resp = calendar_router.move_timetable_allocation(
            event_uid, start_at=f"{tuesday}T09:00:00", end_at=f"{tuesday}T11:30:00", date_=_MONDAY, conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/calendar/timetable?date_={_MONDAY}"
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
        calendar_router.move_timetable_allocation(
            "e-plain", start_at=f"{_MONDAY}T14:00:00", end_at=f"{_MONDAY}T15:00:00", date_=_MONDAY, conn=conn
        )
        event = db.get_event(conn, "e-plain")
        assert event["start_at"] == f"{_MONDAY}T12:00:00"


class TestDeleteTimetableAllocation:
    def test_delete_removes_only_the_block_not_the_task(self, conn):
        _task(conn, "t1", title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        resp = calendar_router.delete_timetable_allocation(event_uid, date_=_MONDAY, conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/calendar/timetable?date_={_MONDAY}"
        assert db.get_event(conn, event_uid) is None
        assert db.get_task(conn, "t1") is not None