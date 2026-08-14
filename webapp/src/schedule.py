"""Schedule feature (1.6, Schedule & recurrence rework): a specialized
interface for creating and managing the recurring events a university
timetable needs -- weekly lectures/seminars with alternating even/odd-week
parity, semester bounds, and holiday exclusions -- without a class being
its own data entity. A "class" is a real, ordinary recurring event
(`events` table) tagged with its course's project-enabled label (and the
per-install "Schedule" system label, `schedule_settings.schedule_label`,
so it can be told apart from an ad hoc one-off event that merely also
carries the course label -- an exam, a guest lecture). This module is pure
recurrence math (first occurrence, RRULE/EXDATE generation, conflict
detection); routers/schedule.py wires it to real `db.upsert_event` calls.

Course-level facts that describe the whole course rather than any one
meeting -- acronym, type, credits, instructor -- live on the course
label's own `label_config` row (see db.py's `label_config` CREATE TABLE
comment), not on these events; there's no standard VEVENT property for
"credits" or "professor" to round-trip them through, and inventing one
would violate features/architecture.md §1.4's "no made-up X- properties"
rule. Only day/time/parity/room/title genuinely belong to a specific
recurring meeting, and those already have a real VEVENT home
(start_at/end_at/RRULE/location/title).

Generalized non-working-day policy (named holiday calendars, independent
weekend exclusions) is a separate, not-yet-built 1.6 item -- this module
still reads the existing flat `schedule_holidays` date-range list, same as
before; see plans/STATE.md's next-slice note.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from . import recurrence_expand

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def iso_week_parity(d: date) -> str:
    """'odd' or 'even', by ISO-8601 week number -- the convention most
    European timetables already use."""
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
    ('all') or every 2 weeks (odd/even)."""
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


# --------------------------------------------------------------------- #
# Deriving day/parity off a real event -- never stored, same "compute on
# read" rule as every other derived value in this app (features/
# architecture.md §6). Once a class IS a real event, its own start_at and
# recurrence string are the single source of truth for when it happens.
# --------------------------------------------------------------------- #


def event_day(event: dict[str, Any]) -> str | None:
    """Weekday name ('Monday'..'Sunday') this event's own `start_at` falls
    on, or None if it has no start_at."""
    start_at = event.get("start_at")
    if not start_at:
        return None
    try:
        d = datetime.fromisoformat(start_at).date()
    except ValueError:
        return None
    return DAYS[d.weekday()]


def event_parity(event: dict[str, Any]) -> str:
    """'all'/'odd'/'even', derived from the RRULE's INTERVAL -- 'all' for a
    plain weekly rule (INTERVAL absent or 1) or a non-recurring event."""
    recurrence = (event.get("recurrence") or "").upper()
    if "INTERVAL=2" not in recurrence:
        return "all"
    day = event_day(event)
    start_at = event.get("start_at")
    if not day or not start_at:
        return "all"
    return iso_week_parity(datetime.fromisoformat(start_at).date())


def next_occurrence_for_event(
    event: dict[str, Any], today: date | None = None, horizon_days: int = 400
) -> date | None:
    """Next date (>= today) this recurring event actually occurs, honoring
    its own RRULE + EXDATE list (via `recurrence_expand.expand_events`, the
    same RFC 5545 expansion the Calendar tab itself uses) -- used for the
    "next lecture" badges on a course's label page and the Space-filtered
    calendar agenda. A non-recurring event just returns its own date if
    that's still >= today."""
    today = today or date.today()
    window_end = today + timedelta(days=horizon_days)
    occurrences = recurrence_expand.expand_events([event], today, window_end)
    dates: list[date] = []
    for occ in occurrences:
        start_at = occ.get("start_at")
        if not start_at:
            continue
        try:
            d = datetime.fromisoformat(start_at).date()
        except ValueError:
            continue
        if d >= today:
            dates.append(d)
    return min(dates) if dates else None


def next_label(next_date: date, today: date | None = None) -> str:
    """Label for a "next lecture" badge: 'today', 'tomorrow', or 'in N
    days'."""
    today = today or date.today()
    delta = (next_date - today).days
    if delta <= 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return f"in {delta} days"


# --------------------------------------------------------------------- #
# Building the recurring event row for one class meeting.
# --------------------------------------------------------------------- #


def build_class_event_row(
    fields: dict[str, Any], settings: dict[str, Any], holidays: list[dict[str, str]], today: date | None = None
) -> dict[str, Any]:
    """The real recurring `events` row for one class meeting (a lecture, a
    seminar, ...). Unlike the pre-1.6 `class_to_event_row` this never
    returns None -- there's no separate `schedule_classes` row backing a
    class anymore, so the event this function builds IS the class's only
    record; a class entered before the semester's dates are configured
    still needs somewhere to live; it just isn't a *recurring* event yet.

    Anchor date: the semester start if configured, otherwise the first
    matching day/parity on or after `today` -- a placeholder that gets
    replaced with the real semester-anchored date the moment semester_start
    is saved (every settings/holiday change re-calls this for every class
    event, see routers/schedule.py's `_regenerate_all`). Recurrence: open-
    ended (no UNTIL, no EXDATEs) until semester_end is also configured --
    "Blocks only generate real calendar occurrences once both semester
    dates are set" no longer means *no event*, just *no recurrence yet*.

    `fields`: {uid, day, start_time, end_time, title, room, parity,
    enrolled} -- everything that's actually this *meeting's* own, not the
    course's (acronym/type/credits/professor live on the course label's
    label_config row instead, see this module's docstring)."""
    today = today or date.today()
    semester_start = settings.get("semester_start")
    semester_end = settings.get("semester_end")
    parity = fields.get("parity") or "all"

    start_date = date.fromisoformat(semester_start) if semester_start else today
    anchor = first_occurrence(start_date, fields["day"], parity)

    start_at = f"{anchor.isoformat()}T{fields['start_time']}:00"
    end_at = f"{anchor.isoformat()}T{fields['end_time']}:00"

    recurrence_parts = ["FREQ=WEEKLY"]
    if parity in ("odd", "even"):
        recurrence_parts.append("INTERVAL=2")
    exdates: list[str] = []
    if semester_end:
        end_date = date.fromisoformat(semester_end)
        if anchor > end_date:
            # The semester is too short for this day/parity to ever land --
            # keep the meeting itself (still editable/re-schedulable), just
            # with no occurrences: UNTIL equal to the anchor's own date,
            # excluded outright, rather than silently reverting to
            # open-ended (which would generate occurrences past a semester
            # that's already fully configured).
            exdates = [start_at]
            recurrence_parts.append(f"UNTIL={anchor.isoformat()}")
        else:
            occurrences = generate_occurrences(anchor, end_date, parity)
            excluded = compute_excluded(occurrences, holidays)
            exdates = [f"{d.isoformat()}T{fields['start_time']}:00" for d in excluded]
            recurrence_parts.append(f"UNTIL={end_date.isoformat()}")

    return {
        "uid": fields["uid"],
        "title": fields.get("title") or "Class",
        "description": "",
        "start_at": start_at,
        "end_at": end_at,
        "all_day": False,
        "location": fields.get("room") or None,
        "status": "active" if fields.get("enrolled", True) else "archived",
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


def compute_conflicts(events: list[dict[str, Any]]) -> list[tuple[dict, dict]]:
    """Two active (non-archived, i.e. 'enrolled') class events only
    conflict if they land on the same day, overlap in time, AND could
    actually land on the same real date -- an odd-week meeting and an
    even-week meeting in the same slot alternate and never truly clash.
    Day/time-of-day/parity are all derived from each event's own
    start_at/end_at/recurrence, never a separate stored field."""
    enrolled = [e for e in events if e.get("status") != "archived"]
    conflicts = []
    for i in range(len(enrolled)):
        for j in range(i + 1, len(enrolled)):
            a, b = enrolled[i], enrolled[j]
            if event_day(a) != event_day(b) or event_day(a) is None:
                continue
            if not _parity_compatible(event_parity(a), event_parity(b)):
                continue
            a_start, a_end = a["start_at"][11:16], a["end_at"][11:16]
            b_start, b_end = b["start_at"][11:16], b["end_at"][11:16]
            if _time_overlap(a_start, a_end, b_start, b_end):
                conflicts.append((a, b))
    return conflicts
