"""The page of one discipline, under the page of the space that holds the semester: an overview and the views Syllabus, Contents,
Bibliography and Exams and homework. Pages show; small windows (a slot, a topic list, an exam, a reading, a class's contents) edit."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request

from . import clock, db, tags
from . import university_plan as up
from .deps import get_db, templates
from .study_page import when
from .university import _enabled

router = APIRouter(prefix="/groups/{group}/disciplines", tags=["university"], dependencies=[Depends(_enabled)])

VIEWS = (("overview", "Overview"), ("sheet", "Course sheet"), ("contents", "Contents"), ("bibliography", "Bibliography"), ("exams", "Examination"))


def _views(group: str, name: str, active: str) -> list[dict]:
    base = f"/groups/{quote(group, safe='')}/disciplines/{quote(name, safe='')}"
    return [{"key": k, "label": label, "url": base if k == "overview" else f"{base}?view={k}", "active": k == active} for k, label in VIEWS]


def build(conn, semester: dict, discipline: dict, view: str, today) -> dict:
    uid, name = semester["uid"], discipline["name"]
    ctx: dict = {"view": view}
    classes = up.list_classes(conn, uid, name, today)
    milestones = up.list_milestones(conn, uid, name, today)
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
                pending.append({"tone": "exam" if m["event_uid"] else "homework", "title": m["title"], "when": when(m["date"], today), "detail": weight, "url": way_url, "sort": m["date"]})
            elif not m["date"]:
                pending.append({"tone": "dated", "title": m["title"], "when": "No date yet", "detail": weight, "url": way_url, "sort": "9998"})
        for h in up.list_homework(conn, uid, name):
            if h["status"] not in ("done", "archived"):
                pending.append({"tone": "homework", "title": h["title"], "when": when(h["due"], today) if h["due"] else "No date", "detail": "", "url": f"/settings/university/homework/{h['task_uid']}/edit", "sort": h["due"] or "9999"})
        pending.sort(key=lambda p: ({"exam": 0, "dated": 1, "homework": 2}[p["tone"]], p["sort"]))
        ctx.update(slots=slots, upcoming=upcoming, pending=pending, topics_done=len([t for t in topics if t["events"]]), topics_total=len(topics),
                   read_done=len([r for r in readings if r["status"] == "done"]), read_total=len(readings), classes_total=len(classes),
                   classes_left=len([c for c in classes if c["date"] >= iso]))
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
        ctx.update(sheet=sheet, groups=groups, can_place=bool(topics and classes),
                   sheet_empty=not up.sheet_filled(sheet) and not any(g["rows"] for g in groups))
    elif view == "contents":
        every = {t["uid"]: f"{t['number']}. {t['title']}" for t in up.list_topics(conn, uid, name) + up.list_topics(conn, uid, name, "competence")}
        for c in classes:
            c["topic_name"] = every.get(c["topic_uid"], "")
            c["competence_names"] = [every[u] for u in c["competence_uids"] if u in every]
        nxt = next((c for c in classes if not c["past"]), None)
        if nxt:
            nxt["is_next"] = True
        ctx.update(classes=classes, can_place=bool(topics and classes))
    elif view == "bibliography":
        ctx.update(readings=readings)
    elif view == "exams":
        ctx.update(others=up.list_other_items(conn, uid, name), evaluation=up.evaluation_rows(conn, uid, name, today))
    return ctx


@router.get("/{name}")
def discipline_page(group: str, name: str, request: Request, view: str = "overview", conn=Depends(get_db)):
    semester = up.semester_for_group(conn, group)
    if not semester:
        raise HTTPException(404, "No such semester")
    found = next((d for d in up.disciplines(conn, semester) if d["name"].lower() == name.lower()), None)
    if not found:
        raise HTTPException(404, "No such discipline")
    view = view if view in dict(VIEWS) else "overview"
    from . import university
    from .routers import dashboard as dashboard_router

    ctx = build(conn, semester, found, view, clock.today())
    ctx.update(dashboard_router._page_banner_context(conn, university.banner_scope(found["name"]), name=found["name"]))
    ctx.update(request=request, semester=semester, d=found, group=group, views=_views(group, found["name"], view), enc=quote(found["name"], safe=""),
               crumbs=[{"url": f"/groups/{quote(group, safe='')}", "name": group}], WEEKDAYS=up.WEEKDAYS)
    return templates.TemplateResponse("university_discipline_page.html", ctx)
