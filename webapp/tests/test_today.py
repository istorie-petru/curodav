"""1.7 slice 1 acceptance tests (plans/open-priority.md § Information
architecture & view surfaces' "Today -- execution" bullet) -- `GET /today`
(`routers/today.py::today_view`): today's ordinary calendar events split
from today's scheduled task work (work allocations), due/overdue tasks, and
important/urgent items not already covered by those. No new data model --
everything is read straight off db.list_events/list_tasks plus the shared
derived_state aggregation service (1.1), same as test_project_calendar.py's
own direct-router-call convention."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import today as today_router

_TODAY = datetime.now(timezone.utc).date().isoformat()


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request():
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/today",
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _task(conn, uid, **overrides):
    row = {
        "uid": uid, "title": uid, "description": "", "status": "active",
        "tags": [], "created_at": _now(),
    }
    row.update(overrides)
    db.upsert_task(conn, row)
    return db.get_task(conn, uid)


def _event(conn, uid, start_at, end_at=None, **overrides):
    row = {
        "uid": uid, "title": uid, "description": "", "status": "active",
        "all_day": False, "start_at": start_at, "end_at": end_at,
        "tags": [], "created_at": _now(), "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_event(conn, row)
    return db.get_event(conn, uid)


class TestTodaySchedule:
    def test_ordinary_event_today_shows_in_calendar_events(self, conn):
        _event(conn, "e1", f"{_TODAY}T09:00:00", f"{_TODAY}T10:00:00", title="Standup")
        body = today_router.today_view(_request(), conn=conn).body.decode()
        assert "Standup" in body

    def test_event_on_another_day_is_excluded(self, conn):
        _event(conn, "e1", "2020-01-01T09:00:00", "2020-01-01T10:00:00", title="Old meeting")
        body = today_router.today_view(_request(), conn=conn).body.decode()
        assert "Old meeting" not in body

    def test_work_allocation_today_shows_as_scheduled_work_not_ordinary_event(self, conn):
        _task(conn, "t1", title="Write report")
        db.create_work_allocation(conn, "t1", f"{_TODAY}T14:00:00", f"{_TODAY}T16:00:00")
        body = today_router.today_view(_request(), conn=conn).body.decode()
        assert "Write report" in body
        assert "2.0h" in body

    def test_scheduled_hours_today_sums_work_allocations(self, conn):
        _task(conn, "t1", title="Write report")
        db.create_work_allocation(conn, "t1", f"{_TODAY}T14:00:00", f"{_TODAY}T16:00:00")
        _task(conn, "t2", title="Review PR")
        db.create_work_allocation(conn, "t2", f"{_TODAY}T09:00:00", f"{_TODAY}T09:30:00")
        resp = today_router.today_view(_request(), conn=conn)
        assert resp.body.decode()
        # Rendered via workload.scheduled_hours_today, 2.5h total.
        assert "2.5h" in resp.body.decode()


class TestDueOverdue:
    def test_overdue_open_task_shows_overdue_tag(self, conn):
        _task(conn, "t1", title="Late thing", due_at="2020-01-01T00:00:00")
        body = today_router.today_view(_request(), conn=conn).body.decode()
        assert "Late thing" in body
        assert "Overdue" in body

    def test_due_today_task_shows_today_tag(self, conn):
        _task(conn, "t1", title="Due now", due_at=f"{_TODAY}T00:00:00")
        body = today_router.today_view(_request(), conn=conn).body.decode()
        assert "Due now" in body

    def test_done_task_never_appears(self, conn):
        _task(conn, "t1", title="Finished", due_at="2020-01-01T00:00:00", status="done")
        body = today_router.today_view(_request(), conn=conn).body.decode()
        assert "Finished" not in body

    def test_future_due_task_not_in_due_overdue_list(self, conn):
        _task(conn, "t1", title="Later thing", due_at="2099-01-01T00:00:00")
        body = today_router.today_view(_request(), conn=conn).body.decode()
        assert "Later thing" not in body


class TestImportantUrgent:
    def test_important_task_not_due_today_still_surfaces(self, conn):
        _task(conn, "t1", title="Big important thing", importance=3, due_at="2099-01-01T00:00:00")
        body = today_router.today_view(_request(), conn=conn).body.decode()
        assert "Big important thing" in body
        assert "Important" in body

    def test_task_already_shown_as_due_today_is_not_duplicated_in_important_section(self, conn):
        _task(conn, "t1", title="Uniquely-titled-important-task", importance=3, due_at=f"{_TODAY}T00:00:00")
        resp = today_router.today_view(_request(), conn=conn)
        assert resp.body.decode().count("Uniquely-titled-important-task") == 1

    def test_plain_task_with_no_importance_or_urgency_is_absent(self, conn):
        _task(conn, "t1", title="Whatever", due_at="2099-01-01T00:00:00")
        body = today_router.today_view(_request(), conn=conn).body.decode()
        assert "Whatever" not in body


class TestWorkloadCounts:
    def test_counts_reflect_seeded_data(self, conn):
        _task(conn, "t1", title="Overdue one", due_at="2020-01-01T00:00:00")
        _task(conn, "t2", title="Due today one", due_at=f"{_TODAY}T00:00:00")
        _event(conn, "e1", f"{_TODAY}T09:00:00", f"{_TODAY}T10:00:00", title="A meeting")
        resp = today_router.today_view(_request(), conn=conn)
        body = resp.body.decode()
        assert 'class="at-a-glance-number is-overdue">1<' in body
