"""The `@`, `$` and `:` pickers find contacts, tasks and events, and icons."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src import db, notebook_mentions
from src.routers import notebook as notebook_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now():
    return datetime.now(timezone.utc).isoformat()


def _seed(conn):
    db.upsert_contact(conn, {"uid": "c1", "full_name": "Ana Pop", "org": "Acme", "tags": [], "created_at": _now(), "updated_at": _now()})
    db.upsert_contact(conn, {"uid": "c2", "full_name": "Bob Ray", "tags": [], "created_at": _now(), "updated_at": _now()})
    db.upsert_task(conn, {"uid": "t1", "title": "Write essay", "description": "", "status": "active", "due_at": "2026-11-02", "created_at": _now()})
    db.upsert_task(conn, {"uid": "t2", "title": "Essay review", "description": "", "status": "done", "created_at": _now()})
    db.upsert_event(conn, {"uid": "e1", "title": "Essay seminar", "description": "", "start_at": "2026-10-20T10:00:00", "all_day": False,
                           "status": "active", "created_at": _now(), "updated_at": _now()})


def test_contacts_match_by_name(conn):
    _seed(conn)
    assert [r["title"] for r in notebook_mentions.contacts(conn, "ana")] == ["Ana Pop"]
    assert notebook_mentions.contacts(conn, "ana")[0]["subtitle"] == "Acme"
    assert len(notebook_mentions.contacts(conn, "")) == 2


def test_items_list_open_tasks_then_events_then_finished_tasks(conn):
    _seed(conn)
    rows = notebook_mentions.items(conn, "essay")
    assert [(r["kind"], r["uid"]) for r in rows] == [("task", "t1"), ("event", "e1"), ("task", "t2")]
    assert rows[0]["subtitle"] == "2026-11-02" and rows[1]["subtitle"] == "2026-10-20"


def test_icons_put_prefix_matches_first():
    names = ["calendar", "check", "book", "bookmark", "notebook"]
    assert [r["name"] for r in notebook_mentions.icons(names, "book")] == ["book", "bookmark", "notebook"]


def test_the_route_answers_each_kind_and_refuses_others(conn):
    _seed(conn)
    assert len(json.loads(notebook_router.mention_candidates(kind="contact", q="", conn=conn).body)) == 2
    assert json.loads(notebook_router.mention_candidates(kind="icon", q="calendar", conn=conn).body)[0]["name"] == "calendar"
    assert notebook_router.mention_candidates(kind="nope", q="", conn=conn).status_code == 400
