"""Contacts and their phones, emails, addresses and links.

Part of the db package; src/db/__init__.py re-exports every name.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .core import ENTITY_SYNC_FIELDS, _BIRTHDAY_FULL_RE, _BIRTHDAY_MONTHS, _BIRTHDAY_YEARLESS_RE, _UUID_RE, _row_columns, _row_to_dict, get_app_meta, set_app_meta
from .labels import _attach_tags, _attach_tags_bulk, list_object_label_names, set_object_labels
from .events import _birthday_event_uid, delete_event, get_event, upsert_event


def migrate_legacy_contact_phone_email(conn: sqlite3.Connection) -> None:
    """Contacts field parity slice 2 of 6 (plans/open.md) -- the green-lit
    auto-migration: a contact whose legacy `phone`/`email` column already
    has a value gets that value copied into the new `contact_phones`/
    `contact_emails` table as a single row typed "Other" (the vocabulary's
    catch-all, since the old flat column never recorded which kind of
    number/address it was).

    Idempotent by construction, not by a separate "have I run" flag: a
    contact is only migrated if it has a legacy value AND zero existing
    child rows for that field, so running this again after the first row
    exists is a no-op for that contact -- covers both "called twice in a
    row" (schema setup runs on every `db.connect`) and "the contact
    already has real typed rows a user entered" (per this slice's own test
    list: a contact with real post-migration rows must be left alone even
    if the legacy column somehow still has a stale value, since nothing
    writes to the legacy column anymore -- see the contacts CREATE TABLE
    comment for why it's frozen, not kept live). A contact with no legacy
    value gets no rows at all -- no spurious "Other" entry from an empty
    field."""
    now = datetime.now(timezone.utc).isoformat()
    phone_rows = conn.execute(
        "SELECT uid, phone FROM contacts WHERE phone IS NOT NULL AND TRIM(phone) != '' "
        "AND uid NOT IN (SELECT DISTINCT contact_uid FROM contact_phones)"
    ).fetchall()
    for row in phone_rows:
        conn.execute(
            "INSERT INTO contact_phones (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), row["uid"], "Other", row["phone"], 0, now),
        )
    email_rows = conn.execute(
        "SELECT uid, email FROM contacts WHERE email IS NOT NULL AND TRIM(email) != '' "
        "AND uid NOT IN (SELECT DISTINCT contact_uid FROM contact_emails)"
    ).fetchall()
    for row in email_rows:
        conn.execute(
            "INSERT INTO contact_emails (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), row["uid"], "Other", row["email"], 0, now),
        )
    if phone_rows or email_rows:
        conn.commit()


def migrate_legacy_contact_address(conn: sqlite3.Connection) -> None:
    """Contacts field parity slice 5 of 6 -- the same green-lit auto-
    migration shape as migrate_legacy_contact_phone_email above: a contact
    whose legacy free-text `address` column already has a value gets that
    value copied into the new `contact_addresses` table as a single row
    typed "Other". Unlike phone/email (a single flat string that maps
    directly onto TEL/EMAIL's own single `value`), the legacy `address`
    column was never structured -- there's no reliable way to split an
    arbitrary free-text address into PO Box/Street/City/Region/Postal code/
    Country, so the whole legacy string is placed into `street` (the one
    ADR line meant for a general street-level address) and every other
    structured field is left blank; a user can split it into the real
    fields by hand from the edit form afterward if they want to.

    Same idempotence shape as migrate_legacy_contact_phone_email: only
    migrates a contact that has a legacy value AND zero existing
    contact_addresses rows, so a contact with real typed address rows
    already (or a second call after the first migrated it) is left alone."""
    now = datetime.now(timezone.utc).isoformat()
    address_rows = conn.execute(
        "SELECT uid, address FROM contacts WHERE address IS NOT NULL AND TRIM(address) != '' "
        "AND uid NOT IN (SELECT DISTINCT contact_uid FROM contact_addresses)"
    ).fetchall()
    for row in address_rows:
        conn.execute(
            "INSERT INTO contact_addresses "
            "(uid, contact_uid, type, po_box, extended, street, city, region, postal_code, country, position, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), row["uid"], "Other", "", "", row["address"], "", "", "", "", 0, now),
        )
    if address_rows:
        conn.commit()


def _search_contacts(
    conn: sqlite3.Connection,
    q: str | None,
    labels: list[str] | None,
    excluded: set[str],
) -> list[dict[str, Any]]:
    query = "SELECT * FROM contacts"
    params: list[str] = []
    clauses: list[str] = ["archived_at IS NULL", "is_draft = 0"]

    if q:
        # Same "search both the dead legacy columns and the new child
        # tables" reasoning as list_contacts above.
        like = f"%{q}%"
        clauses.append(
            "(full_name LIKE ? OR title LIKE ? OR org LIKE ? OR phone LIKE ? OR email LIKE ? OR uid IN "
            "(SELECT object_id FROM object_labels WHERE object_type = 'contact' AND label_name LIKE ?) OR uid IN "
            "(SELECT contact_uid FROM contact_phones WHERE value LIKE ?) OR uid IN "
            "(SELECT contact_uid FROM contact_emails WHERE value LIKE ?) OR uid IN "
            "(SELECT contact_uid FROM contact_websites WHERE url LIKE ?))"
        )
        params.extend([like, like, like, like, like, like, like, like, like])
    if labels:
        placeholders = ", ".join("?" for _ in labels)
        clauses.append(
            f"uid IN (SELECT DISTINCT object_id FROM object_labels WHERE object_type = 'contact' AND label_name IN ({placeholders}))"
        )
        params.extend(labels)
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        clauses.append(f"uid NOT IN ({placeholders})")
        params.extend(excluded)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY full_name COLLATE NOCASE"
    rows = conn.execute(query, params).fetchall()
    dicts = _attach_contact_phones_emails_bulk(
        conn, _attach_tags_bulk(conn, "contact", [_row_to_dict(r, _CONTACT_JSON_FIELDS) for r in rows])
    )
    out: list[dict[str, Any]] = []
    for d in dicts:
        first_email = d["emails"][0]["value"] if d.get("emails") else d.get("email")
        first_phone = d["phones"][0]["value"] if d.get("phones") else d.get("phone")
        subtitle = d.get("org") or d.get("title") or first_email or first_phone or ""
        out.append(
            {
                "type": "contact",
                "uid": d["uid"],
                "title": d["full_name"],
                "subtitle": subtitle,
                "tags": d["tags"],
                "entity": d,
            }
        )
    return out


# --------------------------------------------------------------------- #
# Contacts
# --------------------------------------------------------------------- #

_CONTACT_JSON_FIELDS: tuple[str, ...] = ()

CONTACT_PHONE_TYPES: tuple[str, ...] = ("Home", "Work", "Cell", "Fax", "Pager", "Other")
CONTACT_EMAIL_TYPES: tuple[str, ...] = ("Home", "Work", "Other")
CONTACT_WEBSITE_TYPES: tuple[str, ...] = ("Home", "Work", "Other")
CONTACT_ADDRESS_TYPES: tuple[str, ...] = ("Home", "Work", "Other")
# Contacts field parity slice 6 of 6 -- Social network. Network names, not
# Home/Work/Other -- matches vcard_rows.py's own _SOCIAL_TYPE_TO_VCARD
# mapping (every entry here except "Other" has a TYPE= token there).
CONTACT_SOCIAL_TYPES: tuple[str, ...] = ("Twitter", "Facebook", "Instagram", "LinkedIn", "Mastodon", "GitHub", "Other")


def parse_contact_birthday(value: str) -> str:
    v = (value or "").strip()
    if _BIRTHDAY_FULL_RE.match(v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Birthday must be YYYY-MM-DD or --MM-DD, got '{value}'") from exc
        return v
    if _BIRTHDAY_YEARLESS_RE.match(v):
        month, day = v[2:4], v[5:7]
        try:
            # 2000 is a leap year -- lets a real "--02-29" (Feb 29, no
            # year) validate, same as it would for someone born in an
            # actual leap year, without this function needing to know
            # which specific years were leap years.
            datetime.strptime(f"2000-{month}-{day}", "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Birthday must be YYYY-MM-DD or --MM-DD, got '{value}'") from exc
        return v
    raise ValueError(f"Birthday must be YYYY-MM-DD or --MM-DD, got '{value}'")


def format_contact_birthday(value: str | None) -> str:
    """Human-readable display form for a stored birthday string --
    "May 17, 1990" for a full date, "May 17" (no year) for a year-less
    one. Returns the raw stored value unchanged if it doesn't match either
    known shape (a hand-edited vCard from another CardDAV client could
    carry a BDAY this app didn't write, e.g. a bare `19900517` -- showing
    the original text is safer than guessing at a reformat)."""
    v = (value or "").strip()
    if _BIRTHDAY_FULL_RE.match(v):
        year, month, day = v.split("-")
        return f"{_BIRTHDAY_MONTHS[int(month) - 1]} {int(day)}, {year}"
    if _BIRTHDAY_YEARLESS_RE.match(v):
        month, day = v[2:4], v[5:7]
        return f"{_BIRTHDAY_MONTHS[int(month) - 1]} {int(day)}"
    return v


def sync_contact_birthday_event(conn: sqlite3.Connection, contact_uid: str, full_name: str | None, birthday: str | None) -> None:
    """Direct follow-up (2026-08-16) to Contacts field parity slice 4 of 6:
    a contact's Birthday shows up on the Calendar itself, as a real all-day
    event recurring yearly, tagged with the "Birthday" label -- not a
    separate widget. Called from upsert_contact on every save (so the
    event's title/date always tracks the contact's current full_name/
    birthday) and from delete_contact.

    The event's uid is deterministic (`_birthday_event_uid`), not a fresh
    uuid4 -- lets this function find-and-replace it idempotently without a
    separate contact<->event relation column/table, the same "derive the
    id instead of storing a relation" shape event_occurrence_overrides'
    `master_uid::occurrence_date` composite key already uses. A cleared
    birthday (`None`) deletes the event outright via `delete_event` (which
    also clears its `object_labels` row) rather than leaving a dangling
    dateless event around.

    A year-less "--MM-DD" birthday has no real year to anchor DTSTART on,
    so it uses a fixed placeholder year (1900) far enough in the past that
    `FREQ=YEARLY` always has a "this year" occurrence to expand, regardless
    of when the calendar is viewed -- RRULE recurrence only ever generates
    occurrences forward from DTSTART, never before it, which is also
    exactly correct for a *full* birthday date: recurrence naturally starts
    at the real birth year and never fires an occurrence before someone was
    born."""
    event_uid = _birthday_event_uid(contact_uid)
    if not birthday:
        delete_event(conn, event_uid)
        return
    v = birthday.strip()
    if v.startswith("--"):
        start_at = f"1900-{v[2:4]}-{v[5:7]}"
    else:
        start_at = v
    existing = get_event(conn, event_uid)
    now = datetime.now(timezone.utc).isoformat()
    upsert_event(
        conn,
        {
            "uid": event_uid,
            "title": f"{full_name}'s Birthday" if full_name else "Birthday",
            "description": "",
            "start_at": start_at,
            "end_at": None,
            "all_day": True,
            "location": None,
            "meeting_url": None,
            "status": "active",
            "recurrence": "FREQ=YEARLY",
            "tags": ["Birthday"],
            "reminders": [],
            "holiday_calendar": None,
            "exclude_saturday": False,
            "exclude_sunday": False,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        },
    )


def upsert_contact(
    conn: sqlite3.Connection, row: dict[str, Any], *, record_server_write: bool = True
) -> None:
    from .sync import record_server_sync_write
    data = dict(row)
    if record_server_write:
        previous = _row_columns(conn, "contacts", str(data.get("uid")), _CONTACT_SYNC_COLUMNS)
    tags = data.pop("tags", None)
    # `phones`/`emails` (the new multi-value lists) are handled separately
    # below, same "pop the non-column keys, write the base row, then attach
    # the related rows" shape `tags` already used -- upsert_contact stays
    # the single call site every router/test uses to save a contact, it just
    # now also owns writing the child tables when the caller supplies them.
    phones = data.pop("phones", None)
    emails = data.pop("emails", None)
    # Contacts field parity slice 3 of 6 -- Website, same "pop, write the
    # base row, then attach the related rows" shape as phones/emails above.
    websites = data.pop("websites", None)
    # Contacts field parity slice 5 of 6 -- Address, same "pop, write the
    # base row, then attach the related rows" shape as phones/emails/
    # websites above.
    addresses = data.pop("addresses", None)
    # Contacts field parity slice 6 of 6 -- Social network, same "pop,
    # write the base row, then attach the related rows" shape as phones/
    # emails/websites/addresses above.
    social_profiles = data.pop("social_profiles", None)
    data["photo_version"] = hashlib.md5(data["photo_b64"].encode("ascii")).hexdigest()[:12] if data.get("photo_b64") else None
    if "archived_at" not in data:
        existing_row = conn.execute("SELECT archived_at FROM contacts WHERE uid = ?", (data.get("uid"),)).fetchone()
        data["archived_at"] = existing_row["archived_at"] if existing_row else None
    cols = [
        "uid", "full_name", "pseudonym", "title", "role", "org",
        "phone", "email", "address", "birthday", "notes",
        "photo_b64", "photo_type", "photo_version", "archived_at", "created_at", "updated_at",
    ]
    values = [data.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid")
    conn.execute(
        f"INSERT INTO contacts ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        values,
    )
    if tags is not None:
        set_object_labels(conn, "contact", data["uid"], tags)
    if phones is not None:
        set_contact_phones(conn, data["uid"], phones)
    if emails is not None:
        set_contact_emails(conn, data["uid"], emails)
    if websites is not None:
        set_contact_websites(conn, data["uid"], websites)
    if addresses is not None:
        set_contact_addresses(conn, data["uid"], addresses)
    if social_profiles is not None:
        set_contact_social_profiles(conn, data["uid"], social_profiles)
    if record_server_write:
        record_server_sync_write(
            conn,
            "contact",
            data["uid"],
            previous,
            _row_columns(conn, "contacts", data["uid"], _CONTACT_SYNC_COLUMNS),
        )
    conn.commit()
    sync_contact_birthday_event(conn, data["uid"], data.get("full_name"), data.get("birthday"))


def create_contact_draft(conn: sqlite3.Connection) -> str:
    """A buffer contact for a new-contact form. Not synced, not listed."""
    purge_contact_drafts(conn)
    uid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO contacts (uid, full_name, is_draft, created_at, updated_at) VALUES (?, '', 1, ?, ?)",
        (uid, now, now),
    )
    conn.commit()
    return uid


def purge_contact_drafts(conn: sqlite3.Connection, older_than_hours: int = 24) -> None:
    """Drafts nobody finished (a closed tab never reports back)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
    for row in conn.execute("SELECT uid FROM contacts WHERE is_draft = 1 AND created_at < ?", (cutoff,)).fetchall():
        delete_contact(conn, row["uid"], record_server_write=False)


def delete_contact(
    conn: sqlite3.Connection, uid: str, *, record_server_write: bool = True
) -> None:
    from .sync import record_server_delete
    if record_server_write:
        record_server_delete(conn, "contact", uid)
    conn.execute("DELETE FROM contacts WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM object_labels WHERE object_type = 'contact' AND object_id = ?", (uid,))
    conn.execute("DELETE FROM object_contacts WHERE contact_uid = ?", (uid,))
    # Same cascade-cleanup reasoning as delete_checklist_items_for_task --
    # never actually reachable via a reused uid (uuid4), but an orphaned
    # phone/email/website row pointing at a gone contact serves no purpose
    # either.
    conn.execute("DELETE FROM contact_phones WHERE contact_uid = ?", (uid,))
    conn.execute("DELETE FROM contact_emails WHERE contact_uid = ?", (uid,))
    conn.execute("DELETE FROM contact_websites WHERE contact_uid = ?", (uid,))
    conn.execute("DELETE FROM contact_addresses WHERE contact_uid = ?", (uid,))
    conn.execute("DELETE FROM contact_social_profiles WHERE contact_uid = ?", (uid,))
    # Deletes the generated Birthday event (if one exists) along with the
    # contact itself -- see sync_contact_birthday_event's docstring for why
    # this is a plain delete_event on the deterministic uid, not a lookup
    # through any relation table.
    delete_event(conn, _birthday_event_uid(uid))
    conn.commit()


def _backfill_contact_photo_version(conn: sqlite3.Connection, d: dict[str, Any]) -> dict[str, Any]:
    """A contact whose photo was saved before contacts.photo_version
    existed (_ensure_column above) has photo_b64 but a NULL version --
    computed and persisted here, once, the same lazy-backfill-on-read
    pattern get_page_banner/get_profile_photo use for their own version
    field. Every other read already gets a fresh version for free
    (upsert_contact computes it on every write), so this only ever fires
    for a genuinely pre-migration row."""
    if d.get("photo_b64") and not d.get("photo_version"):
        version = hashlib.md5(d["photo_b64"].encode("ascii")).hexdigest()[:12]
        conn.execute("UPDATE contacts SET photo_version = ? WHERE uid = ?", (version, d["uid"]))
        conn.commit()
        d["photo_version"] = version
    return d


def get_contact(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM contacts WHERE uid = ?", (uid,)).fetchone()
    if not row:
        return None
    d = _attach_tags(conn, "contact", _row_to_dict(row, _CONTACT_JSON_FIELDS))
    return _backfill_contact_photo_version(conn, _attach_contact_phones_emails(conn, d))


def _attach_contact_phones_emails(conn: sqlite3.Connection, d: dict[str, Any]) -> dict[str, Any]:
    """Attaches `phones`/`emails`/`websites`/`addresses` (each a list of
    position-ordered dicts -- phones/emails are {"uid", "type", "value"},
    websites {"uid", "type", "url"}, addresses {"uid", "type", "po_box",
    "extended", "street", "city", "region", "postal_code", "country"},
    social_profiles {"uid", "type", "value"}) the same way `_attach_tags`
    attaches `tags` -- computed live from the child tables at read time,
    never a stored JSON blob on the contacts row itself."""
    d["phones"] = list_contact_phones(conn, d["uid"])
    d["emails"] = list_contact_emails(conn, d["uid"])
    d["websites"] = list_contact_websites(conn, d["uid"])
    d["addresses"] = list_contact_addresses(conn, d["uid"])
    d["social_profiles"] = list_contact_social_profiles(conn, d["uid"])
    return d


def _attach_contact_phones_emails_bulk(
    conn: sqlite3.Connection, dicts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Batch form of `_attach_contact_phones_emails` -- one `IN (...)`
    query per child table (5 total) for the whole contact list instead of
    5 queries per row (the second half of the N+1 finding, `db.py:3038-
    3042` in the audit report -- a contacts-list render used to cost the
    base query plus 6 extra queries *per row*). Mutates and returns
    `dicts` in place, same contract as `_attach_contact_phones_emails`."""
    if not dicts:
        return dicts
    ids = [d["uid"] for d in dicts]
    placeholders = ", ".join("?" for _ in ids)

    def _grouped(table: str) -> dict[str, list[dict[str, Any]]]:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE contact_uid IN ({placeholders}) "
            "ORDER BY position ASC, created_at ASC",
            ids,
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            grouped.setdefault(r["contact_uid"], []).append(dict(r))
        return grouped

    phones = _grouped("contact_phones")
    emails = _grouped("contact_emails")
    websites = _grouped("contact_websites")
    addresses = _grouped("contact_addresses")
    social_profiles = _grouped("contact_social_profiles")
    for d in dicts:
        d["phones"] = phones.get(d["uid"], [])
        d["emails"] = emails.get(d["uid"], [])
        d["websites"] = websites.get(d["uid"], [])
        d["addresses"] = addresses.get(d["uid"], [])
        d["social_profiles"] = social_profiles.get(d["uid"], [])
    return dicts


def list_contacts(
    conn: sqlite3.Connection,
    q: str | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """`include_archived` defaults False (2026-09-26, item 19 -- "archived
    contacts don't sync"/aren't visible normally) -- same "excluded unless
    a caller explicitly opts in" shape `list_tasks`'s own
    `include_habit_tasks` already established. This is the ONE fetcher
    both the Contacts page (routers/contacts.py) and Published Lists'
    materialization (published_lists.py's `_ENTITY_FETCHERS["contact"]`)
    call, so leaving this default False protects both call sites at once
    -- a List can never end up including an archived contact just because
    it matched the List's own label filter, without published_lists.py
    needing its own separate archived-exclusion logic."""
    query = "SELECT * FROM contacts"
    params: list[str] = []
    clauses = ["is_draft = 0"]
    if not include_archived:
        clauses.append("archived_at IS NULL")
    if q:
        # Matches name, org, title, or any phone/email -- both the legacy
        # flat columns (harmless redundancy; a pre-migration value can only
        # exist there if migrate_legacy_contact_phone_email somehow hasn't
        # run yet, which it always has by the time any query executes -- see
        # that function's own call site in init_schema) and the new
        # multi-value child tables, so a search for a number/address still
        # finds the contact no matter which type it's tagged with.
        clauses.append(
            "(full_name LIKE ? OR title LIKE ? OR org LIKE ? OR phone LIKE ? OR email LIKE ? "
            "OR uid IN (SELECT contact_uid FROM contact_phones WHERE value LIKE ?) "
            "OR uid IN (SELECT contact_uid FROM contact_emails WHERE value LIKE ?) "
            "OR uid IN (SELECT contact_uid FROM contact_websites WHERE url LIKE ?))"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like, like, like, like, like])
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY full_name ASC"
    rows = conn.execute(query, params).fetchall()
    dicts = _attach_contact_phones_emails_bulk(
        conn, _attach_tags_bulk(conn, "contact", [_row_to_dict(r, _CONTACT_JSON_FIELDS) for r in rows])
    )
    return [_backfill_contact_photo_version(conn, d) for d in dicts]


def archive_contact(conn: sqlite3.Connection, uid: str) -> None:
    """Item 19 (2026-09-26): a real top-level data-model column, not a
    label -- replaces the old `ARCHIVED_LABEL` fake-label hack
    (routers/contacts.py), which conflated archiving with categorization
    once a contact could carry only one label total (item 16). Same
    "explicit action, never automatic" shape `archive_project` already
    uses for label_config.archived_at. No-op on an unknown uid (matches
    every other single-object mutator's own quiet-no-op convention, e.g.
    `remove_latest_work_allocation`)."""
    conn.execute(
        "UPDATE contacts SET archived_at = ? WHERE uid = ?",
        (datetime.now(timezone.utc).isoformat(), uid),
    )
    conn.commit()


def unarchive_contact(conn: sqlite3.Connection, uid: str) -> None:
    """Undoes archive_contact -- the contact is visible/synced again."""
    conn.execute("UPDATE contacts SET archived_at = NULL WHERE uid = ?", (uid,))
    conn.commit()


def migrate_archived_contact_label(conn: sqlite3.Connection) -> None:
    """One-time migration (item 19, 2026-09-26): 'Archived' used to be a
    top-level fake LABEL on Contacts (routers/contacts.py's since-removed
    `ARCHIVED_LABEL`) -- every contact still carrying that tag gets the
    tag removed and the real `contacts.archived_at` column (this item's
    whole point) set instead. Matched case-insensitively, same convention
    the old filter code used (a user could have typed "Archived" via the
    label picker's free-text "new label" field, not just lowercase).
    Idempotent via its own app_meta flag -- once run, a later admin who
    deliberately creates a real, ordinary label that happens to be NAMED
    "archived" is never silently re-migrated."""
    key = "contacts_archived_label_migrated_v1"
    if get_app_meta(conn, key):
        return
    rows = conn.execute(
        "SELECT DISTINCT object_id, label_name FROM object_labels "
        "WHERE object_type = 'contact' AND LOWER(label_name) = 'archived'"
    ).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        conn.execute(
            "DELETE FROM object_labels WHERE object_type = 'contact' AND object_id = ? AND label_name = ?",
            (r["object_id"], r["label_name"]),
        )
        conn.execute(
            "UPDATE contacts SET archived_at = COALESCE(archived_at, ?) WHERE uid = ?",
            (now, r["object_id"]),
        )
    set_app_meta(conn, key, "1")
    conn.commit()


# --------------------------------------------------------------------- #
# Contact phones / emails -- Contacts field parity slice 2 of 6 (plans/
# open.md). Per-parent child-table CRUD, closest precedent is work
# allocations' list_work_allocations_for_task/create_work_allocation/
# delete_work_allocation trio -- but a contact's phone/email list is edited
# as a whole via one Save button (contact_form.html submits every row
# together as parallel phone_type[]/phone_value[] form arrays, same shape
# `tags_labels: list[str] = Form([])` already uses on this router), not
# through separate per-row add/remove endpoints the way work sessions or
# checklist items are -- so the primary write operation here is
# set_contact_phones/set_contact_emails ("replace everything for this
# contact with this ordered list"), not incremental add/update/delete
# calls. add_contact_phone/add_contact_email still exist standalone because
# migrate_legacy_contact_phone_email needs to insert exactly one row without
# disturbing anything else already there.
# --------------------------------------------------------------------- #


def list_contact_phones(conn: sqlite3.Connection, contact_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM contact_phones WHERE contact_uid = ? ORDER BY position ASC, created_at ASC",
        (contact_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_contact_emails(conn: sqlite3.Connection, contact_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM contact_emails WHERE contact_uid = ? ORDER BY position ASC, created_at ASC",
        (contact_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_contact_phone(conn: sqlite3.Connection, contact_uid: str, type_: str, value: str) -> str:
    """Appends one phone row after whatever's already there. Used by
    migrate_legacy_contact_phone_email (a single-row, non-destructive
    insert); the create/edit form uses set_contact_phones instead, since it
    always submits the full list at once."""
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM contact_phones WHERE contact_uid = ?",
        (contact_uid,),
    ).fetchone()
    new_uid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO contact_phones (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (new_uid, contact_uid, type_ or "Other", value, row["p"], datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return new_uid


def add_contact_email(conn: sqlite3.Connection, contact_uid: str, type_: str, value: str) -> str:
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM contact_emails WHERE contact_uid = ?",
        (contact_uid,),
    ).fetchone()
    new_uid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO contact_emails (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (new_uid, contact_uid, type_ or "Other", value, row["p"], datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return new_uid


def set_contact_phones(conn: sqlite3.Connection, contact_uid: str, items: list[dict[str, Any]]) -> None:
    """Replaces every phone row for `contact_uid` with `items` (each a
    {"type", "value"} dict), in the given order. The create/edit form always
    submits its whole ordered phone list together (one Save button, per
    plans/open.md's own reasoning for choosing form-array fields over
    per-row endpoints) so "delete everything, re-insert in submitted order"
    is simpler and just as correct as diffing against the previous set by
    uid -- position is always just the item's index, so display order keeps
    matching submission order. Blank values are dropped silently (an empty
    row in the form is "no phone here", not a phone with an empty number)."""
    conn.execute("DELETE FROM contact_phones WHERE contact_uid = ?", (contact_uid,))
    now = datetime.now(timezone.utc).isoformat()
    position = 0
    for item in items:
        value = (item.get("value") or "").strip()
        if not value:
            continue
        conn.execute(
            "INSERT INTO contact_phones (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), contact_uid, item.get("type") or "Other", value, position, now),
        )
        position += 1
    conn.commit()


def set_contact_emails(conn: sqlite3.Connection, contact_uid: str, items: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM contact_emails WHERE contact_uid = ?", (contact_uid,))
    now = datetime.now(timezone.utc).isoformat()
    position = 0
    for item in items:
        value = (item.get("value") or "").strip()
        if not value:
            continue
        conn.execute(
            "INSERT INTO contact_emails (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), contact_uid, item.get("type") or "Other", value, position, now),
        )
        position += 1
    conn.commit()


# --------------------------------------------------------------------- #
# Contact websites -- Contacts field parity slice 3 of 6 (plans/open.md).
# Same shape as contact_phones/contact_emails immediately above -- one
# Save-button replace-all write path (set_contact_websites), no separate
# add/remove endpoints. Unlike phone/email, there is no legacy single-value
# column to migrate from (confirmed by grep before this slice started), so
# there's no add_contact_website standalone helper -- nothing needs to
# insert exactly one row outside of set_contact_websites.
# --------------------------------------------------------------------- #


def list_contact_websites(conn: sqlite3.Connection, contact_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM contact_websites WHERE contact_uid = ? ORDER BY position ASC, created_at ASC",
        (contact_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def set_contact_websites(conn: sqlite3.Connection, contact_uid: str, items: list[dict[str, Any]]) -> None:
    """Replaces every website row for `contact_uid` with `items` (each a
    {"type", "url"} dict), in the given order -- same "delete everything,
    re-insert in submitted order" reasoning as set_contact_phones/
    set_contact_emails. Blank URLs are dropped silently."""
    conn.execute("DELETE FROM contact_websites WHERE contact_uid = ?", (contact_uid,))
    now = datetime.now(timezone.utc).isoformat()
    position = 0
    for item in items:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        conn.execute(
            "INSERT INTO contact_websites (uid, contact_uid, type, url, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), contact_uid, item.get("type") or "Other", url, position, now),
        )
        position += 1
    conn.commit()


# --------------------------------------------------------------------- #
# Contact addresses -- Contacts field parity slice 5 of 6 (plans/open.md).
# Same shape as contact_phones/contact_emails/contact_websites above (one
# Save-button replace-all write path, no separate add/remove endpoints),
# just with seven value fields per row instead of one. A row counts as
# "blank" (dropped on save) only when EVERY structured field is blank --
# unlike phone/email/website's single `value`/`url`, a real address could
# legitimately have e.g. only a city and country filled in, so there's no
# single field whose blankness alone means "no address here."
# --------------------------------------------------------------------- #

_CONTACT_ADDRESS_FIELDS: tuple[str, ...] = (
    "po_box", "extended", "street", "city", "region", "postal_code", "country",
)


def list_contact_addresses(conn: sqlite3.Connection, contact_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM contact_addresses WHERE contact_uid = ? ORDER BY position ASC, created_at ASC",
        (contact_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def format_contact_address(addr: dict[str, Any]) -> str:
    """Human-readable multi-line display for one structured address dict
    (contact_detail.html's `fmt_address` filter, deps.py) -- same line
    ordering vCard's own `vobject.vcard.Address.__str__` uses (PO Box/
    Extended/Street each get their own line if present, then "City, Region
    PostalCode" on one line, then Country on its own line), reimplemented
    here as a pure function of this app's dict shape rather than building a
    throwaway `vobject.vcard.Address` object just to stringify it. Blank
    fields are omitted entirely rather than leaving stray empty lines/
    commas."""
    lines = [addr.get(f) for f in ("po_box", "extended", "street") if (addr.get(f) or "").strip()]
    city, region, postal_code = addr.get("city") or "", addr.get("region") or "", addr.get("postal_code") or ""
    if city.strip() or region.strip() or postal_code.strip():
        city_line = ", ".join(p for p in (city.strip(), " ".join(p for p in (region.strip(), postal_code.strip()) if p)) if p)
        lines.append(city_line)
    if (addr.get("country") or "").strip():
        lines.append(addr["country"].strip())
    return "\n".join(lines)


def set_contact_addresses(conn: sqlite3.Connection, contact_uid: str, items: list[dict[str, Any]]) -> None:
    """Replaces every address row for `contact_uid` with `items` (each a
    {"type", "po_box", "extended", "street", "city", "region",
    "postal_code", "country"} dict, any key may be omitted), in the given
    order -- same "delete everything, re-insert in submitted order"
    reasoning as set_contact_phones/set_contact_emails/set_contact_websites.
    A row is dropped only when every one of the seven structured fields is
    blank (see this section's own comment for why that's a 7-way check,
    not a single-field one like the sibling setters)."""
    conn.execute("DELETE FROM contact_addresses WHERE contact_uid = ?", (contact_uid,))
    now = datetime.now(timezone.utc).isoformat()
    position = 0
    for item in items:
        values = {f: (item.get(f) or "").strip() for f in _CONTACT_ADDRESS_FIELDS}
        if not any(values.values()):
            continue
        conn.execute(
            "INSERT INTO contact_addresses "
            "(uid, contact_uid, type, po_box, extended, street, city, region, postal_code, country, position, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), contact_uid, item.get("type") or "Other",
                values["po_box"], values["extended"], values["street"],
                values["city"], values["region"], values["postal_code"], values["country"],
                position, now,
            ),
        )
        position += 1
    conn.commit()


# --------------------------------------------------------------------- #
# Contact social profiles -- Contacts field parity slice 6 of 6 (plans/
# open.md). Same shape as contact_phones/contact_emails/contact_websites
# (single `value` column, one Save-button replace-all write path, no
# separate add/remove endpoints, no legacy column to migrate -- same
# "confirmed by grep, nothing to migrate" situation as Website).
# --------------------------------------------------------------------- #


def list_contact_social_profiles(conn: sqlite3.Connection, contact_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM contact_social_profiles WHERE contact_uid = ? ORDER BY position ASC, created_at ASC",
        (contact_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def set_contact_social_profiles(conn: sqlite3.Connection, contact_uid: str, items: list[dict[str, Any]]) -> None:
    """Replaces every social-profile row for `contact_uid` with `items`
    (each a {"type", "value"} dict), in the given order -- same "delete
    everything, re-insert in submitted order" reasoning as
    set_contact_phones/set_contact_emails/set_contact_websites. Blank
    values are dropped silently."""
    conn.execute("DELETE FROM contact_social_profiles WHERE contact_uid = ?", (contact_uid,))
    now = datetime.now(timezone.utc).isoformat()
    position = 0
    for item in items:
        value = (item.get("value") or "").strip()
        if not value:
            continue
        conn.execute(
            "INSERT INTO contact_social_profiles (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), contact_uid, item.get("type") or "Other", value, position, now),
        )
        position += 1
    conn.commit()


def list_contact_tag_names(conn: sqlite3.Connection) -> list[str]:
    """Distinct labels across all contacts (Phase 7 rework -- the Contacts
    tag filter + the project People section; Phase 2 label-space rework --
    now backed by object_labels instead of tags_json). Thin wrapper over
    list_object_label_names, kept under its historical name since every
    existing caller (contacts.py, contacts_list.html) already uses it."""
    return list_object_label_names(conn, "contact")


def all_contact_uids(conn: sqlite3.Connection) -> set[str]:
    return {r["uid"] for r in conn.execute("SELECT uid FROM contacts").fetchall()}


def resolve_contact_entries(conn: sqlite3.Connection, entries: list[str]) -> list[str]:
    """Turns the Contacts field's values into contact uids. A value that is a
    known uid stays; a typed name matches an existing contact by name or
    becomes a new contact (name only); a stray unknown uid is dropped."""
    resolved: list[str] = []
    for raw in entries or []:
        value = (raw or "").strip()
        if not value:
            continue
        if conn.execute("SELECT 1 FROM contacts WHERE uid = ? AND is_draft = 0", (value,)).fetchone():
            resolved.append(value)
            continue
        if _UUID_RE.match(value) or not any(ch.isalpha() for ch in value):
            continue
        row = conn.execute(
            "SELECT uid FROM contacts WHERE lower(full_name) = lower(?) AND is_draft = 0 LIMIT 1", (value,)
        ).fetchone()
        if row:
            resolved.append(row["uid"])
            continue
        now = datetime.now(timezone.utc).isoformat()
        uid = str(uuid.uuid4())
        upsert_contact(conn, {"uid": uid, "full_name": value, "org": None, "tags": [], "created_at": now, "updated_at": now})
        resolved.append(uid)
    return resolved


def set_object_contacts(conn: sqlite3.Connection, object_type: str, object_id: str, contact_uids: list[str]) -> None:
    """Replaces the contacts linked to (object_type, object_id) with exactly
    `contact_uids`; unknown or draft contacts are ignored."""
    conn.execute("DELETE FROM object_contacts WHERE object_type = ? AND object_id = ?", (object_type, object_id))
    for uid in dict.fromkeys(u for u in (contact_uids or []) if u):
        if conn.execute("SELECT 1 FROM contacts WHERE uid = ? AND is_draft = 0", (uid,)).fetchone():
            conn.execute(
                "INSERT OR IGNORE INTO object_contacts (object_type, object_id, contact_uid) VALUES (?, ?, ?)",
                (object_type, object_id, uid),
            )
    conn.commit()


def list_object_contacts(conn: sqlite3.Connection, object_type: str, object_id: str) -> list[dict[str, Any]]:
    """The contacts linked to a task or event, by name."""
    rows = conn.execute(
        "SELECT c.uid, c.full_name FROM object_contacts oc JOIN contacts c ON c.uid = oc.contact_uid "
        "WHERE oc.object_type = ? AND oc.object_id = ? ORDER BY c.full_name",
        (object_type, object_id),
    ).fetchall()
    return [dict(r) for r in rows]


def list_contact_objects(conn: sqlite3.Connection, contact_uid: str) -> dict[str, list[dict[str, Any]]]:
    """The tasks and events that involve a contact, for the contact's page."""
    tasks = conn.execute(
        "SELECT t.uid, t.title FROM object_contacts oc JOIN tasks t ON t.uid = oc.object_id "
        "WHERE oc.object_type = 'task' AND oc.contact_uid = ? ORDER BY t.title",
        (contact_uid,),
    ).fetchall()
    events = conn.execute(
        "SELECT e.uid, e.title FROM object_contacts oc JOIN events e ON e.uid = oc.object_id "
        "WHERE oc.object_type = 'event' AND oc.contact_uid = ? ORDER BY e.title",
        (contact_uid,),
    ).fetchall()
    return {"tasks": [dict(r) for r in tasks], "events": [dict(r) for r in events]}


_CONTACTS_WIDGET_DEFAULT_FIXED_KEY = "label_modules_contacts_default_fixed"


def _fix_contacts_widget_default(conn: sqlite3.Connection) -> None:
    """One-time fix (slice b, 2026-09-25): slice a shipped contacts_widget
    defaulting to off, on the wrong belief that the plain label page had no
    Contacts card. It did (added 2026-09-16). Nothing could set the field
    before slice b's form, so every stored value is that wrong default and
    is safe to turn on. On a database migrated by slice a, the column
    DEFAULT stays 0 (SQLite can't alter a default in place), but every
    insert goes through upsert_label_config, which writes the Python-side
    default of 1 explicitly."""
    if get_app_meta(conn, _CONTACTS_WIDGET_DEFAULT_FIXED_KEY):
        return
    conn.execute("UPDATE label_config SET contacts_widget = 1")
    set_app_meta(conn, _CONTACTS_WIDGET_DEFAULT_FIXED_KEY, "1")
_CONTACT_SYNC_COLUMNS = sorted(ENTITY_SYNC_FIELDS["contact"])
