"""Habits H5 (2026-09-24, plans/ui-cleanup-2026-09.md item 14): amount
units and "avoid" habits. An avoid habit logs relapses (same completion
endpoints); its streak counts clean days; it's never "to do"."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db, habit_schedule, habit_view
from src.routers import habits as habits_router
from src.routers import tasks as tasks_router

T = date(2026, 9, 24)


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now():
    return datetime.now(timezone.utc).isoformat()


def _habit(conn, uid, title, **extra):
    db.save_task_habit_settings(conn, "Habit")
    row = {"uid": uid, "title": title, "description": "", "status": "active", "tags": ["Habit"],
           "recurrence": "FREQ=DAILY", "created_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()}
    row.update(extra)
    db.upsert_task(conn, row)


def _req(path="/habits"):
    return Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b""})


class TestAvoidStats:
    def test_clean_days_since_last_relapse(self):
        s = habit_schedule.habit_stats({"2026-09-20": 1}, "FREQ=DAILY", today=T, created=date(2026, 9, 10), kind="avoid")
        assert (s["current"], s["longest"], s["due_today"], s["relapsed_today"]) == (4, 10, False, False)
        assert s["rate"] == pytest.approx(14 / 15)

    def test_relapse_today_resets(self):
        s = habit_schedule.habit_stats({"2026-09-24": 1}, "FREQ=DAILY", today=T, created=date(2026, 9, 20), kind="avoid")
        assert (s["current"], s["relapsed_today"]) == (0, True)

    def test_never_relapsed(self):
        s = habit_schedule.habit_stats({}, "FREQ=WEEKLY;BYDAY=MO", today=T, created=date(2026, 9, 20), kind="avoid")
        assert (s["current"], s["longest"], s["rate"]) == (5, 5, 1.0)


class TestFormFields:
    @pytest.mark.parametrize("raw,expected", [("avoid", "avoid"), ("AVOID ", "avoid"), ("build", None), ("", None), ("x", None)])
    def test_kind(self, raw, expected):
        assert tasks_router._habit_kind_value(raw) == expected

    def test_unit_trimmed_and_capped(self):
        assert tasks_router._habit_unit_value("  glasses ") == "glasses"
        assert tasks_router._habit_unit_value("") is None
        assert len(tasks_router._habit_unit_value("x" * 50)) == 24

    def test_create_and_plain_form_preserves(self, conn):
        db.save_task_habit_settings(conn, "Habit")
        tasks_router.create_task(title="No sugar", description="", due_at="", status="active", tags="",
                                 tags_labels=["Habit"], recurrence="FREQ=DAILY", target_per_day="1",
                                 habit_kind="avoid", habit_unit="", conn=conn)
        t = next(t for t in db.list_habit_tasks(conn) if t["title"] == "No sugar")
        assert t["habit_kind"] == "avoid"
        tasks_router.update_task(t["uid"], title="No sugar!", description="", due_at="", start_at="", status="active",
                                 tags="", tags_labels=["Habit"], recurrence="FREQ=DAILY", target_per_day="1", conn=conn)
        assert db.get_task(conn, t["uid"])["habit_kind"] == "avoid"


class TestRendering:
    def test_avoid_row(self, conn):
        _habit(conn, "a1", "No smoking", habit_kind="avoid")
        db.upsert_task_completion(conn, "a1", (date.today() - timedelta(days=2)).isoformat(), _now())
        resp = habits_router.habits_page(_req(), conn=conn)
        assert [h["uid"] for h in resp.context["on_track"]] == ["a1"]  # never "to do"
        body = resp.body.decode()
        assert "habit-check-btn habit-check-avoid" in body
        assert "2 days clean" in body
        assert "Avoid" in body
        assert body.count("habit-day is-relapse") == 1

    def test_amount_unit(self, conn):
        _habit(conn, "w1", "Water", target_per_day=8, habit_unit="glasses")
        body = habits_router.habits_page(_req(), conn=conn).body.decode()
        assert "8 glasses a day" in body
        detail = tasks_router.task_detail("w1", _req("/tasks/w1"), conn=conn).body.decode()
        assert "Amount (glasses)" in detail

    def test_avoid_detail(self, conn):
        _habit(conn, "a1", "No smoking", habit_kind="avoid")
        body = tasks_router.task_detail("a1", _req("/tasks/a1"), conn=conn).body.decode()
        assert "Log a relapse" in body
        assert "heatmap-avoid" in body
        assert "habit-month detail-plain-section is-avoid" in body
        assert habit_view.cadence_label({"habit_kind": "avoid", "recurrence": "FREQ=DAILY"}) == "Avoid"

    def test_form_preselects(self, conn):
        _habit(conn, "a1", "No smoking", habit_kind="avoid", habit_unit="cigs")
        body = tasks_router.edit_task_form("a1", _req("/tasks/a1/edit"), conn=conn).body.decode()
        assert '<option value="avoid" selected>' in body
        assert 'value="cigs"' in body
