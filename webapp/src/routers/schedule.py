from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db, grid_layout, schedule as schedule_logic
from ..deps import get_db, templates

router = APIRouter(prefix="/schedule", tags=["schedule"])

PARITIES = ["all", "odd", "even"]

# Table view: sortable columns + a search box + inline-editable pills for
# Day/Parity/Time/Enrolled, mirroring the Tasks table (tasks_list.html,
# routers/tasks.py) feature-for-feature wherever a class actually has an
# equivalent field.
_SORT_KEYS = {
    "day": lambda c: (schedule_logic.DAYS.index(c["day"]) if c["day"] in schedule_logic.DAYS else 99, c["start_time"]),
    "time": lambda c: c["start_time"],
    "name": lambda c: (c.get("name") or "").lower(),
    "professor": lambda c: (c.get("professor") or "").lower(),
    "room": lambda c: (c.get("room") or "").lower(),
    "credits": lambda c: c.get("credits") or 0,
    "parity": lambda c: c.get("parity") or "",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------- #
# Enriching a class event -- 1.6 (Schedule & recurrence rework): a "class"
# in this router is always a real recurring `events` row (tagged with the
# Schedule system label + its course's project label). Every place that
# used to read a schedule_classes row's own day/acronym/professor/credits/
# parity/name columns now reads this same shape off an enriched dict
# instead, built here -- so schedule_classes.html/schedule_class_form.html
# needed NO template changes at all, only this router did: day/parity are
# derived from the event's own start_at/recurrence (schedule.event_day/
# event_parity, never stored separately), start_time/end_time are sliced
# off start_at/end_at, name/room are the event's own title/location, and
# acronym/class_type/credits/professor come from the course label's own
# label_config row (db.py's label_config CREATE TABLE comment explains why
# those four live there instead of on the event).
# --------------------------------------------------------------------- #


def _course_label_and_config(conn, event: dict) -> tuple[str | None, dict]:
    name = db.project_label_for(conn, "event", event["uid"])
    cfg = db.get_label_config(conn, name) if name else None
    return name, (cfg or {})


def _class_row(conn, event: dict, today: date | None = None) -> dict:
    course_name, cfg = _course_label_and_config(conn, event)
    professor_uid = cfg.get("course_professor_contact_uid")
    contact = db.get_contact(conn, professor_uid) if professor_uid else None
    start_at = event.get("start_at") or ""
    end_at = event.get("end_at") or ""
    row = {
        "uid": event["uid"],
        "day": schedule_logic.event_day(event),
        "parity": schedule_logic.event_parity(event),
        "start_time": start_at[11:16] if len(start_at) >= 16 else "",
        "end_time": end_at[11:16] if len(end_at) >= 16 else "",
        "name": event.get("title") or "",
        "room": event.get("location") or "",
        "enrolled": event.get("status") != "archived",
        "acronym": cfg.get("course_acronym"),
        "class_type": cfg.get("course_type"),
        "credits": cfg.get("course_credits") or 0,
        "professor_contact_uid": professor_uid,
        "professor": contact["full_name"] if contact else None,
        "project_uid": course_name,
        "tags": event.get("tags") or [],
    }
    nxt = schedule_logic.next_occurrence_for_event(event, today, holiday_calendars=db.list_holidays_by_calendar(conn))
    row["next_occurrence"] = schedule_logic.next_label(nxt, today) if nxt else None
    return row


def _course_field_dict(
    acronym: str, class_type: str, credits_val: str, professor_contact_uid: str | None
) -> dict:
    return {
        "course_acronym": acronym.strip() or None,
        "course_type": class_type.strip() or None,
        "course_credits": float(credits_val) if credits_val else 0.0,
        "course_professor_contact_uid": professor_contact_uid,
    }


def _infer_schedule_group(conn) -> str | None:
    """Find the Space label (generate_space=1) that other class events
    already carry, if any -- when a user has a "University" Space with
    existing classes, every subsequent class's auto-applied course label
    should carry that same Space label too rather than floating without
    one."""
    for event in db.list_schedule_class_events(conn):
        for name in event.get("tags") or []:
            cfg = db.get_label_config(conn, name)
            if cfg and cfg.get("generate_space"):
                return name
    return None


def _auto_provision_course_label(conn, name: str) -> tuple[str, str | None]:
    """Creates a label named after the class (the "course becomes a
    project" behavior) and returns (course_label, space_label) -- the
    caller tags the class event with both directly (direct object_labels
    membership, not just label_config's `parent_name` nesting -- a Space
    page aggregates by direct membership only, see features/
    architecture.md §2/§5) when other class events already carry a Space
    label (e.g. "University"). Marks the new label `is_project=1`: 1.6's
    "Classes as project labels" line means a course is meant to actually
    get Project treatment (show on /projects, get a lifecycle), not just
    be "the one non-Space label attached" the way the pre-1.3 heuristic
    used to infer it. Only called when the create/edit form didn't already
    name an existing label to use."""
    space_label = _infer_schedule_group(conn)
    db.upsert_label_config(
        conn,
        {
            "name": name,
            "color": "blue",
            "icon": "book-open",
            "parent_name": space_label,
            "is_project": 1,
            "created_at": _now(),
        },
    )
    return name, space_label


def _resolve_new_professor_name(text: str, conn) -> str | None:
    """Turns a typed "+ Add new professor..." name into a contacts.uid --
    checks for an existing exact-name match first as a dedupe safety net,
    same as before 1.6. If no match: creates a new contact with just that
    name and returns its uid."""
    text = text.strip()
    if not text:
        return None
    existing = db.find_contact_by_name(conn, text)
    if existing:
        return existing["uid"]
    now = _now()
    row = {"uid": str(uuid.uuid4()), "full_name": text, "created_at": now, "updated_at": now}
    db.upsert_contact(conn, row)
    return row["uid"]


def _resolve_professor_field(professor_select: str, professor_new: str, conn) -> str | None:
    if professor_select == "__new__":
        return _resolve_new_professor_name(professor_new, conn)
    if professor_select:
        contact = db.get_contact(conn, professor_select)
        if contact:
            return contact["uid"]
    return None


def _resolve_class_type_field(class_type_select: str, class_type_other: str) -> str:
    if class_type_select == "__other__":
        return class_type_other
    return class_type_select


def _regenerate_event(uid: str, day: str, start_time: str, end_time: str, parity: str, title: str, room: str, enrolled: bool, conn) -> None:
    """(Re)build one class meeting's recurring event from its own
    day/time/parity/title/room + the current semester settings, and write
    it straight into the universal `events` pool -- preserves whatever
    tags/uid the event already carries (upsert_event only replaces tags
    when explicitly given, and this never passes `tags`). Holiday exclusion
    is no longer computed here (1.6, "Generalized recurrence and the
    non-working-day policy") -- build_class_event_row just copies
    settings['holiday_calendar'] onto the event, applied generically at
    read time."""
    settings = db.get_schedule_settings(conn)
    row = schedule_logic.build_class_event_row(
        {
            "uid": uid,
            "day": day,
            "start_time": start_time,
            "end_time": end_time,
            "title": title,
            "room": room,
            "parity": parity,
            "enrolled": enrolled,
        },
        settings,
    )
    db.upsert_event(conn, row)


def _regenerate_all(conn) -> None:
    """Every class event's start_at/end_at/recurrence depend on settings
    (semester bounds, holiday calendar) that just changed -- rebuild each
    from its own current day/time/parity/title/room/enrolled (all still
    derivable off the event itself), same as before 1.6."""
    for event in db.list_schedule_class_events(conn):
        row = _class_row(conn, event)
        _regenerate_event(
            event["uid"], row["day"], row["start_time"], row["end_time"],
            row["parity"], row["name"], row["room"], row["enrolled"], conn,
        )


@router.get("")
def classes_view(
    request: Request,
    view: str = "table",
    q: str | None = None,
    label: str | None = None,
    sort: str = "day",
    dir: str = "asc",
    conn=Depends(get_db),
):
    today = date.today()
    all_events = db.list_schedule_class_events(conn)
    all_classes = [_class_row(conn, e, today) for e in all_events]
    settings = db.get_schedule_settings(conn)
    # Conflicts/credits always reflect *every* class, never the search box
    # or label filter -- computed on the enriched dicts (by uid) rather
    # than the raw events, so the warnings strip reads the same
    # acronym/name shape the table rows do.
    _by_uid = {c["uid"]: c for c in all_classes}
    conflicts = [
        (_by_uid[a["uid"]], _by_uid[b["uid"]])
        for a, b in schedule_logic.compute_conflicts(all_events)
    ]
    # Credits are a *course* fact now, not a per-meeting one -- summed once
    # per distinct course label with at least one active (enrolled)
    # meeting, not once per meeting (a course with a lecture + a seminar
    # shouldn't double its own credits).
    course_labels = {c["project_uid"] for c in all_classes if c["project_uid"] and c["enrolled"]}
    used_credits = 0.0
    for name in course_labels:
        cfg = db.get_label_config(conn, name)
        if cfg and cfg.get("course_credits"):
            used_credits += cfg["course_credits"]
    needed = settings.get("credits_needed")

    # Label filter (single-select fancy toolbar dropdown, same as
    # Calendar/Tasks): classes link to a course label, so the dropdown
    # lists only labels actually attached to at least one class.
    label_items: list[dict] = []
    _seen: set[str] = set()
    for _c in all_classes:
        _name = _c.get("project_uid")
        if _name and _name not in _seen:
            _seen.add(_name)
            label_items.append({"value": _name, "name": _name})

    week_grid = None
    if view == "calendar":
        grid_classes = all_classes
        if label:
            grid_classes = [c for c in all_classes if c.get("project_uid") == label]
        week_grid = _build_week_grid(grid_classes)

    classes = all_classes
    if label:
        classes = [c for c in classes if c.get("project_uid") == label]
    if q:
        needle = q.lower()
        classes = [
            c
            for c in classes
            if needle in (c.get("name") or "").lower()
            or needle in (c.get("acronym") or "").lower()
            or needle in (c.get("professor") or "").lower()
            or needle in (c.get("room") or "").lower()
        ]
    key_fn = _SORT_KEYS.get(sort, _SORT_KEYS["day"])
    classes = sorted(classes, key=key_fn, reverse=(dir == "desc"))

    classes_by_day = [(d, [c for c in classes if c["day"] == d]) for d in schedule_logic.DAYS]
    classes_by_day = [(d, day_classes) for d, day_classes in classes_by_day if day_classes]

    return templates.TemplateResponse(
        "schedule_classes.html",
        {
            "request": request,
            "active_tab": "schedule",
            "sub_tab": "classes",
            "classes": classes,
            "classes_by_day": classes_by_day,
            "view": view,
            "week_grid": week_grid,
            "conflicts": conflicts,
            "used_credits": used_credits,
            "needed_credits": needed,
            "px_per_hour": grid_layout.PX_PER_HOUR,
            "q": q or "",
            "label": label or "",
            "schedule_label_items": label_items,
            "sort": sort,
            "dir": dir,
            "parities": PARITIES,
            "days": schedule_logic.DAYS,
            "holidays": db.list_holidays(conn),
            "holiday_calendar_names": db.list_holiday_calendar_names(conn),
            "settings": settings,
        },
    )


def _build_week_grid(classes: list[dict]) -> dict:
    """Pixel-positioned layout for the weekly grid template -- reuses
    grid_layout.py by faking a `start_at`/`end_at` on an arbitrary shared
    date (grid_layout only ever reads the HH:MM substring)."""
    by_day: dict[str, list[dict]] = {d: [] for d in schedule_logic.DAYS}
    for cls in classes:
        if cls["day"] not in by_day:
            continue
        fake = dict(cls)
        fake["start_at"] = f"2000-01-03T{cls['start_time']}:00"
        fake["end_at"] = f"2000-01-03T{cls['end_time']}:00"
        by_day[cls["day"]].append(fake)
    return {
        "days": schedule_logic.DAYS,
        "hours": list(range(grid_layout.GRID_HOURS)),
        "px_per_hour": grid_layout.PX_PER_HOUR,
        "by_day": {d: grid_layout.layout_day(events) for d, events in by_day.items()},
    }


@router.get("/classes/new")
def new_class_form(
    request: Request,
    day: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    conn=Depends(get_db),
):
    prefill = None
    if day:
        prefill = {"day": day, "start_time": start_time or "08:00", "end_time": end_time or "10:00"}
    return templates.TemplateResponse(
        "schedule_class_form.html",
        {
            "request": request,
            "active_tab": "schedule",
            "sub_tab": "classes",
            "cls": None,
            "prefill": prefill,
            "parities": PARITIES,
            "contacts": db.list_contacts(conn),
            "projects": [l for l in db.list_labels(conn) if not l.get("generate_space")],
            "class_types": db.list_course_types(conn),
        },
    )


@router.post("/classes")
def create_class(
    day: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    name: str = Form(...),
    acronym: str = Form(""),
    class_type_select: str = Form(""),
    class_type_other: str = Form(""),
    professor_select: str = Form(""),
    professor_new: str = Form(""),
    room: str = Form(""),
    credits: str = Form("0"),
    parity: str = Form("all"),
    enrolled: str = Form(""),
    project_uid: str = Form(""),
    conn=Depends(get_db),
):
    professor_contact_uid = _resolve_professor_field(professor_select, professor_new, conn)
    class_type = _resolve_class_type_field(class_type_select, class_type_other)

    space_label = None
    if project_uid.strip():
        course_label = project_uid.strip()
    else:
        course_label, space_label = _auto_provision_course_label(conn, name)
    db.upsert_label_config(
        conn,
        dict(_course_field_dict(acronym, class_type, credits, professor_contact_uid), name=course_label),
    )

    uid = str(uuid.uuid4())
    _regenerate_event(uid, day, start_time, end_time, parity, name, room, bool(enrolled), conn)
    schedule_label = db.get_schedule_settings(conn).get("schedule_label") or "Schedule"
    tags = [schedule_label, course_label]
    if space_label:
        tags.append(space_label)
    db.set_object_labels(conn, "event", uid, tags)
    return RedirectResponse(url="/schedule", status_code=303)


@router.get("/classes/{uid}/edit")
def edit_class_form(uid: str, request: Request, conn=Depends(get_db)):
    event = db.get_event(conn, uid)
    cls = _class_row(conn, event) if event else None
    return templates.TemplateResponse(
        "schedule_class_form.html",
        {
            "request": request,
            "active_tab": "schedule",
            "sub_tab": "classes",
            "cls": cls,
            "parities": PARITIES,
            "contacts": db.list_contacts(conn),
            "projects": [l for l in db.list_labels(conn) if not l.get("generate_space")],
            "class_types": db.list_course_types(conn),
        },
    )


@router.post("/classes/{uid}")
def update_class(
    uid: str,
    day: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    name: str = Form(...),
    acronym: str = Form(""),
    class_type_select: str = Form(""),
    class_type_other: str = Form(""),
    professor_select: str = Form(""),
    professor_new: str = Form(""),
    room: str = Form(""),
    credits: str = Form("0"),
    parity: str = Form("all"),
    enrolled: str = Form(""),
    project_uid: str = Form(""),
    conn=Depends(get_db),
):
    event = db.get_event(conn, uid)
    if event is None:
        return RedirectResponse(url="/schedule", status_code=303)
    professor_contact_uid = _resolve_professor_field(professor_select, professor_new, conn)
    class_type = _resolve_class_type_field(class_type_select, class_type_other)

    if project_uid.strip():
        course_label = project_uid.strip()
    else:
        course_label, _space_label = _auto_provision_course_label(conn, name)
    db.upsert_label_config(
        conn,
        dict(_course_field_dict(acronym, class_type, credits, professor_contact_uid), name=course_label),
    )

    _regenerate_event(uid, day, start_time, end_time, parity, name, room, bool(enrolled), conn)
    schedule_label = db.get_schedule_settings(conn).get("schedule_label") or "Schedule"
    # Final tag set: the Schedule system label, the (possibly changed)
    # course label, and whichever Space label(s) the event already carried
    # (generate_space=1 labels stay untouched -- same "swap the project
    # label, leave Space labels alone" rule set_object_project_label_
    # uniform uses elsewhere). set_object_labels replaces the whole tag set
    # on the event, so every one that should survive has to be named here.
    space_tags = [
        t for t in (event.get("tags") or [])
        if t != schedule_label and (db.get_label_config(conn, t) or {}).get("generate_space")
    ]
    db.set_object_labels(conn, "event", uid, [schedule_label, course_label, *space_tags])
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/classes/{uid}/reposition")
async def reposition_class(uid: str, request: Request, conn=Depends(get_db)):
    """JSON endpoint for the Schedule grid's drag-to-move
    (static/schedule_grid.js) -- same idea as /events/{uid}/reschedule, but
    keyed by day/start_time/end_time instead of start_at/end_at, since a
    class meeting's day/parity determine its recurrence anchor, not a
    literal datetime drag."""
    payload = await request.json()
    event = db.get_event(conn, uid)
    if event is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    row = _class_row(conn, event)
    _regenerate_event(
        uid, payload["day"], payload["start_time"], payload["end_time"],
        row["parity"], row["name"], row["room"], row["enrolled"], conn,
    )
    return JSONResponse({"ok": True, "day": payload["day"], "start_time": payload["start_time"], "end_time": payload["end_time"]})


_UPDATABLE_FIELDS = {"parity"}


@router.post("/classes/{uid}/update-field")
async def update_class_field(uid: str, request: Request, conn=Depends(get_db)):
    """Single-field inline edit for the Table view's Parity pill -- mirrors
    routers/tasks.py's identical endpoint."""
    payload = await request.json()
    field = payload.get("field")
    value = payload.get("value")
    if field not in _UPDATABLE_FIELDS:
        return JSONResponse({"error": f"field '{field}' is not inline-editable"}, status_code=400)
    event = db.get_event(conn, uid)
    if event is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    row = _class_row(conn, event)
    _regenerate_event(
        uid, row["day"], row["start_time"], row["end_time"],
        value, row["name"], row["room"], row["enrolled"], conn,
    )
    return JSONResponse({"ok": True})


@router.post("/classes/{uid}/toggle-enrolled")
def toggle_enrolled(uid: str, conn=Depends(get_db)):
    """Plain-form boolean toggle for the Table view's Enrolled icon --
    "enrolled" maps to the event's own active/archived status."""
    event = db.get_event(conn, uid)
    if event is not None:
        row = _class_row(conn, event)
        _regenerate_event(
            uid, row["day"], row["start_time"], row["end_time"],
            row["parity"], row["name"], row["room"], not row["enrolled"], conn,
        )
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/classes/{uid}/delete")
def delete_class(uid: str, conn=Depends(get_db)):
    db.delete_event(conn, uid)
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/holidays")
def create_holiday(
    calendar_name: str = Form("Default"),
    label: str = Form(""),
    date_from: str = Form(...),
    date_to: str = Form(...),
    conn=Depends(get_db),
):
    # 1.6: no more _regenerate_all(conn) call here -- a class event only
    # ever stores *which* holiday calendar it references
    # (holiday_calendar), never the dates themselves; those are looked up
    # fresh on every read (recurrence_expand.expand_events), so adding a
    # holiday takes effect immediately without touching any event row.
    db.upsert_holiday(
        conn,
        {
            "uid": str(uuid.uuid4()), "calendar_name": calendar_name.strip() or "Default",
            "label": label, "date_from": date_from, "date_to": date_to,
        },
    )
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/holidays/{uid}/delete")
def delete_holiday(uid: str, conn=Depends(get_db)):
    db.delete_holiday(conn, uid)
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/settings")
def save_settings(
    semester_start: str = Form(""),
    semester_end: str = Form(""),
    credits_needed: str = Form(""),
    reminder_minutes: str = Form("15"),
    schedule_label: str = Form("Schedule"),
    holiday_calendar: str = Form("Default"),
    conn=Depends(get_db),
):
    old_label = db.get_schedule_settings(conn).get("schedule_label") or "Schedule"
    new_label = schedule_label.strip() or "Schedule"
    db.save_schedule_settings(
        conn,
        {
            "semester_start": semester_start or None,
            "semester_end": semester_end or None,
            "credits_needed": float(credits_needed) if credits_needed else None,
            "reminder_minutes": int(reminder_minutes) if reminder_minutes else 15,
            "schedule_label": new_label,
            "holiday_calendar": holiday_calendar.strip() or "Default",
        },
    )
    # 1.6: renaming the event label used to require a bespoke rewrite of
    # every mirrored event's tags list (the old model wrote a single
    # literal tag). Now the label lives in object_labels like any other --
    # find every event still tagged with the *old* name and swap it before
    # regenerating (which reads the *new* name to find "is this a class"
    # going forward).
    if new_label != old_label:
        for uid in db.list_object_ids_for_label(conn, "event", old_label):
            db.remove_object_label(conn, "event", uid, old_label)
            db.add_object_label(conn, "event", uid, new_label)
    _regenerate_all(conn)
    return RedirectResponse(url="/schedule", status_code=303)
