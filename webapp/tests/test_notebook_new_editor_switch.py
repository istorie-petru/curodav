"""The Tiptap editor is the default; ?editor=legacy loads the Editor.js scripts for notes it cannot hold yet."""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from src import db, main


def test_the_new_editor_is_the_default_and_legacy_stays_available(monkeypatch, tmp_path):
    path = tmp_path / "c.sqlite"
    monkeypatch.setenv("CC_DB_PATH", str(path))
    monkeypatch.setenv("CC_BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setenv("CC_SKIP_AUTH", "1")
    with TestClient(main.create_app()) as client:
        with db.connect(path) as conn:
            db.upsert_notebook_document(conn, {"uid": "d1", "title": "Note", "content_json": json.dumps({"blocks": []}), "document_type": "full", "note_type": ""})
        page = client.get("/notebook/d1").text
        assert "tiptap.bundle.js" in page and "editorjs.umd.js" not in page
        legacy = client.get("/notebook/d1?editor=legacy").text
        assert "editorjs.umd.js" in legacy and "tiptap.bundle.js" not in legacy


def test_every_link_to_a_note_opens_the_new_editor_and_a_note_it_cannot_hold_stays_there(monkeypatch, tmp_path):
    path = tmp_path / "c.sqlite"
    monkeypatch.setenv("CC_DB_PATH", str(path))
    monkeypatch.setenv("CC_BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setenv("CC_SKIP_AUTH", "1")
    odd = {"blocks": [{"type": "warning", "data": {"title": "x", "message": "y"}}]}
    with TestClient(main.create_app()) as client:
        with db.connect(path) as conn:
            db.upsert_notebook_document(conn, {"uid": "odd", "title": "Odd", "content_json": json.dumps(odd), "document_type": "full",
                                               "note_type": "", "tags": ["Uni"]})
            db.set_notebook_pinned(conn, "odd", True)
        for url in ("/notebook", "/notebook/folder?kind=label&name=Uni"):
            page = client.get(url).text
            assert "/notebook/odd" in page and "editor=legacy" not in page
        note = client.get("/notebook/odd").text
        assert "tiptap.bundle.js" in note and "editorjs.umd.js" not in note
