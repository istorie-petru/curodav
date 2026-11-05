"""Block-level note edits for the API and MCP: revision check, protected custom blocks, versions and restore."""

from __future__ import annotations

import json

import pytest

from src import api_write, db, log, note_versions

BLOCKS = [
    {"id": "h1", "type": "header", "data": {"text": "Duty", "level": 2}},
    {"id": "p1", "type": "paragraph", "data": {"text": "First paragraph"}},
    {"id": "c1", "type": "callout", "data": {"kind": "warning", "text": "Read the Groundwork first"}},
    {"id": "f1", "type": "image", "data": {"file": {"url": "/notebook/images/" + "a" * 64}, "caption": "Kant"}},
    {"id": "p2", "type": "paragraph", "data": {"text": "Last paragraph"}},
]


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        db.upsert_notebook_document(c, {"uid": "n1", "title": "Kant", "content_json": json.dumps({"blocks": BLOCKS}),
                                        "document_type": "full", "note_type": "", "created_at": "2026-10-01T10:00:00+00:00",
                                        "updated_at": "2026-10-01T10:00:00+00:00"})
        yield c


REV = "2026-10-01T10:00:00+00:00"


def _blocks(conn):
    return db.get_notebook_document_content(conn, "n1")["blocks"]


def test_insert_after_adds_blocks_from_markdown_with_fresh_ids(conn):
    api_write.edit_note(conn, "n1", REV, [{"op": "insert_after", "block_id": "p1", "markdown": "New **idea**\n\n- one\n- two"}],
                        source="mcp")
    blocks = _blocks(conn)
    assert [b["type"] for b in blocks[2:4]] == ["paragraph", "list"]
    assert blocks[2]["data"]["text"] == "New <b>idea</b>"
    assert len({b["id"] for b in blocks}) == len(blocks)


def test_every_custom_block_survives_an_edit(conn):
    api_write.edit_note(conn, "n1", REV, [{"op": "replace", "block_id": "p1", "markdown": "Changed"},
                                          {"op": "append", "markdown": "The end"}], source="api")
    blocks = _blocks(conn)
    assert [b for b in blocks if b["id"] in ("c1", "f1")] == BLOCKS[2:4]


def test_custom_blocks_cannot_be_replaced_or_deleted(conn):
    for op in ({"op": "delete", "block_id": "c1"}, {"op": "replace", "block_id": "f1", "markdown": "x"}):
        with pytest.raises(api_write.EditError) as err:
            api_write.edit_note(conn, "n1", REV, [op], source="mcp")
        assert err.value.code == "invalid"
    assert _blocks(conn) == BLOCKS


def test_a_stale_revision_is_refused(conn):
    first = api_write.edit_note(conn, "n1", REV, [{"op": "append", "markdown": "One"}], source="mcp")
    with pytest.raises(api_write.EditError) as err:
        api_write.edit_note(conn, "n1", REV, [{"op": "append", "markdown": "Two"}], source="mcp")
    assert err.value.code == "conflict"
    api_write.edit_note(conn, "n1", first["revision"], [{"op": "append", "markdown": "Two"}], source="mcp")


def test_a_bad_operation_changes_nothing(conn):
    with pytest.raises(api_write.EditError):
        api_write.edit_note(conn, "n1", REV, [{"op": "append", "markdown": "Kept?"}, {"op": "delete", "block_id": "missing"}],
                            source="mcp")
    assert _blocks(conn) == BLOCKS
    assert note_versions.list_versions(conn, "n1") == []


def test_html_in_markdown_is_escaped(conn):
    api_write.edit_note(conn, "n1", REV, [{"op": "append", "markdown": "<img src=x onerror=alert(1)>"}], source="mcp")
    assert "<img" not in json.dumps(_blocks(conn)[-1])


def test_footnotes_from_two_edits_do_not_share_ids(conn):
    rev = api_write.edit_note(conn, "n1", REV, [{"op": "append", "markdown": "A[^1]\n\n[^1]: first"}], source="mcp")["revision"]
    api_write.edit_note(conn, "n1", rev, [{"op": "append", "markdown": "B[^1]\n\n[^1]: second"}], source="mcp")
    texts = [b["data"]["text"] for b in _blocks(conn)[-2:]]
    ids = [t.split('data-note-id="', 1)[1].split('"', 1)[0] for t in texts]
    assert ids[0] != ids[1]


def test_an_edit_keeps_a_version_that_restores_the_note(conn):
    result = api_write.edit_note(conn, "n1", REV, [{"op": "delete", "block_id": "p2"}], source="mcp", summary="Drop the end")
    versions = note_versions.list_versions(conn, "n1")
    assert versions[0]["source"] == "mcp" and versions[0]["summary"] == "Drop the end"
    api_write.restore_version(conn, result["version"], source="web")
    assert _blocks(conn) == BLOCKS
    assert len(note_versions.list_versions(conn, "n1")) == 2


def test_only_the_last_versions_are_kept(conn, monkeypatch):
    monkeypatch.setattr(note_versions, "KEEP", 3)
    rev = REV
    for i in range(5):
        rev = api_write.edit_note(conn, "n1", rev, [{"op": "append", "markdown": f"Line {i}"}], source="mcp")["revision"]
    assert len(note_versions.list_versions(conn, "n1")) == 3


def _web_client(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from src import main

    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "web.sqlite"))
    monkeypatch.delenv("CC_AUTH_USERNAME", raising=False)
    monkeypatch.delenv("CC_AUTH_PASSWORD", raising=False)
    client = TestClient(main.create_app(), base_url="http://testserver")
    client.__enter__()
    with db.connect(client.app.state.settings.db_path, reuse_schema=True) as c:
        db.upsert_notebook_document(c, {"uid": "n1", "title": "Kant", "content_json": json.dumps({"blocks": BLOCKS}),
                                        "document_type": "full", "note_type": "", "created_at": REV, "updated_at": REV})
    return client


def test_the_editor_save_always_goes_through_and_keeps_what_it_replaces(tmp_path, monkeypatch):
    client = _web_client(tmp_path, monkeypatch)
    saved = client.put("/notebook/n1/content", json={"blocks": BLOCKS[:2]})
    assert saved.status_code == 200
    with db.connect(client.app.state.settings.db_path, reuse_schema=True) as c:
        api_write.edit_note(c, "n1", saved.json()["revision"], [{"op": "append", "markdown": "From Claude"}], source="mcp")
    later = client.put("/notebook/n1/content", headers={"If-Match": '"stale"'}, json={"blocks": BLOCKS[:1]})
    assert later.status_code == 200
    with db.connect(client.app.state.settings.db_path, reuse_schema=True) as c:
        assert len(db.get_notebook_document_content(c, "n1")["blocks"]) == 1
        kept = [note_versions.get_version(c, v["uid"]) for v in note_versions.list_versions(c, "n1")]
        assert any("From Claude" in (v["content_json"] or "") for v in kept)
    client.__exit__(None, None, None)


def test_the_editor_save_leaves_a_log_line_and_so_does_a_refused_one(tmp_path, monkeypatch):
    client = _web_client(tmp_path, monkeypatch)
    before = log.entries("all")[-1]["id"] if log.entries("all") else 0
    client.put("/notebook/n1/content", json={"blocks": BLOCKS[:2]})
    assert client.put("/notebook/missing/content", json={"blocks": []}).status_code == 404
    client.post("/notebook/n1/content/report", json={"what": "save failed: network"})
    lines = [(e["level"], e["message"]) for e in log.entries("all", after=before)]
    assert any(level == "info" and "n1 saved (2 blocks)" in m for level, m in lines)
    assert any(level == "warning" and "not found" in m for level, m in lines)
    assert any(level == "warning" and "save failed: network" in m for level, m in lines)
    client.__exit__(None, None, None)


def test_editor_saves_keep_a_version_now_and_then_and_after_an_ai_edit(tmp_path, monkeypatch):
    client = _web_client(tmp_path, monkeypatch)
    for blocks in (BLOCKS[:4], BLOCKS[:3]):
        client.put("/notebook/n1/content", json={"blocks": blocks})
    with db.connect(client.app.state.settings.db_path, reuse_schema=True) as c:
        assert [v["source"] for v in note_versions.list_versions(c, "n1")] == ["web"]
        rev = db.get_notebook_document(c, "n1")["updated_at"]
        api_write.edit_note(c, "n1", rev, [{"op": "append", "markdown": "From Claude"}], source="mcp")
    client.put("/notebook/n1/content", json={"blocks": BLOCKS[:2]})
    with db.connect(client.app.state.settings.db_path, reuse_schema=True) as c:
        versions = note_versions.list_versions(c, "n1")
        assert [v["source"] for v in versions] == ["web", "mcp", "web"]
        assert "From Claude" in note_versions.get_version(c, versions[0]["uid"])["content_json"]
    client.__exit__(None, None, None)
