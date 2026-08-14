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

    def test_unscheduled_task_shows_its_project_pill(self, conn):
        """1.9 one-line card: the project renders as a pill (icon + name)
        before the task title, not a `Project > Task` prefix."""
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        body = calendar_router.timetable_view(_request(), conn=conn).body.decode()
        assert 'class="unscheduled-project-pill"' in body
        assert "Conference XYZ" in body
        assert "&gt; Research" not in body

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
        its title links to the task's view modal (not the edit form), the
        block carries the task uid as data-task-uid so a click anywhere on
        the block body reaches the same view (project_calendar.js
        interaction 4, taskUrlBase config), and the delete form still
        targets the allocation endpoint."""
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        body = calendar_router.timetable_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert 'data-task-uid="t1"' in body
        assert 'href="/tasks/t1"' in body
        assert 'href="/tasks/t1/edit"' not in body
        assert 'taskUrlBase: "/tasks/"' in body
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
    def test_delete_unschedules_the_block_not_the_task(self, conn):
        """"Delete" on a block doesn't delete the session -- it clears its
        start/end back to undated, so the task's session count never drops
        just from unscheduling; the task itself is never deleted either."""
        _task(conn, "t1", title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        resp = calendar_router.delete_timetable_allocation(event_uid, date_=_MONDAY, conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/calendar/timetable?date_={_MONDAY}"
        assert db.get_task(conn, "t1") is not None
        remaining = db.list_work_allocations_for_task(conn, "t1")
        assert [wa["uid"] for wa in remaining] == [event_uid]
        assert remaining[0]["start_at"] is None
        assert remaining[0]["end_at"] is None

    def test_delete_leaves_the_tasks_other_sessions_untouched(self, conn):
        """Went through two earlier same-day (2026-08-14) designs, both
        wrong: first this collapsed ALL of a task's sessions down to one
        undated placeholder on any single unschedule ("the session count
        doesn't hold as a guide"); the fix for that then hard-deleted just
        the one session, which visibly dropped a single-session task's count
        to zero on unschedule. Unscheduling one of three sessions must leave
        the other two exactly as they were AND leave the unscheduled one
        still present, just undated -- the count never changes."""
        _task(conn, "t1", title="Research")
        for day in ("2026-08-17", "2026-08-18", "2026-08-19"):
            db.create_work_allocation(conn, "t1", f"{day}T16:00:00", f"{day}T18:00:00")
        event_uids = [wa["uid"] for wa in db.list_work_allocations_for_task(conn, "t1")]
        calendar_router.delete_timetable_allocation(event_uids[0], date_=_MONDAY, conn=conn)
        remaining = db.list_work_allocations_for_task(conn, "t1")
        assert [wa["uid"] for wa in remaining] == event_uids
        by_uid = {wa["uid"]: wa for wa in remaining}
        assert by_uid[event_uids[0]]["start_at"] is None
        assert by_uid[event_uids[1]]["start_at"] is not None
        assert by_uid[event_uids[2]]["start_at"] is not None


class TestUnscheduledPanelStepper:
    """1.9 "unscheduled work" panel rework on the Timetable view: per-item
    session count with −/+ buttons and a scheduled/total hours readout."""

    def test_item_shows_plus_button_and_count_not_minus_at_one(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")  # one undated session
        body = calendar_router.timetable_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert 'data-task-uid="t1"' in body
        assert "unscheduled-count" in body
        assert "/tasks/t1/work-allocations" in body  # the "+" form action
        assert "/tasks/t1/work-allocations/remove-latest" not in body  # − hidden at count 1

    def test_minus_button_renders_at_more_than_one_session(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")
        db.create_work_allocation(conn, "t1")
        body = calendar_router.timetable_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "/tasks/t1/work-allocations/remove-latest" in body
        assert 'value="/calendar/timetable?date_=' in body  # +/− return here

    def test_card_is_one_line_without_hours(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")
        body = calendar_router.timetable_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "unscheduled-count" in body
        assert "unscheduled-hours" not in body
        assert "unscheduled-grip" not in body
        assert "unscheduled-task-body" not in body

    def test_item_has_no_native_draggable_attribute(self, conn):
        _task(conn, "t1", title="Research")
        body = calendar_router.timetable_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert 'draggable="true"' not in body