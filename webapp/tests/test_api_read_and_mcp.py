"""The read side shared by /api/v1 and the MCP server: search, notes, citations, entries, tasks, events, and the MCP messages."""

from __future__ import annotations

import json

import pytest

from src import api_service, db, mcp_server, search_index

CUSTOM_BLOCKS = [
    {"id": "b1", "type": "header", "data": {"text": "Duty", "level": 2}},
    {"id": "b2", "type": "paragraph", "data": {"text": "The <b>categorical</b> imperative &amp; its maxims"}},
    {"id": "b3", "type": "callout", "data": {"kind": "warning", "text": "Read the Groundwork first"}},
    {"id": "b4", "type": "timeline", "data": {"items": [{"date": "1785", "text": "Groundwork published"}]}},
]


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _note(conn, uid, title, blocks, updated="2026-10-01T10:00:00+00:00", **extra):
    db.upsert_notebook_document(conn, {"uid": uid, "title": title, "content_json": json.dumps({"blocks": blocks}),
                                       "document_type": "full", "note_type": extra.pop("note_type", ""),
                                       "created_at": updated, "updated_at": updated, **extra})


def test_note_search_finds_words_inside_formatted_text_by_prefix(conn):
    _note(conn, "n1", "Kant lecture", CUSTOM_BLOCKS)
    hits = api_service.search(conn, "categor", ["note"])
    assert [h["uid"] for h in hits] == ["n1"]
    assert "[categorical]" in hits[0]["snippet"]


def test_note_search_follows_edits_and_deletes(conn):
    _note(conn, "n1", "Kant lecture", CUSTOM_BLOCKS)
    api_service.search(conn, "kant", ["note"])
    db.set_notebook_document_content(conn, "n1", {"blocks": [{"type": "paragraph", "data": {"text": "Hegel instead"}}]})
    assert api_service.search(conn, "categorical", ["note"]) == []
    assert [h["uid"] for h in api_service.search(conn, "hegel", ["note"])] == ["n1"]
    db.delete_notebook_document(conn, "n1")
    assert api_service.search(conn, "hegel", ["note"]) == []


def test_templates_never_show_up_in_search_or_lists(conn):
    _note(conn, "t1", "Kant template", CUSTOM_BLOCKS, is_template=True)
    assert api_service.search(conn, "kant", ["note"]) == []
    assert api_service.list_notes(conn)["items"] == []


def test_search_spans_tasks_entries_and_citations(conn):
    conn.execute("INSERT INTO tasks (uid, title, description) VALUES ('t1', 'Read Kant', 'chapter two')")
    conn.commit()
    db.upsert_glossary_term(conn, {"uid": "e1", "term": "Imperative", "definition": "A command of reason, as in Kant"})
    db.upsert_citation(conn, {"uid": "c1", "title": "Groundwork of the Metaphysics of Morals", "authors": [{"family": "Kant", "given": "Immanuel"}]})
    kinds = {h["kind"] for h in api_service.search(conn, "kant")}
    assert kinds == {"task", "entry", "citation"}


def test_search_index_install_can_run_twice_without_duplicates(conn):
    conn.execute("INSERT INTO tasks (uid, title) VALUES ('t1', 'Read Kant')")
    search_index.install(conn)
    search_index.install(conn)
    assert len(api_service.search(conn, "kant", ["task"])) == 1


def test_list_notes_pages_newest_edit_first_with_a_cursor(conn):
    for i in range(5):
        _note(conn, f"n{i}", f"Note {i}", [], updated=f"2026-10-0{i + 1}T10:00:00+00:00")
    first = api_service.list_notes(conn, limit=2)
    assert [n["uid"] for n in first["items"]] == ["n4", "n3"]
    second = api_service.list_notes(conn, limit=2, cursor=first["next"])
    assert [n["uid"] for n in second["items"]] == ["n2", "n1"]
    last = api_service.list_notes(conn, limit=2, cursor=second["next"])
    assert [n["uid"] for n in last["items"]] == ["n0"] and last["next"] == ""


def test_get_note_gives_markdown_and_keeps_every_custom_block_when_asked(conn):
    _note(conn, "n1", "Kant lecture", CUSTOM_BLOCKS)
    note = api_service.get_note(conn, "n1", include_blocks=True)
    assert "## Duty" in note["markdown"]
    assert note["blocks"] == CUSTOM_BLOCKS
    assert note["revision"] == "2026-10-01T10:00:00+00:00"


def test_get_note_lists_links_both_ways(conn):
    _note(conn, "n2", "Target", [])
    link = '<a class="wikilink" data-uid="n2">Target</a>'
    _note(conn, "n1", "Source", [{"type": "paragraph", "data": {"text": link}}])
    db.set_notebook_links(conn, "n1", ["n2"])
    assert api_service.get_note(conn, "n1")["links_to"] == [{"uid": "n2", "title": "Target"}]
    assert api_service.get_note(conn, "n2")["linked_from"] == [{"uid": "n1", "title": "Source"}]


def test_missing_objects_raise_not_found(conn):
    for read in (api_service.get_note, api_service.get_citation, api_service.get_entry, api_service.get_task, api_service.get_event):
        with pytest.raises(api_service.NotFound):
            read(conn, "nope")


def test_list_tasks_orders_by_due_date_and_pages(conn):
    for uid, due in (("a", "2026-11-03"), ("b", None), ("c", "2026-11-01")):
        conn.execute("INSERT INTO tasks (uid, title, due_at) VALUES (?, ?, ?)", (uid, uid, due))
    conn.commit()
    first = api_service.list_tasks(conn, limit=2)
    assert [t["uid"] for t in first["items"]] == ["c", "a"]
    assert [t["uid"] for t in api_service.list_tasks(conn, limit=2, cursor=first["next"])["items"]] == ["b"]


def _rpc(conn, method, params=None, msg_id=1):
    return mcp_server.handle(conn, {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})


def test_mcp_initialize_agrees_on_a_protocol_version(conn):
    known = _rpc(conn, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}})
    assert known["result"]["protocolVersion"] == "2025-06-18"
    unknown = _rpc(conn, "initialize", {"protocolVersion": "1999-01-01"})
    assert unknown["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSIONS[0]


def test_mcp_notifications_get_no_answer(conn):
    assert mcp_server.handle(conn, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_mcp_lists_only_read_only_tools(conn):
    tools = _rpc(conn, "tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} >= {"search", "get_note", "list_citations"}
    assert all(t["annotations"]["readOnlyHint"] for t in tools)


def test_mcp_get_note_returns_the_note_as_data(conn):
    _note(conn, "n1", "Kant lecture", CUSTOM_BLOCKS)
    result = _rpc(conn, "tools/call", {"name": "get_note", "arguments": {"uid": "n1"}})["result"]
    assert result["structuredContent"]["title"] == "Kant lecture"
    assert json.loads(result["content"][0]["text"])["uid"] == "n1"


def test_mcp_bad_arguments_and_missing_notes_are_tool_errors(conn):
    missing = _rpc(conn, "tools/call", {"name": "get_note", "arguments": {}})["result"]
    unknown_arg = _rpc(conn, "tools/call", {"name": "get_note", "arguments": {"uid": "x", "drop": True}})["result"]
    not_found = _rpc(conn, "tools/call", {"name": "get_note", "arguments": {"uid": "x"}})["result"]
    assert missing["isError"] and unknown_arg["isError"] and not_found["isError"]


def test_mcp_unknown_method_and_tool_are_protocol_errors(conn):
    assert _rpc(conn, "resources/list")["error"]["code"] == mcp_server.METHOD_NOT_FOUND
    assert _rpc(conn, "tools/call", {"name": "delete_everything"})["error"]["code"] == mcp_server.INVALID_PARAMS


def test_university_overview_and_exams_follow_the_current_semester(conn, monkeypatch, frozen_today):
    from datetime import date

    from src import university, university_plan as up
    from src.routers.labels import COLORS
    from university_helpers import add_exam

    assert university
    monkeypatch.setenv("CC_MODULES", "university")
    frozen_today(date(2026, 11, 1))
    sid = up.save_semester(conn, uid=None, name="Autumn 2026", shelf_name="University", start_date="2026-10-05",
                           end_date="2027-02-14", class_end_date="2026-12-18")
    sem = up.get_semester(conn, sid)
    up.save_discipline(conn, sem, old="", name="Biology", color="green", icon="leaf", teacher_names="Dr Ionescu", colors=COLORS)
    add_exam(conn, sem, title="Final", day="2027-01-20", weight="100")
    overview = api_service.university_overview(conn)
    assert overview["semester"]["name"] == "Autumn 2026"
    assert [d["name"] for d in overview["disciplines"]] == ["Biology"]
    exams = api_service.list_exams(conn, upcoming=True)["items"]
    assert [e["title"] for e in exams] and exams[0]["date"] == "2027-01-20"
    biology = api_service.get_discipline(conn, "biology")
    assert biology["exams"][0]["days_left"] == 80
    with pytest.raises(api_service.NotFound):
        api_service.get_discipline(conn, "Chemistry")


def test_university_reads_are_empty_without_a_semester(conn):
    assert api_service.university_overview(conn)["semester"] is None
    assert api_service.list_exams(conn) == {"items": []}
