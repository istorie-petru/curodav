"""Contacts field parity with Nextcloud Contacts (plans/open.md), slice 3 of
6 (Title -> Phone/Email -> Website -> Birthday -> Address -> Social network,
per the build order recorded there). Website becomes a genuine multi-value
field: a contact can have any number of websites, each tagged with a
vCard/Nextcloud type (Home/Work/Other -- same vocabulary as email/address,
green-lit, AskUserQuestion, 2026-08-15).

Structured like test_contacts_field_parity_phone_email.py -- same fixture
helpers, same TestSchema/TestVcardRoundTrip/TestCreateEditFlow/
TestSearchMatches*/TestRenderedMarkup breakdown. No TestLegacyMigration
class here: unlike phone/email, there was never a single-value website-ish
column anywhere in this app (confirmed by grepping db.py/vcard_rows.py/
contact_form.html/contact_detail.html for "website"/"url"/"URL" before this
slice started), so there is nothing to auto-migrate.
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
    def test_contact_websites_table_exists(self, conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contact_websites)").fetchall()}
        assert {"uid", "contact_uid", "type", "url", "position", "created_at"} <= cols

    def test_type_vocabulary_matches_vcard_nextcloud(self):
        assert db.CONTACT_WEBSITE_TYPES == ("Home", "Work", "Other")

    def test_set_and_list_contact_websites_round_trip(self, conn):
        uid = _make_contact(conn)
        db.set_contact_websites(conn, uid, [{"type": "Work", "url": "https://work.example.com"}, {"type": "Home", "url": "https://home.example.com"}])
        websites = db.list_contact_websites(conn, uid)
        assert [(w["type"], w["url"]) for w in websites] == [("Work", "https://work.example.com"), ("Home", "https://home.example.com")]

    def test_set_contact_websites_replaces_not_appends(self, conn):
        uid = _make_contact(conn)
        db.set_contact_websites(conn, uid, [{"type": "Home", "url": "https://a.example.com"}])
        db.set_contact_websites(conn, uid, [{"type": "Work", "url": "https://b.example.com"}])
        websites = db.list_contact_websites(conn, uid)
        assert [(w["type"], w["url"]) for w in websites] == [("Work", "https://b.example.com")]

    def test_set_contact_websites_drops_blank_urls(self, conn):
        uid = _make_contact(conn)
        db.set_contact_websites(conn, uid, [{"type": "Home", "url": "  "}, {"type": "Work", "url": "https://b.example.com"}])
        websites = db.list_contact_websites(conn, uid)
        assert [(w["type"], w["url"]) for w in websites] == [("Work", "https://b.example.com")]

    def test_get_contact_attaches_websites(self, conn):
        uid = _make_contact(conn)
        db.set_contact_websites(conn, uid, [{"type": "Work", "url": "https://work.example.com"}])
        row = db.get_contact(conn, uid)
        assert row["websites"][0]["url"] == "https://work.example.com"

    def test_get_contact_websites_empty_by_default(self, conn):
        uid = _make_contact(conn)
        row = db.get_contact(conn, uid)
        assert row["websites"] == []

    def test_delete_contact_cascades_websites(self, conn):
        uid = _make_contact(conn)
        db.set_contact_websites(conn, uid, [{"type": "Home", "url": "https://a.example.com"}])
        db.delete_contact(conn, uid)
        assert db.list_contact_websites(conn, uid) == []


class TestVcardRoundTrip:
    def test_multiple_websites_round_trip_with_types(self):
        row = {
            "uid": "person-1",
            "full_name": "Jane Doe",
            "websites": [{"type": "Home", "url": "https://home.example.com"}, {"type": "Work", "url": "https://work.example.com"}],
        }
        text = contact_row_to_vcard(row)
        assert "URL;TYPE=HOME:https://home.example.com" in text
        assert "URL;TYPE=WORK:https://work.example.com" in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert [(w["type"], w["url"]) for w in result["websites"]] == [("Home", "https://home.example.com"), ("Work", "https://work.example.com")]

    def test_other_type_omits_type_param_both_ways(self):
        row = {"uid": "person-2", "full_name": "X", "websites": [{"type": "Other", "url": "https://other.example.com"}]}
        text = contact_row_to_vcard(row)
        assert "URL:https://other.example.com" in text
        assert "TYPE=OTHER" not in text.upper()
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["websites"] == [{"type": "Other", "url": "https://other.example.com"}]

    def test_unrecognized_vcard_type_token_maps_to_other(self):
        text = (
            "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:person-3\r\nFN:X\r\n"
            "URL;TYPE=BLOG:https://blog.example.com\r\nEND:VCARD\r\n"
        )
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["websites"] == [{"type": "Other", "url": "https://blog.example.com"}]

    def test_zero_websites_round_trip_with_no_lines(self):
        row = {"uid": "person-4", "full_name": "No Websites", "websites": []}
        text = contact_row_to_vcard(row)
        assert "URL" not in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["websites"] == []

    def test_missing_websites_key_round_trips_with_no_lines(self):
        # A hand-built row dict that never mentions websites at all (not
        # even an empty list) -- must not error, and emits nothing.
        row = {"uid": "person-5", "full_name": "Bare Row"}
        text = contact_row_to_vcard(row)
        assert "URL" not in text


class TestCreateEditFlow:
    def test_create_contact_stores_multiple_websites(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Grace Hopper", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[],
            website_type=["Home", "Work"], website_url=["https://home.example.com", "https://work.example.com"], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="", tags="", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert [(w["type"], w["url"]) for w in row["websites"]] == [("Home", "https://home.example.com"), ("Work", "https://work.example.com")]

    def test_create_contact_with_no_website_stores_empty_list(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="No Website", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[],
            website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="", tags="", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["websites"] == []

    def test_create_contact_blank_url_row_is_dropped(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Blank Row", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[],
            website_type=["Home"], website_url=[""], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="", tags="", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["websites"] == []

    def test_update_contact_replaces_website_list(self, conn):
        uid = _make_contact(conn)
        db.set_contact_websites(conn, uid, [{"type": "Home", "url": "https://old.example.com"}])
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[],
            website_type=["Work"], website_url=["https://new.example.com"], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="", tags="", notes="", photo=None, remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert [(w["type"], w["url"]) for w in row["websites"]] == [("Work", "https://new.example.com")]

    def test_update_contact_can_clear_all_websites(self, conn):
        uid = _make_contact(conn)
        db.set_contact_websites(conn, uid, [{"type": "Home", "url": "https://old.example.com"}])
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[],
            website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="", tags="", notes="", photo=None, remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert row["websites"] == []

    def test_create_update_routes_accept_website_array_params(self):
        for fn in (contacts_router.create_contact, contacts_router.update_contact):
            params = inspect.signature(fn).parameters
            assert "website_type" in params
            assert "website_url" in params


class TestSearchMatchesWebsite:
    def test_list_contacts_search_matches_new_website_table(self, conn):
        uid1 = _make_contact(conn, uid="c1", full_name="Prof A")
        _make_contact(conn, uid="c2", full_name="Classmate B")
        db.set_contact_websites(conn, uid1, [{"type": "Work", "url": "https://university.edu/prof-a"}])

        results = db.list_contacts(conn, q="university.edu")
        assert [r["uid"] for r in results] == ["c1"]

    def test_route_list_contacts_search_matches_website(self, conn):
        uid1 = _make_contact(conn, uid="c1", full_name="Prof A")
        _make_contact(conn, uid="c2", full_name="Classmate B")
        db.set_contact_websites(conn, uid1, [{"type": "Work", "url": "https://university.edu/prof-a"}])

        resp = contacts_router.list_contacts(request=_fake_request(), q="university.edu", tag=None, conn=conn)
        uids = [c["uid"] for c in resp.context["contacts"]]
        assert uids == ["c1"]


class TestRenderedMarkup:
    def test_new_contact_form_has_website_add_button(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert 'name="website_type"' in body
        assert 'name="website_url"' in body

    def test_new_contact_form_type_select_has_full_website_vocabulary(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        for t in ("Home", "Work", "Other"):
            assert f'value="{t}"' in body

    def test_edit_form_prefills_existing_websites(self, conn):
        uid = _make_contact(conn)
        db.set_contact_websites(conn, uid, [{"type": "Work", "url": "https://work.example.com"}])
        resp = contacts_router.edit_contact_form(uid, _fake_request(f"/contacts/{uid}/edit"), conn=conn)
        body = resp.body.decode()
        assert 'value="https://work.example.com"' in body

    def test_detail_shows_each_website_with_type_and_link(self, conn):
        uid = _make_contact(conn)
        db.set_contact_websites(conn, uid, [{"type": "Home", "url": "https://home.example.com"}, {"type": "Work", "url": "https://work.example.com"}])
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert 'href="https://home.example.com" target="_blank" rel="noopener"' in body
        assert 'href="https://work.example.com" target="_blank" rel="noopener"' in body
        assert "Home" in body
        assert "Work" in body

    def test_list_row_does_not_show_website(self, conn):
        # Decision recorded in the slice's own docs: website is left off the
        # compact contacts-list row subtitle (org/title/phone/email are the
        # more useful subtitle fields) -- unlike phone/email, no "first
        # entry" rendering is added to contacts_list.html/_widget_contact_
        # list.html for websites.
        _make_contact(conn, uid="c1")
        db.set_contact_websites(conn, "c1", [{"type": "Work", "url": "https://work.example.com"}])
        resp = contacts_router.list_contacts(request=_fake_request(), q=None, tag=None, conn=conn)
        body = resp.body.decode()
        assert "work.example.com" not in body


class TestTypePickerIsCustomDropdown:
    """audit-fixes-2.1.md ("Contacts edit modal window doesn't use the
    custom drop down menus") -- same swap as
    test_contacts_field_parity_phone_email.py's identically-named class
    (see that file for the full rationale); this file's own coverage for
    Website's `website_type`."""

    def test_native_select_is_gone(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert '<select name="website_type">' not in body

    def test_custom_dropdown_markup_present(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert "contact-type-select" in body
        assert 'data-ms-mode="single"' in body

    def test_radio_never_carries_the_real_submitted_field_name(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert '<input type="radio" name="website_type"' not in body

    def test_each_row_gets_a_distinct_radio_group_and_proxy_id(self, conn):
        uid = _make_contact(conn)
        db.set_contact_websites(conn, uid, [{"type": "Work", "url": "https://work.example.com"}, {"type": "Home", "url": "https://home.example.com"}])
        resp = contacts_router.edit_contact_form(uid, _fake_request(f"/contacts/{uid}/edit"), conn=conn)
        body = resp.body.decode()
        assert 'id="website_type-proxy-1" name="website_type" value="Work"' in body
        assert 'id="website_type-proxy-2" name="website_type" value="Home"' in body

    def test_hidden_proxy_still_carries_the_real_field_name(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert '<input type="hidden" id="website_type-proxy-tmpl" name="website_type"' in body
