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


def _request(path="/contacts"):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
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
    def test_tag_param_filters_case_insensitively(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Bob", tags=["Faculty"])
        _seed_contact(conn, "c3", "Carol", tags=["university", "family"])
        resp = contacts_router.list_contacts(_request(), tag="UNIVERSITY", conn=conn)
        assert [c["uid"] for c in resp.context["contacts"]] == ["c1", "c3"]
        assert resp.context["active_tag"] == "university"

    def test_no_tag_returns_everything(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Bob", tags=["Faculty"])
        resp = contacts_router.list_contacts(_request(), conn=conn)
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1", "c2"}
        assert resp.context["active_tag"] == ""

    def test_context_exposes_tag_options(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Bob", tags=["Faculty"])
        resp = contacts_router.list_contacts(_request(), conn=conn)
        assert resp.context["contact_tags"] == ["Faculty", "University"]

    def test_tag_filter_matches_regardless_of_an_archived_tag(self, conn):
        # 2026-08-07: Active/Archived view removed entirely -- "Archived"
        # is just a normal label now, same as "University". Filtering by
        # one label returns everything carrying it, whether or not it also
        # carries any other label.
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        _seed_contact(conn, "c2", "Bob", tags=["University", "Archived"])
        resp = contacts_router.list_contacts(_request(), tag="University", conn=conn)
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1", "c2"}

    def test_tag_links_appear_in_the_rendered_body(self, conn):
        _seed_contact(conn, "c1", "Alice", tags=["University"])
        resp = contacts_router.list_contacts(_request(), tag="University", conn=conn)
        body = resp.body.decode()
        # 2026-08-07: "All tags" -> "All labels" (tag/label wording pass).
        assert "All labels" in body
        assert "Alice" in body
