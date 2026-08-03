from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_bridge, get_db, templates

router = APIRouter(prefix="/contacts", tags=["contacts"])

# Photo upload -- see db.py's contacts.photo_b64/photo_type columns and
# vcard_rows.py for how this round-trips through the vCard PHOTO property.
# Capped at 5MB and restricted to a fixed content-type allowlist rather
# than trusting the browser-supplied filename extension -- this app has no
# auth (see webapp/README.md's "Known gaps"), so anything reachable by an
# unauthenticated POST should validate what it's actually being handed
# before it goes anywhere near disk/Radicale, not just accept<->reject
# based on the client's own claims about the file. No resizing/
# transcoding (would need Pillow, a new dependency) -- the size cap is the
# only guard against an oversized upload bloating the vCard.
_MAX_PHOTO_BYTES = 5 * 1024 * 1024
_CONTENT_TYPE_TO_VCARD_TYPE = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/gif": "GIF",
    "image/webp": "WEBP",
}


async def _read_photo(photo: UploadFile | None) -> tuple[str, str] | None:
    """Returns (base64_data, vcard_type) if a real file was uploaded, or
    None if the field was left empty (FastAPI still hands back an
    UploadFile with an empty filename for an unfilled `<input type=file>`,
    not None -- checking `.filename` is what actually distinguishes "no
    file chosen" from "a file was chosen")."""
    if photo is None or not photo.filename:
        return None
    vcard_type = _CONTENT_TYPE_TO_VCARD_TYPE.get((photo.content_type or "").lower())
    if vcard_type is None:
        raise HTTPException(400, f"Unsupported photo type '{photo.content_type}' -- use JPEG, PNG, GIF, or WEBP.")
    data = await photo.read()
    if len(data) > _MAX_PHOTO_BYTES:
        raise HTTPException(400, "Photo is too large (max 5MB).")
    return base64.b64encode(data).decode("ascii"), vcard_type


def _tags_list(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


@router.get("")
def list_contacts(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    view: str | None = None,  # "active" (default) or "archived"
    conn=Depends(get_db),
):
    # "active" is the default view; "archived" shows only Archived book contacts.
    show_archived = view == "archived"
    addressbook_path = (
        db.ARCHIVED_ADDRESSBOOK_UID if show_archived else db.DEFAULT_ADDRESSBOOK_UID
    )
    contacts = db.list_contacts(conn, q=q, category=category, addressbook_path=addressbook_path)
    categories = db.list_contact_categories(conn)
    return templates.TemplateResponse(
        "contacts_list.html",
        {
            "request": request,
            "active_tab": "contacts",
            "settings_tab": "contacts",
            "contacts": contacts,
            "categories": categories,
            "q": q or "",
            "active_category": category or "",
            "view": "archived" if show_archived else "active",
        },
    )


@router.get("/new")
def new_contact_form(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "contact_form.html",
        {
            "request": request,
            "active_tab": "contacts",
            "contact": None,
            "tag_names": db.list_tag_names_in_use(conn),
        },
    )


@router.post("")
async def create_contact(
    full_name: str = Form(...),
    org: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    photo_result = await _read_photo(photo)
    photo_b64, photo_type = photo_result if photo_result else (None, None)
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "uid": str(uuid.uuid4()),
        "full_name": full_name,
        "org": org or None,
        "phone": phone or None,
        "email": email or None,
        "address": address or None,
        "category": category or None,
        "tags": _tags_list(tags),
        "notes": notes or None,
        "addressbook_path": db.DEFAULT_ADDRESSBOOK_UID,
        "photo_b64": photo_b64,
        "photo_type": photo_type,
        "created_at": now,
        "updated_at": now,
    }
    saved = bridge.save_contact_row(row)
    db.upsert_contact(conn, saved)
    db.ensure_tags_registered(conn, row["tags"])
    return RedirectResponse(url="/contacts", status_code=303)


@router.get("/{uid}")
def contact_detail(uid: str, request: Request, conn=Depends(get_db)):
    contact = db.get_contact(conn, uid)
    addressbook = db.get_addressbook(conn, contact["addressbook_path"]) if contact and contact.get("addressbook_path") else None
    is_archived = (
        contact["addressbook_path"] == db.ARCHIVED_ADDRESSBOOK_UID
        if contact
        else False
    )
    return templates.TemplateResponse(
        "contact_detail.html",
        {
            "request": request,
            "active_tab": "contacts",
            "contact": contact,
            "addressbook": addressbook,
            "is_archived": is_archived,
        },
    )


@router.get("/{uid}/edit")
def edit_contact_form(uid: str, request: Request, conn=Depends(get_db)):
    contact = db.get_contact(conn, uid)
    return templates.TemplateResponse(
        "contact_form.html",
        {
            "request": request,
            "active_tab": "contacts",
            "contact": contact,
            "tag_names": db.list_tag_names_in_use(conn),
        },
    )


@router.post("/{uid}")
async def update_contact(
    uid: str,
    full_name: str = Form(...),
    org: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    remove_photo: str = Form(""),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    existing = db.get_contact(conn, uid) or {}
    # Keep the contact in whatever book it's currently in (Active or
    # Archived); use the dedicated /archive and /unarchive endpoints to
    # move between them.  The old form-field-based addressbook_path move
    # is gone -- with only two books, archive/unarchive are explicit
    # single-click actions, not a dropdown in the edit form.
    current_addressbook = existing.get("addressbook_path") or db.DEFAULT_ADDRESSBOOK_UID
    row = dict(existing)
    row.update(
        {
            "uid": uid,
            "full_name": full_name,
            "org": org or None,
            "phone": phone or None,
            "email": email or None,
            "address": address or None,
            "category": category or None,
            "tags": _tags_list(tags),
            "notes": notes or None,
            "addressbook_path": current_addressbook,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if remove_photo:
        row["photo_b64"] = None
        row["photo_type"] = None
    else:
        photo_result = await _read_photo(photo)
        if photo_result:
            row["photo_b64"], row["photo_type"] = photo_result
        # else: no new file chosen -- row already carries the existing
        # photo_b64/photo_type through from `dict(existing)` above.
    saved = bridge.save_contact_row(row)
    db.upsert_contact(conn, saved)
    db.ensure_tags_registered(conn, row["tags"])
    return RedirectResponse(url=f"/contacts/{uid}", status_code=303)


@router.post("/{uid}/archive")
def archive_contact(uid: str, bridge=Depends(get_bridge), conn=Depends(get_db)):
    """Move a contact from Active to Archived.

    This is a real CardDAV move: delete the vCard from 'contacts' and
    save it into 'contacts-archived', exactly how update_contact handled
    calendar/list moves before the two-addressbook simplification."""
    existing = db.get_contact(conn, uid)
    if not existing:
        return RedirectResponse(url="/contacts", status_code=303)
    old_addressbook = existing.get("addressbook_path") or db.DEFAULT_ADDRESSBOOK_UID
    if old_addressbook == db.ARCHIVED_ADDRESSBOOK_UID:
        # Already archived -- nothing to do.
        return RedirectResponse(url=f"/contacts/{uid}", status_code=303)
    row = dict(existing)
    row["addressbook_path"] = db.ARCHIVED_ADDRESSBOOK_UID
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    bridge.delete_contact(uid, old_addressbook)
    saved = bridge.save_contact_row(row)
    db.upsert_contact(conn, saved)
    return RedirectResponse(url=f"/contacts/{uid}", status_code=303)


@router.post("/{uid}/unarchive")
def unarchive_contact(uid: str, bridge=Depends(get_bridge), conn=Depends(get_db)):
    """Move a contact from Archived back to Active."""
    existing = db.get_contact(conn, uid)
    if not existing:
        return RedirectResponse(url="/contacts", status_code=303)
    old_addressbook = existing.get("addressbook_path") or db.DEFAULT_ADDRESSBOOK_UID
    if old_addressbook == db.DEFAULT_ADDRESSBOOK_UID:
        # Already active -- nothing to do.
        return RedirectResponse(url=f"/contacts/{uid}", status_code=303)
    row = dict(existing)
    row["addressbook_path"] = db.DEFAULT_ADDRESSBOOK_UID
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    bridge.delete_contact(uid, old_addressbook)
    saved = bridge.save_contact_row(row)
    db.upsert_contact(conn, saved)
    return RedirectResponse(url=f"/contacts/{uid}", status_code=303)


@router.post("/{uid}/delete")
def delete_contact(uid: str, bridge=Depends(get_bridge), conn=Depends(get_db)):
    existing = db.get_contact(conn, uid)
    addressbook_path = (existing or {}).get("addressbook_path") or db.DEFAULT_ADDRESSBOOK_UID
    bridge.delete_contact(uid, addressbook_path)
    db.delete_contact(conn, uid)
    return RedirectResponse(url="/contacts", status_code=303)
