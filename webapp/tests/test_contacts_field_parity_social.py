"""Contacts field parity with Nextcloud Contacts (plans/open.md), slice 6 of
6 (Title -> Phone/Email -> Website -> Birthday -> Address -> Social network,
per the build order recorded there) -- the last field, closing out this
effort. Social network round-trips via the standard `X-SOCIALPROFILE` vCard
property (green-lit, AskUserQuestion, 2026-08-15): a contact can have any
number of social profiles, each tagged with a network name (Twitter/
Facebook/Instagram/LinkedIn/Mastodon/GitHub/Other -- db.CONTACT_SOCIAL_TYPES),
not the Home/Work/Other vocabulary every other typed contact field uses.

Structured like test_contacts_field_parity_website.py -- same fixture
helpers, same TestSchema/TestVcardRoundTrip/TestCreateEditFlow/
TestRenderedMarkup breakdown. No TestLegacyMigration class -- no pre-
existing single-value social-network column ever existed on this app
(confirmed by grep before this slice started), so there is nothing to
auto-migrate, same situation as Website. No TestSearchMatches* class either
-- not part of the green-lit spec and not asked for; kept consistent with
Address (also not searched)."""

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


# Same "every multi-value form array must be passed explicitly" situation as
# test_contacts_field_parity_address.py -- create_contact/update_contact
# called directly bypass FastAPI's own Form(...) default resolution.
_BASE_KWARGS = dict(
    title="", org="",
    phone_type=[], phone_value=[], email_type=[], email_value=[],
    website_type=[], website_url=[],
    address_type=[], address_po_box=[], address_extended=[], address_street=[],
    address_city=[], address_region=[], address_postal_code=[], address_country=[],
    birthday="", tags="", notes="", photo=None,
)


class TestSchema:
    def test_contact_social_profiles_table_exists(self, conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contact_social_profiles)").fetchall()}
        assert {"uid", "contact_uid", "type", "value", "position", "created_at"} <= cols

    def test_type_vocabulary_is_network_names_not_home_work(self):
        assert db.CONTACT_SOCIAL_TYPES == ("Twitter", "Facebook", "Instagram", "LinkedIn", "Mastodon", "GitHub", "Other")

    def test_set_and_list_contact_social_profiles_round_trip(self, conn):
        uid = _make_contact(conn)
        db.set_contact_social_profiles(conn, uid, [
            {"type": "Twitter", "value": "https://twitter.com/ada"},
            {"type": "GitHub", "value": "https://github.com/ada"},
        ])
        profiles = db.list_contact_social_profiles(conn, uid)
        assert [(p["type"], p["value"]) for p in profiles] == [
            ("Twitter", "https://twitter.com/ada"),
            ("GitHub", "https://github.com/ada"),
        ]

    def test_set_contact_social_profiles_replaces_not_appends(self, conn):
        uid = _make_contact(conn)
        db.set_contact_social_profiles(conn, uid, [{"type": "Twitter", "value": "https://twitter.com/old"}])
        db.set_contact_social_profiles(conn, uid, [{"type": "Facebook", "value": "https://facebook.com/new"}])
        profiles = db.list_contact_social_profiles(conn, uid)
        assert [(p["type"], p["value"]) for p in profiles] == [("Facebook", "https://facebook.com/new")]

    def test_set_contact_social_profiles_drops_blank_values(self, conn):
        uid = _make_contact(conn)
        db.set_contact_social_profiles(conn, uid, [
            {"type": "Twitter", "value": "  "},
            {"type": "GitHub", "value": "https://github.com/ada"},
        ])
        profiles = db.list_contact_social_profiles(conn, uid)
        assert [(p["type"], p["value"]) for p in profiles] == [("GitHub", "https://github.com/ada")]

    def test_get_contact_attaches_social_profiles(self, conn):
        uid = _make_contact(conn)
        db.set_contact_social_profiles(conn, uid, [{"type": "Twitter", "value": "https://twitter.com/ada"}])
        row = db.get_contact(conn, uid)
        assert row["social_profiles"][0]["value"] == "https://twitter.com/ada"

    def test_get_contact_social_profiles_empty_by_default(self, conn):
        uid = _make_contact(conn)
        row = db.get_contact(conn, uid)
        assert row["social_profiles"] == []

    def test_delete_contact_cascades_social_profiles(self, conn):
        uid = _make_contact(conn)
        db.set_contact_social_profiles(conn, uid, [{"type": "Twitter", "value": "https://twitter.com/ada"}])
        db.delete_contact(conn, uid)
        assert db.list_contact_social_profiles(conn, uid) == []


class TestVcardRoundTrip:
    def test_multiple_social_profiles_round_trip_with_types(self):
        row = {
            "uid": "person-1",
            "full_name": "Jane Doe",
            "social_profiles": [
                {"type": "Twitter", "value": "https://twitter.com/jane"},
                {"type": "GitHub", "value": "https://github.com/jane"},
            ],
        }
        text = contact_row_to_vcard(row)
        assert "X-SOCIALPROFILE;TYPE=TWITTER:https://twitter.com/jane" in text
        assert "X-SOCIALPROFILE;TYPE=GITHUB:https://github.com/jane" in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert [(p["type"], p["value"]) for p in result["social_profiles"]] == [
            ("Twitter", "https://twitter.com/jane"),
            ("GitHub", "https://github.com/jane"),
        ]

    def test_other_type_omits_type_param_both_ways(self):
        row = {"uid": "person-2", "full_name": "X", "social_profiles": [{"type": "Other", "value": "https://myspace.com/x"}]}
        text = contact_row_to_vcard(row)
        assert "X-SOCIALPROFILE:https://myspace.com/x" in text
        assert "TYPE=OTHER" not in text.upper()
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["social_profiles"] == [{"type": "Other", "value": "https://myspace.com/x"}]

    def test_unrecognized_vcard_type_token_maps_to_other(self):
        text = (
            "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:person-3\r\nFN:X\r\n"
            "X-SOCIALPROFILE;TYPE=TIKTOK:https://tiktok.com/@x\r\nEND:VCARD\r\n"
        )
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["social_profiles"] == [{"type": "Other", "value": "https://tiktok.com/@x"}]

    def test_zero_social_profiles_round_trip_with_no_lines(self):
        row = {"uid": "person-4", "full_name": "No Profiles", "social_profiles": []}
        text = contact_row_to_vcard(row)
        assert "SOCIALPROFILE" not in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["social_profiles"] == []

    def test_missing_social_profiles_key_round_trips_with_no_lines(self):
        row = {"uid": "person-5", "full_name": "Bare Row"}
        text = contact_row_to_vcard(row)
        assert "SOCIALPROFILE" not in text


class TestCreateEditFlow:
    def test_create_contact_stores_multiple_social_profiles(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Grace Hopper", **_BASE_KWARGS,
            social_type=["Twitter", "LinkedIn"],
            social_value=["https://twitter.com/grace", "https://linkedin.com/in/grace"],
            conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert [(s["type"], s["value"]) for s in row["social_profiles"]] == [
            ("Twitter", "https://twitter.com/grace"),
            ("LinkedIn", "https://linkedin.com/in/grace"),
        ]

    def test_create_contact_with_no_social_profile_stores_empty_list(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="No Social", **_BASE_KWARGS, social_type=[], social_value=[], conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["social_profiles"] == []

    def test_create_contact_blank_value_row_is_dropped(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Blank Row", **_BASE_KWARGS, social_type=["Twitter"], social_value=[""], conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["social_profiles"] == []

    def test_update_contact_replaces_social_profile_list(self, conn):
        uid = _make_contact(conn)
        db.set_contact_social_profiles(conn, uid, [{"type": "Twitter", "value": "https://twitter.com/old"}])
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", **_BASE_KWARGS,
            social_type=["GitHub"], social_value=["https://github.com/ada"],
            remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert [(s["type"], s["value"]) for s in row["social_profiles"]] == [("GitHub", "https://github.com/ada")]

    def test_update_contact_can_clear_all_social_profiles(self, conn):
        uid = _make_contact(conn)
        db.set_contact_social_profiles(conn, uid, [{"type": "Twitter", "value": "https://twitter.com/old"}])
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", **_BASE_KWARGS,
            social_type=[], social_value=[],
            remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert row["social_profiles"] == []

    def test_create_update_routes_accept_social_array_params(self):
        for fn in (contacts_router.create_contact, contacts_router.update_contact):
            params = inspect.signature(fn).parameters
            assert "social_type" in params
            assert "social_value" in params


class TestRenderedMarkup:
    def test_new_contact_form_has_social_add_button(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert 'name="social_type"' in body
        assert 'name="social_value"' in body

    def test_new_contact_form_type_select_has_full_social_vocabulary(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        for t in db.CONTACT_SOCIAL_TYPES:
            assert f'value="{t}"' in body

    def test_edit_form_prefills_existing_social_profiles(self, conn):
        uid = _make_contact(conn)
        db.set_contact_social_profiles(conn, uid, [{"type": "GitHub", "value": "https://github.com/ada"}])
        resp = contacts_router.edit_contact_form(uid, _fake_request(f"/contacts/{uid}/edit"), conn=conn)
        body = resp.body.decode()
        assert 'value="https://github.com/ada"' in body

    def test_detail_shows_url_shaped_profile_as_external_link(self, conn):
        uid = _make_contact(conn)
        db.set_contact_social_profiles(conn, uid, [{"type": "Twitter", "value": "https://twitter.com/ada"}])
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert 'href="https://twitter.com/ada" target="_blank" rel="noopener"' in body
        assert "Twitter" in body

    def test_detail_shows_bare_handle_as_plain_text_not_a_link(self, conn):
        uid = _make_contact(conn)
        db.set_contact_social_profiles(conn, uid, [{"type": "Mastodon", "value": "@ada@fosstodon.org"}])
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert "@ada@fosstodon.org" in body
        assert 'href="@ada@fosstodon.org"' not in body

    def test_detail_does_not_show_social_section_when_none(self, conn):
        uid = _make_contact(conn)
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert 'detail-meta-label">Social' not in body


class TestTypePickerIsCustomDropdown:
    """audit-fixes-2.1.md ("Contacts edit modal window doesn't use the
    custom drop down menus") -- same swap as
    test_contacts_field_parity_phone_email.py's identically-named class
    (see that file for the full rationale); this file's own coverage for
    Social network's `social_type`."""

    def test_native_select_is_gone(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert '<select name="social_type">' not in body

    def test_custom_dropdown_markup_present(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert "contact-type-select" in body
        assert 'data-ms-mode="single"' in body

    def test_radio_never_carries_the_real_submitted_field_name(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert '<input type="radio" name="social_type"' not in body

    def test_each_row_gets_a_distinct_radio_group_and_proxy_id(self, conn):
        uid = _make_contact(conn)
        db.set_contact_social_profiles(conn, uid, [{"type": "Twitter", "value": "https://twitter.com/ada"}, {"type": "Mastodon", "value": "@ada@fosstodon.org"}])
        resp = contacts_router.edit_contact_form(uid, _fake_request(f"/contacts/{uid}/edit"), conn=conn)
        body = resp.body.decode()
        assert 'id="social_type-proxy-1" name="social_type" value="Twitter"' in body
        assert 'id="social_type-proxy-2" name="social_type" value="Mastodon"' in body

    def test_hidden_proxy_still_carries_the_real_field_name(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert '<input type="hidden" id="social_type-proxy-tmpl" name="social_type"' in body
