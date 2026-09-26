"""Habits H8 (2026-09-24, plans/ui-cleanup-2026-09.md item 14): insights --
a Loop-style strength score, logged days per month, and the usual
check-in hour (same-day check-ins only, server local time)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db, habit_schedule, habit_view
from src.routers import habits as habits_router
from src.routers import tasks as tasks_router

T = date(2026, 9, 24)


def _daily(n, today=T, skip=()):
    return {(today - timedelta(days=i)).isoformat(): 1 for i in range(n) if i not in skip}


class TestStrength:
    def test_builds_up_and_dents(self):
        full = habit_schedule.habit_stats(_daily(120), "FREQ=DAILY", today=T)["strength"]
        dented = habit_schedule.habit_stats(_daily(120, skip={3}), "FREQ=DAILY", today=T)["strength"]
        young = habit_schedule.habit_stats(_daily(14), "FREQ=DAILY", today=T, created=T - timedelta(days=13))["strength"]
        assert full == 100
        assert 85 < dented < 100  # one miss dents, doesn't zero (the streak does)
        assert 40 < young < 60
        assert habit_schedule.habit_stats(_daily(120, skip={3}), "FREQ=DAILY", today=T)["current"] == 3

    def test_none_before_anything_counts_and_avoid(self):
        assert habit_schedule.habit_stats({}, "FREQ=DAILY", today=T)["strength"] is None
        clean = habit_schedule.habit_stats({}, "FREQ=DAILY", today=T, created=T - timedelta(days=60), kind="avoid")
        assert clean["strength"] > 90

    def test_weekly_uses_slower_decay(self):
        weekly = {(T - timedelta(weeks=i)).isoformat(): 1 for i in range(10)}
        s = habit_schedule.habit_stats(weekly, "FREQ=WEEKLY", today=T)["strength"]
        assert 60 < s < 90


class TestInsights:
    def test_months_and_hours(self):
        rows = []
        for i in range(6):  # six same-day check-ins at 07:xx local
            d = T - timedelta(days=i)
            stamp = datetime(d.year, d.month, d.day, 7, 30).astimezone()
            rows.append({"due_date": d.isoformat(), "completed_at": stamp.isoformat(), "value": 1})
        # a backfilled day (logged later) must not count for the hour
        rows.append({"due_date": "2026-08-01", "completed_at": datetime(2026, 9, 20, 22, 0).astimezone().isoformat(), "value": 1})
        rows.append({"due_date": "2026-08-02", "completed_at": "", "value": 0})  # not logged
        ins = habit_view.insights(rows, today=T)
        months = {m["key"]: m["count"] for m in ins["months"]}
        assert len(ins["months"]) == 12 and ins["months"][-1]["key"] == "2026-09"
        assert months["2026-09"] == 6 and months["2026-08"] == 1
        assert ins["same_day"] == 6 and ins["top_hour"] == 7
        assert ins["hours"][22]["count"] == 0

    def test_hours_hidden_below_five(self):
        rows = [{"due_date": T.isoformat(), "completed_at": datetime(T.year, T.month, T.day, 9).astimezone().isoformat(), "value": 1}]
        assert habit_view.insights(rows, today=T)["hours"] is None


class TestHabitsPagePanel:
    """2026-09-26 (Peter): insights moved from the view modal to the Habits
    page row's expandable panel; strength stays a modal stat."""
    def test_renders_strength_and_bars(self, tmp_path):
        with db.connect(tmp_path / "cache.sqlite") as conn:
            db.save_task_habit_settings(conn, "Habit")
            db.upsert_task(conn, {"uid": "h1", "title": "Read", "description": "", "status": "active",
                                  "tags": ["Habit"], "recurrence": "FREQ=DAILY",
                                  "created_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()})
            today = date.today()
            # 2026-09-26: insights show from 14 logged days (INSIGHTS_MIN_DAYS).
            for i in range(14):
                d = today - timedelta(days=i)
                db.upsert_task_completion(conn, "h1", d.isoformat(),
                                          datetime(d.year, d.month, d.day, 8).astimezone().isoformat())
            req = Request({"type": "http", "method": "GET", "path": "/tasks/h1", "headers": [], "query_string": b""})
            detail = tasks_router.task_detail("h1", req, conn=conn).body.decode()
            body = habits_router.habits_page(req, conn=conn).body.decode()
        assert ">Strength<" in detail and "habit-bars" not in detail
        assert 'class="habit-panel" id="habit-panel-h1" hidden' in body
        assert 'class="habit-bars habit-bars-months"' in body
        assert "usually around 08:00" in body
        assert 'data-style="height:' in body and 'style="height' not in body.replace('data-style="height', "")
