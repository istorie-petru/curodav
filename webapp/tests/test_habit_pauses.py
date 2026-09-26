"""Habits H6 (2026-09-24, plans/ui-cleanup-2026-09.md item 14): vacation /
pause. A pause covers one habit or all; paused days are neutral for
streaks; a habit paused today isn't "to do"."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db, habit_schedule, habit_view
from src.routers import habits as habits_router
from src.routers import tasks as tasks_router

T = date(2026, 9, 24)
TODAY = date.today()


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now():
    return datetime.now(timezone.utc).isoformat()


def _habit(conn, uid, title="Read", **extra):
    db.save_task_habit_settings(conn, "Habit")
    row = {"uid": uid, "title": title, "description": "", "status": "active", "tags": ["Habit"],
           "recurrence": "FREQ=DAILY", "created_at": _now()}
    row.update(extra)
    db.upsert_task(conn, row)


def _req(path="/habits"):
    return Request({"type": "http", "method": "POST", "path": path, "headers": [], "query_string": b""})


def _days(start, n):
    return {(start + timedelta(days=i)).isoformat() for i in range(n)}


class TestEngine:
    def test_vacation_keeps_daily_streak(self):
        e = {d: 1 for d in _days(date(2026, 9, 10), 3) | _days(date(2026, 9, 20), 4)}
        paused = _days(date(2026, 9, 13), 7)
        assert habit_schedule.habit_stats(e, "FREQ=DAILY", today=T, paused_dates=paused)["current"] == 7
        assert habit_schedule.habit_stats(e, "FREQ=DAILY", today=T)["current"] == 4

    def test_paused_week_neutral_for_weekly(self):
        e = {"2026-09-01": 1, "2026-09-15": 1, "2026-09-22": 1}
        paused = _days(date(2026, 9, 7), 7)
        assert habit_schedule.habit_stats(e, "FREQ=WEEKLY", today=T, paused_dates=paused)["current"] == 3

    def test_paused_today_not_due(self):
        s = habit_schedule.habit_stats({}, "FREQ=DAILY", today=T, paused_dates={T.isoformat()})
        assert (s["due_today"], s["paused_today"]) == (False, True)

    def test_pause_info_scoping(self):
        pauses = [
            {"uid": "p1", "task_uid": None, "start_date": "2026-09-20", "end_date": "2026-09-30"},
            {"uid": "p2", "task_uid": "other", "start_date": "2026-09-01", "end_date": "2026-09-30"},
            {"uid": "p3", "task_uid": "h1", "start_date": "2026-08-01", "end_date": "2026-08-02"},
        ]
        info = habit_view.pause_info(pauses, "h1", T)
        assert info["paused_today"] and info["paused_until"] == "2026-09-30"
        assert "2026-09-24" in info["dates"] and "2026-09-25" not in info["dates"]  # never past today
        assert "2026-08-01" in info["dates"] and "2026-09-05" not in info["dates"]  # other habit's pause ignored
        assert [p["uid"] for p in info["upcoming"]] == ["p1"]


class TestEndpoints:
    def test_add_validates(self, conn):
        _habit(conn, "h1")
        bad = [("x", "2026-09-01", ""), ("2026-09-05", "2026-09-01", ""), ("2026-01-01", "2027-06-01", ""),
               ("2026-09-01", "2026-09-02", "nope")]
        for s, e, uid in bad:
            resp = habits_router.add_pause(_req(), start_date=s, end_date=e, task_uid=uid,
                                           x_requested_with="fetch", conn=conn)
            assert resp.status_code in (400, 404)
        assert db.list_habit_pauses(conn) == []

    def test_add_and_delete(self, conn):
        _habit(conn, "h1")
        habits_router.add_pause(_req(), start_date="2026-09-01", end_date="2026-09-03", task_uid="h1",
                                x_requested_with="fetch", conn=conn)
        (p,) = db.list_habit_pauses(conn)
        assert (p["task_uid"], p["start_date"], p["end_date"]) == ("h1", "2026-09-01", "2026-09-03")
        habits_router.delete_pause(p["uid"], _req(), x_requested_with="fetch", conn=conn)
        assert db.list_habit_pauses(conn) == []

    def test_deleting_habit_drops_its_pauses_only(self, conn):
        _habit(conn, "h1")
        db.add_habit_pause(conn, "p1", "h1", "2026-09-01", "2026-09-02", _now())
        db.add_habit_pause(conn, "p2", None, "2026-09-01", "2026-09-02", _now())
        db.delete_task(conn, "h1")
        assert [p["uid"] for p in db.list_habit_pauses(conn)] == ["p2"]


class TestRendering:
    def test_paused_section_and_badge(self, conn):
        _habit(conn, "h1", "Aaa")
        _habit(conn, "h2", "Bbb")
        until = (TODAY + timedelta(days=3)).isoformat()
        db.add_habit_pause(conn, "p1", "h1", TODAY.isoformat(), until, _now())
        resp = habits_router.habits_page(_req(), conn=conn)
        assert [h["uid"] for h in resp.context["paused"]] == ["h1"]
        assert [h["uid"] for h in resp.context["todo"]] == ["h2"]
        body = resp.body.decode()
        assert "Paused until" in body
        # 2026-09-26: the add-pause form moved to the Pauses modal.
        assert 'href="/habits/pauses" data-modal' in body

    def test_global_pause_listed_and_detail_form(self, conn):
        _habit(conn, "h1")
        db.add_habit_pause(conn, "g1", None, TODAY.isoformat(), TODAY.isoformat(), _now())
        # 2026-09-26: listed in the Pauses modal, no longer on the page or
        # in the habit's view modal (single-habit pauses are added there).
        body = habits_router.pauses_modal(_req("/habits/pauses"), conn=conn).body.decode()
        assert "<strong>All habits</strong>" in body and 'action="/habits/pauses/g1/delete"' in body
        assert '<option value="h1">' in body
        detail = tasks_router.task_detail("h1", _req("/tasks/h1"), conn=conn).body.decode()
        assert "Pause this habit" not in detail


class TestBackup:
    def test_round_trip(self, conn):
        from src.routers import export as export_router

        _habit(conn, "h1")
        db.add_habit_pause(conn, "p1", "h1", "2026-09-01", "2026-09-02", _now())
        payload = {"habit_pauses": db.list_habit_pauses(conn)}
        db.delete_habit_pause(conn, "p1")
        export_router.restore_backup_payload(conn, payload)
        export_router.restore_backup_payload(conn, payload)  # idempotent
        assert [p["uid"] for p in db.list_habit_pauses(conn)] == ["p1"]
