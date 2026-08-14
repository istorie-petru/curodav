"""Phase 6 (label-space rework) acceptance tests -- see
features/architecture.md §2/§3 Phase 6:

  * `evaluate_label_filter` for all/any/none combinations, including the
    plan's own example (`University AND NOT Archived`);
  * `materialize()` against a fake bridge creates/updates/deletes the
    right members and is idempotent on a second call with no membership
    change;
  * a List's target collection only contains members matching the
    current filter after a membership change (add/remove a label,
    re-materialize, assert the collection updated);
  * Settings CRUD round-trip (create/edit/delete a List via the router).

Also: this version is read-only from the subscriber's side -- nothing
below ever calls ical_to_*_row/vcard_to_contact_row against the published
collection (only row-to-ical/vcard OUT, via the bridge's save_*_row). See
the read-only-ness assertions in TestReadOnlyness.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db
from src.published_lists import evaluate_label_filter, materialize, materialize_all


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


# --------------------------------------------------------------------- #
# A fake CalDavBridge -- only the methods published_lists.py actually
# calls (list_*_rows / save_*_row / delete_*), each collection modeled as
# a plain dict keyed by uid, same "in-memory stand-in for Radicale" idea
# real tests elsewhere use for the DB itself.
# --------------------------------------------------------------------- #


class FakeBridge:
    def __init__(self):
        self.event_collections: dict[str, dict[str, dict]] = {}
        self.task_collections: dict[str, dict[str, dict]] = {}
        self.contact_collections: dict[str, dict[str, dict]] = {}
        self.deleted_calendar_collections: list[str] = []
        self.deleted_task_list_collections: list[str] = []
        self.deleted_addressbook_collections: list[str] = []

    # events
    def list_event_rows(self, calendar_path):
        return list(self.event_collections.get(calendar_path, {}).values())

    def save_event_row(self, row):
        path = row.get("calendar_path") or "calendar"
        self.event_collections.setdefault(path, {})[row["uid"]] = dict(row)
        return row

    def delete_event(self, uid, calendar_path):
        self.event_collections.get(calendar_path, {}).pop(uid, None)

    def delete_calendar_collection(self, calendar_path):
        self.event_collections.pop(calendar_path, None)
        self.deleted_calendar_collections.append(calendar_path)

    # tasks
    def list_task_rows(self, list_path):
        return list(self.task_collections.get(list_path, {}).values())

    def save_task_row(self, row):
        path = row.get("list_path") or "tasks"
        self.task_collections.setdefault(path, {})[row["uid"]] = dict(row)
        return row

    def delete_task(self, uid, list_path):
        self.task_collections.get(list_path, {}).pop(uid, None)

    def delete_task_list_collection(self, list_path):
        self.task_collections.pop(list_path, None)
        self.deleted_task_list_collections.append(list_path)

    # contacts
    def list_contact_rows(self, addressbook_path):
        return list(self.contact_collections.get(addressbook_path, {}).values())

    def save_contact_row(self, row):
        path = row.get("addressbook_path") or "contacts"
        self.contact_collections.setdefault(path, {})[row["uid"]] = dict(row)
        return row

    def delete_contact(self, uid, addressbook_path):
        self.contact_collections.get(addressbook_path, {}).pop(uid, None)

    def delete_addressbook_collection(self, addressbook_path):
        self.contact_collections.pop(addressbook_path, None)
        self.deleted_addressbook_collections.append(addressbook_path)


def _make_task(conn, uid, title, tags):
    db.upsert_task(conn, {"uid": uid, "title": title, "description": "", "status": "active", "tags": tags, "created_at": _now()})


# --------------------------------------------------------------------- #
# evaluate_label_filter
# --------------------------------------------------------------------- #


class TestEvaluateLabelFilter:
    def test_all_is_and(self, conn):
        _make_task(conn, "t1", "A", ["University", "Homework"])
        _make_task(conn, "t2", "B", ["University"])
        _make_task(conn, "t3", "C", ["Homework"])
        result = evaluate_label_filter(conn, "task", {"all": ["University", "Homework"]})
        assert result == ["t1"]

    def test_any_is_or(self, conn):
        _make_task(conn, "t1", "A", ["University"])
        _make_task(conn, "t2", "B", ["Personal"])
        _make_task(conn, "t3", "C", ["Work"])
        result = evaluate_label_filter(conn, "task", {"any": ["University", "Personal"]})
        assert set(result) == {"t1", "t2"}

    def test_none_excludes(self, conn):
        _make_task(conn, "t1", "A", ["University"])
        _make_task(conn, "t2", "B", ["University", "Archived"])
        result = evaluate_label_filter(conn, "task", {"all": ["University"], "none": ["Archived"]})
        assert result == ["t1"]

    def test_plan_example_university_and_not_archived(self, conn):
        # features/architecture.md §2: "University AND NOT Archived"
        _make_task(conn, "t1", "Assignment 1", ["University"])
        _make_task(conn, "t2", "Old assignment", ["University", "Archived"])
        _make_task(conn, "t3", "Unrelated", ["Personal"])
        result = evaluate_label_filter(conn, "task", {"all": ["University"], "any": [], "none": ["Archived"]})
        assert result == ["t1"]

    def test_all_and_any_combine_with_and(self, conn):
        _make_task(conn, "t1", "A", ["University", "Homework"])
        _make_task(conn, "t2", "B", ["University", "Exam"])
        _make_task(conn, "t3", "C", ["University"])
        _make_task(conn, "t4", "D", ["Homework"])
        result = evaluate_label_filter(
            conn, "task", {"all": ["University"], "any": ["Homework", "Exam"]}
        )
        assert set(result) == {"t1", "t2"}

    def test_no_positive_criteria_matches_nothing(self, conn):
        _make_task(conn, "t1", "A", ["University"])
        assert evaluate_label_filter(conn, "task", {}) == []
        assert evaluate_label_filter(conn, "task", None) == []
        assert evaluate_label_filter(conn, "task", {"none": ["University"]}) == []

    def test_scoped_to_entity_type(self, conn):
        _make_task(conn, "t1", "A", ["University"])
        db.upsert_event(conn, {"uid": "e1", "title": "Lecture", "description": "", "all_day": 0, "status": "active", "tags": ["University"], "created_at": _now()})
        assert evaluate_label_filter(conn, "task", {"all": ["University"]}) == ["t1"]
        assert evaluate_label_filter(conn, "event", {"all": ["University"]}) == ["e1"]


# --------------------------------------------------------------------- #
# materialize()
# --------------------------------------------------------------------- #


class TestMaterialize:
    def _list_row(self, list_id="lst1", entity_type="task", label_filter=None, collection="published-uni"):
        return {
            "id": list_id,
            "name": "University tasks",
            "entity_type": entity_type,
            "label_filter": label_filter or {"all": ["University"]},
            "radicale_collection_path": collection,
            "sync_direction": "read_only",
            "last_materialized_at": None,
            "created_at": _now(),
        }

    def test_creates_matching_members(self, conn):
        _make_task(conn, "t1", "A", ["University"])
        _make_task(conn, "t2", "B", ["Personal"])
        bridge = FakeBridge()
        summary = materialize(conn, bridge, self._list_row())
        assert summary == {"created": 1, "updated": 0, "deleted": 0, "member_count": 1}
        assert set(bridge.event_collections.get("published-uni", {})) == set()
        assert set(bridge.task_collections["published-uni"]) == {"t1"}

    def test_idempotent_on_second_call(self, conn):
        _make_task(conn, "t1", "A", ["University"])
        bridge = FakeBridge()
        materialize(conn, bridge, self._list_row())
        summary2 = materialize(conn, bridge, self._list_row())
        assert summary2 == {"created": 0, "updated": 1, "deleted": 0, "member_count": 1}
        assert set(bridge.task_collections["published-uni"]) == {"t1"}

    def test_deletes_stale_members_no_longer_matching(self, conn):
        _make_task(conn, "t1", "A", ["University"])
        _make_task(conn, "t2", "B", ["University"])
        bridge = FakeBridge()
        list_row = self._list_row()
        materialize(conn, bridge, list_row)
        assert set(bridge.task_collections["published-uni"]) == {"t1", "t2"}

        # t2 loses the label -- no longer a member.
        db.set_object_labels(conn, "task", "t2", [])
        summary = materialize(conn, bridge, list_row)
        assert summary["deleted"] == 1
        assert set(bridge.task_collections["published-uni"]) == {"t1"}

    def test_collection_reflects_current_filter_after_membership_change(self, conn):
        _make_task(conn, "t1", "A", ["University"])
        bridge = FakeBridge()
        list_row = self._list_row()
        materialize(conn, bridge, list_row)
        assert set(bridge.task_collections["published-uni"]) == {"t1"}

        # A new task gains the label -- should appear on next materialize.
        _make_task(conn, "t2", "B", ["University"])
        materialize(conn, bridge, list_row)
        assert set(bridge.task_collections["published-uni"]) == {"t1", "t2"}

        # t1 loses the label -- should disappear.
        db.set_object_labels(conn, "task", "t1", [])
        materialize(conn, bridge, list_row)
        assert set(bridge.task_collections["published-uni"]) == {"t2"}

    def test_events_and_contacts_also_materialize(self, conn):
        db.upsert_event(conn, {"uid": "e1", "title": "Lecture", "description": "", "all_day": 0, "status": "active", "tags": ["University"], "created_at": _now(), "start_at": "2026-08-17T16:00:00", "end_at": "2026-08-17T18:00:00"})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Prof X", "tags": ["University"], "created_at": _now()})
        bridge = FakeBridge()
        materialize(conn, bridge, self._list_row("lst2", "event", collection="published-events"))
        materialize(conn, bridge, self._list_row("lst3", "contact", collection="published-contacts"))
        assert set(bridge.event_collections["published-events"]) == {"e1"}
        assert set(bridge.contact_collections["published-contacts"]) == {"c1"}

    def test_undated_event_member_is_skipped(self, conn):
        """An undated work-session placeholder (the Work sessions "+" on a
        task card) has no start_at yet -- it must not be pushed to a
        published event collection as a DTSTART-less VEVENT. A dated event
        with the same label still materializes."""
        db.upsert_event(conn, {"uid": "e1", "title": "Lecture", "description": "", "all_day": 0, "status": "active", "tags": ["University"], "created_at": _now(), "start_at": "2026-08-17T16:00:00", "end_at": "2026-08-17T18:00:00"})
        db.upsert_event(conn, {"uid": "e2", "title": "Unplaced session", "description": "", "all_day": 0, "status": "active", "tags": ["University"], "created_at": _now()})
        bridge = FakeBridge()
        materialize(conn, bridge, self._list_row("lst2", "event", collection="published-events"))
        assert set(bridge.event_collections["published-events"]) == {"e1"}

    def test_materialize_records_last_materialized_at(self, conn):
        _make_task(conn, "t1", "A", ["University"])
        list_row = self._list_row()
        db.upsert_published_list(conn, list_row)
        saved = db.get_published_list(conn, "lst1")
        assert saved["last_materialized_at"] is None
        materialize(conn, FakeBridge(), saved)
        refreshed = db.get_published_list(conn, "lst1")
        assert refreshed["last_materialized_at"] is not None

    def test_materialize_all_isolates_per_list_failures(self, conn):
        _make_task(conn, "t1", "A", ["University"])
        db.upsert_published_list(conn, self._list_row())
        db.upsert_published_list(conn, self._list_row("bad", entity_type="not_a_real_type", collection="published-bad"))
        results = materialize_all(conn, FakeBridge())
        assert "lst1" in results
        assert "bad" not in results  # raised ValueError, caught and logged, skipped


# --------------------------------------------------------------------- #
# Settings CRUD round-trip (routers/published_lists.py)
# --------------------------------------------------------------------- #


class TestPublishedListsRouterCrud:
    def test_create_edit_delete_round_trip(self, conn):
        from src.routers import published_lists as router

        _make_task(conn, "t1", "A", ["University"])
        bridge = FakeBridge()

        router.create_list(
            name="Uni tasks", entity_type="task",
            filter_all=["University"], filter_any=[], filter_none=[],
            conn=conn, bridge=bridge,
        )
        rows = db.list_published_lists(conn)
        assert len(rows) == 1
        list_id = rows[0]["id"]
        assert rows[0]["radicale_collection_path"] == "published-uni-tasks"
        assert set(bridge.task_collections["published-uni-tasks"]) == {"t1"}

        # Edit: broaden the filter to include a second label via "any".
        _make_task(conn, "t2", "B", ["Personal"])
        router.update_list(
            list_id, name="Uni tasks", filter_all=[], filter_any=["University", "Personal"],
            filter_none=[], conn=conn, bridge=bridge,
        )
        updated = db.get_published_list(conn, list_id)
        assert updated["label_filter"] == {"all": [], "any": ["University", "Personal"], "none": []}
        assert set(bridge.task_collections["published-uni-tasks"]) == {"t1", "t2"}

        # Delete: row gone AND the collection torn down via the bridge.
        router.delete_list(list_id, conn=conn, bridge=bridge)
        assert db.get_published_list(conn, list_id) is None
        assert "published-uni-tasks" in bridge.deleted_task_list_collections

    def test_create_slugifies_name_and_dedupes_collection_path(self, conn):
        from src.routers import published_lists as router

        bridge = FakeBridge()
        router.create_list(name="My List!!", entity_type="task", filter_all=[], filter_any=[], filter_none=[], conn=conn, bridge=bridge)
        router.create_list(name="My List!!", entity_type="task", filter_all=[], filter_any=[], filter_none=[], conn=conn, bridge=bridge)
        rows = db.list_published_lists(conn)
        paths = {r["radicale_collection_path"] for r in rows}
        assert paths == {"published-my-list", "published-my-list-2"}

    def test_list_index_includes_subscribe_url(self, conn):
        from starlette.requests import Request

        from src.routers import published_lists as router

        bridge = FakeBridge()
        router.create_list(name="Uni", entity_type="task", filter_all=["University"], filter_any=[], filter_none=[], conn=conn, bridge=bridge)

        request = Request(
            {
                "type": "http", "method": "GET", "path": "/published-lists",
                "query_string": b"", "scheme": "http", "server": ("testserver", 80),
                "root_path": "", "headers": [],
                "app": _FakeApp(),
            }
        )
        resp = router.list_index(request, conn=conn)
        assert resp.status_code == 200
        assert resp.context["lists"][0]["subscribe_url"] == "http://127.0.0.1:5232/devuser/published-uni/"


class _FakeSettings:
    radicale_base_url = "http://127.0.0.1:5232/devuser/"


class _FakeAppState:
    settings = _FakeSettings()


class _FakeApp:
    state = _FakeAppState()


# --------------------------------------------------------------------- #
# Read-only-ness: v1 never parses a published collection's contents back
# into a row -- only row-to-ical/vcard OUT via the bridge's save_*_row.
# --------------------------------------------------------------------- #


class TestReadOnlyness:
    def test_sync_direction_defaults_to_read_only(self, conn):
        from src.routers import published_lists as router

        bridge = FakeBridge()
        router.create_list(name="Uni", entity_type="task", filter_all=["University"], filter_any=[], filter_none=[], conn=conn, bridge=bridge)
        row = db.list_published_lists(conn)[0]
        assert row["sync_direction"] == "read_only"

    def test_materialize_module_never_imports_ical_to_row_parsers(self):
        # Sanity check that the materializer stays a one-way push -- no
        # reverse (ical/vcard -> row) parser is even referenced in this
        # module's source, so there is no code path that could apply a
        # subscriber's edit back onto the row it came from.
        import inspect

        from src import published_lists as published_lists_module

        # Only inspect the real code (functions), not the module's own
        # prose docstrings, which legitimately name these functions when
        # explaining what this module deliberately does NOT do.
        for _, obj in inspect.getmembers(published_lists_module, inspect.isfunction):
            if obj.__module__ != published_lists_module.__name__:
                continue
            body_source = inspect.getsource(obj)
            assert "ical_to_event_row" not in body_source
            assert "ical_to_task_row" not in body_source
            assert "vcard_to_contact_row" not in body_source
