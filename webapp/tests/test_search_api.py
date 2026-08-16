"""Tests for the 1.2 side-work Universal command surface's HTTP layer
(routers/search.py) -- `GET /api/search` and `GET /search`. The query layer
itself (`db.search_entities`) is covered by test_search_entities.py; this
file covers routers/search.py's own responsibilities:

  - Global mode (`q`/`types`/`labels`) returns the compact picker surface
    (type/uid/title/subtitle/tags), never the full `entity` row.
  - Relation-picker mode (`for_task`/`for_event`) applies the app's one
    relation rule -- share >= 1 label with the source object, not already
    linked -- the same rule the old `<select>`-based `linkable_events`/
    `linkable_tasks` context pools (routers/tasks.py/calendar.py, removed
    1.2 side work step 3) used to apply, now server-side per request
    instead of precomputed on every page render.
  - `for_task` and `for_event` are mutually exclusive.
  - `/search` renders the picker button-free result list for a bookmarked
    query, and an empty prompt with no query at all."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import search as search_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/", query_string=b""):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": query_string,
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


def _seed_contact(conn, uid, tags=None, **overrides):
    row = {
        "uid": uid,
        "full_name": uid,
        "tags": tags or [],
        "created_at": _now(),
    }
    row.update(overrides)
    db.upsert_contact(conn, row)
    return db.get_contact(conn, uid)


class TestGlobalMode:
    def test_returns_compact_surface_only(self, conn):
        _seed_task(conn, "t1", tags=["Work"], due_at="2026-09-01")
        resp = search_router.api_search(q="t1", conn=conn)
        body = resp.body.decode()
        import json

        data = json.loads(body)
        assert len(data["results"]) == 1
        row = data["results"][0]
        # "status" (2026-08-15, Command palette actions) rides along too --
        # the palette's own action buttons need it to hide "Mark done" on
        # an already-done task; every other consumer of this shape ignores it.
        assert set(row.keys()) == {"type", "uid", "title", "subtitle", "tags", "status"}
        assert row["type"] == "task"
        assert row["uid"] == "t1"
        assert row["status"] == "active"

    def test_searches_across_all_three_types(self, conn):
        _seed_task(conn, "t1", title="Shared name")
        _seed_event(conn, "e1", title="Shared name")
        _seed_contact(conn, "c1", full_name="Shared name")
        import json

        data = json.loads(search_router.api_search(q="Shared", conn=conn).body.decode())
        assert {r["type"] for r in data["results"]} == {"task", "event", "contact"}

    def test_type_filter_narrows_to_one_type(self, conn):
        _seed_task(conn, "t1", title="Match")
        _seed_event(conn, "e1", title="Match")
        import json

        data = json.loads(search_router.api_search(q="Match", types=["task"], conn=conn).body.decode())
        assert [r["type"] for r in data["results"]] == ["task"]

    def test_no_query_returns_everything_up_to_limit(self, conn):
        _seed_task(conn, "t1")
        _seed_task(conn, "t2")
        import json

        data = json.loads(search_router.api_search(limit=1, types=["task"], conn=conn).body.decode())
        assert len(data["results"]) == 1


class TestForTaskFilter:
    def test_offers_only_shared_label_not_already_linked_events(self, conn):
        task = _seed_task(conn, "t1", tags=["Work"])
        _seed_event(conn, "e1", tags=["Work"])  # shared label -> offered
        _seed_event(conn, "e2", tags=["Home"])  # no shared label -> excluded
        e3 = _seed_event(conn, "e3", tags=["Work"])  # already linked -> excluded
        db.add_event_task_relation(conn, "e3", "t1")
        import json

        data = json.loads(search_router.api_search(for_task="t1", conn=conn).body.decode())
        uids = {r["uid"] for r in data["results"]}
        assert uids == {"e1"}
        assert data["context"] == task["title"]

    def test_no_labels_short_circuits_with_a_flag(self, conn):
        _seed_task(conn, "t1", tags=[])
        _seed_event(conn, "e1", tags=["Work"])
        import json

        data = json.loads(search_router.api_search(for_task="t1", conn=conn).body.decode())
        assert data["results"] == []
        assert data["no_labels"] is True

    def test_unknown_task_returns_empty(self, conn):
        import json

        data = json.loads(search_router.api_search(for_task="nope", conn=conn).body.decode())
        assert data == {"results": [], "context": None}

    def test_q_further_narrows_within_the_implicit_filter(self, conn):
        _seed_task(conn, "t1", tags=["Work"])
        _seed_event(conn, "e1", tags=["Work"], title="Alpha")
        _seed_event(conn, "e2", tags=["Work"], title="Beta")
        import json

        data = json.loads(search_router.api_search(for_task="t1", q="Alpha", conn=conn).body.decode())
        assert [r["uid"] for r in data["results"]] == ["e1"]


class TestForEventFilter:
    def test_offers_only_shared_label_not_already_linked_tasks(self, conn):
        event = _seed_event(conn, "e1", tags=["Work"])
        _seed_task(conn, "t1", tags=["Work"])
        _seed_task(conn, "t2", tags=["Home"])
        db.add_event_task_relation(conn, "e1", "t1")
        _seed_task(conn, "t3", tags=["Work"])
        import json

        data = json.loads(search_router.api_search(for_event="e1", conn=conn).body.decode())
        uids = {r["uid"] for r in data["results"]}
        assert uids == {"t3"}
        assert data["context"] == event["title"]

    def test_no_labels_short_circuits_with_a_flag(self, conn):
        _seed_event(conn, "e1", tags=[])
        import json

        data = json.loads(search_router.api_search(for_event="e1", conn=conn).body.decode())
        assert data["results"] == []
        assert data["no_labels"] is True


class TestMutualExclusivity:
    def test_for_task_and_for_event_together_is_rejected(self, conn):
        _seed_task(conn, "t1", tags=["Work"])
        _seed_event(conn, "e1", tags=["Work"])
        resp = search_router.api_search(for_task="t1", for_event="e1", conn=conn)
        assert resp.status_code == 400


class TestPageNavigation:
    """Direct feedback (2026-08-15): "I would like it to also allow to
    navigate to pages" -- global mode's results now include the app's own
    pages alongside entities (routers/search.py's _matching_pages)."""

    def test_matching_page_appears_in_global_results(self, conn):
        import json

        data = json.loads(search_router.api_search(q="Tasks", conn=conn).body.decode())
        pages = [r for r in data["results"] if r["type"] == "page"]
        assert pages == [{"type": "page", "uid": "/tasks", "url": "/tasks", "title": "Tasks", "subtitle": "", "tags": [], "status": None}]

    def test_no_query_still_lists_pages(self, conn):
        import json

        data = json.loads(search_router.api_search(conn=conn).body.decode())
        titles = {r["title"] for r in data["results"] if r["type"] == "page"}
        assert "Dashboard" in titles

    def test_a_space_label_is_a_navigable_page(self, conn):
        import json

        db.upsert_label_config(
            conn,
            {"name": "University", "generate_space": 1, "created_at": _now()},
        )
        data = json.loads(search_router.api_search(q="Univers", conn=conn).body.decode())
        pages = [r for r in data["results"] if r["type"] == "page"]
        assert pages == [
            {"type": "page", "uid": "/labels/University", "url": "/labels/University", "title": "University", "subtitle": "Space", "tags": [], "status": None}
        ]

    def test_type_filtered_search_excludes_pages(self, conn):
        import json

        _seed_task(conn, "t1", title="Tasks about things")
        data = json.loads(search_router.api_search(q="Tasks", types=["task"], conn=conn).body.decode())
        assert all(r["type"] != "page" for r in data["results"])

    def test_relation_mode_excludes_pages(self, conn):
        import json

        task = _seed_task(conn, "t1", tags=["Work"])
        data = json.loads(search_router.api_search(for_task="t1", q="Tasks", conn=conn).body.decode())
        assert all(r["type"] != "page" for r in data["results"])

    def test_no_match_returns_no_pages(self, conn):
        import json

        data = json.loads(search_router.api_search(q="zzzznomatch", conn=conn).body.decode())
        assert [r for r in data["results"] if r["type"] == "page"] == []


class TestSearchPage:
    def test_no_query_shows_prompt_not_results(self, conn):
        body = search_router.search_page(_request("/search"), q="", conn=conn).body.decode()
        assert "Type to search" in body

    def test_query_renders_matching_results(self, conn):
        _seed_task(conn, "t1", title="Findable")
        body = search_router.search_page(_request("/search"), q="Findable", conn=conn).body.decode()
        assert "Findable" in body
        assert "/tasks/t1" in body

    def test_query_with_no_matches_shows_empty_state(self, conn):
        body = search_router.search_page(_request("/search"), q="nothingmatchesthis", conn=conn).body.decode()
        assert "No results" in body
