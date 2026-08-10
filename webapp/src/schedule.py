"""Schedule feature: a repeating class list ("repeat endlessly between
dates, excepting certain dates" -- the university/school timetable this
was deferred for months, per the desktop app's todo file) with odd/even
ISO-week parity, same convention the uploaded reference "Uni Schedule ->
ICS" app uses and documents.

Each class in `schedule_classes` (db.py) is local-only, structured data --
day/time/name/acronym/professor/room/credits/parity/enrolled. This module
compiles a class's cadence + the semester bounds + the holiday exception
ranges into a single VEVENT (RRULE + EXDATE) and mirrors it one-way into
the `events` table/Radicale via the normal event bridge, so it shows up in
this app's own Calendar tab and any other CalDAV client. The mirrored
event is a courtesy export -- edits to it aren't parsed back into the
class's structured fields; the class list is the only source of truth for
those.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def iso_week_parity(d: date) -> str:
    """'odd' or 'even', by ISO-8601 week number -- the convention most
    European timetables already use (documented the same way in the
    uploaded reference app)."""
    return "odd" if d.isocalendar()[1] % 2 == 1 else "even"


def first_occurrence(semester_start: date, weekday_name: str, parity: str) -> date:
    """The first date >= semester_start on `weekday_name` whose ISO week
    parity matches `parity` ('all' skips the parity check entirely)."""
    target_weekday = DAYS.index(weekday_name)
    delta = (target_weekday - semester_start.weekday()) % 7
    occ = semester_start + timedelta(days=delta)
    if parity in ("odd", "even") and iso_week_parity(occ) != parity:
        occ += timedelta(days=7)
    return occ


def generate_occurrences(anchor: date, until: date, parity: str) -> list[date]:
    """Raw occurrence dates (before holiday exclusion), stepping weekly
    ('all') or every 2 weeks (odd/even). ISO week parity strictly
    alternates, so stepping by 2 weeks from a correctly-anchored date stays
    aligned for the whole range -- no need to re-check parity per step."""
    step = timedelta(weeks=1 if parity == "all" else 2)
    occurrences = []
    current = anchor
    while current <= until:
        occurrences.append(current)
        current += step
    return occurrences


def compute_excluded(occurrences: list[date], holidays: list[dict[str, str]]) -> list[date]:
    ranges = [
        (date.fromisoformat(h["date_from"]), date.fromisoformat(h["date_to"]))
        for h in holidays
    ]
    return [occ for occ in occurrences if any(lo <= occ <= hi for lo, hi in ranges)]


def next_occurrence(
    cls: dict[str, Any],
    settings: dict[str, Any],
    holidays: list[dict[str, str]],
    today: date | None = None,
) -> date | None:
    """The next date a class actually meets, on or after `today` (Phase 6
    rework -- the calendar's education "next lecture" badge and a project
    page's per-class "Next: today/tomorrow/in N days"). Respects parity
    (odd/even-week classes) and semester bounds by generating the class's
    real occurrences from first_occurrence, then skipping any that land on
    a holiday. Returns None if the class couldn't be scheduled (no
    semester_start) or no occurrence remains at/after today."""
    today = today or date.today()
    start_str = (settings or {}).get("semester_start")
    if not start_str:
        return None
    semester_end = date.fromisoformat((settings or {}).get("semester_end")) if (settings or {}).get("semester_end") else None
    anchor = first_occurrence(date.fromisoformat(start_str), (cls or {}).get("day") or "Monday", (cls or {}).get("parity") or "all")
    until = semester_end if semester_end and semester_end >= today else today
    occurrences = generate_occurrences(anchor, until, (cls or {}).get("parity") or "all")
    excluded = set(compute_excluded(occurrences, holidays))
    for occ in occurrences:
        if occ < today:
            continue
        if occ.isoformat() in excluded:
            continue
        return occ
    return None


def next_label(next_date: date, today: date | None = None) -> str:
    """Label for a "next lecture" badge: 'today', 'tomorrow', or 'in N
    days' (never a past date -- next_occurrence only ever returns >=
    today, and a bare date reads worse than the relative form for the
    near future)."""
    today = today or date.today()
    delta = (next_date - today).days
    if delta <= 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return f"in {delta} days"


def class_to_event_row(
    cls: dict[str, Any], settings: dict[str, Any], holidays: list[dict[str, str]]
) -> dict[str, Any] | None:
    """The mirrored VEVENT row for a schedule class, or None if it can't be
    scheduled yet (no semester start/end configured, or the semester is too
    short for this class's day/parity to ever land)."""
    semester_start = settings.get("semester_start")
    semester_end = settings.get("semester_end")
    if not semester_start or not semester_end:
        return None

    start_date = date.fromisoformat(semester_start)
    end_date = date.fromisoformat(semester_end)
    anchor = first_occurrence(start_date, cls["day"], cls["parity"])
    if anchor > end_date:
        return None

    occurrences = generate_occurrences(anchor, end_date, cls["parity"])
    excluded = compute_excluded(occurrences, holidays)

    start_at = f"{anchor.isoformat()}T{cls['start_time']}:00"
    end_at = f"{anchor.isoformat()}T{cls['end_time']}:00"
    exdates = [f"{d.isoformat()}T{cls['start_time']}:00" for d in excluded]

    recurrence_parts = ["FREQ=WEEKLY"]
    if cls["parity"] in ("odd", "even"):
        recurrence_parts.append("INTERVAL=2")
    recurrence_parts.append(f"UNTIL={end_date.isoformat()}")

    description_lines = []
    if cls.get("professor"):
        description_lines.append(f"Professor: {cls['professor']}")
    if cls.get("class_type"):
        description_lines.append(f"Type: {cls['class_type']}")
    if cls.get("credits"):
        description_lines.append(f"Credits: {cls['credits']}")
    if cls.get("acronym"):
        description_lines.append(f"Acronym: {cls['acronym']}")

    reminder = settings.get("reminder_minutes") or 0

    return {
        "uid": cls.get("event_uid") or cls["uid"],
        "title": cls.get("name") or cls.get("acronym") or "Class",
        "description": "\n".join(description_lines),
        "start_at": start_at,
        "end_at": end_at,
        "all_day": False,
        "location": cls.get("room") or None,
        "status": "active" if cls.get("enrolled", True) else "archived",
        "tags": [settings.get("schedule_label") or "Schedule"],
        "calendar_path": settings.get("target_calendar_uid") or "calendar",
        "recurrence": ";".join(recurrence_parts),
        "exdates": exdates,
    }


# --------------------------------------------------------------------- #
# Conflicts + credits (mirrors the reference app's warnings strip)
# --------------------------------------------------------------------- #


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _time_overlap(s1: str, e1: str, s2: str, e2: str) -> bool:
    return _minutes(s1) < _minutes(e2) and _minutes(s2) < _minutes(e1)


def _parity_compatible(p1: str, p2: str) -> bool:
    return p1 == "all" or p2 == "all" or p1 == p2


def compute_conflicts(classes: list[dict[str, Any]]) -> list[tuple[dict, dict]]:
    """Two enrolled classes only conflict if same day, overlapping times,
    AND could actually land on the same real date -- an odd-week class and
    an even-week class in the same slot alternate and never truly clash."""
    enrolled = [c for c in classes if c.get("enrolled", True)]
    conflicts = []
    for i in range(len(enrolled)):
        for j in range(i + 1, len(enrolled)):
            a, b = enrolled[i], enrolled[j]
            if a["day"] != b["day"]:
                continue
            if not _parity_compatible(a["parity"], b["parity"]):
                continue
            if _time_overlap(a["start_time"], a["end_time"], b["start_time"], b["end_time"]):
                conflicts.append((a, b))
    return conflicts


def credits_summary(classes: list[dict[str, Any]]) -> float:
    return sum(c.get("credits") or 0 for c in classes if c.get("enrolled", True))
