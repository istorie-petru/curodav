"""Habits H3 (2026-09-24, plans/ui-cleanup-2026-09.md item 14): the habit
detail modal -- view-only year grid, clickable month calendar, day notes, "Log a
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


class TestMonthCalendar:
    def test_shape(self):
        rows = [{"due_date": "2026-09-10", "value": 1, "note": "x"}]
        cal = habit_view.month_calendar("h1", rows, "2026-09", today=date(2026, 9, 24))
        days = [d for w in cal["weeks"] for d in w]
        assert all(len(w) == 7 for w in cal["weeks"])
        assert days[0]["iso"] == "2026-08-31"  # Monday before Sep 1
        sep10 = next(d for d in days if d["iso"] == "2026-09-10")
        assert sep10["done"] and sep10["note"] == "x"
        assert next(d for d in days if d["iso"] == "2026-09-25")["is_future"]
        assert cal["label"] == "September 2026"
        assert cal["prev_url"] == "/tasks/h1?month=2026-08"
        assert cal["next_url"] is None  # never past this month
        assert cal["done_count"] == 1

    def test_bad_or_future_month_clamps(self):
        t = date(2026, 9, 24)
        assert habit_view.month_calendar("h1", [], "garbage", today=t)["label"] == "September 2026"
        assert habit_view.month_calendar("h1", [], "2027-01", today=t)["label"] == "September 2026"
        assert habit_view.month_calendar("h1", [], "2026-07", today=t)["next_url"] == "/tasks/h1?month=2026-08"


class TestDetailModal:
    def test_renders_interactive_grid_month_and_log_form(self, conn):
        _habit(conn)
        db.upsert_task_completion(conn, "h1", TODAY.isoformat(), _now(), 1, "morning run")
        req = Request({"type": "http", "method": "GET", "path": "/tasks/h1", "headers": [], "query_string": b""})
        body = tasks_router.task_detail("h1", req, conn=conn).body.decode()
        assert "heatmap-cell-form" not in body  # year grid stays view-only (2026-08-29 request)
        assert 'class="form-inline" data-modal-keep-open data-cc-change="task"' in body  # month days
        assert 'class="habit-month-grid"' in body
        assert 'action="/tasks/h1/completions" class="habit-log-form" data-modal-keep-open' in body
        assert "morning run" in body
        assert f'max="{TODAY.isoformat()}"' in body


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
