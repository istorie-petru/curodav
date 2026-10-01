"""Notebook (curodav-notes/documentation/plans/STATE.md +
architecture-notes-module-2026-09-29.md, 2026-09-29) -- Phase 1 backend
skeleton coverage: db.py's CRUD + content get/set, and
routers/notebook.py's list/create/edit-title/delete/content endpoints.
Grows through every subsequent phase (Editor.js integration, Groups/Labels
browsing), per the roadmap's mandatory-testing rule -- not written once at
the end."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import dashboard as dashboard_router
from src.routers import notebook as notebook_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bare_request(path="/notebook", query_string: bytes = b""):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": query_string,
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )


def _put_json_request(path: str, payload: dict):
    req = Request({"type": "http", "method": "PUT", "path": path, "headers": [(b"content-type", b"application/json")]})

    async def receive():
        return {"type": "http.request", "body": json.dumps(payload).encode(), "more_body": False}

    req._receive = receive
    return req


def _document(conn, uid="d1", title="My Document", **overrides):
    row = {
        "uid": uid,
        "title": title,
        "content_json": '{"blocks": []}',
        "document_type": "full",
        "note_type": "notes",
        "created_at": _now(),
        "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_notebook_document(conn, row)
    return db.get_notebook_document(conn, uid)


class TestDb:
    def test_upsert_and_get_round_trips(self, conn):
        doc = _document(conn, tags=["University"])
        assert doc["title"] == "My Document"
        assert doc["note_type"] == "notes"
        assert doc["tags"] == ["University"]

    def test_list_defaults_to_every_document_newest_first(self, conn):
        _document(conn, uid="old", title="Old", created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00")
        _document(conn, uid="new", title="New", created_at="2026-02-01T00:00:00+00:00", updated_at="2026-02-01T00:00:00+00:00")
        docs = db.list_notebook_documents(conn)
        assert [d["uid"] for d in docs] == ["new", "old"]

    def test_list_filters_by_label(self, conn):
        _document(conn, uid="d1", tags=["University"])
        _document(conn, uid="d2", tags=["Personal"])
        docs = db.list_notebook_documents(conn, label="University")
        assert [d["uid"] for d in docs] == ["d1"]

    def test_delete_removes_document_and_labels(self, conn):
        _document(conn, uid="d1", tags=["University"])
        db.delete_notebook_document(conn, "d1")
        assert db.get_notebook_document(conn, "d1") is None
        assert db.list_labels_for_object(conn, "notebook", "d1") == []

    def test_content_round_trips_through_get_set(self, conn):
        _document(conn, uid="d1")
        ok = db.set_notebook_document_content(conn, "d1", {"blocks": [{"type": "paragraph", "data": {"text": "hi"}}]})
        assert ok is True
        content = db.get_notebook_document_content(conn, "d1")
        assert content["blocks"][0]["data"]["text"] == "hi"

    def test_set_content_on_missing_document_reports_no_match(self, conn):
        assert db.set_notebook_document_content(conn, "missing", {"blocks": []}) is False

    def test_get_content_on_missing_document_is_none(self, conn):
        assert db.get_notebook_document_content(conn, "missing") is None

    def test_get_content_recovers_from_corrupt_json_instead_of_500(self, conn):
        _document(conn, uid="d1")
        conn.execute("UPDATE notebook_documents SET content_json = 'not json' WHERE uid = 'd1'")
        conn.commit()
        assert db.get_notebook_document_content(conn, "d1") == {"blocks": []}


class TestRouter:
    def test_list_documents_renders_title_and_nav_tab(self, conn):
        _document(conn, uid="d1", title="Thesis Notes")
        resp = notebook_router.list_documents(_bare_request(), conn=conn)
        body = resp.body.decode()
        assert resp.context["active_tab"] == "notebook"
        assert "Thesis Notes" in body

    def test_list_documents_empty_state(self, conn):
        resp = notebook_router.list_documents(_bare_request(), conn=conn)
        assert "No documents yet" in resp.body.decode()

    def test_create_document_defaults_to_untitled_and_redirects_to_its_editor(self, conn):
        resp = notebook_router.create_document(label="", x_requested_with=None, conn=conn)
        assert resp.status_code == 303
        docs = db.list_notebook_documents(conn)
        assert len(docs) == 1
        assert resp.headers["location"] == f"/notebook/{docs[0]['uid']}"
        assert docs[0]["title"] == "Untitled"
        assert docs[0]["tags"] == []

    def test_create_document_with_label_json_response(self, conn):
        resp = notebook_router.create_document(label="University", x_requested_with="fetch", conn=conn)
        assert resp.status_code == 201
        body = json.loads(resp.body.decode())
        doc = db.get_notebook_document(conn, body["uid"])
        assert doc["tags"] == ["University"]

    def test_document_page_renders_editor_mount_with_uid(self, conn):
        _document(conn, uid="d1", title="Thesis Notes")
        resp = notebook_router.document_page("d1", _bare_request("/notebook/d1"), conn=conn)
        body = resp.body.decode()
        assert 'data-uid="d1"' in body
        assert 'data-content-url="/notebook/d1/content"' in body

    def test_document_page_missing_uid_redirects_to_list(self, conn):
        resp = notebook_router.document_page("missing", _bare_request("/notebook/missing"), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/notebook"

    def test_update_title_renames_document(self, conn):
        _document(conn, uid="d1", title="Untitled")
        resp = notebook_router.update_document_title("d1", title="Renamed", x_requested_with=None, conn=conn)
        assert resp.status_code == 303
        assert db.get_notebook_document(conn, "d1")["title"] == "Renamed"

    def test_update_title_blank_falls_back_to_untitled(self, conn):
        _document(conn, uid="d1", title="Something")
        notebook_router.update_document_title("d1", title="   ", x_requested_with=None, conn=conn)
        assert db.get_notebook_document(conn, "d1")["title"] == "Untitled"

    def test_update_title_missing_document_is_a_404_for_json(self, conn):
        resp = notebook_router.update_document_title("missing", title="X", x_requested_with="fetch", conn=conn)
        assert resp.status_code == 404

    def test_delete_document_removes_it(self, conn):
        _document(conn, uid="d1")
        resp = notebook_router.delete_document("d1", x_requested_with=None, conn=conn)
        assert resp.status_code == 303
        assert db.get_notebook_document(conn, "d1") is None

    def test_get_content_endpoint(self, conn):
        _document(conn, uid="d1", content_json='{"blocks": [{"type": "paragraph", "data": {"text": "hi"}}]}')
        resp = notebook_router.get_document_content("d1", conn=conn)
        data = json.loads(resp.body.decode())
        assert data["blocks"][0]["data"]["text"] == "hi"

    def test_get_content_endpoint_missing_document_is_404(self, conn):
        resp = notebook_router.get_document_content("missing", conn=conn)
        assert resp.status_code == 404

    def test_put_content_endpoint_saves_and_bumps_updated_at(self, conn):
        _document(conn, uid="d1", updated_at="2026-01-01T00:00:00+00:00")
        req = _put_json_request("/notebook/d1/content", {"blocks": [{"type": "header", "data": {"text": "Hi", "level": 1}}]})
        resp = asyncio.run(notebook_router.put_document_content("d1", req, conn=conn))
        assert resp.status_code == 200
        doc = db.get_notebook_document(conn, "d1")
        assert doc["updated_at"] != "2026-01-01T00:00:00+00:00"
        assert db.get_notebook_document_content(conn, "d1")["blocks"][0]["data"]["text"] == "Hi"

    def test_put_content_endpoint_missing_document_is_404(self, conn):
        req = _put_json_request("/notebook/missing/content", {"blocks": []})
        resp = asyncio.run(notebook_router.put_document_content("missing", req, conn=conn))
        assert resp.status_code == 404


class TestDashboardWidget:
    """routers/dashboard.py's _render_notebook_list -- Phase 3 of the
    roadmap, the Groups/Labels widget. Scope/tags-filter/limit mechanics
    are the same pipeline test_dashboard_router.py already covers for
    _render_contact_list; this focuses on what's Notebook-specific:
    label scoping and the create_label gate."""

    def test_unscoped_shows_every_document_with_no_create_action(self, conn):
        _document(conn, uid="d1", tags=["University"])
        _document(conn, uid="d2", tags=[])
        data = dashboard_router._render_notebook_list(conn, {})
        assert {d["uid"] for d in data["documents"]} == {"d1", "d2"}
        assert data["create_label"] is None

    def test_label_page_scopes_to_that_label_and_offers_create(self, conn):
        _document(conn, uid="d1", tags=["University"])
        _document(conn, uid="d2", tags=["Personal"])
        data = dashboard_router._render_notebook_list(conn, {"label_name": "University"})
        assert [d["uid"] for d in data["documents"]] == ["d1"]
        assert data["create_label"] == "University"

    def test_group_page_scopes_to_member_labels_with_no_create_action(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "label_group": "Uni", "color": "blue", "created_at": _now()})
        _document(conn, uid="d1", tags=["CS101"])
        _document(conn, uid="d2", tags=["Elsewhere"])
        data = dashboard_router._render_notebook_list(conn, {"label_name": "group:Uni"})
        assert [d["uid"] for d in data["documents"]] == ["d1"]
        # A group aggregates several labels -- no single one to pre-attach
        # a new document to, so the widget offers no create action here.
        assert data["create_label"] is None

    def test_limit_caps_results(self, conn):
        for i in range(10):
            _document(conn, uid=f"d{i}", tags=["University"])
        data = dashboard_router._render_notebook_list(conn, {"label_name": "University", "limit": 3})
        assert len(data["documents"]) == 3
