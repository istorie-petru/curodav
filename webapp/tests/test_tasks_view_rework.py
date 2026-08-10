"""Tests for Phase 9 of the projects/tags rework: independent date/status/
priority filters replacing the old combined 'smart filter', completed
tasks staying visible but separated, and start_at always defaulting to
today on creation. No bridge/Radicale dependency for the pure filter
logic; create_task needs a fake bridge (no live server) same pattern as
test_project_linking.py."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src import db
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid, due_at=None, status="active", priority=None):
    db.upsert_task(conn, {
        "uid": uid, "title": uid,
        "description": "", "status": status, "due_at": due_at, "priority": priority,
        "tags": [], "created_at": _now(),
    })


class TestDateFilter:
    def test_today(self, conn):
        today = date.today()
        tasks = [
            {"uid": "a", "due_at": today.isoformat()},
            {"uid": "b", "due_at": (today - timedelta(days=1)).isoformat()},
            {"uid": "c", "due_at": (today + timedelta(days=1)).isoformat()},
            {"uid": "d", "due_at": None},
        ]
        result = tasks_router._apply_date_filter(tasks, "today")
        assert {t["uid"] for t in result} == {"a"}

    def test_this_week_includes_today_through_six_days_out(self, conn):
        today = date.today()
        tasks = [
            {"uid": "today", "due_at": today.isoformat()},
            {"uid": "in6", "due_at": (today + timedelta(days=6)).isoformat()},
            {"uid": "in7", "due_at": (today + timedelta(days=7)).isoformat()},  # out of range
            {"uid": "yesterday", "due_at": (today - timedelta(days=1)).isoformat()},  # out of range
        ]
        result = tasks_router._apply_date_filter(tasks, "this_week")
        assert {t["uid"] for t in result} == {"today", "in6"}

    def test_overdue_is_pure_date_logic_regardless_of_status(self, conn):
        today = date.today()
        tasks = [
            {"uid": "a", "due_at": (today - timedelta(days=1)).isoformat(), "status": "active"},
            {"uid": "b", "due_at": today.isoformat(), "status": "active"},
        ]
        result = tasks_router._apply_date_filter(tasks, "overdue")
        assert {t["uid"] for t in result} == {"a"}

    def test_all_includes_tasks_with_no_due_date(self, conn):
        tasks = [{"uid": "a", "due_at": None}, {"uid": "b", "due_at": "2026-01-01"}]
        result = tasks_router._apply_date_filter(tasks, "all")
        assert {t["uid"] for t in result} == {"a", "b"}


class TestStatusFilter:
    def test_all_passes_everything(self):
        tasks = [{"status": "active"}, {"status": "done"}]
        assert len(tasks_router._apply_status_filter(tasks, "all")) == 2

    def test_specific_status(self):
        tasks = [{"uid": "a", "status": "active"}, {"uid": "b", "status": "waiting"}]
        result = tasks_router._apply_status_filter(tasks, "waiting")
        assert {t["uid"] for t in result} == {"b"}


class TestPriorityFilter:
    def test_all_passes_everything(self):
        tasks = [{"priority": 1}, {"priority": None}]
        assert len(tasks_router._apply_priority_filter(tasks, "all")) == 2

    def test_specific_priority(self):
        tasks = [{"uid": "a", "priority": 1}, {"uid": "b", "priority": 2}]
        result = tasks_router._apply_priority_filter(tasks, "1")
        assert {t["uid"] for t in result} == {"a"}


class TestFiltersAreIndependentAndCombine:
    def test_this_week_high_priority_waiting_combo(self, conn):
        """The specific gap the rework closes: a combination the old
        single 'smart filter' preset list had no entry for at all."""
        today = date.today()
        _seed_task(conn, "match", due_at=today.isoformat(), status="waiting", priority=1)
        _seed_task(conn, "wrong_status", due_at=today.isoformat(), status="active", priority=1)
        _seed_task(conn, "wrong_priority", due_at=today.isoformat(), status="waiting", priority=3)
        _seed_task(conn, "wrong_date", due_at=(today + timedelta(days=10)).isoformat(), status="waiting", priority=1)

        tasks = db.list_tasks(conn)
        tasks = tasks_router._apply_date_filter(tasks, "this_week")
        tasks = tasks_router._apply_status_filter(tasks, "waiting")
        tasks = tasks_router._apply_priority_filter(tasks, "1")
        assert {t["uid"] for t in tasks} == {"match"}


class TestCompletedTasksSeparation:
    def test_route_splits_open_and_completed(self, conn):
        from starlette.requests import Request

        _seed_task(conn, "open1", status="active")
        _seed_task(conn, "done1", status="done")
        _seed_task(conn, "archived1", status="archived")

        req = Request({"type": "http", "method": "GET", "path": "/tasks", "headers": []})
        resp = tasks_router.list_tasks(req, conn=conn)
        assert resp.status_code == 200
        open_uids = {t["uid"] for t in resp.context["open_tasks"]}
        completed_uids = {t["uid"] for t in resp.context["completed_tasks"]}
        assert open_uids == {"open1"}
        assert completed_uids == {"done1", "archived1"}

    def test_completed_tasks_visible_by_default_in_all_view(self, conn):
        """'Completed tasks remain in the database view, in today, all,
        this week views' -- the default (date_filter=all) must not hide
        them, just separate them."""
        from starlette.requests import Request

        _seed_task(conn, "done1", status="done", due_at=date.today().isoformat())
        req = Request({"type": "http", "method": "GET", "path": "/tasks", "headers": []})
        resp = tasks_router.list_tasks(req, conn=conn)
        assert any(t["uid"] == "done1" for t in resp.context["completed_tasks"])

    def test_completed_tasks_visible_in_today_view(self, conn):
        from starlette.requests import Request

        today = date.today().isoformat()
        _seed_task(conn, "done_today", status="done", due_at=today)
        req = Request({"type": "http", "method": "GET", "path": "/tasks", "headers": [(b"", b"")]}, )
        resp = tasks_router.list_tasks(req, date_filter="today", conn=conn)
        assert any(t["uid"] == "done_today" for t in resp.context["completed_tasks"])

    def test_completed_tasks_visible_in_this_week_view(self, conn):
        from starlette.requests import Request

        today = date.today().isoformat()
        _seed_task(conn, "done_this_week", status="done", due_at=today)
        req = Request({"type": "http", "method": "GET", "path": "/tasks", "headers": []})
        resp = tasks_router.list_tasks(req, date_filter="this_week", conn=conn)
        assert any(t["uid"] == "done_this_week" for t in resp.context["completed_tasks"])


class TestStartDateConfigurableAtCreation:
    # 2026-08-08 direct feedback ("tasks should also have start date") --
    # reverses the previous "start date is always today, not a form field
    # on creation" rule this class used to enforce: task_form.html now
    # shows Start date on the new-task form too, and routers/tasks.py's
    # create_task accepts it. Still defaults to today when left blank/not
    # sent at all, so every pre-existing caller that doesn't pass start_at
    # (this suite's other direct create_task() calls, task_detail.html's
    # subtask quick-add form) keeps the old "starts today" behavior.
    def test_create_task_defaults_to_today_when_start_at_omitted(self, conn):
        tasks_router.create_task(title="Test", description="", due_at="", priority="", status="active",
                                   tags="", recurrence="", parent_uid="",
                                   conn=conn)
        task = db.list_tasks(conn)[0]
        assert task["start_at"] == date.today().isoformat()

    def test_create_task_honors_an_explicit_start_at(self, conn):
        tasks_router.create_task(title="Test", description="", due_at="", start_at="2026-09-01",
                                   priority="", status="active", tags="", recurrence="", parent_uid="",
                                   conn=conn)
        task = db.list_tasks(conn)[0]
        assert task["start_at"] == "2026-09-01"

    def test_start_date_is_a_real_field_on_the_new_task_form(self, conn):
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/tasks/new", "headers": []})
        resp = tasks_router.new_task_form(req, conn=conn)
        body = resp.body.decode()
        assert 'name="start_at"' in body
