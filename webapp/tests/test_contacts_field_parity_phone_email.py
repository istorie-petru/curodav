"""Contacts field parity with Nextcloud Contacts (plans/open.md), slice 2 of
6 (Title -> Phone/Email -> Website -> Birthday -> Address -> Social network,
per the build order recorded there). Phone/Email become genuinely
multi-value: a contact can have any number of phone numbers/email addresses,
each tagged with a vCard/Nextcloud type (Home/Work/Cell/Fax/Pager/Other for
phone, Home/Work/Other for email -- green-lit, AskUserQuestion, 2026-08-15).

Structured like test_contacts_field_parity_title.py -- same fixture helpers,
same TestSchema/TestVcardRoundTrip/TestCreateEditFlow/TestSearchMatches*/
TestRenderedMarkup breakdown, plus a TestLegacyMigration class covering the
auto-migration this slice's own green-lit decision requires (an existing
single-value phone/email auto-migrates as a first entry typed "Other").
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from pathlib import Path

import pytest
import vobject
from starlette.requests import Request

from src import db
from src.routers import contacts as contacts_router
from src.vcard_rows import contact_row_to_vcard, vcard_to_contact_row

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "src" / "templates"


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_contact(conn, **overrides):
    now = _now()
    row = {
        "uid": overrides.pop("uid", None) or "c-" + str(id(overrides)),
        "full_name": "Ada Lovelace",
        "title": None,
        "org": None,
        "phone": None,
        "email": None,
        "address": None,
        "notes": None,
        "tags": [],
        "photo_b64": None,
        "photo_type": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    db.upsert_contact(conn, row)
    return row["uid"]


def _fake_request(path="/contacts"):
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "root_path": "",
        "headers": [],
    })


class TestSchema:
    def test_contact_phones_table_exists(self, conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contact_phones)").fetchall()}
        assert {"uid", "contact_uid", "type", "value", "position", "created_at"} <= cols

    def test_contact_emails_table_exists(self, conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contact_emails)").fetchall()}
        assert {"uid", "contact_uid", "type", "value", "position", "created_at"} <= cols

    def test_legacy_phone_email_columns_still_present(self, conn):
        # Never force-dropped -- see db.py's contacts CREATE TABLE comment.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
        assert "phone" in cols
        assert "email" in cols

    def test_type_vocabularies_match_vcard_nextcloud(self):
        assert db.CONTACT_PHONE_TYPES == ("Home", "Work", "Cell", "Fax", "Pager", "Other")
        assert db.CONTACT_EMAIL_TYPES == ("Home", "Work", "Other")

    def test_set_and_list_contact_phones_round_trip(self, conn):
        uid = _make_contact(conn)
        db.set_contact_phones(conn, uid, [{"type": "Cell", "value": "555-1111"}, {"type": "Work", "value": "555-2222"}])
        phones = db.list_contact_phones(conn, uid)
        assert [(p["type"], p["value"]) for p in phones] == [("Cell", "555-1111"), ("Work", "555-2222")]

    def test_set_and_list_contact_emails_round_trip(self, conn):
        uid = _make_contact(conn)
        db.set_contact_emails(conn, uid, [{"type": "Home", "value": "a@b.com"}])
        emails = db.list_contact_emails(conn, uid)
        assert [(e["type"], e["value"]) for e in emails] == [("Home", "a@b.com")]

    def test_set_contact_phones_replaces_not_appends(self, conn):
        uid = _make_contact(conn)
        db.set_contact_phones(conn, uid, [{"type": "Home", "value": "111"}])
        db.set_contact_phones(conn, uid, [{"type": "Work", "value": "222"}])
        phones = db.list_contact_phones(conn, uid)
        assert [(p["type"], p["value"]) for p in phones] == [("Work", "222")]

    def test_set_contact_phones_drops_blank_values(self, conn):
        uid = _make_contact(conn)
        db.set_contact_phones(conn, uid, [{"type": "Home", "value": "  "}, {"type": "Work", "value": "222"}])
        phones = db.list_contact_phones(conn, uid)
        assert [(p["type"], p["value"]) for p in phones] == [("Work", "222")]

    def test_get_contact_attaches_phones_and_emails(self, conn):
        uid = _make_contact(conn)
        db.set_contact_phones(conn, uid, [{"type": "Cell", "value": "555-1111"}])
        db.set_contact_emails(conn, uid, [{"type": "Work", "value": "a@b.com"}])
        row = db.get_contact(conn, uid)
        assert row["phones"][0]["value"] == "555-1111"
        assert row["emails"][0]["value"] == "a@b.com"

    def test_get_contact_phones_emails_empty_by_default(self, conn):
        uid = _make_contact(conn)
        row = db.get_contact(conn, uid)
        assert row["phones"] == []
        assert row["emails"] == []

    def test_delete_contact_cascades_phones_and_emails(self, conn):
        uid = _make_contact(conn)
        db.set_contact_phones(conn, uid, [{"type": "Home", "value": "111"}])
        db.delete_contact(conn, uid)
        assert db.list_contact_phones(conn, uid) == []


class TestLegacyMigration:
    def test_legacy_phone_migrates_as_other(self, conn):
        uid = _make_contact(conn, phone="555-9999")
        db.migrate_legacy_contact_phone_email(conn)
        phones = db.list_contact_phones(conn, uid)
        assert [(p["type"], p["value"]) for p in phones] == [("Other", "555-9999")]

    def test_legacy_email_migrates_as_other(self, conn):
        uid = _make_contact(conn, email="ada@example.com")
        db.migrate_legacy_contact_phone_email(conn)
        emails = db.list_contact_emails(conn, uid)
        assert [(e["type"], e["value"]) for e in emails] == [("Other", "ada@example.com")]

    def test_migration_is_idempotent(self, conn):
        uid = _make_contact(conn, phone="555-9999", email="ada@example.com")
        db.migrate_legacy_contact_phone_email(conn)
        db.migrate_legacy_contact_phone_email(conn)
        db.migrate_legacy_contact_phone_email(conn)
        assert len(db.list_contact_phones(conn, uid)) == 1
        assert len(db.list_contact_emails(conn, uid)) == 1

    def test_no_legacy_value_means_no_spurious_row(self, conn):
        uid = _make_contact(conn)
        db.migrate_legacy_contact_phone_email(conn)
        assert db.list_contact_phones(conn, uid) == []
        assert db.list_contact_emails(conn, uid) == []

    def test_contact_with_real_typed_rows_is_left_alone_even_with_stale_legacy_value(self, conn):
        uid = _make_contact(conn, phone="555-0000")
        db.set_contact_phones(conn, uid, [{"type": "Cell", "value": "555-1111"}, {"type": "Work", "value": "555-2222"}])
        # `contacts.phone` still physically has "555-0000" (nothing clears
        # it -- see db.py's "frozen, not kept live" comment), but the
        # contact already has real typed rows, so migration must not touch it.
        db.migrate_legacy_contact_phone_email(conn)
        phones = db.list_contact_phones(conn, uid)
        assert [(p["type"], p["value"]) for p in phones] == [("Cell", "555-1111"), ("Work", "555-2222")]

    def test_migration_runs_automatically_on_connect(self, tmp_path):
        # No test-only call to migrate_legacy_contact_phone_email here --
        # db.connect's schema setup must run it on its own (init_schema).
        path = tmp_path / "cache.sqlite"
        with db.connect(path) as c:
            db.upsert_contact(c, {
                "uid": "c1", "full_name": "A", "phone": "555-1234",
                "created_at": _now(), "updated_at": _now(),
            })
        with db.connect(path) as c2:
            phones = db.list_contact_phones(c2, "c1")
        assert [(p["type"], p["value"]) for p in phones] == [("Other", "555-1234")]


class TestVcardRoundTrip:
    def test_multiple_phones_round_trip_with_types(self):
        row = {
            "uid": "person-1",
            "full_name": "Jane Doe",
            "phones": [{"type": "Cell", "value": "555-1111"}, {"type": "Work", "value": "555-2222"}],
            "emails": [],
        }
        text = contact_row_to_vcard(row)
        assert "TEL;TYPE=CELL:555-1111" in text
        assert "TEL;TYPE=WORK:555-2222" in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert [(p["type"], p["value"]) for p in result["phones"]] == [("Cell", "555-1111"), ("Work", "555-2222")]

    def test_multiple_emails_round_trip_with_types(self):
        row = {
            "uid": "person-2",
            "full_name": "Jane Doe",
            "phones": [],
            "emails": [{"type": "Home", "value": "jane@home.com"}, {"type": "Work", "value": "jane@work.com"}],
        }
        text = contact_row_to_vcard(row)
        assert "EMAIL;TYPE=HOME:jane@home.com" in text
        assert "EMAIL;TYPE=WORK:jane@work.com" in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert [(e["type"], e["value"]) for e in result["emails"]] == [("Home", "jane@home.com"), ("Work", "jane@work.com")]

    def test_other_type_omits_type_param_both_ways(self):
        row = {"uid": "person-3", "full_name": "X", "phones": [{"type": "Other", "value": "555-0000"}], "emails": []}
        text = contact_row_to_vcard(row)
        assert "TEL:555-0000" in text
        assert "TYPE=OTHER" not in text.upper()
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["phones"] == [{"type": "Other", "value": "555-0000"}]

    def test_unrecognized_vcard_type_token_maps_to_other(self):
        text = (
            "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:person-4\r\nFN:X\r\n"
            "TEL;TYPE=VOICE:555-4444\r\nEND:VCARD\r\n"
        )
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["phones"] == [{"type": "Other", "value": "555-4444"}]

    def test_zero_phones_and_emails_round_trip_with_no_lines(self):
        row = {"uid": "person-5", "full_name": "No Contact Info", "phones": [], "emails": []}
        text = contact_row_to_vcard(row)
        assert "TEL" not in text
        assert "EMAIL" not in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["phones"] == []
        assert result["emails"] == []

    def test_missing_phones_emails_keys_round_trip_with_no_lines(self):
        # A hand-built row dict that never mentions phones/emails at all
        # (not even empty lists) -- must not error, and emits nothing.
        row = {"uid": "person-6", "full_name": "Bare Row"}
        text = contact_row_to_vcard(row)
        assert "TEL" not in text
        assert "EMAIL" not in text


class TestCreateEditFlow:
    def test_create_contact_stores_multiple_phones(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Grace Hopper", title="", org="",
            phone_type=["Cell", "Work"], phone_value=["555-1111", "555-2222"],
            email_type=[], email_value=[],
            address="", tags="", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert [(p["type"], p["value"]) for p in row["phones"]] == [("Cell", "555-1111"), ("Work", "555-2222")]

    def test_create_contact_stores_multiple_emails(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Grace Hopper", title="", org="",
            phone_type=[], phone_value=[],
            email_type=["Home", "Work"], email_value=["g@home.com", "g@work.com"],
            address="", tags="", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert [(e["type"], e["value"]) for e in row["emails"]] == [("Home", "g@home.com"), ("Work", "g@work.com")]

    def test_create_contact_with_no_phone_email_stores_empty_lists(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="No Contact Info", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[],
            address="", tags="", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["phones"] == []
        assert row["emails"] == []

    def test_create_contact_blank_value_row_is_dropped(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Blank Row", title="", org="",
            phone_type=["Home"], phone_value=[""],
            email_type=[], email_value=[],
            address="", tags="", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["phones"] == []

    def test_update_contact_replaces_phone_list(self, conn):
        uid = _make_contact(conn)
        db.set_contact_phones(conn, uid, [{"type": "Home", "value": "111"}])
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", title="", org="",
            phone_type=["Cell"], phone_value=["555-9999"],
            email_type=[], email_value=[],
            address="", tags="", notes="", photo=None, remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert [(p["type"], p["value"]) for p in row["phones"]] == [("Cell", "555-9999")]

    def test_update_contact_can_clear_all_phones(self, conn):
        uid = _make_contact(conn)
        db.set_contact_phones(conn, uid, [{"type": "Home", "value": "111"}])
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[],
            address="", tags="", notes="", photo=None, remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert row["phones"] == []

    def test_create_update_routes_accept_phone_email_array_params(self):
        for fn in (contacts_router.create_contact, contacts_router.update_contact):
            params = inspect.signature(fn).parameters
            assert "phone_type" in params
            assert "phone_value" in params
            assert "email_type" in params
            assert "email_value" in params

    def test_create_update_routes_no_longer_take_flat_phone_email(self):
        for fn in (contacts_router.create_contact, contacts_router.update_contact):
            params = inspect.signature(fn).parameters
            assert "phone" not in params
            assert "email" not in params


class TestSearchMatchesPhoneEmail:
    def test_list_contacts_search_matches_new_phone_table(self, conn):
        uid1 = _make_contact(conn, uid="c1", full_name="Prof A")
        _make_contact(conn, uid="c2", full_name="Classmate B")
        db.set_contact_phones(conn, uid1, [{"type": "Cell", "value": "555-1234"}])

        results = db.list_contacts(conn, q="555-1234")
        assert [r["uid"] for r in results] == ["c1"]

    def test_list_contacts_search_matches_new_email_table(self, conn):
        uid1 = _make_contact(conn, uid="c1", full_name="Prof A")
        _make_contact(conn, uid="c2", full_name="Classmate B")
        db.set_contact_emails(conn, uid1, [{"type": "Work", "value": "prof@university.edu"}])

        results = db.list_contacts(conn, q="university.edu")
        assert [r["uid"] for r in results] == ["c1"]

    def test_route_list_contacts_search_matches_phone(self, conn):
        uid1 = _make_contact(conn, uid="c1", full_name="Prof A")
        _make_contact(conn, uid="c2", full_name="Classmate B")
        db.set_contact_phones(conn, uid1, [{"type": "Cell", "value": "555-1234"}])

        resp = contacts_router.list_contacts(request=_fake_request(), q="555-1234", tag=None, conn=conn)
        uids = [c["uid"] for c in resp.context["contacts"]]
        assert uids == ["c1"]


class TestRenderedMarkup:
    def test_new_contact_form_has_phone_and_email_add_buttons(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert 'name="phone_type"' in body
        assert 'name="phone_value"' in body
        assert 'name="email_type"' in body
        assert 'name="email_value"' in body

    def test_new_contact_form_type_select_has_full_phone_vocabulary(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        for t in ("Home", "Work", "Cell", "Fax", "Pager", "Other"):
            assert f'value="{t}"' in body

    def test_edit_form_prefills_existing_phones(self, conn):
        uid = _make_contact(conn)
        db.set_contact_phones(conn, uid, [{"type": "Cell", "value": "555-4321"}])
        resp = contacts_router.edit_contact_form(uid, _fake_request(f"/contacts/{uid}/edit"), conn=conn)
        body = resp.body.decode()
        assert 'value="555-4321"' in body

    def test_detail_shows_each_phone_with_type_and_tel_link(self, conn):
        uid = _make_contact(conn)
        db.set_contact_phones(conn, uid, [{"type": "Cell", "value": "555-1111"}, {"type": "Work", "value": "555-2222"}])
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert 'href="tel:555-1111"' in body
        assert 'href="tel:555-2222"' in body
        assert "Cell" in body
        assert "Work" in body

    def test_detail_shows_each_email_with_type_and_mailto_link(self, conn):
        uid = _make_contact(conn)
        db.set_contact_emails(conn, uid, [{"type": "Home", "value": "a@home.com"}, {"type": "Work", "value": "a@work.com"}])
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert 'href="mailto:a@home.com"' in body
        assert 'href="mailto:a@work.com"' in body

    def test_list_row_shows_first_phone_only(self, conn):
        _make_contact(conn, uid="c1")
        db.set_contact_phones(conn, "c1", [{"type": "Cell", "value": "555-1111"}, {"type": "Work", "value": "555-2222"}])
        resp = contacts_router.list_contacts(request=_fake_request(), q=None, tag=None, conn=conn)
        body = resp.body.decode()
        assert "555-1111" in body
        assert "555-2222" not in body
