"""Web Push P2 (2026-09-24, plans/ui-cleanup-2026-09.md item 7): the
reminder scheduler -- events at start (or their own reminder offsets),
a morning digest for tasks and habits due today, sleep/leisure block
starts; never sent twice; nothing while no device is subscribed."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src import db, reminders

TODAY = date.today()


def at(hh, mm=0, day=TODAY):
    return datetime(day.year, day.month, day.day, hh, mm)


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now_utc():
    return datetime.now(timezone.utc).isoformat()


def _event(conn, uid, start, reminders_=None, **extra):
    row = {"uid": uid, "title": uid.title(), "description": "", "status": "active", "all_day": 0,
           "start_at": start.isoformat(timespec="seconds"), "end_at": (start + timedelta(hours=1)).isoformat(timespec="seconds"),
           "reminders": reminders_ or [], "created_at": _now_utc()}
    row.update(extra)
    db.upsert_event(conn, row)


def _keys(conn, now):
    return sorted(n.key for n in reminders.due_notifications(conn, now))


class TestEvents:
    def test_fires_at_start_within_grace(self, conn):
        _event(conn, "standup", at(9, 0))
        assert _keys(conn, at(8, 59)) == []
        (n,) = reminders.due_notifications(conn, at(9, 5))
        assert n.title == "Standup" and "Starting now" in n.body and n.url == f"/calendar/day/{TODAY}"
        assert _keys(conn, at(9, 16)) == []  # past the grace window: skipped, not late

    def test_uses_own_reminder_offsets(self, conn):
        _event(conn, "dentist", at(14, 0), reminders_=[30, 1440])
        keys = _keys(conn, at(13, 31))
        assert keys == [f"event:dentist:{at(14, 0).isoformat()}:30"]
        assert _keys(conn, at(14, 0)) == []  # offsets replace the at-start one

    def test_offset_across_midnight(self, conn):
        tomorrow = TODAY + timedelta(days=1)
        _event(conn, "early", at(0, 10, tomorrow), reminders_=[30])
        assert len(_keys(conn, at(23, 45))) == 1

    def test_all_day_and_cancelled_skipped(self, conn):
        _event(conn, "holiday", at(0, 0), all_day=1)
        _event(conn, "off", at(10, 0), status="archived")
        assert _keys(conn, at(10, 1)) == []


class TestDigest:
    def _task(self, conn, uid, title, due, status="active", tags=()):
        db.upsert_task(conn, {"uid": uid, "title": title, "description": "", "status": status, "tags": list(tags),
                              "due_at": due, "created_at": _now_utc()})

    def test_tasks_generic_when_many(self, conn):
        self._task(conn, "t1", "Invoice", TODAY.isoformat())
        assert _keys(conn, at(7, 59)) == []
        (n,) = reminders.due_notifications(conn, at(8, 0))
        assert n.body == "“Invoice” is due today."
        self._task(conn, "t2", "Call", TODAY.isoformat())
        self._task(conn, "t3", "Done", TODAY.isoformat(), status="done")
        (n,) = reminders.due_notifications(conn, at(12, 0))
        assert n.body.startswith("You have 2 tasks due today")
        assert _keys(conn, at(21, 30)) == []  # too late in the day

    def test_habits_digest_and_custom_time(self, conn):
        db.save_task_habit_settings(conn, "Habit")
        for uid in ("h1", "h2"):
            db.upsert_task(conn, {"uid": uid, "title": uid, "description": "", "status": "active", "tags": ["Habit"],
                                  "recurrence": "FREQ=DAILY", "created_at": _now_utc()})
        db.set_app_meta(conn, reminders.DIGEST_TIME_KEY, "06:30")
        (n,) = reminders.due_notifications(conn, at(6, 30))
        assert n.key == f"habits:{TODAY}" and n.body.startswith("2 habits lined up")
        assert n.url == "/habits"


class TestTimeBlocks:
    def test_block_start_and_midnight_continuation(self, conn):
        wd = TODAY.strftime("%A")
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "", "start_time": "22:30", "end_time": "23:59", "days": wd})
        db.upsert_time_block(conn, {"uid": "s2", "kind": "sleep", "label": "", "start_time": "00:00", "end_time": "06:00", "days": wd})
        db.upsert_time_block(conn, {"uid": "l1", "kind": "leisure", "label": "Guitar", "start_time": "18:00", "end_time": "19:00", "days": wd})
        (n,) = reminders.due_notifications(conn, at(22, 31))
        assert n.title == "Wind-down time"
        assert _keys(conn, at(0, 1)) == []  # 00:00 block = last night's continuation
        (n,) = reminders.due_notifications(conn, at(18, 0))
        assert n.title == "Guitar"


class TestRunOnce:
    def test_idle_without_devices_then_sends_once(self, conn):
        _event(conn, "standup", at(9, 0))
        calls = []

        def fake(**kw):
            calls.append(kw)

        assert reminders.run_once(conn, at(9, 1), sender=fake) == 0  # no device yet
        assert calls == []
        db.upsert_push_subscription(conn, "https://a.example/1", "k", "a", None, "now")
        assert reminders.run_once(conn, at(9, 2), sender=fake) == 1
        assert reminders.run_once(conn, at(9, 3), sender=fake) == 0  # recorded -- never twice
        assert len(calls) == 1

    def test_failed_send_retried_next_tick(self, conn):
        _event(conn, "standup", at(9, 0))
        db.upsert_push_subscription(conn, "https://a.example/1", "k", "a", None, "now")

        def boom(**kw):
            raise ConnectionError("offline")

        assert reminders.run_once(conn, at(9, 1), sender=boom) == 0
        assert not db.push_was_sent(conn, f"event:standup:{at(9, 0).isoformat()}:0")
        assert reminders.run_once(conn, at(9, 2), sender=lambda **kw: None) == 1
