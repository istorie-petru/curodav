"""The study page: the page of the space that holds the University semester, with the views Overview, Disciplines and Examination.

Overview is a row of widget cards (the next class, the next examination, what is due, the semester, the absences), the weekly timetable
drawn with the calendar's own event blocks (odd weeks in the left half of a day, even weeks in the right half) and cards of short lists.
Examination is every exam and every piece of work of the semester. The timetable comes from the slots, so it is the same for any week;
the lists read the dated classes, milestones and tasks.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import quote

from fastapi import Request

from . import clock, db, grid_layout, tags
from . import university_attendance as ua
from . import university_evaluation as ue
from . import university_plan as up
from .deps import templates

_OPEN = ("done", "archived")
VIEWS = (("overview", "Overview"), ("disciplines", "Disciplines"), ("exams", "Examination"))


def _minutes(clock_text: str) -> int:
    hh, mm = (clock_text or "0:0").split(":")[:2]
    return int(hh) * 60 + int(mm)


def when(day: str | None, today: date) -> str:
    """A date as short as it can be said: "today", "tomorrow", "in 6 days", then "3 Nov"."""
    if not day:
        return "No date"
    d = date.fromisoformat(day[:10])
    n = (d - today).days
    if n < 0:
        return "overdue"
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if n <= 14:
        return f"in {n} days"
    return f"{d.day} {d.strftime('%b')}" + ("" if d.year == today.year else f" {d.year}")


def layout_day(blocks: list[dict], start_min: int, total_min: int) -> None:
    """Top and height in pixels, left and width in percent, of each block of one day. Odd-week classes take the left half, even-week
    classes the right half, weekly classes the whole width; blocks of one kind that overlap share their width."""
    base = {"all": (0.0, 100.0), "odd": (0.0, 50.0), "even": (50.0, 100.0)}
    for group in base:
        members = sorted([b for b in blocks if b["weeks"] == group], key=lambda x: (x["from"], x["to"]))
        lanes: list[int] = []
        for b in members:
            lane = next((i for i, end in enumerate(lanes) if end <= b["from"]), None)
            if lane is None:
                lanes.append(b["to"])
                lane = len(lanes) - 1
            else:
                lanes[lane] = b["to"]
            b["lane"] = lane
        count = max(len(lanes), 1)
        lo, hi = base[group]
        for b in members:
            width = (hi - lo) / count
            b.update(left=round(lo + b["lane"] * width, 3), width=round(width, 3))
    px = grid_layout.PX_PER_HOUR / 60
    for b in blocks:
        b.update(top=round((b["from"] - start_min) * px, 1), height=max(round((b["to"] - b["from"]) * px, 1), 18))


def schedule(conn, semester: dict, group: str, editing: bool = False) -> dict:
    """The weekly timetable: Monday to Friday, plus the weekend when a class falls on it. With `editing`, a block opens its slot and each
    empty hour adds a class at that hour, for the Settings page."""
    looks = {t["name"]: t for t in tags.tags_of_label(conn, semester["shelf_name"])}
    abbr = up.abbreviations(conn, semester["uid"])
    slots = up.list_slots(conn, semester["uid"])
    used = {s["weekday"] for s in slots}
    last_day = 6 if 6 in used else (5 if 5 in used else 4)
    first_h = min([_minutes(s["start"]) // 60 for s in slots] + [8])
    last_h = max([-(-_minutes(s["end"] or s["start"]) // 60) for s in slots] + [18 if editing else 16])
    start_min, total_min = first_h * 60, (last_h - first_h) * 60
    days = []
    for wd in range(last_day + 1):
        blocks = []
        for s in (x for x in slots if x["weekday"] == wd):
            look = looks.get(s["discipline"], {"color": "gray", "icon": ""})
            url = (f"/settings/university/slot/{s['series_uid']}/edit" if editing
                   else f"/groups/{quote(group, safe='')}/disciplines/{quote(s['discipline'], safe='')}")
            blocks.append({"discipline": s["discipline"], "short": abbr.get(s["discipline"], s["discipline"]), "color": look.get("color") or "gray", "weeks": s["weeks"],
                           "start": s["start"], "end": s["end"], "room": s["room"], "kind_label": up.SLOT_KINDS.get(s["kind"], "Class"),
                           "from": _minutes(s["start"]), "to": max(_minutes(s["end"] or s["start"]), _minutes(s["start"]) + 30), "url": url, "modal": editing})
        layout_day(blocks, start_min, total_min)
        cells = [{"top": round((h - first_h) * grid_layout.PX_PER_HOUR, 1), "url": f"/settings/university/slot/new?weekday={wd}&start={h:02d}:00",
                  "label": f"Add a class on {up.WEEKDAYS[wd]} at {h:02d}:00"} for h in range(first_h, last_h)] if editing else []
        days.append({"label": up.WEEKDAYS[wd][:3], "blocks": blocks, "cells": cells})
    hours = [{"hour": h, "top": round((h - first_h) * grid_layout.PX_PER_HOUR, 1)} for h in range(first_h, last_h)]
    return {"days": days, "hours": hours, "height": (last_h - first_h) * grid_layout.PX_PER_HOUR, "cell_height": grid_layout.PX_PER_HOUR,
            "has_parity": any(s["weeks"] != "all" for s in slots), "empty": not slots}


def _short(conn, semester: dict):
    abbr = up.abbreviations(conn, semester["uid"])
    return lambda name: abbr.get(name, name)


def _looks(conn, semester: dict) -> dict[str, dict]:
    return {d["name"]: d for d in up.disciplines(conn, semester)}


def summary(conn, semester: dict, today: date) -> dict:
    """The summary line and the progress of the semester: which week it is, its parity, how many weeks are left and the credits."""
    start = date.fromisoformat(semester["start_date"]) if semester.get("start_date") else None
    end_text = semester.get("end_date") or semester.get("class_end_date")
    end = date.fromisoformat(end_text) if end_text else None
    out = {"week": None, "weeks": None, "parity": "", "left": "", "percent": None}
    if start and end and end > start:
        weeks = -(-((end - start).days + 1) // 7)
        out["weeks"] = weeks
        if today < start:
            out["left"] = f"starts {when(start.isoformat(), today)}"
            out["percent"] = 0
        elif today > end:
            out["left"] = "over"
            out["percent"] = 100
        else:
            week = (up._monday(today) - up._monday(start)).days // 7 + 1
            left = max(1, -(-(end - today).days // 7))
            out.update(week=week, parity="odd" if week % 2 else "even", left=f"{left} week{'s' if left != 1 else ''} left",
                       percent=round(100 * (today - start).days / max((end - start).days, 1)))
    out["credits"] = up.credits_planned(conn, semester["uid"])
    out["credits_target"] = semester.get("credits_target")
    return out


def next_classes(conn, semester: dict, now: datetime, limit: int = 3) -> list[dict]:
    """The coming classes of every discipline, not cancelled."""
    rows = conn.execute(
        "SELECT e.uid, s.discipline_tag, s.kind FROM events e JOIN university_slots s ON s.series_uid = e.series_uid "
        "WHERE s.semester_uid = ? AND e.start_at >= ? AND COALESCE(e.status, 'active') != 'archived' ORDER BY e.start_at LIMIT ?",
        (semester["uid"], now.strftime("%Y-%m-%dT%H:%M"), limit)).fetchall()
    out = []
    for r in rows:
        e = db.get_event(conn, r["uid"])
        if e:
            out.append({"event": e, "discipline": r["discipline_tag"], "kind_label": up.SLOT_KINDS.get(r["kind"], "Class")})
    return out


def exams(conn, semester: dict, today: date) -> dict:
    """Every milestone of the semester, the coming ones grouped by week, with the discipline, the weight, whether the entry conditions are
    met and the grade once there is one."""
    looks = _looks(conn, semester)
    short = _short(conn, semester)
    standing = {name: ue.standing(conn, semester["uid"], name, today) for name in looks}
    ways = {(name, w["id"]): w for name, st in standing.items() for w in st["ways"]}
    rows = []
    for m in ue.list_milestones(conn, semester["uid"], today=today):
        way = ways.get((next((n for n in looks if n.lower() == m["discipline"].lower()), m["discipline"]), m["way_id"]), {})
        rows.append({**m, "look": looks.get(m["discipline"]) or {"name": m["discipline"], "color": "gray", "icon": ""}, "short": short(m["discipline"]),
                     "eligible": way.get("eligible"), "grade": way.get("grade"), "url": f"/settings/university/evaluation/{m['way_id']}/edit?discipline={quote(m['discipline'], safe='')}",
                     "item_url": f"/events/{m['event_uid']}" if m["event_uid"] else (f"/tasks/{m['task_uid']}" if m["task_uid"] else "")})
    monday = up._monday(today)
    groups: list[dict] = []
    for r in [r for r in rows if r["date"] and r["days_left"] >= 0]:
        offset = (up._monday(date.fromisoformat(r["date"])) - monday).days // 7
        label = "This week" if offset == 0 else ("Next week" if offset == 1 else f"Week of {(monday + timedelta(weeks=offset)).day} {(monday + timedelta(weeks=offset)).strftime('%b')}")
        if not groups or groups[-1]["label"] != label:
            groups.append({"label": label, "rows": []})
        groups[-1]["rows"].append(r)
    undated = [r for r in rows if not r["date"]]
    past = sorted([r for r in rows if r["date"] and r["days_left"] < 0], key=lambda r: r["date"], reverse=True)
    finals = [{"look": looks[n], "final": st["final"], "so_far": st["so_far"], "passed": st["passed"]} for n, st in standing.items() if st["ways"]]
    return {"groups": groups, "undated": undated, "past": past, "finals": finals, "count": len(rows), "rows": rows}


def work(conn, semester: dict, today: date) -> list[dict]:
    """Homework and readings of every discipline that are still open, dated first and soonest first."""
    looks = _looks(conn, semester)
    out = []
    for name, d in looks.items():
        for h in up.list_homework(conn, semester["uid"], name):
            if h["status"] not in _OPEN:
                out.append({"kind": "Homework", "title": h["title"], "due": h["due"], "status": h["status"], "look": d, "url": f"/settings/university/homework/{h['task_uid']}/edit"})
    for r in up.list_readings(conn, semester["uid"]):
        if r["status"] not in _OPEN:
            d = next((v for k, v in looks.items() if k.lower() == r["discipline"].lower()), {"name": r["discipline"], "color": "gray", "icon": ""})
            out.append({"kind": "Reading", "title": r["title"], "due": r["due"], "status": r["status"], "look": d, "url": f"/settings/university/reading/{r['task_uid']}/edit"})
    out.sort(key=lambda x: (not x["due"], x["due"] or "", x["title"]))
    for x in out:
        x["overdue"] = bool(x["due"]) and x["due"] < today.isoformat()
    return out


def timeline(exam_rows: list[dict], work_rows: list[dict], today: date) -> list[dict]:
    """Every exam, deadline, homework and reading of the semester in the order of its date, with a marker where today falls and the undated at the end."""
    items = []
    for m in exam_rows:
        extra = [m["look"]["name"]] + ([f"{m['weight']:g}%"] if m.get("weight") is not None else []) + ([m["start"]] if m.get("start") else []) \
            + (["can sit"] if m.get("eligible") is True else (["conditions not met"] if m.get("eligible") is False else []))
        items.append({"day": m["date"] or "", "title": m["title"], "sub": " · ".join(extra), "url": m["item_url"] or m["url"], "color": m["look"].get("color") or "gray",
                      "grade": m.get("grade")})
    for w in work_rows:
        items.append({"day": w["due"] or "", "title": w["title"], "sub": f"{w['look']['name']} · {w['kind'].lower()}", "url": w["url"],
                      "color": w["look"].get("color") or "gray", "grade": None})
    iso = today.isoformat()
    items.sort(key=lambda i: (not i["day"], i["day"], i["title"]))
    for i in items:
        i["past"] = bool(i["day"]) and i["day"] < iso
        i["month"] = date.fromisoformat(i["day"]).strftime("%B %Y") if i["day"] else "No date"
    at = next((n for n, i in enumerate(items) if not i["past"]), len(items))
    items.insert(at, {"now": True, "day": iso, "title": "Today", "sub": "", "url": "", "color": "gray", "past": False, "grade": None, "month": date.fromisoformat(iso).strftime("%B %Y")})
    return items


def cards(conn, semester: dict, group: str, today: date) -> list[dict]:
    """One tall card per discipline in its own colour, sorted by colour and then by name, with the one exam and the one task or homework that
    are coming up next."""
    from .routers.labels import COLORS

    uid = semester["uid"]
    order = {c["key"] if isinstance(c, dict) else c: i for i, c in enumerate(COLORS)}
    out = []
    for d in up.disciplines(conn, semester):
        name = d["name"]
        coming = [e for e in ue.list_milestones(conn, uid, name, today) if e["days_left"] is not None and e["days_left"] >= 0]
        homework = sorted([h for h in up.list_homework(conn, uid, name) if h["status"] not in _OPEN and h["due"] and h["due"] >= today.isoformat()], key=lambda h: h["due"])
        readings = sorted([r for r in up.list_readings(conn, uid) if r["discipline"].lower() == name.lower() and r["status"] not in _OPEN and r["due"] and r["due"] >= today.isoformat()],
                          key=lambda r: r["due"])
        task = (homework[:1] + readings[:1] or [None])
        task = min([t for t in task if t], key=lambda t: t["due"], default=None)
        attendance = ua.discipline_attendance(conn, uid, name, today)
        held = [c for c in attendance["classes"] if c["status"] != "cancelled"]
        color = d.get("color") or "gray"
        out.append({"name": name, "color": color, "icon": d.get("icon") or "book-open",
                    "exam": {"title": coming[0]["title"], "when": when(coming[0]["date"], today)} if coming else None,
                    "task": {"title": task["title"], "when": when(task["due"], today)} if task else None,
                    "classes": f"{len([c for c in held if c['past']])} of {len(held)} classes" if held else "",
                    "url": f"/groups/{quote(group, safe='')}/disciplines/{quote(name, safe='')}"})
    out.sort(key=lambda c: (order.get(c["color"], 99), c["name"].lower()))
    return out


def overview(conn, semester: dict, group: str, today: date, now: datetime) -> dict:
    looks = _looks(conn, semester)
    exam_rows = exams(conn, semester, today)
    coming = [r for g in exam_rows["groups"] for r in g["rows"]]
    due = work(conn, semester, today)
    attendance = ua.semester_attendance(conn, semester, today)
    standing_rows = []
    for a in attendance:
        for k in a["kinds"]:
            if k["limit"] is not None:
                standing_rows.append({"look": a["discipline"], "label": k["label"], "left": k["left"], "over": k["over"], "at_risk": k["at_risk"]})
    missed = sorted([{**c, "look": a["discipline"]} for a in attendance for c in a["missed"]], key=lambda c: c["date"], reverse=True)[:5]
    over = len([s for s in standing_rows if s["over"]])
    tight = sorted([s for s in standing_rows if s["left"] is not None], key=lambda s: s["left"])
    return {"summary": summary(conn, semester, today), "next_classes": next_classes(conn, semester, now), "exams_soon": coming[:5], "tight": tight[:1], "today": today,
            "exams_this_fortnight": len([r for r in coming if r["days_left"] <= 14]), "due": due[:6], "over": over,
            "absences": standing_rows, "missed": missed, "disciplines": list(looks.values()), "schedule": schedule(conn, semester, group)}


def _page_add(semester: dict | None, view: str, disciplines: list[dict]) -> dict:
    """The header bar's add button of the study page: what can be added on the view that is open."""
    if not semester:
        return {"href": "/settings/university/semester", "label": "Set up a semester"}
    if view == "disciplines":
        return {"href": "/settings/university/discipline/new", "label": "New discipline"}
    items = [{"href": "/settings/university/slot/new", "icon": "clock", "label": "New weekly class"},
             {"href": "/settings/university/discipline/new", "icon": "book-open", "label": "New discipline"}]
    if view == "exams":
        items += [{"href": f"/settings/university/evaluation/new?discipline={quote(d['name'], safe='')}", "icon": "file-check", "label": f"Examination: {d['name']}"}
                  for d in disciplines]
    return {"label": "Add", "items": items}


def render(conn, request: Request, name: str, label: dict):
    semester = up.semester_for_group(conn, name)
    today = clock.today()
    base = f"/groups/{quote(name, safe='')}"
    asked = request.query_params.get("view") or "overview"
    view = asked if asked in dict(VIEWS) else "overview"
    ctx = {"request": request, "label": label, "name": name, "enc": quote(name, safe=""), "semester": semester, "view": view,
           "views": [{"key": k, "label": text, "url": base if k == "overview" else f"{base}?view={k}", "active": k == view} for k, text in VIEWS]}
    if semester:
        if view == "disciplines":
            ctx["cards"] = cards(conn, semester, name, today)
        elif view == "exams":
            ctx.update(exams=exams(conn, semester, today), work=work(conn, semester, today), today=today, disciplines=list(_looks(conn, semester).values()))
            ctx["timeline"] = timeline(ctx["exams"]["rows"], ctx["work"], today)
        else:
            ctx.update(overview(conn, semester, name, today, clock.local_now()))
    ctx["page_add"] = _page_add(semester, view, ctx.get("disciplines") or [])
    return templates.TemplateResponse("study_page.html", ctx)
