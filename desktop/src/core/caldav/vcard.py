"""Person <-> vCard (RFC 6350 / CardDAV) translation.

Same split as `ical.py`: standard vCard properties (FN, N, ORG, TEL, EMAIL,
ADR, CATEGORIES, NOTE, REV) are what a self-hosted Radicale/Baikal
CardDAV collection and any native Contacts app actually sync.
CommandCenter-only fields (icon, cover_path, sort_key, pinned,
workspace_id, and `PersonDetails.category`, which is our own single-value
classification and unrelated to vCard's multi-value CATEGORIES/tags) ride
along as `X-COMMANDCENTER-*` properties, ignored-not-rejected by compliant
clients per RFC 6350 §6.10.

Limitation worth stating plainly: `PersonDetails.photo_path` is a local
filesystem path, not portable to another device, so it is *not* mapped to
vCard's PHOTO property (which expects embedded/URI image data). It rides
as an X-property purely so our own client round-trips it; external clients
correctly see no photo unless this is revisited to embed actual image
bytes.
"""

from __future__ import annotations

from typing import Any

import vobject

from ..models import Object, PersonDetails

X_PREFIX = "x-commandcenter-"


def _set_x(card: vobject.base.Component, name: str, value: Any) -> None:
    if value is None or value == "" or value is False:
        return
    line = card.add(f"{X_PREFIX}{name}")
    line.value = str(value)


def _get_x(card: vobject.base.Component, name: str) -> str | None:
    lines = card.contents.get(f"{X_PREFIX}{name}")
    if not lines:
        return None
    return str(lines[0].value)


def to_vcard(obj: Object, details: PersonDetails) -> vobject.base.Component:
    card = vobject.vCard()
    card.add("version").value = "3.0"
    card.add("uid").value = obj.id
    card.add("fn").value = obj.title or ""

    name = card.add("n")
    name.value = vobject.vcard.Name(given=obj.title or "")

    if details.org:
        card.add("org").value = [details.org]
    if details.phone:
        card.add("tel").value = details.phone
    if details.email:
        card.add("email").value = details.email
    if details.address:
        card.add("adr").value = vobject.vcard.Address(street=details.address)
    if obj.tags:
        card.add("categories").value = list(obj.tags)
    if obj.description:
        card.add("note").value = obj.description
    if obj.updated_at:
        card.add("rev").value = obj.updated_at

    _set_x(card, "icon", obj.icon)
    _set_x(card, "cover-path", obj.cover_path)
    _set_x(card, "sort-key", obj.sort_key)
    _set_x(card, "pinned", obj.pinned)
    _set_x(card, "workspace-id", obj.workspace_id)
    _set_x(card, "status", obj.status)
    _set_x(card, "photo-path", details.photo_path)
    _set_x(card, "category", details.category)
    return card


def vcard_to_fields(card: vobject.base.Component) -> dict[str, Any]:
    """Standard-field updates recoverable from a vCard, for
    `merge.merge_standard_fields_into`. Only keys actually present are
    included, same contract as `ical.vtodo_to_fields`."""
    fields: dict[str, Any] = {}
    details: dict[str, Any] = {}

    if hasattr(card, "fn"):
        fields["title"] = str(card.fn.value)
    if hasattr(card, "note"):
        fields["description"] = str(card.note.value)
    if hasattr(card, "org"):
        org_val = card.org.value
        details["org"] = org_val[0] if isinstance(org_val, list) else str(org_val)
    if hasattr(card, "tel"):
        details["phone"] = str(card.tel.value)
    if hasattr(card, "email"):
        details["email"] = str(card.email.value)
    if hasattr(card, "adr"):
        adr = card.adr.value
        details["address"] = getattr(adr, "street", "") or str(adr)
    if hasattr(card, "categories"):
        cats = card.categories.value
        fields["tags"] = list(cats) if isinstance(cats, list) else [str(cats)]

    x_status = _get_x(card, "status")
    if x_status is not None:
        fields["status"] = x_status
    x_icon = _get_x(card, "icon")
    if x_icon is not None:
        fields["icon"] = x_icon
    x_cover = _get_x(card, "cover-path")
    if x_cover is not None:
        fields["cover_path"] = x_cover
    x_sort = _get_x(card, "sort-key")
    if x_sort is not None:
        fields["sort_key"] = x_sort
    x_pinned = _get_x(card, "pinned")
    if x_pinned is not None:
        fields["pinned"] = x_pinned == "True"
    x_workspace = _get_x(card, "workspace-id")
    if x_workspace is not None:
        fields["workspace_id"] = x_workspace
    x_photo = _get_x(card, "photo-path")
    if x_photo is not None:
        details["photo_path"] = x_photo
    x_category = _get_x(card, "category")
    if x_category is not None:
        details["category"] = x_category

    if details:
        fields["details"] = details
    return fields
