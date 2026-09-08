from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import db
from ..deps import get_db, respond, templates
from ..image_sniff import sniff_image_type
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
    # 2026-09-07 fix (flagged in an earlier audit): `vcard_type` above only
    # reflects the browser's own Content-Type claim -- confirm the bytes
    # actually are a real image before they go anywhere near a vCard,
    # using whatever the bytes actually are rather than trusting the
    # (possibly spoofed) header any further.
    sniffed = sniff_image_type(data)
    if sniffed is None:
        raise HTTPException(400, "That file doesn't look like a real JPEG, PNG, GIF, or WEBP image.")
    return base64.b64encode(data).decode("ascii"), sniffed.upper()


def _attach_photo_url(contact: dict) -> dict:
    """Every place this router hands a contact dict to a template that
    might render its avatar (deps.py's avatar() global) attaches
    `photo_url` here first (2026-08-29, direct request: "better cache
    these images") -- a real, `?v=`-versioned URL (contact_photo_image
    below) that avatar() prefers over embedding the photo inline as a
    `data:` URI. A contact with no photo is untouched (photo_url stays
    unset, avatar() falls through to the initials fallback)."""
    if contact.get("photo_b64"):
        contact["photo_url"] = f"/contacts/{contact['uid']}/photo?v={contact.get('photo_version') or ''}"
    return contact


def _tags_list(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


def _parse_birthday_field(birthday: str) -> str | None:
    """Contacts field parity slice 4 of 6 -- validates a create/edit form's
    raw `birthday` text against db.parse_contact_birthday's two accepted
    shapes (full "YYYY-MM-DD" or year-less "--MM-DD"), same "reject with a
    clear 400 rather than silently storing garbage" convention this app's
    other plain-form validation (e.g. single-project-per-task) already
    uses. A blank field is "no birthday," not an error -- same as every
    other optional contact field on this router."""
    v = (birthday or "").strip()
    if not v:
        return None
    try:
        return db.parse_contact_birthday(v)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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


def _website_list(types: list[str], urls: list[str]) -> list[dict]:
    """Same zip as `_phone_email_list` (parallel `website_type[]`/
    `website_url[]` form arrays into db.set_contact_websites' {"type",
    "url"} shape) -- kept as a separate function rather than a shared
    generic helper because the value key differs (`url`, not `value` --
    db.py's contact_websites column naming choice)."""
    return [
        {"type": (t or "").strip() or "Other", "url": u}
        for t, u in zip(types, urls)
    ]


def _address_list(
    types: list[str], po_boxes: list[str], extendeds: list[str], streets: list[str],
    cities: list[str], regions: list[str], postal_codes: list[str], countries: list[str],
) -> list[dict]:
    """Contacts field parity slice 5 of 6 -- zips a create/edit form's eight
    parallel `address_*[]` arrays into db.set_contact_addresses' per-row
    shape. Unlike `_phone_email_list`/`_website_list` (one value field), a
    structured address has seven -- `zip` over eight equal-length lists
    (the form always submits every field for every row, even ones left
    blank, since they're all part of the same repeatable-row template) is
    still the simplest correct way to reconstruct each row; db.
    set_contact_addresses itself is what actually drops an all-blank row."""
    return [
        {
            "type": (t or "").strip() or "Other",
            "po_box": po_box, "extended": extended, "street": street,
            "city": city, "region": region, "postal_code": postal_code, "country": country,
        }
        for t, po_box, extended, street, city, region, postal_code, country in zip(
            types, po_boxes, extendeds, streets, cities, regions, postal_codes, countries
        )
    ]


def _social_profile_list(types: list[str], values: list[str]) -> list[dict]:
    """Contacts field parity slice 6 of 6 -- same zip shape as
    `_phone_email_list`, for the `social_type[]`/`social_value[]` form
    arrays into db.set_contact_social_profiles' {"type", "value"} shape."""
    return [
        {"type": (t or "").strip() or "Other", "value": v}
        for t, v in zip(types, values)
    ]


def _contacts_list_context(conn, request: Request, q: str | None, tag: str | None) -> dict:
    contacts = [_attach_photo_url(c) for c in db.list_contacts(conn, q=q)]
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
    return {
        "request": request,
        "active_tab": "contacts",
        "contacts": contacts,
        "q": q or "",
        "contact_tags": db.list_contact_tag_names(conn),
        "active_tag": active_tag,
    }


@router.get("")
def list_contacts(
    request: Request,
    q: str | None = None,
    tag: str | None = None,
    conn=Depends(get_db),
):
    return templates.TemplateResponse(
        "contacts_list.html",
        _contacts_list_context(conn, request, q, tag),
    )


@router.get("/regions")
def contacts_regions(
    request: Request,
    region: str = "list",
    q: str | None = None,
    tag: str | None = None,
    conn=Depends(get_db),
):
    """Async-CRUD region fragment (features/async-crud.md): renders the
    #contacts-body div shared with contacts_list.html so refreshRegion() can
    swap it in place after a contact mutation instead of a full reload.
    Takes the same query params as list_contacts so the refreshed region
    honors the active search/label filter."""
    if region != "list":
        return JSONResponse({"error": f"unknown region '{region}'"}, status_code=400)
    ctx = _contacts_list_context(conn, request, q, tag)
    html = templates.env.get_template("_contacts_body.html").render(ctx)
    return HTMLResponse(html)


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
            "website_types": db.CONTACT_WEBSITE_TYPES,
            "address_types": db.CONTACT_ADDRESS_TYPES,
            "social_types": db.CONTACT_SOCIAL_TYPES,
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
    website_type: list[str] = Form([]),
    website_url: list[str] = Form([]),
    address_type: list[str] = Form([]),
    address_po_box: list[str] = Form([]),
    address_extended: list[str] = Form([]),
    address_street: list[str] = Form([]),
    address_city: list[str] = Form([]),
    address_region: list[str] = Form([]),
    address_postal_code: list[str] = Form([]),
    address_country: list[str] = Form([]),
    social_type: list[str] = Form([]),
    social_value: list[str] = Form([]),
    birthday: str = Form(""),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    tags = dashboard_router._combine_tags(tags, tags_labels)
    birthday_value = _parse_birthday_field(birthday)
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
        # Contacts field parity slice 3 of 6 -- Website, same multi-value
        # form-array shape as phone/email above (website_type[]/
        # website_url[]; the value key is "url" to match db.py's
        # contact_websites column naming, not "value").
        "websites": _website_list(website_type, website_url),
        # Contacts field parity slice 5 of 6 -- Address is now the full
        # structured, multi-value vCard ADR (contact_addresses), submitted
        # as eight parallel address_*[] form arrays (see _address_list).
        # The old flat `address` column is no longer written here at all,
        # same "legacy column frozen, not kept live" convention phone/email
        # already established.
        "addresses": _address_list(
            address_type, address_po_box, address_extended, address_street,
            address_city, address_region, address_postal_code, address_country,
        ),
        # Contacts field parity slice 6 of 6 -- Social network
        # (contact_social_profiles), same multi-value form-array shape as
        # phone/email/website above.
        "social_profiles": _social_profile_list(social_type, social_value),
        # Contacts field parity slice 4 of 6 -- Birthday, single-value (no
        # form-array shape like phone/email/website above -- a contact has
        # at most one). `_parse_birthday_field` already validated/
        # normalized it (or raised a 400) before this dict is built.
        "birthday": birthday_value,
        "tags": _tags_list(tags),
        "notes": notes if notes and notes.strip().lower() not in ("none", "nothing") else None,
        "photo_b64": photo_b64,
        "photo_type": photo_type,
        "created_at": now,
        "updated_at": now,
    }
    db.upsert_contact(conn, row)
    return respond(x_requested_with, "/contacts", status_code=201, uid=row["uid"])


@router.get("/{uid}")
def contact_detail(uid: str, request: Request, conn=Depends(get_db)):
    contact = db.get_contact(conn, uid)
    if contact:
        _attach_photo_url(contact)
    return templates.TemplateResponse(
        "contact_detail.html",
        {
            "request": request,
            "active_tab": "contacts",
            "contact": contact,
            # 2026-09-03 (direct request, view-modal cover banner baseline)
            # -- same resolved label/Project/Space banner db.banner_for_task
            # already gave tasks, generalized to db.banner_for_object.
            "banner": db.banner_for_object(conn, "contact", contact) if contact else None,
        },
    )


@router.get("/{uid}/photo")
def contact_photo_image(uid: str, conn=Depends(get_db)):
    """Serves a contact's decoded photo bytes for `<img src>` (2026-08-29,
    direct request: "better cache these images"). Exact mirror of
    routers/banners.py's banner_image / routers/settings.py's
    profile_photo_image -- same problem (a contact's photo used to be
    embedded as an inline `data:` URI, deps.py's avatar() global, riding
    along in the HTML of every contact list row that has one, not just
    the one contact being viewed), same fix (a real, separately cacheable
    request), same immutable Cache-Control safety argument (the URL's own
    `?v=` -- contacts.photo_version -- changes whenever the photo does)."""
    contact = db.get_contact(conn, uid)
    if not contact or not contact.get("photo_b64"):
        raise HTTPException(404)
    try:
        data = base64.b64decode(contact["photo_b64"], validate=True)
    except (ValueError, TypeError):
        raise HTTPException(404)
    image_type = str(contact.get("photo_type") or "").lower()
    if image_type not in ("jpeg", "png", "gif", "webp"):
        image_type = "jpeg"
    return Response(
        content=data,
        media_type=f"image/{image_type}",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Encoding": "identity",
        },
    )


@router.get("/{uid}/edit")
def edit_contact_form(uid: str, request: Request, conn=Depends(get_db)):
    contact = db.get_contact(conn, uid)
    if contact:
        _attach_photo_url(contact)
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
            "website_types": db.CONTACT_WEBSITE_TYPES,
            "address_types": db.CONTACT_ADDRESS_TYPES,
            "social_types": db.CONTACT_SOCIAL_TYPES,
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
    website_type: list[str] = Form([]),
    website_url: list[str] = Form([]),
    address_type: list[str] = Form([]),
    address_po_box: list[str] = Form([]),
    address_extended: list[str] = Form([]),
    address_street: list[str] = Form([]),
    address_city: list[str] = Form([]),
    address_region: list[str] = Form([]),
    address_postal_code: list[str] = Form([]),
    address_country: list[str] = Form([]),
    social_type: list[str] = Form([]),
    social_value: list[str] = Form([]),
    birthday: str = Form(""),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    remove_photo: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    tags = dashboard_router._combine_tags(tags, tags_labels)
    birthday_value = _parse_birthday_field(birthday)
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
            "websites": _website_list(website_type, website_url),
            "addresses": _address_list(
                address_type, address_po_box, address_extended, address_street,
                address_city, address_region, address_postal_code, address_country,
            ),
            "social_profiles": _social_profile_list(social_type, social_value),
            "birthday": birthday_value,
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
    return respond(x_requested_with, f"/contacts/{uid}")


@router.post("/{uid}/delete")
def delete_contact(
    uid: str,
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    db.delete_contact(conn, uid)
    return respond(x_requested_with, "/contacts")
