"""Wikilinks & relationships (roadmap-mvp-to-full-product-checklist's
"Wikilinks & relationships" section, 2026-10-03) -- db.py's notebook_links
derived cache + search, routers/notebook.py's GET /notebook/search and the
document_page backlinks wiring. The outbound ("Links to") half is a pure
client-side DOM walk (static/notebook/notebook_wikilinks.js) and has no
backend surface of its own to test here."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from starlette.requests import Request

from src import db
from src.routers import export as export_router
from src.routers import notebook as notebook_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _bare_request(path="/notebook/search", query_string: bytes = b""):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": query_string,
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _document(conn, uid="d1", title="My Document", content=None, **overrides):
    row = {
        "uid": uid, "title": title,
        "content_json": json.dumps(content if content is not None else {"blocks": []}),
        "document_type": "full", "note_type": overrides.pop("note_type", "notes"),
        "created_at": _now(), "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_notebook_document(conn, row)
    return db.get_notebook_document(conn, uid)


def _wikilink_block(target_uid: str, title: str = "Target") -> dict:
    return {
        "type": "paragraph",
        "data": {
            "text": (
                'Some text <span class="cdx-wikilink" data-target-uid="'
                + target_uid + '" data-target-title="' + title + '">' + title + "</span> more text."
            )
        },
    }


class TestExtractAndRebuildLinks:
    def test_set_document_content_rebuilds_outbound_links(self, conn):
        _document(conn, uid="d1")
        _document(conn, uid="d2", title="Target Doc")
        content = {"blocks": [_wikilink_block("d2", "Target Doc")]}
        db.set_notebook_document_content(conn, "d1", content)
        backlinks = db.list_notebook_backlinks(conn, "d2")
        assert [b["uid"] for b in backlinks] == ["d1"]

    def test_rebuild_replaces_the_whole_previous_set(self, conn):
        _document(conn, uid="d1")
        _document(conn, uid="d2")
        _document(conn, uid="d3")
        db.set_notebook_document_content(conn, "d1", {"blocks": [_wikilink_block("d2")]})
        db.set_notebook_document_content(conn, "d1", {"blocks": [_wikilink_block("d3")]})
        assert db.list_notebook_backlinks(conn, "d2") == []
        assert [b["uid"] for b in db.list_notebook_backlinks(conn, "d3")] == ["d1"]

    def test_multiple_links_to_the_same_target_are_deduped(self, conn):
        _document(conn, uid="d1")
        _document(conn, uid="d2")
        content = {"blocks": [_wikilink_block("d2"), _wikilink_block("d2")]}
        db.set_notebook_document_content(conn, "d1", content)
        assert len(db.list_notebook_backlinks(conn, "d2")) == 1

    def test_self_link_is_dropped(self, conn):
        _document(conn, uid="d1")
        content = {"blocks": [_wikilink_block("d1")]}
        db.set_notebook_document_content(conn, "d1", content)
        assert db.list_notebook_backlinks(conn, "d1") == []

    def test_content_with_no_wikilinks_leaves_no_links(self, conn):
        _document(conn, uid="d1")
        db.set_notebook_document_content(conn, "d1", {"blocks": [{"type": "paragraph", "data": {"text": "plain"}}]})
        assert db.list_notebook_backlinks(conn, "d1") == []

    def test_backlink_rows_carry_the_source_documents_type_look(self, conn):
        _document(conn, uid="d1", note_type="person")
        _document(conn, uid="d2")
        db.set_notebook_document_content(conn, "d1", {"blocks": [_wikilink_block("d2")]})
        backlinks = db.list_notebook_backlinks(conn, "d2")
        assert backlinks[0]["type_icon"] and backlinks[0]["type_color"]

    def test_missing_document_leaves_no_links_and_no_crash(self, conn):
        assert db.set_notebook_document_content(conn, "missing", {"blocks": []}) is False
        assert db.list_notebook_backlinks(conn, "missing") == []


class TestSearchNotebookDocuments:
    def test_search_matches_title_substring_case_insensitively(self, conn):
        _document(conn, uid="d1", title="Treaty of Versailles")
        _document(conn, uid="d2", title="Congress of Vienna")
        results = db.search_notebook_documents(conn, "treaty")
        assert [r["uid"] for r in results] == ["d1"]

    def test_blank_query_returns_everything_most_recent_first(self, conn):
        _document(conn, uid="d1", title="Older")
        _document(conn, uid="d2", title="Newer")
        results = db.search_notebook_documents(conn, "")
        assert [r["uid"] for r in results] == ["d2", "d1"]

    def test_exclude_uid_omits_that_document(self, conn):
        _document(conn, uid="d1", title="A")
        _document(conn, uid="d2", title="B")
        results = db.search_notebook_documents(conn, "", exclude_uid="d1")
        assert [r["uid"] for r in results] == ["d2"]

    def test_results_carry_note_type_look(self, conn):
        _document(conn, uid="d1", note_type="country")
        results = db.search_notebook_documents(conn, "")
        assert results[0]["color"] and results[0]["icon"]

    def test_limit_caps_result_count(self, conn):
        for i in range(5):
            _document(conn, uid=f"d{i}", title=f"Doc {i}")
        assert len(db.search_notebook_documents(conn, "", limit=2)) == 2


class TestSearchRoute:
    def test_search_route_returns_json(self, conn):
        _document(conn, uid="d1", title="Findable")
        resp = notebook_router.search_documents(_bare_request(), q="Findable", exclude="", conn=conn)
        body = json.loads(resp.body.decode())
        assert body[0]["uid"] == "d1"
        assert body[0]["title"] == "Findable"

    def test_search_route_excludes_current_document(self, conn):
        _document(conn, uid="d1", title="Self")
        resp = notebook_router.search_documents(_bare_request(), q="", exclude="d1", conn=conn)
        assert json.loads(resp.body.decode()) == []


class TestDocumentPageBacklinks:
    def test_document_page_carries_backlinks(self, conn):
        _document(conn, uid="d1")
        _document(conn, uid="d2", title="Linker")
        db.set_notebook_document_content(conn, "d2", {"blocks": [_wikilink_block("d1")]})
        req = Request(
            {
                "type": "http", "method": "GET", "path": "/notebook/d1", "query_string": b"",
                "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
            }
        )
        resp = notebook_router.document_page("d1", req, conn=conn)
        assert resp.context["backlinks"][0]["uid"] == "d2"
        assert "Linker" in resp.body.decode()


class TestBackupRoundTrip:
    def test_links_are_rebuilt_from_restored_content_not_backed_up_directly(self, conn, tmp_path):
        """notebook_links is a derived cache (db.py's own schema comment) --
        it rides along for free via each restored document's content_json,
        never as its own backup key."""
        _document(conn, uid="d1")
        _document(conn, uid="d2")
        db.set_notebook_document_content(conn, "d1", {"blocks": [_wikilink_block("d2")]})
        payload = export_router.build_backup_payload(conn)
        assert "notebook_links" not in payload

        with db.connect(tmp_path / "restored.sqlite") as fresh:
            export_router.restore_backup_payload(fresh, payload)
            assert [b["uid"] for b in db.list_notebook_backlinks(fresh, "d2")] == ["d1"]


class TestRankedSearch:
    def test_same_project_then_same_label_then_alphabetical(self, conn):
        db.upsert_label_config(conn, {"name": "Thesis", "is_project": 1})
        db.upsert_label_config(conn, {"name": "History"})
        for uid, title in (("me", "Me"), ("a", "Aardvark"), ("b", "Bravo"), ("c", "Charlie"), ("d", "Delta")):
            _document(conn, uid=uid, title=title)
        db.set_object_labels(conn, "notebook", "me", ["Thesis", "History"])
        db.set_object_labels(conn, "notebook", "d", ["Thesis"])
        db.set_object_labels(conn, "notebook", "c", ["History"])
        results = db.search_notebook_documents(conn, "", exclude_uid="me", rank_for="me")
        assert [r["uid"] for r in results] == ["d", "c", "a", "b"]
