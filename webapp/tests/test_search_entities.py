"""Tests for `db.search_entities` -- the shared query layer behind the
universal command surface (1.2, plans/open.md § Universal command surface).
One function finds tasks/events/contacts by name plus working filters; every
future invocation mode (Ctrl-K global search, the relation picker, per-view
search boxes) delegates to it instead of each view's own q= handling.

Filter vocabulary under test (explicit, AND together):
  - q:          free-text over title/description/labels (and contact
                name/org/phone/email)
  - types:      subset of task/event/contact
  - labels:     multi-select, any-match
  - task_status, task_due_on: task-only filters
  - event_start, event_end:   event-only date-range filter
Implicit:
  - exclude_uids (not-already-linked for the relation picker)
  - include_habit_tasks=False hides habit-labeled tasks (list_tasks' rule)
"""

from __future__ import annotations

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


def _seed(conn):
    db.upsert_task(
        conn,
        {"uid": "t1", "title": "Write report", "description": "quarterly recap",
         "due_at": "2026-08-20", "status": "active", "created_at": _now(), "tags": ["Work"]},
    )
    db.upsert_task(
        conn,
        {"uid": "t2", "title": "Call dentist", "description": "",
         "due_at": "2026-08-10", "status": "in_progress", "created_at": _now(), "tags": ["Health"]},
    )
    db.upsert_event(
        conn,
        {"uid": "e1", "title": "Standup", "description": "daily sync",
         "start_at": "2026-08-11T09:00:00", "end_at": "2026-08-11T09:30:00",
         "all_day": False, "status": "active",
         "created_at": _now(), "updated_at": _now(), "tags": ["Work"]},
    )
    db.upsert_contact(
        conn,
        {"uid": "c1", "full_name": "Ada Lovelace", "org": "UCL", "phone": "+123",
         "email": "ada@example.com", "tags": ["Colleague"], "created_at": _now(), "updated_at": _now()},
    )


def _titles(results):
    return [(r["type"], r["title"]) for r in results]


class TestSearchAll:
    def test_empty_db(self, conn):
        assert db.search_entities(conn) == []

    def test_no_filters_returns_everything(self, conn):
        _seed(conn)
        assert sorted(_titles(db.search_entities(conn))) == [
            ("contact", "Ada Lovelace"),
            ("event", "Standup"),
            ("task", "Call dentist"),
            ("task", "Write report"),
        ]

    def test_results_carried_the_picker_surface_keys(self, conn):
        _seed(conn)
        r = db.search_entities(conn, q="report")[0]
        assert r["type"] == "task"
        assert r["uid"] == "t1"
        assert r["title"] == "Write report"
        assert r["tags"] == ["Work"]
        assert r["entity"]["description"] == "quarterly recap"
        assert "No due date" not in r["subtitle"]


class TestTypesFilter:
    def test_task_only(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, types=["task"])) == [
            ("task", "Call dentist"),
            ("task", "Write report"),
        ]

    def test_event_only(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, types=["event"])) == [("event", "Standup")]

    def test_contact_only(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, types=["contact"])) == [("contact", "Ada Lovelace")]

    def test_pair(self, conn):
        _seed(conn)
        assert sorted(_titles(db.search_entities(conn, types=["task", "contact"]))) == [
            ("contact", "Ada Lovelace"),
            ("task", "Call dentist"),
            ("task", "Write report"),
        ]


class TestFreeTextQ:
    def test_matches_task_title(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, q="report")) == [("task", "Write report")]

    def test_matches_task_description(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, q="quarterly")) == [("task", "Write report")]

    def test_matches_event_title(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, q="standup")) == [("event", "Standup")]

    def test_matches_contact_email(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, q="ada@example.com")) == [("contact", "Ada Lovelace")]

    def test_matches_contact_org(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, q="ucl")) == [("contact", "Ada Lovelace")]

    def test_case_insensitive(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, q="REPORT")) == [("task", "Write report")]

    def test_no_match(self, conn):
        _seed(conn)
        assert db.search_entities(conn, q="zzznope") == []


class TestLabelsFilter:
    def test_any_match_across_types(self, conn):
        _seed(conn)
        # "Work" labels the task and the event; "Health" the other task.
        assert sorted(_titles(db.search_entities(conn, labels=["Work"]))) == [
            ("event", "Standup"),
            ("task", "Write report"),
        ]

    def test_multi_select_is_any_match(self, conn):
        _seed(conn)
        assert sorted(_titles(db.search_entities(conn, labels=["Work", "Health"]))) == [
            ("event", "Standup"),
            ("task", "Call dentist"),
            ("task", "Write report"),
        ]

    def test_contact_label(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, labels=["Colleague"])) == [("contact", "Ada Lovelace")]

    def test_labels_and_q_and(self, conn):
        _seed(conn)
        # Both filters must hold (AND): "report" narrows to t1, "Work"
        # already matches it -- still one hit. "Health" would contradict.
        assert _titles(db.search_entities(conn, q="report", labels=["Work"])) == [("task", "Write report")]
        assert db.search_entities(conn, q="report", labels=["Health"]) == []


class TestTaskOnlyFilters:
    def test_status(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, task_status="in_progress")) == [("task", "Call dentist")]
        assert _titles(db.search_entities(conn, task_status="active")) == [("task", "Write report")]

    def test_due_on(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, task_due_on="2026-08-10")) == [("task", "Call dentist")]
        assert db.search_entities(conn, task_due_on="2026-08-11") == []

    def test_status_and_due_and(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, task_status="active", task_due_on="2026-08-20")) == [
            ("task", "Write report")
        ]
        assert db.search_entities(conn, task_status="in_progress", task_due_on="2026-08-20") == []


class TestEventDateRange:
    def test_start_only(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, event_start="2026-08-11")) == [("event", "Standup")]
        assert db.search_entities(conn, event_start="2026-08-12") == []

    def test_end_only(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, event_end="2026-08-12")) == [("event", "Standup")]
        assert db.search_entities(conn, event_end="2026-08-10") == []

    def test_range(self, conn):
        _seed(conn)
        assert _titles(db.search_entities(conn, event_start="2026-08-11", event_end="2026-08-11")) == [
            ("event", "Standup")
        ]


class TestImplicitFilters:
    def test_exclude_uids_drops_linked_items(self, conn):
        _seed(conn)
        # The relation picker's "not-already-linked" rule.
        result = db.search_entities(conn, types=["event"], exclude_uids={"event": {"e1"}})
        assert result == []

    def test_exclude_uids_is_per_type(self, conn):
        _seed(conn)
        result = db.search_entities(conn, exclude_uids={"event": {"e1"}})
        assert sorted(_titles(result)) == [
            ("contact", "Ada Lovelace"),
            ("task", "Call dentist"),
            ("task", "Write report"),
        ]

    def test_habit_tasks_hidden_by_default(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "Habit task", "description": "", "status": "active", "created_at": _now(), "tags": ["Habit"]})
        db.save_task_habit_settings(conn, "Habit")
        assert db.search_entities(conn, q="Habit task") == []
        assert _titles(db.search_entities(conn, q="Habit task", include_habit_tasks=True)) == [
            ("task", "Habit task")
        ]

    def test_limit(self, conn):
        _seed(conn)
        assert len(db.search_entities(conn, limit=2)) == 2
        assert len(db.search_entities(conn, limit=1)) == 1
