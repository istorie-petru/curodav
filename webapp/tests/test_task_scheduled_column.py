"""1.5's final piece -- the deadline-vs-work-allocation distinction (see
plans/open-priority.md § Task model, "The distinction between a task
deadline and scheduled work is explicit"). The two fields already existed
independently (`due_at` and work allocations via `db.task_work_hours`), but
the global Tasks table and the project detail Tasks view (both rendering
the shared `_task_row.html` macro) only ever showed "Due" -- work-allocation
status was invisible on the primary task-management surface unless the
detail modal was opened. This adds a "Scheduled" column, distinct from
"Due", to both.

Covers: a task with no allocations renders a plain empty-state dash (not an
error), a task with allocations shows the right completed/scheduled hours,
the column appears on both `GET /tasks` and `GET /projects/{name}` (the
shared macro), and `db.task_work_hours_bulk` (the batched query added to
avoid an N+1 -- one query per row would otherwise happen on every page
render) matches `db.task_work_hours`'s per-task numbers exactly."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import projects as projects_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/tasks", query_string=b""):
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


def _task(conn, uid, tags=None, status="active", due_at=None, title=None):
    db.upsert_task(
        conn,
        {
            "uid": uid, "title": title or uid, "description": "", "status": status,
            "tags": tags or [], "created_at": _now(), "due_at": due_at,
        },
    )


def _project(conn, name, start_date="2026-08-01", end_date="2026-09-01"):
    db.upsert_label_config(
        conn,
        {"name": name, "is_project": 1, "start_date": start_date, "end_date": end_date, "created_at": _now()},
    )


class TestGlobalTasksPage:
    def test_no_allocations_renders_dash_not_error(self, conn):
        _task(conn, "t1")
        resp = tasks_router.list_tasks(_request(), conn=conn)
        assert resp.status_code == 200
        task = next(t for t in resp.context["open_tasks"] if t["uid"] == "t1")
        assert task["work_hours"] == {"scheduled": 0.0, "completed": 0.0, "remaining": 0.0}
        body = resp.body.decode()
        assert "Scheduled" in body

    def test_allocation_hours_shown_in_table(self, conn):
        _task(conn, "t1", due_at="2026-09-01T00:00:00")
        now = datetime.now(timezone.utc)
        # A past (completed) 2h block and a future (still-scheduled) 1h block.
        db.create_work_allocation(
            conn, "t1",
            (now - timedelta(days=1)).isoformat(),
            (now - timedelta(days=1) + timedelta(hours=2)).isoformat(),
        )
        db.create_work_allocation(
            conn, "t1",
            (now + timedelta(days=1)).isoformat(),
            (now + timedelta(days=1) + timedelta(hours=1)).isoformat(),
        )
        resp = tasks_router.list_tasks(_request(), conn=conn)
        task = next(t for t in resp.context["open_tasks"] if t["uid"] == "t1")
        assert task["work_hours"]["scheduled"] == pytest.approx(3.0)
        assert task["work_hours"]["completed"] == pytest.approx(2.0)
        assert task["work_hours"]["remaining"] == pytest.approx(1.0)
        body = resp.body.decode()
        assert "2.0/3.0h" in body

    def test_due_and_scheduled_are_distinct_columns(self, conn):
        _task(conn, "t1", due_at="2026-09-01T00:00:00")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert ">Due<" in body
        assert ">Scheduled<" in body


class TestProjectDetailPage:
    def test_scheduled_column_present_and_correct(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"])
        now = datetime.now(timezone.utc)
        db.create_work_allocation(
            conn, "t1", now.isoformat(), (now + timedelta(hours=4)).isoformat()
        )
        body = projects_router.project_detail(
            "Conference XYZ", _request("/projects/Conference XYZ"), conn=conn
        ).body.decode()
        assert ">Scheduled<" in body
        assert "0.0/4.0h" in body

    def test_task_with_no_allocations_shows_dash(self, conn):
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"])
        resp = projects_router.project_detail(
            "Conference XYZ", _request("/projects/Conference XYZ"), conn=conn
        )
        task = next(t for t in resp.context["open_tasks"] if t["uid"] == "t1")
        assert task["work_hours"] == {"scheduled": 0.0, "completed": 0.0, "remaining": 0.0}


class TestTaskWorkHoursBulk:
    def test_matches_per_task_function(self, conn):
        _task(conn, "t1")
        _task(conn, "t2")
        now = datetime.now(timezone.utc)
        db.create_work_allocation(conn, "t1", now.isoformat(), (now + timedelta(hours=2)).isoformat())
        bulk = db.task_work_hours_bulk(conn, ["t1", "t2"])
        assert bulk["t1"] == db.task_work_hours(conn, "t1")
        assert bulk["t2"] == db.task_work_hours(conn, "t2")

    def test_empty_list_returns_empty_dict(self, conn):
        assert db.task_work_hours_bulk(conn, []) == {}

    def test_task_with_no_allocations_zero_filled(self, conn):
        _task(conn, "t1")
        bulk = db.task_work_hours_bulk(conn, ["t1"])
        assert bulk["t1"] == {"scheduled": 0.0, "completed": 0.0, "remaining": 0.0}
