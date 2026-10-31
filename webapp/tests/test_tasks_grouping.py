"""The Tasks list's grouping: by default sections by due date (Overdue, Today, This week, Later, No date) with a task
appearing once; `shelf` gives one section per shelf, `none` one plain list. Completed is always last."""

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


def _groups(conn, group=""):
    return tasks_router.list_tasks(_request(), group=group, conn=conn).context["groups"]


def _day(offset):
    from src import clock
    return (clock.today() + timedelta(days=offset)).isoformat()


class TestDateSections:
    def test_tasks_fall_into_their_section_in_fixed_order(self, conn):
        for uid, off in (("late", -2), ("now", 0), ("soon", 3), ("far", 30)):
            _task(conn, uid, due_at=_day(off))
        _task(conn, "undated")
        _task(conn, "fin", status="done")
        groups = _groups(conn)
        assert [g["name"] for g in groups] == ["Overdue", "Today", "This week", "Later", "No date", "Completed"]
        assert [[t["uid"] for t in g["tasks"]] for g in groups] == [["late"], ["now"], ["soon"], ["far"], ["undated"], ["fin"]]

    def test_a_task_with_tags_on_two_shelves_appears_once(self, conn):
        _shelf_tag(conn, "Work", "Client A")
        _shelf_tag(conn, "Home", "Chores")
        _tagged(conn, "t1", ["Client A", "Chores"], due_at=_day(0))
        assert [t["uid"] for g in _groups(conn) for t in g["tasks"]] == ["t1"]

    def test_empty_sections_are_left_out(self, conn):
        _task(conn, "a", due_at=_day(0))
        assert [g["name"] for g in _groups(conn)] == ["Today"]

    def test_a_section_is_due_date_ascending(self, conn):
        for uid, off in (("z", 3), ("a", 1), ("m", 2)):
            _task(conn, uid, due_at=_day(off))
        assert [t["uid"] for t in _groups(conn)[0]["tasks"]] == ["a", "m", "z"]


class TestShelfSections:
    def test_shelves_then_untagged_then_completed(self, conn):
        _shelf_tag(conn, "Home", "Chores")
        _tagged(conn, "a1", ["Chores"])
        _task(conn, "loose1", tags=[])
        _tagged(conn, "done1", ["Chores"], status="done")
        assert [g["kind"] for g in _groups(conn, "shelf")] == ["label", "unassigned", "completed"]

    def test_shelves_are_alphabetical_case_insensitive(self, conn):
        for shelf in ("banana", "Apple", "cherry"):
            _shelf_tag(conn, shelf, shelf)
            _tagged(conn, shelf, [shelf])
        assert [g["name"] for g in _groups(conn, "shelf")] == ["Apple", "banana", "cherry"]

    def test_two_tags_on_one_shelf_list_the_task_once(self, conn):
        _shelf_tag(conn, "Work", "Client A")
        _shelf_tag(conn, "Work", "Client B")
        _tagged(conn, "t1", ["Client A", "Client B"])
        work = _group(_groups(conn, "shelf"), "label", "Work")
        assert [t["uid"] for t in work["tasks"]] == ["t1"]

    def test_a_task_with_tags_on_two_shelves_appears_in_both_sections(self, conn):
        _shelf_tag(conn, "Work", "Client A")
        _shelf_tag(conn, "Home", "Chores")
        _tagged(conn, "t1", ["Client A", "Chores"])
        assert [g["name"] for g in _groups(conn, "shelf")] == ["Home", "Work"]


class TestPlainList:
    def test_none_gives_one_list_without_headings(self, conn):
        _task(conn, "a", due_at=_day(0))
        _task(conn, "b")
        groups = _groups(conn, "none")
        assert [g["kind"] for g in groups] == ["plain"]
        assert [t["uid"] for t in groups[0]["tasks"]] == ["a", "b"]
        body = tasks_router.list_tasks(_request(), group="none", conn=conn).body.decode()
        assert 'class="section-row' not in body


class TestCompletedGroup:
    def test_completed_tasks_pulled_out_of_their_section(self, conn):
        _task(conn, "open", due_at=_day(0))
        _task(conn, "done", status="done")
        _task(conn, "loose_done", status="archived")
        groups = _groups(conn)
        assert {t["uid"] for t in _group(groups, "date", "Today")["tasks"]} == {"open"}
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
