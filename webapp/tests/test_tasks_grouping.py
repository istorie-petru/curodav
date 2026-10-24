"""The Tasks list's grouping: one section per shelf (alphabetical), tasks with no tag, then Completed last. A shelf
section holds a sub-group per tag, and a task sits under every tag it carries. Every group is due-date ascending."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db, tags
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(query_string=b""):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/tasks",
            "query_string": query_string,
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _task(conn, uid, tags=None, status="active", due_at=None, title=None):
    db.upsert_task(
        conn,
        {
            "uid": uid, "title": title or uid, "description": "", "status": status,
            "tags": tags or [], "created_at": _now(), "due_at": due_at,
        },
    )


def _shelf_tag(conn, shelf, name):
    """A tag `name` on shelf `shelf`."""
    tags.ensure_schema(conn)
    conn.execute("INSERT OR IGNORE INTO label_tags (name, label_name) VALUES (?, ?)", (name, shelf))
    conn.commit()


def _tagged(conn, uid, names, **kw):
    _task(conn, uid, tags=[], **kw)
    tags.set_object_tags(conn, "task", uid, names)


def _group(groups, kind, name=None):
    for g in groups:
        if g["kind"] == kind and (name is None or g["name"] == name):
            return g
    raise AssertionError(f"no group kind={kind} name={name} in {[ (g['kind'], g['name']) for g in groups ]}")


def _groups(conn):
    return tasks_router.list_tasks(_request(), conn=conn).context["groups"]


class TestFixedGroupOrder:
    def test_shelves_then_untagged_then_completed(self, conn):
        _shelf_tag(conn, "Home", "Chores")
        _tagged(conn, "a1", ["Chores"])
        _task(conn, "loose1", tags=[])
        _tagged(conn, "done1", ["Chores"], status="done")
        assert [g["kind"] for g in _groups(conn)] == ["label", "unassigned", "completed"]

    def test_shelves_are_alphabetical_case_insensitive(self, conn):
        for shelf in ("banana", "Apple", "cherry"):
            _shelf_tag(conn, shelf, shelf)
            _tagged(conn, shelf, [shelf])
        assert [g["name"] for g in _groups(conn)] == ["Apple", "banana", "cherry"]


class TestTagSubgroups:
    def test_a_shelf_section_has_a_subgroup_per_tag(self, conn):
        _shelf_tag(conn, "Work", "Client A")
        _shelf_tag(conn, "Work", "Client B")
        _tagged(conn, "a1", ["Client A"])
        _tagged(conn, "b1", ["Client B"])
        work = _group(_groups(conn), "label", "Work")
        assert [(s["name"], [t["uid"] for t in s["tasks"]]) for s in work["subgroups"]] == [("Client A", ["a1"]), ("Client B", ["b1"])]

    def test_a_task_sits_under_every_tag_but_is_counted_once_in_its_section(self, conn):
        _shelf_tag(conn, "Work", "Client A")
        _shelf_tag(conn, "Work", "Client B")
        _tagged(conn, "t1", ["Client A", "Client B"])
        work = _group(_groups(conn), "label", "Work")
        assert all([t["uid"] for t in s["tasks"]] == ["t1"] for s in work["subgroups"])
        assert [t["uid"] for t in work["tasks"]] == ["t1"]

    def test_a_task_with_tags_on_two_shelves_appears_in_both_sections(self, conn):
        _shelf_tag(conn, "Work", "Client A")
        _shelf_tag(conn, "Home", "Chores")
        _tagged(conn, "t1", ["Client A", "Chores"])
        groups = _groups(conn)
        assert [g["name"] for g in groups] == ["Home", "Work"]

    def test_sections_and_subgroups_are_due_date_ascending(self, conn):
        _shelf_tag(conn, "Work", "Client A")
        _tagged(conn, "z", ["Client A"], due_at="2026-09-03")
        _tagged(conn, "a", ["Client A"], due_at="2026-09-01")
        _tagged(conn, "m", ["Client A"], due_at="2026-09-02")
        work = _group(_groups(conn), "label", "Work")
        assert [t["uid"] for t in work["tasks"]] == ["a", "m", "z"]
        assert [t["uid"] for t in work["subgroups"][0]["tasks"]] == ["a", "m", "z"]


class TestCompletedGroup:
    def test_completed_tasks_pulled_out_of_their_shelf_group(self, conn):
        _shelf_tag(conn, "Home", "Chores")
        _tagged(conn, "open", ["Chores"])
        _tagged(conn, "done", ["Chores"], status="done")
        _task(conn, "loose_done", tags=[], status="archived")
        groups = _groups(conn)
        assert {t["uid"] for t in _group(groups, "label", "Home")["tasks"]} == {"open"}
        assert {t["uid"] for t in _group(groups, "completed")["tasks"]} == {"done", "loose_done"}

    def test_completed_group_is_most_recent_first(self, conn):
        for uid, stamp in (("old", "2026-01-01T00:00:00+00:00"), ("new", "2026-06-01T00:00:00+00:00")):
            db.upsert_task(conn, {"uid": uid, "title": uid, "description": "", "status": "done",
                                  "tags": [], "created_at": _now(), "updated_at": stamp})
        assert [t["uid"] for t in _group(_groups(conn), "completed")["tasks"]] == ["new", "old"]


class TestDueSoon:
    def test_a_task_due_within_two_days_or_overdue_is_flagged_and_a_far_one_is_not(self, conn):
        from src import clock
        today = clock.today()
        for uid, days in (("late", -3), ("tomorrow", 1), ("far", 10)):
            _task(conn, uid, due_at=(today + timedelta(days=days)).isoformat())
        _task(conn, "done", due_at=today.isoformat(), status="done")
        html = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        flagged = lambda uid: re.search(rf'data-uid="{uid}".*?class="task-row-date([^"]*)"', html, re.S).group(1)
        assert "is-overdue" in flagged("late") and "is-soon" in flagged("tomorrow")
        assert "is-" not in flagged("far") and "is-" not in flagged("done")
