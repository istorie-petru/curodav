"""Flat dict row <-> vCard, for the web app's `contacts` table (db.py).
Same relationship to desktop/src/core/caldav/vcard.py as ical_rows.py has
to ical.py -- same field conventions, independent code, no X-COMMANDCENTER-*
properties since this app has no graph metadata to carry.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any

import vobject

# This app's Home/Work/Cell/Fax/Pager/Other vocabulary (db.
# CONTACT_PHONE_TYPES/CONTACT_EMAIL_TYPES) <-> vCard 3.0's real TYPE=
# tokens. "Other" intentionally has no entry -- see the module docstring
# for why it's the one type that gets no TYPE= param at all, in either
# direction.
_TYPE_TO_VCARD: dict[str, str] = {
    "Home": "HOME", "Work": "WORK", "Cell": "CELL", "Fax": "FAX", "Pager": "PAGER",
}
_VCARD_TO_TYPE: dict[str, str] = {v: k for k, v in _TYPE_TO_VCARD.items()}

_SOCIAL_TYPE_TO_VCARD: dict[str, str] = {
    "Twitter": "TWITTER", "Facebook": "FACEBOOK", "Instagram": "INSTAGRAM",
    "LinkedIn": "LINKEDIN", "Mastodon": "MASTODON", "GitHub": "GITHUB",
}
_VCARD_TO_SOCIAL_TYPE: dict[str, str] = {v: k for k, v in _SOCIAL_TYPE_TO_VCARD.items()}


def contact_row_to_vcard(row: dict[str, Any], name_field: str = "full_name") -> str:
    """`name_field` picks what FN carries: "full_name", or "pseudonym" when the contact has one."""
    card = vobject.vCard()
    card.add("version").value = "3.0"
    card.add("uid").value = row["uid"]
    card.add("fn").value = (row.get("pseudonym") if name_field == "pseudonym" else None) or row.get("full_name") or ""
    name = card.add("n")
    name.value = vobject.vcard.Name(given=row.get("full_name") or "")

    if row.get("pseudonym"):
        card.add("nickname").value = row["pseudonym"]
    if row.get("title"):
        card.add("title").value = row["title"]
    if row.get("role"):
        card.add("role").value = row["role"]
    if row.get("org"):
        card.add("org").value = [row["org"]]
    for phone in row.get("phones") or []:
        value = (phone.get("value") or "").strip()
        if not value:
            continue
        prop = card.add("tel")
        prop.value = value
        vcard_type = _TYPE_TO_VCARD.get(phone.get("type") or "Other")
        if vcard_type:
            prop.type_param = vcard_type
    for email in row.get("emails") or []:
        value = (email.get("value") or "").strip()
        if not value:
            continue
        prop = card.add("email")
        prop.value = value
        vcard_type = _TYPE_TO_VCARD.get(email.get("type") or "Other")
        if vcard_type:
            prop.type_param = vcard_type
    for website in row.get("websites") or []:
        url = (website.get("url") or "").strip()
        if not url:
            continue
        prop = card.add("url")
        prop.value = url
        vcard_type = _TYPE_TO_VCARD.get(website.get("type") or "Other")
        if vcard_type:
            prop.type_param = vcard_type
    if row.get("birthday"):
        card.add("bday").value = row["birthday"]
    for addr in row.get("addresses") or []:
        fields = {f: (addr.get(f) or "") for f in ("po_box", "extended", "street", "city", "region", "postal_code", "country")}
        if not any(fields.values()):
            continue
        prop = card.add("adr")
        prop.value = vobject.vcard.Address(
            box=fields["po_box"], extended=fields["extended"], street=fields["street"],
            city=fields["city"], region=fields["region"], code=fields["postal_code"], country=fields["country"],
        )
        vcard_type = _TYPE_TO_VCARD.get(addr.get("type") or "Other")
        if vcard_type:
            prop.type_param = vcard_type
    for profile in row.get("social_profiles") or []:
        value = (profile.get("value") or "").strip()
        if not value:
            continue
        prop = card.add("x-socialprofile")
        prop.value = value
        vcard_type = _SOCIAL_TYPE_TO_VCARD.get(profile.get("type") or "Other")
        if vcard_type:
            prop.type_param = vcard_type
    if row.get("tags"):
        card.add("categories").value = list(row["tags"])
    if row.get("notes"):
        card.add("note").value = row["notes"]
    if row.get("photo_b64"):
        # PHOTO travels as the actual vCard standard property (ENCODING=b,
        # inline base64), not a local file path -- this is what makes an
        # uploaded photo a real synced field, showing up on a phone's
        # native Contacts app or desktop's own CardDAV client too, not
        # just this web app. `photo.value` takes raw bytes; vobject does
        # the base64 encoding itself at serialize time once encoding_param
        # is set to "b" (confirmed via a real round-trip test, not just
        # the vobject docs, since binary-property behavior across vCard
        # libraries is a common source of subtly-wrong assumptions).
        photo = card.add("photo")
        photo.value = base64.b64decode(row["photo_b64"])
        photo.encoding_param = "b"
        photo.type_param = row.get("photo_type") or "JPEG"
    return card.serialize()


def vcard_to_contact_row(card: vobject.base.Component) -> dict[str, Any]:
    # A UID line is mandatory in the vCard spec, but plenty of real-world
    # exporters (Nextcloud's own "Administrator" sample card among them --
    # this is exactly the card that surfaced the crash) write cards with no
    # UID property at all. `card.uid` raises AttributeError via vobject's
    # `__getattr__` in that case (confirmed directly -- vobject has no
    # `getattr(card, "uid", None)`-friendly accessor), which used to
    # propagate all the way out as a 500 on /export/import/auto. Same
    # "assign a fresh identity for anything that doesn't already have one"
    # convention as every other uid-on-creation callsite in this app (see
    # e.g. routers/contacts.py's own `str(uuid.uuid4())`) -- a uid-less
    # imported card just becomes a new contact instead of failing the whole
    # import.
    uid = str(card.uid.value) if hasattr(card, "uid") and card.uid.value else str(uuid.uuid4())
    row: dict[str, Any] = {"uid": uid}
    row["full_name"] = str(card.fn.value) if hasattr(card, "fn") else ""
    # `hasattr(card, "org")` (and the tel/email checks below) is only "this
    # property line exists in the vCard," not "it has a real value" -- a
    # CardDAV client can round-trip a card with an empty `ORG:;`/`TEL:`/
    # `EMAIL:` line, in which case `.value` comes back `None` and the old
    # unconditional `str(org_val)` stored the literal string "None" (not
    # the value None) into the row -- which the web UI then dutifully
    # rendered ("None" reads as text, not as "field is empty"). Found via a
    # live contact showing a literal "None" in its list-row subtitle. Every
    # branch below now checks the actual value is truthy before storing it,
    # same as every other optional field here (adr/categories/note already
    # did this implicitly via `or`/isinstance guards).
    if hasattr(card, "nickname") and card.nickname.value:
        row["pseudonym"] = str(card.nickname.value)
    if hasattr(card, "title") and card.title.value:
        row["title"] = str(card.title.value)
    if hasattr(card, "role") and card.role.value:
        row["role"] = str(card.role.value)
    if hasattr(card, "org") and card.org.value:
        org_val = card.org.value
        row["org"] = org_val[0] if isinstance(org_val, list) else str(org_val)
    row["phones"] = [
        {"type": _VCARD_TO_TYPE.get(str(getattr(tel, "type_param", "") or "").upper(), "Other"), "value": str(tel.value)}
        for tel in getattr(card, "tel_list", [])
        if tel.value
    ]
    row["emails"] = [
        {"type": _VCARD_TO_TYPE.get(str(getattr(email, "type_param", "") or "").upper(), "Other"), "value": str(email.value)}
        for email in getattr(card, "email_list", [])
        if email.value
    ]
    row["websites"] = [
        {"type": _VCARD_TO_TYPE.get(str(getattr(url, "type_param", "") or "").upper(), "Other"), "url": str(url.value)}
        for url in getattr(card, "url_list", [])
        if url.value
    ]
    if hasattr(card, "bday") and card.bday.value:
        row["birthday"] = str(card.bday.value)
    row["addresses"] = [
        {
            "type": _VCARD_TO_TYPE.get(str(getattr(adr, "type_param", "") or "").upper(), "Other"),
            "po_box": getattr(adr.value, "box", "") or "",
            "extended": getattr(adr.value, "extended", "") or "",
            "street": getattr(adr.value, "street", "") or "",
            "city": getattr(adr.value, "city", "") or "",
            "region": getattr(adr.value, "region", "") or "",
            "postal_code": getattr(adr.value, "code", "") or "",
            "country": getattr(adr.value, "country", "") or "",
        }
        for adr in getattr(card, "adr_list", [])
        if adr.value
    ]
    row["social_profiles"] = [
        {
            "type": _VCARD_TO_SOCIAL_TYPE.get(str(getattr(p, "type_param", "") or "").upper(), "Other"),
            "value": str(p.value),
        }
        for p in getattr(card, "x_socialprofile_list", [])
        if p.value
    ]
    if hasattr(card, "categories"):
        cats = card.categories.value
        row["tags"] = list(cats) if isinstance(cats, list) else [str(cats)]
    if hasattr(card, "note"):
        row["notes"] = str(card.note.value)
    if hasattr(card, "photo"):
        photo_val = card.photo.value
        if isinstance(photo_val, bytes):
            # Inline embedded photo (the common case, and the only kind
            # this app itself ever writes) -- re-encode to base64 for
            # storage the same shape db.py/contact_detail.html expect.
            row["photo_b64"] = base64.b64encode(photo_val).decode("ascii")
            type_param = getattr(card.photo, "type_param", None)
            row["photo_type"] = str(type_param) if type_param else "JPEG"
        # A PHOTO given as a bare URI (ENCODING absent, value is a URL
        # string) is left alone -- this app has nowhere to store "fetch
        # this external URL" today, and silently trying to download
        # arbitrary third-party URLs during a sync poll is its own can of
        # worms. A contact edited elsewhere with a URI photo just won't
        # show a photo here until re-uploaded through this app.
    return row
