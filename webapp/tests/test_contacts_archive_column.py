"""Tests for item 19 of Peter's queued list (2026-09-26): "Turn 'Archive'
into a top-level data-model column (real SQL, not a label) -- primary use
is Contacts, toggle between not-archived/archived, archived contacts don't
sync. An archive flag is never counted as a label -- separate data model
entirely."

Replaces the old `ARCHIVED_LABEL` fake-label mechanism on Contacts (see
routers/contacts.py's own module docstring for that mechanism's history --
it became actively wrong once item 16 restricted a contact to ONE label
total, since marking a contact archived silently ate its real category
label). Covers: the real `contacts.archived_at` column + `db.archive_
contact`/`unarchive_contact`, the `migrate_archived_contact_label`
one-time migration off the old fake label, `db.list_contacts`'s new
`include_archived` param (the single fetcher both the Contacts page and
Published Lists' materialization share, so excluding archived there
covers both "hidden by default"/"doesn't sync" at once), `upsert_contact`
no longer silently clearing archived_at on an unrelated edit, and the
routes themselves.

Habits (also item 19: "Habits must be archivable") and Events ("must not
be archivable") are covered separately in test_habit_archive.py -- a habit
is a task, so it reuses task `status='archived'`, an entirely different
mechanism from this column."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db, published_lists
from src.routers import contacts as contacts_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/contacts", query_string=b""):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": query_string, "headers": []})


def _contact(conn, uid, full_name=None, tags=None):
    db.upsert_contact(conn, {
        "uid": uid, "full_name": full_name or uid, "tags": tags or [], "created_at": _now(),
    })
    return uid


class TestArchiveColumn:
    def test_new_contact_is_not_archived(self, conn):
        _contact(conn, "c1")
        assert db.get_contact(conn, "c1")["archived_at"] is None

    def test_archive_sets_a_timestamp(self, conn):
        _contact(conn, "c1")
        db.archive_contact(conn, "c1")
        assert db.get_contact(conn, "c1")["archived_at"]

    def test_unarchive_clears_it(self, conn):
        _contact(conn, "c1")
        db.archive_contact(conn, "c1")
        db.unarchive_contact(conn, "c1")
        assert db.get_contact(conn, "c1")["archived_at"] is None

    def test_archiving_an_unknown_uid_is_a_quiet_no_op(self, conn):
        db.archive_contact(conn, "ghost")  # must not raise
        assert db.get_contact(conn, "ghost") is None


class TestListContactsIncludeArchived:
    def test_excluded_by_default(self, conn):
        _contact(conn, "c1")
        _contact(conn, "c2")
        db.archive_contact(conn, "c2")
        assert {c["uid"] for c in db.list_contacts(conn)} == {"c1"}

    def test_included_when_requested(self, conn):
        _contact(conn, "c1")
        _contact(conn, "c2")
        db.archive_contact(conn, "c2")
        assert {c["uid"] for c in db.list_contacts(conn, include_archived=True)} == {"c1", "c2"}

    def test_search_still_respects_the_default_exclusion(self, conn):
        _contact(conn, "c1", full_name="Ada Match")
        _contact(conn, "c2", full_name="Ada Archived")
        db.archive_contact(conn, "c2")
        assert {c["uid"] for c in db.list_contacts(conn, q="Ada")} == {"c1"}
        assert {c["uid"] for c in db.list_contacts(conn, q="Ada", include_archived=True)} == {"c1", "c2"}


class TestArchivedNeverCountedAsALabel:
    """The whole point of item 19: archiving must never touch `tags`/
    `object_labels` at all -- a contact's real category label survives
    archiving intact, unlike the old fake-label mechanism which
    (post item 16) would have overwritten it."""

    def test_archiving_does_not_touch_the_contacts_own_label(self, conn):
        _contact(conn, "c1", tags=["Family"])
        db.archive_contact(conn, "c1")
        c = db.get_contact(conn, "c1")
        assert c["tags"] == ["Family"]
        assert c["archived_at"]

    def test_archived_is_not_a_selectable_label_anywhere(self, conn):
        _contact(conn, "c1", tags=["Family"])
        assert "archived" not in [t.lower() for t in db.list_contact_tag_names(conn)]


_MIGRATION_FLAG = "contacts_archived_label_migrated_v1"


def _reset_migration_flag(conn):
    """The `conn` fixture's own `db.connect()` already runs `init_schema`
    (which calls `migrate_archived_contact_label` once, at connection-open
    time -- before these tests' own contacts exist), marking the migration
    done with nothing yet to migrate. Every test below needs the flag
    cleared first so its own explicit `migrate_archived_contact_label`
    call actually re-runs against the tagged contact it just seeded,
    instead of silently no-op'ing on an already-set flag."""
    db.set_app_meta(conn, _MIGRATION_FLAG, "")


class TestMigrateArchivedContactLabel:
    """The old `ARCHIVED_LABEL = "archived"` fake-label mechanism
    (routers/contacts.py, now removed) is migrated onto the real column by
    this one-time pass -- `init_schema` calls it, but these tests call it
    directly for isolation (see `_reset_migration_flag` above for why each
    one clears the flag first)."""

    def test_tagged_contact_migrates_to_the_real_column(self, conn):
        _contact(conn, "c1", tags=["Archived"])
        _reset_migration_flag(conn)
        db.migrate_archived_contact_label(conn)
        c = db.list_contacts(conn, include_archived=True)[0]
        assert c["archived_at"]
        assert c["tags"] == []

    def test_matched_case_insensitively(self, conn):
        _contact(conn, "c1", tags=["ARCHIVED"])
        _contact(conn, "c2", tags=["archived"])
        _reset_migration_flag(conn)
        db.migrate_archived_contact_label(conn)
        contacts = {c["uid"]: c for c in db.list_contacts(conn, include_archived=True)}
        assert contacts["c1"]["archived_at"] and contacts["c1"]["tags"] == []
        assert contacts["c2"]["archived_at"] and contacts["c2"]["tags"] == []

    def test_a_contacts_other_label_is_untouched(self, conn):
        # This is the exact bug item 19 fixes: pre-item-16, a contact could
        # carry both "Family" and "Archived" -- the migration must not
        # drop the real label, only the fake-archive one.
        _contact(conn, "c1", tags=["Archived", "Family"])
        _reset_migration_flag(conn)
        db.migrate_archived_contact_label(conn)
        c = db.list_contacts(conn, include_archived=True)[0]
        assert c["tags"] == ["Family"]

    def test_idempotent_via_its_own_app_meta_flag(self, conn):
        _contact(conn, "c1", tags=["Archived"])
        _reset_migration_flag(conn)
        db.migrate_archived_contact_label(conn)  # first real run -- actually migrates
        assert db.get_contact(conn, "c1")["archived_at"]
        db.unarchive_contact(conn, "c1")
        db.set_object_labels(conn, "contact", "c1", ["Archived"])  # re-tag after unarchiving
        db.migrate_archived_contact_label(conn)  # must be a no-op the second time (flag now set)
        c = db.list_contacts(conn, include_archived=True)[0]
        # Second run does nothing -- the re-added "Archived" tag survives
        # as an ordinary label, proving the migration didn't run again.
        assert c["archived_at"] is None
        assert c["tags"] == ["Archived"]

    def test_no_op_when_nothing_to_migrate(self, conn):
        _contact(conn, "c1", tags=["Family"])
        _reset_migration_flag(conn)
        db.migrate_archived_contact_label(conn)  # must not raise or touch anything
        c = db.list_contacts(conn)[0]
        assert c["tags"] == ["Family"]
        assert c["archived_at"] is None


class TestUpsertContactPreservesArchivedAt:
    """upsert_contact is a full-field write (unlike upsert_label_config's
    partial-merge shape) -- without an explicit fallback, an unrelated
    "edit the name" save would silently un-archive the contact by writing
    a NULL over the column, since routers/contacts.py's update_contact
    never mentions archived_at in the row dict it builds."""

    def test_plain_edit_save_does_not_clear_archived_at(self, conn):
        _contact(conn, "c1", full_name="Old Name")
        db.archive_contact(conn, "c1")
        # Simulates update_contact's own row dict -- no archived_at key.
        db.upsert_contact(conn, {"uid": "c1", "full_name": "New Name", "created_at": _now()})
        c = db.list_contacts(conn, include_archived=True)[0]
        assert c["full_name"] == "New Name"
        assert c["archived_at"]

    def test_explicit_archived_at_in_the_row_still_wins(self, conn):
        # The one caller that DOES need to actually change it: a backup
        # restore (export.py's full_backup includes the column explicitly).
        _contact(conn, "c1")
        db.upsert_contact(conn, {"uid": "c1", "full_name": "c1", "archived_at": "2026-01-01T00:00:00+00:00", "created_at": _now()})
        assert db.get_contact(conn, "c1")["archived_at"] == "2026-01-01T00:00:00+00:00"


class TestPublishedListsExcludeArchivedContacts:
    """"archived contacts don't sync". Two independent paths in
    `evaluate_label_filter` (published_lists.py) both need this:
      - No label filter at all -> `_ALL_OBJECT_IDS["contact"]` ==
        `db.list_contacts(conn)`, excluded by that function's own
        `include_archived=False` default.
      - A label filter (`all`/`any`/`none`) -> candidate uids come from
        `db.list_object_ids_for_label` (raw `object_labels` reads, no
        archived concept at all) -- an archived contact that still
        carries a matching label would otherwise leak through here
        regardless of the branch above. `evaluate_label_filter`'s own
        unconditional `entity_type == "contact"` subtraction at the end
        (added for this item) is what covers this second path."""

    def test_all_object_ids_fetcher_excludes_archived(self, conn):
        _contact(conn, "c1", tags=["Family"])
        _contact(conn, "c2", tags=["Family"])
        db.archive_contact(conn, "c2")
        fetched = published_lists._ALL_OBJECT_IDS["contact"](conn)
        assert {c["uid"] for c in fetched} == {"c1"}

    def test_label_filtered_list_also_excludes_an_archived_matching_contact(self, conn):
        _contact(conn, "c1", tags=["University"])
        _contact(conn, "c2", tags=["University"])
        db.archive_contact(conn, "c2")
        result = published_lists.evaluate_label_filter(conn, "contact", {"all": ["University"]})
        assert result == ["c1"]

    def test_no_filter_at_all_also_excludes_archived(self, conn):
        _contact(conn, "c1")
        _contact(conn, "c2")
        db.archive_contact(conn, "c2")
        result = published_lists.evaluate_label_filter(conn, "contact", {})
        assert result == ["c1"]

    def test_task_filter_is_unaffected_by_the_contact_only_exclusion(self, conn):
        # Sanity check: the new subtraction is scoped to entity_type ==
        # "contact" -- a task List with the same shape filter must still
        # behave exactly as before.
        db.upsert_task(conn, {"uid": "t1", "title": "A", "description": "", "status": "active", "tags": ["University"], "created_at": _now()})
        result = published_lists.evaluate_label_filter(conn, "task", {"all": ["University"]})
        assert result == ["t1"]


class TestRoutes:
    def test_archive_route_sets_the_column_and_redirects(self, conn):
        _contact(conn, "c1")
        resp = contacts_router.archive_contact("c1", conn=conn)
        assert resp.status_code == 303
        assert db.get_contact(conn, "c1")["archived_at"]

    def test_unarchive_route_clears_it(self, conn):
        _contact(conn, "c1")
        db.archive_contact(conn, "c1")
        resp = contacts_router.unarchive_contact("c1", conn=conn)
        assert resp.status_code == 303
        assert db.get_contact(conn, "c1")["archived_at"] is None

    def test_show_archived_query_param_round_trips(self, conn):
        _contact(conn, "c1")
        db.archive_contact(conn, "c1")
        hidden = contacts_router.list_contacts(_request(), conn=conn)
        assert hidden.context["contacts"] == []
        shown = contacts_router.list_contacts(_request(query_string=b"archived=1"), archived="1", conn=conn)
        assert [c["uid"] for c in shown.context["contacts"]] == ["c1"]

    def test_regions_endpoint_accepts_archived_param_too(self, conn):
        _contact(conn, "c1")
        db.archive_contact(conn, "c1")
        resp = contacts_router.contacts_regions(_request("/contacts/regions"), archived="1", conn=conn)
        assert "c1" in resp.body.decode()


class TestRowKebabRendersArchiveAction:
    def test_not_archived_row_offers_archive(self, conn):
        _contact(conn, "c1", full_name="Ada")
        body = contacts_router.list_contacts(_request(), conn=conn).body.decode()
        row = body[body.index('data-uid="c1"'):]
        assert 'action="/contacts/c1/archive"' in row
        assert 'data-archive-undo="Ada"' in row
        assert 'data-unarchive-url="/contacts/c1/unarchive"' in row
        assert 'action="/contacts/c1/unarchive"' not in row

    def test_archived_row_offers_unarchive_instead(self, conn):
        _contact(conn, "c1", full_name="Ada")
        db.archive_contact(conn, "c1")
        body = contacts_router.list_contacts(_request(query_string=b"archived=1"), archived="1", conn=conn).body.decode()
        row = body[body.index('data-uid="c1"'):]
        assert 'action="/contacts/c1/unarchive"' in row
        assert 'action="/contacts/c1/archive"' not in row
        assert "Archived" in row  # the row's own inline badge (_contacts_body.html)
