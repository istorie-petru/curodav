from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db, grid_layout, schedule as schedule_logic
from ..deps import get_bridge, get_db, templates
from .calendars import COLORS, _slugify

router = APIRouter(prefix="/schedule", tags=["schedule"])

PARITIES = ["all", "odd", "even"]

# Table view: sortable columns + a search box + inline-editable pills for
# Day/Parity/Time/Enrolled, mirroring the Tasks table (tasks_list.html,
# routers/tasks.py) feature-for-feature wherever a class actually has an
# equivalent field. Deliberately NOT ported: checklist/subtasks/Kanban --
# none of those map onto what a class *is* (there's no per-class
# checklist concept, and "status" for a class is really just enrolled/not,
# already covered by the Enrolled toggle).
_SORT_KEYS = {
    "day": lambda c: (schedule_logic.DAYS.index(c["day"]) if c["day"] in schedule_logic.DAYS else 99, c["start_time"]),
    "time": lambda c: c["start_time"],
    "name": lambda c: (c.get("name") or "").lower(),
    "professor": lambda c: (c.get("professor") or "").lower(),
    "room": lambda c: (c.get("room") or "").lower(),
    "credits": lambda c: c.get("credits") or 0,
    "parity": lambda c: c.get("parity") or "",
}


def _class_next_occurrence(cls: dict, settings: dict) -> str | None:
    """Human-readable countdown to the next occurrence of `cls` -- "today",
    "tomorrow", "in N days", or None if the semester isn't configured or
    this class can't be scheduled (no start, no valid first occurrence, or
    the semester has already ended).

    Uses `schedule_logic.first_occurrence` + `schedule_logic.generate_occurrences`
    from schedule.py's existing logic to find the next occurrence on or
    after today, then formats the delta, same "today / tomorrow / in N days"
    idiom dashboard.html's agenda widget uses for event countdowns."""
    semester_start = settings.get("semester_start")
    semester_end = settings.get("semester_end")
    if not semester_start or not semester_end:
        return None
    if cls["day"] not in schedule_logic.DAYS:
        return None
    try:
        start_date = date.fromisoformat(semester_start)
        end_date = date.fromisoformat(semester_end)
        today = date.today()
        if today > end_date:
            return None
        anchor = schedule_logic.first_occurrence(start_date, cls["day"], cls["parity"])
        if anchor > end_date:
            return None
        # Find the first occurrence >= today (holidays intentionally ignored
        # here -- we're computing "when does this class next happen in the
        # abstract timetable," not "is this specific occurrence cancelled by
        # a holiday," which would require a full holiday-exclusion pass and
        # would make a class that happens to fall in a holiday week show an
        # awkward "the next non-cancelled occurrence" date instead).
        occurrences = schedule_logic.generate_occurrences(anchor, end_date, cls["parity"])
        future = [d for d in occurrences if d >= today]
        if not future:
            return None
        delta = (future[0] - today).days
        if delta == 0:
            return "today"
        if delta == 1:
            return "tomorrow"
        return f"in {delta} days"
    except (ValueError, IndexError):
        return None


def _infer_schedule_group(conn) -> str | None:
    """Find the project_group that already has schedule-class projects in
    it, if any.  When a user has a "University" Space with existing
    classes, every subsequent class's auto-provisioned project should land
    in that same Space rather than floating ungrouped."""
    classes = db.list_schedule_classes(conn)
    projects = {p["uid"]: p for p in db.list_projects(conn)}
    for cls in classes:
        p = projects.get(cls.get("project_uid") or "")
        if p and p.get("group_uid"):
            return p["group_uid"]
    return None


def _auto_provision_university_project(conn, cls: dict) -> str:
    """Creates a project named after the class and a pre-built Grades
    database linked to it, then links the class to the new project.
    Returns the new project's uid.

    Called from create_class only when the submitted form didn't already
    name an existing project to link to -- the 'auto-create a project for
    every new class' behaviour described in §5 of the University module
    plan. Idempotent in the sense that it only runs when project_uid is
    absent from the form submission; re-creating the class via the edit
    form (which always has a project dropdown) never hits this path."""
    now = datetime.now(timezone.utc).isoformat()
    project_uid = str(uuid.uuid4())
    # Try to scope the new project under the same Space (project_group)
    # other schedule-class projects already live in — if the user has a
    # "University" Space with existing classes in it, the new class's
    # project lands there too instead of floating ungrouped. Falls back
    # to None (ungrouped) when no schedule classes have been grouped yet.
    group_uid = _infer_schedule_group(conn)
    db.upsert_project(
        conn,
        {
            "uid": project_uid,
            "name": cls["name"],
            "description": "",
            "color": "blue",
            "icon": "book-open",
            "group_uid": group_uid,
            "created_at": now,
            "updated_at": now,
        },
    )
    db.set_schedule_class_project(conn, cls["uid"], project_uid)

    # Pre-built Grades database linked to this project.
    db_uid = str(uuid.uuid4())
    db.upsert_database(
        conn,
        {
            "uid": db_uid,
            "name": f"{cls['name']} Grades",
            "description": "Auto-created grade tracker for this course.",
            "color": "blue",
            "project_uid": project_uid,
            "created_at": now,
            "updated_at": now,
        },
    )

    # Columns in display order: Assessment, Grade (with WEIGHTAVG summary),
    # Weight, Date, Source. The summary formula uses lowercase column-name
    # references ("grade", "weight") which resolve case-insensitively via
    # databases.py's _rows_by_column_name.
    columns = [
        {"name": "Assessment", "type": "text",   "summary_formula": None,                      "position": 0},
        {"name": "Grade",      "type": "number", "summary_formula": "WEIGHTAVG(grade, weight)", "position": 1},
        {"name": "Weight",     "type": "number", "summary_formula": None,                      "position": 2},
        {"name": "Date",       "type": "date",   "summary_formula": None,                      "position": 3},
        {"name": "Source",     "type": "text",   "summary_formula": None,                      "position": 4},
    ]
    for col in columns:
        db.upsert_database_column(
            conn,
            {
                "uid": str(uuid.uuid4()),
                "database_uid": db_uid,
                "name": col["name"],
                "type": col["type"],
                "formula": None,
                "summary_formula": col["summary_formula"],
                "options": [],
                "position": col["position"],
                "created_at": now,
            },
        )

    return project_uid


def _target_calendar(settings: dict) -> str:
    """Which real calendar Schedule's mirrored class events currently live
    in -- defaults to the app's default calendar until the user picks a
    destination via the Export flow below."""
    return settings.get("target_calendar_uid") or db.DEFAULT_CALENDAR_UID


def _regenerate_class_event(cls: dict, settings: dict, holidays: list[dict], bridge, conn) -> dict:
    """(Re)build the mirrored VEVENT for one class and push it through the
    normal event bridge. Returns the (possibly updated) class dict --
    callers must persist it via db.upsert_schedule_class if `event_uid`
    was just assigned for the first time."""
    if not cls.get("event_uid"):
        cls["event_uid"] = str(uuid.uuid4())
    event_row = schedule_logic.class_to_event_row(cls, settings, holidays)
    if event_row is None:
        # Not schedulable yet (no semester dates configured) -- clean up
        # any stale mirrored event from a previous configuration.
        bridge.delete_event(cls["event_uid"], _target_calendar(settings))
        db.delete_event(conn, cls["event_uid"])
        return cls
    saved = bridge.save_event_row(event_row)
    db.upsert_event(conn, saved)
    return cls


def _regenerate_all(bridge, conn) -> None:
    settings = db.get_schedule_settings(conn)
    holidays = db.list_holidays(conn)
    for cls in db.list_schedule_classes(conn):
        cls = _regenerate_class_event(cls, settings, holidays, bridge, conn)
        db.upsert_schedule_class(conn, cls)


def _tags_or_none(value: str) -> str | None:
    return value.strip() or None


def _resolve_new_professor_name(text: str, bridge, conn) -> tuple[str | None, str | None]:
    """Turns a typed "+ Add new professor..." name into (display_name,
    contacts.uid). Still checks for an existing exact-name match first
    (`db.find_contact_by_name`) as a dedupe safety net -- the Professor
    field's dropdown (see `_resolve_professor_field` below) is what makes
    "pick an existing contact" and "type a new one" two unambiguous paths
    now, but someone can still type a name that happens to match a contact
    without noticing it was already in the dropdown, and silently creating
    a duplicate in that case would be worse than just linking to the one
    that already exists.

    If no match: creates a new contact with just that name -- everything
    else blank -- and links to it. Goes through `bridge.save_contact_row`
    (the same path routers/contacts.py's create_contact uses), not a
    direct db.upsert_contact, because contacts are CardDAV-backed here
    (see caldav_bridge.py's module docstring: "Radicale is the source of
    truth") -- a contact created only in the local SQLite cache would
    vanish on the next full_refresh sync, since that resync treats
    Radicale as authoritative and deletes any cached row it doesn't find
    there."""
    text = text.strip()
    if not text:
        return None, None
    existing = db.find_contact_by_name(conn, text)
    if existing:
        return existing["full_name"], existing["uid"]
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "uid": str(uuid.uuid4()),
        "full_name": text,
        "addressbook_path": db.DEFAULT_ADDRESSBOOK_UID,
        "created_at": now,
        "updated_at": now,
    }
    saved = bridge.save_contact_row(row)
    db.upsert_contact(conn, saved)
    return text, saved["uid"]


def _resolve_professor_field(professor_select: str, professor_new: str, bridge, conn) -> tuple[str | None, str | None]:
    """The Professor field is a <select> of contacts by uid plus a
    "+ Add new professor..." sentinel (schedule_class_form.html) --
    unambiguous compared to the free-text-with-suggestions field this
    replaced, which blurred "picked an existing person" and "typed
    something new" into the same input. Picking a real contact links
    straight to it by uid, no name-matching involved at all; only the
    "add new" path goes through name-based dedupe/creation
    (`_resolve_new_professor_name`)."""
    if professor_select == "__new__":
        return _resolve_new_professor_name(professor_new, bridge, conn)
    if professor_select:
        contact = db.get_contact(conn, professor_select)
        if contact:
            return contact["full_name"], contact["uid"]
    return None, None


@router.get("")
def classes_view(
    request: Request,
    view: str = "table",
    q: str | None = None,
    sort: str = "day",
    dir: str = "asc",
    conn=Depends(get_db),
):
    all_classes = db.list_schedule_classes(conn)
    settings = db.get_schedule_settings(conn)
    # Conflicts/credits/the calendar-view grid always reflect *every*
    # class, never the search box -- a conflict warning for a class that
    # doesn't currently match the search text shouldn't disappear just
    # because the table's filtered to something else.
    conflicts = schedule_logic.compute_conflicts(all_classes)
    used_credits = schedule_logic.credits_summary(all_classes)
    needed = settings.get("credits_needed")

    week_grid = None
    if view == "calendar":
        week_grid = _build_week_grid(all_classes)

    classes = all_classes
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

    # §5 countdown: annotate each class dict with a human-readable
    # "next occurrence" label ("today", "tomorrow", "in N days") so the
    # template can render it without any logic of its own. Computed here,
    # not in the template -- templates render, routers compute.
    for c in classes:
        c["next_occurrence"] = _class_next_occurrence(c, settings)

    # Grouped by day for the Table view (2026-08-01, "a lot of classes,
    # easily viewed") -- one flat sortable list stopped scaling once a
    # full course load's worth of blocks were all in it; day-of-week
    # section headers turn "scan a long list for what's on Wednesday"
    # into "look at the Wednesday section." Whatever `sort` is currently
    # active still governs the order *within* each day -- grouping and
    # sorting are independent, sorting by "day" itself just becomes
    # redundant with the grouping (harmless, not specially handled).
    # Days with nothing in them are omitted outright rather than shown
    # empty, same as any other empty-state-avoidance in this app.
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
            "sort": sort,
            "dir": dir,
            "parities": PARITIES,
            "days": schedule_logic.DAYS,
            # 2026-08-01: Holidays merged into this same view (a
            # collapsible section below the Blocks table/grid) instead of
            # its own page + nav tab -- see schedule_classes.html. The
            # standalone GET /schedule/holidays route is gone; the two
            # POST endpoints below still exist (the merged section's forms
            # still need somewhere to submit to) and now redirect back
            # here instead.
            "holidays": db.list_holidays(conn),
        },
    )


def _build_week_grid(classes: list[dict]) -> dict:
    """Pixel-positioned layout for the weekly grid template -- reuses
    grid_layout.py (the same overlap-packing algorithm Calendar's Week/Day
    views use) by faking a `start_at`/`end_at` on an arbitrary shared date
    (grid_layout only ever reads the HH:MM substring, so the date itself is
    irrelevant here -- Schedule classes have a weekday name, not a real
    date). Lets the weekly grid support the same hover-preview/click-drag
    creation and drag-to-move JS as the main Calendar grid, instead of the
    static hour-bucket table this used to be."""
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
            "projects": db.list_projects(conn),
        },
    )


@router.post("/classes")
def create_class(
    day: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    name: str = Form(...),
    acronym: str = Form(""),
    class_type: str = Form(""),
    professor_select: str = Form(""),
    professor_new: str = Form(""),
    room: str = Form(""),
    credits: str = Form("0"),
    parity: str = Form("all"),
    enrolled: str = Form(""),
    project_uid: str = Form(""),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    now = datetime.now(timezone.utc).isoformat()
    professor_name, professor_contact_uid = _resolve_professor_field(professor_select, professor_new, bridge, conn)
    cls = {
        "uid": str(uuid.uuid4()),
        "day": day,
        "start_time": start_time,
        "end_time": end_time,
        "name": name,
        "acronym": _tags_or_none(acronym),
        "class_type": _tags_or_none(class_type),
        "professor": professor_name,
        "professor_contact_uid": professor_contact_uid,
        "room": _tags_or_none(room),
        "credits": float(credits) if credits else 0.0,
        "parity": parity,
        "enrolled": bool(enrolled),
        "event_uid": None,
        "created_at": now,
        "updated_at": now,
    }
    settings = db.get_schedule_settings(conn)
    holidays = db.list_holidays(conn)
    cls = _regenerate_class_event(cls, settings, holidays, bridge, conn)
    db.upsert_schedule_class(conn, cls)
    if project_uid:
        # A course "becomes a project" per the feature request via this
        # dropdown -- upsert_schedule_class deliberately never lists
        # project_uid in its own column set (see set_schedule_class_project's
        # docstring in db.py), so it's always applied as a separate step.
        db.set_schedule_class_project(conn, cls["uid"], project_uid)
    else:
        # §5 University module: auto-create a project + Grades database for
        # every new class that wasn't explicitly linked to an existing one.
        # The edit form always has the project dropdown pre-filled, so this
        # path only runs once -- on initial creation. See
        # _auto_provision_university_project for the full rationale.
        _auto_provision_university_project(conn, cls)
    return RedirectResponse(url="/schedule", status_code=303)


@router.get("/classes/{uid}/edit")
def edit_class_form(uid: str, request: Request, conn=Depends(get_db)):
    cls = db.get_schedule_class(conn, uid)
    return templates.TemplateResponse(
        "schedule_class_form.html",
        {
            "request": request,
            "active_tab": "schedule",
            "sub_tab": "classes",
            "cls": cls,
            "parities": PARITIES,
            "contacts": db.list_contacts(conn),
            "projects": db.list_projects(conn),
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
    class_type: str = Form(""),
    professor_select: str = Form(""),
    professor_new: str = Form(""),
    room: str = Form(""),
    credits: str = Form("0"),
    parity: str = Form("all"),
    enrolled: str = Form(""),
    project_uid: str = Form(""),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    existing = db.get_schedule_class(conn, uid) or {}
    professor_name, professor_contact_uid = _resolve_professor_field(professor_select, professor_new, bridge, conn)
    cls = dict(existing)
    cls.update(
        {
            "uid": uid,
            "day": day,
            "start_time": start_time,
            "end_time": end_time,
            "name": name,
            "acronym": _tags_or_none(acronym),
            "class_type": _tags_or_none(class_type),
            "professor": professor_name,
            "professor_contact_uid": professor_contact_uid,
            "room": _tags_or_none(room),
            "credits": float(credits) if credits else 0.0,
            "parity": parity,
            "enrolled": bool(enrolled),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    settings = db.get_schedule_settings(conn)
    holidays = db.list_holidays(conn)
    cls = _regenerate_class_event(cls, settings, holidays, bridge, conn)
    db.upsert_schedule_class(conn, cls)
    # See create_class above for why this is a separate explicit call.
    db.set_schedule_class_project(conn, uid, project_uid or None)
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/classes/{uid}/reposition")
async def reposition_class(
    uid: str, request: Request, bridge=Depends(get_bridge), conn=Depends(get_db)
):
    """JSON endpoint for the Schedule grid's drag-to-move (static/schedule_grid.js)
    -- same idea as /events/{uid}/reschedule, but for a schedule_classes row
    (day/start_time/end_time instead of start_at/end_at), which then
    regenerates the mirrored VEVENT through the normal path."""
    payload = await request.json()
    cls = db.get_schedule_class(conn, uid)
    if cls is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    cls["day"] = payload["day"]
    cls["start_time"] = payload["start_time"]
    cls["end_time"] = payload["end_time"]
    cls["updated_at"] = datetime.now(timezone.utc).isoformat()
    settings = db.get_schedule_settings(conn)
    holidays = db.list_holidays(conn)
    cls = _regenerate_class_event(cls, settings, holidays, bridge, conn)
    db.upsert_schedule_class(conn, cls)
    return JSONResponse({"ok": True, "day": cls["day"], "start_time": cls["start_time"], "end_time": cls["end_time"]})


_UPDATABLE_FIELDS = {"parity"}


@router.post("/classes/{uid}/update-field")
async def update_class_field(uid: str, request: Request, bridge=Depends(get_bridge), conn=Depends(get_db)):
    """Single-field inline edit for the Table view's Parity pill --
    mirrors routers/tasks.py's identical endpoint. Day/Time have their own
    inline editors too, but those reuse `/reposition` above (the same JSON
    endpoint the calendar-view drag-to-move already posts to) rather than
    duplicating that field set here -- Day/Time are naturally a matched
    trio there (moving a class already means "day + start + end"), so
    `/reposition` already is the single-field... well, single-*concept*
    update for them. Enrolled has its own plain-form toggle below
    (`/toggle-enrolled`) rather than living here, matching how Tasks'
    "mark done" is a plain form too, not a JSON call -- a boolean flip
    doesn't need a dropdown/JS round-trip to work with no-JS as a
    fallback."""
    payload = await request.json()
    field = payload.get("field")
    value = payload.get("value")
    if field not in _UPDATABLE_FIELDS:
        return JSONResponse({"error": f"field '{field}' is not inline-editable"}, status_code=400)
    cls = db.get_schedule_class(conn, uid)
    if cls is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    cls["parity"] = value
    cls["updated_at"] = datetime.now(timezone.utc).isoformat()
    settings = db.get_schedule_settings(conn)
    holidays = db.list_holidays(conn)
    cls = _regenerate_class_event(cls, settings, holidays, bridge, conn)
    db.upsert_schedule_class(conn, cls)
    return JSONResponse({"ok": True})


@router.post("/classes/{uid}/toggle-enrolled")
def toggle_enrolled(uid: str, bridge=Depends(get_bridge), conn=Depends(get_db)):
    """Plain-form boolean toggle for the Table view's Enrolled icon --
    same "click the icon, it's a real form submit" pattern as Tasks'
    Mark-done column (tasks_list.html), not a dropdown/JS-only control."""
    cls = db.get_schedule_class(conn, uid)
    if cls:
        cls["enrolled"] = not cls.get("enrolled", True)
        cls["updated_at"] = datetime.now(timezone.utc).isoformat()
        settings = db.get_schedule_settings(conn)
        holidays = db.list_holidays(conn)
        cls = _regenerate_class_event(cls, settings, holidays, bridge, conn)
        db.upsert_schedule_class(conn, cls)
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/classes/{uid}/delete")
def delete_class(uid: str, bridge=Depends(get_bridge), conn=Depends(get_db)):
    cls = db.get_schedule_class(conn, uid)
    if cls and cls.get("event_uid"):
        settings = db.get_schedule_settings(conn)
        bridge.delete_event(cls["event_uid"], _target_calendar(settings))
        db.delete_event(conn, cls["event_uid"])
    db.delete_schedule_class(conn, uid)
    return RedirectResponse(url="/schedule", status_code=303)


@router.get("/export")
def export_form(request: Request, conn=Depends(get_db)):
    """Mirrors the reference desktop app's "export the term schedule to a
    calendar" action: pick an existing calendar to drop every class into,
    or spin up a fresh one just for the schedule. Every class is already
    continuously mirrored as a VEVENT (see class_to_event_row) -- this
    modal just lets the user choose/redirect *where* that mirror lives,
    instead of it being silently hardcoded to the app's default
    calendar."""
    settings = db.get_schedule_settings(conn)
    calendars = db.list_calendars(conn)
    current_uid = _target_calendar(settings)
    return templates.TemplateResponse(
        "schedule_export.html",
        {
            "request": request,
            "active_tab": "schedule",
            "calendars": calendars,
            "current_uid": current_uid,
            "colors": COLORS,
        },
    )


@router.post("/export")
def export_submit(
    mode: str = Form(...),
    calendar_uid: str = Form(""),
    new_name: str = Form(""),
    new_color: str = Form("blue"),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    settings = db.get_schedule_settings(conn)
    old_target = _target_calendar(settings)

    if mode == "new":
        existing_uids = {c["uid"] for c in db.list_calendars(conn)}
        target = _slugify(new_name or "Schedule", existing_uids)
        bridge.ensure_calendar(target)
        db.upsert_calendar(
            conn,
            {
                "uid": target,
                "name": new_name or "Schedule",
                "color": new_color,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    else:
        target = calendar_uid or old_target

    if target != old_target:
        # The mirrored events already living in the old calendar are now
        # orphaned -- class_to_event_row is about to regenerate them fresh
        # at `target`, so delete the stale copies rather than leaving
        # duplicates behind in a calendar the user just moved away from.
        for cls in db.list_schedule_classes(conn):
            if cls.get("event_uid"):
                bridge.delete_event(cls["event_uid"], old_target)
                db.delete_event(conn, cls["event_uid"])

    db.set_schedule_target_calendar(conn, target)
    _regenerate_all(bridge, conn)
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/holidays")
def create_holiday(
    label: str = Form(""),
    date_from: str = Form(...),
    date_to: str = Form(...),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    db.upsert_holiday(
        conn, {"uid": str(uuid.uuid4()), "label": label, "date_from": date_from, "date_to": date_to}
    )
    _regenerate_all(bridge, conn)
    # 2026-08-01: Holidays merged into the main Blocks view (schedule_classes.html)
    # -- no more standalone /schedule/holidays page to redirect back to.
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/holidays/{uid}/delete")
def delete_holiday(uid: str, bridge=Depends(get_bridge), conn=Depends(get_db)):
    db.delete_holiday(conn, uid)
    _regenerate_all(bridge, conn)
    return RedirectResponse(url="/schedule", status_code=303)


@router.get("/settings")
def settings_view(request: Request, conn=Depends(get_db)):
    settings = db.get_schedule_settings(conn)
    return templates.TemplateResponse(
        "schedule_settings.html",
        {
            "request": request,
            # Deliberately "schedule_settings", not "schedule" -- this page
            # is reached via the Settings gear now (_settings_nav.html),
            # not Calendar's "Schedule" modal button, so it shouldn't
            # highlight the Calendar tab in base.html's topbar the way the
            # modal's own pages still do. See base.html's Settings-gear
            # active check.
            "active_tab": "schedule_settings",
            "settings_tab": "schedule",
            "settings": settings,
        },
    )


@router.post("/settings")
def save_settings(
    semester_start: str = Form(""),
    semester_end: str = Form(""),
    credits_needed: str = Form(""),
    reminder_minutes: str = Form("15"),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    db.save_schedule_settings(
        conn,
        {
            "semester_start": semester_start or None,
            "semester_end": semester_end or None,
            "credits_needed": float(credits_needed) if credits_needed else None,
            "reminder_minutes": int(reminder_minutes) if reminder_minutes else 15,
        },
    )
    _regenerate_all(bridge, conn)
    return RedirectResponse(url="/schedule/settings", status_code=303)
