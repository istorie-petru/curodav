"""Two fixed address books (Active='contacts', Archived='contacts-archived').

Users can no longer create or delete address books -- the two-addressbook
model (§4 of the contacts rework) replaces arbitrary books with a single
Active collection and a single Archived collection, with the old per-book
grouping replaced by tags (CATEGORIES on the vCard, tags_json in the DB).

What's left here:
  - GET /addressbooks   -- manage page (shows the two fixed books, read-only)
  - POST /addressbooks/import  -- .vcf import, always targets Active
  - POST /addressbooks/link    -- project association (Projects page)
  - POST /addressbooks/{uid}/edit  -- project assignment only (name/color fixed)

Everything that *was* here but is now gone:
  - POST /addressbooks          (create)   -- removed
  - POST /addressbooks/{uid}/delete        -- removed
  - Name/color editing in the edit form    -- name is fixed; color still editable
    so the Project page's color picker still works as a visual cue.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import vobject
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_bridge, get_db, templates
from ..vcard_rows import vcard_to_contact_row

router = APIRouter(prefix="/addressbooks", tags=["addressbooks"])

_MAX_IMPORT_BYTES = 10 * 1024 * 1024


def _safe_return_to(return_to, default: str) -> str:
    """Only honour an absolute internal path as a redirect target -- same
    guard as the one in task_lists.py / the old version of this file."""
    return return_to if isinstance(return_to, str) and return_to.startswith("/") else default


@router.get("")
def list_addressbooks_view(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "addressbooks_manage.html",
        {
            "request": request,
            "active_tab": "contacts",
            "addressbooks": db.list_addressbooks(conn),
            "projects": db.list_projects(conn),
        },
    )


@router.post("/{uid}/edit")
def edit_addressbook(
    uid: str,
    project_uid: str = Form(""),
    return_to: str = Form(""),
    conn=Depends(get_db),
):
    """Project-assignment only.  Name and color of the two fixed books are
    immutable from the UI -- only the project link can be changed here."""
    if db.get_addressbook(conn, uid) is not None:
        db.set_addressbook_project(conn, uid, project_uid or None)
    return RedirectResponse(url=_safe_return_to(return_to, "/addressbooks"), status_code=303)


@router.post("/link")
def link_addressbook(uid: str = Form(...), project_uid: str = Form(""), return_to: str = Form(""), conn=Depends(get_db)):
    """Pure association change for the Projects page's 'Link existing' picker."""
    if db.get_addressbook(conn, uid) is not None:
        db.set_addressbook_project(conn, uid, project_uid or None)
    return RedirectResponse(url=_safe_return_to(return_to, "/addressbooks"), status_code=303)


# --------------------------------------------------------------------- #
# Import (.vcf -> always into Active)
# --------------------------------------------------------------------- #


@router.get("/import")
def import_form(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "addressbooks_import.html",
        {
            "request": request,
            "active_tab": "contacts",
            # Only show Active for the destination -- Archived is not a
            # sensible import target.
            "addressbooks": [
                ab
                for ab in db.list_addressbooks(conn)
                if ab["uid"] == db.DEFAULT_ADDRESSBOOK_UID
            ],
        },
    )


def _import_vcf_contacts(raw: bytes, addressbook_path: str, bridge, conn) -> tuple[int, int]:
    """Same shape as the old version -- parses a concatenated .vcf byte
    string and saves each vCard into the given addressbook collection."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    try:
        cards = list(vobject.readComponents(text))
    except Exception:
        return 0, 0
    imported = skipped = 0
    now = datetime.now(timezone.utc).isoformat()
    for card in cards:
        try:
            if not hasattr(card, "uid"):
                card.add("uid").value = str(uuid.uuid4())
            row = vcard_to_contact_row(card)
            if not row.get("uid"):
                raise ValueError("missing UID")
            row["addressbook_path"] = addressbook_path
            row["created_at"] = now
            row["updated_at"] = now
            saved = bridge.save_contact_row(row)
            db.upsert_contact(conn, saved)
            imported += 1
        except Exception:
            skipped += 1
    return imported, skipped


@router.post("/import")
async def import_submit(
    request: Request,
    file: UploadFile = File(...),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    """Always imports into the Active addressbook (DEFAULT_ADDRESSBOOK_UID).
    The 'mode=new / mode=existing' choice is gone -- there are now only two
    fixed books and new books can't be created."""
    target = db.DEFAULT_ADDRESSBOOK_UID
    existing = db.get_addressbook(conn, target)
    target_name = existing["name"] if existing else "Active"

    raw = await file.read()
    raw = raw[:_MAX_IMPORT_BYTES]
    imported, skipped = _import_vcf_contacts(raw, target, bridge, conn)
    return templates.TemplateResponse(
        "import_result.html",
        {
            "request": request,
            "imported": imported,
            "skipped": skipped,
            "target_name": target_name,
            "back_url": "/contacts",
            "active_tab": "contacts",
        },
    )
