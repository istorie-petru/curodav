"""Habits H3 (2026-09-24, plans/ui-cleanup-2026-09.md item 14): the habit
detail modal -- clickable year grid (2026-09-25; view-only before), month calendar, day notes, "Log a
day" -- plus note storage on task_completions, date validation on the
completion endpoints, and the backup restore keeping value/note."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db, habit_view
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now():
    return datetime.now(timezone.utc).isoformat()


def _habit(conn, uid="h1", target=1):
    db.save_task_habit_settings(conn, "Habit")
    db.upsert_task(conn, {"uid": uid, "title": "Read", "description": "", "status": "active",
                          "tags": ["Habit"], "recurrence": "FREQ=DAILY", "target_per_day": target,
                          "created_at": _now()})


def _req(path="/tasks/h1"):
    return Request({"type": "http", "method": "POST", "path": path, "headers": []})


TODAY = date.today()


class TestNotes:
    def test_note_kept_by_plain_check_in_and_clearable(self, conn):
        _habit(conn)
        d = TODAY.isoformat()
        db.upsert_task_completion(conn, "h1", d, _now(), 1, "felt great")
        db.upsert_task_completion(conn, "h1", d, _now(), 2)  # +1 without a note
        assert db.get_task_completion(conn, "h1", d)["note"] == "felt great"
        db.upsert_task_completion(conn, "h1", d, _now(), 2, "")
        assert db.get_task_completion(conn, "h1", d)["note"] == ""

    def test_log_endpoint_stores_note_and_value(self, conn):
        _habit(conn, target=8)
        d = (TODAY - timedelta(days=2)).isoformat()
        tasks_router.set_task_completion("h1", _req(), completion_date=d, value="5", note="  late  ",
                                         x_requested_with="fetch", conn=conn)
        row = db.get_task_completion(conn, "h1", d)
        assert (row["value"], row["note"]) == (5, "late")

    def test_future_and_bad_dates_rejected(self, conn):
        _habit(conn)
        future = (TODAY + timedelta(days=1)).isoformat()
        for d in (future, "not-a-date"):
            resp = tasks_router.set_task_completion("h1", _req(), completion_date=d, value="1", note=None,
                                                    x_requested_with="fetch", conn=conn)
            assert resp.status_code == 400
            resp = tasks_router.toggle_task_completion("h1", d, _req(), x_requested_with="fetch", conn=conn)
            assert resp.status_code == 400
        assert db.list_task_completions(conn, "h1") == []

    def test_recent_notes_newest_first(self):
        rows = [{"due_date": "2026-09-01", "note": "a", "value": 1}, {"due_date": "2026-09-03", "note": " c ", "value": 1},
                {"due_date": "2026-09-02", "note": "", "value": 1}]
        assert [n["note"] for n in habit_view.recent_notes(rows)] == ["c", "a"]


class TestDetailModal:
    def test_renders_interactive_grid_month_and_log_form(self, conn):
        _habit(conn)
        db.upsert_task_completion(conn, "h1", TODAY.isoformat(), _now(), 1, "morning run")
        req = Request({"type": "http", "method": "GET", "path": "/tasks/h1", "headers": [], "query_string": b""})
        body = tasks_router.task_detail("h1", req, conn=conn).body.decode()
        assert 'class="heatmap-cell-form" data-modal-keep-open data-cc-change="task"' in body  # clickable (2026-09-25)
        assert "habit-month" not in body  # 2026-09-26: no month calendar
        assert "habit-log-form" not in body and "Log a day" not in body  # 2026-09-26: removed
        assert "morning run" in body  # logged notes still list


class TestBackupRestoreKeepsValueAndNote:
    def test_round_trip(self, conn):
        from src.routers import export as export_router

        _habit(conn, target=8)
        db.upsert_task_completion(conn, "h1", "2026-09-01", _now(), 5, "tired")
        payload = {"task_completions": db.list_task_completions(conn)}
        conn.execute("DELETE FROM task_completions")
        conn.commit()
        export_router.restore_backup_payload(conn, payload)
        back = db.get_task_completion(conn, "h1", "2026-09-01")
        assert (back["value"], back["note"]) == (5, "tired")


class TestSmarterHeatmap:
    """2026-09-25 (Peter): clickable heatmap, smarter per habit shape --
    an amount habit's days open the small amount popup (placeholder = the
    target) instead of toggling; a "3x a week" / "once a month" (period)
    habit gets no heatmap; Work sessions are collapsed in the view modal."""

    def _detail(self, conn, uid):
        req = Request({"type": "http", "method": "GET", "path": f"/tasks/{uid}", "headers": [], "query_string": b""})
        return tasks_router.task_detail(uid, req, conn=conn).body.decode()

    def test_amount_habit_days_are_popup_triggers(self, conn):
        _habit(conn, "w1", target=8)
        db.upsert_task(conn, {**db.get_task(conn, "w1"), "habit_unit": "glasses"})
        db.upsert_task_completion(conn, "w1", TODAY.isoformat(), _now(), 3)
        body = self._detail(conn, "w1")
        assert "heatmap-cell-form" not in body  # no one-click toggles for an amount habit
        assert 'habit-amount-trigger"' in body and 'data-url="/tasks/w1/completions"' in body
        assert f'data-date="{TODAY.isoformat()}" data-value="3"' in body
        assert 'data-target="8" data-unit="glasses"' in body

    def test_amount_level_reflects_partial_days(self, conn):
        _habit(conn, "w1", target=8)
        db.upsert_task_completion(conn, "w1", TODAY.isoformat(), _now(), 2)
        body = self._detail(conn, "w1")
        cell = body[body.index(f'data-date="{TODAY.isoformat()}" data-value="2"') - 200:][:220]
        assert "level-4" not in cell  # 2 of 8 isn't a full day

    @pytest.mark.parametrize("rrule,per", [("FREQ=WEEKLY", 3), ("FREQ=MONTHLY", None)])
    def test_period_habits_have_no_heatmap(self, conn, rrule, per):
        _habit(conn, "p1")
        db.upsert_task(conn, {**db.get_task(conn, "p1"), "recurrence": rrule, "habits_per_period": per})
        body = self._detail(conn, "p1")
        assert 'class="heatmap' not in body
        # 2026-09-26: the week / month grid instead
        assert f'class="habit-periods habit-periods-{"week" if rrule == "FREQ=WEEKLY" else "month"}"' in body

    def test_work_sessions_hidden_in_view_when_empty_and_present_in_edit(self, conn):
        """2026-09-26 (Peter): no Work sessions section in the view modal
        while there are none -- the edit modal is where they're added."""
        _habit(conn, "h1")
        body = self._detail(conn, "h1")
        assert "habit-work-sessions" not in body
        req = Request({"type": "http", "method": "GET", "path": "/tasks/h1/edit", "headers": [], "query_string": b""})
        form = tasks_router.edit_task_form("h1", req, conn=conn).body.decode()
        assert 'action="/tasks/h1/work-allocations"' in form


class TestPageStripAmount:
    def test_strip_uses_popup_for_amount_habits(self, conn):
        from src.routers import habits as habits_router

        _habit(conn, "w1", target=8)
        _habit(conn, "d1")
        req = Request({"type": "http", "method": "GET", "path": "/habits", "headers": [], "query_string": b""})
        body = habits_router.habits_page(req, conn=conn).body.decode()
        assert body.count('class="habit-day habit-amount-trigger') == date.today().weekday() + 1  # w1's strip
        assert body.count('class="form-inline habit-action habit-day-form"') == date.today().weekday() + 1  # d1's strip


class TestViewModal20260926:
    """2026-09-26 (Peter, second pass): no month calendar, no insights, no
    "Log a relapse", no Work sessions while empty; the habit's colour and
    icon on the cover; a period habit's history is a week / month grid."""

    def _detail(self, conn, uid):
        req = Request({"type": "http", "method": "GET", "path": f"/tasks/{uid}", "headers": [], "query_string": b""})
        return tasks_router.task_detail(uid, req, conn=conn).body.decode()

    def test_no_month_calendar_or_insights(self, conn):
        _habit(conn, "h1")
        for i in range(30):
            db.upsert_task_completion(conn, "h1", (TODAY - timedelta(days=i)).isoformat(), _now(), 1)
        body = self._detail(conn, "h1")
        assert "habit-month" not in body and "habit-insights" not in body and "habit-bars" not in body

    def test_avoid_has_no_log_form(self, conn):
        _habit(conn, "a1")
        db.upsert_task(conn, {**db.get_task(conn, "a1"), "habit_kind": "avoid"})
        body = self._detail(conn, "a1")
        assert "Log a relapse" not in body and "habit-log-form" not in body

    def test_colour_and_icon(self, conn):
        _habit(conn, "h1")
        db.set_task_habit_look(conn, "h1", "moon", "purple")
        body = self._detail(conn, "h1")
        assert "var(--cal-accent-purple)" in body and 'href="#icon-moon"' in body
        assert "habit-year-heatmap habit-c-purple" in body

    def test_no_pause_section_and_readable_schedule(self, conn):
        _habit(conn, "h1")
        db.upsert_task(conn, {**db.get_task(conn, "h1"), "recurrence": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"})
        body = self._detail(conn, "h1")
        assert "habit-pause-form" not in body
        assert "FREQ=" not in body
        assert "Mon, Tue, Wed, Thu, Fri" in body


class TestPeriodGrid:
    def test_weeks(self):
        from src import habit_schedule

        today = date(2026, 9, 26)  # a Saturday
        sched = habit_schedule.parse_schedule("FREQ=WEEKLY", 3)
        entries = {"2026-09-21": 1, "2026-09-22": 1, "2026-09-23": 1, "2026-09-15": 1}
        grid = habit_view.period_grid(entries, sched, today)
        assert grid["unit"] == "week" and len(grid["cells"]) == 52
        assert (grid["cells"][-1]["count"], grid["cells"][-1]["done"], grid["cells"][-1]["is_current"]) == (3, True, True)
        assert (grid["cells"][-2]["count"], grid["cells"][-2]["partial"]) == (1, True)
        # Sunday-first weeks: Sep 20 (Sun) .. Sep 26
        grid = habit_view.period_grid({"2026-09-20": 1}, sched, today, week_start="sunday")
        assert grid["cells"][-1]["count"] == 1

    def test_months(self):
        from src import habit_schedule

        grid = habit_view.period_grid({"2026-09-02": 1}, habit_schedule.parse_schedule("FREQ=MONTHLY", None), date(2026, 9, 26))
        assert grid["unit"] == "month" and len(grid["cells"]) == 12
        assert grid["cells"][-1]["label"] == "Sep" and grid["cells"][-1]["done"]
