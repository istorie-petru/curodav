"""Quick Capture parser (plans/quick-capture.md) -- a single-field input
method for creating a task/event/contact/note without opening a dedicated
form. Pure functions only: nothing here touches the database (that's
routers/quick_capture.py's job, which also runs label resolution via
db.resolve_capture_label -- deliberately not called from here, so this
module stays trivially unit-testable with no `conn` fixture at all).

Grammar, per the design doc:

  - An entity marker -- `!t` (task), `!e` (event), `!c` (contact), `!n`
    (note) -- selects the entity type. May appear anywhere in the input;
    the first one found wins if more than one marker-looking token is
    present (an edge case the spec doesn't cover).
  - `#label` tokens (anywhere) are labels, extracted independently of
    type.
  - Dates are `D/M/YYYY` (unambiguous) or `D/M` (year inferred: the next
    occurrence of that day/month on or after `today`, i.e. this year
    unless that date has already passed, in which case next year -- the
    spec's own short-form examples, e.g. "2/08", never specify a year).
  - Time ranges are `H:MM-H:MM`.
  - Every recognized token is whitespace-delimited (matches every example
    in the design doc) -- this parser does not attempt to recognize a
    marker/date/label glued to adjacent text with no space.

See parse_task/parse_event/parse_contact/parse_note below for the
per-type rules; `parse()` is the single dispatch entry point
routers/quick_capture.py calls."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

MARKER_TYPES = {"t": "task", "e": "event", "c": "contact", "n": "note"}

_MARKER_RE = re.compile(r"^!([tecn])$")
_LABEL_RE = re.compile(r"^#([^\s#]+)$")
_DATE_FULL_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_DATE_SHORT_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")
_TIME_RANGE_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
_PHONE_RE = re.compile(r"^\+\d{6,15}$")


class QuickCaptureError(ValueError):
    """Raised when `text` has no recognizable marker, or a recognized
    token's value doesn't actually parse (e.g. `32/13/2026`)."""


@dataclass
class TimeBlock:
    date_iso: str  # YYYY-MM-DD
    start: str  # HH:MM
    end: str  # HH:MM


@dataclass
class ParsedCapture:
    type: str  # "task" | "event" | "contact" | "note"
    title: str = ""
    labels: list[str] = field(default_factory=list)
    # Task-only:
    due_date_iso: str | None = None
    timeblocks: list[TimeBlock] = field(default_factory=list)
    # Event-only:
    start_iso: str | None = None  # date or datetime, see to_event_fields
    end_iso: str | None = None
    all_day: bool = False
    # Contact-only:
    phone: str | None = None
    email: str | None = None
    # Note-only:
    content: str = ""


def _find_marker(tokens: list[str]) -> tuple[int, str]:
    for i, tok in enumerate(tokens):
        m = _MARKER_RE.match(tok)
        if m:
            return i, MARKER_TYPES[m.group(1)]
    raise QuickCaptureError("No entity marker (!t task / !e event / !c contact / !n note) found.")


def _resolve_date(day: int, month: int, year: int | None, today: date) -> date:
    try:
        if year is not None:
            return date(year, month, day)
        # Short form (no year) -- the next occurrence of this day/month on
        # or after `today`: this year unless it's already passed, then
        # next year. Matches the design doc's own short-date examples
        # ("2/08", "5/09"), none of which specify a year.
        candidate = date(today.year, month, day)
        if candidate < today:
            candidate = date(today.year + 1, month, day)
        return candidate
    except ValueError as exc:
        raise QuickCaptureError(f"'{day}/{month}' isn't a valid date.") from exc


def _parse_date_token(tok: str, today: date) -> date | None:
    m = _DATE_FULL_RE.match(tok)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        return _resolve_date(d, mo, y, today)
    m = _DATE_SHORT_RE.match(tok)
    if m:
        d, mo = (int(x) for x in m.groups())
        return _resolve_date(d, mo, None, today)
    return None


def _parse_time_range_token(tok: str) -> tuple[str, str] | None:
    m = _TIME_RANGE_RE.match(tok)
    if not m:
        return None
    h1, m1, h2, m2 = m.groups()
    for h in (h1, h2):
        if int(h) > 23:
            raise QuickCaptureError(f"'{tok}' isn't a valid time range.")
    for mm in (m1, m2):
        if int(mm) > 59:
            raise QuickCaptureError(f"'{tok}' isn't a valid time range.")
    return f"{int(h1):02d}:{m1}", f"{int(h2):02d}:{m2}"


def _extract_labels(tokens: list[str]) -> tuple[list[str], list[int]]:
    labels: list[str] = []
    consumed: list[int] = []
    for i, tok in enumerate(tokens):
        m = _LABEL_RE.match(tok)
        if m:
            labels.append(m.group(1))
            consumed.append(i)
    return labels, consumed


def parse_task(tokens: list[str], today: date) -> ParsedCapture:
    """`!t` -- plans/quick-capture.md § Tasks. The first standalone date
    (one NOT immediately followed by a time-range token) is the due date;
    every date immediately followed by a time-range token is a timeblock's
    date instead. Both are removed from the title; only the FIRST
    standalone date becomes `due_date_iso` (further bare dates, an
    undocumented edge case, are still stripped from the title but
    otherwise ignored -- see this module's own docstring)."""
    labels, label_idx = _extract_labels(tokens)
    consumed = set(label_idx)
    timeblocks: list[TimeBlock] = []
    due_date: date | None = None

    i = 0
    while i < len(tokens):
        if i in consumed:
            i += 1
            continue
        d = _parse_date_token(tokens[i], today)
        if d is not None:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            tr = _parse_time_range_token(nxt) if nxt else None
            if tr is not None:
                timeblocks.append(TimeBlock(date_iso=d.isoformat(), start=tr[0], end=tr[1]))
                consumed.add(i)
                consumed.add(i + 1)
                i += 2
                continue
            consumed.add(i)
            if due_date is None:
                due_date = d
        i += 1

    title = " ".join(tok for i, tok in enumerate(tokens) if i not in consumed).strip()
    return ParsedCapture(
        type="task",
        title=title,
        labels=labels,
        due_date_iso=due_date.isoformat() if due_date else None,
        timeblocks=timeblocks,
    )


def parse_event(tokens: list[str], today: date) -> ParsedCapture:
    """`!e` -- plans/quick-capture.md § Events. The first date token found
    is the event's date; if immediately followed by a time range, that's
    the start/end time-of-day (a timed event). A date with no following
    time range makes an all-day event. No date at all is allowed too (an
    undated event, left for the user to schedule on the form) -- the spec
    doesn't require a date, only shows it in every example."""
    labels, label_idx = _extract_labels(tokens)
    consumed = set(label_idx)
    start_date: date | None = None
    times: tuple[str, str] | None = None

    i = 0
    while i < len(tokens):
        if i in consumed:
            i += 1
            continue
        if start_date is None:
            d = _parse_date_token(tokens[i], today)
            if d is not None:
                start_date = d
                consumed.add(i)
                nxt = tokens[i + 1] if i + 1 < len(tokens) else None
                tr = _parse_time_range_token(nxt) if nxt else None
                if tr is not None:
                    times = tr
                    consumed.add(i + 1)
                    i += 2
                    continue
        i += 1

    title = " ".join(tok for i, tok in enumerate(tokens) if i not in consumed).strip()
    all_day = start_date is not None and times is None
    start_iso = end_iso = None
    if start_date is not None:
        if times is not None:
            start_iso = f"{start_date.isoformat()}T{times[0]}:00"
            end_iso = f"{start_date.isoformat()}T{times[1]}:00"
        else:
            start_iso = f"{start_date.isoformat()}T00:00:00"
            end_iso = f"{start_date.isoformat()}T23:59:00"
    return ParsedCapture(
        type="event",
        title=title,
        labels=labels,
        start_iso=start_iso,
        end_iso=end_iso,
        all_day=all_day,
    )


def parse_contact(tokens: list[str], today: date) -> ParsedCapture:
    """`!c` -- plans/quick-capture.md § Contacts. Every recognized phone/
    email token is stripped from the name regardless of position; only the
    first of each is kept -- Quick Capture's free-text grammar has no way to
    express "this is a second phone number" or a type for either, so it
    deliberately stays single-value even though contacts themselves are
    multi-value as of Contacts field parity slice 2 of 6 (routers/
    quick_capture.py stores whatever's captured here as one "Other"-typed
    entry -- see that module for why)."""
    labels, label_idx = _extract_labels(tokens)
    consumed = set(label_idx)
    phone: str | None = None
    email: str | None = None
    for i, tok in enumerate(tokens):
        if i in consumed:
            continue
        if _EMAIL_RE.match(tok):
            consumed.add(i)
            if email is None:
                email = tok
        elif _PHONE_RE.match(tok):
            consumed.add(i)
            if phone is None:
                phone = tok

    name = " ".join(tok for i, tok in enumerate(tokens) if i not in consumed).strip()
    return ParsedCapture(type="contact", title=name, labels=labels, phone=phone, email=email)


def parse_note(tokens: list[str], today: date) -> ParsedCapture:
    """`!n` -- plans/quick-capture.md § Notes. Only the marker and any
    `#label` tokens are control syntax removed from the body; dates/times
    are left as ordinary content ("do not automatically change the entity
    type" -- and, by extension, aren't extracted out of the text either)."""
    labels, label_idx = _extract_labels(tokens)
    consumed = set(label_idx)
    content = " ".join(tok for i, tok in enumerate(tokens) if i not in consumed).strip()
    return ParsedCapture(type="note", title=content, labels=labels, content=content)


_PARSERS = {"task": parse_task, "event": parse_event, "contact": parse_contact, "note": parse_note}


def parse(text: str, today: date | None = None) -> ParsedCapture:
    """Dispatch entry point. Raises QuickCaptureError if `text` has no
    marker or a malformed date/time token; never returns a partially-
    invalid result."""
    today = today or datetime.now().date()
    tokens = text.split()
    if not tokens:
        raise QuickCaptureError("Nothing to capture.")
    marker_idx, entity_type = _find_marker(tokens)
    remaining = tokens[:marker_idx] + tokens[marker_idx + 1 :]
    result = _PARSERS[entity_type](remaining, today)
    if entity_type in ("task", "contact") and not result.title:
        raise QuickCaptureError(f"A {entity_type} needs a title." if entity_type == "task" else "A contact needs a name.")
    if entity_type == "event" and not result.title:
        raise QuickCaptureError("An event needs a title.")
    if entity_type == "note" and not result.content:
        raise QuickCaptureError("A note needs some content.")
    return result
