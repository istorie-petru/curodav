"""Notebook (curodav-notes/documentation/plans/STATE.md +
architecture-notes-module-2026-09-29.md, 2026-09-29) -- Phase 1 backend
skeleton of the 0-to-MVP roadmap: a top-level, block-based note-taking
module with two modes (see db.py's `notebook_documents` schema comment for
the full column rationale):

  * Browser mode -- this router's plain list/create/delete routes, server-
    rendered Jinja2 like every other feature.
  * Editor mode -- the `/notebook/{uid}` page, which mounts Editor.js
    (Phase 2) against the one deliberate JSON exception below.

MVP scope only: no citations, no cross-referencing, no Calibre Web, no
absorption of the old quick-capture `notes` feature (Phase 4) -- see the
roadmap for what's intentionally not here yet. The Groups/Labels widget
itself (Phase 3) lives in routers/dashboard.py's WIDGET_TYPES registry,
not here -- this router only needed to support create-with-label (already
present below) for that widget to work."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Header, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db
from ..deps import get_db, respond, templates, wants_json

router = APIRouter(prefix="/notebook", tags=["notebook"])


def _notebook_list_context(conn, request: Request) -> dict:
    return {
        "request": request,
        "active_tab": "notebook",
        # The "All documents" safety net (STATE.md's MVP-readiness-check
        # gap #2): every document regardless of label, not scoped to one
        # label/group yet -- that's Phase 3's widget, a narrower query on
        # top of the same db.list_notebook_documents(label=...) support.
        "documents": db.list_notebook_documents(conn),
    }


@router.get("")
def list_documents(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse("notebook_list.html", _notebook_list_context(conn, request))


@router.post("")
def create_document(
    label: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """A document starts blank -- there's no form to fill in first (unlike
    a task/contact/note, a Notebook document's actual content is written in
    the Editor, not at creation time). `label` is optional, pre-attaching
    this document to whichever label/group page it was created from (Phase
    3's "New note" widget action); the All Documents view's own "New"
    button omits it, same as how a document with no label at all is
    exactly what that view exists to still surface.

    Redirects straight into the new document's own Editor page, not back to
    a list -- standard "New" behavior for a note-taking app (Notion/Apple
    Notes/Google Docs all open the new, still-empty document immediately),
    and the only choice that makes sense from every caller of this route:
    the All Documents page, and (Phase 3) a label/group page's widget, which
    has nowhere sensible to "refresh in place" to. A plain form with no
    data-cc-change needed anywhere this route is posted from -- the real
    redirect is the whole mechanism, same as every other plain-form POST in
    this app."""
    now = datetime.now(timezone.utc).isoformat()
    uid = str(uuid.uuid4())
    row = {
        "uid": uid,
        "title": "Untitled",
        "content_json": '{"blocks": []}',
        "document_type": "full",
        "note_type": "notes",
        "created_at": now,
        "updated_at": now,
        "tags": [label] if label else [],
    }
    db.upsert_notebook_document(conn, row)
    return respond(x_requested_with, f"/notebook/{uid}", status_code=201, uid=uid)


@router.get("/{uid}")
def document_page(uid: str, request: Request, conn=Depends(get_db)):
    document = db.get_notebook_document(conn, uid)
    if document is None:
        return RedirectResponse(url="/notebook", status_code=303)
    return templates.TemplateResponse(
        "notebook_document.html",
        {"request": request, "active_tab": "notebook", "document": document},
    )


@router.post("/{uid}")
def update_document_title(
    uid: str,
    title: str = Form(...),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Not in the roadmap's own route list, added because without it a
    document could never get a real name within MVP scope at all --
    Browser mode's richer "edit frontmatter without opening the document"
    modal is explicitly post-MVP (STATE.md), but the title itself can't
    wait for that; this is the minimal plain-form equivalent, same
    `respond()`-based JSON-or-redirect shape every other mutation route in
    this app uses."""
    existing = db.get_notebook_document(conn, uid)
    if existing is None:
        if wants_json(x_requested_with):
            return JSONResponse({"error": "document not found"}, status_code=404)
        return RedirectResponse(url="/notebook", status_code=303)
    row = dict(existing)
    row["title"] = title.strip() or "Untitled"
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.upsert_notebook_document(conn, row)
    return respond(x_requested_with, f"/notebook/{uid}")


@router.post("/{uid}/delete")
def delete_document(
    uid: str,
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    db.delete_notebook_document(conn, uid)
    return respond(x_requested_with, "/notebook")


# The one deliberate JSON exception in this router (db.py's
# `notebook_documents` schema comment has the full reasoning): Editor.js's
# own API is JS-object in/out, and there's no HTML fragment that can
# represent live rich-block-editor state, so this pair talks raw JSON
# instead of this app's normal server-rendered-fragment convention.
@router.get("/{uid}/content")
def get_document_content(uid: str, conn=Depends(get_db)):
    content = db.get_notebook_document_content(conn, uid)
    if content is None:
        return JSONResponse({"error": "document not found"}, status_code=404)
    return JSONResponse(content)


@router.put("/{uid}/content")
async def put_document_content(uid: str, request: Request, conn=Depends(get_db)):
    content = await request.json()
    if not db.set_notebook_document_content(conn, uid, content):
        return JSONResponse({"error": "document not found"}, status_code=404)
    return JSONResponse({"ok": True})
