"""2026-08-29 (STATE.md backlog item 1, direct request: "bulk actions on
tables... Tasks first, since it's the precedent; then Habits, Contacts,
Labels, Holidays, Time blocks, etc."). static/tasks_table.js's existing
bulk bar is the precedent and is untouched by this slice except for one
addition: Habits-group rows (both the habit-labeled-task kind and the
standalone Habit-entity kind) now carry a `.row-select` checkbox too, so
they can be bulk-deleted from the same Tasks-page bar. Labels/Holidays/
Time blocks each get their own new bulk-delete JSON endpoint, driven by
the new generic `static/bulk_select.js` module (not covered by these
Python-side tests, which only exercise the routers) instead of a second
hand-rolled selection implementation.

2026-09-14 (direct request, "add bulk select for contacts too"): Contacts
gets the same treatment now -- it was deferred in the original pass
because its rows are a card-list, not a `<table>` (a `.row-select`
checkbox can't just live inside the row's own whole-row `<a>` without also
triggering the anchor's navigation/modal-open on a checkbox click).
`_contacts_body.html` now wraps each row in a `.contact-row-wrap` div (the
checkbox as a sibling before the `<a>`, not inside it) and
`static/bulk_select.js` gained a `rowSelector` option (default `tr`) so
this same module still drives it instead of a second hand-rolled
implementation."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import contacts as contacts_router
from src.routers import labels as labels_router
from src.routers import settings as settings_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_request(payload: dict) -> Request:
    body = json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/x",
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


class TestTasksBulkDelete:
    def test_deletes_plain_tasks_as_before(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "x", "description": "", "status": "active", "tags": [], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t2", "title": "y", "description": "", "status": "active", "tags": [], "created_at": _now()})
        import asyncio

        resp = asyncio.run(tasks_router.bulk_action(_json_request({"action": "delete", "uids": ["t1", "t2"]}), conn=conn))
        assert resp.status_code == 200
        assert json.loads(resp.body)["count"] == 2
        assert db.get_task(conn, "t1") is None
        assert db.get_task(conn, "t2") is None

    def test_both_empty_still_400s(self, conn):
        import asyncio

        resp = asyncio.run(tasks_router.bulk_action(_json_request({"action": "delete", "uids": []}), conn=conn))
        assert resp.status_code == 400

    def test_status_action_400s_on_empty_uids(self, conn):
        import asyncio

        resp = asyncio.run(tasks_router.bulk_action(_json_request({"action": "status", "uids": [], "status": "done"}), conn=conn))
        assert resp.status_code == 400



class TestLabelsBulkDelete:
    def test_clears_every_selected_label(self, conn):
        import asyncio

        db.set_object_labels(conn, "task", "t1", ["Work", "Personal"])
        resp = asyncio.run(labels_router.bulk_delete_labels(_json_request({"uids": ["Work", "Personal"]}), conn=conn))
        assert resp.status_code == 200
        assert json.loads(resp.body)["count"] == 2
        assert db.list_labels_for_object(conn, "task", "t1") == []

    def test_empty_selection_400s(self, conn):
        import asyncio

        resp = asyncio.run(labels_router.bulk_delete_labels(_json_request({"uids": []}), conn=conn))
        assert resp.status_code == 400


class TestLabelsBulkMerge:
    """2026-09-13 (direct request: "in the labels table bulk select i would
    like an option to merge labels into one"). `labels_router.bulk_merge_labels`
    is a plain loop over the existing single-pair `db.merge_labels` (see
    TestPhase2Labels' own merge coverage in test_phase2_labels.py for that
    function's own union/repoint semantics) -- these tests cover the bulk
    wrapper's own contract: merging N selected labels into one destination,
    skipping the destination if it's also among the selected names, and the
    modal-context GET endpoint that lists candidates."""

    def test_merges_every_selected_label_into_the_destination(self, conn):
        db.set_object_labels(conn, "task", "t1", ["Work"])
        db.set_object_labels(conn, "task", "t2", ["Errands"])
        db.set_object_labels(conn, "task", "t3", ["Chores"])
        resp = labels_router.bulk_merge_labels(uids=["Errands", "Chores"], dest_name="Work", conn=conn)
        assert resp.status_code == 303
        assert db.list_labels_for_object(conn, "task", "t1") == ["Work"]
        assert db.list_labels_for_object(conn, "task", "t2") == ["Work"]
        assert db.list_labels_for_object(conn, "task", "t3") == ["Work"]
        assert "Errands" not in db.list_all_label_names(conn)
        assert "Chores" not in db.list_all_label_names(conn)

    def test_destination_included_in_uids_is_skipped_not_merged_into_itself(self, conn):
        db.set_object_labels(conn, "task", "t1", ["Work"])
        db.set_object_labels(conn, "task", "t2", ["Errands"])
        resp = labels_router.bulk_merge_labels(uids=["Work", "Errands"], dest_name="Work", conn=conn)
        assert resp.status_code == 303
        assert db.list_labels_for_object(conn, "task", "t1") == ["Work"]
        assert db.list_labels_for_object(conn, "task", "t2") == ["Work"]

    def test_empty_dest_name_400s(self, conn):
        with pytest.raises(Exception):
            labels_router.bulk_merge_labels(uids=["Work", "Errands"], dest_name="  ", conn=conn)

    def test_reserved_dest_name_rejected(self, conn):
        with pytest.raises(Exception):
            labels_router.bulk_merge_labels(uids=["Work"], dest_name=db.PAGE_HEADER_BANNER_SCOPE, conn=conn)

    def test_bulk_merge_modal_lists_selected_and_all_label_names(self, conn):
        db.set_object_labels(conn, "task", "t1", ["Work"])
        db.set_object_labels(conn, "task", "t2", ["Errands"])
        db.set_object_labels(conn, "task", "t3", ["Chores"])
        req = Request(
            {
                "type": "http", "method": "GET", "path": "/settings/labels/bulk-merge-modal",
                "query_string": b"uids=Work,Errands", "scheme": "http", "server": ("t", 80),
                "root_path": "", "headers": [],
            }
        )
        resp = labels_router.bulk_merge_modal(uids="Work,Errands", request=req, conn=conn)
        ctx = resp.context
        assert ctx["selected_names"] == ["Work", "Errands"]
        assert ctx["all_label_names"] == ["Chores", "Errands", "Work"]


class TestHolidaysBulkDelete:
    def test_deletes_every_selected_holiday(self, conn):
        import asyncio

        db.upsert_holiday(conn, {"uid": "hol1", "calendar_name": "Default", "label": "X", "date_from": "2026-01-01", "date_to": "2026-01-02"})
        db.upsert_holiday(conn, {"uid": "hol2", "calendar_name": "Default", "label": "Y", "date_from": "2026-02-01", "date_to": "2026-02-02"})
        resp = asyncio.run(settings_router.bulk_delete_holidays(_json_request({"uids": ["hol1", "hol2"]}), conn=conn))
        assert resp.status_code == 200
        assert json.loads(resp.body)["count"] == 2
        assert db.get_holiday(conn, "hol1") is None
        assert db.get_holiday(conn, "hol2") is None

    def test_empty_selection_400s(self, conn):
        import asyncio

        resp = asyncio.run(settings_router.bulk_delete_holidays(_json_request({"uids": []}), conn=conn))
        assert resp.status_code == 400


class TestContactsBulkDelete:
    def test_deletes_every_selected_contact(self, conn):
        import asyncio

        db.upsert_contact(conn, {"uid": "c1", "full_name": "Alice A", "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c2", "full_name": "Bob B", "created_at": _now()})
        resp = asyncio.run(contacts_router.bulk_delete_contacts(_json_request({"uids": ["c1", "c2"]}), conn=conn))
        assert resp.status_code == 200
        assert json.loads(resp.body)["count"] == 2
        assert db.get_contact(conn, "c1") is None
        assert db.get_contact(conn, "c2") is None

    def test_empty_selection_400s(self, conn):
        import asyncio

        resp = asyncio.run(contacts_router.bulk_delete_contacts(_json_request({"uids": []}), conn=conn))
        assert resp.status_code == 400


class TestContactsRowSelectCheckbox:
    def test_contact_row_carries_row_select_and_wrap(self, conn):
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Alice A", "created_at": _now()})
        from src.routers import contacts as router

        body = router.list_contacts(
            Request({"type": "http", "method": "GET", "path": "/contacts", "query_string": b"", "scheme": "http", "server": ("t", 80), "root_path": "", "headers": []}),
            conn=conn,
        ).body.decode()
        assert 'class="contact-row-wrap" data-uid="c1"' in body
        assert 'class="row-select" data-uid="c1"' in body


class TestTimeBlocksBulkDelete:
    def test_deletes_selected_blocks_of_either_kind(self, conn):
        import asyncio

        db.upsert_time_block(conn, {"uid": "tb1", "kind": "sleep", "label": "Night", "start_time": "23:00", "end_time": "06:00", "days": "0,1,2,3,4,5,6"})
        db.upsert_time_block(conn, {"uid": "tb2", "kind": "leisure", "label": "Gaming", "start_time": "18:00", "end_time": "20:00", "days": "5,6"})
        resp = asyncio.run(settings_router.bulk_delete_time_blocks(_json_request({"uids": ["tb1", "tb2"]}), conn=conn))
        assert resp.status_code == 200
        assert json.loads(resp.body)["count"] == 2
        assert db.get_time_block(conn, "tb1") is None
        assert db.get_time_block(conn, "tb2") is None

    def test_empty_selection_400s(self, conn):
        import asyncio

        resp = asyncio.run(settings_router.bulk_delete_time_blocks(_json_request({"uids": []}), conn=conn))
        assert resp.status_code == 400
