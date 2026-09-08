"""Tests for Phase 9 of the projects/tags rework: independent date/status
filters replacing the old combined 'smart filter' (Importance/Urgency were
also part of that filter set at the time; that whole feature is since
removed outright, see src/derived_state.py's module docstring), completed
tasks staying visible but separated, and start_at always defaulting to
today on creation. No bridge/Radicale dependency for the pure filter logic;
create_task needs a fake bridge (no live server) same pattern as
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


def _seed_task(conn, uid, due_at=None, status="active"):
    db.upsert_task(conn, {
        "uid": uid, "title": uid,
        "description": "", "status": status, "due_at": due_at,
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


class TestFilterOptionListsAfterFilterCleanup:
    """2026-08-28 "major rework" session (item 3, "filtering reduced to
    date only"): Status/Importance/Urgency/label filtering is gone from the
    Tasks page entirely -- `_apply_status_filter`/`_apply_importance_
    filter`/`_apply_urgency_filter`/`_apply_label_filter` and their
    STATUS_FILTERS/IMPORTANCE_FILTERS/URGENCY_FILTERS option lists no
    longer exist on this module (their prior TestStatusFilter/
    TestImportanceUrgencyFilters/TestFilterOptionListsAfterFilterCleanup
    coverage is gone with them, per git log). DATE_FILTERS is the one
    filter axis left standing."""

    def test_date_filters_no_longer_carry_virtual_states(self):
        assert tasks_router.DATE_FILTERS == ["all", "today", "tomorrow", "this_week", "this_month"]

    def test_status_importance_urgency_filter_machinery_is_gone(self):
        for name in (
            "_apply_status_filter", "_apply_importance_filter", "_apply_urgency_filter",
            "_apply_label_filter", "STATUS_FILTERS", "IMPORTANCE_FILTERS", "URGENCY_FILTERS",
        ):
            assert not hasattr(tasks_router, name), f"{name} should have been removed"


class TestCompletedTasksSeparation:
    def test_route_splits_open_and_completed(self, conn):
        from starlette.requests import Request

        _seed_task(conn, "open1", status="active")
        _seed_task(conn, "done1", status="done")
        _seed_task(conn, "archived1", status="archived")

        req = Request({"type": "http", "method": "GET", "path": "/tasks", "headers": []})
        resp = tasks_router.list_tasks(req, conn=conn)
        assert resp.status_code == 200
        completed = next(g for g in resp.context["groups"] if g["kind"] == "completed")
        unassigned = next(g for g in resp.context["groups"] if g["kind"] == "unassigned")
        assert {t["uid"] for t in unassigned["tasks"]} == {"open1"}
        assert {t["uid"] for t in completed["tasks"]} == {"done1", "archived1"}

    def test_completed_tasks_visible_by_default_in_all_view(self, conn):
        """'Completed tasks remain in the database view, in today, all,
        this week views' -- the default (date_filter=all) must not hide
        them, just separate them."""
        from starlette.requests import Request

        _seed_task(conn, "done1", status="done", due_at=date.today().isoformat())
        req = Request({"type": "http", "method": "GET", "path": "/tasks", "headers": []})
        resp = tasks_router.list_tasks(req, conn=conn)
        completed = next(g for g in resp.context["groups"] if g["kind"] == "completed")
        assert any(t["uid"] == "done1" for t in completed["tasks"])

    def test_completed_tasks_visible_in_today_view(self, conn):
        from starlette.requests import Request

        today = date.today().isoformat()
        _seed_task(conn, "done_today", status="done", due_at=today)
        req = Request({"type": "http", "method": "GET", "path": "/tasks", "headers": [(b"", b"")]}, )
        resp = tasks_router.list_tasks(req, date_filter="today", conn=conn)
        completed = next(g for g in resp.context["groups"] if g["kind"] == "completed")
        assert any(t["uid"] == "done_today" for t in completed["tasks"])

    def test_completed_tasks_visible_in_this_week_view(self, conn):
        from starlette.requests import Request

        today = date.today().isoformat()
        _seed_task(conn, "done_this_week", status="done", due_at=today)
        req = Request({"type": "http", "method": "GET", "path": "/tasks", "headers": []})
        resp = tasks_router.list_tasks(req, date_filter="this_week", conn=conn)
        completed = next(g for g in resp.context["groups"] if g["kind"] == "completed")
        assert any(t["uid"] == "done_this_week" for t in completed["tasks"])


class TestStartDateConfigurableAtCreation:
    # 2026-08-08 direct feedback ("tasks should also have start date") --
    # reverses the previous "start date is always today, not a form field
    # on creation" rule this class used to enforce: task_form.html now
    # shows Start date on the new-task form too, and routers/tasks.py's
    # create_task accepts it. Still defaults to today when left blank/not
    # sent at all, so every pre-existing caller that doesn't pass start_at
    # (this suite's other direct create_task() calls) keeps the old
    # "starts today" behavior.
    def test_create_task_defaults_to_today_when_start_at_omitted(self, conn):
        tasks_router.create_task(title="Test", description="", due_at="", status="active",
                                   tags="", recurrence="",
                                   conn=conn)
        task = db.list_tasks(conn)[0]
        assert task["start_at"] == date.today().isoformat()

    def test_create_task_honors_an_explicit_start_at(self, conn):
        tasks_router.create_task(title="Test", description="", due_at="", start_at="2026-09-01",
                                   status="active", tags="", recurrence="",
                                   conn=conn)
        task = db.list_tasks(conn)[0]
        assert task["start_at"] == "2026-09-01"

    def test_start_date_is_a_real_field_on_the_new_task_form(self, conn):
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/tasks/new", "headers": []})
        resp = tasks_router.new_task_form(req, conn=conn)
        body = resp.body.decode()
        assert 'name="start_at"' in body
