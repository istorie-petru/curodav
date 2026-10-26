"""The University module: registers itself with the module framework (src/modules.py) and serves its Settings page and windows.

The Settings page under Modules describes the semester (its dates and class end date) and lists its disciplines. A discipline has its own
page (`university_discipline.py`); the small windows in this file edit one thing at a time: a discipline, its course sheet, a timetable slot,
a topic list, an exam, a reading, homework, and what a class covered. Nothing asks for confirmation in a window: a change that
removed or replaced something says so in a short toast (`?note=`). The domain rules are in `university_plan.py`; the study page is
`study_page.py`. A module is switched on in Settings, General.
"""

from __future__ import annotations

from contextvars import ContextVar
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import db, modules, tags
from . import university_plan as up
from .deps import get_db, templates

MODULE = modules.register(modules.Module("university", "University", "/settings/university", icon="graduation-cap",
                                         description="Semesters, classes, exams and readings, with a study page"))


def _render_study(conn, request, name, label):
    from . import study_page
    return study_page.render(conn, request, name, label)


modules.register_page_type(modules.PageType(up.PAGE_TYPE, "Study page", MODULE.key, _render_study))


def _enabled() -> None:
    if not modules.is_enabled(MODULE.key):
        raise HTTPException(404, "Not found")


router = APIRouter(prefix="/settings/university", tags=["university"], dependencies=[Depends(_enabled)])

HOME = "/settings/university"

_group: ContextVar[str] = ContextVar("university_group", default="")


def url_for_discipline(name: str, view: str = "") -> str:
    """The page of a discipline, under the page of the space that holds the semester."""
    base = f"/groups/{quote(_group.get(), safe='')}/disciplines/{quote(name, safe='')}"
    return base + (f"?view={view}" if view else "")


def _note(url: str, message: str = "") -> RedirectResponse:
    """Back to a page, with a short toast when there is something worth saying."""
    return RedirectResponse(url + (("&" if "?" in url else "?") + "note=" + quote(message)) if message else url, status_code=303)


def _semester(conn) -> dict:
    semester = up.current_semester(conn)
    if not semester:
        raise HTTPException(409, "Create the semester first")
    _group.set(up.semester_group(conn, semester))
    return semester


def _discipline(conn, semester: dict, name: str) -> dict:
    found = next((d for d in up.disciplines(conn, semester) if d["name"].lower() == name.lower()), None)
    if not found:
        raise HTTPException(404, "No such discipline")
    return found


def _bad(exc: Exception):
    raise HTTPException(400, str(exc)) from exc


def _colors():
    from .routers.labels import COLORS
    return COLORS


def _icon_groups(current=None):
    from .routers.labels import icon_groups_for
    return icon_groups_for(current)


# ---------------------------------------------------------------- the page

@router.get("")
def university_settings(request: Request, conn=Depends(get_db)):
    semester = up.current_semester(conn)
    ctx = {"request": request, "semester": semester, "semesters": up.list_semesters(conn)}
    if semester:
        _group.set(up.attach_group(conn, semester))
        ctx.update(disciplines=up.disciplines(conn, semester), url_for_discipline=url_for_discipline, group=_group.get(),
                   calendar=semester.get("holiday_calendar") or "", credits_planned=up.credits_planned(conn, semester["uid"]))
    return templates.TemplateResponse("settings_university.html", ctx)


# ---------------------------------------------------------------- semester

@router.get("/semester")
def semester_form(request: Request, new: str = "", conn=Depends(get_db)):
    semester = None if new else up.current_semester(conn)
    return templates.TemplateResponse("university_semester_modal.html", {
        "request": request, "semester": semester, "calendars": db.list_holiday_calendar_names(conn)})


@router.post("/semester")
def semester_save(name: str = Form(""), start_date: str = Form(""), end_date: str = Form(""), class_end_date: str = Form(""),
                  holiday_calendar: str = Form(""), uid: str = Form(""), credits_target: str = Form(""), conn=Depends(get_db)):
    existing = up.get_semester(conn, uid) if uid else None
    note = ""
    try:
        new_end = up._date(class_end_date, "Class end date")
        if existing and new_end and (existing.get("class_end_date") or "") != new_end.isoformat():
            plan = up.plan_class_end(conn, existing["uid"], new_end)
            if plan["removed"]:
                note = f"{plan['removed']} classes after {new_end.isoformat()} were removed" + (f", {plan['removed_with_text']} of them with contents" if plan["removed_with_text"] else "")
        up.save_semester(conn, uid=existing["uid"] if existing else None, name=name, shelf_name="", start_date=start_date, end_date=end_date,
                         class_end_date=class_end_date, holiday_calendar=holiday_calendar, credits_target=credits_target)
    except up.PlanError as exc:
        _bad(exc)
    return _note(HOME, note)


@router.post("/semester/select")
def semester_select(uid: str = Form(...), conn=Depends(get_db)):
    try:
        up.select_semester(conn, uid)
    except up.PlanError as exc:
        _bad(exc)
    semester = up.get_semester(conn, uid)
    group = up.semester_group(conn, semester)
    return RedirectResponse(f"/groups/{quote(group, safe='')}" if group else HOME, status_code=303)


# ---------------------------------------------------------------- disciplines

def banner_scope(name: str) -> str:
    """The key a discipline's banner image is stored under."""
    return f"discipline:{name}"


def _discipline_form_context(request: Request, conn, semester: dict, d: dict | None) -> dict:
    values = up.get_sheet(conn, semester["uid"], d["name"])["values"] if d else {}
    banner = db.effective_page_banner(conn, banner_scope(d["name"]), name=d["name"]) if d else None
    return {"request": request, "d": d, "colors": _colors(), "icon_groups": _icon_groups(d.get("icon") if d else None), "values": values,
            "banner": banner, "banner_scope": banner_scope(d["name"]) if d else ""}


@router.get("/discipline/new")
def discipline_new(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse("university_discipline_modal.html", _discipline_form_context(request, conn, _semester(conn), None))


@router.get("/discipline/{name}/edit")
def discipline_edit(name: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    return templates.TemplateResponse("university_discipline_modal.html", _discipline_form_context(request, conn, semester, _discipline(conn, semester, name)))


@router.post("/discipline")
def discipline_save(old: str = Form(""), name: str = Form(""), color: str = Form("gray"), icon: str = Form(""), abbreviation: str = Form(""), code: str = Form(""),
                    credits: str = Form(""), type: str = Form(""), conn=Depends(get_db)):
    semester = _semester(conn)
    try:
        saved = up.save_discipline(conn, semester, old=old, name=name, color=color, icon=icon, teacher_names=None, colors=_colors())
        up.save_sheet(conn, semester["uid"], saved, {"abbreviation": abbreviation, "code": code, "credits": credits, "type": type})
    except (up.PlanError, tags.ManagedLabelError) as exc:
        _bad(exc)
    return _note(url_for_discipline(saved))


@router.post("/discipline/{name}/remove")
def discipline_remove(name: str, conn=Depends(get_db)):
    try:
        up.remove_discipline(conn, _semester(conn), name)
    except up.PlanError as exc:
        _bad(exc)
    return RedirectResponse(HOME, status_code=303)


# ---------------------------------------------------------------- course sheet

def _section(key: str) -> tuple:
    return next((sec for sec in up.SHEET_SECTIONS if sec[0] == key), up.SHEET_SECTIONS[0])


@router.get("/sheet/{name}")
def sheet_form(name: str, request: Request, section: str = "identification", conn=Depends(get_db)):
    """One section of the course sheet in its own window."""
    semester = _semester(conn)
    d = _discipline(conn, semester, name)
    key, label, _ = _section(section)
    sheet = up.get_sheet(conn, semester["uid"], d["name"])
    return templates.TemplateResponse("university_sheet_modal.html", {
        "request": request, "d": d, "sheet": sheet, "sec": next(s for s in sheet["sections"] if s["key"] == key),
        "lecture": [t["uid"] for t in sheet["lecture_teachers"]], "seminar": [t["uid"] for t in sheet["seminar_teachers"]]})


@router.post("/sheet/{name}")
async def sheet_save(name: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, name)
    form = await request.form()
    key, _, fields = _section(str(form.get("section") or "identification"))
    values = {k: str(form.get(f"f_{k}") or "") for k, _, _, _ in fields}
    labels, firsts, seconds = ([str(x) for x in form.getlist(n)] for n in ("custom_label", "custom_a", "custom_b"))
    firsts, seconds = (firsts + [""] * len(labels))[:len(labels)], (seconds + [""] * len(labels))[:len(labels)]
    custom = [(key, lab, up.encode_custom(key, a, b)) for lab, a, b in zip(labels, firsts, seconds)]
    saved = d["name"]
    try:
        new_name = str(form.get("name") or "").strip()
        if key == "identification" and new_name and new_name != d["name"]:
            saved = up.save_discipline(conn, semester, old=d["name"], name=new_name, color=d.get("color") or "gray", icon=d.get("icon") or "", teacher_names=None, colors=_colors())
        up.save_sheet(conn, semester["uid"], saved, values, custom, only_section=key)
        if key == "teaching":
            up.set_teachers(conn, semester["uid"], saved, [str(x) for x in form.getlist("lecture_teachers")], [str(x) for x in form.getlist("seminar_teachers")])
    except (up.PlanError, tags.ManagedLabelError) as exc:
        _bad(exc)
    return _note(url_for_discipline(saved, "sheet"))


# ---------------------------------------------------------------- evaluation

def _way_context(request: Request, d: dict, way: dict | None) -> dict:
    events = [m for m in (way["milestones"] if way else []) if m["event_uid"] or not m["task_uid"]]
    tasks = [m for m in (way["milestones"] if way else []) if m["task_uid"]]
    return {"request": request, "d": d, "way": way, "forms": up.EVALUATION_FORMS, "events": events, "tasks": tasks}


@router.get("/evaluation/new")
def way_new(request: Request, discipline: str, conn=Depends(get_db)):
    d = _discipline(conn, _semester(conn), discipline)
    return templates.TemplateResponse("university_evaluation_modal.html", _way_context(request, d, None))


@router.get("/evaluation/{way_id}/edit")
def way_edit(way_id: str, request: Request, discipline: str, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline)
    way = next((w for w in up.get_evaluation(conn, semester["uid"], d["name"]) if w["id"] == way_id), None)
    if not way:
        raise HTTPException(404, "No such way of evaluating")
    return templates.TemplateResponse("university_evaluation_modal.html", _way_context(request, d, way))


@router.post("/evaluation")
async def way_save(request: Request, conn=Depends(get_db)):
    """One way of evaluating: name, type and weight, its components, and its milestones as a list of events and a list of tasks."""
    semester = _semester(conn)
    form = await request.form()
    d = _discipline(conn, semester, str(form.get("discipline") or ""))
    milestones: dict[str, dict] = {}
    for i, uid in enumerate(form.getlist("ev_uid")):
        milestones.setdefault(uid or f"new-event-{i}", {"uid": uid})
        milestones[uid or f"new-event-{i}"].update(title=form.getlist("ev_title")[i], day=form.getlist("ev_day")[i], start=form.getlist("ev_start")[i],
                                                    end_day=form.getlist("ev_end_day")[i], end=form.getlist("ev_end")[i], location=form.getlist("ev_location")[i])
    for i, uid in enumerate(form.getlist("tk_uid")):
        milestones.setdefault(uid or f"new-task-{i}", {"uid": uid})
        entry = milestones[uid or f"new-task-{i}"]
        entry.update(due=form.getlist("tk_due")[i])
        entry.setdefault("title", form.getlist("tk_title")[i])
    subs = [{"id": i, "name": n, "weight": w} for i, n, w in zip(form.getlist("sub_id"), form.getlist("sub_name"), form.getlist("sub_weight"))]
    way = {"id": str(form.get("way_id") or ""), "name": str(form.get("name") or ""), "form": str(form.get("form") or ""), "weight": str(form.get("weight") or ""),
           "subs": subs, "milestones": list(milestones.values())}
    try:
        warnings = up.save_way(conn, semester["uid"], d["name"], way)
    except up.PlanError as exc:
        _bad(exc)
    return _note(url_for_discipline(d["name"], "exams"), "; ".join(warnings))


@router.post("/evaluation/{way_id}/delete")
def way_delete(way_id: str, discipline: str = "", conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline)
    warnings = up.delete_way(conn, semester["uid"], d["name"], way_id)
    return _note(url_for_discipline(d["name"], "exams"), "; ".join(warnings))


# ---------------------------------------------------------------- timetable

def _slot_from(weekday, start, end, room, kind, weeks, teachers) -> dict:
    return {"weekday": weekday, "start": start, "end": end, "room": room, "kind": kind, "weeks": weeks, "teachers": [t for t in teachers if t]}


@router.get("/slot/new")
def slot_new(request: Request, discipline: str, conn=Depends(get_db)):
    d = _discipline(conn, _semester(conn), discipline)
    return templates.TemplateResponse("university_slot_modal.html", {
        "request": request, "d": d, "slot": None, "series_uid": "", "weekdays": up.WEEKDAYS, "kinds": up.SLOT_KINDS, "back": ""})


@router.get("/slot/{series_uid}/edit")
def slot_edit(series_uid: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    slot = next((s for s in up.list_slots(conn, semester["uid"]) if s["series_uid"] == series_uid), None)
    if not slot:
        raise HTTPException(404, "No such timetable slot")
    d = _discipline(conn, semester, slot["discipline"])
    return templates.TemplateResponse("university_slot_modal.html", {
        "request": request, "d": d, "slot": slot, "series_uid": series_uid, "weekdays": up.WEEKDAYS, "kinds": up.SLOT_KINDS, "back": ""})


@router.post("/slot")
def slot_save(discipline: str = Form(...), series_uid: str = Form(""), weekday: str = Form("0"), start: str = Form(""), end: str = Form(""),
              room: str = Form(""), kind: str = Form("lecture"), weeks: str = Form("all"), teachers: list[str] = Form(default=[]), conn=Depends(get_db)):
    semester = _semester(conn)
    slot = _slot_from(weekday, start, end, room, kind, weeks, teachers)
    try:
        plan = up.plan_slot(conn, semester, discipline, slot, series_uid or None)
        up.save_slot(conn, semester, discipline, slot, series_uid or None)
    except up.PlanError as exc:
        _bad(exc)
    notes = ["Past classes were not moved"] if plan["past"] else []
    if plan["lost"]:
        notes.append(f"The contents of {len(plan['lost'])} classes were lost: they no longer exist")
    return _note(url_for_discipline(discipline), "; ".join(notes))


@router.post("/slot/{series_uid}/delete")
def slot_delete(series_uid: str, discipline: str = "", conn=Depends(get_db)):
    _semester(conn)
    removed = up.delete_slot(conn, up.current_semester(conn)["uid"], series_uid)
    return _note(url_for_discipline(discipline) if discipline else HOME, f"{removed} classes removed")


# ---------------------------------------------------------------- planned contents and competences

def _kind(kind: str) -> str:
    return kind if kind in up.TOPIC_KINDS else "lecture"


@router.get("/syllabus/{name}")
def syllabus_form(name: str, request: Request, kind: str = "lecture", conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, name)
    kind = _kind(kind)
    rows = up.list_topics(conn, semester["uid"], d["name"], kind)
    return templates.TemplateResponse("university_syllabus_modal.html", {
        "request": request, "d": d, "kind": kind, "kind_label": up.TOPIC_KINDS[kind], "rows": rows, "next_number": (max([r["number"] for r in rows] or [0]) + 1)})


@router.post("/syllabus/{name}")
async def syllabus_save(name: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, name)
    form = await request.form()
    kind = _kind(str(form.get("kind") or "lecture"))
    rows = list(zip(form.getlist("number"), form.getlist("title"), form.getlist("importance") or [""] * len(form.getlist("title"))))
    up.save_topic_rows(conn, semester["uid"], d["name"], rows, kind)
    return _note(url_for_discipline(d["name"], "sheet"))


@router.post("/syllabus/{name}/assign")
def syllabus_assign(name: str, conn=Depends(get_db)):
    """Places the topics nobody uses yet, in order, on the lecture classes that have no text of their own."""
    semester = _semester(conn)
    d = _discipline(conn, semester, name)
    plan = up.plan_assign_in_order(conn, semester["uid"], d["name"])
    placed = up.apply_assign_in_order(conn, semester["uid"], d["name"])
    parts = [f"{placed} topics placed on classes"]
    if plan["blocked"]:
        parts.append(f"{len(plan['blocked'])} classes with their own text were skipped")
    if plan["left_over"]:
        parts.append(f"{plan['left_over']} topics found no free class")
    return _note(url_for_discipline(d["name"], "contents"), "; ".join(parts) if placed or plan["blocked"] or plan["left_over"] else "Nothing to place")


# ---------------------------------------------------------------- bibliography (readings are references to library books)

def _reading_form_context(request: Request, conn, d: dict, reading: dict | None) -> dict:
    books = db.picker_items(conn, [reading["citation_id"]] if reading and reading.get("citation_id") else [])
    return {"request": request, "d": d, "reading": reading, "books": books, "categories": up.READING_CATEGORIES}


@router.get("/reading/new")
def reading_new(request: Request, discipline: str, conn=Depends(get_db)):
    d = _discipline(conn, _semester(conn), discipline)
    return templates.TemplateResponse("university_reading_modal.html", _reading_form_context(request, conn, d, None))


@router.get("/reading/{task_uid}/edit")
def reading_edit(task_uid: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    reading = next((r for r in up.list_readings(conn, semester["uid"]) if r["task_uid"] == task_uid), None)
    if not reading:
        raise HTTPException(404, "No such reading")
    return templates.TemplateResponse("university_reading_modal.html", _reading_form_context(request, conn, _discipline(conn, semester, reading["discipline"]), reading))


@router.post("/reading")
def reading_save(discipline: str = Form(...), task_uid: str = Form(""), citation_id: str = Form(""), locator: str = Form(""), category: str = Form("recommended"),
                 notes: str = Form(""), due: str = Form(""), status: str = Form("active"), title: str = Form(""), author: str = Form(""), conn=Depends(get_db)):
    try:
        up.save_reading(conn, _semester(conn), discipline, task_uid=task_uid or None, title=title, author=author, due=due, status=status,
                        citation_id=citation_id, locator=locator, category=category, notes=notes)
    except up.PlanError as exc:
        _bad(exc)
    return _note(url_for_discipline(discipline, "bibliography"))


@router.post("/reading/{task_uid}/delete")
def reading_delete(task_uid: str, discipline: str = "", conn=Depends(get_db)):
    _semester(conn)
    up.delete_reading(conn, task_uid)
    return _note(url_for_discipline(discipline, "bibliography") if discipline else HOME)


# ---------------------------------------------------------------- homework

@router.get("/homework/new")
def homework_new(request: Request, discipline: str, conn=Depends(get_db)):
    d = _discipline(conn, _semester(conn), discipline)
    return templates.TemplateResponse("university_homework_modal.html", {"request": request, "d": d, "item": None})


@router.get("/homework/{task_uid}/edit")
def homework_edit(task_uid: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    task = db.get_task(conn, task_uid)
    tag = next((t for t in tags.tags_for_object(conn, "task", task_uid)), "") if task else ""
    if not task or not up.is_homework(conn, task_uid) or not tag:
        raise HTTPException(404, "No such homework")
    d = _discipline(conn, semester, tag)
    item = {"task_uid": task_uid, "title": task["title"], "due": (task.get("due_at") or "")[:10], "status": task["status"]}
    return templates.TemplateResponse("university_homework_modal.html", {"request": request, "d": d, "item": item})


@router.post("/homework")
def homework_save(discipline: str = Form(...), task_uid: str = Form(""), title: str = Form(""), due: str = Form(""), status: str = Form("active"),
                  conn=Depends(get_db)):
    try:
        up.save_homework(conn, _semester(conn), discipline, task_uid=task_uid or None, title=title, due=due, status=status)
    except up.PlanError as exc:
        _bad(exc)
    return _note(url_for_discipline(discipline, "exams"))


@router.post("/homework/{task_uid}/delete")
def homework_delete(task_uid: str, discipline: str = "", conn=Depends(get_db)):
    _semester(conn)
    if up.is_homework(conn, task_uid):
        db.delete_task(conn, task_uid)
    return _note(url_for_discipline(discipline, "exams") if discipline else HOME)


@router.post("/event/{uid}/delete")
def other_event_delete(uid: str, discipline: str = "", conn=Depends(get_db)):
    semester = _semester(conn)
    if discipline and up.is_other_event(conn, semester["uid"], discipline, uid):
        db.delete_event(conn, uid)
    return _note(url_for_discipline(discipline, "exams") if discipline else HOME)


# ---------------------------------------------------------------- lecture notes and class contents

notes_router = APIRouter(prefix="/university", tags=["university"], dependencies=[Depends(_enabled)])


@notes_router.post("/class/{event_uid}/note")
def class_note(event_uid: str, conn=Depends(get_db)):
    """Opens the note of a class, making it from the Lecture template the first time."""
    try:
        uid = up.open_class_note(conn, event_uid)
    except up.PlanError as exc:
        raise HTTPException(404, str(exc)) from exc
    return RedirectResponse(f"/notebook/{uid}", status_code=303)


@notes_router.get("/class/{event_uid}/content")
def class_content_form(event_uid: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    event = db.get_event(conn, event_uid)
    slot = conn.execute("SELECT * FROM university_slots WHERE series_uid = ?", (event.get("series_uid") if event else None,)).fetchone()
    if not event or not slot:
        raise HTTPException(404, "No such class")
    tag = slot["discipline_tag"]
    links = up.class_links(conn, event_uid)
    kind = slot["kind"]
    topics = [t for t in up.list_topics(conn, semester["uid"], tag) if t["kind"] == kind] or up.list_topics(conn, semester["uid"], tag)
    return templates.TemplateResponse("university_class_modal.html", {
        "request": request, "event": event, "discipline": tag, "kind": up.SLOT_KINDS.get(kind, "Class"), "topics": topics,
        "competences": up.list_topics(conn, semester["uid"], tag, "competence"), "topic_uid": links["topics"][0]["uid"] if links["topics"] else "",
        "competence_uids": [c["uid"] for c in links["competences"]], "text": up.class_free_text(conn, event_uid, event.get("description") or ""),
        "note_uid": up.class_note(conn, event_uid)})


@notes_router.post("/class/{event_uid}/content")
def class_content_save(event_uid: str, topic_uid: str = Form(""), competences: list[str] = Form(default=[]), text: str = Form(""), conn=Depends(get_db)):
    try:
        up.save_class_content(conn, event_uid, topic_uid, text, competences)
    except up.PlanError as exc:
        _bad(exc)
    return RedirectResponse(HOME, status_code=303)
