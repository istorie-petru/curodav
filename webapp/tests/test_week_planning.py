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

    def test_unscheduled_task_shows_its_project_pill(self, conn):
        """1.9 one-line card: the project renders as a pill (icon + name)
        before the task title, not a `Project > Task` prefix."""
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert 'class="unscheduled-project-pill"' in body
        assert "Conference XYZ" in body
        assert "&gt; Research" not in body

    def test_project_pill_carries_the_projects_icon(self, conn):
        """'Add icons to projects (backend only)' -- the router attaches the
        project's label-config icon to the pill (no client work needed)."""
        db.upsert_label_config(
            conn, {"name": "Conference XYZ", "is_project": 1, "start_date": "2026-08-01", "end_date": "2026-09-01", "icon": "folder", "created_at": _now()}
        )
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert 'href="#icon-folder"' in body
        assert "Conference XYZ" in body

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
        assert 'data-task-uid="t1"' in body
        assert 'href="/tasks/t1"' in body
        assert 'href="/tasks/t1/edit"' not in body

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

    def test_task_with_undated_session_stays_on_unscheduled_panel(self, conn):
        """A session added from the task modal's Work sessions "+" button has
        no date yet -- the task is still unscheduled work and must remain in
        the drag-source panel until the session is placed onto a slot."""
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")
        body = week_router.week_view(_request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn).body.decode()
        assert "unscheduled-task-item" in body
        assert "Research" in body

    def test_dragging_task_with_undated_session_places_that_session(self, conn):
        """Dragging a task that has an undated session placeholder places
        THAT session onto the dropped slot (sets its start/end) instead of
        creating yet another block -- so repeated "+" sessions each get
        placed by a drag, not multiplied."""
        _task(conn, "t1", title="Research")
        undated_uid = db.create_work_allocation(conn, "t1")
        resp = week_router.create_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T18:00:00", date_=_MONDAY, conn=conn
        )
        assert resp.status_code == 303
        allocations = db.list_work_allocations_for_task(conn, "t1")
        assert len(allocations) == 1
        assert allocations[0]["uid"] == undated_uid
        assert allocations[0]["start_at"] == f"{_MONDAY}T16:00:00"
        assert allocations[0]["end_at"] == f"{_MONDAY}T18:00:00"

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
    def test_delete_unschedules_the_block_not_the_task(self, conn):
        """"Delete" on a block doesn't delete the session -- it clears its
        start/end back to undated, so the task's session COUNT never drops
        just from unscheduling; the task itself is never deleted either."""
        _task(conn, "t1", title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        resp = week_router.delete_allocation(event_uid, date_=_MONDAY, conn=conn)
        assert resp.status_code == 303
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
        week_router.delete_allocation(event_uids[0], date_=_MONDAY, conn=conn)
        remaining = db.list_work_allocations_for_task(conn, "t1")
        assert [wa["uid"] for wa in remaining] == event_uids
        by_uid = {wa["uid"]: wa for wa in remaining}
        assert by_uid[event_uids[0]]["start_at"] is None
        assert by_uid[event_uids[1]]["start_at"] is not None
        assert by_uid[event_uids[2]]["start_at"] is not None


class TestUnscheduledPanelStepper:
    """"Unscheduled work" panel rework: each panel item shows its
    still-needing-placement session count (`undated_count`, not the task's
    total session count) with −/+ buttons. Direct feedback (2026-08-14):
    dropping one of a task's sessions onto the grid didn't move this number
    when it showed the total -- it must count DOWN as sessions get placed,
    and the − button must be available whenever there's an undated session
    to remove, including down to exactly one (reaching 0 remaining is a
    normal state, not a floor the panel avoids)."""

    def test_item_shows_plus_and_minus_buttons_at_one_undated_session(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")  # one undated session
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert 'data-task-uid="t1"' in body
        assert "unscheduled-count" in body
        assert "/tasks/t1/work-allocations" in body  # the "+" form action
        assert "/tasks/t1/work-allocations/remove-latest" in body  # − shown: 1 undated to remove

    def test_minus_button_hidden_with_no_undated_sessions(self, conn):
        """A task with only DATED (already-scheduled) sessions has nothing
        left for the panel's "−" to remove -- it must never appear as a way
        to delete a scheduled block."""
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert "/tasks/t1/work-allocations/remove-latest" not in body

    def test_count_reflects_sessions_still_needing_placement(self, conn):
        """The displayed number is undated_count, not the task's total
        session count -- placing one of two sessions on the grid must move
        it from 2 to 1, not leave it stuck at 2."""
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")
        db.create_work_allocation(conn, "t1")
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert '<span class="unscheduled-count" title="Sessions still needing placement">2</span>' in body

        event_uids = [wa["uid"] for wa in db.list_work_allocations_for_task(conn, "t1")]
        week_router.create_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T17:00:00", date_=_MONDAY, conn=conn
        )
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert '<span class="unscheduled-count" title="Sessions still needing placement">1</span>' in body

    def test_minus_button_renders_at_more_than_one_undated_session(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")
        db.create_work_allocation(conn, "t1")
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert "/tasks/t1/work-allocations/remove-latest" in body
        assert 'value="/week?date_=' in body  # the +/− forms return to this page

    def test_card_is_one_line_without_hours_or_due(self, conn):
        """The 2026-08-14 one-line card spec: pill + task title + session
        count only -- the scheduled/total hours readout and due date are
        gone, and there is no two-line title/stepper split."""
        _task(conn, "t1", title="Research", due_at=f"{_MONDAY}T00:00:00")
        db.create_work_allocation(conn, "t1")
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert "unscheduled-count" in body
        assert "unscheduled-hours" not in body
        assert "unscheduled-grip" not in body
        assert "unscheduled-task-body" not in body
        assert "&middot; due" not in body

    def test_item_has_no_native_draggable_attribute(self, conn):
        """Interaction 1 is POINTER-based now (project_calendar.js); a native
        HTML5 `draggable` attribute would double-trigger with the pointer
        handlers on desktop."""
        _task(conn, "t1", title="Research")
        body = week_router.week_view(_request(), conn=conn).body.decode()
        assert 'draggable="true"' not in body
