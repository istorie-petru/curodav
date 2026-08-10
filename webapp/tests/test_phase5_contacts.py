"""Phase 5 (label-space rework) acceptance tests -- see
plans/label-space-rework.md §3 Phase 5's own acceptance criteria:

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
        asyncio.run(contacts_router.create_contact(
            full_name="Grace Hopper", org="Navy", phone="", email="",
            address="", tags="Professor, CS", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert "category" not in row
        assert sorted(row["tags"]) == ["CS", "Professor"]

    def test_update_contact_flow_never_touches_category(self, conn):
        uid = _make_contact(conn, tags=["Old"])
        asyncio.run(contacts_router.update_contact(
            uid=uid, full_name="Ada Lovelace", org="", phone="", email="",
            address="", tags="Mathematician", notes="", photo=None,
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
            request=_fake_request(), q=None, tag="Professor", conn=conn,
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
    """2026-08-07: Active/Archived removed entirely -- Contacts has no
    special "archived" state anymore, only labels, same as every other
    object type. `archive_contact`/`unarchive_contact`/the `view` query
    param no longer exist; tagging a contact "Archived" is just a normal
    label like any other -- it doesn't hide the contact from the list or
    require any dedicated endpoint."""

    def test_no_archive_endpoints_exist(self):
        assert not hasattr(contacts_router, "archive_contact")
        assert not hasattr(contacts_router, "unarchive_contact")

    def test_list_contacts_has_no_view_param(self):
        import inspect

        assert "view" not in inspect.signature(contacts_router.list_contacts).parameters

    def test_tagging_a_contact_archived_is_just_a_normal_label(self, conn):
        uid = _make_contact(conn, full_name="Old Contact", tags=["Archived"])
        resp = contacts_router.list_contacts(
            request=_fake_request(), q=None, tag=None, conn=conn,
        )
        # No hiding -- a contact tagged "Archived" shows up in the plain
        # list exactly like any other tag would.
        assert [c["uid"] for c in resp.context["contacts"]] == [uid]

    def test_context_has_no_view_key(self, conn):
        _make_contact(conn, uid="c1")
        resp = contacts_router.list_contacts(
            request=_fake_request(), q=None, tag=None, conn=conn,
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


def _fake_request():
    from starlette.requests import Request

    return Request({
        "type": "http",
        "method": "GET",
        "path": "/contacts",
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "root_path": "",
        "headers": [],
    })
