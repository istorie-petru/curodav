"""Habits H1 (2026-09-24, plans/ui-cleanup-2026-09.md item 14):
schedule-aware streaks. Before this, streaks walked calendar days, so a
weekly habit kept four weeks running read (current 0, best 1) and a fully
kept Mon/Wed/Fri habit read (1, 1)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src import db, habit_schedule, habit_view
from src.habit_heatmap import streak_text
from src.routers import tasks as tasks_router

THU = date(2026, 9, 24)  # a Thursday


def _log(*days):
    return {d: 1 for d in days}


def stats(entries, rrule, **kw):
    kw.setdefault("today", THU)
    return habit_schedule.habit_stats(entries, rrule, **kw)


class TestReportedBug:
    def test_weekly_habit_kept_four_weeks(self):
        s = stats(_log("2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22"), "FREQ=WEEKLY")
        assert (s["current"], s["longest"], s["unit"]) == (4, 4, "week")

    def test_mon_wed_fri_all_kept(self):
        s = stats(_log("2026-09-14", "2026-09-16", "2026-09-18", "2026-09-21", "2026-09-23"),
                  "FREQ=WEEKLY;BYDAY=MO,WE,FR")
        assert (s["current"], s["longest"], s["rate"]) == (5, 5, 1.0)


class TestWeekdays:
    def test_late_log_counts_for_its_window(self):
        # Monday's habit done on Tuesday still keeps Monday's window.
        s = stats(_log("2026-09-14", "2026-09-16", "2026-09-18", "2026-09-22"), "FREQ=WEEKLY;BYDAY=MO,WE,FR")
        assert s["current"] == 4

    def test_missed_window_breaks(self):
        s = stats(_log("2026-09-14", "2026-09-18"), "FREQ=WEEKLY;BYDAY=MO,WE,FR")
        assert (s["current"], s["longest"], s["rate"]) == (0, 1, 0.5)

    def test_open_window_is_pending_not_missed(self):
        # Wednesday's window is still open on Thursday.
        s = stats(_log("2026-09-21"), "FREQ=WEEKLY;BYDAY=MO,WE,FR")
        assert s["current"] == 1
        assert s["due_today"] is True

    def test_excluded_due_day_is_neutral(self):
        s = stats(_log("2026-09-14", "2026-09-18"), "FREQ=WEEKLY;BYDAY=MO,WE,FR",
                  excluded_dates={"2026-09-16"})
        assert s["longest"] == 2


class TestPeriod:
    def test_three_times_a_week(self):
        s = stats(_log("2026-09-15", "2026-09-17", "2026-09-19", "2026-09-22", "2026-09-23"),
                  "FREQ=WEEKLY", per_period=3)
        assert (s["current"], s["period_done"], s["period_target"], s["due_today"]) == (1, 2, 3, True)

    def test_short_week_breaks(self):
        s = stats(_log("2026-09-08", "2026-09-09", "2026-09-10", "2026-09-15", "2026-09-22", "2026-09-23",
                       "2026-09-24"), "FREQ=WEEKLY", per_period=3)
        assert (s["current"], s["longest"]) == (1, 1)

    def test_monthly(self):
        s = stats(_log("2026-07-02", "2026-08-30", "2026-09-01"), "FREQ=MONTHLY")
        assert (s["current"], s["unit"]) == (3, "month")


class TestEveryNDays:
    def test_daily_matches_old_behavior(self):
        s = stats(_log("2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23"), "FREQ=DAILY")
        assert (s["current"], s["due_today"]) == (4, True)

    def test_every_two_days(self):
        s = stats(_log("2026-09-18", "2026-09-20", "2026-09-22"), "FREQ=DAILY;INTERVAL=2",
                  created=date(2026, 9, 18))
        assert s["current"] == 3

    def test_empty(self):
        s = stats({}, "FREQ=DAILY")
        assert (s["current"], s["longest"], s["rate"]) == (0, 0, None)


class TestLabelsAndText:
    @pytest.mark.parametrize(
        "rrule,per,label",
        [
            ("FREQ=DAILY", None, "Daily"),
            ("FREQ=DAILY;INTERVAL=3", None, "Every 3 days"),
            ("FREQ=WEEKLY;BYDAY=MO,WE,FR", None, "Mon, Wed, Fri"),
            ("FREQ=WEEKLY", None, "Weekly"),
            ("FREQ=WEEKLY", 3, "3x a week"),
            ("FREQ=MONTHLY", 10, "10x a month"),
            ("FREQ=WEEKLY;INTERVAL=2", None, "Once every 2 weeks"),
        ],
    )
    def test_cadence_label(self, rrule, per, label):
        assert habit_view.cadence_label({"recurrence": rrule, "habits_per_period": per}) == label

    def test_streak_text_units(self):
        assert streak_text(3, unit="week") == "3 weeks streak"
        assert streak_text(1, playful=True, unit="month") == "1 month streak"
        assert streak_text(3) == "3 days streak"


class TestTimesPerPeriodField:
    @pytest.mark.parametrize("raw,expected", [("", None), ("1", None), ("3", 3), ("40", 31), ("x", None)])
    def test_value_parsing(self, raw, expected):
        assert tasks_router._habits_per_period_value(raw) == expected

    def test_round_trip_and_plain_form_preserves(self, tmp_path):
        with db.connect(tmp_path / "cache.sqlite") as conn:
            now = datetime.now(timezone.utc).isoformat()
            db.upsert_task(conn, {"uid": "h1", "title": "Run", "description": "", "status": "active",
                                  "tags": ["Habit"], "recurrence": "FREQ=WEEKLY", "created_at": now})
            tasks_router.update_task("h1", title="Run", description="", due_at="", start_at="", status="active",
                                     tags="", tags_labels=["Habit"], recurrence="FREQ=WEEKLY", target_per_day="1",
                                     habits_per_period="3", conn=conn)
            assert db.get_task(conn, "h1")["habits_per_period"] == 3
            # A form without the field (plain task form) keeps the value.
            tasks_router.update_task("h1", title="Run", description="", due_at="", start_at="", status="active",
                                     tags="", tags_labels=["Habit"], recurrence="FREQ=WEEKLY", target_per_day="1",
                                     conn=conn)
            assert db.get_task(conn, "h1")["habits_per_period"] == 3
