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


class TestSettings:
    """Web Push P3: per-type toggles + digest time."""

    def test_defaults_all_on(self, conn):
        assert reminders.enabled_types(conn) == set(reminders.TYPES)
        assert reminders.digest_time_str(conn) == "08:00"

    def test_types_filter_and_all_off(self, conn):
        from src.routers import settings as settings_router

        _event(conn, "standup", at(9, 0))
        db.upsert_task(conn, {"uid": "t1", "title": "Invoice", "description": "", "status": "active", "tags": [],
                              "due_at": TODAY.isoformat(), "created_at": _now_utc()})
        settings_router.set_notifications(types=["tasks"], digest_time="09:00", conn=conn)
        assert reminders.enabled_types(conn) == {"tasks"}
        assert _keys(conn, at(9, 1)) == [f"tasks:{TODAY}"]  # event reminder off
        settings_router.set_notifications(types=[], digest_time="09:00", conn=conn)
        assert reminders.enabled_types(conn) == set()
        assert _keys(conn, at(9, 1)) == []

    @pytest.mark.parametrize("raw,expected", [("7:05", "07:05"), ("25:00", "08:00"), ("nope", "08:00"), ("23:59", "23:59")])
    def test_digest_time_validated(self, conn, raw, expected):
        from src.routers import settings as settings_router

        settings_router.set_notifications(types=list(reminders.TYPES), digest_time=raw, conn=conn)
        assert reminders.digest_time_str(conn) == expected

    def test_settings_page_renders_form(self, conn):
        from starlette.requests import Request
        from src.routers import settings as settings_router

        req = Request({"type": "http", "method": "GET", "path": "/settings/general", "headers": [], "query_string": b""})
        body = settings_router.settings_general(req, conn=conn).body.decode()
        assert 'action="/settings/notifications"' in body
        assert body.count('name="types"') == 4
        assert 'name="digest_time" value="08:00"' in body


def _habit(conn, uid, title=None, target=1, kind="build", reminder=None):
    db.save_task_habit_settings(conn, "Habit")
    db.upsert_task(conn, {"uid": uid, "title": title or uid.title(), "description": "", "status": "active",
                          "tags": ["Habit"], "recurrence": "FREQ=DAILY", "target_per_day": target,
                          "habit_kind": kind, "created_at": _now_utc()})
    if reminder:
        db.set_task_reminder_time(conn, uid, reminder)


class TestPerHabitReminderTime:
    """2026-09-25: a habit with its own reminder time reminds at that time
    (only while still due) and drops out of the morning digest."""

    def test_normalizes_and_survives_an_ordinary_save(self, conn):
        assert db.normalize_reminder_time("7:05") == "07:05"
        assert db.normalize_reminder_time("24:00") is None
        assert db.normalize_reminder_time("") is None
        _habit(conn, "walk", reminder="19:30")
        row = dict(db.get_task(conn, "walk"))
        db.upsert_task(conn, {**row, "title": "Evening walk"})  # e.g. a rename or a sync re-save
        assert db.get_task(conn, "walk")["reminder_time"] == "19:30"
        db.set_task_reminder_time(conn, "walk", "")
        assert db.get_task(conn, "walk")["reminder_time"] is None

    def test_fires_at_its_time_and_leaves_the_digest(self, conn):
        _habit(conn, "walk", reminder="19:30")
        _habit(conn, "read")
        (digest,) = reminders.due_notifications(conn, at(8, 5))
        assert digest.key == f"habits:{TODAY}" and "Read" in digest.body  # walk isn't in it
        # (the morning digest stays eligible until 21:00 -- only per-habit
        # keys matter here)
        def own(now):
            return [n for n in reminders.due_notifications(conn, now) if n.key.startswith("habit:")]
        assert own(at(19, 29)) == []
        (n,) = own(at(19, 31))
        assert n.key == f"habit:walk:{TODAY}" and n.title == "Walk" and n.body == "Still to do today."
        assert own(at(19, 50)) == []  # past the grace window

    def test_quiet_once_done_and_shows_progress_for_amounts(self, conn):
        _habit(conn, "water", target=8, reminder="15:00")
        db.upsert_task_completion(conn, "water", TODAY.isoformat(), _now_utc(), value=3)
        (n,) = reminders.due_notifications(conn, at(15, 0))
        assert n.body == "3 of 8 so far. Keep going."
        db.upsert_task_completion(conn, "water", TODAY.isoformat(), _now_utc(), value=8)
        assert _keys(conn, at(15, 0)) == []  # done: no reminder, and not in the digest either

    def test_avoid_habits_and_disabled_type_never_remind(self, conn):
        _habit(conn, "sugar", kind="avoid", reminder="12:00")
        assert _keys(conn, at(12, 0)) == []
        _habit(conn, "walk", reminder="12:00")
        db.set_app_meta(conn, reminders.TYPES_KEY, "events,tasks")
        assert _keys(conn, at(12, 0)) == []
