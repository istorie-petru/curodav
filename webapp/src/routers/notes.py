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

from fastapi import APIRouter, Depends, Form, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import db
from ..deps import get_db, respond, templates, wants_json
from . import dashboard as dashboard_router

router = APIRouter(prefix="/notes", tags=["notes"])


def _notes_list_context(conn, request: Request, q: str | None) -> dict:
    notes = db.list_notes(conn, q=q)
    return {
        "request": request,
        "active_tab": "notes",
        "notes": [{"row": n, "title": db.note_title(n)} for n in notes],
        "q": q or "",
    }


@router.get("")
def list_notes(request: Request, q: str | None = None, conn=Depends(get_db)):
    return templates.TemplateResponse("notes.html", _notes_list_context(conn, request, q))


@router.get("/regions")
def notes_regions(
    request: Request,
    region: str = "list",
    q: str | None = None,
    conn=Depends(get_db),
):
    """Async-CRUD region fragment (features/async-crud.md): renders the
    #notes-body div shared with notes.html so refreshRegion() can swap it in
    place after a note mutation instead of a full reload. Takes the same
    query params as list_notes so the refreshed region honors the search."""
    if region != "list":
        return JSONResponse({"error": f"unknown region '{region}'"}, status_code=400)
    ctx = _notes_list_context(conn, request, q)
    html = templates.env.get_template("_notes_body.html").render(ctx)
    return HTMLResponse(html)


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
    x_requested_with: str | None = Header(default=None),
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
    return respond(x_requested_with, "/notes", status_code=201, uid=row["uid"])


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
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    existing = db.get_note(conn, uid)
    if existing is None:
        if wants_json(x_requested_with):
            return JSONResponse({"error": "note not found"}, status_code=404)
        return RedirectResponse(url="/notes", status_code=303)
    row = dict(existing)
    row["content"] = content
    row["tags"] = dashboard_router._tags_list(dashboard_router._combine_tags(tags, tags_labels))
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.upsert_note(conn, row)
    return respond(x_requested_with, "/notes")


@router.post("/{uid}/delete")
def delete_note(
    uid: str,
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    db.delete_note(conn, uid)
    return respond(x_requested_with, "/notes")
