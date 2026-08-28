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


class TestHabitRowAsyncSubmit:
    """The Habits group's check-in form (_habit_row.html) needs
    `data-cc-change` for async_crud.js's global data-cc-change submit
    listener (loaded in base.html) to intercept it at all -- without it, a
    submit falls through to a plain native form submit (full-page reload,
    reported directly). Guards against that gap silently coming back by
    rendering the real page template, same pattern as
    test_phase1_derived_states.py's own template-render assertions.

    2026-08-28 follow-ups: first the checkbox/"+1"/reset trio became one
    always-visible `<input type="number">`; same day, direct feedback
    ("like Notion... click twice and it becomes editable in a non-discrete
    way") turned that visible input into a `data-inline-edit` span (plain
    text by default, static/inline_edit.js swaps in a real input on
    double-click) plus a hidden `name="value"` input carrying the actual
    value, both wrapped in the same `.habit-checkin-value` form."""

    def _render_tasks_page(self, conn, req=None):
        req = req or _request("/tasks")
        resp = tasks_router.list_tasks(req, conn=conn)
        ctx = {"request": req, **resp.context}
        return tasks_router.templates.get_template("tasks_list.html").render(ctx)

    def test_plain_habit_task_has_data_cc_change_task(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate")
        body = self._render_tasks_page(conn)
        assert 'class="form-inline habit-checkin-value" data-cc-change="task" data-cc-action="checkin"' in body
        assert 'data-inline-edit data-field="value" data-min="0" data-max="999999"' in body
        assert 'type="hidden" name="value" value="0"' in body

    def test_quantity_habit_shows_target_and_today_value(self, conn):
        _seed_task(conn, "h2", tags=["Habit"], title="Water", target_per_day=8)
        today = date.today().isoformat()
        db.upsert_task_completion(conn, "h2", today, _now(), value=3)
        body = self._render_tasks_page(conn)
        assert 'type="hidden" name="value" value="3"' in body
        assert '>3</span>' in body  # the inline-edit cell's own display text
        assert 'habit-checkin-target">/ 8</span>' in body

    def test_standalone_habit_entity_form_has_data_cc_change_habit(self, conn):
        db.upsert_habit(
            conn,
            {"uid": "e1", "name": "Read", "color": "blue", "target_per_day": 1, "created_at": _now()},
        )
        body = self._render_tasks_page(conn)
        assert 'action="/habits/e1/entries"' in body
        assert 'class="form-inline habit-checkin-value" data-cc-change="habit" data-cc-action="checkin"' in body

    def test_due_column_renders_streak_text_standard_by_default(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate")
        today = date.today().isoformat()
        db.upsert_task_completion(conn, "h1", today, _now())
        body = self._render_tasks_page(conn)
        assert "1 day streak" in body

    def test_due_column_renders_playful_streak_text_when_configured(self, conn, tmp_path):
        db.set_app_meta(conn, "habit_streak_terminology", "playful")
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate")
        for i in range(8):
            db.upsert_task_completion(conn, "h1", (date.today() - timedelta(days=i)).isoformat(), _now())
        req = _request_with_app("/tasks", tmp_path / "cache.sqlite")
        body = self._render_tasks_page(conn, req=req)
        assert "This week has been full" in body


class TestHabitSettings:
    def test_defaults_to_habit(self, conn):
        assert db.get_task_habit_settings(conn)["habit_label"] == "Habit"

    def test_save_and_reload(self, conn):
        db.save_task_habit_settings(conn, "Routine")
        assert db.get_task_habit_settings(conn)["habit_label"] == "Routine"

    def test_blank_falls_back_to_habit(self, conn):
        db.save_task_habit_settings(conn, "   ")
        assert db.get_task_habit_settings(conn)["habit_label"] == "Habit"
