"""Recent API activity: each call in a few words with where it went, grouped into visits per token."""

from __future__ import annotations

import json

import pytest

from src import api_activity, db


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "c.sqlite") as c:
        db.upsert_notebook_document(c, {"uid": "n1", "title": "Kant lecture", "content_json": json.dumps({"blocks": []}),
                                        "document_type": "full", "note_type": "", "created_at": "x", "updated_at": "y"})
        yield c


def test_a_tool_call_says_what_and_where(conn):
    assert api_activity.describe_tool(conn, "get_note", {"uid": "n1"}) == ("Read note", "Kant lecture")
    assert api_activity.describe_tool(conn, "search", {"query": "duty"}) == ("Search", "“duty”")
    assert api_activity.describe_tool(conn, "university_set_course_sheet", {"discipline": "Biology"}) == ("Course sheet", "Biology")


def test_a_rest_call_says_what_and_where(conn):
    assert api_activity.describe_request(conn, "GET", "/api/v1/notes/n1") == ("Read notes", "Kant lecture")
    assert api_activity.describe_request(conn, "GET", "/api/v1/notes") == ("List notes", "")


def _row(at, who="t1", name="Claude", action="Read note"):
    return {"at": at, "token_uid": who, "token_name": name, "action": action, "target": "", "surface": "mcp"}


def test_calls_close_together_are_one_visit_and_a_pause_starts_another():
    rows = [_row("2026-11-02T13:00:00+00:00"), _row("2026-11-02T13:05:00+00:00"), _row("2026-11-02T13:30:00+00:00"),
            _row("2026-11-02T13:04:00+00:00", who="t2", name="Script")]
    visits = api_activity.visits(rows)
    assert [(v["who"], len(v["calls"])) for v in visits] == [("Claude", 1), ("Script", 1), ("Claude", 2)]


def test_older_rows_without_a_where_still_read_plainly(conn):
    from src import access_tokens

    access_tokens.log_activity(conn, "t1", "mcp", "tool get_note")
    access_tokens.log_activity(conn, "t1", "api", "GET /api/v1/notes/n1")
    calls = api_activity.recent_visits(conn)[0]["calls"]
    assert [(c["action"], c["target"]) for c in calls] == [("Read note", ""), ("Read notes", "Kant lecture")]
