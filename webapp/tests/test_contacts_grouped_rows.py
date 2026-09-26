"""Tests for Contacts items 17-18 (2026-09-26, Peter's queued list):

  17. Grouped by label (confirmed via AskUserQuestion: section headers
      per label, same pattern Settings > Projects already uses for its
      label groups) -- routers/contacts.py's `_group_contacts_by_label`.
      A contact carries at most one label (item 16), so this is a clean
      partition: one group per label in use, sorted alphabetically,
      ungrouped last; the ungrouped bucket's own heading is skipped when
      it's the only group.
  18. Row actions at the right of the row -- each `.contact-row-wrap`
      gained an Edit link and a Delete form (the same optimistic-hide +
      undo-toast contract static/app.js's generic `data-delete-undo`
      already gives Tasks' own rows).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import contacts as contacts_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_contact(conn, uid, **overrides):
    now = _now()
    row = {
        "uid": uid,
        "full_name": uid,
        "org": None,
        "tags": [],
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    db.upsert_contact(conn, row)
    return uid


def _request(path="/contacts"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "headers": []})


class TestGroupContactsByLabel:
    def test_groups_sorted_alphabetically_ungrouped_last(self):
        contacts = [
            {"uid": "c1", "full_name": "Zed", "tags": ["Work"]},
            {"uid": "c2", "full_name": "Amy", "tags": ["Family"]},
            {"uid": "c3", "full_name": "Sam", "tags": []},
            {"uid": "c4", "full_name": "Bea", "tags": ["Family"]},
        ]
        groups = contacts_router._group_contacts_by_label(contacts)
        assert [g["name"] for g in groups] == ["Family", "Work", None]
        assert [c["uid"] for c in groups[0]["contacts"]] == ["c2", "c4"]
        assert [c["uid"] for c in groups[1]["contacts"]] == ["c1"]
        assert [c["uid"] for c in groups[2]["contacts"]] == ["c3"]

    def test_no_ungrouped_bucket_when_everyone_has_a_label(self):
        contacts = [{"uid": "c1", "full_name": "A", "tags": ["Work"]}]
        groups = contacts_router._group_contacts_by_label(contacts)
        assert groups == [{"name": "Work", "contacts": contacts}]

    def test_single_ungrouped_bucket_when_nobody_has_a_label(self):
        contacts = [{"uid": "c1", "full_name": "A", "tags": []}, {"uid": "c2", "full_name": "B", "tags": None}]
        groups = contacts_router._group_contacts_by_label(contacts)
        assert groups == [{"name": None, "contacts": contacts}]

    def test_empty_list_is_no_groups(self):
        assert contacts_router._group_contacts_by_label([]) == []


class TestRenderedGrouping:
    def test_section_headings_appear_per_label_ungrouped_last(self, conn):
        _make_contact(conn, "c1", full_name="Zed", tags=["Work"])
        _make_contact(conn, "c2", full_name="Amy", tags=["Family"])
        _make_contact(conn, "c3", full_name="Sam", tags=[])
        body = contacts_router.list_contacts(_request(), conn=conn).body.decode()
        family_pos = body.index(">Family<")
        work_pos = body.index(">Work<")
        unlabeled_pos = body.index(">Unlabeled<")
        assert family_pos < work_pos < unlabeled_pos
        assert "1 contact<" in body  # Family/Work each have one

    def test_heading_still_shows_when_every_contact_shares_the_one_label(self, conn):
        # Unlike the Unlabeled bucket below, a real label's heading always
        # shows -- it's real user structure, not a "nothing to distinguish
        # it from" flat list.
        _make_contact(conn, "c1", full_name="Zed", tags=["Work"])
        _make_contact(conn, "c2", full_name="Amy", tags=["Work"])
        body = contacts_router.list_contacts(_request(), conn=conn).body.decode()
        assert 'class="contact-section-row">' in body
        assert ">Work<" in body and "2 contacts" in body

    def test_no_section_heading_when_nobody_has_a_label(self, conn):
        _make_contact(conn, "c1", full_name="Zed")
        body = contacts_router.list_contacts(_request(), conn=conn).body.decode()
        assert 'class="contact-section-row' not in body
        assert ">Unlabeled<" not in body


class TestRowActions:
    def test_row_has_edit_link_and_delete_undo_form(self, conn):
        # 2026-09-26 (item 19): the plain Edit/Delete `.action-buttons`
        # icon-button pair is now a 3-item `.action-menu` kebab (Edit/
        # Archive/Delete, _action_menu.html) -- see
        # test_contacts_archive_column.py for the Archive item's own
        # dedicated coverage; this test just confirms Edit/Delete both
        # still made the move into the kebab intact.
        _make_contact(conn, "c1", full_name="Ada Lovelace")
        body = contacts_router.list_contacts(_request(), conn=conn).body.decode()
        row = body[body.index('data-uid="c1"'):]
        assert 'role="menuitem" href="/contacts/c1/edit" data-modal' in row
        assert 'action="/contacts/c1/delete"' in row
        assert 'data-cc-change="contact"' in row
        assert 'data-delete-undo="Ada Lovelace"' in row

    def test_no_label_pill_left_inline_on_the_row_itself(self, conn):
        # The per-row pill is redundant now that the section heading
        # already names the contact's one label.
        _make_contact(conn, "c1", full_name="Ada", tags=["Work"])
        body = contacts_router.list_contacts(_request(), conn=conn).body.decode()
        row_start = body.index('data-uid="c1"')
        row = body[row_start:body.index("</a>", row_start) + 4]
        assert "cell-tag cal-" not in row  # label_pill()'s own rendered class

    def test_delete_undo_row_wrapper_has_data_undo_row(self, conn):
        _make_contact(conn, "c1", full_name="Ada Lovelace")
        body = contacts_router.list_contacts(_request(), conn=conn).body.decode()
        assert 'class="contact-row-wrap" data-uid="c1" data-undo-row>' in body
