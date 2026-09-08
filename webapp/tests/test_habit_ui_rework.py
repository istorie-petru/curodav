"""Tests for the 2026-08-29 Habits UI rework (direct feedback):

  1. The Habits group's row (_habit_row.html): the streak's `repeat` icon
     is gone, and the Scheduled/Due columns are swapped back so Scheduled
     shows the streak (plain text) and Due shows the habit's cadence
     ("Daily"/"Weekly"/...) instead of a second streak readout.
  2. Recurrence displays as "Daily"/"Weekly"/etc, never the raw
     "FREQ=DAILY" a task's `recurrence` column stores.
  3. A habit-tracked task's edit/view modals are dedicated templates
     (habit_task_form.html/habit_task_detail.html) with no label dropdown,
     status dropdown, due date, or start date -- and the edit modal gained
     a Work sessions card; the view modal gained a non-interactive
     heatmap.
  4. The standalone Habit entity's edit modal (habit_form.html) dropped
     its Labels chip multiselect (tags are preserved via hidden inputs,
     not user-editable there anymore), and its view modal's heatmap
     (_habit_detail_body.html) is non-interactive too.
  5. A habit-tracked recurring task's work sessions persist on the Week
     view's "Unscheduled work" panel until its own period's requirement
     is met (daily: 7 dated sessions in the displayed week; weekly/
     monthly: just 1) -- db.habit_work_sessions_status and
     routers/calendar.py::week_view.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from starlette.requests import Request

from src import db, habit_heatmap
from src.routers import calendar as calendar_router
from src.routers import tasks as tasks_router

_MONDAY = "2026-08-17"  # a real Monday


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid, tags=None, **overrides):
    row = {
        "uid": uid,
        "title": uid,
        "description": "",
        "status": "active",
        "tags": tags or [],
        "target_per_day": 1,
        "created_at": _now(),
    }
    row.update(overrides)
    db.upsert_task(conn, row)
    return db.get_task(conn, uid)


def _request(path, query_string=b""):
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


class TestRecurrenceLabel:
    def test_daily(self):
        assert habit_heatmap.recurrence_label("FREQ=DAILY") == "Daily"

    def test_weekly_with_interval_is_still_weekly(self):
        assert habit_heatmap.recurrence_label("FREQ=WEEKLY;INTERVAL=2") == "Weekly"

    def test_monthly(self):
        assert habit_heatmap.recurrence_label("FREQ=MONTHLY") == "Monthly"

    def test_yearly(self):
        assert habit_heatmap.recurrence_label("FREQ=YEARLY") == "Yearly"

    def test_no_freq_at_all_is_custom(self):
        assert habit_heatmap.recurrence_label("COUNT=5") == "Custom"

    def test_interval_qualifier_still_resolves_to_its_freq_bucket(self):
        assert habit_heatmap.recurrence_label("FREQ=DAILY;BYDAY=MO,WE") == "Daily"

    def test_blank_is_custom(self):
        assert habit_heatmap.recurrence_label("") == "Custom"
        assert habit_heatmap.recurrence_label(None) == "Custom"


class TestHabitRowColumns:
    def _render_tasks_page(self, conn):
        req = _request("/tasks")
        resp = tasks_router.list_tasks(req, conn=conn)
        ctx = {"request": req, **resp.context}
        return tasks_router.templates.get_template("tasks_list.html").render(ctx)

    def test_no_repeat_icon_next_to_streak(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=DAILY")
        body = self._render_tasks_page(conn)
        assert "#icon-repeat" not in body

    def test_due_column_shows_recurrence_label_not_raw_rrule(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=WEEKLY")
        body = self._render_tasks_page(conn)
        assert "FREQ=WEEKLY" not in body
        assert "Weekly" in body

    def test_entity_habit_recurrence_label_is_daily(self, conn):
        db.upsert_habit(conn, {"uid": "e1", "name": "Read", "color": "blue", "target_per_day": 1, "created_at": _now()})
        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        item = next(g for g in resp.context["groups"] if g["kind"] == "habits")["habit_items"][0]
        assert item["recurrence_label"] == "Daily"

    def test_streak_still_present_in_scheduled_column(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=DAILY")
        today = date.today().isoformat()
        db.upsert_task_completion(conn, "h1", today, _now())
        body = self._render_tasks_page(conn)
        assert "1 day streak" in body


class TestHabitTaskEditModal:
    def test_uses_dedicated_template_no_label_status_due_start(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=DAILY")
        resp = tasks_router.edit_task_form("h1", _request("/tasks/h1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'name="due_at"' not in body
        assert 'name="start_at"' not in body
        assert 'name="status"' not in body
        assert 'data-ms-label="labels"' not in body
        assert 'data-ms-label="status"' not in body
        # still has the habit-relevant fields
        assert 'name="recurrence"' in body
        assert 'name="target_per_day"' in body

    def test_has_work_sessions_card(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=DAILY")
        resp = tasks_router.edit_task_form("h1", _request("/tasks/h1/edit"), conn=conn)
        body = resp.body.decode()
        assert "Work sessions" in body
        assert "/tasks/h1/work-allocations" in body

    def test_plain_task_still_uses_generic_form(self, conn):
        _seed_task(conn, "p1", title="Plain task")
        resp = tasks_router.edit_task_form("p1", _request("/tasks/p1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'name="due_at"' in body
        assert 'name="status"' in body


class TestHabitTaskViewModal:
    def test_uses_dedicated_template_with_heatmap(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=DAILY")
        resp = tasks_router.task_detail("h1", _request("/tasks/h1"), conn=conn)
        body = resp.body.decode()
        assert "heatmap-grid" in body
        assert "Daily" in body

    def test_heatmap_is_not_interactive(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=DAILY")
        resp = tasks_router.task_detail("h1", _request("/tasks/h1"), conn=conn)
        body = resp.body.decode()
        assert "heatmap-cell-form" not in body

    def test_no_status_due_start_meta(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=DAILY")
        resp = tasks_router.task_detail("h1", _request("/tasks/h1"), conn=conn)
        body = resp.body.decode()
        assert "detail-meta-label\">Status" not in body
        assert "detail-meta-label\">Due" not in body
        assert "detail-meta-label\">Start" not in body

    def test_plain_recurring_task_still_uses_generic_detail(self, conn):
        _seed_task(conn, "p1", title="Plain recurring", recurrence="FREQ=DAILY")
        resp = tasks_router.task_detail("p1", _request("/tasks/p1"), conn=conn)
        body = resp.body.decode()
        assert "detail-meta-label\">Status" in body


class TestEntityHabitFormAndDetail:
    def test_edit_form_has_no_labels_multiselect(self, conn):
        db.upsert_habit(conn, {"uid": "e1", "name": "Read", "color": "blue", "target_per_day": 1, "tags": ["Books"], "created_at": _now()})
        from src.routers import habits as habits_router

        resp = habits_router.edit_habit_form("e1", _request("/habits/e1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'data-ms-label="labels"' not in body
        # existing tags are preserved via hidden inputs, not shown as a picker
        assert '<input type="hidden" name="tags_labels" value="Books">' in body

    def test_edit_preserves_tags_without_the_field_being_editable(self, conn):
        from src.routers import habits as habits_router

        db.upsert_habit(conn, {"uid": "e1", "name": "Read", "color": "blue", "target_per_day": 1, "tags": ["Books"], "created_at": _now()})
        habits_router.edit_habit(
            "e1",
            name="Read",
            description="",
            color="blue",
            icon="",
            target_per_day="1",
            tags="",
            tags_labels=["Books"],
            project_uid="",
            conn=conn,
        )
        assert db.get_habit(conn, "e1")["tags"] == ["Books"]

    def test_detail_heatmap_is_not_interactive(self, conn):
        db.upsert_habit(conn, {"uid": "e1", "name": "Read", "color": "blue", "target_per_day": 1, "created_at": _now()})
        from src.routers import habits as habits_router

        resp = habits_router.habit_detail("e1", _request("/habits/e1"), conn=conn)
        body = resp.body.decode()
        assert "heatmap-cell-form" not in body
        assert "heatmap-grid" in body


class TestHabitWorkSessionsStatus:
    def test_daily_habit_requires_seven(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], recurrence="FREQ=DAILY")
        info = db.habit_work_sessions_status(conn, "h1", "FREQ=DAILY", "2026-08-17", "2026-08-23")
        assert info["required"] == 7
        assert info["needed"] == 7

    def test_weekly_habit_requires_one(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], recurrence="FREQ=WEEKLY")
        info = db.habit_work_sessions_status(conn, "h1", "FREQ=WEEKLY", "2026-08-17", "2026-08-23")
        assert info["required"] == 1
        assert info["needed"] == 1

    def test_dated_session_in_period_counts_toward_requirement(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], recurrence="FREQ=DAILY")
        db.create_work_allocation(conn, "h1", "2026-08-18T09:00:00", "2026-08-18T10:00:00")
        info = db.habit_work_sessions_status(conn, "h1", "FREQ=DAILY", "2026-08-17", "2026-08-23")
        assert info["dated_in_period"] == 1
        assert info["needed"] == 6

    def test_dated_session_outside_period_does_not_count(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], recurrence="FREQ=WEEKLY")
        db.create_work_allocation(conn, "h1", "2026-08-01T09:00:00", "2026-08-01T10:00:00")
        info = db.habit_work_sessions_status(conn, "h1", "FREQ=WEEKLY", "2026-08-17", "2026-08-23")
        assert info["needed"] == 1

    def test_undated_placeholder_counts_toward_requirement(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], recurrence="FREQ=WEEKLY")
        db.create_work_allocation(conn, "h1")  # undated placeholder
        info = db.habit_work_sessions_status(conn, "h1", "FREQ=WEEKLY", "2026-08-17", "2026-08-23")
        assert info["needed"] == 0

    def test_fully_covered_daily_habit_needs_nothing_more(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], recurrence="FREQ=DAILY")
        for day in range(17, 24):
            db.create_work_allocation(conn, "h1", f"2026-08-{day:02d}T09:00:00", f"2026-08-{day:02d}T10:00:00")
        info = db.habit_work_sessions_status(conn, "h1", "FREQ=DAILY", "2026-08-17", "2026-08-23")
        assert info["needed"] == 0


class TestHabitWorkSessionsOnWeekView:
    def test_habit_task_appears_on_unscheduled_panel(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=DAILY")
        body = calendar_router.week_view(
            _request("/calendar/week", query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "Meditate" in body

    def test_daily_habit_persists_until_full_week_covered(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=DAILY")
        # Only 6 of the 7 days in the displayed week are scheduled.
        for day in range(17, 23):
            db.create_work_allocation(conn, "h1", f"2026-08-{day:02d}T09:00:00", f"2026-08-{day:02d}T10:00:00")
        body = calendar_router.week_view(
            _request("/calendar/week", query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "Meditate" in body

    def test_daily_habit_drops_off_once_full_week_covered(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Meditate", recurrence="FREQ=DAILY")
        for day in range(17, 24):
            db.create_work_allocation(conn, "h1", f"2026-08-{day:02d}T09:00:00", f"2026-08-{day:02d}T10:00:00")
        body = calendar_router.week_view(
            _request("/calendar/week", query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        # The scheduled sessions still render as real calendar blocks --
        # only the Unscheduled work panel's own item for this task drops.
        assert 'data-task-title="Meditate"' not in body

    def test_weekly_habit_drops_off_after_one_session_this_week(self, conn):
        _seed_task(conn, "h1", tags=["Habit"], title="Water plants", recurrence="FREQ=WEEKLY")
        db.create_work_allocation(conn, "h1", f"{_MONDAY}T09:00:00", f"{_MONDAY}T10:00:00")
        body = calendar_router.week_view(
            _request("/calendar/week", query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert 'data-task-title="Water plants"' not in body

    def test_plain_non_habit_recurring_task_uses_generic_rule(self, conn):
        """A plain recurring task (no habit label) isn't subject to the
        habit "N sessions this period" rule -- one dated session anywhere
        is enough to drop it off, same as before this slice."""
        _seed_task(conn, "p1", title="Standup", recurrence="FREQ=DAILY")
        db.create_work_allocation(conn, "p1", f"{_MONDAY}T09:00:00", f"{_MONDAY}T10:00:00")
        body = calendar_router.week_view(
            _request("/calendar/week", query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert 'data-task-title="Standup"' not in body
