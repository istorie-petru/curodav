"""Contacts field parity with Nextcloud Contacts (plans/open.md), slice 5 of
6 (Title -> Phone/Email -> Website -> Birthday -> Address -> Social network,
per the build order recorded there). Address becomes a genuine structured,
multi-value field: a contact can have any number of addresses, each tagged
Home/Work/Other (same vocabulary as email/website, green-lit,
AskUserQuestion, 2026-08-15) and carrying the full vCard ADR structure (PO
Box, Extended, Street, City, Region, Postal code, Country).

Structured like test_contacts_field_parity_phone_email.py -- same fixture
helpers, same TestSchema/TestLegacyMigration/TestVcardRoundTrip/
TestCreateEditFlow/TestRenderedMarkup breakdown. Unlike phone/email/website,
there IS a legacy single-value column to migrate from (`contacts.address`),
same shape as phone/email's own TestLegacyMigration. No TestSearchMatches*
class -- Address stays deliberately NOT searched, same precedent Birthday
established (plans/open.md)."""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from pathlib import Path

import pytest
import vobject
from starlette.requests import Request

from src import db
from src.deps import _fmt_address
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


# create_contact/update_contact take a large fixed set of multi-value form
# arrays now (phone/email/website/address/social) -- since these tests call
# the router functions directly (bypassing FastAPI's own request parsing),
# every one of those params must be passed explicitly or it's left as the
# raw `Form(...)` sentinel object, not an actual empty list. This bundles
# the ones this file doesn't care about so each test only spells out the
# address_*/social_* fields it's actually exercising.
_BASE_KWARGS = dict(
    title="", org="",
    phone_type=[], phone_value=[], email_type=[], email_value=[],
    website_type=[], website_url=[],
    social_type=[], social_value=[],
    birthday="", tags="", notes="", photo=None,
)


class TestSchema:
    def test_contact_addresses_table_exists(self, conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contact_addresses)").fetchall()}
        assert {
            "uid", "contact_uid", "type", "po_box", "extended", "street",
            "city", "region", "postal_code", "country", "position", "created_at",
        } <= cols

    def test_type_vocabulary_matches_vcard_nextcloud(self):
        assert db.CONTACT_ADDRESS_TYPES == ("Home", "Work", "Other")

    def test_set_and_list_contact_addresses_round_trip(self, conn):
        uid = _make_contact(conn)
        db.set_contact_addresses(conn, uid, [
            {"type": "Home", "street": "1 Home St", "city": "Springfield"},
            {"type": "Work", "street": "2 Work Ave", "city": "Metropolis"},
        ])
        addresses = db.list_contact_addresses(conn, uid)
        assert [(a["type"], a["street"], a["city"]) for a in addresses] == [
            ("Home", "1 Home St", "Springfield"),
            ("Work", "2 Work Ave", "Metropolis"),
        ]

    def test_set_contact_addresses_replaces_not_appends(self, conn):
        uid = _make_contact(conn)
        db.set_contact_addresses(conn, uid, [{"type": "Home", "street": "Old St"}])
        db.set_contact_addresses(conn, uid, [{"type": "Work", "street": "New St"}])
        addresses = db.list_contact_addresses(conn, uid)
        assert [(a["type"], a["street"]) for a in addresses] == [("Work", "New St")]

    def test_set_contact_addresses_drops_fully_blank_rows(self, conn):
        uid = _make_contact(conn)
        db.set_contact_addresses(conn, uid, [
            {"type": "Home", "po_box": "", "extended": "", "street": "", "city": "", "region": "", "postal_code": "", "country": ""},
            {"type": "Work", "street": "Real St"},
        ])
        addresses = db.list_contact_addresses(conn, uid)
        assert [(a["type"], a["street"]) for a in addresses] == [("Work", "Real St")]

    def test_set_contact_addresses_keeps_row_with_only_one_field_set(self, conn):
        # A row is only dropped when EVERY structured field is blank --
        # unlike phone/email/website's single `value`, a real address could
        # legitimately have just a city and no street.
        uid = _make_contact(conn)
        db.set_contact_addresses(conn, uid, [{"type": "Home", "city": "Springfield"}])
        addresses = db.list_contact_addresses(conn, uid)
        assert [(a["type"], a["city"]) for a in addresses] == [("Home", "Springfield")]

    def test_get_contact_attaches_addresses(self, conn):
        uid = _make_contact(conn)
        db.set_contact_addresses(conn, uid, [{"type": "Home", "street": "1 Home St"}])
        row = db.get_contact(conn, uid)
        assert row["addresses"][0]["street"] == "1 Home St"

    def test_get_contact_addresses_empty_by_default(self, conn):
        uid = _make_contact(conn)
        row = db.get_contact(conn, uid)
        assert row["addresses"] == []

    def test_delete_contact_cascades_addresses(self, conn):
        uid = _make_contact(conn)
        db.set_contact_addresses(conn, uid, [{"type": "Home", "street": "1 Home St"}])
        db.delete_contact(conn, uid)
        assert db.list_contact_addresses(conn, uid) == []


class TestLegacyMigration:
    def test_legacy_address_migrates_as_other_into_street(self, conn):
        uid = _make_contact(conn, address="123 Old Freeform Ave")
        db.migrate_legacy_contact_address(conn)
        addresses = db.list_contact_addresses(conn, uid)
        assert [(a["type"], a["street"], a["city"]) for a in addresses] == [("Other", "123 Old Freeform Ave", "")]

    def test_migration_is_idempotent(self, conn):
        uid = _make_contact(conn, address="123 Old Freeform Ave")
        db.migrate_legacy_contact_address(conn)
        db.migrate_legacy_contact_address(conn)
        db.migrate_legacy_contact_address(conn)
        assert len(db.list_contact_addresses(conn, uid)) == 1

    def test_no_legacy_value_means_no_spurious_row(self, conn):
        uid = _make_contact(conn)
        db.migrate_legacy_contact_address(conn)
        assert db.list_contact_addresses(conn, uid) == []

    def test_contact_with_real_typed_rows_is_left_alone_even_with_stale_legacy_value(self, conn):
        uid = _make_contact(conn, address="Stale Legacy Value")
        db.set_contact_addresses(conn, uid, [{"type": "Home", "street": "Real St"}])
        db.migrate_legacy_contact_address(conn)
        addresses = db.list_contact_addresses(conn, uid)
        assert [(a["type"], a["street"]) for a in addresses] == [("Home", "Real St")]

    def test_migration_runs_automatically_on_connect(self, tmp_path):
        path = tmp_path / "cache.sqlite"
        with db.connect(path) as c:
            db.upsert_contact(c, {
                "uid": "c1", "full_name": "A", "address": "123 Old Freeform Ave",
                "created_at": _now(), "updated_at": _now(),
            })
        with db.connect(path) as c2:
            addresses = db.list_contact_addresses(c2, "c1")
        assert [(a["type"], a["street"]) for a in addresses] == [("Other", "123 Old Freeform Ave")]


class TestVcardRoundTrip:
    def test_multiple_addresses_round_trip_with_types_and_full_structure(self):
        row = {
            "uid": "person-1",
            "full_name": "Jane Doe",
            "addresses": [
                {
                    "type": "Home", "po_box": "PB1", "extended": "Apt 2",
                    "street": "123 Main St", "city": "Springfield",
                    "region": "IL", "postal_code": "62704", "country": "USA",
                },
                {"type": "Work", "street": "456 Work Ave", "city": "Metropolis"},
            ],
        }
        text = contact_row_to_vcard(row)
        assert "ADR;TYPE=HOME:PB1;Apt 2;123 Main St;Springfield;IL;62704;USA" in text
        assert "ADR;TYPE=WORK:;;456 Work Ave;Metropolis;;;" in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["addresses"][0] == row["addresses"][0]
        assert result["addresses"][1]["type"] == "Work"
        assert result["addresses"][1]["street"] == "456 Work Ave"
        assert result["addresses"][1]["city"] == "Metropolis"

    def test_other_type_omits_type_param_both_ways(self):
        row = {"uid": "person-2", "full_name": "X", "addresses": [{"type": "Other", "street": "Somewhere"}]}
        text = contact_row_to_vcard(row)
        assert "ADR:" in text
        assert "TYPE=OTHER" not in text.upper()
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["addresses"][0]["type"] == "Other"
        assert result["addresses"][0]["street"] == "Somewhere"

    def test_unrecognized_vcard_type_token_maps_to_other(self):
        text = (
            "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:person-3\r\nFN:X\r\n"
            "ADR;TYPE=SHIPPING:;;789 Dock Rd;Port City;;;\r\nEND:VCARD\r\n"
        )
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["addresses"][0]["type"] == "Other"
        assert result["addresses"][0]["street"] == "789 Dock Rd"

    def test_zero_addresses_round_trip_with_no_lines(self):
        row = {"uid": "person-4", "full_name": "No Addresses", "addresses": []}
        text = contact_row_to_vcard(row)
        assert "ADR" not in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["addresses"] == []

    def test_missing_addresses_key_round_trips_with_no_lines(self):
        row = {"uid": "person-5", "full_name": "Bare Row"}
        text = contact_row_to_vcard(row)
        assert "ADR" not in text

    def test_fully_blank_address_entry_emits_no_line(self):
        row = {"uid": "person-6", "full_name": "Blank Entry", "addresses": [{"type": "Home"}]}
        text = contact_row_to_vcard(row)
        assert "ADR" not in text


class TestCreateEditFlow:
    def test_create_contact_stores_multiple_addresses(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Grace Hopper", **_BASE_KWARGS,
            address_type=["Home", "Work"],
            address_po_box=["", ""], address_extended=["", ""],
            address_street=["1 Home St", "2 Work Ave"],
            address_city=["Springfield", "Metropolis"],
            address_region=["", ""], address_postal_code=["", ""], address_country=["", ""],
            conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert [(a["type"], a["street"], a["city"]) for a in row["addresses"]] == [
            ("Home", "1 Home St", "Springfield"),
            ("Work", "2 Work Ave", "Metropolis"),
        ]

    def test_create_contact_with_no_address_stores_empty_list(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="No Address", **_BASE_KWARGS,
            address_type=[], address_po_box=[], address_extended=[], address_street=[],
            address_city=[], address_region=[], address_postal_code=[], address_country=[],
            conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["addresses"] == []

    def test_create_contact_fully_blank_row_is_dropped(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Blank Row", **_BASE_KWARGS,
            address_type=["Home"], address_po_box=[""], address_extended=[""], address_street=[""],
            address_city=[""], address_region=[""], address_postal_code=[""], address_country=[""],
            conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["addresses"] == []

    def test_update_contact_replaces_address_list(self, conn):
        uid = _make_contact(conn)
        db.set_contact_addresses(conn, uid, [{"type": "Home", "street": "Old St"}])
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", **_BASE_KWARGS,
            address_type=["Work"], address_po_box=[""], address_extended=[""], address_street=["New St"],
            address_city=[""], address_region=[""], address_postal_code=[""], address_country=[""],
            remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert [(a["type"], a["street"]) for a in row["addresses"]] == [("Work", "New St")]

    def test_update_contact_can_clear_all_addresses(self, conn):
        uid = _make_contact(conn)
        db.set_contact_addresses(conn, uid, [{"type": "Home", "street": "Old St"}])
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", **_BASE_KWARGS,
            address_type=[], address_po_box=[], address_extended=[], address_street=[],
            address_city=[], address_region=[], address_postal_code=[], address_country=[],
            remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert row["addresses"] == []

    def test_create_update_routes_accept_address_array_params(self):
        for fn in (contacts_router.create_contact, contacts_router.update_contact):
            params = inspect.signature(fn).parameters
            for name in (
                "address_type", "address_po_box", "address_extended", "address_street",
                "address_city", "address_region", "address_postal_code", "address_country",
            ):
                assert name in params

    def test_create_update_routes_no_longer_accept_bare_address_param(self):
        # The old single-value `address: str = Form("")` param is gone --
        # superseded entirely by the address_*[] arrays above.
        for fn in (contacts_router.create_contact, contacts_router.update_contact):
            assert "address" not in inspect.signature(fn).parameters


class TestFormatContactAddress:
    def test_full_address_formats_as_vcard_style_multiline(self):
        addr = {
            "po_box": "PB1", "extended": "Apt 2", "street": "123 Main St",
            "city": "Springfield", "region": "IL", "postal_code": "62704", "country": "USA",
        }
        assert db.format_contact_address(addr) == "PB1\nApt 2\n123 Main St\nSpringfield, IL 62704\nUSA"

    def test_partial_address_omits_blank_lines(self):
        addr = {"street": "456 Elm St", "city": "Metropolis"}
        assert db.format_contact_address(addr) == "456 Elm St\nMetropolis"

    def test_city_only_has_no_stray_comma(self):
        addr = {"city": "Springfield"}
        assert db.format_contact_address(addr) == "Springfield"

    def test_jinja_filter_delegates_to_db_function(self):
        addr = {"street": "1 St", "city": "Town"}
        assert _fmt_address(addr) == db.format_contact_address(addr)


class TestRenderedMarkup:
    def test_new_contact_form_has_address_add_button(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert 'name="address_type"' in body
        assert 'name="address_street"' in body
        assert 'name="address_city"' in body
        assert 'name="address_country"' in body

    def test_new_contact_form_type_select_has_full_address_vocabulary(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        for t in ("Home", "Work", "Other"):
            assert f'value="{t}"' in body

    def test_new_contact_form_has_no_bare_address_input(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert 'name="address"' not in body

    def test_edit_form_prefills_existing_address(self, conn):
        uid = _make_contact(conn)
        db.set_contact_addresses(conn, uid, [{"type": "Work", "street": "1 Work Blvd", "city": "Gotham"}])
        resp = contacts_router.edit_contact_form(uid, _fake_request(f"/contacts/{uid}/edit"), conn=conn)
        body = resp.body.decode()
        assert 'value="1 Work Blvd"' in body
        assert 'value="Gotham"' in body

    def test_detail_shows_each_address_with_type_and_formatted_lines(self, conn):
        uid = _make_contact(conn)
        db.set_contact_addresses(conn, uid, [
            {"type": "Home", "street": "1 Home St", "city": "Springfield", "region": "IL", "postal_code": "62704"},
            {"type": "Work", "street": "2 Work Ave", "city": "Metropolis"},
        ])
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert "1 Home St" in body
        assert "Springfield, IL 62704" in body
        assert "2 Work Ave" in body
        assert "Metropolis" in body
        assert "Home" in body
        assert "Work" in body

    def test_detail_does_not_show_address_section_when_none(self, conn):
        uid = _make_contact(conn)
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert "Address (" not in body


class TestTypePickerIsCustomDropdown:
    """audit-fixes-2.1.md ("Contacts edit modal window doesn't use the
    custom drop down menus") -- same swap as
    test_contacts_field_parity_phone_email.py's identically-named class
    (see that file for the full rationale); this file's own coverage for
    Address's `address_type`."""

    def test_native_select_is_gone(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert '<select name="address_type">' not in body

    def test_custom_dropdown_markup_present(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert "contact-type-select" in body
        assert 'data-ms-mode="single"' in body

    def test_radio_never_carries_the_real_submitted_field_name(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert '<input type="radio" name="address_type"' not in body

    def test_each_row_gets_a_distinct_radio_group_and_proxy_id(self, conn):
        uid = _make_contact(conn)
        db.set_contact_addresses(conn, uid, [
            {"type": "Home", "street": "1 Home St"},
            {"type": "Work", "street": "2 Work Ave"},
        ])
        resp = contacts_router.edit_contact_form(uid, _fake_request(f"/contacts/{uid}/edit"), conn=conn)
        body = resp.body.decode()
        assert 'id="address_type-proxy-1" name="address_type" value="Home"' in body
        assert 'id="address_type-proxy-2" name="address_type" value="Work"' in body

    def test_hidden_proxy_still_carries_the_real_field_name(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert '<input type="hidden" id="address_type-proxy-tmpl" name="address_type"' in body

    def test_picker_still_renders_inside_the_address_row(self, conn):
        # The old `.contact-address-row select{width:140px}` CSS override
        # became `.contact-address-row .contact-type-select{width:140px}`
        # (style.css) -- confirm the picker still renders inside a
        # `.contact-address-row` so that ancestor-scoped rule still reaches
        # it (no `extra_class` needed on the macro call, see
        # _contact_type_picker.html's own comment on why).
        uid = _make_contact(conn)
        db.set_contact_addresses(conn, uid, [{"type": "Home", "street": "1 Home St"}])
        resp = contacts_router.edit_contact_form(uid, _fake_request(f"/contacts/{uid}/edit"), conn=conn)
        body = resp.body.decode()
        row = body.split('<div class="contact-multi-row contact-address-row">')[1]
        assert "contact-type-select" in row.split("contact-address-fields")[0]
