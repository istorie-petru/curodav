"""Reminder scheduling for Web Push (2026-09-24, plans/ui-cleanup-2026-09.md
item 7, slice P2).

The one reminder primitive the spec allows, plus the one extra mechanism
it names:

- **Events** remind at their start -- or at each of their own
  `reminders` offsets (minutes before start, imported VALARMs) when they
  have any. Timed events only; all-day events are covered by nothing
  here (they have no moment to fire at).
- **Tasks** and **habits** remind on the day they're due: one morning
  digest each (generic when more than one -- "You have 3 tasks due
  today", never a list), at the digest time.
- **Sleep / leisure time** blocks remind when they start (the extra
  mechanism). A block starting at 00:00 is the continuation of the
  previous night's block (blocks can't cross midnight), so it doesn't
  fire.

`due_notifications(conn, now)` is pure given the database -- the
background thread (`start_scheduler`) calls it every minute, sends
whatever isn't in `push_sent` yet, and records it, so a restart never
double-sends. A moment that passed while the server was down still fires
within `GRACE` (then it's skipped rather than arriving hours late); a
digest fires any time from the digest time until `DIGEST_UNTIL`.

Times are the server's local wall clock -- the same clock event
`start_at` values are written in.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from . import db, habit_view, push, recurrence_expand

log = logging.getLogger(__name__)

GRACE = timedelta(minutes=15)
DIGEST_TIME_KEY = "push_digest_time"
DEFAULT_DIGEST_TIME = "08:00"
DIGEST_UNTIL = time(21, 0)
TICK_SECONDS = 60
# Web Push P3: which reminder types are on (Settings > General). Stored as
# a comma list; missing = all on.
TYPES_KEY = "push_types"
TYPES: tuple[str, ...] = ("events", "tasks", "habits", "blocks")
TYPE_LABELS = {
    "events": "Events, when they start",
    "tasks": "Tasks due today (morning)",
    "habits": "Habits due today (morning)",
    "blocks": "Sleep & leisure time starting",
}


def enabled_types(conn) -> set[str]:
    raw = db.get_app_meta(conn, TYPES_KEY)
    if raw is None:
        return set(TYPES)
    return {t for t in raw.split(",") if t in TYPES}


def digest_time_str(conn) -> str:
    return _digest_time(conn).strftime("%H:%M")


@dataclass(frozen=True)
class Notification:
    key: str
    title: str
    body: str
    url: str
    tag: str


def _local_naive(value: str | None) -> datetime | None:
    if not value or len(value) < 16:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _digest_time(conn) -> time:
    raw = db.get_app_meta(conn, DIGEST_TIME_KEY) or DEFAULT_DIGEST_TIME
    try:
        h, m = (int(x) for x in raw.split(":", 1))
        return time(h, m)
    except (ValueError, TypeError):
        return time(8, 0)


def _in_window(moment: datetime, now: datetime) -> bool:
    return moment <= now < moment + GRACE


def _fmt_clock(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _event_notifications(conn, now: datetime) -> list[Notification]:
    out = []
    today = now.date()
    # Tomorrow too: a reminder offset can reach back over midnight (an
    # event at 00:10 with a 30-minute reminder fires at 23:40 today).
    for day in (today, today + timedelta(days=1)):
        iso = day.isoformat()
        events = db.list_events(conn, start=iso, end=iso + "T23:59:59")
        events = recurrence_expand.expand_events(
            events, day, day, db.list_holidays_by_calendar(conn), db.list_event_occurrence_overrides_by_master(conn)
        )
        for e in events:
            # A cancelled (VEVENT STATUS:CANCELLED) event is stored as
            # status "archived" -- see ical_rows._VEVENT_TO_STATUS.
            if e.get("all_day") or e.get("status") == "archived":
                continue
            start = _local_naive(e.get("start_at"))
            if start is None or start.date() != day:
                continue
            offsets = [int(m) for m in (e.get("reminders") or []) if isinstance(m, (int, float)) and 0 <= m <= 7 * 24 * 60]
            for minutes in offsets or [0]:
                moment = start - timedelta(minutes=minutes)
                if not _in_window(moment, now):
                    continue
                if minutes == 0:
                    body = f"Starting now ({_fmt_clock(start)})."
                elif minutes < 60:
                    body = f"Starts in {minutes} min, at {_fmt_clock(start)}."
                else:
                    body = f"Coming up at {_fmt_clock(start)}."
                out.append(
                    Notification(
                        key=f"event:{e['uid']}:{start.isoformat()}:{minutes}",
                        title=e.get("title") or "Event",
                        body=body,
                        url=f"/calendar/day/{day.isoformat()}",
                        tag=f"event-{e['uid']}",
                    )
                )
    return out


def _digest_notifications(conn, now: datetime) -> list[Notification]:
    at = datetime.combine(now.date(), _digest_time(conn))
    if not (at <= now and now.time() < DIGEST_UNTIL):
        return []
    today_iso = now.date().isoformat()
    out = []
    tasks = [
        t for t in db.list_tasks(conn)
        if t.get("status") not in ("done", "archived") and (t.get("due_at") or "")[:10] == today_iso
    ]
    if tasks:
        body = f"“{tasks[0]['title']}” is due today." if len(tasks) == 1 else f"You have {len(tasks)} tasks due today. One at a time."
        out.append(Notification(f"tasks:{today_iso}", "Today's tasks", body, "/tasks", "tasks-today"))
    habits = [h for h in habit_view.habit_items(conn, now.date()) if h["due_today"] and not h["is_avoid"]]
    if habits:
        if len(habits) == 1:
            body = f"Time for “{habits[0]['title']}” today."
        else:
            body = f"{len(habits)} habits lined up for today. You've got this."
        out.append(Notification(f"habits:{today_iso}", "Habits", body, "/habits", "habits-today"))
    return out


def _time_block_notifications(conn, now: datetime) -> list[Notification]:
    weekday = now.strftime("%A")
    out = []
    for b in db.list_time_blocks(conn):
        if weekday not in db.time_block_days(b) or b.get("start_time") in (None, "", "00:00"):
            continue
        try:
            h, m = (int(x) for x in b["start_time"].split(":", 1))
        except ValueError:
            continue
        moment = datetime.combine(now.date(), time(h, m))
        if not _in_window(moment, now):
            continue
        if b["kind"] == "sleep":
            title, body = "Wind-down time", "Sleep time starts now. Rest well."
        else:
            title, body = "Leisure time", "Your leisure time starts now. Enjoy it."
        label = (b.get("label") or "").strip()
        out.append(
            Notification(
                key=f"block:{b['uid']}:{now.date().isoformat()}",
                title=label or title,
                body=body,
                url="/calendar/week",
                tag=f"block-{b['uid']}",
            )
        )
    return out


def due_notifications(conn, now: datetime | None = None) -> list[Notification]:
    """Everything that should fire at `now` (local naive) and hasn't been
    sent yet."""
    now = now or datetime.now()
    on = enabled_types(conn)
    candidates: list[Notification] = []
    if "events" in on:
        candidates += _event_notifications(conn, now)
    if on & {"tasks", "habits"}:
        candidates += [n for n in _digest_notifications(conn, now) if n.key.split(":", 1)[0] in on]
    if "blocks" in on:
        candidates += _time_block_notifications(conn, now)
    return [n for n in candidates if not db.push_was_sent(conn, n.key)]


def run_once(conn, now: datetime | None = None, sender=None) -> int:
    """One scheduler tick: send what's due, record it. Returns how many
    notifications went out. Nothing is computed while no device is
    subscribed (and nothing is recorded, so turning notifications on
    mid-grace-window still catches the current moment)."""
    if not db.list_push_subscriptions(conn):
        return 0
    sent = 0
    for n in due_notifications(conn, now):
        kwargs = {"sender": sender} if sender else {}
        result = push.send_to_all(conn, n.title, n.body, url=n.url, tag=n.tag, **kwargs)
        if result["sent"] or not db.list_push_subscriptions(conn):
            db.record_push_sent(conn, n.key, (now or datetime.now()).isoformat())
            sent += 1
        # else: every device failed (network?) -- leave it unrecorded and
        # retry next tick while the moment is still in its window.
    db.prune_push_sent(conn, ((now or datetime.now()) - timedelta(days=3)).isoformat())
    return sent


def _loop(db_path, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            with db.connect(db_path) as conn:
                run_once(conn)
        except Exception:
            log.exception("Reminder tick failed; will retry next minute")
        stop_event.wait(TICK_SECONDS)


def start_scheduler(db_path) -> tuple[threading.Thread, threading.Event]:
    """Background thread, same pattern as sync.start_background_sync: its
    own SQLite connection per tick, stopped via the returned event."""
    stop_event = threading.Event()
    thread = threading.Thread(target=_loop, args=(db_path, stop_event), daemon=True, name="push-reminders")
    thread.start()
    return thread, stop_event
