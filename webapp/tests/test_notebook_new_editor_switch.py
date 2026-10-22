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
