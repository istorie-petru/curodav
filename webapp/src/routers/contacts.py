from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_db, templates
from . import dashboard as dashboard_router

router = APIRouter(prefix="/contacts", tags=["contacts"])

# Phase 1 (label-space rework, 2026-08-06) dropped the two-addressbook
# model (Active/Archived as real CardDAV collections) along with
# `addressbooks`/`addressbook_path` entirely, replacing "archived" with a
# plain `Archived` tag. 2026-08-07: that tag-based Active/Archived split
# is gone too, per explicit instruction -- Contacts has no special
# "archived" state at all now, only labels, same as every other object
# type. If you want to mark a contact as archived, put a label on it;
# nothing in this router treats any particular label name specially.

# Photo upload -- see db.py's contacts.photo_b64/photo_type columns and
# vcard_rows.py for how this round-trips through the vCard PHOTO property.
# Capped at 5MB and restricted to a fixed content-type allowlist rather
# than trusting the browser-supplied filename extension -- this app has no
# auth (see webapp/README.md's "Known gaps"), so anything reachable by an
# unauthenticated POST should validate what it's actually being handed
# before it goes anywhere near disk, not just accept<->reject based on the
# client's own claims about the file. No resizing/transcoding (would need
# Pillow, a new dependency) -- the size cap is the only guard against an
# oversized upload bloating the vCard.
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


def _phone_email_list(types: list[str], values: list[str]) -> list[dict]:
    """Zips a create/edit form's parallel `*_type[]`/`*_value[]` arrays
    into the {"type", "value"} shape db.set_contact_phones/
    set_contact_emails expects. A blank type (a row where the browser
    submitted the field but nothing was picked -- shouldn't normally
    happen with a `<select>` that always has a value, but a hand-built
    POST could) falls back to "Other", same default the legacy-column
    migration uses. Blank values are left in -- db.set_contact_phones/
    set_contact_emails already drop them, same place every other blank-row
    filtering happens for this feature."""
    return [
        {"type": (t or "").strip() or "Other", "value": v}
        for t, v in zip(types, values)
    ]


@router.get("")
def list_contacts(
    request: Request,
    q: str | None = None,
    tag: str | None = None,
    conn=Depends(get_db),
):
    contacts = db.list_contacts(conn, q=q)
    # Saved tag filter (Phase 7 rework; Phase 5 label-space rework --
    # this is now the *only* grouping/filtering mechanism for contacts,
    # `category` is gone) -- `?tag=` matches contacts.tags
    # case-insensitively (a tag written both "University" and "university"
    # is one filter), same matching the project People section uses.
    active_tag = tag.lower() if tag else ""
    if active_tag:
        contacts = [
            c for c in contacts
            if any(t.lower() == active_tag for t in c.get("tags") or [])
        ]
    return templates.TemplateResponse(
        "contacts_list.html",
        {
            "request": request,
            "active_tab": "contacts",
            "contacts": contacts,
            "q": q or "",
            "contact_tags": db.list_contact_tag_names(conn),
            "active_tag": active_tag,
        },
    )


@router.get("/new")
def new_contact_form(request: Request, conn=Depends(get_db)):
    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "contact_form.html",
        {
            "request": request,
            "active_tab": "contacts",
            "contact": None,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            "phone_types": db.CONTACT_PHONE_TYPES,
            "email_types": db.CONTACT_EMAIL_TYPES,
        },
    )


@router.post("")
async def create_contact(
    full_name: str = Form(...),
    title: str = Form(""),
    org: str = Form(""),
    phone_type: list[str] = Form([]),
    phone_value: list[str] = Form([]),
    email_type: list[str] = Form([]),
    email_value: list[str] = Form([]),
    address: str = Form(""),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    conn=Depends(get_db),
):
    tags = dashboard_router._combine_tags(tags, tags_labels)
    photo_result = await _read_photo(photo)
    photo_b64, photo_type = photo_result if photo_result else (None, None)
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "uid": str(uuid.uuid4()),
        "full_name": full_name,
        "title": title if title and title.strip().lower() not in ("none", "nothing") else None,
        "org": org if org and org.strip().lower() not in ("none", "nothing") else None,
        # Contacts field parity slice 2 of 6 -- phone/email are multi-value
        # now (contact_phones/contact_emails), submitted as parallel
        # phone_type[]/phone_value[] (email_type[]/email_value[]) form
        # arrays, same `list[str] = Form([])` shape `tags_labels` already
        # uses on this router -- one Save button, no separate per-row
        # endpoints (see plans/STATE.md's slice entry for the full
        # reasoning). The old flat `phone`/`email` columns are no longer
        # written here at all (db.py's contacts CREATE TABLE comment).
        "phones": _phone_email_list(phone_type, phone_value),
        "emails": _phone_email_list(email_type, email_value),
        "address": address if address and address.strip().lower() not in ("none", "nothing") else None,
        "tags": _tags_list(tags),
        "notes": notes if notes and notes.strip().lower() not in ("none", "nothing") else None,
        "photo_b64": photo_b64,
        "photo_type": photo_type,
        "created_at": now,
        "updated_at": now,
    }
    db.upsert_contact(conn, row)
    return RedirectResponse(url="/contacts", status_code=303)


@router.get("/{uid}")
def contact_detail(uid: str, request: Request, conn=Depends(get_db)):
    contact = db.get_contact(conn, uid)
    return templates.TemplateResponse(
        "contact_detail.html",
        {
            "request": request,
            "active_tab": "contacts",
            "contact": contact,
        },
    )


@router.get("/{uid}/edit")
def edit_contact_form(uid: str, request: Request, conn=Depends(get_db)):
    contact = db.get_contact(conn, uid)
    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "contact_form.html",
        {
            "request": request,
            "active_tab": "contacts",
            "contact": contact,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            "phone_types": db.CONTACT_PHONE_TYPES,
            "email_types": db.CONTACT_EMAIL_TYPES,
        },
    )


@router.post("/{uid}")
async def update_contact(
    uid: str,
    full_name: str = Form(...),
    title: str = Form(""),
    org: str = Form(""),
    phone_type: list[str] = Form([]),
    phone_value: list[str] = Form([]),
    email_type: list[str] = Form([]),
    email_value: list[str] = Form([]),
    address: str = Form(""),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    remove_photo: str = Form(""),
    conn=Depends(get_db),
):
    tags = dashboard_router._combine_tags(tags, tags_labels)
    existing = db.get_contact(conn, uid) or {}
    row = dict(existing)
    row.update(
        {
            "uid": uid,
            "full_name": full_name,
            "title": title if title and title.strip().lower() not in ("none", "nothing") else None,
            "org": org if org and org.strip().lower() not in ("none", "nothing") else None,
            # Same multi-value replace-on-save as create_contact above --
            # the submitted arrays are the full, ordered set, so this
            # always overwrites `existing`'s phones/emails rather than
            # merging with them (`db.upsert_contact` -> `set_contact_
            # phones`/`set_contact_emails`, a full delete-then-reinsert).
            "phones": _phone_email_list(phone_type, phone_value),
            "emails": _phone_email_list(email_type, email_value),
            "address": address if address and address.strip().lower() not in ("none", "nothing") else None,
            "tags": _tags_list(tags),
            "notes": notes if notes and notes.strip().lower() not in ("none", "nothing") else None,
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
    db.upsert_contact(conn, row)
    return RedirectResponse(url=f"/contacts/{uid}", status_code=303)


@router.post("/{uid}/delete")
def delete_contact(uid: str, conn=Depends(get_db)):
    db.delete_contact(conn, uid)
    return RedirectResponse(url="/contacts", status_code=303)
