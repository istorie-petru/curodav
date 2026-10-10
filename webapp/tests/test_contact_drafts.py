"""The buffer contact behind a new-contact form: hidden until Save, gone on
cancel, and carrying the photo through to the real contact."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src import db
from src.routers import contacts as contacts_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _create(conn, draft_uid="", photo=None):
    return asyncio.run(contacts_router.create_contact(
        full_name="Dana Scully", pseudonym="", title="", role="", org="",
        phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[],
        address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[],
        address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
        birthday="", tags="", notes="", photo=photo, draft_uid=draft_uid, conn=conn,
    ))


def test_a_draft_is_hidden_from_lists_and_search(conn):
    uid = db.create_contact_draft(conn)
    assert db.get_contact(conn, uid)["is_draft"] == 1
    assert db.list_contacts(conn) == []
    assert db.list_contacts(conn, include_archived=True) == []


def test_save_turns_the_draft_into_the_real_contact_and_keeps_its_photo(conn):
    uid = db.create_contact_draft(conn)
    row = dict(db.get_contact(conn, uid))
    row["photo_b64"], row["photo_type"] = "QUJD", "PNG"
    db.upsert_contact(conn, row, record_server_write=False)
    _create(conn, draft_uid=uid)
    contacts = db.list_contacts(conn)
    assert [c["uid"] for c in contacts] == [uid]
    assert contacts[0]["photo_b64"] == "QUJD"
    assert not contacts[0]["is_draft"]


def test_discard_removes_a_draft_but_never_a_saved_contact(conn):
    draft = db.create_contact_draft(conn)
    contacts_router.discard_contact_draft(draft, conn=conn)
    assert db.get_contact(conn, draft) is None
    _create(conn)
    saved = db.list_contacts(conn)[0]["uid"]
    contacts_router.discard_contact_draft(saved, conn=conn)
    assert db.get_contact(conn, saved) is not None


def test_stale_drafts_are_purged(conn):
    old = db.create_contact_draft(conn)
    stale = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    conn.execute("UPDATE contacts SET created_at = ? WHERE uid = ?", (stale, old))
    conn.commit()
    fresh = db.create_contact_draft(conn)
    assert db.get_contact(conn, old) is None
    assert db.get_contact(conn, fresh) is not None
