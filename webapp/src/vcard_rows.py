"""Flat dict row <-> vCard, for the web app's `contacts` table (db.py).
Same relationship to desktop/src/core/caldav/vcard.py as ical_rows.py has
to ical.py -- same field conventions, independent code, no X-COMMANDCENTER-*
properties since this app has no graph metadata to carry."""

from __future__ import annotations

import base64
from typing import Any

import vobject


def contact_row_to_vcard(row: dict[str, Any]) -> str:
    card = vobject.vCard()
    card.add("version").value = "3.0"
    card.add("uid").value = row["uid"]
    card.add("fn").value = row.get("full_name") or ""
    name = card.add("n")
    name.value = vobject.vcard.Name(given=row.get("full_name") or "")

    if row.get("org"):
        card.add("org").value = [row["org"]]
    if row.get("phone"):
        card.add("tel").value = row["phone"]
    if row.get("email"):
        card.add("email").value = row["email"]
    if row.get("address"):
        card.add("adr").value = vobject.vcard.Address(street=row["address"])
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
    row: dict[str, Any] = {"uid": str(card.uid.value)}
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
    if hasattr(card, "org") and card.org.value:
        org_val = card.org.value
        row["org"] = org_val[0] if isinstance(org_val, list) else str(org_val)
    if hasattr(card, "tel") and card.tel.value:
        row["phone"] = str(card.tel.value)
    if hasattr(card, "email") and card.email.value:
        row["email"] = str(card.email.value)
    if hasattr(card, "adr"):
        adr = card.adr.value
        row["address"] = getattr(adr, "street", "") or str(adr)
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
