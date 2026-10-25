"""The study page: the University shelf's own page type. It shows the week as a grid coloured by discipline, the exams with a countdown,
the readings still open, and quick creation on an empty day. It reads classes by tag and date range from the event rows (a series is
never expanded here), so a semester of several hundred classes costs one small query per week."""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

from fastapi import Request

from . import clock, db, tags
from . import university_plan as up
from .deps import templates


def _week_start(request: Request, today: date) -> date:
    raw = request.query_params.get("week", "")
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        day = today
    return day - timedelta(days=day.weekday())


def _classes_between(conn, semester_uid: str, start: date, end: date) -> list[dict]:
    series = [r["series_uid"] for r in conn.execute("SELECT series_uid FROM university_slots WHERE semester_uid = ?", (semester_uid,))]
    if not series:
        return []
    marks = ", ".join("?" for _ in series)
    rows = conn.execute(
        f"SELECT uid, title, description, start_at, end_at, location, series_uid FROM events WHERE series_uid IN ({marks}) AND start_at >= ? AND start_at < ? "
        "ORDER BY start_at", (*series, start.isoformat(), (end + timedelta(days=1)).isoformat())).fetchall()
    return [dict(r) for r in rows]


def build(conn, semester: dict, week: date, today: date) -> dict:
    looks = {t["name"]: t for t in tags.tags_of_label(conn, semester["shelf_name"])}
    kinds = {r["series_uid"]: (r["kind"], r["discipline_tag"]) for r in conn.execute(
        "SELECT series_uid, kind, discipline_tag FROM university_slots WHERE semester_uid = ?", (semester["uid"],))}
    week_end = week + timedelta(days=6)
    classes = _classes_between(conn, semester["uid"], week, week_end)
    exams = up.list_exams(conn, semester["uid"], today=today)
    notes = up.class_notes_by_event(conn, [c["uid"] for c in classes])
    days = []
    for i in range(7):
        d = week + timedelta(days=i)
        iso = d.isoformat()
        day_classes = []
        for c in classes:
            if c["start_at"][:10] != iso:
                continue
            kind, tag = kinds.get(c["series_uid"], ("other", ""))
            day_classes.append({**c, "start": c["start_at"][11:16], "end": (c.get("end_at") or "")[11:16], "kind_label": up.SLOT_KINDS.get(kind, "Class"),
                                "discipline": tag, "note_uid": notes.get(c["uid"]), "look": looks.get(tag, {"color": "gray", "icon": ""})})
        day_exams = [{**e, "look": looks.get(e["discipline"], {"color": "gray", "icon": ""})} for e in exams if e["date"] == iso]
        days.append({"date": iso, "label": d.strftime("%a"), "day": d.day, "month": d.strftime("%b"), "is_today": d == today, "classes": day_classes,
                     "exams": day_exams, "new_url": f"/events/new?date={iso}&start_time=10:00&end_time=12:00"})
    upcoming = [{**e, "look": looks.get(e["discipline"], {"color": "gray", "icon": ""})} for e in exams if e["days_left"] >= 0][:4]
    readings = [{**r, "look": looks.get(r["discipline"], {"color": "gray", "icon": ""})} for r in up.list_readings(conn, semester["uid"])
                if r["status"] not in ("done", "archived")][:8]
    return {"days": days, "upcoming": upcoming, "readings": readings, "next_class": next_class(conn, semester, looks, kinds, today),
            "exams_this_week": [e for e in upcoming if week.isoformat() <= e["date"] <= week_end.isoformat()]}


def next_class(conn, semester: dict, looks: dict, kinds: dict, today: date) -> dict | None:
    series = list(kinds)
    if not series:
        return None
    marks = ", ".join("?" for _ in series)
    now = clock.local_now().strftime("%Y-%m-%dT%H:%M")
    row = conn.execute(f"SELECT uid, title, start_at, end_at, location, series_uid FROM events WHERE series_uid IN ({marks}) AND start_at >= ? "
                       "ORDER BY start_at LIMIT 1", (*series, now)).fetchone()
    if not row:
        return None
    kind, tag = kinds.get(row["series_uid"], ("other", ""))
    return {**dict(row), "start": row["start_at"][11:16], "day": row["start_at"][:10], "discipline": tag, "kind_label": up.SLOT_KINDS.get(kind, "Class"),
            "look": looks.get(tag, {"color": "gray", "icon": ""})}


def render(conn, request: Request, name: str, label: dict):
    semester = conn.execute("SELECT * FROM university_semesters WHERE shelf_name = ? COLLATE NOCASE", (name,)).fetchone()
    today = clock.today()
    ctx = {"request": request, "label": label, "name": name, "semester": dict(semester) if semester else None, "today": today.isoformat(),
           "settings_url": "/settings/university"}
    if semester:
        week = _week_start(request, today)
        ctx.update(build(conn, dict(semester), week, today))
        base = f"/labels/{quote(name, safe='')}"
        ctx.update(prev_url=f"{base}?week={(week - timedelta(days=7)).isoformat()}", next_url=f"{base}?week={(week + timedelta(days=7)).isoformat()}",
                   today_url=base, week_label=f"{week.strftime('%d %b')} to {(week + timedelta(days=6)).strftime('%d %b %Y')}")
    return templates.TemplateResponse("study_page.html", ctx)
