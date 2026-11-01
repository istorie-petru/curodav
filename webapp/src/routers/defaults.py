"""Settings > Defaults: where a new item's reminder, length or tag starts from. Item values always win, and changing a
default never rewrites an item that already exists.

To add a default, add its key to app_defaults.KEYS, use it where the item is created, and list it in ROWS.

Feature notes: curodav-notes/documentation/features/notebook.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import app_defaults, db
from .. import tags as tag_store
from ..deps import get_db, templates

router = APIRouter(prefix="/settings/defaults", tags=["defaults"])

REMINDERS = lambda conn: app_defaults.REMINDER_CHOICES  # noqa: E731
LENGTHS = lambda conn: app_defaults.LENGTH_CHOICES  # noqa: E731


def _tags(conn) -> list[tuple[str, str]]:
    return [("", "No tag")] + [(i["name"], i["name"]) for i in tag_store.picker(conn, "notebook", "", [])["items"]]


HOURS = lambda conn: app_defaults.HOUR_CHOICES  # noqa: E731
CALENDAR_VIEWS = lambda conn: app_defaults.CALENDAR_VIEWS  # noqa: E731

ROWS = [
    {"group": "Calendar", "key": "calendar_view", "label": "Calendar opens on", "hint": "The view the Calendar tab opens", "choices": CALENDAR_VIEWS},
    {"group": "Tasks", "key": "tasks_view", "label": "Tasks opens on", "hint": "The view the Tasks tab opens", "choices": lambda conn: app_defaults.TASKS_VIEWS},
    {"group": "Tasks", "key": "habit_reminder", "label": "Habit reminder", "hint": "Preselected when a habit is created", "choices": HOURS},
    {"group": "Notifications", "key": "quiet_start", "label": "Quiet hours start", "hint": "No reminders are sent from this time", "choices": HOURS},
    {"group": "Notifications", "key": "quiet_end", "label": "Quiet hours end", "hint": "Reminders resume at this time", "choices": HOURS},
    {"group": "Calendar", "key": "event_reminder", "label": "Event reminder", "hint": "Added to new events", "choices": REMINDERS},
    {"group": "Calendar", "key": "event_length", "label": "Event length", "hint": "Fills the end time of a new timed event", "choices": LENGTHS},
    {"group": "University", "key": "class_reminder", "label": "Class reminder", "hint": "Added to classes created from now on", "choices": REMINDERS},
    {"group": "Notebook", "key": "note_tag", "label": "Note tag", "hint": "Preselected when a note is created outside a folder", "choices": _tags},
]


LINKS = [
    {"group": "Set elsewhere", "label": "Week start, time format, time zone, currency", "hint": "General", "href": "/settings/general"},
    {"group": "Set elsewhere", "label": "Morning reminder and notification types", "hint": "Notifications", "href": "/settings/notifications"},
    {"group": "Set elsewhere", "label": "Journal template, citation format, entry types", "hint": "Notebook", "href": "/settings/notebook"},
    {"group": "Set elsewhere", "label": "Rating scale and criteria, media kinds, film source", "hint": "Library", "href": "/settings/library"},
]


def _folder_rows(conn) -> list[dict]:
    templates_ = [("", "Blank note")] + [(d["uid"], d["title"] or "Untitled") for d in db.list_notebook_documents(conn, scope="templates")]
    items = [{"uid": v, "name": n} for v, n in templates_]
    folders = [f for f in db.list_notebook_folders(conn)["labels"] if f["kind"] != "unfiled"]
    return [{"group": "Notebook folders", "key": app_defaults.FOLDER_TEMPLATE + f["name"], "label": f["name"], "hint": "Template for new notes",
             "items": items, "value": app_defaults.folder_template(conn, f["name"])} for f in folders]


def _rows(conn) -> list[dict]:
    out = []
    for row in ROWS:
        items = [{"uid": v, "name": n} for v, n in row["choices"](conn)]
        out.append({**row, "items": items, "value": app_defaults.get(conn, row["key"])})
    return out + _folder_rows(conn)


@router.get("")
def defaults_page(request: Request, conn=Depends(get_db)):
    rows = _rows(conn)
    groups = [{"name": g, "rows": [r for r in rows if r["group"] == g]} for g in dict.fromkeys(r["group"] for r in rows)]
    groups.append({"name": LINKS[0]["group"], "rows": LINKS})
    return templates.TemplateResponse(
        "settings_defaults.html",
        {"request": request, "active_tab": "settings_defaults", "crumbs": [{"url": "/settings", "name": "Settings"}], "title": "Defaults", "groups": groups},
    )


@router.post("")
def save_default(key: str = Form(...), value: str = Form(""), conn=Depends(get_db)):
    if key.startswith(app_defaults.FOLDER_TEMPLATE):
        if value == "" or db.get_notebook_document(conn, value):
            app_defaults.put_folder_template(conn, key[len(app_defaults.FOLDER_TEMPLATE):], value)
        return RedirectResponse(url="/settings/defaults", status_code=303)
    row = next((r for r in ROWS if r["key"] == key), None)
    if row is not None and value in {v for v, _ in row["choices"](conn)}:
        app_defaults.put(conn, key, value)
    return RedirectResponse(url="/settings/defaults", status_code=303)
