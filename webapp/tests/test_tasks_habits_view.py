"""Tests for Tasks > Habits (2026-08-08, "add habits page as a view on
tasks") -- a task carrying the configured habit label
(task_habit_settings.habit_label, default "Habit") is treated as a habit:
excluded from db.list_tasks' default (Table/Timeline/Board/Calendar/
dashboard widgets all use it unchanged), and instead shown on
routers/tasks.py's habits_view with a checkbox/number-stepper check-in row
and a per-task heatmap sourced from task_completions/tasks.target_per_day.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

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


def _request_with_app(path, db_path):
    """A Request whose `.app.state.settings.db_path` resolves, needed to
    exercise deps.py's habit_streak_text()/_cached_app_meta() -- a bare
    `_request()` above has no `.app` at all, so that global silently falls
    back to its "standard" default every time regardless of what's stored
    in `conn`. Same pattern as test_recurrence_terminology.py's own helper
    of the same name."""
    fake_app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(db_path=db_path, radicale_base_url="http://localhost:5232")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
            "app": fake_app,
        }
    )


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



class TestTasksPageNoLongerShowsHabits:
    """Habits H2 (2026-09-24): habits moved to their own page (/habits,
    see test_habits_page.py); the Tasks table's Habits group is gone."""

    def test_tasks_habits_url_redirects_to_habits_page(self, conn):
        resp = tasks_router.habits_view_redirect()
        assert resp.status_code == 302
        assert resp.headers["location"] == "/habits"

    def test_no_habits_group_and_habit_task_not_in_any_group(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=DAILY")
        _seed_task(conn, "t1", title="Plain")
        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        groups = resp.context["groups"]
        assert all(g["kind"] != "habits" for g in groups)
        uids = [t["uid"] for g in groups for t in g.get("tasks", [])]
        assert uids == ["t1"]
        assert 'id="habits-table"' not in resp.body.decode()

    def test_only_habits_means_tasks_empty_state(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=DAILY")
        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        assert resp.context["has_any"] is False


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

    def test_no_fetch_header_still_redirects(self, conn):
        """Plain-HTML fallback (no JS): unchanged 303 behavior."""
        _seed_task(conn, "h1", tags=["Habit"])
        today = date.today().isoformat()
        resp = tasks_router.set_task_completion(
            "h1", _request("/tasks/h1/completions", method="POST"), completion_date=today, value="1", conn=conn
        )
        assert resp.status_code == 303

    def test_fetch_header_returns_json_instead_of_a_redirect(self, conn):
        """2026-08-28 follow-up fix: this endpoint used to always 303
        regardless of `X-Requested-With`, so the Habits group's "+1" button
        (_habit_row.html) had no JSON success path and fell back to a plain
        native form submit -- a full-page reload on every check-in
        (reported directly against a `POST .../completions ... 303 See
        Other` server log). Now dual-mode like every other mutation route."""
        _seed_task(conn, "h1", tags=["Habit"], target_per_day=8)
        today = date.today().isoformat()
        req = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/tasks/h1/completions",
                "headers": [(b"x-requested-with", b"fetch")],
            }
        )
        resp = tasks_router.set_task_completion(
            "h1", req, completion_date=today, value="5", x_requested_with="fetch", conn=conn
        )
        assert resp.status_code == 200
        assert db.get_task_completion(conn, "h1", today)["value"] == 5


class TestToggleTaskCompletion:
    def test_no_fetch_header_still_redirects(self, conn):
        _seed_task(conn, "h1", tags=["Habit"])
        today = date.today().isoformat()
        resp = tasks_router.toggle_task_completion(
            "h1", today, _request("/tasks/h1/completion/" + today + "/toggle", method="POST"), conn=conn
        )
        assert resp.status_code == 303

    def test_fetch_header_returns_json_and_toggles(self, conn):
        """Same dual-mode fix as TestSetTaskCompletion above, applied to the
        plain checkbox habit's toggle route (_habit_row.html's
        `habit-checkin-toggle` form)."""
        _seed_task(conn, "h1", tags=["Habit"])
        today = date.today().isoformat()
        req = _request("/tasks/h1/completion/" + today + "/toggle", method="POST")
        resp = tasks_router.toggle_task_completion("h1", today, req, x_requested_with="fetch", conn=conn)
        assert resp.status_code == 200
        assert db.get_task_completion(conn, "h1", today) is not None
        # toggling again removes it
        resp = tasks_router.toggle_task_completion("h1", today, req, x_requested_with="fetch", conn=conn)
        assert resp.status_code == 200
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
