"""Tests for Phase 9 of the projects/tags rework: independent date/status/
importance/urgency filters replacing the old combined 'smart filter',
completed tasks staying visible but separated, and start_at always
defaulting to today on creation. No bridge/Radicale dependency for the
pure filter logic; create_task needs a fake bridge (no live server) same
pattern as test_project_linking.py."""

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


def _seed_task(conn, uid, due_at=None, status="active", importance=None, urgency=None):
    """importance/urgency are computed, not stored columns (side work,
    post-1.1, src/derived_state.py) -- importance is reproduced via a
    dedicated per-task label with that label_config rule; urgency only
    supports level 3 (due today, temporal), the only level this file
    needs."""
    tags = []
    if importance is not None:
        label = f"{uid}-imp-label"
        db.upsert_label_config(conn, {"name": label, "importance": importance})
        tags.append(label)
    if urgency == 3 and due_at is None:
        due_at = date.today().isoformat()
    db.upsert_task(conn, {
        "uid": uid, "title": uid,
        "description": "", "status": status, "due_at": due_at,
        "tags": tags, "created_at": _now(),
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

    def test_overdue_is_a_virtual_pseudo_status(self):
        """Tasks page filter cleanup (2026-08-15, plans/open.md): `overdue`
        moved from DATE_FILTERS into STATUS_FILTERS as a virtual value --
        it isn't a real `tasks.status`, so it needs the same
        `derived_state.virtual_states` path _apply_date_filter's old
        `overdue` branch used, now reached via `label_rules`."""
        today = date.today()
        tasks = [
            {"uid": "a", "due_at": (today - timedelta(days=1)).isoformat(), "status": "active"},
            {"uid": "b", "due_at": today.isoformat(), "status": "active"},
            {"uid": "c", "due_at": (today - timedelta(days=5)).isoformat(), "status": "done"},
        ]
        result = tasks_router._apply_status_filter(tasks, "overdue", {})
        assert {t["uid"] for t in result} == {"a", "c"}

    def test_overdue_is_absent_from_status_filter_with_no_label_rules_arg(self):
        """label_rules defaults to None (same convention as the other three
        `_apply_*_filter` helpers) -- overdue still resolves correctly
        without every call site being forced to pass `{}` explicitly."""
        today = date.today()
        tasks = [{"uid": "a", "due_at": (today - timedelta(days=1)).isoformat(), "status": "active"}]
        result = tasks_router._apply_status_filter(tasks, "overdue")
        assert {t["uid"] for t in result} == {"a"}


class TestImportanceUrgencyFilters:
    """importance/urgency are computed (label rules + temporal state, see
    src/derived_state.py), so these filters now need `label_rules` and
    real tags/due dates instead of a raw stored value -- "all" still
    passes anything straight through with no computation, so those two
    keep working on bare dicts unchanged."""

    def test_importance_all_passes_everything(self):
        tasks = [{"tags": ["Exam"]}, {"tags": []}]
        assert len(tasks_router._apply_importance_filter(tasks, "all")) == 2

    def test_urgency_all_passes_everything(self):
        tasks = [{"due_at": "2026-01-01"}, {"due_at": None}]
        assert len(tasks_router._apply_urgency_filter(tasks, "all")) == 2

    def test_specific_importance(self):
        tasks = [{"uid": "a", "tags": ["Hi"]}, {"uid": "b", "tags": ["Lo"]}]
        rules = {"Hi": {"importance": 1}, "Lo": {"importance": 2}}
        result = tasks_router._apply_importance_filter(tasks, "1", rules)
        assert {t["uid"] for t in result} == {"a"}

    def test_specific_urgency(self):
        today = date.today().isoformat()
        far_out = (date.today() + timedelta(days=30)).isoformat()
        tasks = [{"uid": "a", "due_at": today}, {"uid": "b", "due_at": far_out}]
        result = tasks_router._apply_urgency_filter(tasks, "3")
        assert {t["uid"] for t in result} == {"a"}

    def test_importance_and_urgency_are_independent_axes(self):
        today = date.today().isoformat()
        far_out = (date.today() + timedelta(days=30)).isoformat()
        tasks = [
            {"uid": "a", "tags": ["Hi"], "due_at": far_out},
            {"uid": "b", "tags": ["Lo"], "due_at": today},
        ]
        rules = {"Hi": {"importance": 3}, "Lo": {"importance": 1}}
        assert {t["uid"] for t in tasks_router._apply_importance_filter(tasks, "3", rules)} == {"a"}
        assert {t["uid"] for t in tasks_router._apply_urgency_filter(tasks, "3", rules)} == {"b"}

    def test_important_any_level_option(self):
        """Tasks page filter cleanup (2026-08-15, plans/open.md): `important`
        moved from DATE_FILTERS into IMPORTANCE_FILTERS as an "(any level)"
        option -- at/above the Important threshold (derived_state.
        is_important), not one exact 1/2/3 level."""
        tasks = [
            {"uid": "a", "tags": ["Hi"]},
            {"uid": "b", "tags": ["Mid"]},
            {"uid": "c", "tags": []},
        ]
        rules = {"Hi": {"importance": 3}, "Mid": {"importance": 2}}
        result = tasks_router._apply_importance_filter(tasks, "important", rules)
        assert {t["uid"] for t in result} == {"a"}

    def test_urgent_any_level_option(self):
        """The urgency-axis sibling of test_important_any_level_option."""
        today = date.today().isoformat()
        far_out = (date.today() + timedelta(days=30)).isoformat()
        tasks = [{"uid": "a", "due_at": today}, {"uid": "b", "due_at": far_out}]
        result = tasks_router._apply_urgency_filter(tasks, "urgent", {})
        assert {t["uid"] for t in result} == {"a"}


class TestFilterOptionListsAfterFilterCleanup:
    """Tasks page filter cleanup (2026-08-15, plans/open.md § Tasks page
    filter cleanup): pins the exact new shape of the four dropdowns' option
    lists so a future edit can't silently reintroduce overdue/important/
    urgent into the Date dropdown, or drop them from their new homes."""

    def test_date_filters_no_longer_carry_virtual_states(self):
        assert tasks_router.DATE_FILTERS == ["all", "today", "tomorrow", "this_week", "this_month"]

    def test_status_filters_gained_overdue(self):
        assert tasks_router.STATUS_FILTERS[0] == "all"
        assert tasks_router.STATUS_FILTERS[-1] == "overdue"
        assert tasks_router.STATUS_FILTER_LABELS["overdue"] == "Overdue"

    def test_importance_filters_gained_important(self):
        assert tasks_router.IMPORTANCE_FILTERS == ["all", "1", "2", "3", "important"]
        assert "important" in tasks_router.IMPORTANCE_FILTER_LABELS

    def test_urgency_filters_gained_urgent(self):
        assert tasks_router.URGENCY_FILTERS == ["all", "1", "2", "3", "urgent"]
        assert "urgent" in tasks_router.URGENCY_FILTER_LABELS


class TestFiltersAreIndependentAndCombine:
    def test_this_week_high_importance_waiting_combo(self, conn):
        """The specific gap the rework closes: a combination the old
        single 'smart filter' preset list had no entry for at all."""
        today = date.today()
        _seed_task(conn, "match", due_at=today.isoformat(), status="waiting", importance=3)
        _seed_task(conn, "wrong_status", due_at=today.isoformat(), status="active", importance=3)
        _seed_task(conn, "wrong_importance", due_at=today.isoformat(), status="waiting", importance=1)
        _seed_task(conn, "wrong_date", due_at=(today + timedelta(days=10)).isoformat(), status="waiting", importance=3)

        label_rules = db.list_label_rules(conn)
        tasks = db.list_tasks(conn)
        tasks = tasks_router._apply_date_filter(tasks, "this_week")
        tasks = tasks_router._apply_status_filter(tasks, "waiting")
        tasks = tasks_router._apply_importance_filter(tasks, "3", label_rules)
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
