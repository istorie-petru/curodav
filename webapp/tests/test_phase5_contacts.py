"""Phase 5 (label-space rework) acceptance tests -- see
features/architecture.md §3 Phase 5's own acceptance criteria:

  * `contacts.category` is gone entirely (no column, no create/edit form
    field, no filter dropdown, no `list_contact_categories`/`category`
    param anywhere in `src/`);
  * grouping/filtering contacts is 100% via labels (`tags`/`object_labels`),
    reusing the exact same mechanism tasks/events already use -- there is
    no separate "filter by category" UI left, only "filter by tag";
  * archiving still works off the plain `Archived` tag (Phase 1's
    approach, unaffected by this phase -- a regression check, not new
    behavior).
"""

from __future__ import annotations

import asyncio
import inspect
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src import db
from src.routers import contacts as contacts_router

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"


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


class TestNoCategoryColumn:
    def test_contacts_table_has_no_category_column(self, conn):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
        assert "category" not in cols

    def test_upsert_contact_ignores_stray_category_key(self, conn):
        # Passing a stray "category" key in the row dict must not error
        # and must not be persisted anywhere queryable.
        uid = _make_contact(conn, category="Professor")
        row = db.get_contact(conn, uid)
        assert "category" not in row

    def test_list_contacts_has_no_category_param(self, conn):
        sig = inspect.signature(db.list_contacts)
        assert "category" not in sig.parameters

    def test_list_contact_categories_removed(self):
        assert not hasattr(db, "list_contact_categories")

    def test_create_update_contact_routes_have_no_category_param(self):
        for fn in (contacts_router.create_contact, contacts_router.update_contact):
            assert "category" not in inspect.signature(fn).parameters

    def test_list_contacts_route_has_no_category_query_param(self):
        assert "category" not in inspect.signature(contacts_router.list_contacts).parameters


class TestCreateEditFlowHasNoCategory:
    def test_create_contact_flow_never_touches_category(self, conn):
        # 2026-09-26 (Peter: "Contacts should only allow one label") --
        # the legacy comma-separated `tags` fallback field truncates to
        # its first entry now, same as the real single-select Label field
        # does; "Professor, CS" used to keep both.
        asyncio.run(contacts_router.create_contact(
            full_name="Grace Hopper", title="", org="Navy",
            phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="", tags="Professor, CS", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert "category" not in row
        assert row["tags"] == ["Professor"]

    def test_update_contact_flow_never_touches_category(self, conn):
        uid = _make_contact(conn, tags=["Old"])
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[], address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
            birthday="", tags="Mathematician", notes="", photo=None,
            remove_photo="", conn=conn,
        ))
        row = db.get_contact(conn, uid)
        assert "category" not in row
        assert row["tags"] == ["Mathematician"]


class TestFilterByLabelReplacesCategory:
    def test_filtering_by_tag_works(self, conn):
        _make_contact(conn, uid="c1", full_name="Prof A", tags=["Professor"])
        _make_contact(conn, uid="c2", full_name="Classmate B", tags=["Classmate"])

        resp = contacts_router.list_contacts(
            request=_fake_request(b"tag=Professor&contacts_filtered=1"), q=None, tag=["Professor"], conn=conn,
        )
        names = [c["full_name"] for c in resp.context["contacts"]]
        assert names == ["Prof A"]

    def test_no_tag_filter_returns_all_contacts(self, conn):
        _make_contact(conn, uid="c1", full_name="Prof A", tags=["Professor"])
        _make_contact(conn, uid="c2", full_name="Classmate B", tags=["Classmate"])

        resp = contacts_router.list_contacts(
            request=_fake_request(), q=None, tag=None, conn=conn,
        )
        names = sorted(c["full_name"] for c in resp.context["contacts"])
        assert names == ["Classmate B", "Prof A"]

    def test_context_has_no_categories_key(self, conn):
        _make_contact(conn, uid="c1")
        resp = contacts_router.list_contacts(
            request=_fake_request(), q=None, tag=None, conn=conn,
        )
        assert "categories" not in resp.context
        assert "active_category" not in resp.context


class TestNoSpecialArchivedState:
    """History of this class's own name, now stale twice over -- kept as a
    literal paper trail rather than renamed, since the "view" param checks
    below are still genuinely true today:

    2026-08-07: Active/Archived removed entirely -- Contacts had no
    dedicated *state*/endpoints for it, only a label, same as every other
    object type.

    2026-09-21 direct request reversed the *visibility* half of that:
    "archived labels should not be visible normally" -- tagging a contact
    "Archived" became a label with real, built-in default-hidden behavior
    (still just a label, no new column/endpoint, at that point).

    Item 19 (2026-09-26, same day as this test update) reverses the rest:
    "an archive flag is never counted as a label -- separate data model
    entirely." `archive_contact`/`unarchive_contact` (routers/contacts.py)
    are real routes now, backed by the real `contacts.archived_at` column
    (db.py) -- see `migrate_archived_contact_label`'s own docstring for
    why the label-based predecessor was actively wrong once item 16
    restricted a contact to one label total (archiving one ate the
    contact's real category label). See test_phase7_contacts_global.py's
    TestArchivedDefaultExclusion for the default-hidden behavior's own
    tests, and test_contacts_archive_column.py for the new column/routes
    themselves -- this class only still covers the "no `view` query param"
    checks, unrelated to any of the above and still true today."""

    def test_archive_endpoints_exist_and_are_column_backed(self, conn):
        # The inverse of this class's old-named check -- see the class
        # docstring above for why "no archive endpoints" stopped being
        # true. Full behavioral coverage lives in
        # test_contacts_archive_column.py; this is just the "yes, this
        # reversed" regression marker in the same place the old negative
        # assertion used to live.
        assert hasattr(contacts_router, "archive_contact")
        assert hasattr(contacts_router, "unarchive_contact")
        uid = _make_contact(conn, uid="c1")
        contacts_router.archive_contact(uid, conn=conn)
        assert db.get_contact(conn, uid)["archived_at"]
        contacts_router.unarchive_contact(uid, conn=conn)
        assert db.get_contact(conn, uid)["archived_at"] is None

    def test_list_contacts_has_no_view_param(self):
        import inspect

        assert "view" not in inspect.signature(contacts_router.list_contacts).parameters

    def test_context_has_no_view_key(self, conn):
        _make_contact(conn, uid="c1")
        resp = contacts_router.list_contacts(
            request=_fake_request(), q=None, tag=[], conn=conn,
        )
        assert "view" not in resp.context


class TestNoDanglingReferences:
    def test_no_category_reference_in_src(self):
        offenders = []
        for path in _SRC_DIR.rglob("*.py"):
            text = path.read_text()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if re.search(r"\bcategory\b|\bcategories\b|list_contact_categories", line, re.IGNORECASE):
                    # "category"/"categories" used as a plain English word
                    # in an unrelated comment (e.g. habits.py's "same
                    # category as", style.css-adjacent pill comments) is
                    # fine -- what must be gone is any reference to the
                    # contacts.category *field* or its accessor function.
                    if "list_contact_categories" in line or "contact.category" in line or "c[\"category\"]" in line:
                        offenders.append(f"{path}:{lineno}: {line.strip()}")
        assert offenders == [], "\n".join(offenders)

    def test_no_category_reference_in_templates(self):
        # Comments *documenting* the removal (e.g. "Category field removed
        # (Phase 5...)") are fine and expected; what must be gone is any
        # live template code that reads/renders/submits a `category` field
        # (`contact.category`, `name="category"`, `active_category`, or a
        # category filter <select>).
        templates_dir = _SRC_DIR / "templates"
        live_patterns = [
            r"contact\.category",
            r'name="category"',
            r"active_category",
            r"c\.category",
            r"list_contact_categories",
        ]
        offenders = []
        for path in templates_dir.glob("contact*.html"):
            text = path.read_text()
            for pat in live_patterns:
                if re.search(pat, text):
                    offenders.append(f"{path}: matched {pat!r}")
        assert offenders == [], "\n".join(offenders)


def _fake_request(query_string=b""):
    from starlette.requests import Request

    return Request({
        "type": "http",
        "method": "GET",
        "path": "/contacts",
        "query_string": query_string,
        "scheme": "http",
        "server": ("testserver", 80),
        "root_path": "",
        "headers": [],
    })
