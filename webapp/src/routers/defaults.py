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
    {"page": "calendar", "key": "calendar_view", "label": "Calendar opens on", "hint": "The view the Calendar tab opens", "choices": CALENDAR_VIEWS},
    {"page": "calendar", "key": "event_reminder", "label": "Event reminder", "hint": "Added to new events", "choices": REMINDERS},
    {"page": "calendar", "key": "event_length", "label": "Event length", "hint": "Fills the end time of a new timed event", "choices": LENGTHS},
    {"page": "tasks", "key": "tasks_view", "label": "Tasks opens on", "hint": "The view the Tasks tab opens", "choices": lambda conn: app_defaults.TASKS_VIEWS},
    {"page": "tasks", "key": "habit_reminder", "label": "Habit reminder", "hint": "Preselected when a habit is created", "choices": HOURS},
    {"page": "notifications", "key": "quiet_start", "label": "Quiet hours start", "hint": "No reminders are sent from this time", "choices": HOURS},
    {"page": "notifications", "key": "quiet_end", "label": "Quiet hours end", "hint": "Reminders resume at this time", "choices": HOURS},
    {"page": "notebook", "key": "note_tag", "label": "Note tag", "hint": "Preselected when a note is created outside a folder", "choices": _tags},
]
BACK = {"calendar": "/settings/calendar", "tasks": "/settings/tasks", "notifications": "/settings/notifications", "notebook": "/settings/notebook"}


def folder_rows(conn) -> list[dict]:
    """The template a new note in each space's folder starts from, as rows for the Notebook page."""
    templates_ = [("", "Blank note")] + [(d["uid"], d["title"] or "Untitled") for d in db.list_notebook_documents(conn, scope="templates")]
    items = [{"uid": v, "name": n} for v, n in templates_]
    folders = [f for f in db.list_notebook_folders(conn)["spaces"] if f["kind"] != "unfiled"]
    return [{"page": "notebook", "back": BACK["notebook"], "key": app_defaults.FOLDER_TEMPLATE + f["name"], "label": f["name"], "hint": "Template for new notes",
             "items": items, "value": app_defaults.folder_template(conn, f["name"])} for f in folders]


def rows_for(conn, page: str) -> list[dict]:
    """The rows of one settings page, each with its dropdown items and current value and the page to come back to."""
    out = []
    for row in ROWS:
        if row["page"] == page:
            items = [{"uid": v, "name": n} for v, n in row["choices"](conn)]
            value = app_defaults.get(conn, row["key"])
            if value not in {i["uid"] for i in items} and items and "" not in {i["uid"] for i in items}:
                value = items[0]["uid"]  # nothing stored yet: the first choice is what applies
            out.append({**row, "items": items, "value": value, "back": BACK[page]})
    return out


@router.post("")
def save_default(key: str = Form(...), value: str = Form(""), back: str = Form(""), conn=Depends(get_db)):
    back = back if back in BACK.values() else "/settings/general"
    if key.startswith(app_defaults.FOLDER_TEMPLATE):
        if value == "" or db.get_notebook_document(conn, value):
            app_defaults.put_folder_template(conn, key[len(app_defaults.FOLDER_TEMPLATE):], value)
        return RedirectResponse(url=back, status_code=303)
    row = next((r for r in ROWS if r["key"] == key), None)
    if row is not None and value in {v for v, _ in row["choices"](conn)}:
        app_defaults.put(conn, key, value)
    return RedirectResponse(url=back, status_code=303)
