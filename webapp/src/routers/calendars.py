"""Multi-calendar management: create/rename/recolor/delete calendars, the
per-device visibility toggle (a cookie, not synced anywhere -- matches
desktop's "each has a visibility toggle, persisted locally" behavior for
its multi-calendar legend, see features/calendar.md), and importing events
from an .ics file into an existing or brand-new calendar."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

import icalendar
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_bridge, get_db, templates
from ..ical_rows import ical_to_event_row

router = APIRouter(prefix="/calendars", tags=["calendars"])

HIDDEN_COOKIE = "hidden_calendars"
COLORS = ["blue", "green", "orange", "red", "purple", "pink", "gray", "yellow"]
_MAX_IMPORT_BYTES = 10 * 1024 * 1024


def _all_collection_uids(conn) -> set[str]:
    """Every collection name already in use across calendars, task lists,
    and address books -- see routers/task_lists.py's identical helper for
    why: all three share one flat namespace on the Radicale server, so a
    new calendar can't reuse a task list's or address book's name either,
    not just another calendar's."""
    return (
        {c["uid"] for c in db.list_calendars(conn)}
        | {t["uid"] for t in db.list_task_lists(conn)}
        | {a["uid"] for a in db.list_addressbooks(conn)}
    )


def get_hidden_calendars(request: Request) -> set[str]:
    raw = request.cookies.get(HIDDEN_COOKIE)
    if not raw:
        return set()
    try:
        return set(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        return set()


def _slugify(name: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "calendar"
    slug = base
    n = 2
    while slug in existing:
        slug = f"{base}-{n}"
        n += 1
    return slug


@router.get("")
def list_calendars_view(request: Request, conn=Depends(get_db)):
    hidden = get_hidden_calendars(request)
    calendars = db.list_calendars(conn)
    return templates.TemplateResponse(
        "calendars_list.html",
        {
            "request": request,
            "active_tab": "calendar",
            "calendars": calendars,
            "hidden": hidden,
            "colors": COLORS,
            "projects": db.list_projects(conn),
        },
    )


def _safe_return_to(return_to, default: str) -> str:
    """See routers/task_lists.py's identical helper -- only an absolute
    internal path is honored, so the Projects page's per-project quick-
    add/link-existing calendar forms (2026-08-02) can send you back there
    instead of always landing on /calendars."""
    return return_to if isinstance(return_to, str) and return_to.startswith("/") else default


@router.post("")
def create_calendar(
    name: str = Form(...),
    color: str = Form("blue"),
    project_uid: str = Form(""),
    return_to: str = Form(""),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    uid = _slugify(name, _all_collection_uids(conn))
    bridge.ensure_calendar(uid)
    db.upsert_calendar(
        conn,
        {"uid": uid, "name": name, "color": color, "created_at": datetime.now(timezone.utc).isoformat()},
    )
    if project_uid:
        db.set_calendar_project(conn, uid, project_uid)
    return RedirectResponse(url=_safe_return_to(return_to, "/calendars"), status_code=303)


@router.post("/{uid}/edit")
def edit_calendar(
    uid: str,
    name: str = Form(...),
    color: str = Form("blue"),
    project_uid: str = Form(""),
    return_to: str = Form(""),
    conn=Depends(get_db),
):
    existing = db.get_calendar(conn, uid)
    db.upsert_calendar(
        conn,
        {
            "uid": uid,
            "name": name,
            "color": color,
            "created_at": existing.get("created_at") if existing else None,
        },
    )
    # Explicit setter, not folded into the upsert above -- see
    # upsert_calendar's own COALESCE comment (db.py): an ordinary rename/
    # recolor must not silently touch project_uid, so this form field is
    # applied via set_calendar_project regardless, including clearing it
    # back to unassigned when the dropdown is set to "(no project)" (an
    # empty string here is a real, explicit "unassign," not "don't touch").
    db.set_calendar_project(conn, uid, project_uid or None)
    return RedirectResponse(url=_safe_return_to(return_to, "/calendars"), status_code=303)


@router.post("/link")
def link_calendar(uid: str = Form(...), project_uid: str = Form(""), return_to: str = Form(""), conn=Depends(get_db)):
    """See routers/task_lists.py's identical link_task_list -- pure
    association change for the Projects page's "Link existing" picker."""
    if db.get_calendar(conn, uid) is not None:
        db.set_calendar_project(conn, uid, project_uid or None)
    return RedirectResponse(url=_safe_return_to(return_to, "/calendars"), status_code=303)


@router.post("/{uid}/delete")
def delete_calendar(uid: str, bridge=Depends(get_bridge), conn=Depends(get_db)):
    if len(db.list_calendars(conn)) <= 1:
        # Refuse to delete the last calendar -- every event needs somewhere
        # to live, and event_form.html's selector assumes at least one
        # option always exists.
        return RedirectResponse(url="/calendars", status_code=303)
    bridge.delete_calendar_collection(uid)
    db.delete_events_by_calendar(conn, uid)
    db.delete_calendar(conn, uid)
    return RedirectResponse(url="/calendars", status_code=303)


@router.post("/{uid}/toggle-visibility")
def toggle_visibility(uid: str, request: Request, next: str = Form("/")):
    hidden = get_hidden_calendars(request)
    if uid in hidden:
        hidden.discard(uid)
    else:
        hidden.add(uid)
    response = RedirectResponse(url=next, status_code=303)
    response.set_cookie(HIDDEN_COOKIE, json.dumps(sorted(hidden)), max_age=60 * 60 * 24 * 365)
    return response


# --------------------------------------------------------------------- #
# Import (.ics -> an existing or brand-new calendar)
# --------------------------------------------------------------------- #


@router.get("/import")
def import_form(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "calendars_import.html",
        {"request": request, "active_tab": "calendar", "calendars": db.list_calendars(conn), "colors": COLORS},
    )


def _import_ics_events(raw: bytes, calendar_path: str, bridge, conn) -> tuple[int, int]:
    """Parses every VEVENT out of an uploaded .ics file and saves each one
    into `calendar_path` through the normal event bridge (so imported
    events are real, synced CalDAV objects, not a local-only bulk-insert).
    Returns (imported, skipped) -- one bad VEVENT (a missing required
    field, an unparseable date) is skipped rather than aborting the whole
    import, since the whole point of importing a real-world .ics is that
    it may contain entries from a client with slightly different
    assumptions about what's required."""
    try:
        cal = icalendar.Calendar.from_ical(raw)
    except (ValueError, IndexError):
        return 0, 0
    imported = skipped = 0
    now = datetime.now(timezone.utc).isoformat()
    for component in cal.walk("VEVENT"):
        try:
            row = ical_to_event_row(component)
            if not row.get("uid") or row["uid"] == "None" or not row.get("start_at"):
                raise ValueError("missing UID or start time")
            row["calendar_path"] = calendar_path
            row.setdefault("status", "active")
            row["created_at"] = now
            row["updated_at"] = now
            saved = bridge.save_event_row(row)
            db.upsert_event(conn, saved)
            imported += 1
        except Exception:
            skipped += 1
    return imported, skipped


@router.post("/import")
async def import_submit(
    request: Request,
    mode: str = Form(...),
    calendar_uid: str = Form(""),
    new_name: str = Form(""),
    new_color: str = Form("blue"),
    file: UploadFile = File(...),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    if mode == "new":
        target = _slugify(new_name or "Imported", _all_collection_uids(conn))
        bridge.ensure_calendar(target)
        db.upsert_calendar(
            conn,
            {
                "uid": target,
                "name": new_name or "Imported",
                "color": new_color,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        target_name = new_name or "Imported"
    else:
        target = calendar_uid or db.DEFAULT_CALENDAR_UID
        existing = db.get_calendar(conn, target)
        target_name = existing["name"] if existing else target

    raw = await file.read()
    raw = raw[:_MAX_IMPORT_BYTES]
    imported, skipped = _import_ics_events(raw, target, bridge, conn)
    return templates.TemplateResponse(
        "import_result.html",
        {
            "request": request,
            "imported": imported,
            "skipped": skipped,
            "target_name": target_name,
            "back_url": "/calendar",
            "active_tab": "calendar",
        },
    )
