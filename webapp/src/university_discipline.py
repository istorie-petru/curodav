"""The page of one discipline, under the page of the space that holds the semester: an overview and the views Course sheet, Classes (the contents
and the attendance of every class), Bibliography and Examination. Pages show; small windows (a slot, a topic list, a way of evaluating, a reading, a class) edit."""

from __future__ import annotations

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request

from . import clock
from . import university_attendance as ua
from . import university_evaluation as ue
from . import university_plan as up
from .deps import get_db, templates
from .study_page import when
from .university import _enabled

router = APIRouter(prefix="/groups/{group}/disciplines", tags=["university"], dependencies=[Depends(_enabled)])

VIEWS = (("overview", "Overview"), ("sheet", "Course sheet"), ("bibliography", "Bibliography"), ("exams", "Examination"))
OLD_VIEWS = {"contents": "overview", "attendance": "overview", "classes": "overview"}


def _views(group: str, name: str, active: str) -> list[dict]:
    base = f"/groups/{quote(group, safe='')}/disciplines/{quote(name, safe='')}"
    return [{"key": k, "label": label, "url": base if k == "overview" else f"{base}?view={k}", "active": k == active} for k, label in VIEWS]


def build(conn, semester: dict, discipline: dict, view: str, today) -> dict:
    uid, name = semester["uid"], discipline["name"]
    ctx: dict = {"view": view}
    classes = up.list_classes(conn, uid, name, today)
    milestones = ue.list_milestones(conn, uid, name, today)
    readings = up.list_readings(conn, uid, name)
    topics = up.list_topics(conn, uid, name)
    if view == "overview":
        slots = up.list_slots(conn, uid, name)
        teachers = {t["uid"]: t["name"] for t in discipline["teachers"]}
        for s in slots:
            s["weekday_name"] = up.WEEKDAYS[s["weekday"]]
            s["kind_label"] = up.SLOT_KINDS.get(s["kind"], "Class")
            s["teacher_names"] = ", ".join(teachers[u] for u in s["teachers"] if u in teachers)
        iso = today.isoformat()
        names = {t["uid"]: f"{t['number']}. {t['title']}" for t in topics}
        upcoming = []
        for c in [c for c in classes if c["date"] >= iso][:2]:
            upcoming.append({**c, "topic": names.get(c["topic_uid"], ""), "when": f"{c['date']}"})
        pending = []
        for m in milestones:
            way_url = f"/settings/university/evaluation/{m['way_id']}/edit?discipline={quote(name, safe='')}"
            weight = f"{m['weight']:g}%" if m["weight"] is not None else ""
            if m["date"] and m["days_left"] >= 0:
                pending.append({"icon": "calendar" if m["event_uid"] else "check-square", "title": m["title"], "when": when(m["date"], today),
                                "tone": "red" if m["days_left"] <= 7 else "gray", "detail": weight, "url": way_url, "sort": m["date"]})
            elif not m["date"]:
                pending.append({"icon": "calendar", "title": m["title"], "when": "No date", "tone": "orange", "detail": weight, "url": way_url, "sort": "9998"})
        for h in up.list_homework(conn, uid, name):
            if h["status"] not in ("done", "archived"):
                pending.append({"icon": "check-square", "title": h["title"], "when": when(h["due"], today) if h["due"] else "No date", "tone": "gray", "detail": "",
                                "url": f"/settings/university/homework/{h['task_uid']}/edit", "sort": h["due"] or "9999"})
        pending.sort(key=lambda p: p["sort"])
        soon_exam = next((p for p, m in ((p, m) for p in pending for m in milestones if p["title"] == m["title"] and p["sort"] == m["date"]) if m["days_left"] is not None and 0 <= m["days_left"] <= 14), None)
        attendance = ua.discipline_attendance(conn, uid, name, today)
        data = ua.discipline_attendance(conn, uid, name, today)
        rows = data["classes"]
        topic_names = {t["uid"]: f"{t['number']}. {t['title']}" for t in topics}
        nxt = next((c for c in rows if not c["past"] and c["status"] != "cancelled"), None)
        for c in rows:
            c["topic_name"] = topic_names.get(c["topic_uid"], "")
            c["is_next"] = c is nxt
        ctx.update(next_class=({"uid": nxt["uid"], "name": nxt["topic_name"] or f"{nxt['kind_label']} {nxt['number']}", "date": nxt["date"], "start": nxt["start"]} if nxt else None), class_rows=rows, soon_exam=soon_exam, slots=slots, upcoming=upcoming, pending=pending, topics_done=len([t for t in topics if t["events"]]), topics_total=len(topics),
                   read_done=len([r for r in readings if r["status"] == "done"]), read_total=len(readings), classes_total=len(classes),
                   classes_left=len([c for c in classes if c["date"] >= iso]), absences=attendance["kinds"])
    elif view == "sheet":
        by_event = {c["uid"]: c for c in classes}
        groups = []
        for kind in ("lecture", "seminar", "lab", "competence"):
            items = up.list_topics(conn, uid, name, kind)
            for t in items:
                t["dates"] = [by_event[e]["date"] for e in t["events"] if e in by_event]
            groups.append({"kind": kind, "label": up.TOPIC_KINDS[kind], "rows": items})
        sheet = up.get_sheet(conn, uid, name)
        for sec in sheet["sections"]:
            sec["shown"] = [f for f in sec["fields"] if f["value"]]
            sec["has_content"] = bool(sec["shown"] or sec["custom"] or (sec["key"] == "teaching" and (sheet["lecture_teachers"] or sheet["seminar_teachers"]))
                                      or sec["key"] == "identification")
        names = {c["uid"]: c.get("full_name") or "" for c in (db.get_contact(conn, u) or {"uid": u} for u in {u for s in up.list_slots(conn, uid, name) for u in s["teachers"]})}
        teaching = []
        for kind in ("lecture", "seminar", "lab"):
            kind_slots = [s for s in up.list_slots(conn, uid, name) if s["kind"] == kind]
            for s in kind_slots:
                s["weekday_name"] = up.WEEKDAYS[s["weekday"]]
                s["teacher_names"] = ", ".join(names.get(u, "") for u in s["teachers"] if names.get(u))
                minutes = (int(s["end"][:2]) * 60 + int(s["end"][3:])) - (int(s["start"][:2]) * 60 + int(s["start"][3:]))
                s["hours"] = f"{minutes / 60 * (1 if s['weeks'] == 'all' else 0.5):g}"
            teaching.append({"kind": kind, "label": up.SLOT_KINDS[kind], "slots": kind_slots, "absences": sheet["values"].get(f"absences_{kind}", ""),
                             "hours": f"{sum(float(s['hours']) for s in kind_slots):g}" if kind_slots else ""})
        ways = ue.standing(conn, uid, name, today)["ways"]
        ctx.update(sheet=sheet, groups=[g for g in groups if g["kind"] != "competence"], can_place=bool(topics and classes), teaching=teaching, ways=ways)
    elif view == "bibliography":
        ctx.update(readings=readings)
    elif view == "exams":
        standing = ue.standing(conn, uid, name, today)
        for w in standing["ways"]:
            w["tone"] = ue.EVALUATION_TONES.get(w["form"], "orange")
            for m in w["milestones"]:
                m["days_left"] = (date.fromisoformat(m["date"]) - today).days if m["date"] else None
            w["soon"] = any(m["days_left"] is not None and 0 <= m["days_left"] <= 14 for m in w["milestones"])
        ctx.update(others=up.list_other_items(conn, uid, name), standing=standing)
    return ctx


@router.get("/{name}")
def discipline_page(group: str, name: str, request: Request, view: str = "overview", conn=Depends(get_db)):
    semester = up.semester_for_group(conn, group)
    if not semester:
        raise HTTPException(404, "No such semester")
    found = next((d for d in up.disciplines(conn, semester) if d["name"].lower() == name.lower()), None)
    if not found:
        raise HTTPException(404, "No such discipline")
    view = OLD_VIEWS.get(view, view)
    view = view if view in dict(VIEWS) else "overview"
    from . import university
    from .routers import dashboard as dashboard_router

    ctx = build(conn, semester, found, view, clock.today())
    ctx.update(dashboard_router._page_banner_context(conn, university.banner_scope(found["name"]), name=found["name"]))
    ctx.update(request=request, semester=semester, d=found, group=group, views=_views(group, found["name"], view), enc=quote(found["name"], safe=""),
               crumbs=[{"url": f"/groups/{quote(group, safe='')}", "name": group}], WEEKDAYS=up.WEEKDAYS)
    return templates.TemplateResponse("university_discipline_page.html", ctx)
