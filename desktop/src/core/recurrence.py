"""Recurrence rules -- expand a repeating task/event into occurrence dates.

Deliberately not a full RFC 5545 RRULE implementation (BYSETPOS, BYMONTH,
secondly/minutely frequencies, and their interactions are a project on their
own, and nothing in this app needs them). This covers what was actually
asked for: a schedule that repeats daily or weekly, on an interval, on
specific weekdays, until a date or for N occurrences, with specific dates
excepted (holidays, cancelled sessions) -- a class/work timetable, not an
arbitrary calendar feed.

The string encoding is intentionally RRULE-shaped (FREQ=/INTERVAL=/BYDAY=/
UNTIL=/COUNT=/EXDATE=) so it reads as a recognizable subset of the real
thing rather than a bespoke format, even though the parser only understands
the fields below.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Object

WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


@dataclass(frozen=True)
class RecurrenceRule:
    """A repeat pattern. `freq` is "daily" or "weekly".

    `weekdays` (weekly only) are 0=Monday..6=Sunday, matching `date.weekday()`.
    An empty `weekdays` set on a weekly rule means "the same weekday as the
    start date" (the common case: "every Tuesday" from a Tuesday start).
    Exactly one of `until` / `count` should be set; if both are None the
    rule repeats indefinitely (expansion is still bounded by the window
    passed to `expand_occurrences`, so this is safe to store and expand,
    just not to iterate to completion).
    """

    freq: str = "weekly"  # "daily" | "weekly"
    interval: int = 1
    weekdays: frozenset[int] = field(default_factory=frozenset)
    until: date | None = None
    count: int | None = None
    exceptions: frozenset[date] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.freq not in ("daily", "weekly"):
            raise ValueError(f"Unsupported freq: {self.freq!r}")
        if self.interval < 1:
            raise ValueError("interval must be >= 1")

    def to_rule_string(self) -> str:
        parts = [f"FREQ={self.freq.upper()}"]
        if self.interval != 1:
            parts.append(f"INTERVAL={self.interval}")
        if self.freq == "weekly" and self.weekdays:
            days = ",".join(WEEKDAY_CODES[d] for d in sorted(self.weekdays))
            parts.append(f"BYDAY={days}")
        if self.until is not None:
            parts.append(f"UNTIL={self.until.isoformat()}")
        if self.count is not None:
            parts.append(f"COUNT={self.count}")
        if self.exceptions:
            exdates = ",".join(d.isoformat() for d in sorted(self.exceptions))
            parts.append(f"EXDATE={exdates}")
        return ";".join(parts)

    @classmethod
    def from_rule_string(cls, s: str | None) -> RecurrenceRule | None:
        """Parse a rule string. Returns None for empty/None/unparseable input
        (treated as "not recurring", never raises -- a malformed or
        hand-edited value shouldn't crash the calendar)."""
        if not s or not s.strip():
            return None
        fields: dict[str, str] = {}
        for part in s.split(";"):
            if "=" not in part:
                continue
            key, _, value = part.partition("=")
            fields[key.strip().upper()] = value.strip()

        freq_raw = fields.get("FREQ", "").lower()
        if freq_raw not in ("daily", "weekly"):
            return None

        try:
            interval = int(fields["INTERVAL"]) if "INTERVAL" in fields else 1
        except ValueError:
            interval = 1

        weekdays: frozenset[int] = frozenset()
        if "BYDAY" in fields:
            codes = [c.strip().upper() for c in fields["BYDAY"].split(",") if c.strip()]
            weekdays = frozenset(
                WEEKDAY_CODES.index(c) for c in codes if c in WEEKDAY_CODES
            )

        until: date | None = None
        if "UNTIL" in fields:
            try:
                until = date.fromisoformat(fields["UNTIL"])
            except ValueError:
                until = None

        count: int | None = None
        if "COUNT" in fields:
            try:
                count = int(fields["COUNT"])
            except ValueError:
                count = None

        exceptions: frozenset[date] = frozenset()
        if "EXDATE" in fields:
            exc_dates = []
            for token in fields["EXDATE"].split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    exc_dates.append(date.fromisoformat(token))
                except ValueError:
                    continue
            exceptions = frozenset(exc_dates)

        try:
            return cls(
                freq=freq_raw,
                interval=max(1, interval),
                weekdays=weekdays,
                until=until,
                count=count,
                exceptions=exceptions,
            )
        except ValueError:
            return None


def expand_occurrences(
    rule: RecurrenceRule,
    dtstart: date,
    window_start: date,
    window_end: date,
    hard_cap: int = 2000,
) -> list[date]:
    """All occurrence dates of `rule` (anchored at `dtstart`) that fall
    within [window_start, window_end] inclusive, with `rule.exceptions`
    removed.

    The master event's own date/time is the source of truth (`dtstart`);
    occurrences are computed here on every call, never stored individually
    -- calendar views call this for whatever date range is on screen rather
    than materializing a row per occurrence anywhere.

    `hard_cap` bounds how many candidate dates get generated even for a
    huge or unbounded (`until`/`count` both None) rule with a wide window,
    so a bad rule can't hang the UI.
    """
    if window_end < window_start or window_end < dtstart:
        return []

    if rule.freq == "daily":
        step = timedelta(days=rule.interval)
        occurrences: list[date] = []
        current = dtstart
        n_generated = 0
        while current <= window_end and n_generated < hard_cap:
            if rule.until is not None and current > rule.until:
                break
            if rule.count is not None and n_generated >= rule.count:
                break
            if current >= window_start and current not in rule.exceptions:
                occurrences.append(current)
            current += step
            n_generated += 1
        return occurrences

    # weekly
    active_weekdays = rule.weekdays or {dtstart.weekday()}
    occurrences = []
    n_generated = 0
    # Walk week-by-week (by `interval` weeks) from the week containing dtstart.
    week_anchor = dtstart - timedelta(days=dtstart.weekday())  # Monday of dtstart's week
    week = week_anchor
    while week <= window_end and n_generated < hard_cap:
        for wd in sorted(active_weekdays):
            occ = week + timedelta(days=wd)
            if occ < dtstart:
                continue
            if rule.until is not None and occ > rule.until:
                continue
            n_generated += 1
            if rule.count is not None and n_generated > rule.count:
                break
            if window_start <= occ <= window_end and occ not in rule.exceptions:
                occurrences.append(occ)
        if rule.count is not None and n_generated >= rule.count:
            break
        week += timedelta(weeks=rule.interval)
    occurrences.sort()
    return occurrences


def expand_recurring_objects(
    objects: list[Object], window_start: date, window_end: date
) -> list[Object]:
    """Return `objects` plus one synthetic copy per extra occurrence of
    every recurring task/event whose expansion falls in [window_start,
    window_end] -- the calendar/task views' single integration point with
    this module.

    The master object (whatever `objects` already contains) is always
    included as-is and represents its own anchor date; this only adds
    *additional* occurrences, so a non-recurring object list round-trips
    unchanged. A recurring object's rule lives in `obj.details["recurrence"]`
    as an RRULE-subset string (see `RecurrenceRule`); the anchor date is
    `due_at` if set, else the date part of `start_at`. Synthetic copies
    keep the *same id* as the master -- clicking one still opens/edits the
    master event, matching the "master is the source of truth, occurrences
    are computed, never stored" principle the architecture doc has always
    specified. `due_at`, and `start_at`/`details["end_at"]` if present
    (shifted by the same day delta, preserving time-of-day and duration),
    are the only fields that differ per occurrence.
    """
    result: list[Object] = list(objects)

    for obj in objects:
        if not obj.details:
            continue
        rule = RecurrenceRule.from_rule_string(obj.details.get("recurrence"))
        if rule is None:
            continue

        anchor: date | None = None
        if obj.due_at:
            try:
                anchor = date.fromisoformat(obj.due_at[:10])
            except ValueError:
                anchor = None
        if anchor is None and obj.start_at:
            try:
                anchor = datetime.fromisoformat(obj.start_at).date()
            except ValueError:
                anchor = None
        if anchor is None:
            continue

        occurrences = expand_occurrences(rule, anchor, window_start, window_end)
        for occ_date in occurrences:
            if occ_date == anchor:
                continue  # the master object already represents this one
            delta = occ_date - anchor
            occurrence = copy.copy(obj)
            occurrence.due_at = occ_date.isoformat() if obj.due_at else obj.due_at
            if obj.start_at:
                try:
                    start_dt = datetime.fromisoformat(obj.start_at) + delta
                    occurrence.start_at = start_dt.isoformat()
                except ValueError:
                    pass
            if obj.details:
                occurrence.details = dict(obj.details)
                end_at = obj.details.get("end_at")
                if end_at:
                    try:
                        end_dt = datetime.fromisoformat(end_at) + delta
                        occurrence.details["end_at"] = end_dt.isoformat()
                    except ValueError:
                        pass
            result.append(occurrence)

    return result
