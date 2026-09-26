#!/usr/bin/env python3
"""Seed a throwaway preview database with realistic data for screenshots and
visual checks (2026-09-25 UI audit; kept so later sessions don't rebuild it).

Usage, from webapp/:

    ../.venv/bin/python scripts/seed_preview.py [DB_PATH] [--force]
    CC_DB_PATH=DB_PATH PYTHONPATH=src ../.venv/bin/python -m src.main

DB_PATH defaults to /tmp/curodav-preview/cache.sqlite. Dates are relative to
today, so the data always looks current. What it creates, and the data rules
it follows (each one cost a debugging round once):

- 7 labels: Work, Personal, Health, Website Relaunch (project with a deadline
  20 days out), Family (group "People"), Habit, Reading (group "Hobbies").
  Colours are the app's named palette ("blue", "green", ...) -- hex values
  aren't a valid label colour and render with no colour at all.
- 24 events: timed, three overlapping, a crowded day ("+N more"), all-day
  and multi-day. All-day events are stored the app's way: T00:00 on the
  first day to T23:59 on the LAST day (inclusive), not an exclusive end.
- 10 tasks using the app's status keys (active / in_progress / done); iCal
  keys like NEEDS-ACTION render as a blank status and an empty Kanban.
- 4 habits with ~90 days of history: Meditate (daily), Drink water (8 a
  day, amount habit), Run (Mon/Wed/Fri), No sugar (avoid habit).
- 4 contacts.

Refuses to write into a database that already holds events or tasks unless
--force is given, so it can't pollute a real one by accident."""
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import db  # noqa: E402

random.seed(7)
_args = [a for a in sys.argv[1:] if a != "--force"]
FORCE = "--force" in sys.argv[1:]
DB = Path(_args[0] if _args else "/tmp/curodav-preview/cache.sqlite")
today = date.today()
now = datetime.now(timezone.utc).isoformat()


def _refuse_if_populated(conn) -> None:
    existing = conn.execute("SELECT (SELECT COUNT(*) FROM events) + (SELECT COUNT(*) FROM tasks)").fetchone()[0]
    if existing and not FORCE:
        sys.exit(f"{DB} already has {existing} events/tasks; refusing to seed it (pass --force to add anyway).")


def d(offset, hh=None, mm=0):
    day = today + timedelta(days=offset)
    if hh is None:
        return day.isoformat()
    return datetime(day.year, day.month, day.day, hh, mm).isoformat()


with db.connect(DB) as conn:
    db.init_schema(conn)
    _refuse_if_populated(conn)
    labels = [
        dict(name="Work", color="blue", icon="briefcase", is_project=0, sidebar_pin=1, has_dashboard=1),
        dict(name="Personal", color="green", icon="home", sidebar_pin=1),
        dict(name="Health", color="red", icon="heart"),
        dict(name="Website Relaunch", color="purple", icon="flag", is_project=1, has_deadline=1,
             deadline_date=d(20), sidebar_pin=1, has_dashboard=1, widget_pin=1),
        dict(name="Family", color="orange", icon="users", label_group="People"),
        dict(name="Habit", color="teal", icon="repeat"),
        dict(name="Reading", color="slate", icon="book", label_group="Hobbies"),
    ]
    for lb in labels:
        db.upsert_label_config(conn, {"created_at": now, **lb})

    events = [
        ("Team standup", d(0, 9), d(0, 9, 30), 0, ["Work"]),
        ("Design review", d(0, 11), d(0, 12, 30), 0, ["Work", "Website Relaunch"]),
        ("Lunch with Ana", d(0, 13), d(0, 14), 0, ["Personal"]),
        ("Gym", d(0, 18), d(0, 19), 0, ["Health"]),
        ("Dentist appointment with a really long title that wraps", d(1, 10), d(1, 11), 0, ["Health"]),
        ("Conference (all-day, multi-day)", d(2), d(5), 1, ["Work"]),
        ("Mom's birthday", d(3), d(4), 1, ["Family"]),
        ("Sprint planning", d(-1, 14), d(-1, 15, 30), 0, ["Work"]),
        ("Launch day", d(20), d(21), 1, ["Website Relaunch"]),
        ("Vacation", d(8), d(13), 1, ["Personal"]),
        ("Book club", d(6, 19), d(6, 21), 0, ["Reading"]),
        ("Overlapping A", d(1, 14), d(1, 16), 0, ["Work"]),
        ("Overlapping B", d(1, 15), d(1, 17), 0, ["Personal"]),
        ("Overlapping C", d(1, 15, 30), d(1, 16, 30), 0, ["Health"]),
        ("Quarterly review", d(-6), d(-5), 1, ["Work"]),
        ("Flight to Berlin", d(9, 7), d(9, 9, 30), 0, ["Personal"]),
        ("1:1 with manager", d(7, 10), d(7, 10, 30), 0, ["Work"]),
        ("Holiday party", d(15, 20), d(15, 23), 0, ["Family", "Personal"]),
        ("Unlabeled event", d(2, 16), d(2, 17), 0, []),
        ("Many events day 1", d(4, 8), d(4, 9), 0, ["Work"]),
        ("Many events day 2", d(4, 9), d(4, 10), 0, ["Personal"]),
        ("Many events day 3", d(4, 11), d(4, 12), 0, ["Health"]),
        ("Many events day 4", d(4, 13), d(4, 14), 0, ["Family"]),
        ("Many events day 5", d(4, 15), d(4, 16), 0, ["Reading"]),
    ]
    for i, (title, s, e, allday, tags) in enumerate(events):
        if allday:  # app convention: inclusive last day at 23:59
            s = s + "T00:00:00"
            e = (date.fromisoformat(e) - timedelta(days=1)).isoformat() + "T23:59:00"
        db.upsert_event(conn, dict(uid=f"ev-{i}", title=title, start_at=s, end_at=e, all_day=allday,
                                   status="CONFIRMED", created_at=now, updated_at=now, tags=tags,
                                   location="Room 4B" if i % 3 == 0 else "",
                                   description="Agenda: go over the numbers." if i % 2 else ""))

    tasks = [
        ("Write launch blog post", "active", d(1, 17), ["Website Relaunch"]),
        ("Fix hero image on landing page", "in_progress", d(0, 17), ["Website Relaunch", "Work"]),
        ("Renew passport", "active", d(-2, 12), ["Personal"]),
        ("Book flights", "done", d(-3, 12), ["Personal"]),
        ("Prepare slides for quarterly review", "active", d(3, 9), ["Work"]),
        ("Call grandma", "active", d(2, 18), ["Family"]),
        ("Read 'Deep Work'", "in_progress", None, ["Reading"]),
        ("Buy groceries", "active", d(0, 19), []),
        ("QA checklist for relaunch", "active", d(15, 12), ["Website Relaunch"]),
        ("Migrate DNS", "active", d(18, 12), ["Website Relaunch"]),
    ]
    for i, (title, status, due, tags) in enumerate(tasks):
        db.upsert_task(conn, dict(uid=f"task-{i}", title=title, progress=0, status=status, due_at=due,
                                  created_at=now, updated_at=now, tags=tags,
                                  description="Some details here." if i % 2 else ""))

    habits = [
        ("Meditate", "FREQ=DAILY", 1, None, "build", 0.8),
        ("Drink water", "FREQ=DAILY", 8, "glasses", "build", 0.6),
        ("Run", "FREQ=WEEKLY;BYDAY=MO,WE,FR", 1, None, "build", 0.7),
        ("No sugar", "FREQ=DAILY", 1, None, "avoid", 0.5),
    ]
    for i, (title, rrule, target, unit, kind, rate) in enumerate(habits):
        uid = f"habit-{i}"
        db.upsert_task(conn, dict(uid=uid, title=title, status="active", recurrence=rrule,
                                  description="", progress=0, start_at=d(-90, 8), due_at=d(-90, 8), created_at=now, updated_at=now,
                                  target_per_day=target, habit_unit=unit, habit_kind=kind,
                                  tags=["Habit"]))
        for back in range(1, 90):
            if random.random() < rate:
                day = today - timedelta(days=back)
                db.upsert_task_completion(conn, uid, day.isoformat(), now,
                                          value=random.randint(max(1, target // 2), target))

    for i, (fn, org) in enumerate([("Ana Popescu", "Acme"), ("Bogdan Ionescu", "Globex"),
                                    ("Carla Mendes", None), ("Dan Radu", "Initech")]):
        db.upsert_contact(conn, dict(uid=f"c-{i}", full_name=fn, org=org, created_at=now, updated_at=now,
                                     tags=["Family"] if i == 2 else ["Work"]))
    conn.commit()
print("seeded", DB)
