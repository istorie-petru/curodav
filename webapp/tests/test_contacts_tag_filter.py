"""Phase 7 (command-center-rework) -- contacts global + saved tag filter.

Two halves, matching the phase's two halves:
  1. The Contacts page's tag filter -- a saved filter over the global
     contacts list (`?tag=`), distinct tag names from
     db.list_contact_tag_names, matched case-insensitively against
     contacts.tags_json.
  2. A project's "People" -- a saved filter, same as a Space's: every
     contact whose tags include the project's own name or its Space's
     name, unioned with addressbook-linked contacts. The phase's
     acceptance criterion is "a contact tagged `University` appears under
     the project page's People AND under the Contacts tag filter."
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import contacts as contacts_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/contacts", query_string=b""):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": query_string,
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _seed_contact(conn, uid, full_name, tags=()):
    db.upsert_contact(
        conn,
        {
            "uid": uid,
            "full_name": full_name,
            "tags": list(tags),
            "created_at": _now(),
        },
    )


class TestContactTagNames:
    def test_lists_distinct_contact_tags_sorted(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University", "Faculty"])
        _seed_contact(conn, "c2", "Bob", tags=["university", "family"])
        _seed_contact(conn, "c3", "Carol", tags=[])
        # Case-preserving on first occurrence, deduped case-insensitively,
        # sorted case-insensitively -- same convention as list_tag_names_in_use.
        assert db.list_contact_tag_names(conn) == ["Faculty", "family", "University"]

    def test_empty_when_no_contacts(self, conn):
        assert db.list_contact_tag_names(conn) == []


class TestContactsTagFilter:
    """2026-09-21 rework (direct request): the single-select `?tag=`
    radio filter became a multi-select checkbox filter
    (_filter_dropdown.html's existing "multi" mode). `contacts_filtered`
    must be present in the query string for an explicit `tag=` selection
    to actually take effect (it's what tells routers/contacts.py this is
    a real, deliberate pick and not just an untouched page load) -- see
    _contacts_list_context's own docstring/comment.

    2026-09-26 (item 19): this filter used to have a second job -- "every
    label checked except Archived" -- back when Archived was itself a
    label (see TestArchivedDefaultExclusion below, now covering the real
    `contacts.archived_at` column's own separate `?archived=` toggle
    instead). A label literally named "Archived" is just an ordinary
    label now, with no special filter behavior of its own -- nothing left
    to test for that here beyond the plain OR-filter every other label
    already gets."""

    def test_tag_param_filters_case_insensitively(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Bob", tags=["Faculty"])
        _seed_contact(conn, "c3", "Carol", tags=["university", "family"])
        req = _request(query_string=b"tag=UNIVERSITY&contacts_filtered=1")
        resp = contacts_router.list_contacts(req, tag=["UNIVERSITY"], conn=conn)
        assert [c["uid"] for c in resp.context["contacts"]] == ["c1", "c3"]
        assert resp.context["active_tags"] == {"university"}

    def test_no_tag_returns_everything_by_default(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Bob", tags=["Faculty"])
        resp = contacts_router.list_contacts(_request(), conn=conn)
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1", "c2"}
        assert resp.context["active_tags"] == {"university", "faculty"}

    def test_context_exposes_tag_options(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Bob", tags=["Faculty"])
        resp = contacts_router.list_contacts(_request(), conn=conn)
        assert resp.context["contact_tags"] == ["Faculty", "University"]

    def test_tag_links_appear_in_the_rendered_body(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        req = _request(query_string=b"tag=University&contacts_filtered=1")
        resp = contacts_router.list_contacts(req, tag=["University"], conn=conn)
        body = resp.body.decode()
        assert "Label" in body
        assert "Alice" in body


class TestArchivedDefaultExclusion:
    """Item 19 (2026-09-26): "archived" is a real `contacts.archived_at`
    column now (db.archive_contact/unarchive_contact), not a label --
    replaces the 2026-09-21 fake-"Archived"-label mechanism this class
    used to test (see git history for that version). Same default-hidden
    behavior, `?archived=1` instead of a checkbox in the Label filter
    dropdown (which only ever lists real labels now -- routers/
    contacts.py's own comment on why the old suppression logic is gone)."""

    def test_untouched_page_load_hides_archived_contacts(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Old Contact")
        db.archive_contact(conn, "c2")
        resp = contacts_router.list_contacts(_request(), conn=conn)
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1"}
        assert resp.context["show_archived"] is False

    def test_unlabeled_contacts_are_never_hidden_by_the_default(self, conn):
        # The archived exclusion is orthogonal to the label filter -- an
        # unlabeled, non-archived contact must still appear even though it
        # matches none of the implicitly-checked labels.
        _seed_contact(conn, "c1", "No Labels", tags=[])
        _seed_contact(conn, "c2", "Old Contact")
        db.archive_contact(conn, "c2")
        resp = contacts_router.list_contacts(_request(), conn=conn)
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1"}

    def test_explicitly_requesting_archived_shows_it(self, conn):
        _seed_contact(conn, "c1", "Old Contact")
        db.archive_contact(conn, "c1")
        resp = contacts_router.list_contacts(_request(), archived="1", conn=conn)
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1"}
        assert resp.context["show_archived"] is True

    def test_explicitly_unchecking_every_label_still_shows_nothing(self, conn):
        # A deliberate, fully-empty label selection is respected
        # literally, not silently treated as "no filter active" -- separate
        # from (and unaffected by) the archived toggle.
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        req = _request(query_string=b"contacts_filtered=1")
        resp = contacts_router.list_contacts(req, tag=[], conn=conn)
        assert resp.context["contacts"] == []

    def test_regions_fragment_applies_the_same_default(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Old Contact")
        db.archive_contact(conn, "c2")
        resp = contacts_router.contacts_regions(_request("/contacts/regions"), conn=conn)
        body = resp.body.decode()
        assert "Alice" in body
        assert "Old Contact" not in body

    def test_rendered_show_archived_checkbox_reflects_state(self, conn):
        """2026-09-27 direct feedback reverted the plain checkbox+label
        toggle to a `_filter_dropdown.html` dropdown (same component the
        Label filter next to it uses) -- the checkbox itself is now one
        `<input>` inside that macro's multi-line markup, so this checks
        for "checked" on the same tag rather than one exact single-line
        string."""
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Old Contact")
        db.archive_contact(conn, "c2")
        resp = contacts_router.list_contacts(_request(), conn=conn)
        body = resp.body.decode()
        assert 'name="archived" value="1"' in body
        assert "Old Contact" not in body
        unchecked_input = body[body.index('name="archived" value="1"'):][:200]
        assert "checked" not in unchecked_input
        resp2 = contacts_router.list_contacts(_request(), archived="1", conn=conn)
        body2 = resp2.body.decode()
        checked_input = body2[body2.index('name="archived" value="1"'):][:200]
        assert 'form="contacts-filters-form"' in checked_input
        assert "data-change-submit" in checked_input
        assert "checked" in checked_input
        assert "Old Contact" in body2
