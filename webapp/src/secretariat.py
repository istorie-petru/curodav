"""Content of the Secretariat page: an agenda-style list for one day.

Pure and clock-free: callers pass today's date and the already scoped
tasks, events and habits. Feature notes:
curodav-notes/documentation/features/home-and-secretariat.md.
"""

from datetime import date, timedelta

MAX_HABITS = 2
MAX_NOTES = 6
UPCOMING_EVENT_DAYS = 3
AGENDA_DAYS = 30


def greeting(hour: int, name: str | None = None) -> str:
    base = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    return f"{base}, {name}" if name else base


def _day(value: str | None) -> str:
    return (value or "")[:10]


def _is_open(task: dict) -> bool:
    return task.get("status") not in ("done", "archived")


def pinned_first(notes: list[dict]) -> list[dict]:
    """Pinned notes lead; each group keeps its incoming (newest edited first) order."""
    return sorted(notes, key=lambda n: not n.get("pinned"))[:MAX_NOTES]


def end_of_week(today: date) -> date:
    return today + timedelta(days=6 - today.weekday())


def build(today: date, tasks: list[dict], events: list[dict], habits: list[dict], notes: list[dict] | None = None) -> dict:
    """The four Secretariat sections.

    `events` must already be expanded into occurrences. Overdue open tasks
    lead the "due today" list. "Other reminders" holds up to MAX_HABITS
    habits due today, events in the next UPCOMING_EVENT_DAYS days and
    in-progress tasks that are not already listed above.
    """
    today_iso = today.isoformat()
    week_end_iso = end_of_week(today).isoformat()
    soon_iso = (today + timedelta(days=UPCOMING_EVENT_DAYS)).isoformat()
    open_tasks = [t for t in tasks if _is_open(t)]
    # Tasks completed moments ago arrive in `tasks` too (the caller applies
    # the check-off grace period); they stay in their list, shown done.
    listable = [t for t in tasks if t.get("status") != "archived"]

    events_today = sorted(
        (e for e in events if _day(e.get("start_at")) == today_iso), key=lambda e: e.get("start_at") or ""
    )
    due_today = sorted(
        (t for t in listable if t.get("due_at") and _day(t["due_at"]) <= today_iso),
        key=lambda t: (not _is_open(t), _day(t["due_at"]), t.get("title") or ""),
    )
    due_week = sorted(
        (t for t in listable if t.get("due_at") and today_iso < _day(t["due_at"]) <= week_end_iso),
        key=lambda t: (not _is_open(t), _day(t["due_at"]), t.get("title") or ""),
    )
    listed = {t["uid"] for t in due_today + due_week}
    reminders = [{"kind": "habit", "item": h} for h in habits[:MAX_HABITS]]
    reminders += [
        {"kind": "event", "item": e}
        for e in sorted(events, key=lambda e: e.get("start_at") or "")
        if today_iso < _day(e.get("start_at")) <= soon_iso
    ]
    reminders += [
        {"kind": "task", "item": t}
        for t in open_tasks
        if t.get("status") == "in_progress" and t["uid"] not in listed
    ]
    return {
        "events_today": events_today,
        "tasks_today": [{"task": t, "overdue": _is_open(t) and _day(t["due_at"]) < today_iso} for t in due_today],
        "tasks_week": due_week,
        "reminders": reminders,
        "notes": pinned_first(notes or []),
    }


def build_agenda(today: date, tasks: list[dict], events: list[dict], deadlines: list[dict] | None = None,
                 days: int = AGENDA_DAYS) -> list[dict]:
    """The Agenda view of a scoped page: overdue tasks and deadlines, then everything dated
    up to `days` ahead, as sections (Overdue, Today, This week, Later). No habits.

    `events` must already be expanded into occurrences; each deadline is
    {"title", "date" (ISO), "text", "color"}.
    """
    today_iso = today.isoformat()
    week_iso = end_of_week(today).isoformat()
    end_iso = (today + timedelta(days=days)).isoformat()
    entries = []
    for t in tasks:
        if _is_open(t) and t.get("due_at") and _day(t["due_at"]) <= end_iso:
            entries.append({"kind": "task", "item": t, "day": _day(t["due_at"]), "at": t["due_at"]})
    for e in events:
        if today_iso <= _day(e.get("start_at")) <= end_iso:
            entries.append({"kind": "event", "item": e, "day": _day(e["start_at"]), "at": e["start_at"]})
    for d in deadlines or []:
        if d["date"] <= end_iso:
            entries.append({"kind": "deadline", "item": d, "day": d["date"], "at": d["date"]})
    entries.sort(key=lambda x: (x["day"], x["at"], x["item"].get("title") or ""))
    sections = [("Overdue", lambda d: d < today_iso), ("Today", lambda d: d == today_iso),
                ("This week", lambda d: today_iso < d <= week_iso), ("Later", lambda d: d > week_iso)]
    out = []
    for title, test in sections:
        rows = [x for x in entries if test(x["day"])]
        if rows:
            out.append({"title": title, "entries": rows, "overdue": title == "Overdue"})
    return out
