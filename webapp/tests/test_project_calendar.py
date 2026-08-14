"""1.4 slice 3 (project pages & views' Week Calendar view) acceptance tests
-- see plans/open-priority.md § Project pages & views' Week Calendar bullet.
Covers `GET /projects/{name}/calendar` (`routers/projects.py::
project_calendar`): the project's scheduling surface -- unscheduled tasks
listed beside a week grid, dragging a task onto it (create_allocation),
moving/resizing an existing block (move_allocation), and deleting a block
without touching the task (delete_allocation). All three wrap the already-
tested `db.create_work_allocation`/`db.delete_work_allocation` (1.4 slice 1)
-- this file exercises the new endpoints wrapping them, not that underlying
mechanism again (see test_work_allocations.py for that)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import projects as projects_router

_MONDAY = "2026-08-17"  # a real Monday


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/projects", query_string=b""):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": query_string,
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _project(conn, name, start_date="2026-08-01", end_date="2026-09-01", icon=None):
    db.upsert_label_config(
        conn,
        {"name": name, "is_project": 1, "start_date": start_date, "end_date": end_date, "icon": icon, "created_at": _now()},
    )


def _task(conn, uid, tags, status="active", **overrides):
    row = {
        "uid": uid, "title": uid, "description": "", "status": status,
        "tags": tags, "created_at": _now(),
    }
    row.update(overrides)
    db.upsert_task(conn, row)
    return db.get_task(conn, uid)


class TestProjectCalendarRoute:
    def test_unknown_or_non_project_label_redirects(self, conn):
        resp = projects_router.project_calendar("Nope", _request("/projects/Nope/calendar"), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/projects"

    def test_renders_week_grid_and_subnav(self, conn):
        _project(conn, "Conference XYZ")
        body = projects_router.project_calendar(
            "Conference XYZ", _request("/projects/Conference XYZ/calendar"), conn=conn
        ).body.decode()
        assert "Week Calendar" in body
        assert "Unscheduled tasks" in body
        assert 'class="seg-btn active"' in body

    def test_unscheduled_task_lists_project_task_with_no_allocation(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        body = projects_router.project_calendar(
            "Conference XYZ",
            _request("/projects/Conference XYZ/calendar"),
            conn=conn,
        ).body.decode()
        assert 'class="unscheduled-project-pill"' in body
        assert "Conference XYZ" in body
        assert "Research" in body

    def test_task_with_an_allocation_drops_off_the_unscheduled_list(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        body = projects_router.project_calendar(
            "Conference XYZ",
            _request("/projects/Conference XYZ/calendar", query_string=f"date_={_MONDAY}".encode()),
            date_=_MONDAY,
            conn=conn,
        ).body.decode()
        assert 'class="unscheduled-task-item" data-task-uid="t1"' not in body  # the panel item is gone entirely

    def test_completed_task_never_appears_unscheduled(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Done task", status="done")
        body = projects_router.project_calendar(
            "Conference XYZ", _request("/projects/Conference XYZ/calendar"), conn=conn
        ).body.decode()
        assert "Done task" not in body

    def test_project_work_allocation_renders_as_prominent_block(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        body = projects_router.project_calendar(
            "Conference XYZ",
            _request("/projects/Conference XYZ/calendar", query_string=f"date_={_MONDAY}".encode()),
            date_=_MONDAY,
            conn=conn,
        ).body.decode()
        assert "work-allocation" in body
        assert "Research" in body
        assert 'data-task-uid="t1"' in body
        assert 'href="/tasks/t1"' in body
        assert 'href="/tasks/t1/edit"' not in body

    def test_ordinary_event_and_other_projects_allocation_render_as_subdued_context(self, conn):
        _project(conn, "Conference XYZ")
        _project(conn, "Other Project")
        _task(conn, "t1", tags=["Other Project"], title="Other work")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T09:00:00", f"{_MONDAY}T10:00:00")
        db.upsert_event(
            conn,
            {
                "uid": "e-plain",
                "title": "Ordinary meeting",
                "description": "",
                "start_at": f"{_MONDAY}T12:00:00",
                "end_at": f"{_MONDAY}T13:00:00",
                "all_day": False,
                "status": "active",
                "tags": [],
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
        body = projects_router.project_calendar(
            "Conference XYZ",
            _request("/projects/Conference XYZ/calendar", query_string=f"date_={_MONDAY}".encode()),
            date_=_MONDAY,
            conn=conn,
        ).body.decode()
        assert "context-event" in body
        assert "Ordinary meeting" in body
        assert "Other work" in body


class TestCreateAllocation:
    def test_dragging_a_task_onto_the_grid_creates_an_allocation(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        resp = projects_router.create_allocation(
            "Conference XYZ",
            task_uid="t1",
            start_at=f"{_MONDAY}T16:00:00",
            end_at=f"{_MONDAY}T18:00:00",
            date_=_MONDAY,
            conn=conn,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/projects/Conference%20XYZ/calendar?date_={_MONDAY}"
        allocations = db.list_work_allocations_for_task(conn, "t1")
        assert len(allocations) == 1
        assert allocations[0]["start_at"] == f"{_MONDAY}T16:00:00"

    def test_task_not_in_this_project_is_rejected(self, conn):
        """Defensive re-check -- a client-submitted task_uid must actually
        carry this project's label, same idiom the Relations picker's
        server-side re-check uses."""
        _project(conn, "Conference XYZ")
        _project(conn, "Other Project")
        _task(conn, "t1", tags=["Other Project"], title="Not this project")
        projects_router.create_allocation(
            "Conference XYZ",
            task_uid="t1",
            start_at=f"{_MONDAY}T16:00:00",
            end_at=f"{_MONDAY}T18:00:00",
            date_=_MONDAY,
            conn=conn,
        )
        assert db.list_work_allocations_for_task(conn, "t1") == []

    def test_task_with_undated_session_stays_unscheduled(self, conn):
        """A session added from the task modal's Work sessions "+" button has
        no date yet -- the task is still unscheduled work and must remain in
        the drag-source panel until the session is placed onto a slot."""
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        db.create_work_allocation(conn, "t1")
        body = projects_router.project_calendar(
            "Conference XYZ",
            _request("/projects/Conference XYZ/calendar", query_string=f"date_={_MONDAY}".encode()),
            date_=_MONDAY,
            conn=conn,
        ).body.decode()
        assert "unscheduled-task-item" in body
        assert "Research" in body

    def test_dragging_task_with_undated_session_places_that_session(self, conn):
        """Dragging a task that has an undated session placeholder places
        THAT session onto the dropped slot instead of creating yet another
        block -- so repeated "+" sessions each get placed by a drag, not
        multiplied."""
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        undated_uid = db.create_work_allocation(conn, "t1")
        projects_router.create_allocation(
            "Conference XYZ",
            task_uid="t1",
            start_at=f"{_MONDAY}T16:00:00",
            end_at=f"{_MONDAY}T18:00:00",
            date_=_MONDAY,
            conn=conn,
        )
        allocations = db.list_work_allocations_for_task(conn, "t1")
        assert len(allocations) == 1
        assert allocations[0]["uid"] == undated_uid
        assert allocations[0]["start_at"] == f"{_MONDAY}T16:00:00"

    def test_end_before_start_is_rejected(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        projects_router.create_allocation(
            "Conference XYZ",
            task_uid="t1",
            start_at=f"{_MONDAY}T18:00:00",
            end_at=f"{_MONDAY}T16:00:00",
            date_=_MONDAY,
            conn=conn,
        )
        assert db.list_work_allocations_for_task(conn, "t1") == []


class TestMoveAllocation:
    def test_move_changes_start_and_end_only(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        tuesday = (datetime.fromisoformat(_MONDAY) + timedelta(days=1)).date().isoformat()
        resp = projects_router.move_allocation(
            "Conference XYZ",
            event_uid,
            start_at=f"{tuesday}T09:00:00",
            end_at=f"{tuesday}T11:30:00",
            date_=_MONDAY,
            conn=conn,
        )
        assert resp.status_code == 303
        event = db.get_event(conn, event_uid)
        assert event["start_at"] == f"{tuesday}T09:00:00"
        assert event["end_at"] == f"{tuesday}T11:30:00"
        # Title/task link untouched by a move -- only the schedule changed.
        assert event["title"] == "Research"
        assert db.work_allocation_task_uid(conn, event_uid) == "t1"

    def test_resize_extends_the_end_time(self, conn):
        """Resizing changes the amount of scheduled work, not just its
        position -- verified via db.task_work_hours, the authoritative
        source for a task's scheduled/remaining totals."""
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        before = db.task_work_hours(conn, "t1")
        assert before["scheduled"] == pytest.approx(2.0)
        projects_router.move_allocation(
            "Conference XYZ",
            event_uid,
            start_at=f"{_MONDAY}T16:00:00",
            end_at=f"{_MONDAY}T19:00:00",
            date_=_MONDAY,
            conn=conn,
        )
        after = db.task_work_hours(conn, "t1")
        assert after["scheduled"] == pytest.approx(3.0)

    def test_moving_another_projects_allocation_is_rejected(self, conn):
        _project(conn, "Conference XYZ")
        _project(conn, "Other Project")
        _task(conn, "t1", tags=["Other Project"], title="Other work")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T09:00:00", f"{_MONDAY}T10:00:00")
        projects_router.move_allocation(
            "Conference XYZ",
            event_uid,
            start_at=f"{_MONDAY}T14:00:00",
            end_at=f"{_MONDAY}T15:00:00",
            date_=_MONDAY,
            conn=conn,
        )
        event = db.get_event(conn, event_uid)
        assert event["start_at"] == f"{_MONDAY}T09:00:00"


class TestDeleteAllocation:
    def test_delete_unschedules_the_block_not_the_task(self, conn):
        """"Delete" on a block doesn't delete the session -- it clears its
        start/end back to undated, so the task's session count never drops
        just from unscheduling; the task itself is never deleted either."""
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        resp = projects_router.delete_allocation("Conference XYZ", event_uid, date_=_MONDAY, conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/projects/Conference%20XYZ/calendar?date_={_MONDAY}"
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
        to zero on unschedule. Unscheduling the middle one of three sessions
        must leave the other two exactly as they were AND leave the
        unscheduled one still present, just undated -- the count never
        changes."""
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        for day in ("2026-08-17", "2026-08-18", "2026-08-19"):
            db.create_work_allocation(conn, "t1", f"{day}T16:00:00", f"{day}T18:00:00")
        event_uids = [wa["uid"] for wa in db.list_work_allocations_for_task(conn, "t1")]
        projects_router.delete_allocation("Conference XYZ", event_uids[1], date_=_MONDAY, conn=conn)
        remaining = db.list_work_allocations_for_task(conn, "t1")
        assert [wa["uid"] for wa in remaining] == event_uids
        by_uid = {wa["uid"]: wa for wa in remaining}
        assert by_uid[event_uids[1]]["start_at"] is None
        assert by_uid[event_uids[0]]["start_at"] is not None
        assert by_uid[event_uids[2]]["start_at"] is not None

    def test_deleted_allocations_task_becomes_unscheduled_again(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        projects_router.delete_allocation("Conference XYZ", event_uid, date_=_MONDAY, conn=conn)
        body = projects_router.project_calendar(
            "Conference XYZ",
            _request("/projects/Conference XYZ/calendar", query_string=f"date_={_MONDAY}".encode()),
            date_=_MONDAY,
            conn=conn,
        ).body.decode()
        assert 'class="unscheduled-project-pill"' in body
        assert "Conference XYZ" in body
        assert "Research" in body


class TestUnscheduledPanelStepper:
    """1.9 "unscheduled work" panel rework on the project Week Calendar:
    per-item session count with −/+ buttons on a ONE-LINE card (2026-08-14):
    a project pill (icon + name) then the task title on the left, the
    session count on the right -- no hours readout, no due date, no grip."""

    def _view(self, conn):
        return projects_router.project_calendar(
            "Conference XYZ",
            _request("/projects/Conference XYZ/calendar", query_string=f"date_={_MONDAY}".encode()),
            date_=_MONDAY,
            conn=conn,
        ).body.decode()

    def test_item_shows_plus_button_and_count_not_minus_at_one(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        db.create_work_allocation(conn, "t1")  # one undated session
        body = self._view(conn)
        assert 'data-task-uid="t1"' in body
        assert "unscheduled-count" in body
        assert "/tasks/t1/work-allocations" in body  # the "+" form action
        assert "/tasks/t1/work-allocations/remove-latest" not in body  # − hidden at count 1

    def test_minus_button_renders_at_more_than_one_session(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        db.create_work_allocation(conn, "t1")
        db.create_work_allocation(conn, "t1")
        body = self._view(conn)
        assert "/tasks/t1/work-allocations/remove-latest" in body
        assert 'value="/projects/Conference%20XYZ/calendar?date_=' in body  # +/− return here

    def test_card_is_one_line_without_hours(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        db.create_work_allocation(conn, "t1")
        body = self._view(conn)
        assert "unscheduled-count" in body
        assert "unscheduled-hours" not in body
        assert "unscheduled-grip" not in body
        assert "unscheduled-task-body" not in body
        assert "&middot; due" not in body

    def test_project_pill_carries_the_projects_icon(self, conn):
        _project(conn, "Conference XYZ", icon="folder")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        body = self._view(conn)
        assert 'href="#icon-folder"' in body
        assert "Conference XYZ" in body
