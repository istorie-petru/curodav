"""Multiple task lists: create/rename/recolor/delete, each a real separate
CalDAV VTODO collection (see caldav_bridge.py's `_task_calendar` and
db.py's `task_lists` table). Deliberately no per-device hide-cookie toggle
like calendars.py has -- task lists are filtered via a query param/select
in the Table/Board views instead of a persistent visibility set, since
"show me List X" is the more common need than "hide List X everywhere,"
which is what calendars' multi-calendar-overlay legend is actually for."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import icalendar
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_bridge, get_db, templates
from ..ical_rows import ical_to_task_row

router = APIRouter(prefix="/task-lists", tags=["task-lists"])

COLORS = ["blue", "green", "orange", "red", "purple", "pink", "gray", "yellow"]
_MAX_IMPORT_BYTES = 10 * 1024 * 1024


def _all_collection_uids(conn) -> set[str]:
    """Every collection name already in use across calendars, task lists,
    and address books -- all three live in the same flat namespace under
    the Radicale principal's URL (e.g. `/devuser/<name>/`), so a new task
    list can't reuse a name any of the other two already claimed, not just
    names within its own table."""
    return (
        {c["uid"] for c in db.list_calendars(conn)}
        | {t["uid"] for t in db.list_task_lists(conn)}
        | {a["uid"] for a in db.list_addressbooks(conn)}
    )


def _slugify(name: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "list"
    slug = base
    n = 2
    while slug in existing:
        slug = f"{base}-{n}"
        n += 1
    return slug


@router.get("")
def list_task_lists_view(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "task_lists_manage.html",
        {
            "request": request,
            "active_tab": "tasks",
            "task_lists": db.list_task_lists(conn),
            "colors": COLORS,
            "projects": db.list_projects(conn),
        },
    )


def _safe_return_to(return_to, default: str) -> str:
    """Same allowlist as routers/projects.py's edit_project -- only an
    absolute internal path (starts with "/") is honored, so a create/edit
    posted from somewhere other than this collection's own manage page
    (2026-08-02: the Projects page's per-project quick-add/link-existing
    forms) can send you back there instead of always landing on /task-
    lists, /calendars, or /addressbooks, without this becoming an open
    redirect. `return_to` arrives as the raw Form(...) default object
    (not a str) when this is called directly (tests, not through FastAPI's
    own request parsing) -- isinstance guards that the same way
    edit_project already does."""
    return return_to if isinstance(return_to, str) and return_to.startswith("/") else default


@router.post("")
def create_task_list(
    name: str = Form(...),
    color: str = Form("blue"),
    project_uid: str = Form(""),
    return_to: str = Form(""),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    uid = _slugify(name, _all_collection_uids(conn))
    bridge.ensure_task_list(uid)
    db.upsert_task_list(
        conn,
        {"uid": uid, "name": name, "color": color, "created_at": datetime.now(timezone.utc).isoformat()},
    )
    if project_uid:
        db.set_task_list_project(conn, uid, project_uid)
    return RedirectResponse(url=_safe_return_to(return_to, "/task-lists"), status_code=303)


@router.post("/{uid}/edit")
def edit_task_list(
    uid: str,
    name: str = Form(...),
    color: str = Form("blue"),
    project_uid: str = Form(""),
    return_to: str = Form(""),
    conn=Depends(get_db),
):
    existing = db.get_task_list(conn, uid)
    db.upsert_task_list(
        conn,
        {"uid": uid, "name": name, "color": color, "created_at": existing.get("created_at") if existing else None},
    )
    # See routers/calendars.py's edit_calendar for why this is an explicit
    # setter call, not folded into the upsert above.
    db.set_task_list_project(conn, uid, project_uid or None)
    return RedirectResponse(url=_safe_return_to(return_to, "/task-lists"), status_code=303)


@router.post("/link")
def link_task_list(uid: str = Form(...), project_uid: str = Form(""), return_to: str = Form(""), conn=Depends(get_db)):
    """Pure association change -- no name/color involved -- used by the
    Projects page's per-project "Link existing" picker (2026-08-02): `uid`
    comes from a <select> of currently-unclaimed lists (routers/
    projects.py's manage_projects only offers ones with no project_uid
    yet, so this never silently steals a list already claimed by another
    project), and the same endpoint also unlinks when project_uid is left
    blank -- one form shape either way, mirroring edit_task_list's own
    `project_uid or None` -> real NULL semantics. Registered as a literal
    `/link` segment, not `/{uid}/link`, specifically so `uid` can be a
    plain form field (a <select>'s value) rather than needing JS to
    rewrite the form's action to a per-row URL."""
    if db.get_task_list(conn, uid) is not None:
        db.set_task_list_project(conn, uid, project_uid or None)
    return RedirectResponse(url=_safe_return_to(return_to, "/task-lists"), status_code=303)


@router.post("/{uid}/delete")
def delete_task_list(uid: str, bridge=Depends(get_bridge), conn=Depends(get_db)):
    if len(db.list_task_lists(conn)) <= 1:
        # Refuse to delete the last list -- every task needs somewhere to
        # live, and task_form.html's selector assumes at least one option
        # always exists (same guard calendars.py uses for the last calendar).
        return RedirectResponse(url="/task-lists", status_code=303)
    bridge.delete_task_list_collection(uid)
    db.delete_tasks_by_list(conn, uid)
    db.delete_task_list(conn, uid)
    return RedirectResponse(url="/task-lists", status_code=303)


# --------------------------------------------------------------------- #
# Import (.ics VTODOs -> an existing or brand-new task list)
# --------------------------------------------------------------------- #


@router.get("/import")
def import_form(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "task_lists_import.html",
        {"request": request, "active_tab": "tasks", "task_lists": db.list_task_lists(conn), "colors": COLORS},
    )


def _import_ics_tasks(raw: bytes, list_path: str, bridge, conn) -> tuple[int, int]:
    """Same shape as routers/calendars.py's `_import_ics_events`, just
    walking VTODO instead of VEVENT -- some calendar apps (Apple Reminders'
    export, in particular) put tasks in the same .ics format as events,
    just as a different component type within the same VCALENDAR."""
    try:
        cal = icalendar.Calendar.from_ical(raw)
    except (ValueError, IndexError):
        return 0, 0
    imported = skipped = 0
    now = datetime.now(timezone.utc).isoformat()
    for component in cal.walk("VTODO"):
        try:
            row = ical_to_task_row(component)
            if not row.get("uid") or row["uid"] == "None":
                raise ValueError("missing UID")
            row["list_path"] = list_path
            row.setdefault("status", "active")
            row["created_at"] = now
            row["updated_at"] = now
            saved = bridge.save_task_row(row)
            db.upsert_task(conn, saved)
            imported += 1
        except Exception:
            skipped += 1
    return imported, skipped


@router.post("/import")
async def import_submit(
    request: Request,
    mode: str = Form(...),
    list_uid: str = Form(""),
    new_name: str = Form(""),
    new_color: str = Form("blue"),
    file: UploadFile = File(...),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    if mode == "new":
        target = _slugify(new_name or "Imported", _all_collection_uids(conn))
        bridge.ensure_task_list(target)
        db.upsert_task_list(
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
        target = list_uid or db.DEFAULT_TASK_LIST_UID
        existing = db.get_task_list(conn, target)
        target_name = existing["name"] if existing else target

    raw = await file.read()
    raw = raw[:_MAX_IMPORT_BYTES]
    imported, skipped = _import_ics_tasks(raw, target, bridge, conn)
    return templates.TemplateResponse(
        "import_result.html",
        {
            "request": request,
            "imported": imported,
            "skipped": skipped,
            "target_name": target_name,
            "back_url": "/tasks",
            "active_tab": "tasks",
        },
    )
