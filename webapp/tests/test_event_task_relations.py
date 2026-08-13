"""Tests for the 2026-08-09 "Relations" feature -- explicit event<->task
associative links, the webapp's answer to desktop's old links/backlinks
graph (features/architecture.md Phase 8 left it an accepted gap).

Rules, as specified:
- A relation links exactly one event to exactly one task (many-to-many
  across the two types, stored in `event_task_relations`).
- An event and a task may only be related when they carry at least one
  label in common -- "both have at least one label in common". The add
  row's picker only offers candidates that already share a label, and the
  routers re-check defensively.
- The Relations card is the merged successor of the old Subtasks card
  ("Subtasks is already very similar to this feature so they should just
  be merged"): a task's card shows subtasks + related events, an event's
  card shows related tasks.
- Both "link an existing object" and "create a new one" are supported; a
  new object inherits the source object's labels, guaranteeing the rule.
- Relations are associative, never cascade: deleting one side leaves the
  other alone."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/"):
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


def _seed_event(conn, uid, tags=None, **overrides):
    row = {
        "uid": uid,
        "title": uid,
        "description": "",
        "start_at": "2026-08-10T09:00:00",
        "status": "active",
        "all_day": False,
        "tags": tags or [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_event(conn, row)
    return db.get_event(conn, uid)


def _seed_task(conn, uid, tags=None, **overrides):
    row = {
        "uid": uid,
        "title": uid,
        "description": "",
        "status": "active",
        "tags": tags or [],
        "created_at": _now(),
    }
    row.update(overrides)
    db.upsert_task(conn, row)
    return db.get_task(conn, uid)


class TestRelationStorage:
    def test_add_and_list_is_idempotent(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        db.add_event_task_relation(conn, "e1", "t1")  # duplicate is a no-op
        rows = db.list_event_task_relations(conn)
        assert len(rows) == 1
        assert rows[0]["event_uid"] == "e1"
        assert rows[0]["task_uid"] == "t1"

    def test_remove(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        db.remove_event_task_relation(conn, "e1", "t1")
        assert db.list_event_task_relations(conn) == []

    def test_related_tasks_for_event_returns_full_task_rows(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"], due_at="2026-09-01")
        _seed_task(conn, "t2", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t2")
        db.add_event_task_relation(conn, "e1", "t1")
        related = db.related_tasks_for_event(conn, "e1")
        # Ordered like list_tasks: dated first, then by due date.
        assert [t["uid"] for t in related] == ["t1", "t2"]
        assert related[0]["tags"] == ["Work"]  # labels attached

    def test_related_events_for_task(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_event(conn, "e2", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        db.add_event_task_relation(conn, "e2", "t1")
        assert {e["uid"] for e in db.related_events_for_task(conn, "t1")} == {"e1", "e2"}
        assert db.related_events_for_task(conn, "nope") == []

    def test_delete_event_cleans_only_its_side(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_event(conn, "e2", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        db.add_event_task_relation(conn, "e2", "t1")
        db.delete_event(conn, "e1")
        rows = db.list_event_task_relations(conn)
        assert len(rows) == 1
        assert rows[0]["event_uid"] == "e2"
        # The task itself survives.
        assert db.get_task(conn, "t1") is not None

    def test_delete_task_cleans_only_its_side(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"])
        _seed_task(conn, "t2", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        db.add_event_task_relation(conn, "e1", "t2")
        db.delete_task(conn, "t1")
        rows = db.list_event_task_relations(conn)
        assert len(rows) == 1
        assert rows[0]["task_uid"] == "t2"
        assert db.get_event(conn, "e1") is not None

    def test_purge_all_data_includes_relations(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        db.purge_all_data(conn)
        assert db.list_event_task_relations(conn) == []


class TestSharingLabelCandidates:
    def test_list_events_sharing_labels_matches_any_one(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_event(conn, "e2", tags=["Home"])
        _seed_event(conn, "e3", tags=["Work", "Urgent"])
        got = {e["uid"] for e in db.list_events_sharing_labels(conn, ["Work", "Urgent"])}
        assert got == {"e1", "e3"}

    def test_list_events_sharing_labels_empty_when_no_labels(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        assert db.list_events_sharing_labels(conn, []) == []

    def test_list_tasks_sharing_labels_excludes_habit_tasks(self, conn):
        _seed_task(conn, "t1", tags=["Work"])
        _seed_task(conn, "t2", tags=["Habit", "Work"])
        got = {t["uid"] for t in db.list_tasks_sharing_labels(conn, ["Work"])}
        assert got == {"t1"}

    def test_event_detail_picker_only_offers_shared_label_tasks(self, conn):
        # 1.2 side work (Universal command surface step 3): the page no
        # longer renders a candidate pool up front -- the picker overlay
        # asks GET /api/search?for_event=<uid> for exactly the page it
        # needs (see test_search_api.py's TestForEventFilter for the
        # actual shared-label-and-not-already-linked filtering coverage).
        # This test now only covers that the trigger carries the right
        # implicit-filter context to drive that request.
        _seed_event(conn, "e1", tags=["Work"])
        body = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode()
        assert 'data-for-event="e1"' in body
        assert 'data-relations-picker' in body


class TestEventRelationsCard:
    def test_event_detail_renders_relations_card_with_related_tasks(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        body = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode()
        assert "Relations" in body
        assert "Related tasks" in body
        assert "/tasks/t1" in body
        assert "/events/e1/relations/remove" in body
        assert "/events/e1/relations" in body  # the add form

    def test_event_detail_related_task_shows_status_dot(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"], status="in_progress")
        db.add_event_task_relation(conn, "e1", "t1")
        body = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode()
        assert 'class="detail-identity-dot cal-orange"' in body

    def test_event_detail_unlabeled_shows_hint_not_picker(self, conn):
        _seed_event(conn, "e1", tags=[])
        _seed_task(conn, "t1", tags=["Work"])
        body = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode()
        assert "Add a label to this event to relate tasks." in body
        assert "data-relations-picker" not in body

    def test_event_form_renders_relations_card_on_edit(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        body = calendar_router.edit_event_form("e1", _request("/events/e1/edit"), conn=conn).body.decode()
        assert "/events/e1/relations" in body
        assert "/tasks/t1" in body

    def test_new_event_form_has_no_relations_card(self, conn):
        body = calendar_router.new_event_form(_request("/events/new"), conn=conn).body.decode()
        assert "/events//relations" not in body

    def test_add_event_relation_links_existing_shared_label_task(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"])
        resp = calendar_router.add_event_relation("e1", target_uid="t1", new_title="", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"].endswith("/events/e1")
        assert [t["uid"] for t in db.related_tasks_for_event(conn, "e1")] == ["t1"]

    def test_add_event_relation_rejects_task_without_shared_label(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_task(conn, "t2", tags=["Home"])
        calendar_router.add_event_relation("e1", target_uid="t2", new_title="", conn=conn)
        assert db.related_tasks_for_event(conn, "e1") == []

    def test_add_event_relation_creates_new_task_inheriting_labels(self, conn):
        _seed_event(conn, "e1", tags=["Work", "Urgent"])
        calendar_router.add_event_relation("e1", target_uid="__new__", new_title="Fresh", conn=conn)
        new = [t for t in db.list_tasks(conn, include_habit_tasks=True) if t["title"] == "Fresh"]
        assert len(new) == 1
        assert sorted(new[0]["tags"]) == ["Urgent", "Work"]
        assert [t["uid"] for t in db.related_tasks_for_event(conn, "e1")] == [new[0]["uid"]]

    def test_add_event_relation_new_task_from_unlabeled_event_creates_nothing(self, conn):
        _seed_event(conn, "e0", tags=[])
        before = len(db.list_tasks(conn, include_habit_tasks=True))
        calendar_router.add_event_relation("e0", target_uid="__new__", new_title="Orphan", conn=conn)
        assert len(db.list_tasks(conn, include_habit_tasks=True)) == before
        assert db.related_tasks_for_event(conn, "e0") == []

    def test_remove_event_relation_unlinks_but_keeps_task(self, conn):
        _seed_event(conn, "e1", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        calendar_router.remove_event_relation("e1", task_uid="t1", conn=conn)
        assert db.related_tasks_for_event(conn, "e1") == []
        assert db.get_task(conn, "t1") is not None


class TestTaskRelationsCard:
    def test_task_detail_card_shows_related_events_only(self, conn):
        _seed_task(conn, "t1", tags=["Work"])
        _seed_event(conn, "e1", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        assert "Relations" in body
        assert "Related events" in body
        # 1.2: tasks are flat -- no subtask group-head in the Relations card.
        assert '>Subtasks</div>' not in body
        assert "/events/e1" in body  # related event link
        assert "/tasks/t1/relations/remove" in body
        assert "/tasks/t1/relations" in body
        # Still exactly two detail cards: meta + Relations.
        assert body.count('class="detail-card') == 2

    def test_task_detail_picker_only_offers_shared_label_events(self, conn):
        # See test_event_detail_picker_only_offers_shared_label_tasks above
        # for why this no longer checks a rendered option pool -- the
        # filtering itself is covered by test_search_api.py's
        # TestForTaskFilter now that it happens via GET /api/search.
        _seed_task(conn, "t1", tags=["Work"])
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        assert 'data-for-task="t1"' in body
        assert 'data-relations-picker' in body

    def test_task_form_renders_merged_card_on_edit(self, conn):
        _seed_task(conn, "t1", tags=["Work"])
        _seed_event(conn, "e1", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        body = tasks_router.edit_task_form("t1", _request("/tasks/t1/edit"), conn=conn).body.decode()
        assert "/tasks/t1/relations" in body
        assert "/events/e1" in body

    def test_add_task_relation_links_existing_shared_label_event(self, conn):
        _seed_task(conn, "t1", tags=["Work"])
        _seed_event(conn, "e1", tags=["Work"])
        tasks_router.add_task_relation("t1", target_uid="e1", new_title="", conn=conn)
        assert [e["uid"] for e in db.related_events_for_task(conn, "t1")] == ["e1"]

    def test_add_task_relation_rejects_event_without_shared_label(self, conn):
        _seed_task(conn, "t1", tags=["Work"])
        _seed_event(conn, "e2", tags=["Home"])
        tasks_router.add_task_relation("t1", target_uid="e2", new_title="", conn=conn)
        assert db.related_events_for_task(conn, "t1") == []

    def test_add_task_relation_creates_new_event_inheriting_labels(self, conn):
        _seed_task(conn, "t1", tags=["Work"])
        tasks_router.add_task_relation("t1", target_uid="__new__", new_title="Fresh event", conn=conn)
        new = [e for e in db.list_events(conn) if e["title"] == "Fresh event"]
        assert len(new) == 1
        assert new[0]["tags"] == ["Work"]
        assert new[0]["start_at"].startswith("2026-")  # defaults to a real date, not today-9am hardcoded
        assert [e["uid"] for e in db.related_events_for_task(conn, "t1")] == [new[0]["uid"]]

    def test_remove_task_relation_unlinks_but_keeps_event(self, conn):
        _seed_task(conn, "t1", tags=["Work"])
        _seed_event(conn, "e1", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        tasks_router.remove_task_relation("t1", event_uid="e1", conn=conn)
        assert db.related_events_for_task(conn, "t1") == []
        assert db.get_event(conn, "e1") is not None
