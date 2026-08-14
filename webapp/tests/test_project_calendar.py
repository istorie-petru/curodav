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


def _project(conn, name, start_date="2026-08-01", end_date="2026-09-01"):
    db.upsert_label_config(
        conn,
        {"name": name, "is_project": 1, "start_date": start_date, "end_date": end_date, "created_at": _now()},
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
        assert "Conference XYZ &gt; Research" in body or "Conference XYZ > Research" in body

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
        assert "Conference XYZ &gt; Research" not in body
        assert "Conference XYZ > Research" not in body

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
        assert 'href="/tasks/t1/edit"' in body

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
    def test_delete_removes_only_the_block_not_the_task(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        resp = projects_router.delete_allocation("Conference XYZ", event_uid, date_=_MONDAY, conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/projects/Conference%20XYZ/calendar?date_={_MONDAY}"
        assert db.get_event(conn, event_uid) is None
        assert db.get_task(conn, "t1") is not None
        assert db.list_work_allocations_for_task(conn, "t1") == []

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
        assert "Conference XYZ &gt; Research" in body or "Conference XYZ > Research" in body
