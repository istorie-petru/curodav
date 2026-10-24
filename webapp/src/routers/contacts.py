from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import clock, db
from .. import tags as tag_store
from ..deps import get_db, respond, templates
from ..image_convert import to_webp, write_cached_webp
from ..image_sniff import sniff_image_type

router = APIRouter(prefix="/contacts", tags=["contacts"])


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
    sniffed = sniff_image_type(data)
    if sniffed is None:
        raise HTTPException(400, "That file doesn't look like a real JPEG, PNG, GIF, or WEBP image.")
    return base64.b64encode(data).decode("ascii"), sniffed.upper()


def _attach_photo_url(contact: dict) -> dict:
    """Every place this router hands a contact dict to a template that
        might render its avatar (deps.py's avatar() global) attaches
        `photo_url` here first -- a real, `?v=`-versioned URL (contact_photo_image
        below) that avatar() prefers over embedding the photo inline as a
        `data:` URI. A contact with no photo is untouched (photo_url stays
        unset, avatar() falls through to the initials fallback).
    """
    if contact.get("photo_b64"):
        contact["photo_url"] = f"/contacts/{contact['uid']}/photo?v={contact.get('photo_version') or ''}"
    return contact


def _tags_list(tags: str) -> list[str]:
    """Parses the legacy comma-separated `tags` fallback field (no
        template posts it any more, but every sibling router keeps this
        escape hatch).
    """
    parts = [t.strip() for t in tags.split(",") if t.strip()]
    return parts[:1]


def _resolve_contact_label(tags: str, tags_labels: list[str], tags_labels_new: str) -> list[str]:
    """The edit form's Label field (_contact_form_fields.html,
    ms_mode="single" + ms_allow_new) resolves to at most one tag --
    same "typed name always wins over the picked radio" pattern
    settings.py's `_resolve_calendar_name` already uses for its own
    single-select "pick or create" field (see that function's own
    comment for why the typed-new and picked-existing values need
    distinct form field names rather than sharing one). `__no_label__`
    (the form's explicit "No label" sentinel, same one Labels *filter*
    pickers already use) is never a real label name. Falls back to the
    legacy `tags` fallback field (`_tags_list`) if neither of those
    supplied anything, same defensive layering create_contact/
    update_contact had before this single-select rework.

    `tags_labels`/`tags_labels_new` are defensively coerced -- same
    reasoning `dashboard._combine_tags`'s own docstring gives: plenty of
    pre-existing tests call create_contact/update_contact as plain Python
    functions, bypassing FastAPI's request parsing, without passing
    these two newer parameters at all, so their `Form(...)` defaults (a
    FastAPI marker object, not a real empty list/string, outside of real
    request handling) would otherwise blow up every one of those calls."""
    if not isinstance(tags_labels, list):
        tags_labels = []
    if not isinstance(tags_labels_new, str):
        tags_labels_new = ""
    new = tags_labels_new.strip()
    if new:
        return [new]
    for t in tags_labels:
        if t and t.strip() and t.strip() != "__no_label__":
            return [t.strip()]
    return _tags_list(tags)


def _with_contact_project(conn, tags: list[str], project, project_field) -> list[str]:
    """A contact carries one label and one project. The Project dropdown is the only authority
    over the project, so a project name typed or picked as the label is dropped."""
    if not (isinstance(project_field, str) and project_field == "1"):
        return tags
    project = project if isinstance(project, str) else ""
    return db.apply_project_choice(conn, tags, project)


def _parse_birthday_field(birthday: str) -> str | None:
    """single-project-per-task) already
        uses. A blank field is "no birthday," not an error -- same as every
        other optional contact field on this router.
    """
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
    """Unlike `_phone_email_list`/`_website_list` (one value field), a
        structured address has seven -- `zip` over eight equal-length lists
        (the form always submits every field for every row, even ones left
        blank, since they're all part of the same repeatable-row template) is
        still the simplest correct way to reconstruct each row; db. set_contact_addresses itself is what actually drops an all-blank row.
    """
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
    return [
        {"type": (t or "").strip() or "Other", "value": v}
        for t, v in zip(types, values)
    ]


def _contacts_list_context(
    conn, request: Request, q: str | None, tags: list[str], filtered: bool, show: str = ""
) -> dict:
    show = show if show in ("archived", "all") else ""
    show_archived = bool(show)
    contacts = [_attach_photo_url(c) for c in db.list_contacts(conn, q=q, include_archived=show_archived)]
    if show == "archived":
        contacts = [c for c in contacts if c.get("archived_at")]
    total_before_filtering = len(contacts)
    all_tags = db.list_contact_tag_names(conn)
    filter_items = tag_store.filter_items(conn, "contact", db.label_filter_items(conn, all_tags, lowercase_values=True), lowercase_values=True)
    if filtered:
        selected = {t.lower() for t in tags}
        matches = tag_store.matcher(conn, "contact", selected)
        # Explicit pick -- OR-inclusion, same as the old single-select
        # filter generalized to multiple values: show a contact carrying
        # at least one checked label. An empty selection (every checkbox
        # deliberately unchecked) is respected literally -- nothing
        # matches, not "no filter."
        contacts = [c for c in contacts if matches(c)]
    else:
        # Untouched page load -- every real label counts as implicitly
        # checked (no more Archived-name suppression needed here, see
        # above), same as every other page's own label-filter default.
        selected = {i["value"] for i in filter_items}
    return {
        "request": request,
        "active_tab": "contacts",
        "contacts": contacts,
        "contact_groups": _group_contacts_by_label(contacts, {cfg["name"] for cfg in db.list_project_labels(conn)}),
        "q": q or "",
        "contact_tags": all_tags,
        "contact_filter_items": filter_items,
        "active_tags": selected,
        "show_archived": show_archived,
        "show": show,
        # Whether the list actually got narrowed down right now -- true
        # for an explicit pick or a search -- so _contacts_body.html's
        # empty state reads "No contacts match" (not "No contacts yet")
        # whenever that's the real reason the list is empty.
        "contacts_filter_active": bool(q) or filtered or len(contacts) != total_before_filtering,
    }


def _group_contacts_by_label(contacts: list[dict], project_names: set[str] | None = None) -> list[dict]:
    """same pattern Settings > Projects already uses for its
        label groups") -- one `{"name": label, "contacts": [...]}` per label
        actually in use, sorted alphabetically (ungrouped last, same
        "ungrouped last" convention `routers/labels.py::_labels_context`
        established), each a real Jinja bucket for _contacts_body.html's
        section headings. A contact carries at most one label (item 16 --
        "Contacts should only allow one label"), so this is a clean partition,
        not a fan-out; within a group/the ungrouped bucket, contacts keep
        whatever order `db.list_contacts` already returned them in (no new
        sort -- out of this slice's scope).
    """
    project_names = project_names or set()
    by_label: dict[str, list[dict]] = {}
    unlabeled: list[dict] = []
    for c in contacts:
        tag = next((t for t in (c.get("tags") or []) if t not in project_names), None)
        if tag:
            by_label.setdefault(tag, []).append(c)
        else:
            unlabeled.append(c)
    groups = [{"name": name, "contacts": by_label[name]} for name in sorted(by_label, key=str.lower)]
    if unlabeled:
        groups.append({"name": None, "contacts": unlabeled})
    return groups


@router.get("")
def list_contacts(
    request: Request,
    q: str | None = None,
    tag: list[str] = Query([]),
    archived: str = "",
    show: str = "",
    conn=Depends(get_db),
):
    filtered = "contacts_filtered" in request.query_params
    return templates.TemplateResponse(
        "contacts_list.html",
        _contacts_list_context(conn, request, q, tag, filtered, show="all" if archived == "1" else show),
    )


@router.get("/bulk-edit-modal")
def bulk_edit_modal(uids: str, request: Request, conn=Depends(get_db)):
    """Bulk-select "Edit": one modal that sets the same value on every selected contact."""
    labels = [(i["name"], i["name"]) for i in tag_store.picker(conn, "contact", "", [])["items"]]
    fields = [
        {"name": "remove_tag", "label": "Remove tag", "kind": "select", "options": labels},
        {"name": "add_tag", "label": "Set tag", "kind": "select", "options": labels},
        {"name": "org", "label": "Organization", "kind": "text"},
    ]
    return templates.TemplateResponse(
        "bulk_edit_modal.html",
        {"request": request, "uids": [u for u in uids.split(",") if u], "noun": "contact", "fields": fields,
         "post_url": "/contacts/bulk-edit", "change_type": "contact", "back_url": "/contacts"},
    )


@router.post("/bulk-edit")
def bulk_edit(
    uids: list[str] = Form([]),
    add_tag: str = Form(""),
    remove_tag: str = Form(""),
    org: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    for uid in uids:
        row = db.get_contact(conn, uid)
        if row is None:
            continue
        if org.strip():
            row["org"] = org.strip()
        if add_tag or remove_tag:  # a contact has one tag: the new one replaces it
            row["tags"] = sorted(tag_store.bulk_change(conn, "contact", uid, row.get("tags") or [], [add_tag], [remove_tag], single=True))
        row["updated_at"] = clock.now().isoformat()
        db.upsert_contact(conn, row)
    return respond(x_requested_with, "/contacts", count=len(uids))


@router.post("/bulk-delete")
async def bulk_delete_contacts(request: Request, conn=Depends(get_db)):
    """Bulk-select "Delete" bar (contacts_list.html/_contacts_body.html,
        static/bulk_select.js) -- same JSON endpoint shape as routers/
        settings.py's bulk_delete_holidays/bulk_delete_time_blocks: a plain
        loop over the same `db.delete_contact` each row's own detail-modal
        Delete already calls, no all-or-nothing rollback. Contacts was the one
        list left out when Labels/Holidays/Time blocks got this because its rows are a card-list, not a `<table>` --
        `_contacts_body.html` now wraps each row for a `.row-select` checkbox
        to attach to, same as every other bulk-select surface. Registered
        ahead of no conflicting route (contacts.py has no bare `POST /{uid}`
        that a literal `/bulk-delete` path could collide with), but kept next
        to list_contacts/contacts_regions for readability, same grouping as
        the other list-level routes.
    """
    payload = await request.json()
    uids = payload.get("uids") or []
    if not uids:
        return JSONResponse({"error": "no contacts selected"}, status_code=400)
    for uid in uids:
        db.delete_contact(conn, uid)
    return JSONResponse({"ok": True, "count": len(uids)})


@router.get("/regions")
def contacts_regions(
    request: Request,
    region: str = "list",
    q: str | None = None,
    tag: list[str] = Query([]),
    archived: str = "",
    show: str = "",
    conn=Depends(get_db),
):
    """Async-CRUD region fragment (features/async-crud.md): renders the
    #contacts-body div shared with contacts_list.html so refreshRegion() can
    swap it in place after a contact mutation instead of a full reload.
    Takes the same query params as list_contacts so the refreshed region
    honors the active search/label filter."""
    if region != "list":
        return JSONResponse({"error": f"unknown region '{region}'"}, status_code=400)
    filtered = "contacts_filtered" in request.query_params
    ctx = _contacts_list_context(conn, request, q, tag, filtered, show="all" if archived == "1" else show)
    html = templates.env.get_template("_contacts_body.html").render(ctx)
    return HTMLResponse(html)


@router.post("/{uid}/archive")
def archive_contact(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    """Item 19: archiving is fully reversible (a real
        `unarchive_contact` below), so this submits for real right away --
        static/app.js's `data-archive-undo` handler (the row's own kebab item,
        _contacts_body.html) offers a true Undo that calls `unarchive_contact`
        below, not a delayed/cancelable send like `data-delete-undo`'s.
    """
    db.archive_contact(conn, uid)
    return respond(x_requested_with, "/contacts")


@router.post("/{uid}/unarchive")
def unarchive_contact(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    db.unarchive_contact(conn, uid)
    return respond(x_requested_with, "/contacts")


@router.get("/new")
def new_contact_form(request: Request, conn=Depends(get_db)):
    tag_names = db.list_tag_names_in_use(conn)
    draft_uid = db.create_contact_draft(conn)
    return templates.TemplateResponse(
        "contact_form.html",
        {
            "request": request,
            "active_tab": "contacts",
            "contact": None,
            "draft_uid": draft_uid,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            **db.project_picker_context(conn),
            "phone_types": db.CONTACT_PHONE_TYPES,
            "email_types": db.CONTACT_EMAIL_TYPES,
            "website_types": db.CONTACT_WEBSITE_TYPES,
            "address_types": db.CONTACT_ADDRESS_TYPES,
            "social_types": db.CONTACT_SOCIAL_TYPES,
        },
    )


def _clean_optional(value: str) -> str | None:
    """Blank and the literal "None"/"Nothing" a form can echo back become no value."""
    return value if value and value.strip().lower() not in ("none", "nothing") else None


@router.post("")
async def create_contact(
    full_name: str = Form(...),
    pseudonym: str = Form(""),
    title: str = Form(""),
    role: str = Form(""),
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
    tags_labels_new: str = Form(""),
    item_tags: list[str] = Form([]),
    item_tags_field: str = Form(""),
    project: str = Form(""),
    project_field: str = Form(""),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    draft_uid: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    if item_tags_field == "1":
        tags_labels = tag_store.labels_of(conn, item_tags[:1])
    resolved_tags = _with_contact_project(conn, _resolve_contact_label(tags, tags_labels, tags_labels_new), project, project_field)
    birthday_value = _parse_birthday_field(birthday)
    photo_result = await _read_photo(photo)
    photo_b64, photo_type = photo_result if photo_result else (None, None)
    uid = str(uuid.uuid4())
    draft = db.get_contact(conn, draft_uid) if isinstance(draft_uid, str) and draft_uid else None
    if draft and draft.get("is_draft"):
        # Save turns the buffer contact into the real one: keep its uid and
        # photo, then drop the buffer row so the real one is written (and
        # synced) as a brand-new contact.
        uid = draft_uid
        if not photo_b64:
            photo_b64, photo_type = draft.get("photo_b64"), draft.get("photo_type")
        db.delete_contact(conn, draft_uid, record_server_write=False)
    now = clock.now().isoformat()
    row = {
        "uid": uid,
        "full_name": full_name,
        "pseudonym": _clean_optional(pseudonym),
        "title": _clean_optional(title),
        "role": _clean_optional(role),
        "org": org if org and org.strip().lower() not in ("none", "nothing") else None,
        "phones": _phone_email_list(phone_type, phone_value),
        "emails": _phone_email_list(email_type, email_value),
        "websites": _website_list(website_type, website_url),
        "addresses": _address_list(
            address_type, address_po_box, address_extended, address_street,
            address_city, address_region, address_postal_code, address_country,
        ),
        "social_profiles": _social_profile_list(social_type, social_value),
        "birthday": birthday_value,
        "tags": resolved_tags,
        "notes": notes if notes and notes.strip().lower() not in ("none", "nothing") else None,
        "photo_b64": photo_b64,
        "photo_type": photo_type,
        "created_at": now,
        "updated_at": now,
    }
    db.upsert_contact(conn, row)
    if item_tags_field == "1":
        tag_store.record(conn, "contact", uid, item_tags[:1])
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
            "banner": db.banner_for_object(conn, "contact", contact) if contact else None,
        },
    )


@router.get("/{uid}/photo")
def contact_photo_image(uid: str, request: Request, conn=Depends(get_db)):
    """Serves a contact's decoded photo bytes for `<img src>`. Exact mirror of
        routers/banners.py's banner_image / routers/settings.py's
        profile_photo_image -- same problem (a contact's photo used to be
        embedded as an inline `data:` URI, deps.py's avatar() global, riding
        along in the HTML of every contact list row that has one, not just
        the one contact being viewed), same fix (a real, separately cacheable
        request), same immutable Cache-Control safety argument (the URL's own
        `?v=` -- contacts.photo_version -- changes whenever the photo does).
    """
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

    cache_dir = request.app.state.settings.photo_cache_dir
    cache_name = f"{hashlib.sha256(data).hexdigest()[:16]}.webp"
    cache_path = cache_dir / cache_name
    if cache_path.exists():
        data, image_type = cache_path.read_bytes(), "webp"
    else:
        webp_data = to_webp(data)
        if webp_data is not None:
            write_cached_webp(cache_dir, cache_name, webp_data)
            data, image_type = webp_data, "webp"

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
            "draft_uid": uid if contact and contact.get("is_draft") else "",
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            **db.project_picker_context(conn),
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
    pseudonym: str = Form(""),
    title: str = Form(""),
    role: str = Form(""),
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
    tags_labels_new: str = Form(""),
    item_tags: list[str] = Form([]),
    item_tags_field: str = Form(""),
    project: str = Form(""),
    project_field: str = Form(""),
    notes: str = Form(""),
    photo: UploadFile | None = File(None),
    remove_photo: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    if item_tags_field == "1":
        tags_labels = tag_store.labels_of(conn, item_tags[:1])
    resolved_tags = _with_contact_project(conn, _resolve_contact_label(tags, tags_labels, tags_labels_new), project, project_field)
    birthday_value = _parse_birthday_field(birthday)
    existing = db.get_contact(conn, uid) or {}
    is_draft = bool(existing.get("is_draft"))
    row = dict(existing)
    row.update(
        {
            "uid": uid,
            "full_name": full_name,
            "pseudonym": _clean_optional(pseudonym),
            "title": _clean_optional(title),
            "role": _clean_optional(role),
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
            "tags": resolved_tags,
            "notes": notes if notes and notes.strip().lower() not in ("none", "nothing") else None,
            "updated_at": clock.now().isoformat(),
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
    db.upsert_contact(conn, row, record_server_write=not is_draft)
    if item_tags_field == "1":
        tag_store.record(conn, "contact", uid, item_tags[:1])
    return respond(x_requested_with, f"/contacts/{uid}")


@router.post("/{uid}/discard")
def discard_contact_draft(uid: str, conn=Depends(get_db)):
    """Closing or cancelling a new-contact form drops its buffer contact. A
    saved contact is never touched."""
    contact = db.get_contact(conn, uid)
    if contact and contact.get("is_draft"):
        db.delete_contact(conn, uid, record_server_write=False)
    return Response(status_code=204)


@router.get("/{uid}/photo/modal")
def contact_photo_modal(uid: str, request: Request, conn=Depends(get_db)):
    """The shared upload modal (upload_modal.html) for a contact's photo."""
    contact = db.get_contact(conn, uid)
    if not contact:
        raise HTTPException(404)
    draft = bool(contact.get("is_draft"))
    _attach_photo_url(contact)
    return templates.TemplateResponse(
        "upload_modal.html",
        {
            "request": request,
            "title": "Contact photo",
            "form_id": "contact-photo-upload-form",
            "upload_action": f"/contacts/{uid}/photo",
            "field_name": "photo",
            "input_class": "avatar-upload-input",
            "zone_label": "Choose or drop a photo",
            "preview_url": contact.get("photo_url") or "",
            "delete_url": f"/contacts/{uid}/photo/remove" if contact.get("photo_b64") else "",
            "delete_label": "Remove this photo?",
            "back_url": f"/contacts/{uid}/edit" if draft else f"/contacts/{uid}",
            "back_mode": "modal",
            "discard_url": f"/contacts/{uid}/discard" if draft else "",
        },
    )


@router.post("/{uid}/photo")
async def set_contact_photo(
    uid: str,
    photo: UploadFile | None = File(None),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    contact = db.get_contact(conn, uid)
    if not contact:
        raise HTTPException(404)
    result = await _read_photo(photo)
    if result:
        row = dict(contact)
        row["photo_b64"], row["photo_type"] = result
        row["updated_at"] = clock.now().isoformat()
        db.upsert_contact(conn, row, record_server_write=not contact.get("is_draft"))
    return respond(x_requested_with, f"/contacts/{uid}")


@router.post("/{uid}/photo/remove")
def remove_contact_photo(
    uid: str,
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    contact = db.get_contact(conn, uid)
    if not contact:
        raise HTTPException(404)
    row = dict(contact)
    row["photo_b64"] = None
    row["photo_type"] = None
    row["updated_at"] = clock.now().isoformat()
    db.upsert_contact(conn, row, record_server_write=not contact.get("is_draft"))
    return respond(x_requested_with, f"/contacts/{uid}")


@router.post("/{uid}/delete")
def delete_contact(
    uid: str,
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    db.delete_contact(conn, uid)
    return respond(x_requested_with, "/contacts")
