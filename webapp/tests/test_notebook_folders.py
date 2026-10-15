"""Notebook folders: the home, a folder's list and paging, bulk edit and delete."""

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


class TestHome:
    def test_the_home_shows_project_and_label_folders_and_the_library(self, conn):
        db.upsert_label_config(conn, {"name": "Thesis", "is_project": True})
        _doc(conn, "a", tags=["Thesis"])
        _doc(conn, "b", tags=["Reading"])
        _doc(conn, "c")
        body = notebook_router.list_documents(_request(), conn=conn).body.decode()
        for text in ("Thesis", "Reading", "Unfiled", "Entries", "Citations", "Templates"):
            assert text in body
        assert "/notebook/folder?kind=project&amp;name=Thesis" in body or "/notebook/folder?kind=project&name=Thesis" in body

    def test_an_empty_notebook_shows_the_empty_state(self, conn):
        body = notebook_router.list_documents(_request(), conn=conn).body.decode()
        assert "No documents yet" in body

    def test_the_label_report_notice_shows_until_dismissed(self, conn):
        db.set_app_meta(conn, "notebook_label_report", json.dumps([{"uid": "a", "title": "A", "kept": ["X"], "dropped": ["Y"]}]))
        assert "had several labels" in notebook_router.list_documents(_request(), conn=conn).body.decode()
        notebook_router.dismiss_label_report(conn=conn)
        assert "had several labels" not in notebook_router.list_documents(_request(), conn=conn).body.decode()


class TestFolder:
    def test_a_folder_lists_only_its_notes_with_selection_boxes(self, conn):
        _doc(conn, "a", title="Thesis note", note_type="notes", tags=["Uni"])
        _doc(conn, "b", title="Other", tags=["Elsewhere"])
        resp = notebook_router.folder_view(_request("/notebook/folder"), kind="label", name="Uni", conn=conn)
        body = resp.body.decode()
        assert "Thesis note" in body and "Other" not in body and 'data-uid="a"' in body and "row-select" in body

    def test_the_type_filter_narrows_a_folder(self, conn):
        _doc(conn, "a", note_type="notes", tags=["Uni"])
        _doc(conn, "b", note_type="wiki", tags=["Uni"])
        resp = notebook_router.folder_view(_request("/notebook/folder"), kind="label", name="Uni", note_type="wiki", conn=conn)
        assert [d["uid"] for d in resp.context["documents"]] == ["b"]

    def test_a_folder_sorts_by_title_on_request(self, conn):
        _doc(conn, "a", title="Zed", tags=["Uni"])
        _doc(conn, "b", title="Alpha", tags=["Uni"])
        resp = notebook_router.folder_view(_request("/notebook/folder"), kind="label", name="Uni", sort="title", conn=conn)
        assert [d["title"] for d in resp.context["documents"]] == ["Alpha", "Zed"]

    def test_first_page_is_thirty_rows_with_a_load_more_link(self, conn):
        for n in range(45):
            _doc(conn, f"d{n:02d}", tags=["Uni"])
        resp = notebook_router.folder_view(_request("/notebook/folder"), kind="label", name="Uni", conn=conn)
        assert len(resp.context["documents"]) == 30
        assert 'id="notebook-load-more"' in resp.body.decode()

    def test_no_button_when_everything_fits(self, conn):
        for n in range(5):
            _doc(conn, f"d{n}", tags=["Uni"])
        body = notebook_router.folder_view(_request("/notebook/folder"), kind="label", name="Uni", conn=conn).body.decode()
        assert 'id="notebook-load-more"' not in body

    def test_the_rows_endpoint_returns_the_rest(self, conn):
        for n in range(45):
            _doc(conn, f"d{n:02d}", title=f"Doc {n:02d}", tags=["Uni"])
        data = json.loads(notebook_router.folder_rows(_request("/notebook/folder/rows"), kind="label", name="Uni", sort="title", offset=30, conn=conn).body)
        assert data["has_more"] is False
        assert data["html"].count('class="contact-row-wrap"') == 15 and "Doc 44" in data["html"]

    def test_an_unfiled_folder_holds_notes_without_a_label_or_project(self, conn):
        _doc(conn, "a")
        _doc(conn, "b", tags=["Uni"])
        resp = notebook_router.folder_view(_request("/notebook/folder"), kind="unfiled", conn=conn)
        assert [d["uid"] for d in resp.context["documents"]] == ["a"]


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

    def test_bulk_edit_sets_the_label_and_the_type(self, conn):
        _doc(conn, "a", tags=["Old"], note_type="notes")
        _doc(conn, "b", tags=["Other"])
        notebook_router.bulk_edit(uids=["a", "b"], label="New", project="", note_type="wiki", x_requested_with=None, conn=conn)
        for uid in ("a", "b"):
            doc = db.get_notebook_document(conn, uid)
            assert doc["tags"] == ["New"] and doc["note_type"] == "wiki"

    def test_bulk_edit_can_clear_the_label_and_keeps_the_project(self, conn):
        db.upsert_label_config(conn, {"name": "Thesis", "is_project": True})
        _doc(conn, "a", tags=["Thesis", "Old"])
        notebook_router.bulk_edit(uids=["a"], label="__none__", project="", note_type="", x_requested_with=None, conn=conn)
        assert db.get_notebook_document(conn, "a")["tags"] == ["Thesis"]

    def test_bulk_edit_sets_the_project_and_keeps_the_label(self, conn):
        db.upsert_label_config(conn, {"name": "Thesis", "is_project": True})
        _doc(conn, "a", tags=["Old"])
        notebook_router.bulk_edit(uids=["a"], label="", project="Thesis", note_type="", x_requested_with=None, conn=conn)
        assert sorted(db.get_notebook_document(conn, "a")["tags"]) == ["Old", "Thesis"]

    def test_blank_fields_change_nothing(self, conn):
        _doc(conn, "a", tags=["Old"], note_type="notes")
        notebook_router.bulk_edit(uids=["a"], label="", project="", note_type="", x_requested_with=None, conn=conn)
        doc = db.get_notebook_document(conn, "a")
        assert doc["tags"] == ["Old"] and doc["note_type"] == "notes"

    def test_modal_lists_the_fields(self, conn):
        body = notebook_router.bulk_edit_modal("a,b", _request("/notebook/bulk-edit-modal"), conn=conn).body.decode()
        assert "Edit 2 documents" in body
        for name in ("label", "project", "note_type"):
            assert f'name="{name}"' in body


class TestPinned:
    def test_a_pinned_note_shows_on_the_home_and_an_unpinned_one_does_not(self, conn):
        _doc(conn, "a", title="Keep close", tags=["Uni"])
        _doc(conn, "b", title="Elsewhere", tags=["Uni"])
        notebook_router.pin_document("a", pinned="1", x_requested_with=None, conn=conn)
        body = notebook_router.list_documents(_request(), conn=conn).body.decode()
        pinned = body.split('id="notebook-pinned"', 1)[1].split("</div>\n    </div>", 1)[0]
        assert "Keep close" in pinned and "Elsewhere" not in pinned
        notebook_router.pin_document("a", pinned="0", x_requested_with=None, conn=conn)
        assert "Pinned" not in notebook_router.list_documents(_request(), conn=conn).body.decode()

    def test_saving_a_note_does_not_unpin_it(self, conn):
        _doc(conn, "a", tags=["Uni"])
        notebook_router.pin_document("a", pinned="1", x_requested_with=None, conn=conn)
        doc = db.get_notebook_document(conn, "a")
        db.upsert_notebook_document(conn, {k: doc[k] for k in ("uid", "title", "content_json", "document_type", "note_type", "created_at", "updated_at")})
        assert db.get_notebook_document(conn, "a")["pinned"] == 1

    def test_a_pinned_note_still_lives_in_its_folder(self, conn):
        _doc(conn, "a", tags=["Uni"])
        notebook_router.pin_document("a", pinned="1", x_requested_with=None, conn=conn)
        assert [d["uid"] for d in notebook_router.folder_view(_request("/notebook/folder"), kind="label", name="Uni", conn=conn).context["documents"]] == ["a"]


class TestBackToTheFolder:
    def test_a_folder_page_has_a_back_arrow_to_the_notebook_home(self, conn):
        _doc(conn, "a", tags=["Uni"])
        ctx = notebook_router.folder_view(_request("/notebook/folder"), kind="label", name="Uni", conn=conn).context
        assert ctx["crumbs"] == [{"url": "/notebook", "name": "Notebook"}]

    def test_a_note_opened_from_a_folder_goes_back_to_that_folder(self, conn):
        _doc(conn, "a", tags=["Uni"])
        body = notebook_router.folder_view(_request("/notebook/folder"), kind="label", name="Uni", conn=conn).body.decode()
        assert "back_to=/notebook/folder%3Fkind%3Dlabel%26name%3DUni" in body


    def test_the_pin_button_is_in_the_properties_modal_footer_not_the_note_header(self, conn):
        _doc(conn, "a", tags=["Uni"])
        modal = notebook_router.document_properties_modal("a", _request("/notebook/a/properties"), conn=conn).body.decode()
        assert 'action="/notebook/a/pin"' in modal and "Pin" in modal
        page = notebook_router.document_page("a", _request("/notebook/a"), conn=conn).body.decode()
        assert 'action="/notebook/a/pin"' not in page
