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
    """Find the Space label (generate_space=1) that other schedule
    classes already carry, if any -- when a user has a "University" Space
    with existing classes, every subsequent class's auto-applied label
    should carry that same Space label too rather than floating without
    one. Phase 2 (label-space rework): a class's project link and its
    Space membership are both just object_labels rows now, not a
    `projects.group_uid` FK to walk."""
    for cls in db.list_schedule_classes(conn):
        for name in cls.get("tags") or []:
            cfg = db.get_label_config(conn, name)
            if cfg and cfg.get("generate_space"):
                return name
    return None


def _auto_provision_university_project(conn, cls: dict) -> str:
    """Applies a label named after the class directly to it (the "course
    becomes a project" behavior), and -- if other schedule classes already
    carry a Space label (e.g. "University") -- applies that same Space
    label too, same "apply the University label as well, if that's how it
    worked before" simplification the label-space rework calls for here.
    Returns the class's own label name.

    2026-08-07: this used to also seed a pre-built Grades database (linked
    to the same course label, with Assessment/Grade/Weight/Date/Source
    columns and a WEIGHTAVG summary formula) -- removed along with the
    rest of the Databases/Grades feature. Creating a class now only
    applies the course label and, when applicable, the Space label; it no
    longer provisions anything database-shaped.

    2026-08-08: this used to also default both labels' `enabled_modules`
    the first time each was set up (Phase 4's "Sections" gating) -- gone
    along with that whole mechanism, see routers/labels.py's own removal
    note. There's nothing left to default here.

    Called from create_class only when the submitted form didn't already
    name an existing label to apply -- re-creating the class via the edit
    form (which always has a project dropdown) never hits this path."""
    now = datetime.now(timezone.utc).isoformat()
    label_name = cls["name"]
    space_label = _infer_schedule_group(conn)
    db.upsert_label_config(
        conn,
        {
            "name": label_name,
            "color": "blue",
            "icon": "book-open",
            "parent_name": space_label,
            "created_at": now,
        },
    )
    db.set_schedule_class_project(conn, cls["uid"], label_name)
    if space_label:
        # Direct assignment only (§2/§5) -- a Space page aggregates by
        # direct object_labels membership, not transitively through
        # parent_name, so the class needs the Space's own label applied
        # to it too, not just a course label whose *parent* is the Space.
        db.add_object_label(conn, "schedule_class", cls["uid"], space_label)

    return label_name


def _regenerate_class_event(cls: dict, settings: dict, holidays: list[dict], conn) -> dict:
    """(Re)build the mirrored VEVENT for one class and write it straight
    into the universal `events` pool (Phase 1, label-space rework -- see
    db.py's Phase 1 comments; no more Radicale/bridge call, no more
    per-calendar targeting -- there's only one events pool now). Returns
    the (possibly updated) class dict -- callers must persist it via
    db.upsert_schedule_class if `event_uid` was just assigned for the
    first time."""
    if not cls.get("event_uid"):
        cls["event_uid"] = str(uuid.uuid4())
    event_row = schedule_logic.class_to_event_row(cls, settings, holidays)
    if event_row is None:
        # Not schedulable yet (no semester dates configured) -- clean up
        # any stale mirrored event from a previous configuration.
        db.delete_event(conn, cls["event_uid"])
        return cls
    db.upsert_event(conn, event_row)
    return cls


def _regenerate_all(conn) -> None:
    settings = db.get_schedule_settings(conn)
    holidays = db.list_holidays(conn)
    for cls in db.list_schedule_classes(conn):
        cls = _regenerate_class_event(cls, settings, holidays, conn)
        db.upsert_schedule_class(conn, cls)


def _tags_or_none(value: str) -> str | None:
    return value.strip() or None


def _resolve_new_professor_name(text: str, conn) -> tuple[str | None, str | None]:
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
    else blank -- and links to it. Plain SQL write (Phase 1, label-space
    rework) -- contacts are no longer CardDAV-backed, see db.py's Phase 1
    comments."""
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
        "created_at": now,
        "updated_at": now,
    }
    db.upsert_contact(conn, row)
    return text, row["uid"]


def _resolve_professor_field(professor_select: str, professor_new: str, conn) -> tuple[str | None, str | None]:
    """The Professor field is a <select> of contacts by uid plus a
    "+ Add new professor..." sentinel (schedule_class_form.html) --
    unambiguous compared to the free-text-with-suggestions field this
    replaced, which blurred "picked an existing person" and "typed
    something new" into the same input. Picking a real contact links
    straight to it by uid, no name-matching involved at all; only the
    "add new" path goes through name-based dedupe/creation
    (`_resolve_new_professor_name`)."""
    if professor_select == "__new__":
        return _resolve_new_professor_name(professor_new, conn)
    if professor_select:
        contact = db.get_contact(conn, professor_select)
        if contact:
            return contact["full_name"], contact["uid"]
    return None, None


def _resolve_class_type_field(class_type_select: str, class_type_other: str) -> str:
    """Class type is a segmented control pre-populated with this user's
    own already-used values plus a "+ Other" option (2026-08-07,
    modal-input-design Phase E, §3) -- same "picked from a known set" vs.
    "typed something new" split as `_resolve_professor_field` above, just
    without a contacts table on the other end: picking "__other__" means
    trust the free-text fallback, anything else is used as-is (including
    the empty "(none)" option)."""
    if class_type_select == "__other__":
        return class_type_other
    return class_type_select


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
    all_classes = db.list_schedule_classes(conn)
    settings = db.get_schedule_settings(conn)
    # Conflicts/credits always reflect *every* class, never the search box
    # or label filter -- a conflict warning for a class that doesn't
    # currently match shouldn't disappear just because the table's
    # filtered to something else. The calendar-view grid *does* follow the
    # label filter (2026-08-08, same "label picks filter the whole view"
    # behavior as Calendar's own label dropdown) -- see below.
    conflicts = schedule_logic.compute_conflicts(all_classes)
    used_credits = schedule_logic.credits_summary(all_classes)
    needed = settings.get("credits_needed")

    # Label filter (2026-08-08, same single-select fancy toolbar dropdown
    # as Calendar/Tasks): classes link to a label by project_uid, so the
    # dropdown lists only labels actually attached to at least one block,
    # keyed by uid (value) with a human name for display.
    _label_map = {l["uid"]: l["name"] for l in db.list_labels(conn)}
    label_items: list[dict] = []
    _seen: set[str] = set()
    for _c in all_classes:
        _uid = _c.get("project_uid")
        if _uid and _uid in _label_map and _uid not in _seen:
            _seen.add(_uid)
            label_items.append({"value": _uid, "name": _label_map[_uid]})

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
            "label": label or "",
            "schedule_label_items": label_items,
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
            # 2026-08-08: Settings (semester dates/credits/reminder/event
            # label) moved back onto this page as a <details> block, same
            # shape as Holidays -- needs the raw settings dict to prefill
            # that form now, not just the already-applied values above.
            "settings": settings,
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
            "projects": [l for l in db.list_labels(conn) if not l.get("generate_space")],
            "class_types": db.list_schedule_class_types(conn),
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
    now = datetime.now(timezone.utc).isoformat()
    professor_name, professor_contact_uid = _resolve_professor_field(professor_select, professor_new, conn)
    class_type = _resolve_class_type_field(class_type_select, class_type_other)
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
    cls = _regenerate_class_event(cls, settings, holidays, conn)
    db.upsert_schedule_class(conn, cls)
    if project_uid:
        # A course "becomes a project" per the feature request via this
        # dropdown -- upsert_schedule_class deliberately never lists
        # project_uid in its own column set (see set_schedule_class_project's
        # docstring in db.py), so it's always applied as a separate step.
        db.set_schedule_class_project(conn, cls["uid"], project_uid)
    else:
        # §5 University module: auto-create a project label for every new
        # class that wasn't explicitly linked to an existing one (no
        # longer also a Grades database -- see
        # _auto_provision_university_project's own 2026-08-07 note). The
        # edit form always has the project dropdown pre-filled, so this
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
            "projects": [l for l in db.list_labels(conn) if not l.get("generate_space")],
            "class_types": db.list_schedule_class_types(conn),
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
    existing = db.get_schedule_class(conn, uid) or {}
    professor_name, professor_contact_uid = _resolve_professor_field(professor_select, professor_new, conn)
    class_type = _resolve_class_type_field(class_type_select, class_type_other)
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
    cls = _regenerate_class_event(cls, settings, holidays, conn)
    db.upsert_schedule_class(conn, cls)
    # See create_class above for why this is a separate explicit call.
    db.set_schedule_class_project(conn, uid, project_uid or None)
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/classes/{uid}/reposition")
async def reposition_class(uid: str, request: Request, conn=Depends(get_db)):
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
    cls = _regenerate_class_event(cls, settings, holidays, conn)
    db.upsert_schedule_class(conn, cls)
    return JSONResponse({"ok": True, "day": cls["day"], "start_time": cls["start_time"], "end_time": cls["end_time"]})


_UPDATABLE_FIELDS = {"parity"}


@router.post("/classes/{uid}/update-field")
async def update_class_field(uid: str, request: Request, conn=Depends(get_db)):
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
    cls = _regenerate_class_event(cls, settings, holidays, conn)
    db.upsert_schedule_class(conn, cls)
    return JSONResponse({"ok": True})


@router.post("/classes/{uid}/toggle-enrolled")
def toggle_enrolled(uid: str, conn=Depends(get_db)):
    """Plain-form boolean toggle for the Table view's Enrolled icon --
    same "click the icon, it's a real form submit" pattern as Tasks'
    Mark-done column (tasks_list.html), not a dropdown/JS-only control."""
    cls = db.get_schedule_class(conn, uid)
    if cls:
        cls["enrolled"] = not cls.get("enrolled", True)
        cls["updated_at"] = datetime.now(timezone.utc).isoformat()
        settings = db.get_schedule_settings(conn)
        holidays = db.list_holidays(conn)
        cls = _regenerate_class_event(cls, settings, holidays, conn)
        db.upsert_schedule_class(conn, cls)
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/classes/{uid}/delete")
def delete_class(uid: str, conn=Depends(get_db)):
    cls = db.get_schedule_class(conn, uid)
    if cls and cls.get("event_uid"):
        db.delete_event(conn, cls["event_uid"])
    db.delete_schedule_class(conn, uid)
    # 2026-08-07: no more db.delete_grades_by_class(conn, uid) call here --
    # the `grades` table (and the rest of Databases/Grades) is gone.
    return RedirectResponse(url="/schedule", status_code=303)


# Phase 1 (label-space rework, 2026-08-06) dropped GET/POST /schedule/export
# -- that flow picked (or created) a *calendar* for the mirrored class
# events to live in, and `calendars` no longer exists (there's one
# universal events pool now, see db.py's Phase 1 comments). Every class's
# mirrored VEVENT lands directly in that pool (_regenerate_class_event
# above); schedule_settings.target_calendar_uid is vestigial (unused,
# left in the schema rather than migrated -- harmless dead column, not
# worth a schema migration in this phase).


@router.post("/holidays")
def create_holiday(
    label: str = Form(""),
    date_from: str = Form(...),
    date_to: str = Form(...),
    conn=Depends(get_db),
):
    db.upsert_holiday(
        conn, {"uid": str(uuid.uuid4()), "label": label, "date_from": date_from, "date_to": date_to}
    )
    _regenerate_all(conn)
    # 2026-08-01: Holidays merged into the main Blocks view (schedule_classes.html)
    # -- no more standalone /schedule/holidays page to redirect back to.
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/holidays/{uid}/delete")
def delete_holiday(uid: str, conn=Depends(get_db)):
    db.delete_holiday(conn, uid)
    _regenerate_all(conn)
    return RedirectResponse(url="/schedule", status_code=303)


@router.post("/settings")
def save_settings(
    semester_start: str = Form(""),
    semester_end: str = Form(""),
    credits_needed: str = Form(""),
    reminder_minutes: str = Form("15"),
    schedule_label: str = Form("Schedule"),
    conn=Depends(get_db),
):
    db.save_schedule_settings(
        conn,
        {
            "semester_start": semester_start or None,
            "semester_end": semester_end or None,
            "credits_needed": float(credits_needed) if credits_needed else None,
            "reminder_minutes": int(reminder_minutes) if reminder_minutes else 15,
            "schedule_label": schedule_label.strip() or "Schedule",
        },
    )
    _regenerate_all(conn)
    # 2026-08-08: Settings is a <details> block on /schedule itself now
    # (same as Holidays), not its own page -- see classes_view's own
    # comment. Redirect there instead of the now-removed /schedule/settings
    # page view.
    return RedirectResponse(url="/schedule", status_code=303)
