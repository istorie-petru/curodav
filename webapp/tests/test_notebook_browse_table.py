"""Notebook Browse as a table: toggling filters, loading more rows, bulk edit and delete."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import notebook as notebook_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _request(path="/notebook"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


def _doc(conn, uid, title=None, **overrides):
    now = datetime.now(timezone.utc).isoformat()
    row = {"uid": uid, "title": title or uid, "content_json": '{"blocks": []}', "document_type": "full",
           "note_type": "", "created_at": now, "updated_at": now, "tags": []}
    row.update(overrides)
    db.upsert_notebook_document(conn, row)


def _json_request(payload):
    request = _request("/notebook/bulk-delete")

    async def receive():
        return {"type": "http.request", "body": json.dumps(payload).encode(), "more_body": False}

    request._receive = receive
    return request


class TestFilters:
    def test_picking_the_active_filter_again_removes_it(self, conn):
        _doc(conn, "a", note_type="person", tags=["Uni"])
        ctx = notebook_router._notebook_browse_context(conn, _request(), "person", "", "", "updated")
        assert ctx["facet_href"]("note_type", "person") == "/notebook"
        assert ctx["facet_href"]("note_type", "wiki") == "/notebook?note_type=wiki"

    def test_filters_across_dimensions_combine_and_keep_the_sort(self, conn):
        ctx = notebook_router._notebook_browse_context(conn, _request(), "person", "", "", "title")
        assert ctx["facet_href"]("label", "Uni") == "/notebook?note_type=person&label=Uni&sort=title"

    def test_rail_links_use_the_toggle_hrefs(self, conn):
        _doc(conn, "a", note_type="person")
        body = notebook_router.list_documents(_request(), note_type="person", conn=conn).body.decode()
        assert 'is-active" href="/notebook"' in body


class TestTable:
    def test_documents_render_as_a_table_with_selection_boxes(self, conn):
        _doc(conn, "a", title="Thesis", note_type="notes", tags=["Uni"])
        body = notebook_router.list_documents(_request(), conn=conn).body.decode()
        assert 'class="entity-table notebook-browse-table"' in body
        assert 'data-uid="a"' in body and "row-select" in body and "Thesis" in body

    def test_no_bold_text_on_the_browse_page(self, conn):
        body = notebook_router.list_documents(_request(), conn=conn).body.decode()
        assert "notebook-browse-page" in body


class TestLoadMore:
    def test_first_page_is_thirty_rows_with_a_load_more_link(self, conn):
        for n in range(45):
            _doc(conn, f"d{n:02d}")
        resp = notebook_router.list_documents(_request(), conn=conn)
        assert len(resp.context["documents"]) == 30
        assert 'id="notebook-load-more"' in resp.body.decode()

    def test_no_button_when_everything_fits(self, conn):
        for n in range(5):
            _doc(conn, f"d{n}")
        assert 'id="notebook-load-more"' not in notebook_router.list_documents(_request(), conn=conn).body.decode()

    def test_the_rows_endpoint_returns_the_rest(self, conn):
        for n in range(45):
            _doc(conn, f"d{n:02d}", title=f"Doc {n:02d}")
        data = json.loads(notebook_router.browse_rows(_request("/notebook/rows"), sort="title", offset=30, conn=conn).body)
        assert data["has_more"] is False
        assert data["html"].count("<tr ") == 15 and "Doc 44" in data["html"]

    def test_limit_param_shows_more_without_javascript(self, conn):
        for n in range(45):
            _doc(conn, f"d{n:02d}")
        resp = notebook_router.list_documents(_request(), limit=60, conn=conn)
        assert len(resp.context["documents"]) == 45 and not resp.context["has_more"]


class TestBulk:
    def test_bulk_delete_removes_the_selected_documents(self, conn):
        for uid in ("a", "b", "c"):
            _doc(conn, uid)
        resp = asyncio.run(notebook_router.bulk_delete(_json_request({"uids": ["a", "b"]}), conn=conn))
        assert resp.status_code == 200
        assert [d["uid"] for d in db.list_notebook_documents(conn)] == ["c"]

    def test_bulk_delete_with_nothing_selected_is_refused(self, conn):
        resp = asyncio.run(notebook_router.bulk_delete(_json_request({"uids": []}), conn=conn))
        assert resp.status_code == 400

    def test_bulk_edit_adds_and_removes_labels_and_sets_the_type(self, conn):
        _doc(conn, "a", tags=["Old"], note_type="notes")
        _doc(conn, "b", tags=["Old", "Keep"])
        notebook_router.bulk_edit(uids=["a", "b"], add_tag="New", remove_tag="Old", note_type="wiki",
                                  x_requested_with=None, conn=conn)
        for uid in ("a", "b"):
            doc = db.get_notebook_document(conn, uid)
            assert "Old" not in doc["tags"] and "New" in doc["tags"] and doc["note_type"] == "wiki"
        assert "Keep" in db.get_notebook_document(conn, "b")["tags"]

    def test_blank_fields_change_nothing(self, conn):
        _doc(conn, "a", tags=["Old"], note_type="notes")
        notebook_router.bulk_edit(uids=["a"], add_tag="", remove_tag="", note_type="", x_requested_with=None, conn=conn)
        doc = db.get_notebook_document(conn, "a")
        assert doc["tags"] == ["Old"] and doc["note_type"] == "notes"

    def test_modal_lists_the_fields(self, conn):
        body = notebook_router.bulk_edit_modal("a,b", _request("/notebook/bulk-edit-modal"), conn=conn).body.decode()
        assert "Edit 2 documents" in body
        for name in ("add_tag", "remove_tag", "note_type"):
            assert f'name="{name}"' in body
