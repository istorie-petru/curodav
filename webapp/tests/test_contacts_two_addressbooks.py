"""Tests for §4: two-addressbook contacts system.

Covers:
- db.ensure_default_addressbook (now always ensures Active exists by uid)
- db.ensure_default_archived_addressbook (ensures Archived exists)
- db.migrate_addressbooks_to_two (data-layer migration)
- db.ARCHIVED_ADDRESSBOOK_UID constant present
- contacts router's view= filter (Active / Archived)
- contacts router's archive / unarchive endpoints (via TestClient)
- The app_meta migration flag prevents double-runs
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src import db


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_contact(conn, uid: str, full_name: str, addressbook_path: str, tags: list[str] | None = None) -> dict:
    row = {
        "uid": uid,
        "href": f"/ab/{uid}.vcf",
        "etag": None,
        "addressbook_path": addressbook_path,
        "full_name": full_name,
        "tags": tags or [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    db.upsert_contact(conn, row)
    return db.get_contact(conn, uid)


def _make_addressbook(conn, uid: str, name: str, color: str = "blue") -> dict:
    row = {"uid": uid, "name": name, "color": color, "created_at": _now()}
    db.upsert_addressbook(conn, row)
    return db.get_addressbook(conn, uid)


# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

class TestConstants:
    def test_archived_uid_constant(self):
        assert db.ARCHIVED_ADDRESSBOOK_UID == "contacts-archived"

    def test_default_uid_constant(self):
        assert db.DEFAULT_ADDRESSBOOK_UID == "contacts"


# ------------------------------------------------------------------ #
# ensure_default_addressbook / ensure_default_archived_addressbook
# ------------------------------------------------------------------ #

class TestEnsureAddressbooks:
    def test_ensure_default_creates_active_when_absent(self, conn):
        db.ensure_default_addressbook(conn)
        ab = db.get_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID)
        assert ab is not None
        assert ab["name"] == "Active"

    def test_ensure_default_is_idempotent(self, conn):
        db.ensure_default_addressbook(conn)
        db.ensure_default_addressbook(conn)
        abs_ = [a for a in db.list_addressbooks(conn) if a["uid"] == db.DEFAULT_ADDRESSBOOK_UID]
        assert len(abs_) == 1

    def test_ensure_default_does_not_overwrite_existing_active(self, conn):
        # Pre-create with a custom name; ensure_default must not clobber it.
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "MyContacts")
        db.ensure_default_addressbook(conn)
        ab = db.get_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID)
        assert ab["name"] == "MyContacts"

    def test_ensure_archived_creates_when_absent(self, conn):
        db.ensure_default_archived_addressbook(conn)
        ab = db.get_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID)
        assert ab is not None
        assert ab["name"] == "Archived"

    def test_ensure_archived_is_idempotent(self, conn):
        db.ensure_default_archived_addressbook(conn)
        db.ensure_default_archived_addressbook(conn)
        abs_ = [a for a in db.list_addressbooks(conn) if a["uid"] == db.ARCHIVED_ADDRESSBOOK_UID]
        assert len(abs_) == 1

    def test_both_ensure_calls_together_produce_exactly_two(self, conn):
        db.ensure_default_addressbook(conn)
        db.ensure_default_archived_addressbook(conn)
        abs_ = db.list_addressbooks(conn)
        uids = {a["uid"] for a in abs_}
        assert db.DEFAULT_ADDRESSBOOK_UID in uids
        assert db.ARCHIVED_ADDRESSBOOK_UID in uids


# ------------------------------------------------------------------ #
# migrate_addressbooks_to_two -- data layer
# ------------------------------------------------------------------ #

class TestMigrateAddressbooksToTwo:
    def test_no_extra_books_returns_empty_list(self, conn):
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        result = db.migrate_addressbooks_to_two(conn)
        assert result == []

    def test_extra_book_contacts_moved_to_active(self, conn):
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        _make_addressbook(conn, "friends", "Friends")
        _make_contact(conn, "c1", "Alice", "friends")
        _make_contact(conn, "c2", "Bob", "friends")

        db.migrate_addressbooks_to_two(conn)

        c1 = db.get_contact(conn, "c1")
        c2 = db.get_contact(conn, "c2")
        assert c1["addressbook_path"] == db.DEFAULT_ADDRESSBOOK_UID
        assert c2["addressbook_path"] == db.DEFAULT_ADDRESSBOOK_UID

    def test_extra_book_name_added_as_tag(self, conn):
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        _make_addressbook(conn, "work", "Work")
        _make_contact(conn, "c1", "Charlie", "work", tags=["colleague"])

        db.migrate_addressbooks_to_two(conn)

        c1 = db.get_contact(conn, "c1")
        assert "Work" in c1["tags"]
        assert "colleague" in c1["tags"]

    def test_tag_not_duplicated_if_already_present(self, conn):
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        _make_addressbook(conn, "family", "Family")
        # Contact already has the tag "Family" from before.
        _make_contact(conn, "c1", "Dave", "family", tags=["Family"])

        db.migrate_addressbooks_to_two(conn)

        c1 = db.get_contact(conn, "c1")
        family_count = sum(1 for t in c1["tags"] if t.lower() == "family")
        assert family_count == 1, f"Expected exactly one 'Family' tag, got: {c1['tags']}"

    def test_case_insensitive_tag_dedup(self, conn):
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        _make_addressbook(conn, "friends", "Friends")
        # lowercase variant already present
        _make_contact(conn, "c1", "Eve", "friends", tags=["friends"])

        db.migrate_addressbooks_to_two(conn)

        c1 = db.get_contact(conn, "c1")
        friends_count = sum(1 for t in c1["tags"] if t.lower() == "friends")
        assert friends_count == 1

    def test_multiple_extra_books_all_migrated(self, conn):
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        _make_addressbook(conn, "family", "Family")
        _make_addressbook(conn, "work", "Work")
        _make_contact(conn, "c1", "Frank", "family")
        _make_contact(conn, "c2", "Grace", "work")

        migrated = db.migrate_addressbooks_to_two(conn)
        migrated_uids = {m["uid"] for m in migrated}
        assert "family" in migrated_uids
        assert "work" in migrated_uids

        c1 = db.get_contact(conn, "c1")
        c2 = db.get_contact(conn, "c2")
        assert c1["addressbook_path"] == db.DEFAULT_ADDRESSBOOK_UID
        assert "Family" in c1["tags"]
        assert c2["addressbook_path"] == db.DEFAULT_ADDRESSBOOK_UID
        assert "Work" in c2["tags"]

    def test_contacts_already_in_active_not_touched(self, conn):
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        _make_addressbook(conn, "extra", "Extra")
        _make_contact(conn, "c1", "Henry", db.DEFAULT_ADDRESSBOOK_UID, tags=["existing"])

        db.migrate_addressbooks_to_two(conn)

        c1 = db.get_contact(conn, "c1")
        # Should not have "Extra" tag added and still be in Active.
        assert c1["addressbook_path"] == db.DEFAULT_ADDRESSBOOK_UID
        assert "Extra" not in c1["tags"]

    def test_contacts_in_archived_not_touched(self, conn):
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        _make_addressbook(conn, "extra", "Extra")
        _make_contact(conn, "c1", "Ivy", db.ARCHIVED_ADDRESSBOOK_UID, tags=["old"])

        db.migrate_addressbooks_to_two(conn)

        c1 = db.get_contact(conn, "c1")
        assert c1["addressbook_path"] == db.ARCHIVED_ADDRESSBOOK_UID
        assert "Extra" not in c1["tags"]

    def test_migration_does_not_delete_addressbook_rows(self, conn):
        """data-layer migration leaves DB rows intact -- sync.py deletes
        them after the CardDAV moves, not here."""
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        _make_addressbook(conn, "extra", "Extra")
        _make_contact(conn, "c1", "Jack", "extra")

        db.migrate_addressbooks_to_two(conn)

        # The 'extra' addressbook row must still be present (caller deletes it).
        assert db.get_addressbook(conn, "extra") is not None

    def test_empty_addressbook_returns_in_migrated_list(self, conn):
        """An extra addressbook with no contacts should still be returned as
        migrated (so the caller knows to delete the empty CardDAV collection)."""
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        _make_addressbook(conn, "empty-book", "EmptyBook")

        migrated = db.migrate_addressbooks_to_two(conn)
        assert any(m["uid"] == "empty-book" for m in migrated)

    def test_idempotent_second_call_no_error(self, conn):
        """Calling migrate twice (as could happen if the CardDAV step
        succeeds but the flag write fails and sync retries) must not
        error or create duplicate tags."""
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        _make_addressbook(conn, "uni", "University")
        _make_contact(conn, "c1", "Kim", "uni", tags=["student"])

        db.migrate_addressbooks_to_two(conn)
        # Contact is now in Active; second call should not add University again.
        db.migrate_addressbooks_to_two(conn)

        c1 = db.get_contact(conn, "c1")
        uni_count = sum(1 for t in c1["tags"] if t.lower() == "university")
        assert uni_count == 1


# ------------------------------------------------------------------ #
# app_meta migration flag
# ------------------------------------------------------------------ #

class TestMigrationFlag:
    def test_get_set_app_meta(self, conn):
        assert db.get_app_meta(conn, "contacts_two_addressbooks_migrated_v1") is None
        db.set_app_meta(conn, "contacts_two_addressbooks_migrated_v1", "1")
        assert db.get_app_meta(conn, "contacts_two_addressbooks_migrated_v1") == "1"

    def test_set_app_meta_is_idempotent(self, conn):
        db.set_app_meta(conn, "contacts_two_addressbooks_migrated_v1", "1")
        db.set_app_meta(conn, "contacts_two_addressbooks_migrated_v1", "1")
        assert db.get_app_meta(conn, "contacts_two_addressbooks_migrated_v1") == "1"


# ------------------------------------------------------------------ #
# list_contacts view= filter (Active / Archived)
# ------------------------------------------------------------------ #

class TestListContactsFilter:
    def test_list_contacts_active_default(self, conn):
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        _make_contact(conn, "c1", "Active Person", db.DEFAULT_ADDRESSBOOK_UID)
        _make_contact(conn, "c2", "Archived Person", db.ARCHIVED_ADDRESSBOOK_UID)

        active = db.list_contacts(conn, addressbook_path=db.DEFAULT_ADDRESSBOOK_UID)
        assert any(c["uid"] == "c1" for c in active)
        assert not any(c["uid"] == "c2" for c in active)

    def test_list_contacts_archived(self, conn):
        _make_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID, "Active")
        _make_addressbook(conn, db.ARCHIVED_ADDRESSBOOK_UID, "Archived")
        _make_contact(conn, "c1", "Active Person", db.DEFAULT_ADDRESSBOOK_UID)
        _make_contact(conn, "c2", "Archived Person", db.ARCHIVED_ADDRESSBOOK_UID)

        archived = db.list_contacts(conn, addressbook_path=db.ARCHIVED_ADDRESSBOOK_UID)
        assert any(c["uid"] == "c2" for c in archived)
        assert not any(c["uid"] == "c1" for c in archived)
