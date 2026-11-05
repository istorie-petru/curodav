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

from . import clock, db, modules, tags
from . import university_evaluation as ue
from . import university_attendance as ua
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
    """The page of a discipline (its course sheet), under the page of the space that holds the semester. `view` is kept for older callers."""
    return f"/groups/{quote(_group.get(), safe='')}/disciplines/{quote(name, safe='')}"


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
        from . import study_page
        _group.set(up.attach_group(conn, semester))
        ctx.update(disciplines=up.disciplines(conn, semester), url_for_discipline=url_for_discipline, group=_group.get(),
                   calendar=semester.get("holiday_calendar") or "", credits_planned=up.credits_planned(conn, semester["uid"]),
                   defaults=up.defaults(conn),
                   reminder_items=[{"uid": k, "name": n} for k, n in up.REMINDER_CHOICES],
                   length_items=[{"uid": k, "name": n} for k, n in up.LENGTH_CHOICES], grade_items=[{"uid": k, "name": k} for k in up.GRADE_CHOICES])
    return templates.TemplateResponse("settings_university.html", ctx)


@router.post("/defaults")
def defaults_save(class_reminder: str = Form(""), exam_reminder: str = Form(""), class_length: str = Form("110"), passing_grade: str = Form("5"),
                  conn=Depends(get_db)):
    try:
        changed = up.save_defaults(conn, up.current_semester(conn), class_reminder=class_reminder, exam_reminder=exam_reminder,
                                   class_length=class_length, passing_grade=passing_grade)
    except up.PlanError as exc:
        _bad(exc)
    return _note(HOME, f"The reminder of {changed} coming {'event' if changed == 1 else 'events'} changed" if changed else "")


# ---------------------------------------------------------------- semester

@router.get("/semester")
def semester_form(request: Request, new: str = "", conn=Depends(get_db)):
    semester = None if new else up.current_semester(conn)
    return templates.TemplateResponse("university_semester_modal.html", {
        "request": request, "semester": semester, "calendars": db.list_holiday_calendar_names(conn), "shelves": up.adoptable_shelves(conn, semester["shelf_name"] if semester else "")})


@router.post("/semester")
def semester_save(name: str = Form(""), start_date: str = Form(""), end_date: str = Form(""), class_end_date: str = Form(""),
                  holiday_calendar: str = Form(""), uid: str = Form(""), credits_target: str = Form(""), shelf: str = Form(""), conn=Depends(get_db)):
    existing = up.get_semester(conn, uid) if uid else None
    note = ""
    try:
        new_end = up._date(class_end_date, "Class end date")
        if existing and new_end and (existing.get("class_end_date") or "") != new_end.isoformat():
            plan = up.plan_class_end(conn, existing["uid"], new_end)
            if plan["removed"]:
                note = f"{plan['removed']} classes after {new_end.isoformat()} were removed" + (f", {plan['removed_with_text']} of them with contents" if plan["removed_with_text"] else "")
        up.save_semester(conn, uid=existing["uid"] if existing else None, name=name, shelf_name=shelf, start_date=start_date, end_date=end_date,
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
        values = {"code": code, "credits": credits, "type": type} if (code or credits or type) else {}
        if abbreviation or not old:
            values["abbreviation"] = abbreviation.strip() or up.auto_abbreviation(saved)
        up.save_sheet(conn, semester["uid"], saved, values)
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
    """The title and short name with what the course has, or the other notes, in a window of their own."""
    semester = _semester(conn)
    d = _discipline(conn, semester, name)
    key = "content" if section == "content" else "identification"
    sheet = up.get_sheet(conn, semester["uid"], d["name"])
    return templates.TemplateResponse("university_sheet_modal.html", {
        "request": request, "d": d, "sec": next(s for s in sheet["sections"] if s["key"] == key), "short": up.short_name(conn, semester["uid"], d["name"]),
        "kinds": up.course_kinds(conn, semester["uid"], d["name"]), "notes_text": sheet["values"].get("summary", "")})


@router.post("/sheet/{name}")
async def sheet_save(name: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, name)
    form = await request.form()
    key = "content" if str(form.get("section")) == "content" else "identification"
    saved = d["name"]
    try:
        if key == "identification":
            new_name = str(form.get("name") or "").strip()
            if new_name and new_name != d["name"]:
                saved = up.save_discipline(conn, semester, old=d["name"], name=new_name, color=d.get("color") or "gray", icon=d.get("icon") or "", teacher_names=None, colors=_colors())
            up.save_sheet(conn, semester["uid"], saved, {"abbreviation": str(form.get("f_abbreviation") or "").strip() or up.auto_abbreviation(saved)})
            up.set_course_kinds(conn, semester["uid"], saved, [str(k) for k in form.getlist("kinds")])
        else:
            up.save_sheet(conn, semester["uid"], saved, {"summary": str(form.get("f_summary") or "")})
    except (up.PlanError, tags.ManagedLabelError) as exc:
        _bad(exc)
    return _note(url_for_discipline(saved))


@router.get("/attendance/{name}")
def attendance_limits_form(name: str, request: Request, conn=Depends(get_db)):
    """The absences each class kind of the course allows: a percent of its classes, or a number that replaces the percent."""
    semester = _semester(conn)
    d = _discipline(conn, semester, name)
    settings = ua.settings(conn, semester["uid"], d["name"])
    rows = [{"kind": k, "label": up.SLOT_KINDS[k], **settings[k]} for k in up.course_kinds(conn, semester["uid"], d["name"])]
    return templates.TemplateResponse("university_attendance_limits_modal.html", {"request": request, "d": d, "rows": rows})


@router.post("/attendance/{name}")
async def attendance_limits_save(name: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, name)
    form = await request.form()
    values = {}
    for kind in up.course_kinds(conn, semester["uid"], d["name"]):
        values[f"absences_pct_{kind}"] = str(form.get(f"pct_{kind}") or "")
        values[f"absences_{kind}"] = str(form.get(f"num_{kind}") or "")
    try:
        up.save_sheet(conn, semester["uid"], d["name"], values)
    except up.PlanError as exc:
        _bad(exc)
    return _note(url_for_discipline(d["name"]))


# ---------------------------------------------------------------- evaluation

def _way_context(request: Request, conn, semester: dict, d: dict, way: dict | None) -> dict:
    events = [m for m in (way["milestones"] if way else []) if m["event_uid"] or not m["task_uid"]]
    tasks = [m for m in (way["milestones"] if way else []) if m["task_uid"]]
    options = [{"value": "other", "html": "Other"}]
    kinds = {s["kind"] for s in up.list_slots(conn, semester["uid"], d["name"])}
    options += [{"value": f"attendance:{k}", "html": f"Attendance: {up.TOPIC_KINDS[k].lower()}"} for k in ("lecture", "seminar", "lab") if k in kinds]
    for w in ue.get_evaluation(conn, semester["uid"], d["name"], with_milestones=False):
        options.append({"value": f"grade:{w['id']}", "html": f"Minimum grade: {w['name']}"})
        options += [{"value": f"grade:{s['id']}", "html": f"Minimum grade: {w['name']}, {s['name']}"} for s in w["subs"]]
    options += [{"value": f"done:{m['uid']}", "html": f"Handed in: {m['title']}"} for m in tasks]
    if way:
        for c in way["conditions"]:
            c["pick"] = "other" if c["kind"] == "other" else f"{c['kind']}:{c['target']}"
            if not any(o["value"] == c["pick"] for o in options):
                options.append({"value": c["pick"], "html": "A removed part"})
    notes = conn.execute("SELECT uid, title FROM notebook_documents WHERE is_template = 0 ORDER BY title COLLATE NOCASE").fetchall()
    return {"request": request, "d": d, "way": way, "forms": ue.EVALUATION_FORMS, "events": events, "tasks": tasks, "condition_options": options,
            "form_items": ue.FORM_ITEMS, "note_items": [{"uid": n["uid"], "name": n["title"] or "Untitled"} for n in notes]}


@router.get("/evaluation/new")
def way_new(request: Request, discipline: str, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline)
    return templates.TemplateResponse("university_evaluation_modal.html", _way_context(request, conn, semester, d, None))


@router.get("/evaluation/{way_id}/edit")
def way_edit(way_id: str, request: Request, discipline: str, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline)
    way = next((w for w in ue.get_evaluation(conn, semester["uid"], d["name"]) if w["id"] == way_id), None)
    if not way:
        raise HTTPException(404, "No such way of evaluating")
    return templates.TemplateResponse("university_evaluation_modal.html", _way_context(request, conn, semester, d, way))


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
    way_id = str(form.get("way_id") or "")
    old = next((w for w in ue.get_evaluation(conn, semester["uid"], d["name"], with_milestones=False) if w["id"] == way_id), None) or {}
    # The window no longer edits the minimum grade, criteria, conditions or text notes; an older way keeps what it had.
    way = {"id": way_id, "name": str(form.get("name") or ""), "form": str(form.get("form") or ""), "weight": str(form.get("weight") or ""),
           "elimination": bool(form.get("elimination")), "notes": old.get("notes", ""), "subs": subs, "milestones": list(milestones.values()),
           "criteria": old.get("criteria", ""), "min_grade": "" if old.get("min_grade") is None else f"{old['min_grade']:g}", "conditions": old.get("conditions", []),
           "note_uids": [str(u) for u in form.getlist("note_uids")]}
    try:
        warnings = ue.save_way(conn, semester["uid"], d["name"], way)
    except up.PlanError as exc:
        _bad(exc)
    return _note(url_for_discipline(d["name"], "exams"), "; ".join(warnings))


def _conditions_from(form) -> list[dict]:
    """Condition rows: the picked condition is "kind:target" (an Other condition is just "other"), with a value beside it."""
    out = []
    for cid, pick, value, met in zip(form.getlist("cond_id"), form.getlist("cond_pick"), form.getlist("cond_value"), form.getlist("cond_met")):
        kind, _, target = str(pick).partition(":")
        out.append({"id": cid, "kind": kind, "target": target, "value": value, "met": met == "1"})
    return out


@router.post("/evaluation/{way_id}/condition/{condition_id}")
def condition_tick(way_id: str, condition_id: str, discipline: str = Form(...), met: str = Form(""), conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline)
    ue.tick_condition(conn, semester["uid"], d["name"], way_id, condition_id, met == "1")
    return _note(url_for_discipline(d["name"], "exams"))


@router.get("/grades")
def grades_form(request: Request, discipline: str, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline)
    standing = ue.standing(conn, semester["uid"], d["name"])
    return templates.TemplateResponse("university_grades_modal.html", {
        "request": request, "d": d, "ways": standing["ways"], "grades": ue.get_grades(conn, semester["uid"], d["name"]),
        "passing": standing["passing"], "computed": standing["final"] if standing["final"] is not None else standing["so_far"]})


@router.post("/grades")
async def grades_save(request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    form = await request.form()
    d = _discipline(conn, semester, str(form.get("discipline") or ""))
    try:
        up.save_sheet(conn, semester["uid"], d["name"], {"passing": str(form.get("passing") or "")})
        ue.set_minimums(conn, semester["uid"], d["name"], {k[4:]: str(v) for k, v in form.items() if k.startswith("min_")})
        ue.set_grades(conn, semester["uid"], d["name"], {k[6:]: str(v) for k, v in form.items() if k.startswith("grade_")})
    except up.PlanError as exc:
        _bad(exc)
    return _note(url_for_discipline(d["name"]))


@router.get("/milestone/new")
def milestone_new(request: Request, discipline: str, way: str, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline)
    return templates.TemplateResponse("university_milestone_modal.html", {"request": request, "d": d, "way_id": way, "m": None, "description": ""})


@router.get("/milestone/{uid}/edit")
def milestone_edit(uid: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    m = next((x for x in ue.list_milestones(conn, semester["uid"]) if x["uid"] == uid), None)
    if not m:
        raise HTTPException(404, "No such item")
    d = _discipline(conn, semester, m["discipline"])
    item = (db.get_event(conn, m["event_uid"]) if m["event_uid"] else None) or (db.get_task(conn, m["task_uid"]) if m["task_uid"] else None) or {}
    return templates.TemplateResponse("university_milestone_modal.html", {"request": request, "d": d, "way_id": m["way_id"], "m": m, "description": item.get("description") or ""})


@router.post("/milestone")
def milestone_save(discipline: str = Form(...), way_id: str = Form(...), uid: str = Form(""), title: str = Form(""), day: str = Form(""), start: str = Form(""),
                   end: str = Form(""), due: str = Form(""), description: str = Form(""), conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline)
    try:
        ue.save_item(conn, semester["uid"], d["name"], way_id, {"uid": uid, "title": title, "day": day, "start": start, "end": end, "due": due, "description": description})
    except up.PlanError as exc:
        _bad(exc)
    return _note(url_for_discipline(d["name"]))


@router.post("/milestone/{uid}/delete")
def milestone_delete(uid: str, discipline: str = "", conn=Depends(get_db)):
    semester = _semester(conn)
    ue.delete_milestone(conn, uid)
    return _note(url_for_discipline(discipline) if discipline else HOME)


@router.get("/attach")
def attach_form(request: Request, kind: str, uid: str, back: str = "", conn=Depends(get_db)):
    """An event or task that already exists, attached to one of the ways of evaluating of the semester's disciplines."""
    semester = _semester(conn)
    item = db.get_event(conn, uid) if kind == "event" else db.get_task(conn, uid)
    if kind not in ("event", "task") or not item:
        raise HTTPException(404, "Nothing to attach")
    items = [{"uid": f"{d['name']}\t{w['id']}", "name": f"{d['name']}: {w['name']}"} for d in up.disciplines(conn, semester) for w in ue.get_evaluation(conn, semester["uid"], d["name"], with_milestones=False)]
    return templates.TemplateResponse("university_attach_modal.html", {"request": request, "kind": kind, "uid": uid, "title": item["title"], "items": items, "back": back})


@router.post("/attach")
def attach_save(kind: str = Form(...), uid: str = Form(...), way: str = Form(""), back: str = Form(""), conn=Depends(get_db)):
    semester = _semester(conn)
    discipline, _, way_id = way.partition("\t")
    try:
        ue.attach_item(conn, semester["uid"], _discipline(conn, semester, discipline)["name"], way_id, kind, uid)
    except up.PlanError as exc:
        _bad(exc)
    return RedirectResponse(back or url_for_discipline(discipline), status_code=303)


@router.post("/evaluation/{way_id}/delete")
def way_delete(way_id: str, discipline: str = "", conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline)
    warnings = ue.delete_way(conn, semester["uid"], d["name"], way_id)
    return _note(url_for_discipline(d["name"], "exams"), "; ".join(warnings))


# ---------------------------------------------------------------- timetable

def _slot_from(weekday, start, end, room, kind, weeks, teachers) -> dict:
    return {"weekday": weekday, "start": start, "end": end, "room": room, "kind": kind, "weeks": weeks, "teachers": [t for t in teachers if t]}


def _slot_context(request: Request, conn, semester: dict, d: dict | None, slot: dict | None, series_uid: str = "") -> dict:
    teachers = up.semester_teachers(conn, semester)
    return {"request": request, "d": d, "slot": slot, "series_uid": series_uid, "weekdays": up.WEEKDAYS, "kinds": up.SLOT_KINDS,
            "disciplines": up.disciplines(conn, semester), "teachers": teachers}


@router.get("/class/new")
def class_new(request: Request, discipline: str, day: str = "", conn=Depends(get_db)):
    """A class on a date of its own: a make-up class or an extra one, with the date and the kind, from the usual hours of that kind."""
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline)
    slots = up.list_slots(conn, semester["uid"], d["name"])
    usual = {s["kind"]: (s["start"], s["end"]) for s in reversed(slots)}
    return templates.TemplateResponse("university_new_class_modal.html", {
        "request": request, "d": d, "day": day or clock.today().isoformat(), "kinds": up.SLOT_KINDS, "usual": usual,
        "start": usual.get("lecture", ("10:00", "12:00"))[0], "end": usual.get("lecture", ("10:00", "12:00"))[1]})


@router.post("/class")
def class_create(discipline: str = Form(...), day: str = Form(""), kind: str = Form("lecture"), start: str = Form(""), end: str = Form(""), conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline)
    try:
        up.add_class(conn, semester, d["name"], kind, day, start, end)
    except up.PlanError as exc:
        _bad(exc)
    return _note(url_for_discipline(d["name"]))


@router.get("/slot/new")
def slot_new(request: Request, discipline: str = "", weekday: str = "", start: str = "", kind: str = "", conn=Depends(get_db)):
    """A weekly class: of a discipline (from its page), or of any discipline with the day and hour picked on the timetable."""
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline) if discipline else None
    slot = None
    if weekday or start or kind:
        length = int(up.defaults(conn)["class_length"])
        begin = start if len(start) == 5 and start[2] == ":" and start.replace(":", "").isdigit() else "08:00"
        minutes = min(int(begin[:2]) * 60 + int(begin[3:]) + length, 23 * 60 + 59)
        slot = {"weekday": int(weekday) if weekday.isdigit() and int(weekday) < 7 else 0, "start": begin, "end": f"{minutes // 60:02d}:{minutes % 60:02d}",
                "kind": kind if kind in up.SLOT_KINDS else "lecture", "weeks": "all", "room": "", "teachers": [t["uid"] for t in d["teachers"]] if d else [], "count": 0}
    return templates.TemplateResponse("university_slot_modal.html", _slot_context(request, conn, semester, d, slot))


@router.get("/slot/{series_uid}/edit")
def slot_edit(series_uid: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    slot = next((s for s in up.list_slots(conn, semester["uid"]) if s["series_uid"] == series_uid), None)
    if not slot:
        raise HTTPException(404, "No such timetable slot")
    d = _discipline(conn, semester, slot["discipline"])
    return templates.TemplateResponse("university_slot_modal.html", _slot_context(request, conn, semester, d, slot, series_uid))


@router.post("/slot")
def slot_save(discipline: str = Form(""), discipline_new: str = Form(""), series_uid: str = Form(""), weekday: str = Form("0"), start: str = Form(""),
              end: str = Form(""), room: str = Form(""), kind: str = Form("lecture"), weeks: str = Form("all"), teachers: list[str] = Form(default=[]),
              back: str = Form(""), conn=Depends(get_db)):
    """Saves a weekly class. A discipline typed in the Discipline field is made on the spot, and typed teachers become contacts."""
    semester = _semester(conn)
    try:
        name = discipline_new.strip() or discipline.strip()
        if not name:
            raise up.PlanError("Pick a discipline")
        discipline = up.quick_discipline(conn, semester, name, _colors())
        slot = _slot_from(weekday, start, end, room, kind, weeks, up.tag_teachers(conn, discipline, teachers))
        plan = up.plan_slot(conn, semester, discipline, slot, series_uid or None)
        up.save_slot(conn, semester, discipline, slot, series_uid or None)
        up.sync_teachers(conn, semester["uid"], discipline)
    except (up.PlanError, tags.ManagedLabelError) as exc:
        _bad(exc)
    notes = ["Past classes were not moved"] if plan["past"] else []
    if plan["lost"]:
        notes.append(f"The contents of {len(plan['lost'])} classes were lost: they no longer exist")
    return _note(HOME if back == "settings" else url_for_discipline(discipline, "sheet"), "; ".join(notes))


@router.post("/slot/{series_uid}/delete")
def slot_delete(series_uid: str, discipline: str = "", conn=Depends(get_db)):
    _semester(conn)
    semester = up.current_semester(conn)
    slot = next((x for x in up.list_slots(conn, semester["uid"], history=True) if x["series_uid"] == series_uid), None)
    discipline = discipline or (slot["discipline"] if slot else "")
    removed = up.delete_slot(conn, semester["uid"], series_uid)
    if discipline:
        up.sync_teachers(conn, semester["uid"], discipline)
    return _note(url_for_discipline(discipline, "sheet") if discipline else HOME, f"{removed} classes removed")


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
                 notes: str = Form(""), title: str = Form(""), author: str = Form(""), conn=Depends(get_db)):
    try:
        up.save_reading(conn, _semester(conn), discipline, task_uid=task_uid or None, title=title, author=author,
                        citation_id=citation_id, locator=locator, category=category, notes=notes)
    except up.PlanError as exc:
        _bad(exc)
    return _note(url_for_discipline(discipline))


@router.post("/reading/{task_uid}/delete")
def reading_delete(task_uid: str, discipline: str = "", conn=Depends(get_db)):
    _semester(conn)
    up.delete_reading(conn, task_uid)
    return _note(url_for_discipline(discipline) if discipline else HOME)


# ---------------------------------------------------------------- homework

@router.get("/homework/new")
def homework_new(request: Request, discipline: str, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, discipline)
    # homework is usually due at the next class, so that day is already filled in
    today = clock.today().isoformat()
    due = next((c["date"] for c in up.list_classes(conn, semester["uid"], d["name"], clock.today()) if c["date"] >= today), "")
    return templates.TemplateResponse("university_homework_modal.html", {"request": request, "d": d, "item": None, "due": due})


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
                  back: str = Form(""), conn=Depends(get_db)):
    try:
        up.save_homework(conn, _semester(conn), discipline, task_uid=task_uid or None, title=title, due=due, status=status)
    except up.PlanError as exc:
        _bad(exc)
    return _note(url_for_discipline(discipline, "" if back == "overview" else "exams"))


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


@notes_router.get("/class/{event_uid}/makeup")
def makeup_form(event_uid: str, request: Request, conn=Depends(get_db)):
    """A missed class made up another day: the same class moves to the date and hours picked here."""
    _semester(conn)
    event = db.get_event(conn, event_uid)
    if not event or not _class_discipline(conn, event):
        raise HTTPException(404, "No such class")
    mark = ua.statuses_of(conn, [event_uid]).get(event_uid) or {"status": "", "note": ""}
    return templates.TemplateResponse("university_makeup_modal.html", {"request": request, "event": event, "discipline": _class_discipline(conn, event), "note": mark["note"]})


@notes_router.post("/class/{event_uid}/makeup")
def makeup_save(event_uid: str, day: str = Form(...), start: str = Form(...), end: str = Form(...), note: str = Form(""), back: str = Form("calendar"), conn=Depends(get_db)):
    _semester(conn)
    try:
        ua.make_up(conn, event_uid, f"{day}T{start}", f"{day}T{end}", note)
    except up.PlanError as exc:
        _bad(exc)
    return RedirectResponse("/calendar" if back == "calendar" else HOME, status_code=303)


@notes_router.get("/class/{event_uid}/attendance")
def attendance_form(event_uid: str, request: Request, back: str = "", conn=Depends(get_db)):
    """One question: how the class went, with a note (who lent the notes, when it was made up)."""
    _semester(conn)
    event = db.get_event(conn, event_uid)
    if not event or not _class_discipline(conn, event):
        raise HTTPException(404, "No such class")
    mark = ua.statuses_of(conn, [event_uid]).get(event_uid) or {"status": "attended", "note": ""}
    return templates.TemplateResponse("university_attendance_modal.html", {
        "request": request, "event": event, "discipline": _class_discipline(conn, event), "mark": mark, "statuses": ua.STATUSES, "back": back})


@notes_router.post("/class/{event_uid}/attendance")
def attendance_save(event_uid: str, status: str = Form(...), note: str = Form(""), back: str = Form(""), keep_note: str = Form(""), conn=Depends(get_db)):
    """Marks a class. From a menu only the status is sent, so the note already there is kept."""
    semester = _semester(conn)
    event = db.get_event(conn, event_uid)
    discipline = _class_discipline(conn, event)
    if keep_note:
        note = (ua.statuses_of(conn, [event_uid]).get(event_uid) or {}).get("note", "")
    try:
        ua.set_status(conn, event_uid, status, note)
    except up.PlanError as exc:
        _bad(exc)
    if back == "calendar":
        return RedirectResponse("/calendar", status_code=303)
    if back == "semester":
        return _note(f"/groups/{quote(up.semester_group(conn, semester), safe='')}")
    return _note(url_for_discipline(discipline) if discipline else HOME)


def _class_discipline(conn, event) -> str:
    row = conn.execute("SELECT discipline_tag FROM university_slots WHERE series_uid = ?", (event.get("series_uid") if event else None,)).fetchone()
    return row["discipline_tag"] if row else ""
