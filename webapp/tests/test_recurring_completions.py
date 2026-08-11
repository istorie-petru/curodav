"""Tests for the Phase 5 (command-center-rework) recurring-task completion
model -- habits were retired and their daily check-off + heatmap/streak
view reworked onto recurring tasks backed by `task_completions` rows:

  * complete_task on a recurring task writes a task_completions row for
    today (a plain one-off task just flips to done, no history row);
  * the detail-page heatmap toggle hits POST
    /tasks/{uid}/completion/{date}/toggle (referer redirect);
  * task_detail exposes heatmap/streak context for recurring tasks only.

2026-08-08: the tasks list's own "Habits & Recurring" section (and its
recurring_tasks/completed_today context) is gone -- superseded by the real
Tasks > Habits tab (routers/tasks.py's habits_view, see
test_tasks_habits_view.py), which now also covers a subset of what
habits/habit_entries used to (habit-labeled tasks specifically, not every
recurring task) -- see db.list_tasks' include_habit_tasks default.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid, status="active", recurrence=None):
    db.upsert_task(conn, {
        "uid": uid,
        "title": uid, "description": "", "status": status, "tags": [],
        "recurrence": recurrence, "created_at": _now(),
    })


def _request(path="/tasks/t1", method="POST", referer=None):
    headers = [(b"referer", referer.encode())] if referer else []
    return Request({"type": "http", "method": method, "path": path, "headers": headers})


class TestCompleteTaskWritesCompletion:
    def test_recurring_task_records_today(self, conn):
        _seed_task(conn, "t1", recurrence="daily")

        tasks_router.complete_task("t1", conn=conn)
        assert db.get_task(conn, "t1")["status"] == "done"
        assert db.get_task_completion(conn, "t1", date.today().isoformat()) is not None

    def test_plain_task_gets_no_completion_row(self, conn):
        _seed_task(conn, "t1")  # no recurrence
        tasks_router.complete_task("t1", conn=conn)
        assert db.get_task_completion(conn, "t1", date.today().isoformat()) is None


class TestCompletionToggle:
    def test_adds_then_removes_a_row_and_redirects_to_referer(self, conn):
        _seed_task(conn, "t1", recurrence="daily")
        today = date.today().isoformat()

        add_resp = tasks_router.toggle_task_completion(
            "t1", today, _request(path="/tasks", method="POST", referer="/tasks"), conn=conn
        )
        assert add_resp.status_code == 303
        assert add_resp.headers["location"] == "/tasks"
        assert db.get_task_completion(conn, "t1", today) is not None

        # Referer-less toggle falls back to the task detail page.
        no_ref = Request({"type": "http", "method": "POST", "path": "/tasks/t1", "headers": []})
        other = "2026-01-05"
        tasks_router.toggle_task_completion("t1", other, no_ref, conn=conn)
        assert other in {c["due_date"] for c in db.list_task_completions(conn, "t1")}
        # Toggle the same date again -> removes it.
        tasks_router.toggle_task_completion("t1", other, no_ref, conn=conn)
        assert other not in {c["due_date"] for c in db.list_task_completions(conn, "t1")}


class TestTaskDetailContext:
    def test_recurring_task_gets_heatmap_and_streak(self, conn):
        _seed_task(conn, "t1", recurrence="daily")
        today = date.today().isoformat()
        tasks_router.toggle_task_completion("t1", today, _request(), conn=conn)

        resp = tasks_router.task_detail("t1", _request("/tasks/t1", method="GET"), conn=conn)
        assert resp.context["task"]["recurrence"] == "daily"
        assert today in resp.context["completions"]
        assert resp.context["completion_weeks"]
        assert resp.context["current_streak"] == 1
        assert resp.context["longest_streak"] == 1

    def test_plain_task_gets_empty_heatmap(self, conn):
        _seed_task(conn, "t1")
        resp = tasks_router.task_detail("t1", _request("/tasks/t1", method="GET"), conn=conn)
        assert resp.context["completions"] == {}
        assert resp.context["completion_weeks"] == []
        assert resp.context["current_streak"] == 0
        assert resp.context["longest_streak"] == 0


class TestHeatmapHelpers:
    def test_streaks_count_consecutive_days(self):
        current, longest = tasks_router._completion_streaks(
            {"2026-08-01": "x", "2026-08-02": "x", "2026-08-04": "x"}, today=date(2026, 8, 5)
        )
        assert current == 1  # 08-04 is the latest, and today (08-05) is still allowed to be unlogged
        assert longest == 2

    def test_current_streak_tolerates_unlogged_today(self):
        current, _ = tasks_router._completion_streaks(
            {"2026-08-04": "x"}, today=date(2026, 8, 5)
        )
        assert current == 1

    def test_heatmap_weeks_end_this_week_and_flag_future(self):
        weeks = tasks_router._completion_heatmap_weeks({}, weeks=12, today=date(2026, 8, 3))
        last_week = weeks[-1]
        future = [d for d in last_week if d["is_future"]]
        assert future  # the tail of the final week is in the future
        assert all(d["level"] == -1 for d in future)
        non_future = [d for d in last_week if not d["is_future"]]
        assert all(d["level"] == 0 for d in non_future)


# TestTasksListContext (recurring_tasks/completed_today on the Table view)
# removed 2026-08-08 -- its whole subject no longer exists, per this
# suite's standing rule for a superseded feature (see module docstring).