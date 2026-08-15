"""Contacts field parity with Nextcloud Contacts (plans/open.md), slice 1 of
6 (Title -> Phone/Email -> Website -> Birthday -> Address -> Social network,
per the build order recorded there). Title is the vCard TITLE property (a
person's job title, e.g. "Software Engineer") -- distinct from `org` (their
organization's name, vCard ORG).

Green-lit answers (AskUserQuestion, 2026-08-15) that shaped later slices in
this build order but don't affect this one directly: vCard/Nextcloud type
vocabulary for multi-value fields, auto-migrate-as-"Other" for existing
single-value data, full vCard ADR structure for Address, both full and
year-less Birthday dates, and X-SOCIALPROFILE for Social network.
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
    def test_contacts_table_has_title_column(self, conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
        assert "title" in cols

    def test_upsert_and_get_round_trip_title(self, conn):
        uid = _make_contact(conn, title="Software Engineer")
        row = db.get_contact(conn, uid)
        assert row["title"] == "Software Engineer"

    def test_title_defaults_to_none(self, conn):
        uid = _make_contact(conn)
        row = db.get_contact(conn, uid)
        assert row["title"] is None


class TestVcardRoundTrip:
    def test_title_round_trips_through_vcard(self):
        row = {
            "uid": "person-1",
            "full_name": "Jane Doe",
            "title": "Chief Engineer",
            "org": "Acme",
        }
        text = contact_row_to_vcard(row)
        assert "TITLE:Chief Engineer" in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["title"] == "Chief Engineer"
        assert result["org"] == "Acme"

    def test_missing_title_is_absent_both_ways(self):
        row = {"uid": "person-2", "full_name": "No Title Here"}
        text = contact_row_to_vcard(row)
        assert "TITLE" not in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert "title" not in result


class TestCreateEditFlow:
    def test_create_contact_stores_title(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Grace Hopper", title="Rear Admiral", org="Navy",
            phone_type=[], phone_value=[], email_type=[], email_value=[],
            address="", tags="", notes="",
            photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["title"] == "Rear Admiral"

    def test_create_contact_blank_title_stores_none(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="No Title", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[],
            address="", tags="", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["title"] is None

    def test_update_contact_changes_title(self, conn):
        uid = _make_contact(conn, title="Intern")
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", title="Senior Engineer",
            org="", phone_type=[], phone_value=[], email_type=[], email_value=[],
            address="", tags="", notes="",
            photo=None, remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert row["title"] == "Senior Engineer"

    def test_update_contact_can_clear_title(self, conn):
        uid = _make_contact(conn, title="Intern")
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[],
            address="", tags="", notes="", photo=None,
            remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert row["title"] is None

    def test_create_update_routes_accept_title_param(self):
        for fn in (contacts_router.create_contact, contacts_router.update_contact):
            assert "title" in inspect.signature(fn).parameters


class TestSearchMatchesTitle:
    def test_list_contacts_search_matches_title(self, conn):
        _make_contact(conn, uid="c1", full_name="Prof A", title="Professor of Physics")
        _make_contact(conn, uid="c2", full_name="Classmate B", title="Student")

        results = db.list_contacts(conn, q="Physics")
        assert [r["uid"] for r in results] == ["c1"]

    def test_route_list_contacts_search_matches_title(self, conn):
        _make_contact(conn, uid="c1", full_name="Prof A", title="Professor of Physics")
        _make_contact(conn, uid="c2", full_name="Classmate B", title="Student")

        resp = contacts_router.list_contacts(request=_fake_request(), q="Physics", tag=None, conn=conn)
        uids = [c["uid"] for c in resp.context["contacts"]]
        assert uids == ["c1"]


class TestRenderedMarkup:
    def test_new_contact_form_has_title_field(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert 'name="title"' in body

    def test_edit_form_prefills_existing_title(self, conn):
        uid = _make_contact(conn, title="Chief Engineer")
        resp = contacts_router.edit_contact_form(uid, _fake_request(f"/contacts/{uid}/edit"), conn=conn)
        body = resp.body.decode()
        assert 'value="Chief Engineer"' in body

    def test_detail_shows_title_and_org_combined(self, conn):
        uid = _make_contact(conn, title="Chief Engineer", org="Acme")
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert "Chief Engineer at Acme" in body

    def test_detail_shows_title_alone_when_no_org(self, conn):
        uid = _make_contact(conn, title="Freelancer", org=None)
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert "Freelancer" in body

    def test_list_row_shows_title_and_org_combined(self, conn):
        _make_contact(conn, uid="c1", title="Chief Engineer", org="Acme")
        resp = contacts_router.list_contacts(request=_fake_request(), q=None, tag=None, conn=conn)
        body = resp.body.decode()
        assert "Chief Engineer at Acme" in body
