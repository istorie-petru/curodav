"""The University module: registers itself with the module framework (src/modules.py) and serves its Settings page.

The Settings page under Modules is the one place that describes a semester: its dates, its disciplines, and for each discipline its
timetable, syllabus, exams and readings. Every item with several fields opens in the usual modal from its row; anything that creates
or removes many rows shows a preview first (a GET that renders the plan) and then applies that same plan (a POST). The domain rules
live in `university_plan.py`; the study page is `study_page.py`. The module is off unless CC_MODULES lists `university`.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from . import db, modules, study_format, tags
from . import university_plan as up
from .deps import get_db, templates

MODULE = modules.register(modules.Module("university", "University", "/settings/university", icon="graduation-cap"))


def _render_study(conn, request, name, label):
    from . import study_page
    return study_page.render(conn, request, name, label)


modules.register_page_type(modules.PageType(up.PAGE_TYPE, "Study page", MODULE.key, _render_study))


def _enabled() -> None:
    if not modules.is_enabled(MODULE.key):
        raise HTTPException(404, "Not found")


router = APIRouter(prefix="/settings/university", tags=["university"], dependencies=[Depends(_enabled)])

HOME = "/settings/university"


def _semester(conn) -> dict:
    semester = up.current_semester(conn)
    if not semester:
        raise HTTPException(409, "Create the semester first")
    return semester


def _discipline(conn, semester: dict, name: str) -> dict:
    found = next((d for d in up.disciplines(conn, semester) if d["name"].lower() == name.lower()), None)
    if not found:
        raise HTTPException(404, "No such discipline")
    return found


def _bad(exc: Exception):
    raise HTTPException(400, str(exc)) from exc


def url_for_discipline(name: str) -> str:
    return f"{HOME}/discipline/{quote(name, safe='')}"


def _colors():
    from .routers.labels import COLORS
    return COLORS


def _icon_groups(current=None):
    from .routers.labels import icon_groups_for
    return icon_groups_for(current)


def _preview(request: Request, *, title: str, lines: list[str], action: str, fields: dict, confirm: str, back: str = "", warnings: list[str] | None = None,
             error: str = "", cancel: str = ""):
    return templates.TemplateResponse("university_preview_modal.html", {
        "request": request, "title": title, "lines": lines, "warnings": warnings or [], "action": action, "fields": fields,
        "confirm": confirm, "back": back, "error": error})


# ---------------------------------------------------------------- the page

@router.get("")
def university_settings(request: Request, conn=Depends(get_db)):
    semester = up.current_semester(conn)
    ctx = {"request": request, "semester": semester}
    if semester:
        ctx.update(disciplines=up.disciplines(conn, semester), exams=up.list_exams(conn, semester["uid"]),
                   url_for_discipline=url_for_discipline)
    return templates.TemplateResponse("settings_university.html", ctx)


# ---------------------------------------------------------------- semester

@router.get("/semester")
def semester_form(request: Request, name: str = "", shelf_name: str = "", start_date: str = "", end_date: str = "", class_end_date: str = "",
                  holiday_calendar: str = "", conn=Depends(get_db)):
    semester = up.current_semester(conn)
    typed = {"name": name, "shelf_name": shelf_name, "start_date": start_date, "end_date": end_date, "class_end_date": class_end_date,
             "holiday_calendar": holiday_calendar}
    if any(typed.values()):  # coming back from the preview: keep what was typed
        semester = {**(semester or {}), **{k: v for k, v in typed.items() if v}}
    return templates.TemplateResponse("university_semester_modal.html", {
        "request": request, "semester": semester, "calendars": db.list_holiday_calendar_names(conn)})


def _semester_fields(name, shelf_name, start_date, end_date, class_end_date, holiday_calendar) -> dict:
    return {"name": name, "shelf_name": shelf_name, "start_date": start_date, "end_date": end_date, "class_end_date": class_end_date,
            "holiday_calendar": holiday_calendar}


@router.get("/semester/preview")
def semester_preview(request: Request, name: str = "", shelf_name: str = "", start_date: str = "", end_date: str = "",
                     class_end_date: str = "", holiday_calendar: str = "", conn=Depends(get_db)):
    semester = up.current_semester(conn)
    fields = _semester_fields(name, shelf_name, start_date, end_date, class_end_date, holiday_calendar)
    back = f"{HOME}/semester?{urlencode({k: v for k, v in fields.items() if v})}"
    try:
        lines, warnings = [], []
        if semester:
            lines.append(f"{semester['name']} keeps its shelf {semester['shelf_name']}.")
            new_end = up._date(class_end_date, "Class end date")
            if new_end and (semester.get("class_end_date") or "") != new_end.isoformat():
                plan = up.plan_class_end(conn, semester["uid"], new_end)
                lines.append(f"Moving the class end date to {new_end.isoformat()} removes {plan['removed']} classes and adds {plan['added']}. Exams, tasks and one-off events are not touched.")
                if plan["removed_with_text"]:
                    warnings.append(f"{plan['removed_with_text']} of the classes removed carry a topic or notes.")
        else:
            if not name.strip():
                raise up.PlanError("The semester needs a name")
            plan = up.plan_semester(conn, shelf_name.strip() or name.strip())
            if plan["adopts"]:
                lines.append(f"The shelf {plan['shelf']} already exists and is adopted. Its {len(plan['tags'])} tags become disciplines.")
            else:
                lines.append(f"A new shelf {plan['shelf']} is created for the semester.")
            lines.append("The shelf and its tags become read only in Organise; this page is where they are changed.")
        up._date(start_date, "Start date")
        up._date(end_date, "End date")
    except up.PlanError as exc:
        return _preview(request, title="Semester", lines=[], action="", fields={}, confirm="", back=back, error=str(exc))
    return _preview(request, title="Save the semester" if semester else "Create the semester", lines=lines, warnings=warnings, action=f"{HOME}/semester",
                    fields=fields, confirm="Save" if semester else "Create", back=back)


@router.post("/semester")
def semester_save(name: str = Form(""), shelf_name: str = Form(""), start_date: str = Form(""), end_date: str = Form(""),
                  class_end_date: str = Form(""), holiday_calendar: str = Form(""), conn=Depends(get_db)):
    current = up.current_semester(conn)
    try:
        up.save_semester(conn, uid=current["uid"] if current else None, name=name, shelf_name=shelf_name, start_date=start_date,
                         end_date=end_date, class_end_date=class_end_date, holiday_calendar=holiday_calendar)
    except up.PlanError as exc:
        _bad(exc)
    return RedirectResponse(HOME, status_code=303)


# ---------------------------------------------------------------- disciplines

@router.get("/discipline/new")
def discipline_new(request: Request, conn=Depends(get_db)):
    _semester(conn)
    return templates.TemplateResponse("university_discipline_modal.html", {
        "request": request, "d": None, "colors": _colors(), "icon_groups": _icon_groups(), "teacher_names": ""})


@router.get("/discipline/{name}/edit")
def discipline_edit(name: str, request: Request, conn=Depends(get_db)):
    d = _discipline(conn, _semester(conn), name)
    return templates.TemplateResponse("university_discipline_modal.html", {
        "request": request, "d": d, "colors": _colors(), "icon_groups": _icon_groups(d.get("icon")),
        "teacher_names": ", ".join(t["name"] for t in d["teachers"])})


@router.get("/discipline/{name}")
def discipline_view(name: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, name)
    slots = up.list_slots(conn, semester["uid"], d["name"])
    contacts = {t["uid"]: t["name"] for t in d["teachers"]}
    for s in slots:
        s["weekday_name"] = up.WEEKDAYS[s["weekday"]]
        s["teacher_names"] = ", ".join(contacts.get(u, "") for u in s["teachers"] if u in contacts)
    return templates.TemplateResponse("university_discipline_view.html", {
        "request": request, "semester": semester, "d": d, "slots": slots, "kinds": up.SLOT_KINDS,
        "topics": up.list_topics(conn, semester["uid"], d["name"]), "exams": up.list_exams(conn, semester["uid"], d["name"]),
        "readings": up.list_readings(conn, semester["uid"], d["name"]), "url_for_discipline": url_for_discipline,
        "removal_blocker": up.removal_blockers(conn, semester, d["name"])})


@router.post("/discipline")
def discipline_save(old: str = Form(""), name: str = Form(""), color: str = Form("gray"), icon: str = Form(""), teacher_names: str = Form(""),
                    conn=Depends(get_db)):
    semester = _semester(conn)
    try:
        saved = up.save_discipline(conn, semester, old=old, name=name, color=color, icon=icon, teacher_names=teacher_names, colors=_colors())
    except (up.PlanError, tags.ManagedLabelError) as exc:
        _bad(exc)
    return RedirectResponse(url_for_discipline(saved), status_code=303)


@router.post("/discipline/{name}/remove")
def discipline_remove(name: str, conn=Depends(get_db)):
    try:
        up.remove_discipline(conn, _semester(conn), name)
    except up.PlanError as exc:
        _bad(exc)
    return RedirectResponse(HOME, status_code=303)


# ---------------------------------------------------------------- timetable

def _slot_from(weekday, start, end, room, kind, weeks, teachers) -> dict:
    return {"weekday": weekday, "start": start, "end": end, "room": room, "kind": kind, "weeks": weeks,
            "teachers": [t for t in teachers if t]}


def _typed_slot(base: dict | None, weekday, start, end, room, kind, weeks, teachers) -> dict | None:
    """The slot as typed before a preview, or the stored one."""
    if not (start or end or room or teachers):
        return base
    return {**(base or {}), "weekday": int(weekday) if str(weekday).isdigit() else 0, "start": start, "end": end, "room": room, "kind": kind,
            "weeks": weeks, "teachers": list(teachers)}


@router.get("/slot/new")
def slot_new(request: Request, discipline: str, weekday: str = "0", start: str = "", end: str = "", room: str = "", kind: str = "lecture",
             weeks: str = "all", teachers: list[str] = Query(default=[]), conn=Depends(get_db)):
    d = _discipline(conn, _semester(conn), discipline)
    return templates.TemplateResponse("university_slot_modal.html", {
        "request": request, "d": d, "slot": _typed_slot(None, weekday, start, end, room, kind, weeks, teachers), "series_uid": "", "weekdays": up.WEEKDAYS, "kinds": up.SLOT_KINDS,
        "back": url_for_discipline(d["name"])})


@router.get("/slot/{series_uid}/edit")
def slot_edit(series_uid: str, request: Request, weekday: str = "0", start: str = "", end: str = "", room: str = "", kind: str = "lecture",
              weeks: str = "all", teachers: list[str] = Query(default=[]), conn=Depends(get_db)):
    semester = _semester(conn)
    slot = next((s for s in up.list_slots(conn, semester["uid"]) if s["series_uid"] == series_uid), None)
    if not slot:
        raise HTTPException(404, "No such timetable slot")
    d = _discipline(conn, semester, slot["discipline"])
    return templates.TemplateResponse("university_slot_modal.html", {
        "request": request, "d": d, "slot": _typed_slot(slot, weekday, start, end, room, kind, weeks, teachers), "series_uid": series_uid, "weekdays": up.WEEKDAYS, "kinds": up.SLOT_KINDS,
        "back": url_for_discipline(d["name"])})


@router.get("/slot/preview")
def slot_preview(request: Request, discipline: str, series_uid: str = "", weekday: str = "0", start: str = "", end: str = "", room: str = "",
                 kind: str = "lecture", weeks: str = "all", teachers: list[str] = Query(default=[]), conn=Depends(get_db)):
    semester = _semester(conn)
    slot = _slot_from(weekday, start, end, room, kind, weeks, list(teachers))
    typed = urlencode([("weekday", weekday), ("start", start), ("end", end), ("room", room), ("kind", kind), ("weeks", weeks), *[("teachers", t) for t in teachers]])
    back = f"{HOME}/slot/{series_uid}/edit?{typed}" if series_uid else f"{HOME}/slot/new?discipline={quote(discipline, safe='')}&{typed}"
    try:
        plan = up.plan_slot(conn, semester, discipline, slot, series_uid or None)
    except up.PlanError as exc:
        return _preview(request, title="Timetable", lines=[], action="", fields={}, confirm="", back=back, error=str(exc))
    s = plan["slot"]
    label = up.SLOT_KINDS[s["kind"]].lower()
    lines = [f"{plan['classes']} {label} classes of {discipline}, every {'week' if s['weeks'] == 'all' else s['weeks'] + ' week'} on {up.WEEKDAYS[s['weekday']]} "
             f"{s['start']} to {s['end']}, from {plan['first']} to {plan['last']}."]
    if series_uid and not plan["rebuilds"]:
        lines = [f"The {plan['classes']} existing classes keep their dates and notes; only time, room, kind and teacher change."]
    warnings = []
    if plan["lost"]:
        warnings.append("Text on these classes would be lost: " + ", ".join(plan["lost"]) + ".")
    fields = {"discipline": discipline, "series_uid": series_uid, "weekday": s["weekday"], "start": s["start"], "end": s["end"], "room": s["room"],
              "kind": s["kind"], "weeks": s["weeks"], "teachers": s["teachers"]}
    return _preview(request, title="Save the timetable slot" if series_uid else "Create the timetable slot", lines=lines, warnings=warnings,
                    action=f"{HOME}/slot", fields=fields, confirm="Save" if series_uid else "Create", back=back)


@router.post("/slot")
def slot_save(discipline: str = Form(...), series_uid: str = Form(""), weekday: str = Form("0"), start: str = Form(""), end: str = Form(""),
              room: str = Form(""), kind: str = Form("lecture"), weeks: str = Form("all"), teachers: list[str] = Form(default=[]), conn=Depends(get_db)):
    try:
        up.save_slot(conn, _semester(conn), discipline, _slot_from(weekday, start, end, room, kind, weeks, teachers), series_uid or None)
    except up.PlanError as exc:
        _bad(exc)
    return RedirectResponse(url_for_discipline(discipline), status_code=303)


@router.post("/slot/{series_uid}/delete")
def slot_delete(series_uid: str, discipline: str = "", conn=Depends(get_db)):
    up.delete_slot(conn, _semester(conn)["uid"], series_uid)
    return RedirectResponse(url_for_discipline(discipline) if discipline else HOME, status_code=303)


# ---------------------------------------------------------------- syllabus

@router.get("/syllabus/{name}")
def syllabus_form(name: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, name)
    return templates.TemplateResponse("university_syllabus_modal.html", {
        "request": request, "d": d, "text": up.syllabus_text(conn, semester["uid"], d["name"]), "back": url_for_discipline(d["name"])})


@router.post("/syllabus/{name}")
def syllabus_save(name: str, themes: str = Form(""), conn=Depends(get_db)):
    semester = _semester(conn)
    up.save_syllabus(conn, semester["uid"], _discipline(conn, semester, name)["name"], themes)
    return RedirectResponse(url_for_discipline(name), status_code=303)


@router.get("/syllabus/{name}/assign")
def syllabus_assign_preview(name: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    d = _discipline(conn, semester, name)
    plan = up.plan_assign_in_order(conn, semester["uid"], d["name"])
    back = url_for_discipline(d["name"])
    if not plan["pairs"]:
        return _preview(request, title="Topics to classes", lines=[], action="", fields={}, confirm="", back=back,
                        error="There is no topic left to place, or no lecture class without text.")
    lines = [f"{num}. {title} goes to the class of {day}." for _, _, num, title, day in plan["pairs"][:12]]
    if len(plan["pairs"]) > 12:
        lines.append(f"And {len(plan['pairs']) - 12} more.")
    warnings = []
    if plan["blocked"]:
        warnings.append("Classes with their own text are skipped: " + ", ".join(plan["blocked"][:8]) + ".")
    if plan["left_over"]:
        warnings.append(f"{plan['left_over']} topics find no free lecture class.")
    return _preview(request, title="Place topics in classes", lines=lines, warnings=warnings, action=f"{HOME}/syllabus/{quote(d['name'], safe='')}/assign",
                    fields={}, confirm="Apply", back=back)


@router.post("/syllabus/{name}/assign")
def syllabus_assign(name: str, conn=Depends(get_db)):
    semester = _semester(conn)
    up.apply_assign_in_order(conn, semester["uid"], _discipline(conn, semester, name)["name"])
    return RedirectResponse(url_for_discipline(name), status_code=303)


# ---------------------------------------------------------------- exams

@router.get("/exam/new")
def exam_new(request: Request, discipline: str, conn=Depends(get_db)):
    d = _discipline(conn, _semester(conn), discipline)
    return templates.TemplateResponse("university_exam_modal.html", {"request": request, "d": d, "exam": None, "back": url_for_discipline(d["name"])})


@router.get("/exam/{task_uid}/edit")
def exam_edit(task_uid: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    exam = next((e for e in up.list_exams(conn, semester["uid"]) if e["task_uid"] == task_uid), None)
    if not exam:
        raise HTTPException(404, "No such exam")
    d = _discipline(conn, semester, exam["discipline"])
    return templates.TemplateResponse("university_exam_modal.html", {"request": request, "d": d, "exam": exam, "back": url_for_discipline(d["name"])})


@router.post("/exam")
def exam_save(discipline: str = Form(...), task_uid: str = Form(""), title: str = Form(""), day: str = Form(""), start: str = Form("09:00"),
              end: str = Form("11:00"), weight: str = Form(""), location: str = Form(""), conn=Depends(get_db)):
    try:
        up.save_exam(conn, _semester(conn), discipline, task_uid=task_uid or None, title=title, day=day, start=start, end=end, weight=weight, location=location)
    except up.PlanError as exc:
        _bad(exc)
    return RedirectResponse(url_for_discipline(discipline), status_code=303)


@router.post("/exam/{task_uid}/delete")
def exam_delete(task_uid: str, discipline: str = "", conn=Depends(get_db)):
    up.delete_exam(conn, task_uid)
    return RedirectResponse(url_for_discipline(discipline) if discipline else HOME, status_code=303)


# ---------------------------------------------------------------- readings

@router.get("/reading/new")
def reading_new(request: Request, discipline: str, conn=Depends(get_db)):
    d = _discipline(conn, _semester(conn), discipline)
    return templates.TemplateResponse("university_reading_modal.html", {"request": request, "d": d, "reading": None, "back": url_for_discipline(d["name"])})


@router.get("/reading/{task_uid}/edit")
def reading_edit(task_uid: str, request: Request, conn=Depends(get_db)):
    semester = _semester(conn)
    reading = next((r for r in up.list_readings(conn, semester["uid"]) if r["task_uid"] == task_uid), None)
    if not reading:
        raise HTTPException(404, "No such reading")
    d = _discipline(conn, semester, reading["discipline"])
    return templates.TemplateResponse("university_reading_modal.html", {"request": request, "d": d, "reading": reading, "back": url_for_discipline(d["name"])})


@router.post("/reading")
def reading_save(discipline: str = Form(...), task_uid: str = Form(""), title: str = Form(""), author: str = Form(""), due: str = Form(""),
                 status: str = Form("active"), conn=Depends(get_db)):
    try:
        up.save_reading(conn, _semester(conn), discipline, task_uid=task_uid or None, title=title, author=author, due=due, status=status)
    except up.PlanError as exc:
        _bad(exc)
    return RedirectResponse(url_for_discipline(discipline), status_code=303)


@router.post("/reading/{task_uid}/delete")
def reading_delete(task_uid: str, discipline: str = "", conn=Depends(get_db)):
    up.delete_reading(conn, task_uid)
    return RedirectResponse(url_for_discipline(discipline) if discipline else HOME, status_code=303)


# ---------------------------------------------------------------- JSON export and import

@router.get("/export")
def export_json(what: str = "semester", discipline: str = "", conn=Depends(get_db)):
    semester = _semester(conn)
    try:
        if what == "discipline":
            data = up.export_discipline(conn, semester, discipline)
        else:
            data = up.export_semester(conn, semester)
            what = "semester"
        text = study_format.dump(what, data)
    except (up.PlanError, study_format.FormatError) as exc:
        _bad(exc)
    filename = f"{(discipline if what == 'discipline' else semester['name']).replace(' ', '-').lower()}.curodav-university.json"
    return Response(text, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


_PENDING: dict[str, tuple[str, dict]] = {}  # the uploaded file waiting for its preview to be confirmed (one user, one slot)


@router.get("/import")
def import_form(request: Request, discard: str = "", conn=Depends(get_db)):
    if discard:
        _PENDING.clear()
    semester = _semester(conn)
    pending = _PENDING.get("import")
    plan = up.plan_import(conn, semester, *pending) if pending else None
    return templates.TemplateResponse("university_import_modal.html", {"request": request, "plan": plan})


@router.post("/import/upload")
async def import_upload(file: UploadFile = File(...), conn=Depends(get_db)):
    _semester(conn)
    text = (await file.read()).decode("utf-8", errors="replace")
    try:
        _PENDING["import"] = study_format.load(text)
    except study_format.FormatError as exc:
        _bad(exc)
    return RedirectResponse(f"{HOME}/import", status_code=303)


@router.post("/import/apply")
def import_apply(conn=Depends(get_db)):
    semester = _semester(conn)
    pending = _PENDING.pop("import", None)
    if not pending:
        raise HTTPException(409, "There is no file waiting to be imported")
    try:
        up.apply_import(conn, semester, *pending, colors=_colors())
    except up.PlanError as exc:
        _bad(exc)
    return RedirectResponse(HOME, status_code=303)


# ---------------------------------------------------------------- lecture notes

notes_router = APIRouter(prefix="/university", tags=["university"], dependencies=[Depends(_enabled)])


@notes_router.post("/class/{event_uid}/note")
def class_note(event_uid: str, conn=Depends(get_db)):
    """Opens the note of a class, making it from the Lecture template the first time."""
    try:
        uid = up.open_class_note(conn, event_uid)
    except up.PlanError as exc:
        raise HTTPException(404, str(exc)) from exc
    return RedirectResponse(f"/notebook/{uid}", status_code=303)
