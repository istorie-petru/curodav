"""Habits H7 (2026-09-24, plans/ui-cleanup-2026-09.md item 14): habits in
the Agenda widget (a "habits" Show option, on by default) and in the
calendar day view (habits scheduled that day, checkable unless future)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db, habit_schedule, habit_view
from src.routers import calendar as calendar_router
from src.routers import dashboard as dashboard_router

TODAY = date.today()


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now():
    return datetime.now(timezone.utc).isoformat()


def _habit(conn, uid, title, recurrence="FREQ=DAILY", **extra):
    db.save_task_habit_settings(conn, "Habit")
    row = {"uid": uid, "title": title, "description": "", "status": "active", "tags": ["Habit"],
           "recurrence": recurrence, "created_at": "2026-01-05T00:00:00+00:00"}
    row.update(extra)
    db.upsert_task(conn, row)


def _req(path="/"):
    return Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b""})


class TestIsDueOn:
    def test_kinds(self):
        mwf = habit_schedule.parse_schedule("FREQ=WEEKLY;BYDAY=MO,WE,FR")
        assert habit_schedule.is_due_on(mwf, date(2026, 9, 21)) and not habit_schedule.is_due_on(mwf, date(2026, 9, 22))
        every2 = habit_schedule.parse_schedule("FREQ=DAILY;INTERVAL=2", anchor=date(2026, 9, 20))
        assert habit_schedule.is_due_on(every2, date(2026, 9, 24)) and not habit_schedule.is_due_on(every2, date(2026, 9, 23))
        assert habit_schedule.is_due_on(habit_schedule.parse_schedule("FREQ=WEEKLY", 3), date(2026, 9, 23))


class TestAgenda:
    def test_default_show_includes_habits(self, conn):
        _habit(conn, "h1", "Read")
        _habit(conn, "h2", "Stretch")
        _habit(conn, "a1", "No sugar", habit_kind="avoid")
        db.upsert_task_completion(conn, "h2", TODAY.isoformat(), _now())
        data = dashboard_router._render_agenda(conn, {"range": "today"})
        assert [h["uid"] for h in data["habits"]] == ["h1"]  # done + avoid excluded

    def test_saved_show_without_habits_hides_them(self, conn):
        _habit(conn, "h1", "Read")
        data = dashboard_router._render_agenda(conn, {"range": "today", "show": ["tasks", "events"]})
        assert data["habits"] == []

    def test_renders_one_tap_rows(self, conn):
        _habit(conn, "h1", "Read")
        _habit(conn, "w1", "Water", target_per_day=8)
        data = dashboard_router._render_agenda(conn, {"range": "today"})
        html = dashboard_router.templates.env.get_template("_widget_agenda.html").render(request=_req(), data=data)
        assert f'action="/tasks/h1/completion/{TODAY.isoformat()}/toggle" class="form-inline habit-action"' in html
        assert 'action="/tasks/w1/completions" class="form-inline habit-action"' in html
        assert "Nothing to show." not in html

    def test_builder_offers_habits(self):
        src = open(dashboard_router.templates.env.loader.searchpath[0] + "/_widget_builder_fields.html").read()
        assert "{'uid': 'habits', 'name': 'Habits'}" in src


class TestDayView:
    def test_scheduled_habits_only(self, conn):
        monday = TODAY - timedelta(days=TODAY.weekday())
        _habit(conn, "d1", "Daily")
        _habit(conn, "m1", "Mondays", recurrence="FREQ=WEEKLY;BYDAY=MO")
        _habit(conn, "a1", "Avoid", habit_kind="avoid")
        uids = [h["uid"] for h in habit_view.habits_for_day(conn, monday)]
        assert sorted(uids) == ["d1", "m1"]
        tuesday = monday + timedelta(days=1)
        assert [h["uid"] for h in habit_view.habits_for_day(conn, tuesday, today=max(tuesday, TODAY))] == ["d1"]

    def test_future_not_checkable_and_paused_hidden(self, conn):
        _habit(conn, "d1", "Daily")
        future = TODAY + timedelta(days=2)
        (h,) = habit_view.habits_for_day(conn, future)
        assert h["is_future"] is True
        db.add_habit_pause(conn, "p1", "d1", TODAY.isoformat(), TODAY.isoformat(), _now())
        assert habit_view.habits_for_day(conn, TODAY) == []

    def test_day_grid_renders_forms(self, conn):
        _habit(conn, "d1", "Daily")
        db.upsert_task_completion(conn, "d1", TODAY.isoformat(), _now())
        body = calendar_router.day_view(TODAY.isoformat(), _req(f"/calendar/day/{TODAY}"), conn=conn).body.decode()
        assert f'action="/tasks/d1/completion/{TODAY.isoformat()}/toggle" class="form-inline habit-action allday-habit-form"' in body
        assert "allday-task allday-habit is-done" in body
        assert "habit_actions.js" in body
