"""MCP edits to the library and to one note's title, tag and properties, and what the server leaves out."""

from __future__ import annotations

import json

import pytest

from src import api_service, db, mcp_server, note_versions, tags

WRITER = {"uid": "t1", "scopes": "read:notes write:notes write:library"}


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "c.sqlite") as c:
        yield c


def _call(conn, tool, token=WRITER, **arguments):
    reply = mcp_server.handle(conn, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}, token)
    return reply.get("error") or reply["result"]


def test_a_book_is_added_with_authors_and_found_again(conn):
    result = _call(conn, "library_save_entry", entry={"type": "book", "title": "Groundwork", "authors": ["Immanuel Kant"], "year": "1785"})
    uid = result["structuredContent"]["uid"]
    entry = api_service.get_citation(conn, uid)
    assert entry["authors"] == [{"family": "Kant", "given": "Immanuel"}] and entry["year"] == "1785"
    assert [h["uid"] for h in api_service.search(conn, "groundwork", ["citation"])] == [uid]


def test_a_likely_duplicate_is_refused_unless_allowed(conn):
    _call(conn, "library_save_entry", entry={"type": "book", "title": "Groundwork", "authors": ["Kant, Immanuel"], "year": "1785"})
    again = _call(conn, "library_save_entry", entry={"type": "book", "title": "Groundwork", "authors": ["Kant, Immanuel"], "year": "1785"})
    assert again["isError"] and "already in the library" in again["content"][0]["text"]
    kept = _call(conn, "library_save_entry", allow_duplicate=True,
                 entry={"type": "book", "title": "Groundwork", "authors": ["Kant, Immanuel"], "year": "1785"})
    assert not kept.get("isError")


def test_changing_an_entry_keeps_the_fields_left_out(conn):
    uid = _call(conn, "library_save_entry", entry={"type": "film", "title": "Stalker", "year": "1979", "note": "Tarkovsky"})["structuredContent"]["uid"]
    _call(conn, "library_save_entry", uid=uid, entry={"title": "Stalker (1979)"})
    entry = api_service.get_citation(conn, uid)
    assert entry["title"] == "Stalker (1979)" and entry["year"] == "1979" and entry["note"] == "Tarkovsky" and entry["type"] == "film"


def test_unknown_types_are_refused(conn):
    assert _call(conn, "library_save_entry", entry={"type": "podcast", "title": "x"})["isError"]


def test_tracking_follows_the_window_rules(conn, frozen_today):
    from datetime import date

    frozen_today(date(2026, 11, 2))
    uid = _call(conn, "library_save_entry", entry={"type": "anime", "title": "Frieren"})["structuredContent"]["uid"]
    _call(conn, "library_set_tracking", uid=uid, status="current", progress=3, progress_total=28, rating=4)
    media = api_service.get_citation(conn, uid)["media"]
    assert media["status"] == "current" and media["started_on"] == "2026-11-02" and media["progress"] == 3 and media["rating"] == 4.0
    _call(conn, "library_set_tracking", uid=uid, status="finished")
    media = api_service.get_citation(conn, uid)["media"]
    assert media["finished_on"] == "2026-11-02" and media["progress"] == 28
    assert _call(conn, "library_set_tracking", uid=uid, status="watching")["isError"]
    assert _call(conn, "library_set_tracking", uid=uid, criteria={"Story": 5})["isError"]


def test_library_edits_need_their_own_permission(conn):
    names = {t.name for t in mcp_server.visible_tools({"uid": "t", "scopes": "read:notes write:notes"})}
    assert "library_entry_types" in names and "library_save_entry" not in names


def _note(conn, uid="n1"):
    db.upsert_notebook_document(conn, {"uid": uid, "title": "Kant", "content_json": json.dumps({"blocks": []}), "document_type": "full",
                                       "note_type": "", "created_at": "2026-10-01T10:00:00+00:00", "updated_at": "2026-10-01T10:00:00+00:00"})
    return "2026-10-01T10:00:00+00:00"


def test_a_note_is_created_from_markdown_with_a_tag(conn):
    conn.execute("INSERT INTO label_config (name) VALUES ('Philosophy')")
    tags.add_default_tag(conn, "Philosophy")
    result = _call(conn, "create_note", title="Duty", tag="Philosophy", markdown="# Duty\n\nActs from duty.")["structuredContent"]
    note = api_service.get_note(conn, result["uid"])
    assert note["title"] == "Duty" and note["tags"] == ["Philosophy"] and "Acts from duty." in note["markdown"]
    assert _call(conn, "create_note", title="X", tag="No such tag")["isError"]


def test_rename_tag_and_properties_need_the_current_revision_and_keep_a_version(conn):
    rev = _note(conn)
    renamed = _call(conn, "rename_note", uid="n1", revision=rev, title="Kant on duty")["structuredContent"]
    assert _call(conn, "rename_note", uid="n1", revision=rev, title="Stale")["isError"]
    props = _call(conn, "set_note_properties", uid="n1", revision=renamed["revision"], properties={"Course": "Ethics"})["structuredContent"]
    note = api_service.get_note(conn, "n1")
    assert note["title"] == "Kant on duty" and note["properties"] == {"Course": "Ethics"}
    _call(conn, "set_note_properties", uid="n1", revision=props["revision"], properties={"Course": ""})
    assert api_service.get_note(conn, "n1")["properties"] == {}
    assert [v["summary"] for v in note_versions.list_versions(conn, "n1")][-1] == "Renamed from Kant"


def test_contacts_are_not_searchable_through_the_api(conn):
    db.upsert_contact(conn, {"uid": "c1", "full_name": "Kant Immanuel"})
    assert all(h["kind"] != "contact" for h in api_service.search(conn, "kant"))
    assert "contact" not in api_service.SEARCH_KINDS


def test_there_is_no_tool_for_finance_habits_contacts_or_task_and_event_changes(conn):
    everything = {"uid": "t", "scopes": "read write:notes write:library write:university"}
    names = " ".join(t.name for t in mcp_server.visible_tools(everything))
    for word in ("finance", "habit", "contact", "save_task", "save_event", "delete"):
        assert word not in names
