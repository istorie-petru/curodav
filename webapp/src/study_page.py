"""The study page: the page of the space that holds the University semester. Overview is the weekly schedule (odd weeks in the left half of a
day, even weeks in the right half) above four small widgets (the next examination, the next homework, the next tasks and how much of the
semester is left). Disciplines is one bordered card per discipline. Nothing here reads dated class events: the schedule comes from the
timetable slots, so it is the same for any week."""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

from fastapi import Request

from . import clock, tags
from . import university_plan as up
from .deps import templates

_OPEN = ("done", "archived")


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
    """Top, height, left and width of each block of one day, in percent. Odd-week classes take the left half, even-week classes the right half,
    weekly classes the whole width; blocks of one kind that overlap share their width."""
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
    for b in blocks:
        b.update(top=round((b["from"] - start_min) / total_min * 100, 3), height=max(round((b["to"] - b["from"]) / total_min * 100, 3), 3))


def schedule(conn, semester: dict, group: str) -> dict:
    """The weekly timetable as a grid: Monday to Friday, plus the weekend when a class falls on it."""
    looks = {t["name"]: t for t in tags.tags_of_label(conn, semester["shelf_name"])}
    abbr = up.abbreviations(conn, semester["uid"])
    slots = up.list_slots(conn, semester["uid"])
    used = {s["weekday"] for s in slots}
    last_day = 6 if 6 in used else (5 if 5 in used else 4)
    first_h = min([_minutes(s["start"]) // 60 for s in slots] + [8])
    last_h = max([-(-_minutes(s["end"] or s["start"]) // 60) for s in slots] + [17])
    start_min, total_min = first_h * 60, (last_h - first_h) * 60
    days = []
    for wd in range(last_day + 1):
        blocks = []
        for s in (x for x in slots if x["weekday"] == wd):
            look = looks.get(s["discipline"], {"color": "gray", "icon": ""})
            blocks.append({"discipline": s["discipline"], "short": abbr.get(s["discipline"], s["discipline"]), "color": look.get("color") or "gray", "weeks": s["weeks"],
                           "start": s["start"], "end": s["end"], "room": s["room"], "kind_label": up.SLOT_KINDS.get(s["kind"], "Class"),
                           "from": _minutes(s["start"]), "to": max(_minutes(s["end"] or s["start"]), _minutes(s["start"]) + 30),
                           "url": f"/groups/{quote(group, safe='')}/disciplines/{quote(s['discipline'], safe='')}"})
        layout_day(blocks, start_min, total_min)
        days.append({"label": up.WEEKDAYS[wd][:3], "blocks": blocks})
    return {"days": days, "hours": list(range(first_h, last_h)), "has_parity": any(s["weeks"] != "all" for s in slots), "empty": not slots}


def widgets(conn, semester: dict, today: date) -> dict:
    """The four widgets above the schedule."""
    uid = semester["uid"]
    abbr = up.abbreviations(conn, uid)
    names = [t["name"] for t in tags.tags_of_label(conn, semester["shelf_name"])]

    def short(name: str) -> str:
        return abbr.get(name, name)

    exams = [e for e in up.list_milestones(conn, uid, today=today) if e["days_left"] is not None and e["days_left"] >= 0]
    exam = ({"title": exams[0]["title"], "short": short(exams[0]["discipline"]), "when": when(exams[0]["date"], today),
             "url": f"/events/{exams[0]['event_uid']}" if exams[0]["event_uid"] else f"/tasks/{exams[0]['task_uid']}"}
            if exams else None)
    homework = []
    for name in names:
        homework += [{"title": h["title"], "short": short(name), "due": h["due"], "when": when(h["due"], today), "url": f"/tasks/{h['task_uid']}"}
                     for h in up.list_homework(conn, uid, name) if h["status"] not in _OPEN]
    tasks = [{"title": r["title"], "short": short(r["discipline"]), "due": r["due"], "when": when(r["due"], today), "url": f"/tasks/{r['task_uid']}"}
             for r in up.list_readings(conn, uid) if r["status"] not in _OPEN]
    key = lambda x: (not x["due"], x["due"] or "")  # noqa: E731 -- dated first, soonest first
    start = date.fromisoformat(semester["start_date"]) if semester.get("start_date") else None
    end = date.fromisoformat(semester["end_date"] or semester["class_end_date"]) if (semester.get("end_date") or semester.get("class_end_date")) else None
    left = {"big": "Semester", "small": "", "percent": 0}
    if start and end and end > start:
        total = (end - start).days
        if today < start:
            left = {"big": f"Starts {when(start.isoformat(), today)}", "small": f"{(end - start).days // 7} weeks long", "percent": 0}
        elif today > end:
            left = {"big": "Semester over", "small": f"ended {end.day} {end.strftime('%b')}", "percent": 100}
        else:
            weeks = max(1, -(-(end - today).days // 7))
            left = {"big": f"{weeks} week{'s' if weeks != 1 else ''} left", "small": f"ends {end.day} {end.strftime('%b')}", "percent": round(100 * (today - start).days / total)}
    return {"exam": exam, "homework": sorted(homework, key=key)[:2], "tasks": sorted(tasks, key=key)[:2], "left": left}


def cards(conn, semester: dict, group: str) -> list[dict]:
    """One card per discipline: its name and icon, and one line of text only when something needs saying: an exam is coming, or contents or
    the evaluation are not set up yet."""
    uid = semester["uid"]
    today = clock.today()
    out = []
    for d in up.disciplines(conn, semester):
        name = d["name"]
        exams = [e for e in up.list_milestones(conn, uid, name, today) if e["days_left"] is not None and 0 <= e["days_left"] <= 30]
        missing = [label for label, ok in (("contents", bool(up.list_topics(conn, uid, name))), ("examination", bool(up.get_evaluation(conn, uid, name)))) if not ok]
        out.append({"name": name, "color": d.get("color") or "gray", "icon": d.get("icon") or "book-open",
                    "url": f"/groups/{quote(group, safe='')}/disciplines/{quote(name, safe='')}",
                    "exam": f"{exams[0]['title']} {when(exams[0]['date'], today)}" if exams else "", "missing": ("Not set up: " + ", ".join(missing)) if missing else ""})
    return out


def render(conn, request: Request, name: str, label: dict):
    semester = up.semester_for_group(conn, name)
    today = clock.today()
    base = f"/groups/{quote(name, safe='')}"
    view = "disciplines" if request.query_params.get("view") == "disciplines" else "overview"
    ctx = {"request": request, "label": label, "name": name, "enc": quote(name, safe=""), "semester": semester, "view": view,
           "views": [{"key": k, "label": text, "url": url, "active": k == view} for k, text, url in (("overview", "Overview", base), ("disciplines", "Disciplines", f"{base}?view=disciplines"))]}
    if semester and view == "disciplines":
        ctx["cards"] = cards(conn, semester, name)
    elif semester:
        ctx.update(schedule=schedule(conn, semester, name), widgets=widgets(conn, semester, today))
    return templates.TemplateResponse("study_page.html", ctx)
