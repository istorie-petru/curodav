"""Flat dict row <-> vCard, for the web app's `contacts` table (db.py).
Same relationship to desktop/src/core/caldav/vcard.py as ical_rows.py has
to ical.py -- same field conventions, independent code, no X-COMMANDCENTER-*
properties since this app has no graph metadata to carry.

Contacts field parity slice 2 of 6 (plans/open.md, Phone/Email): a contact's
`phones`/`emails` are now lists of {"type", "value"} dicts (db.py's
contact_phones/contact_emails tables), round-tripped as multiple TEL/EMAIL
vCard 3.0 lines, one per entry, each carrying a TYPE= param
(`TEL;TYPE=CELL:555-1234`). vobject's multi-instance property API is
`card.add("tel")` (repeatable -- each call adds one more line) plus
`.type_param` on the returned property object for the TYPE=; read back via
`card.tel_list`/`card.email_list` (plural, *_list -- `card.tel`/`card.email`
only ever give the first line, which is exactly the slice-1-era bug this
rework fixes). vCard's real TYPE tokens are HOME/WORK/CELL/FAX/PAGER --
"Other" has no standard token, so it's the one type this module omits
TYPE= for entirely (a bare `TEL:...`/`EMAIL:...` line) rather than invent a
non-standard `TYPE=OTHER` value; reading a line with no TYPE= back always
maps to "Other" for the same reason, matching the vocabulary's own
"Other" being the catch-all default (db.CONTACT_PHONE_TYPES/
CONTACT_EMAIL_TYPES).

Contacts field parity slice 3 of 6 (Website): `websites` is a list of
{"type", "url"} dicts (db.py's contact_websites table), round-tripped the
same way as phones/emails above -- multiple `URL` vCard lines, one per
entry, with the same TYPE= convention (Home/Work carry TYPE=, Other omits
it). vCard's URL property isn't one of the typed multi-instance properties
RFC 2426/6350's core defines (TEL/EMAIL/ADR are; URL is single-valued in
the strict spec), but vobject supports repeated `card.add("url")` calls and
a `card.url_list` read-back identically to tel/email -- confirmed directly
against vobject (not assumed) before writing this: building a card with two
`card.add("url")` calls round-trips as two `URL;TYPE=...:` lines and
`card.url_list` returns both, `type_param` included, the exact same shape
as `tel_list`/`email_list`.

Contacts field parity slice 4 of 6 (Birthday): `birthday` is a single raw
text value (db.py's `contacts.birthday` column -- no child table, unlike
phone/email/website, since a contact has at most one), round-tripped
through vCard's single-instance BDAY property. Stored either as a full
"YYYY-MM-DD" or a year-less "--MM-DD" (db.parse_contact_birthday/
format_contact_birthday own that validation/display split); vobject
treats a string BDAY value as opaque text on both write and read, so
either shape passes through unchanged -- confirmed directly against
vobject before writing this.

Contacts field parity slice 5 of 6 (Address): `addresses` is a list of
{"type", "po_box", "extended", "street", "city", "region", "postal_code",
"country"} dicts (db.py's contact_addresses table), round-tripped as
multiple `ADR` vCard lines, one per entry, each carrying a TYPE= param --
same Home/Work-carries-TYPE=/Other-omits-it convention as tel/email/url
above. ADR *is* one of RFC 2426/6350's core typed multi-instance
properties (same standing as TEL/EMAIL, unlike URL's website-slice
workaround), and vobject's `vcard.Address` namedtuple-like value object
maps directly onto its seven-part structure (box/extended/street/city/
region/code/country -- `code` is this module's/db.py's `postal_code`,
purely a naming choice). Multi-instance behavior (`card.add("adr")`
repeatable, `card.adr_list` reading every line back with its own
`type_param`) confirmed directly against vobject before writing this, same
habit as every other field group in this module.

Contacts field parity slice 6 of 6 (Social network): `social_profiles` is a
list of {"type", "value"} dicts (db.py's contact_social_profiles table),
round-tripped as multiple `X-SOCIALPROFILE` vCard lines, one per entry,
each carrying a TYPE= param naming the network (Twitter/Facebook/etc.).
X-SOCIALPROFILE is an X- extension property, not part of the vCard 3.0
core RFC, but vobject treats any `X-...` contentline generically -- the
same `card.add("x-socialprofile")`/`card.x_socialprofile_list` shape as
every typed core property here, confirmed directly against vobject before
writing this (a bare X- property still gets `.type_param`/plural `_list`
read-back for free, since vobject's contentline handling doesn't special-
case X- properties differently from registered ones)."""

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

# Contacts field parity slice 6 of 6 -- Social network's own vocabulary
# (db.CONTACT_SOCIAL_TYPES) is network names, not Home/Work/etc., so it gets
# its own TYPE= mapping rather than reusing _TYPE_TO_VCARD above. Same
# "Other omits TYPE= entirely" convention as every other typed field in this
# module.
_SOCIAL_TYPE_TO_VCARD: dict[str, str] = {
    "Twitter": "TWITTER", "Facebook": "FACEBOOK", "Instagram": "INSTAGRAM",
    "LinkedIn": "LINKEDIN", "Mastodon": "MASTODON", "GitHub": "GITHUB",
}
_VCARD_TO_SOCIAL_TYPE: dict[str, str] = {v: k for k, v in _SOCIAL_TYPE_TO_VCARD.items()}


def contact_row_to_vcard(row: dict[str, Any]) -> str:
    card = vobject.vCard()
    card.add("version").value = "3.0"
    card.add("uid").value = row["uid"]
    card.add("fn").value = row.get("full_name") or ""
    name = card.add("n")
    name.value = vobject.vcard.Name(given=row.get("full_name") or "")

    if row.get("title"):
        card.add("title").value = row["title"]
    if row.get("org"):
        card.add("org").value = [row["org"]]
    # Multi-value phone/email (Contacts field parity slice 2 of 6) -- see
    # the module docstring for the TYPE= mapping/omission rule. `row.get
    # ("phone")`/`row.get("email")` (the legacy flat columns) are
    # deliberately NOT read here anymore -- db.get_contact always attaches
    # `phones`/`emails` (empty lists when there's nothing, never absent), so
    # any caller building a row from a live contact already has the
    # canonical multi-value shape; only a hand-built row dict (tests, a
    # not-yet-migrated legacy caller) could omit `phones`/`emails` entirely,
    # in which case this just emits no TEL/EMAIL lines, same as "zero
    # phones" today.
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
    # Multi-value website (Contacts field parity slice 3 of 6) -- same
    # TYPE=/omission convention as phone/email above, via vobject's
    # repeatable `card.add("url")` (confirmed directly against vobject --
    # see the module docstring).
    for website in row.get("websites") or []:
        url = (website.get("url") or "").strip()
        if not url:
            continue
        prop = card.add("url")
        prop.value = url
        vcard_type = _TYPE_TO_VCARD.get(website.get("type") or "Other")
        if vcard_type:
            prop.type_param = vcard_type
    # Birthday (Contacts field parity slice 4 of 6): stored and emitted as
    # a raw text BDAY value -- either a full "YYYY-MM-DD" or a year-less
    # "--MM-DD" (db.parse_contact_birthday/format_contact_birthday). Setting
    # `.value` to a plain string (not a `date`/`datetime` object) is what
    # keeps vobject from trying to parse/reformat it -- confirmed directly
    # against vobject (both shapes round-trip byte-for-byte through
    # serialize()/readOne()) before writing this, not assumed; see the
    # module docstring's phone/email/website precedent for the same
    # "confirmed against vobject" habit.
    if row.get("birthday"):
        card.add("bday").value = row["birthday"]
    # Multi-value structured Address (Contacts field parity slice 5 of 6) --
    # same TYPE=/omission convention as phone/email/website above, via
    # vobject's repeatable `card.add("adr")` (confirmed directly against
    # vobject -- see the module docstring). `row.get("address")` (the
    # legacy single-value column) is deliberately NOT read here anymore,
    # same "only the canonical multi-value shape" convention slice 2's TEL/
    # EMAIL rework already established for phone/email.
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
    # Social network (Contacts field parity slice 6 of 6) -- multiple
    # X-SOCIALPROFILE lines, one per entry, TYPE= naming the network (Other
    # omits it, same convention as every other typed field here).
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
    if hasattr(card, "title") and card.title.value:
        row["title"] = str(card.title.value)
    if hasattr(card, "org") and card.org.value:
        org_val = card.org.value
        row["org"] = org_val[0] if isinstance(org_val, list) else str(org_val)
    # Multi-value phone/email (Contacts field parity slice 2 of 6) -- every
    # TEL/EMAIL line becomes one {"type", "value"} entry, via vobject's
    # plural `tel_list`/`email_list` (the singular `card.tel`/`card.email`
    # only ever surfaces the first line -- see the module docstring). A
    # line with no TYPE= param, or one with a token outside this app's
    # vocabulary (e.g. a phone from another CardDAV client tagged
    # TYPE=VOICE), maps to "Other" -- the vocabulary's own catch-all, same
    # as a legacy single-value migration.
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
    # Multi-value website (Contacts field parity slice 3 of 6) -- every URL
    # line becomes one {"type", "url"} entry, via vobject's plural
    # `url_list` (see the module docstring).
    row["websites"] = [
        {"type": _VCARD_TO_TYPE.get(str(getattr(url, "type_param", "") or "").upper(), "Other"), "url": str(url.value)}
        for url in getattr(card, "url_list", [])
        if url.value
    ]
    # Birthday (Contacts field parity slice 4 of 6): `.value` comes back as
    # whatever raw text was on the BDAY line -- vobject never parses it into
    # a `date` on read either (confirmed the same way as the write side
    # above), so this is a plain string copy, not a reformat. A BDAY from
    # another CardDAV client in some other shape (e.g. bare `19900517`, no
    # dashes) is stored as-is too; db.format_contact_birthday falls back to
    # showing it unchanged rather than guessing at a reformat.
    if hasattr(card, "bday") and card.bday.value:
        row["birthday"] = str(card.bday.value)
    # Multi-value structured Address (Contacts field parity slice 5 of 6) --
    # every ADR line becomes one {"type", "po_box", "extended", "street",
    # "city", "region", "postal_code", "country"} entry, via vobject's
    # plural `adr_list` (see the module docstring).
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
    # Social network (Contacts field parity slice 6 of 6) -- every
    # X-SOCIALPROFILE line becomes one {"type", "value"} entry. An
    # unrecognized TYPE= token (a network outside this app's own vocabulary,
    # from another CardDAV client) maps to "Other", same catch-all
    # convention as every other typed field here.
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
