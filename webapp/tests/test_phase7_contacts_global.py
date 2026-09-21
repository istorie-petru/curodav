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
    (_filter_dropdown.html's existing "multi" mode), and gained a
    built-in default -- every label checked except Archived -- see
    TestArchivedDefaultExclusion below for that half. `contacts_filtered`
    must be present in the query string for an explicit `tag=` selection
    to actually take effect (it's what tells routers/contacts.py this is
    a real, deliberate pick and not just an untouched page load) -- see
    _contacts_list_context's own docstring/comment."""

    def test_tag_param_filters_case_insensitively(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Bob", tags=["Faculty"])
        _seed_contact(conn, "c3", "Carol", tags=["university", "family"])
        req = _request(query_string=b"tag=UNIVERSITY&contacts_filtered=1")
        resp = contacts_router.list_contacts(req, tag=["UNIVERSITY"], conn=conn)
        assert [c["uid"] for c in resp.context["contacts"]] == ["c1", "c3"]
        assert resp.context["active_tags"] == {"university"}

    def test_no_tag_returns_everything_except_archived_by_default(self, conn):
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

    def test_checking_only_university_still_hides_an_also_archived_contact(self, conn):
        # 2026-09-21 rework: Archived is no longer "just a normal label"
        # (see TestArchivedDefaultExclusion) -- checking University alone
        # leaves Archived unchecked, and an unchecked label hides any
        # contact carrying it, even one that also carries a checked
        # label. Checking Archived too (below) is what surfaces Bob.
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Bob", tags=["University", "Archived"])
        req = _request(query_string=b"tag=University&contacts_filtered=1")
        resp = contacts_router.list_contacts(req, tag=["University"], conn=conn)
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1"}

    def test_checking_university_and_archived_shows_both(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Bob", tags=["University", "Archived"])
        req = _request(query_string=b"tag=University&tag=Archived&contacts_filtered=1")
        resp = contacts_router.list_contacts(req, tag=["University", "Archived"], conn=conn)
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1", "c2"}

    def test_tag_links_appear_in_the_rendered_body(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        req = _request(query_string=b"tag=University&contacts_filtered=1")
        resp = contacts_router.list_contacts(req, tag=["University"], conn=conn)
        body = resp.body.decode()
        assert "Label" in body
        assert "Alice" in body


class TestArchivedDefaultExclusion:
    """Direct request: "archived labels should not be visible normally...
    the label filter... normally is filtered to show all labels and only
    the `archived` one is not checked." """

    def test_untouched_page_load_hides_archived_contacts(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Old Contact", tags=["Archived"])
        resp = contacts_router.list_contacts(_request(), conn=conn)
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1"}
        assert "archived" not in resp.context["active_tags"]

    def test_unlabeled_contacts_are_never_hidden_by_the_default(self, conn):
        # The default exclusion is "hide contacts carrying Archived," not
        # "show only contacts carrying a checked label" -- an unlabeled
        # contact must still appear even though it matches none of the
        # implicitly-checked labels.
        _seed_contact(conn, "c1", "No Labels", tags=[])
        _seed_contact(conn, "c2", "Old Contact", tags=["Archived"])
        resp = contacts_router.list_contacts(_request(), conn=conn)
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1"}

    def test_explicitly_checking_archived_shows_it(self, conn):
        _seed_contact(conn, "c1", "Old Contact", tags=["Archived"])
        req = _request(query_string=b"tag=Archived&contacts_filtered=1")
        resp = contacts_router.list_contacts(req, tag=["Archived"], conn=conn)
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1"}

    def test_explicitly_unchecking_everything_shows_nothing(self, conn):
        # A deliberate, fully-empty selection is respected literally, not
        # silently treated as "no filter active."
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        req = _request(query_string=b"contacts_filtered=1")
        resp = contacts_router.list_contacts(req, tag=[], conn=conn)
        assert resp.context["contacts"] == []

    def test_regions_fragment_applies_the_same_default(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Old Contact", tags=["Archived"])
        resp = contacts_router.contacts_regions(_request("/contacts/regions"), conn=conn)
        body = resp.body.decode()
        assert "Alice" in body

    def test_rendered_checkbox_dropdown_leaves_only_archived_unchecked(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Old Contact", tags=["Archived"])
        resp = contacts_router.list_contacts(_request(), conn=conn)
        body = resp.body.decode()
        checked = dict(re.findall(r'<input type="checkbox" name="tag" value="([^"]*)"[^>]*?(checked)?>', body))
        assert checked.get("university") == "checked"
        assert checked.get("archived") == ""
        assert "Old Contact" not in body
