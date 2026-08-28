"""Tests for Tasks > Habits (2026-08-08, "add habits page as a view on
tasks") -- a task carrying the configured habit label
(task_habit_settings.habit_label, default "Habit") is treated as a habit:
excluded from db.list_tasks' default (Table/Timeline/Board/Calendar/
dashboard widgets all use it unchanged), and instead shown on
routers/tasks.py's habits_view with a checkbox/number-stepper check-in row
and a per-task heatmap sourced from task_completions/tasks.target_per_day.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid, tags=None, target_per_day=1, **overrides):
    row = {
        "uid": uid,
        "title": uid,
        "description": "",
        "status": "active",
        "tags": tags or [],
        "target_per_day": target_per_day,
        "created_at": _now(),
    }
    row.update(overrides)
    db.upsert_task(conn, row)


def _request(path="/tasks/habits", method="GET"):
    return Request({"type": "http", "method": method, "path": path, "headers": []})


class TestListTasksExcludesHabitLabel:
    def test_default_excludes_habit_labeled_task(self, conn):
        _seed_task(conn, "plain")
        _seed_task(conn, "habit1", tags=["Habit"])
        uids = {t["uid"] for t in db.list_tasks(conn)}
        assert uids == {"plain"}

    def test_include_habit_tasks_true_gets_everything(self, conn):
        _seed_task(conn, "plain")
        _seed_task(conn, "habit1", tags=["Habit"])
        uids = {t["uid"] for t in db.list_tasks(conn, include_habit_tasks=True)}
        assert uids == {"plain", "habit1"}

    def test_renamed_label_changes_which_tasks_are_excluded(self, conn):
        _seed_task(conn, "a", tags=["Habit"])
        _seed_task(conn, "b", tags=["Routine"])
        db.save_task_habit_settings(conn, "Routine")
        uids = {t["uid"] for t in db.list_tasks(conn)}
        # "a" (still labeled "Habit") is a normal task again once the
        # configured label moved to "Routine" -- only "b" stays hidden.
        assert uids == {"a"}


class TestListHabitTasks:
    def test_returns_only_labeled_tasks_sorted_by_title(self, conn):
        _seed_task(conn, "z", tags=["Habit"], title="Zzz")
        _seed_task(conn, "a", tags=["Habit"], title="Aaa")
        _seed_task(conn, "plain")
        titles = [t["title"] for t in db.list_habit_tasks(conn)]
        assert titles == ["Aaa", "Zzz"]


class TestHabitsViewRetired:
    """2026-08-28 "major rework" session (items 2+3): the dedicated Tasks >
    Habits page is gone -- `GET /tasks/habits` now redirects to the plain
    Table view, where every habit-labeled task (and every standalone Habit
    entity, see test_habits_router.py) renders as a row in the Habits
    group instead (routers/tasks.py's _habit_group_items/
    _build_task_groups)."""

    def test_habits_view_redirects_to_tasks(self, conn):
        resp = tasks_router.habits_view_redirect()
        assert resp.status_code == 302
        assert resp.headers["location"] == "/tasks"

    def test_habit_labeled_task_appears_in_the_habits_group_with_streak(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate")
        today = date.today().isoformat()
        db.upsert_task_completion(conn, "h1", today, _now())

        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        habits_group = next(g for g in resp.context["groups"] if g["kind"] == "habits")
        items = habits_group["habit_items"]
        assert len(items) == 1
        item = items[0]
        assert item["uid"] == "h1"
        assert item["kind"] == "task"
        assert item["current_streak"] == 1
        assert item["today_value"] == 1

    def test_quantity_habit_task_reports_is_quantity_and_next_value(self, conn):
        _seed_task(conn, "h2", tags=["Habit"], title="Water", target_per_day=8)
        today = date.today().isoformat()
        db.upsert_task_completion(conn, "h2", today, _now(), value=3)

        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        habits_group = next(g for g in resp.context["groups"] if g["kind"] == "habits")
        item = habits_group["habit_items"][0]
        assert item["is_quantity"] is True
        assert item["today_value"] == 3
        assert item["next_value"] == 4

    def test_plain_tasks_never_appear_in_the_habits_group(self, conn):
        _seed_task(conn, "plain")
        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        habits_group = next(g for g in resp.context["groups"] if g["kind"] == "habits")
        assert habits_group["habit_items"] == []

    def test_habit_labeled_task_excluded_from_project_and_unassigned_groups(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate")
        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        unassigned = next(g for g in resp.context["groups"] if g["kind"] == "unassigned")
        assert unassigned["tasks"] == []


class TestSetTaskCompletion:
    def test_posts_an_explicit_value(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], target_per_day=8)
        today = date.today().isoformat()
        tasks_router.set_task_completion(
            "h1", _request("/tasks/h1/completions", method="POST"), completion_date=today, value="5", conn=conn
        )
        assert db.get_task_completion(conn, "h1", today)["value"] == 5

    def test_zero_or_less_deletes_the_completion(self, conn):
        _seed_task(conn, "h1", tags=["Habit"])
        today = date.today().isoformat()
        db.upsert_task_completion(conn, "h1", today, _now(), value=2)
        tasks_router.set_task_completion(
            "h1", _request("/tasks/h1/completions", method="POST"), completion_date=today, value="0", conn=conn
        )
        assert db.get_task_completion(conn, "h1", today) is None


class TestHabitSettings:
    def test_defaults_to_habit(self, conn):
        assert db.get_task_habit_settings(conn)["habit_label"] == "Habit"

    def test_save_and_reload(self, conn):
        db.save_task_habit_settings(conn, "Routine")
        assert db.get_task_habit_settings(conn)["habit_label"] == "Routine"

    def test_blank_falls_back_to_habit(self, conn):
        db.save_task_habit_settings(conn, "   ")
        assert db.get_task_habit_settings(conn)["habit_label"] == "Habit"
