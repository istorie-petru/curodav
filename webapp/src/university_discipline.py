"""The page of one discipline, under the page of the space that holds the semester: its course sheet and nothing else. The page shows; small windows
(the identification, a timetable slot, the absences, a way of evaluating, the grades, a reference) edit."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request

from . import clock, db
from . import university_attendance as ua
from . import university_evaluation as ue
from . import university_plan as up
from .deps import get_db, templates
from .university import _enabled

router = APIRouter(prefix="/groups/{group}/disciplines", tags=["university"], dependencies=[Depends(_enabled)])

OLD_VIEWS = ("overview", "sheet", "bibliography", "exams", "contents", "attendance", "classes")


def build(conn, semester: dict, discipline: dict, today) -> dict:
    """The course sheet of one discipline: who it is, how it is taught, how it is examined (attendance first), its bibliography and other notes."""
    uid, name = semester["uid"], discipline["name"]
    sheet = up.get_sheet(conn, uid, name)
    teachers = {t["uid"]: t["name"] for t in discipline["teachers"]}
    slots = up.list_slots(conn, uid, name)
    for s in slots:
        s["weekday_name"] = up.WEEKDAYS[s["weekday"]]
        s["kind_label"] = up.SLOT_KINDS.get(s["kind"], "Class")
        s["teacher_names"] = ", ".join(teachers[u] for u in s["teachers"] if u in teachers)
    kinds = up.course_kinds(conn, uid, name)
    att = ua.discipline_attendance(conn, uid, name, today)
    settings = ua.settings(conn, uid, name)
    attendance = []
    for kind in kinds:
        k = next((x for x in att["kinds"] if x["kind"] == kind), None)
        attendance.append({"kind": kind, "label": up.SLOT_KINDS[kind], "missed": k["missed"] if k else 0, "limit": k["limit"] if k else None,
                           "left": k["left"] if k else None, "over": bool(k and k["over"]), "percent": settings[kind]["percent"], "number": settings[kind]["number"]})
    standing = ue.standing(conn, uid, name, today)
    for w in standing["ways"]:
        w["tone"] = ue.EVALUATION_TONES.get(w["form"], "orange")
        w["linked_notes"] = [{"uid": n["uid"], "title": n["title"]} for n in (db.get_notebook_document(conn, u) for u in w["note_uids"]) if n]
    return {"sheet": sheet, "short": up.short_name(conn, uid, name), "kinds": [{"key": k, "label": up.TOPIC_KINDS[k]} for k in kinds],
            "slots": slots, "attendance": attendance, "standing": standing, "readings": up.list_readings(conn, uid, name),
            "notes_text": sheet["values"].get("summary", ""), "passing": ue.passing_grade(conn, uid, name)}


@router.get("/{name}")
def discipline_page(group: str, name: str, request: Request, conn=Depends(get_db)):
    semester = up.semester_for_group(conn, group)
    if not semester:
        raise HTTPException(404, "No such semester")
    found = next((d for d in up.disciplines(conn, semester) if d["name"].lower() == name.lower()), None)
    if not found:
        raise HTTPException(404, "No such discipline")
    from . import university
    from .routers import dashboard as dashboard_router

    ctx = build(conn, semester, found, clock.today())
    ctx.update(dashboard_router._page_banner_context(conn, university.banner_scope(found["name"]), name=found["name"]))
    ctx.update(request=request, semester=semester, d=found, group=group, enc=quote(found["name"], safe=""),
               crumbs=[{"url": f"/groups/{quote(group, safe='')}", "name": group}], WEEKDAYS=up.WEEKDAYS)
    return templates.TemplateResponse("university_discipline_page.html", ctx)
