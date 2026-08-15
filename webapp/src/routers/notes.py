"""Notes -- the fourth Quick Capture entity type (`!n`, plans/quick-
capture.md), alongside the pre-existing tasks/events/contacts. Deliberately
minimal, matching the design doc's own scope: a note is free-text content
plus labels, nothing else (see db.py's `notes` CREATE TABLE comment). This
router exists so a captured note is a real, viewable/editable/deletable
page -- not just a database row Quick Capture writes and nothing ever reads
back -- following the same plain CRUD shape contacts.py uses (list / new /
edit / delete), just without contacts' photo-upload/vCard-specific pieces.

Not (yet) a primary tabbar destination -- reachable via the command palette
(both as a search result and as a "Notes" page-navigation entry, see
routers/search.py) and by direct URL. Promoting it to a full tabbar entry is
a separate, deliberately out-of-scope UI decision this slice doesn't make."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_db, templates
from . import dashboard as dashboard_router

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("")
def list_notes(request: Request, q: str | None = None, conn=Depends(get_db)):
    notes = db.list_notes(conn, q=q)
    return templates.TemplateResponse(
        "notes.html",
        {
            "request": request,
            "active_tab": "notes",
            "notes": [{"row": n, "title": db.note_title(n)} for n in notes],
            "q": q or "",
        },
    )


@router.get("/new")
def new_note_form(request: Request, content: str = "", conn=Depends(get_db)):
    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "note_form.html",
        {
            "request": request,
            "active_tab": "notes",
            "note": None,
            "prefill_content": content,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
        },
    )


@router.post("")
def create_note(
    content: str = Form(...),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    conn=Depends(get_db),
):
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "uid": str(uuid.uuid4()),
        "content": content,
        "tags": dashboard_router._tags_list(dashboard_router._combine_tags(tags, tags_labels)),
        "created_at": now,
        "updated_at": now,
    }
    db.upsert_note(conn, row)
    return RedirectResponse(url="/notes", status_code=303)


@router.get("/{uid}/edit")
def edit_note_form(uid: str, request: Request, conn=Depends(get_db)):
    note = db.get_note(conn, uid)
    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "note_form.html",
        {
            "request": request,
            "active_tab": "notes",
            "note": note,
            "prefill_content": "",
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
        },
    )


@router.post("/{uid}")
def update_note(
    uid: str,
    content: str = Form(...),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    conn=Depends(get_db),
):
    existing = db.get_note(conn, uid)
    if existing is None:
        return RedirectResponse(url="/notes", status_code=303)
    row = dict(existing)
    row["content"] = content
    row["tags"] = dashboard_router._tags_list(dashboard_router._combine_tags(tags, tags_labels))
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.upsert_note(conn, row)
    return RedirectResponse(url="/notes", status_code=303)


@router.post("/{uid}/delete")
def delete_note(uid: str, conn=Depends(get_db)):
    db.delete_note(conn, uid)
    return RedirectResponse(url="/notes", status_code=303)
