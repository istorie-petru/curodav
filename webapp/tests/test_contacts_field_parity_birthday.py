"""Contacts field parity with Nextcloud Contacts (plans/open.md), slice 4 of
6 (Title -> Phone/Email -> Website -> Birthday -> Address -> Social network,
per the build order recorded there). Birthday is single-value (unlike Phone/
Email/Website -- a contact has at most one), stored raw as vCard's own BDAY
text: either a full "YYYY-MM-DD" date, or a year-less "--MM-DD" date
(green-lit, AskUserQuestion, 2026-08-15).

Structured like test_contacts_field_parity_title.py (the other single-value
slice) -- same fixture helpers, same TestSchema/TestParsing/TestVcardRoundTrip/
TestCreateEditFlow/TestRenderedMarkup breakdown. No TestSearchMatches* class
here: a birthday's raw stored text isn't a meaningful thing to substring-
search (unlike a name/org/phone/email/url), and address -- the other
already-shipped single-value field -- isn't searched either, so leaving
birthday out of `db._search_contacts`/`db.list_contacts` matches that
precedent rather than inventing a new one.
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
        "birthday": None,
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
    def test_contacts_table_has_birthday_column(self, conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
        assert "birthday" in cols

    def test_upsert_and_get_contact_round_trip_full_date(self, conn):
        uid = _make_contact(conn, birthday="1990-05-17")
        row = db.get_contact(conn, uid)
        assert row["birthday"] == "1990-05-17"

    def test_upsert_and_get_contact_round_trip_yearless_date(self, conn):
        uid = _make_contact(conn, birthday="--05-17")
        row = db.get_contact(conn, uid)
        assert row["birthday"] == "--05-17"

    def test_get_contact_birthday_none_by_default(self, conn):
        uid = _make_contact(conn)
        row = db.get_contact(conn, uid)
        assert row["birthday"] is None


class TestParsing:
    def test_parse_full_date(self):
        assert db.parse_contact_birthday("1990-05-17") == "1990-05-17"

    def test_parse_yearless_date(self):
        assert db.parse_contact_birthday("--05-17") == "--05-17"

    def test_parse_strips_whitespace(self):
        assert db.parse_contact_birthday("  1990-05-17  ") == "1990-05-17"

    @pytest.mark.parametrize("bad", [
        "05/17/1990", "1990-5-17", "17-05-1990", "not a date",
        "1990-13-01", "--13-01", "1990-02-30", "--02-30",
    ])
    def test_parse_rejects_bad_formats(self, bad):
        with pytest.raises(ValueError):
            db.parse_contact_birthday(bad)

    def test_format_full_date(self):
        assert db.format_contact_birthday("1990-05-17") == "May 17, 1990"

    def test_format_yearless_date(self):
        assert db.format_contact_birthday("--05-17") == "May 17"

    def test_format_none_returns_empty_string(self):
        assert db.format_contact_birthday(None) == ""

    def test_format_unrecognized_shape_returns_raw_value(self):
        # A BDAY from another CardDAV client in some other shape (e.g. no
        # dashes) is shown unchanged rather than guessed at.
        assert db.format_contact_birthday("19900517") == "19900517"


class TestVcardRoundTrip:
    def test_full_date_round_trips(self):
        row = {"uid": "person-1", "full_name": "Jane Doe", "birthday": "1990-05-17"}
        text = contact_row_to_vcard(row)
        assert "BDAY:1990-05-17" in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["birthday"] == "1990-05-17"

    def test_yearless_date_round_trips(self):
        row = {"uid": "person-2", "full_name": "X", "birthday": "--05-17"}
        text = contact_row_to_vcard(row)
        assert "BDAY:--05-17" in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert result["birthday"] == "--05-17"

    def test_missing_birthday_round_trips_with_no_line(self):
        row = {"uid": "person-3", "full_name": "No Birthday"}
        text = contact_row_to_vcard(row)
        assert "BDAY" not in text
        card = vobject.readOne(text)
        result = vcard_to_contact_row(card)
        assert "birthday" not in result


class TestCreateEditFlow:
    def test_create_contact_stores_full_birthday(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Grace Hopper", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="1906-12-09", tags="", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["birthday"] == "1906-12-09"

    def test_create_contact_stores_yearless_birthday(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Anon", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="--12-09", tags="", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["birthday"] == "--12-09"

    def test_create_contact_blank_birthday_stores_none(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="No Birthday", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="", tags="", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["birthday"] is None

    def test_create_contact_invalid_birthday_rejected_400(self, conn):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(contacts_router.create_contact(
                full_name="Bad Date", title="", org="",
                phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
                birthday="not-a-date", tags="", notes="", photo=None, conn=conn,
            ))
        assert exc_info.value.status_code == 400
        # Never partially written -- rejected before upsert_contact runs.
        assert db.list_contacts(conn) == []

    def test_update_contact_changes_birthday(self, conn):
        uid = _make_contact(conn, birthday="1990-01-01")
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="1985-06-30", tags="", notes="",
            photo=None, remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert row["birthday"] == "1985-06-30"

    def test_update_contact_can_clear_birthday(self, conn):
        uid = _make_contact(conn, birthday="1990-01-01")
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="", tags="", notes="",
            photo=None, remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert row["birthday"] is None

    def test_update_contact_invalid_birthday_rejected_400_leaves_existing_untouched(self, conn):
        from fastapi import HTTPException
        uid = _make_contact(conn, birthday="1990-01-01")
        with pytest.raises(HTTPException):
            asyncio.run(contacts_router.update_contact(
                uid=uid, full_name="Ada Lovelace", title="", org="",
                phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
                birthday="garbage", tags="", notes="",
                photo=None, remove_photo="", conn=conn,
            ))
        row = db.get_contact(conn, uid)
        assert row["birthday"] == "1990-01-01"

    def test_create_update_routes_accept_birthday_param(self):
        for fn in (contacts_router.create_contact, contacts_router.update_contact):
            params = inspect.signature(fn).parameters
            assert "birthday" in params


class TestRenderedMarkup:
    def test_new_contact_form_has_birthday_field(self, conn):
        resp = contacts_router.new_contact_form(_fake_request("/contacts/new"), conn=conn)
        body = resp.body.decode()
        assert 'name="birthday"' in body

    def test_edit_form_prefills_existing_birthday(self, conn):
        uid = _make_contact(conn, birthday="1990-05-17")
        resp = contacts_router.edit_contact_form(uid, _fake_request(f"/contacts/{uid}/edit"), conn=conn)
        body = resp.body.decode()
        assert 'value="1990-05-17"' in body

    def test_detail_shows_formatted_full_birthday(self, conn):
        uid = _make_contact(conn, birthday="1990-05-17")
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert "<span class=\"detail-meta-value\">May 17, 1990</span>" in body

    def test_detail_shows_formatted_yearless_birthday(self, conn):
        uid = _make_contact(conn, birthday="--05-17")
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert "<span class=\"detail-meta-value\">May 17</span>" in body

    def test_detail_omits_birthday_row_when_absent(self, conn):
        uid = _make_contact(conn)
        resp = contacts_router.contact_detail(uid, _fake_request(f"/contacts/{uid}"), conn=conn)
        body = resp.body.decode()
        assert ">Birthday<" not in body


class TestBirthdayCalendarEvent:
    """Direct follow-up (2026-08-16): a contact's Birthday is a real,
    generated all-day yearly-recurring calendar event tagged "Birthday",
    kept in sync by db.upsert_contact/delete_contact -- see
    db.sync_contact_birthday_event's own docstring for the deterministic-
    uid design."""

    def test_create_contact_with_full_birthday_creates_all_day_yearly_event(self, conn):
        uid = _make_contact(conn, full_name="Grace Hopper", birthday="1906-12-09")
        event = db.get_event(conn, f"birthday::{uid}")
        assert event is not None
        assert event["all_day"] == 1 or event["all_day"] is True
        assert event["start_at"] == "1906-12-09"
        assert event["recurrence"] == "FREQ=YEARLY"
        assert event["tags"] == ["Birthday"]
        assert event["title"] == "Grace Hopper's Birthday"

    def test_create_contact_with_yearless_birthday_uses_placeholder_year(self, conn):
        uid = _make_contact(conn, full_name="Anon", birthday="--05-17")
        event = db.get_event(conn, f"birthday::{uid}")
        assert event["start_at"] == "1900-05-17"
        assert event["recurrence"] == "FREQ=YEARLY"

    def test_create_contact_without_birthday_creates_no_event(self, conn):
        uid = _make_contact(conn)
        assert db.get_event(conn, f"birthday::{uid}") is None

    def test_update_contact_birthday_updates_event_date(self, conn):
        uid = _make_contact(conn, birthday="1990-01-01")
        db.upsert_contact(conn, {"uid": uid, "full_name": "Ada Lovelace", "birthday": "1985-06-30"})
        event = db.get_event(conn, f"birthday::{uid}")
        assert event["start_at"] == "1985-06-30"

    def test_update_contact_name_updates_event_title(self, conn):
        uid = _make_contact(conn, full_name="Old Name", birthday="1990-01-01")
        db.upsert_contact(conn, {"uid": uid, "full_name": "New Name", "birthday": "1990-01-01"})
        event = db.get_event(conn, f"birthday::{uid}")
        assert event["title"] == "New Name's Birthday"

    def test_clearing_birthday_deletes_the_event(self, conn):
        uid = _make_contact(conn, birthday="1990-01-01")
        assert db.get_event(conn, f"birthday::{uid}") is not None
        db.upsert_contact(conn, {"uid": uid, "full_name": "Ada Lovelace", "birthday": None})
        assert db.get_event(conn, f"birthday::{uid}") is None

    def test_deleting_contact_deletes_its_birthday_event(self, conn):
        uid = _make_contact(conn, birthday="1990-01-01")
        db.delete_contact(conn, uid)
        assert db.get_event(conn, f"birthday::{uid}") is None

    def test_deleting_contact_without_birthday_is_a_harmless_noop(self, conn):
        uid = _make_contact(conn)
        db.delete_contact(conn, uid)  # must not raise

    def test_birthday_event_expands_to_an_occurrence_this_year(self, conn):
        # End-to-end through the same recurrence_expand pipeline the
        # Calendar page itself uses -- confirms the generated event isn't
        # just a row in the table but actually renders as a real
        # occurrence, not just structurally plausible.
        from datetime import date

        from src.recurrence_expand import expand_events

        uid = _make_contact(conn, full_name="Grace Hopper", birthday="1906-12-09")
        rows = db.list_events(conn)
        this_year = date.today().year
        window_start = date(this_year, 1, 1)
        window_end = date(this_year, 12, 31)
        occurrences = expand_events(rows, window_start, window_end)
        birthday_occurrences = [o for o in occurrences if o["uid"] == f"birthday::{uid}"]
        assert len(birthday_occurrences) == 1
        occ = birthday_occurrences[0]
        assert occ["start_at"][:10] == f"{this_year}-12-09"
        assert occ["all_day"]

    def test_yearless_birthday_event_expands_to_an_occurrence_this_year(self, conn):
        from datetime import date

        from src.recurrence_expand import expand_events

        uid = _make_contact(conn, full_name="Anon", birthday="--05-17")
        rows = db.list_events(conn)
        this_year = date.today().year
        occurrences = expand_events(rows, date(this_year, 1, 1), date(this_year, 12, 31))
        birthday_occurrences = [o for o in occurrences if o["uid"] == f"birthday::{uid}"]
        assert len(birthday_occurrences) == 1
        assert birthday_occurrences[0]["start_at"][:10] == f"{this_year}-05-17"

    def test_router_create_contact_flow_creates_birthday_event(self, conn):
        import asyncio

        asyncio.run(contacts_router.create_contact(
            full_name="Grace Hopper", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="1906-12-09", tags="", notes="", photo=None, conn=conn,
        ))
        uid = db.list_contacts(conn)[0]["uid"]
        event = db.get_event(conn, f"birthday::{uid}")
        assert event is not None
        assert event["tags"] == ["Birthday"]
