"""Repeating events as real rows.

A repeating event is a series: every occurrence is its own event row (same `series_uid`), so each one can be edited,
moved or deleted like any other event. Before and after are relative: "this and following" is every row of the
series that starts from this one on. The series row keeps the rule, only to know how to extend an open-ended series
and to describe it. Rows are created ahead to a horizon and topped up daily (`ensure_horizon`).
Feature notes: curodav-notes/documentation/features/recurring-events.md.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from dateutil.rrule import rrulestr

from . import clock, db, ical_rows, recurrence_expand

HORIZON_DAYS = 730
MAX_ROWS = 3000
_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


class CannotShift(ValueError):
    pass


# ---------------------------------------------------------------- rule helpers

def parts_of(rule: str) -> dict[str, str]:
    return {k.upper(): v for k, v in (p.split("=", 1) for p in (rule or "").split(";") if "=" in p)}


def join_parts(parts: dict[str, str]) -> str:
    return ";".join(f"{k}={v}" for k, v in parts.items())


def valid_rule(rule: str) -> bool:
    try:
        safe, _ = ical_rows._normalize_rrule(rule, True)
        rrulestr("RRULE:" + safe, dtstart=datetime(2026, 1, 1, 9, 0))
        return bool(parts_of(rule).get("FREQ"))
    except Exception:  # noqa: BLE001 -- any parser error means "not a rule"
        return False


def shift_rule(rule: str, delta_days: int) -> str:
    """The rule with its anchor days moved by `delta_days`; CannotShift when that is not well defined."""
    if not delta_days:
        return rule
    parts = parts_of(rule)
    freq = parts.get("FREQ", "").upper()
    if freq == "WEEKLY" and "BYDAY" in parts:
        days = []
        for token in parts["BYDAY"].split(","):
            token = token.strip().upper()
            if token not in _DAYS:
                raise CannotShift("ordinal weekdays")
            days.append(_DAYS[(_DAYS.index(token) + delta_days) % 7])
        parts["BYDAY"] = ",".join(days)
    elif freq == "MONTHLY" and "BYMONTHDAY" in parts:
        try:
            nums = [int(n) + delta_days for n in parts["BYMONTHDAY"].split(",")]
        except ValueError:
            raise CannotShift("month days") from None
        if any(n < 1 or n > 28 for n in nums):
            raise CannotShift("month days near the end of the month")
        parts["BYMONTHDAY"] = ",".join(str(n) for n in nums)
    elif any(k in parts for k in ("BYDAY", "BYSETPOS", "BYMONTHDAY", "BYMONTH", "BYYEARDAY", "BYWEEKNO")):
        raise CannotShift("this kind of rule")
    return join_parts(parts)


def shiftable(rule: str) -> bool:
    """Whether the rule can be moved by whole days; the "move all future ones" offer is only made when it can."""
    try:
        shift_rule(rule, 1)
        return True
    except CannotShift:
        return False


def _safe_delta(rule: str, delta: timedelta) -> timedelta:
    """`delta` when the rule can follow it; otherwise only its time-of-day part (later events keep their days)."""
    if not delta.days or shiftable(rule):
        return delta
    return timedelta(seconds=delta.seconds)


def _minute(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None) if value else None
    except ValueError:
        return None


def _fmt(d: datetime, like: str | None) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S" if like and len(like) > 16 else "%Y-%m-%dT%H:%M")


def _rrule(rule: str, anchor: datetime):
    safe, exdates = ical_rows._normalize_rrule(rule, True)
    return rrulestr("RRULE:" + safe, dtstart=anchor), exdates


def _days_between(a: datetime, b: datetime) -> int:
    return (b.date() - a.date()).days


def _is_open(rule: str) -> bool:
    parts = parts_of(rule)
    return "UNTIL" not in parts and "COUNT" not in parts


# ---------------------------------------------------------------- storage

def get_series(conn, series_uid: str | None) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM event_series WHERE uid = ?", (series_uid,)).fetchone() if series_uid else None
    return dict(row) if row else None


def members(conn, series_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT uid FROM events WHERE series_uid = ? ORDER BY start_at, uid", (series_uid,)).fetchall()
    return [db.get_event(conn, r["uid"]) for r in rows]


def _save_series(conn, series: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO event_series (uid, rule, anchor, extended_until, holiday_calendar, exclude_saturday, exclude_sunday) "
        "VALUES (:uid, :rule, :anchor, :extended_until, :holiday_calendar, :exclude_saturday, :exclude_sunday) "
        "ON CONFLICT(uid) DO UPDATE SET rule=excluded.rule, anchor=excluded.anchor, extended_until=excluded.extended_until, "
        "holiday_calendar=excluded.holiday_calendar, exclude_saturday=excluded.exclude_saturday, exclude_sunday=excluded.exclude_sunday",
        {"holiday_calendar": None, "exclude_saturday": 0, "exclude_sunday": 0, **series},
    )
    conn.commit()


def _occurrence_row(template: dict[str, Any], start: datetime, duration: timedelta | None, uid: str, series_uid: str) -> dict[str, Any]:
    row = {k: v for k, v in template.items() if k not in ("uid", "series_uid", "exdates")}
    like = template.get("start_at")
    row.update(uid=uid, series_uid=series_uid, recurrence=None, start_at=_fmt(start, like),
               end_at=_fmt(start + duration, template.get("end_at") or like) if duration is not None else None,
               )
    return row


def _generate(conn, series: dict[str, Any], template: dict[str, Any], first_uid: str | None, after: datetime | None,
              limit: datetime, overrides: dict[str, dict] | None = None, exdates_extra: list[date] | None = None) -> int:
    """Creates the series' rows after `after` up to `limit`; returns how many."""
    anchor = _minute(series["anchor"])
    rule, rule_exdates = _rrule(series["rule"], anchor)
    skip = set(rule_exdates) | set(exdates_extra or [])
    calendars = db.list_holidays_by_calendar(conn)
    policy = {"holiday_calendar": series.get("holiday_calendar"), "exclude_saturday": series.get("exclude_saturday"),
              "exclude_sunday": series.get("exclude_sunday")}
    start0, end0 = _minute(template["start_at"]), _minute(template.get("end_at"))
    duration = (end0 - start0) if (start0 and end0 and end0 >= start0) else None
    contacts = [c["uid"] for c in db.list_object_contacts(conn, "event", template["uid"])] if template.get("uid") else []
    made = 0
    existing = conn.execute("SELECT COUNT(*) FROM events WHERE series_uid = ?", (series["uid"],)).fetchone()[0]
    for occ in rule.between(after + timedelta(seconds=1) if after else anchor - timedelta(seconds=1), limit, inc=True):
        if existing + made >= MAX_ROWS:
            break
        if occ.date() in skip or recurrence_expand.is_excluded_by_policy(occ.date(), policy, calendars):
            continue
        key = _fmt(occ, template["start_at"])
        override = (overrides or {}).get(key) or (overrides or {}).get(occ.strftime("%Y-%m-%dT%H:%M:%S")) or (overrides or {}).get(occ.strftime("%Y-%m-%dT%H:%M"))
        if override and override.get("cancelled"):
            continue
        uid = first_uid if (first_uid and made == 0 and occ == anchor) else str(uuid.uuid4())
        row = _occurrence_row(template, occ, duration, uid, series["uid"])
        if override:
            if override.get("start_at"):
                moved = _minute(override["start_at"])
                row["start_at"] = _fmt(moved, template["start_at"])
                row["end_at"] = (override.get("end_at") or (_fmt(moved + duration, template["start_at"]) if duration is not None else None))
            for field in ("title", "location"):
                if override.get(field):
                    row[field] = override[field]
        db.upsert_event(conn, row)
        if contacts:
            db.set_object_contacts(conn, "event", uid, contacts)
        made += 1
    return made


def create_series(conn, row: dict[str, Any], rule: str, today: date | None = None, contacts: list[str] | None = None) -> str:
    """Turns `row` (an event being created) into a series; returns the first occurrence's uid (`row`'s own)."""
    today = today or clock.today()
    start = _minute(row["start_at"])
    if not start or not valid_rule(rule):
        raise ValueError("Recurrence is not a valid rule")
    series = {"uid": str(uuid.uuid4()), "rule": rule, "anchor": _fmt(start, row["start_at"]), "extended_until": None,
              "holiday_calendar": row.get("holiday_calendar"), "exclude_saturday": 1 if row.get("exclude_saturday") else 0,
              "exclude_sunday": 1 if row.get("exclude_sunday") else 0}
    limit = datetime.combine(max(today, start.date()) + timedelta(days=HORIZON_DAYS), datetime.max.time()).replace(microsecond=0)
    series["extended_until"] = limit.strftime("%Y-%m-%d")
    _save_series(conn, series)
    template = dict(row, recurrence=None)
    made = _generate(conn, series, template, row["uid"], None, limit)
    existing = db.get_event(conn, row["uid"])
    if not made:
        # Every occurrence was excluded: keep the event itself so nothing is lost.
        db.upsert_event(conn, dict(row, series_uid=series["uid"], recurrence=None))
    elif existing is not None and existing.get("series_uid") != series["uid"]:
        db.delete_event(conn, row["uid"])  # the event's own slot is not part of the rule
    if contacts is not None:
        for r in members(conn, series["uid"]):
            db.set_object_contacts(conn, "event", r["uid"], contacts)
    return row["uid"]


def migrate_master(conn, master: dict[str, Any], today: date | None = None) -> bool:
    """Replaces a legacy repeating event (an RRULE plus exceptions) by real rows; False when its rule cannot be read."""
    rule = (master.get("recurrence") or "").strip()
    start = _minute(master.get("start_at"))
    if not rule or not start or not valid_rule(rule):
        return False
    today = today or clock.today()
    overrides = {o["occurrence_date"]: o for o in db.list_event_occurrence_overrides(conn, master["uid"])}
    series = {"uid": str(uuid.uuid4()), "rule": rule, "anchor": _fmt(start, master["start_at"]), "extended_until": None,
              "holiday_calendar": master.get("holiday_calendar"), "exclude_saturday": 1 if master.get("exclude_saturday") else 0,
              "exclude_sunday": 1 if master.get("exclude_sunday") else 0}
    limit = datetime.combine(max(today, start.date()) + timedelta(days=HORIZON_DAYS), datetime.max.time()).replace(microsecond=0)
    series["extended_until"] = limit.strftime("%Y-%m-%d")
    _save_series(conn, series)
    exdates = [d for d in (_to_date(x) for x in (master.get("exdates") or [])) if d]
    template = dict(master, recurrence=None)
    made = _generate(conn, series, template, master["uid"], None, limit, overrides, exdates)
    conn.execute("DELETE FROM event_occurrence_overrides WHERE master_uid = ?", (master["uid"],))
    row = db.get_event(conn, master["uid"])
    if row is not None and row.get("series_uid") != series["uid"]:
        db.delete_event(conn, master["uid"], record_server_write=False)  # its own slot was cancelled or moved away
    if not made:
        db.upsert_event(conn, dict(master, recurrence=None, series_uid=series["uid"]))
    conn.commit()
    return True


def _to_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def ensure_horizon(conn, today: date | None = None) -> int:
    """Tops up every open-ended series to the horizon; returns the number of rows added."""
    today = today or clock.today()
    target = today + timedelta(days=HORIZON_DAYS)
    added = 0
    for s in conn.execute("SELECT * FROM event_series").fetchall():
        series = dict(s)
        if not _is_open(series["rule"]) or (series["extended_until"] or "") >= target.isoformat():
            continue
        rows = members(conn, series["uid"])
        if not rows:
            continue
        template = rows[-1]
        after = datetime.fromisoformat(series["extended_until"] + "T23:59:59") if series["extended_until"] else _minute(template["start_at"])
        limit = datetime.combine(target, datetime.max.time()).replace(microsecond=0)
        added += _generate(conn, series, template, None, after, limit)
        series["extended_until"] = target.isoformat()
        _save_series(conn, series)
    return added


_last_ensure: date | None = None


def ensure_horizon_daily(conn) -> None:
    global _last_ensure
    today = clock.today()
    if _last_ensure != today:
        _last_ensure = today
        ensure_horizon(conn, today)


# ---------------------------------------------------------------- scoped operations

def scope_rows(conn, uid: str, scope: str) -> list[dict[str, Any]]:
    """The rows a scope covers: "this", "following" (this one and every later one) or "all"."""
    event = db.get_event(conn, uid)
    if not event or not event.get("series_uid") or scope == "this":
        return [event] if event else []
    rows = members(conn, event["series_uid"])
    if scope == "all":
        return rows
    return [r for r in rows if (r["start_at"], r["uid"]) >= (event["start_at"], event["uid"])]


def delete_scope(conn, uid: str, scope: str) -> int:
    """Deletes one occurrence, it and every later one, or the whole series; returns the number of rows deleted."""
    event = db.get_event(conn, uid)
    if not event:
        return 0
    rows = scope_rows(conn, uid, scope)
    series_uid = event.get("series_uid")
    for r in rows:
        db.delete_event(conn, r["uid"])
    if series_uid:
        left = members(conn, series_uid)
        if not left:
            conn.execute("DELETE FROM event_series WHERE uid = ?", (series_uid,))
            conn.commit()
        elif scope == "following":
            _end_rule_before(conn, series_uid, _minute(event["start_at"]), len(left))
    return len(rows)


def _end_rule_before(conn, series_uid: str, cut: datetime, remaining: int | None = None) -> None:
    series = get_series(conn, series_uid)
    if not series:
        return
    parts = parts_of(series["rule"])
    if "COUNT" in parts:
        parts["COUNT"] = str(remaining if remaining is not None else conn.execute(
            "SELECT COUNT(*) FROM events WHERE series_uid = ?", (series_uid,)).fetchone()[0])
    else:
        parts.pop("UNTIL", None)
        parts["UNTIL"] = (cut - timedelta(days=1)).strftime("%Y-%m-%d")
    series["rule"] = join_parts(parts)
    _save_series(conn, series)


def _shift_row(row: dict[str, Any], delta: timedelta) -> dict[str, Any]:
    like = row["start_at"]
    out = dict(row)
    out["start_at"] = _fmt(_minute(row["start_at"]) + delta, like)
    if row.get("end_at"):
        out["end_at"] = _fmt(_minute(row["end_at"]) + delta, row["end_at"])
    return out


def split_following(conn, uid: str, delta: timedelta = timedelta(0)) -> str:
    """Makes this occurrence and every later one a series of their own (optionally moved by `delta`); returns its uid."""
    event = db.get_event(conn, uid)
    series = get_series(conn, event.get("series_uid")) if event else None
    if not series:
        return ""
    rows = scope_rows(conn, uid, "following")
    if len(rows) == len(members(conn, series["uid"])):
        return series["uid"]  # already the whole series
    before = len(members(conn, series["uid"])) - len(rows)
    old_parts, new_parts = parts_of(series["rule"]), parts_of(series["rule"])
    if "COUNT" in old_parts:
        old_parts["COUNT"] = str(before)
        new_parts["COUNT"] = str(len(rows))
    else:
        old_parts.pop("UNTIL", None)
        old_parts["UNTIL"] = (_minute(event["start_at"]) - timedelta(days=1)).strftime("%Y-%m-%d")
    new_rule = join_parts(new_parts)
    delta = _safe_delta(new_rule, delta)
    if delta:
        new_rule = shift_rule(new_rule, _days_between(_minute(event["start_at"]), _minute(event["start_at"]) + delta))
    new_series = dict(series, uid=str(uuid.uuid4()), rule=new_rule,
                      anchor=_fmt(_minute(event["start_at"]) + delta, event["start_at"]))
    _save_series(conn, dict(series, rule=join_parts(old_parts), extended_until=series["extended_until"]))
    _save_series(conn, new_series)
    for r in rows:
        conn.execute("UPDATE events SET series_uid = ? WHERE uid = ?", (new_series["uid"], r["uid"]))
    conn.commit()
    return new_series["uid"]


def shift_following(conn, uid: str, delta: timedelta) -> int:
    """Moves every later occurrence of this one's series by `delta` (this one is already moved)."""
    event = db.get_event(conn, uid)
    if not event or not event.get("series_uid") or not delta:
        return 0
    rows = [r for r in members(conn, event["series_uid"]) if r["uid"] != uid and (r["start_at"], r["uid"]) > (event["start_at"], event["uid"])]
    if not rows:
        return 0
    first = rows[0]
    delta = _safe_delta((get_series(conn, event["series_uid"]) or {}).get("rule", ""), delta)
    if not delta:
        return 0
    new_series_uid = split_following(conn, first["uid"], delta)
    for r in members(conn, new_series_uid):
        if r["uid"] in {x["uid"] for x in rows}:
            db.upsert_event(conn, _shift_row(r, delta))
    return len(rows)


def apply_edit(conn, uid: str, scope: str, fields: dict[str, Any], delta_start: timedelta, delta_end: timedelta,
               tags: list[str] | None, contacts: list[str] | None, exact: tuple[str, str | None] | None = None) -> int:
    """Saves an edit onto a scope: `fields` (title, description, ...) on every row, start and end moved by their deltas."""
    series0 = get_series(conn, (db.get_event(conn, uid) or {}).get("series_uid"))
    if series0:
        delta_start = _safe_delta(series0["rule"], delta_start)
    if scope == "following":
        split_following(conn, uid, delta_start)
    rows = scope_rows(conn, uid, scope)
    if scope == "all" and delta_start and rows:
        series = get_series(conn, rows[0].get("series_uid"))
        if series:
            anchor = _minute(series["anchor"])
            series["rule"] = shift_rule(series["rule"], _days_between(anchor, anchor + delta_start))
            series["anchor"] = _fmt(anchor + delta_start, series["anchor"])
            _save_series(conn, series)
    for r in rows:
        row = dict(r, **fields)
        if delta_start:
            row["start_at"] = _fmt(_minute(r["start_at"]) + delta_start, r["start_at"])
        if row.get("end_at") and delta_end:
            row["end_at"] = _fmt(_minute(r["end_at"]) + delta_end, r["end_at"])
        if exact and r["uid"] == uid:
            row["start_at"], row["end_at"] = exact  # the edited event always takes exactly what was typed
        if tags is not None:
            row["tags"] = tags
        db.upsert_event(conn, row)
        if contacts is not None:
            db.set_object_contacts(conn, "event", r["uid"], contacts)
    return len(rows)


def change_rule(conn, uid: str, scope: str, new_rule: str, base: dict[str, Any], contacts: list[str] | None) -> str:
    """The rule of a series was edited: from this occurrence on ("following") or for the whole series ("all") the
    rows are rebuilt from `base` (the edited occurrence's new values). An empty rule stops the repetition: only
    `base` is kept. Returns the uid of the series now holding `base`, or "" when it is a single event again."""
    event = db.get_event(conn, uid)
    old_series_uid = event.get("series_uid")
    rows = scope_rows(conn, uid, "all" if scope == "all" else "following")
    keep = rows[0] if scope == "all" else event
    for r in rows:
        if r["uid"] != keep["uid"]:
            db.delete_event(conn, r["uid"])
    row = dict(base, uid=keep["uid"], series_uid=None, recurrence=None)
    if scope == "all":
        conn.execute("DELETE FROM event_series WHERE uid = ?", (old_series_uid,))
    else:
        left = conn.execute("SELECT COUNT(*) FROM events WHERE series_uid = ? AND uid != ?", (old_series_uid, keep["uid"])).fetchone()[0]
        if left:
            _end_rule_before(conn, old_series_uid, _minute(event["start_at"]), left)
        else:
            conn.execute("DELETE FROM event_series WHERE uid = ?", (old_series_uid,))
    conn.commit()
    if not new_rule:
        db.upsert_event(conn, row)
        if contacts is not None:
            db.set_object_contacts(conn, "event", keep["uid"], contacts)
        return ""
    create_series(conn, row, new_rule, contacts=contacts)
    return (db.get_event(conn, keep["uid"]) or {}).get("series_uid") or ""
