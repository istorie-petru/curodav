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


def _paint_type(conn, value, color, icon):
    uid = db.BUILTIN_NOTEBOOK_FIELD_UIDS["note_type"]
    options = [{**o, "color": color, "icon": icon} if o["value"] == value else o
               for o in db.get_notebook_field_config(conn, uid)["options"]]
    db.set_notebook_field_options(conn, uid, options)


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
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "10.1/x"}])
        db.delete_notebook_document(conn, "d1")
        assert db.get_notebook_document(conn, "d1") is None
        assert db.list_labels_for_object(conn, "notebook", "d1") == []
        assert db.list_notebook_properties(conn, "d1") == []

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

    def test_note_types_in_use_lists_distinct_non_blank_values(self, conn):
        _document(conn, uid="d1", note_type="wiki")
        _document(conn, uid="d2", note_type="wiki")
        _document(conn, uid="d3", note_type="research")
        _document(conn, uid="d4", note_type="")
        assert db.list_notebook_note_types_in_use(conn) == ["research", "wiki"]

    def test_note_types_in_use_is_empty_with_no_documents(self, conn):
        assert db.list_notebook_note_types_in_use(conn) == []

    def test_note_type_drops_off_once_nothing_uses_it(self, conn):
        # 2026-10-02 direct request: "frontmatter that is no longer used
        # should be removed from the list" -- same "in use" shape as
        # Labels, not a fixed starter list that lingers regardless of
        # actual use.
        _document(conn, uid="d1", note_type="wiki")
        assert db.list_notebook_note_types_in_use(conn) == ["wiki"]
        notebook_router.update_document_properties(
            "d1", title="D1", note_type="research", note_type_new="", tags_labels=[],
            property_key=[], property_value=[], conn=conn
        )
        assert db.list_notebook_note_types_in_use(conn) == ["research"]


class TestProperties:
    """Custom document properties (2026-10-02, roadmap-browser-modal-
    properties-2026-10-02.md Phase 2) -- notebook_properties' CRUD and its
    attachment onto get/list_notebook_document(s), same "child table
    attached like tags" shape contacts' phones/emails already use."""

    def test_set_then_list_round_trips_in_order(self, conn):
        _document(conn, uid="d1")
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "10.1/x"}, {"key": "Institution", "value": "UBB"}])
        props = db.list_notebook_properties(conn, "d1")
        assert [(p["key"], p["value"]) for p in props] == [("DOI", "10.1/x"), ("Institution", "UBB")]

    def test_set_replaces_the_whole_list(self, conn):
        _document(conn, uid="d1")
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "old"}])
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "new"}])
        props = db.list_notebook_properties(conn, "d1")
        assert len(props) == 1
        assert props[0]["value"] == "new"

    def test_set_drops_rows_with_a_blank_key(self, conn):
        _document(conn, uid="d1")
        db.set_notebook_properties(conn, "d1", [{"key": "", "value": "orphaned"}, {"key": "DOI", "value": "x"}])
        props = db.list_notebook_properties(conn, "d1")
        assert [p["key"] for p in props] == ["DOI"]

    def test_set_with_no_items_clears_existing_properties(self, conn):
        _document(conn, uid="d1")
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "x"}])
        db.set_notebook_properties(conn, "d1", [])
        assert db.list_notebook_properties(conn, "d1") == []

    def test_get_notebook_document_attaches_properties(self, conn):
        _document(conn, uid="d1")
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "x"}])
        doc = db.get_notebook_document(conn, "d1")
        assert doc["properties"][0]["key"] == "DOI"

    def test_list_notebook_documents_attaches_properties_bulk(self, conn):
        _document(conn, uid="d1")
        _document(conn, uid="d2")
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "x"}])
        docs = {d["uid"]: d for d in db.list_notebook_documents(conn)}
        assert [p["key"] for p in docs["d1"]["properties"]] == ["DOI"]
        assert docs["d2"]["properties"] == []

    def test_upsert_notebook_document_with_properties_key_sets_them(self, conn):
        # Same "pop 'properties', write the base row, then attach the
        # related rows" shape upsert_contact's phones/emails use -- a
        # caller (e.g. backup restore) can pass a full document dict with
        # a "properties" key and have it round-trip through one call.
        doc = _document(conn, uid="d1")
        doc = dict(doc)
        doc["properties"] = [{"key": "DOI", "value": "x"}]
        db.upsert_notebook_document(conn, doc)
        assert db.get_notebook_document(conn, "d1")["properties"][0]["key"] == "DOI"

    def test_upsert_notebook_document_without_properties_key_leaves_them_untouched(self, conn):
        # `properties` not present in the row dict at all (vs. an explicit
        # empty list) must NOT clear existing properties -- same "None
        # means don't touch" contract `tags` already has on this function.
        _document(conn, uid="d1")
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "x"}])
        existing = dict(db.get_notebook_document(conn, "d1"))
        del existing["properties"]
        existing["title"] = "Renamed"
        db.upsert_notebook_document(conn, existing)
        assert db.get_notebook_document(conn, "d1")["properties"][0]["key"] == "DOI"

    def test_property_keys_in_use_lists_distinct_non_blank_keys_across_documents(self, conn):
        # 2026-10-02 direct request ("use a drop down similar to the
        # labels one - once a new properties is added, it is available in
        # the list") -- scoped across every document, not just one, same
        # as note_types_in_use/tag_names_in_use.
        _document(conn, uid="d1")
        _document(conn, uid="d2")
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "x"}, {"key": "Institution", "value": "y"}])
        db.set_notebook_properties(conn, "d2", [{"key": "DOI", "value": "z"}])
        assert db.list_notebook_property_keys_in_use(conn) == ["DOI", "Institution"]

    def test_property_keys_in_use_is_empty_with_no_properties(self, conn):
        _document(conn, uid="d1")
        assert db.list_notebook_property_keys_in_use(conn) == []

    def test_property_key_drops_off_once_nothing_uses_it(self, conn):
        _document(conn, uid="d1")
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "x"}])
        assert db.list_notebook_property_keys_in_use(conn) == ["DOI"]
        db.set_notebook_properties(conn, "d1", [{"key": "Institution", "value": "y"}])
        assert db.list_notebook_property_keys_in_use(conn) == ["Institution"]


class TestRouter:
    def test_list_documents_renders_title_and_nav_tab(self, conn):
        _document(conn, uid="d1", title="Thesis Notes")
        resp = notebook_router.list_documents(_bare_request(), conn=conn)
        body = resp.body.decode()
        assert resp.context["active_tab"] == "notebook"
        assert "Thesis Notes" in body

    def test_list_documents_row_links_to_the_properties_modal(self, conn):
        # Phase 1 (roadmap-browser-modal-properties-2026-10-02.md) -- the
        # All Documents list had no entry point to the properties modal
        # before this; every row should link to it now.
        _document(conn, uid="d1", title="Thesis Notes")
        resp = notebook_router.list_documents(_bare_request(), conn=conn)
        assert '/notebook/d1/properties' in resp.body.decode()

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
        # 2026-10-02 direct request: no Type picked yet on a fresh document,
        # not defaulted to "notes" -- see routers/notebook.py's own comment.
        assert docs[0]["note_type"] == ""


class TestDocumentPageBackButton:
    """Roadmap item G (session 8, 2026-10-03) -- the Document editor's
    back arrow defaults to Notebook home, but honors back_to/back_label
    when a caller (Browse-widget row, label/group page, wikilink nav,
    backlink nav) supplies them."""

    def test_defaults_to_notebook_home_with_no_params(self, conn):
        _document(conn, uid="d1", title="Thesis Notes")
        resp = notebook_router.document_page(uid="d1", request=_bare_request("/notebook/d1"), conn=conn)
        assert resp.context["crumbs"] == [{"url": "/notebook", "name": "Notebook"}]

    def test_honors_back_to_and_back_label(self, conn):
        _document(conn, uid="d1", title="Thesis Notes")
        resp = notebook_router.document_page(
            uid="d1", request=_bare_request("/notebook/d1"), back_to="/labels/chemistry",
            back_label="Chemistry", conn=conn,
        )
        assert resp.context["crumbs"] == [{"url": "/labels/chemistry", "name": "Chemistry"}]

    def test_back_to_falls_back_to_notebook_name_with_no_back_label(self, conn):
        _document(conn, uid="d1", title="Thesis Notes")
        resp = notebook_router.document_page(
            uid="d1", request=_bare_request("/notebook/d1"), back_to="/labels/chemistry", conn=conn,
        )
        assert resp.context["crumbs"] == [{"url": "/labels/chemistry", "name": "Notebook"}]

    def test_off_origin_back_to_is_rejected_same_as_return_to(self, conn):
        _document(conn, uid="d1", title="Thesis Notes")
        resp = notebook_router.document_page(
            uid="d1", request=_bare_request("/notebook/d1"), back_to="https://evil.example/", conn=conn,
        )
        assert resp.context["crumbs"] == [{"url": "/notebook", "name": "Notebook"}]

    def test_self_url_and_title_are_always_this_document(self, conn):
        _document(conn, uid="d1", title="Thesis Notes")
        resp = notebook_router.document_page(uid="d1", request=_bare_request("/notebook/d1"), conn=conn)
        assert resp.context["self_url"] == "/notebook/d1"
        assert resp.context["self_title"] == "Thesis Notes"


class TestDocumentPageSidebarLayout:
    """2026-10-04 direct request -- the Document editor renders one of two
    genuinely different template branches depending on Settings >
    Notebook's sidebar-layout preference (db.get_notebook_settings). See
    notebook_document.html's own header comment for the full shape of
    each branch; this just checks the context value flows through and the
    two branches' own markup are mutually exclusive."""

    def test_defaults_to_stacked_with_no_setting_saved(self, conn):
        _document(conn, uid="d1", title="Thesis Notes")
        resp = notebook_router.document_page(uid="d1", request=_bare_request("/notebook/d1"), conn=conn)
        assert resp.context["sidebar_layout"] == "stacked"
        body = resp.body.decode()
        assert "notebook-page-stacked" in body
        assert "notebook-sidebar-toggle" not in body
        assert "cdx-footnote-footer__heading\">Outline" in body

    def test_sidebar_layout_renders_the_sidebar_shell_without_an_endnotes_tab(self, conn):
        db.save_notebook_settings(conn, "sidebar")
        _document(conn, uid="d1", title="Thesis Notes")
        resp = notebook_router.document_page(uid="d1", request=_bare_request("/notebook/d1"), conn=conn)
        assert resp.context["sidebar_layout"] == "sidebar"
        body = resp.body.decode()
        assert 'class="notebook-sidebar"' in body
        assert "notebook-sidebar-toggle" in body
        assert 'data-notebook-sidebar-tab="endnotes"' not in body
        assert 'id="notebook-footnotes-sidebar-slot"' not in body
        # The bottom-of-page Bibliography card is dropped in this branch
        # (it lives only in the sidebar tab now) -- confirmed by checking
        # for the specific bottom-card wrapper class, not just the word
        # "Bibliography" (which the sidebar tab button also contains).
        assert "notebook-bibliography-footer" not in body

    def test_stacked_layout_shows_bibliography_as_a_bottom_card_when_attached(self, conn):
        _document(conn, uid="d1", title="Thesis Notes")
        db.upsert_citation(conn, {
            "uid": "c1", "type": "book", "title": "A History of Something",
            "authors": [{"family": "Bloch", "given": "Marc"}], "year": "1924",
            "container_title": "", "doi": "", "url": "",
        })
        db.set_notebook_citations(conn, "d1", ["c1"])
        resp = notebook_router.document_page(uid="d1", request=_bare_request("/notebook/d1"), conn=conn)
        body = resp.body.decode()
        assert "notebook-bibliography-footer" in body
        assert "A History of Something" in body


class TestBrowseFiltering:
    """Browse page's filing-rail redesign (notebook-browse-page-widget-
    plans.md, 2026-10-02) -- routers/notebook.py's `_notebook_browse_context`.
    Rail counts are always global (unaffected by the current filter); each
    facet pick is a single-select-per-dimension, AND-combined across
    dimensions, same convention described in that plan's own notes."""

    def _seed(self, conn):
        _document(conn, uid="d1", title="Thesis", note_type="person", tags=["History"])
        _document(conn, uid="d2", title="Essay", note_type="research", tags=["History", "Uni"])
        _document(conn, uid="d3", title="Appendix", note_type="research", tags=["Uni"])
        _document(conn, uid="d4", title="Blank", note_type="", tags=[])
        db.upsert_label_config(conn, {"name": "History", "label_group": "School"})
        db.upsert_label_config(conn, {"name": "Uni", "label_group": "School"})

    def _list(self, conn, **params):
        # Calling the route function directly (not through FastAPI's real
        # routing) means Query/str params only ever get their Python
        # defaults -- a `query_string` on the bare Request is never parsed
        # this way, same gotcha routers/notebook.py's own `_s()` helper
        # exists for -- so every filter here is passed as an explicit
        # kwarg, not baked into the Request.
        kwargs = {"note_type": "", "label": "", "group": "", "sort": "updated"}
        kwargs.update(params)
        return notebook_router.list_documents(_bare_request(), conn=conn, **kwargs)

    def test_rail_counts_are_global_not_post_filter(self, conn):
        self._seed(conn)
        resp = self._list(conn, note_type="research")
        ctx = resp.context
        assert ctx["total_documents"] == 4
        assert {t["name"]: t["count"] for t in ctx["type_rows"]} == {"person": 1, "research": 2}
        assert {l["name"]: l["count"] for l in ctx["label_rows"]} == {"History": 2, "Uni": 2}
        # The TYPE rail has no bucket for blank note_type (d4) -- matches
        # the mockup, which shows no "untyped" row either.
        assert len(ctx["type_rows"]) == 2

    def test_note_type_filters_the_list(self, conn):
        self._seed(conn)
        resp = self._list(conn, note_type="person")
        assert [d["uid"] for d in resp.context["documents"]] == ["d1"]
        assert resp.context["active_note_type"] == "person"
        assert resp.context["notebook_filter_active"] is True

    def test_label_filters_the_list(self, conn):
        self._seed(conn)
        resp = self._list(conn, label="Uni")
        assert sorted(d["uid"] for d in resp.context["documents"]) == ["d2", "d3"]

    def test_group_filters_by_every_member_labels_docs(self, conn):
        self._seed(conn)
        resp = self._list(conn, group="School")
        assert sorted(d["uid"] for d in resp.context["documents"]) == ["d1", "d2", "d3"]
        assert {g["name"]: g["count"] for g in resp.context["group_rows"]} == {"School": 3}

    def test_dimensions_and_combine(self, conn):
        self._seed(conn)
        resp = self._list(conn, note_type="research", label="History")
        assert [d["uid"] for d in resp.context["documents"]] == ["d2"]
        assert resp.context["notebook_filter_active"] is True

    def test_sort_title_reorders_without_changing_the_set(self, conn):
        self._seed(conn)
        resp = self._list(conn, sort="title")
        assert [d["title"] for d in resp.context["documents"]] == ["Appendix", "Blank", "Essay", "Thesis"]

    def test_unfiltered_view_is_not_filter_active(self, conn):
        self._seed(conn)
        assert self._list(conn).context["notebook_filter_active"] is False

    def test_no_matches_gets_its_own_empty_state(self, conn):
        self._seed(conn)
        body = self._list(conn, note_type="nope").body.decode()
        assert "No documents match this filter" in body
        assert "No documents yet" not in body

    def test_rows_carry_their_navigation_target_and_leading_icon(self, conn):
        self._seed(conn)
        body = self._list(conn).body.decode()
        assert 'data-row-href="/notebook/d1"' in body
        assert '#icon-user' in body  # d1's note_type is "person"


class TestCreateDocument:
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
        resp = notebook_router.update_document_properties(
            "d1", title="Renamed", note_type="", note_type_new="", tags_labels=[],
            property_key=[], property_value=[], x_requested_with=None, conn=conn
        )
        assert resp.status_code == 303
        assert db.get_notebook_document(conn, "d1")["title"] == "Renamed"

    def test_update_title_blank_falls_back_to_untitled(self, conn):
        _document(conn, uid="d1", title="Something")
        notebook_router.update_document_properties(
            "d1", title="   ", note_type="", note_type_new="", tags_labels=[],
            property_key=[], property_value=[], x_requested_with=None, conn=conn
        )
        assert db.get_notebook_document(conn, "d1")["title"] == "Untitled"

    def test_update_title_missing_document_is_a_404_for_json(self, conn):
        resp = notebook_router.update_document_properties(
            "missing", title="X", note_type="", note_type_new="", tags_labels=[], x_requested_with="fetch", conn=conn
        )
        assert resp.status_code == 404

    def test_update_properties_sets_note_type_from_picked_radio(self, conn):
        _document(conn, uid="d1", note_type="notes")
        notebook_router.update_document_properties(
            "d1", title="D1", note_type="research", note_type_new="", tags_labels=[],
            property_key=[], property_value=[], conn=conn
        )
        assert db.get_notebook_document(conn, "d1")["note_type"] == "research"

    def test_update_properties_typed_note_type_wins_over_radio(self, conn):
        # Same "typed value always overrides the picked radio" rule as
        # routers/settings.py's _resolve_calendar_name -- see
        # _resolve_note_type's own docstring.
        _document(conn, uid="d1", note_type="notes")
        notebook_router.update_document_properties(
            "d1", title="D1", note_type="research", note_type_new="historiography", tags_labels=[],
            property_key=[], property_value=[], conn=conn
        )
        assert db.get_notebook_document(conn, "d1")["note_type"] == "historiography"

    def test_update_properties_blank_note_type_clears_an_existing_type(self, conn):
        # 2026-10-02 direct request ("allow 'No type' for notes") -- picking
        # the always-present "No type" sentinel radio submits a blank
        # note_type; that must actually clear a document's existing type,
        # not silently keep it (the previous "fall back to existing value"
        # behavior made "No type" permanently unreachable once any type was
        # set -- see _resolve_note_type's own docstring).
        _document(conn, uid="d1", note_type="wiki")
        notebook_router.update_document_properties(
            "d1", title="D1", note_type="", note_type_new="", tags_labels=[],
            property_key=[], property_value=[], conn=conn
        )
        assert db.get_notebook_document(conn, "d1")["note_type"] == ""

    def test_update_properties_sets_labels(self, conn):
        _document(conn, uid="d1", tags=["Old"])
        notebook_router.update_document_properties(
            "d1", title="D1", note_type="", note_type_new="",
            tags_labels=["University", "History"], property_key=[], property_value=[], conn=conn,
        )
        assert sorted(db.get_notebook_document(conn, "d1")["tags"]) == ["History", "University"]

    def test_properties_modal_has_labels_and_project_as_two_dropdowns_and_kind_as_a_dropdown(self, conn):
        _document(conn, uid="d1")
        body = notebook_router.document_properties_modal("d1", _bare_request(), conn=conn).body.decode()
        assert 'name="tags_labels"' in body and 'name="project"' in body and 'name="project_field"' in body
        assert "seg-btn" not in body and 'name="kind"' in body

    def test_update_properties_saves_the_project_beside_the_labels(self, conn):
        db.upsert_label_config(conn, {"name": "Thesis", "is_project": 1})
        _document(conn, uid="d1")
        notebook_router.update_document_properties(
            "d1", title="D1", note_type="", note_type_new="", tags_labels=["History"], project="Thesis", project_field="1",
            property_key=[], property_value=[], conn=conn,
        )
        assert sorted(db.get_notebook_document(conn, "d1")["tags"]) == ["History", "Thesis"]

    def test_update_properties_empty_labels_clears_them(self, conn):
        _document(conn, uid="d1", tags=["Old"])
        notebook_router.update_document_properties(
            "d1", title="D1", note_type="", note_type_new="", tags_labels=[],
            property_key=[], property_value=[], conn=conn
        )
        assert db.get_notebook_document(conn, "d1")["tags"] == []

    def test_properties_modal_renders_current_values(self, conn):
        _document(conn, uid="d1", title="Thesis Notes", note_type="research", tags=["University"])
        resp = notebook_router.document_properties_modal("d1", _bare_request("/notebook/d1/properties"), conn=conn)
        body = resp.body.decode()
        assert 'value="Thesis Notes"' in body
        assert "Document properties" in body

    def test_properties_modal_type_picker_is_usage_based_with_a_no_type_sentinel(self, conn):
        # 2026-10-02 direct request: the Type picker isn't a fixed starter
        # list -- "wiki" shouldn't be suggested if nothing uses it, and a
        # fresh document with no type yet must show "No type" rather than
        # whatever value happens to be first in the list.
        _document(conn, uid="d1", title="Untitled", note_type="")
        _document(conn, uid="d2", title="Other", note_type="wiki")
        resp = notebook_router.document_properties_modal("d1", _bare_request("/notebook/d1/properties"), conn=conn)
        body = resp.body.decode()
        assert 'value="wiki"' in body
        assert 'value=""' in body
        assert "No type" in body

    def test_properties_modal_type_options_carry_their_color_and_icon(self, conn):
        # 2026-10-02 direct request: note_type's look should be consistent
        # everywhere it renders, including the Type picker itself.
        _document(conn, uid="d1", note_type="person")
        _paint_type(conn, "person", "orange", "user")
        body = notebook_router.document_properties_modal("d1", _bare_request("/notebook/d1/properties"), conn=conn).body.decode()
        assert 'class="cell-tag cal-orange"' in body
        assert '#icon-user' in body

    def test_properties_modal_missing_uid_redirects_to_list(self, conn):
        resp = notebook_router.document_properties_modal("missing", _bare_request("/notebook/missing/properties"), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/notebook"

    def test_properties_modal_renders_existing_custom_properties(self, conn):
        _document(conn, uid="d1", title="Thesis Notes")
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "10.1/x"}])
        resp = notebook_router.document_properties_modal("d1", _bare_request("/notebook/d1/properties"), conn=conn)
        body = resp.body.decode()
        assert 'value="DOI"' in body
        assert 'value="10.1/x"' in body

    def test_properties_modal_property_key_picker_offers_keys_used_on_other_documents(self, conn):
        # 2026-10-02 direct request ("once a new properties is added, it
        # is available in the list") -- a key typed on one document must
        # be offered as a pick on a totally different document that has
        # never used it itself.
        _document(conn, uid="d1", title="Thesis Notes")
        _document(conn, uid="d2", title="Other")
        db.set_notebook_properties(conn, "d2", [{"key": "DOI", "value": "x"}])
        resp = notebook_router.document_properties_modal("d1", _bare_request("/notebook/d1/properties"), conn=conn)
        body = resp.body.decode()
        assert "notebook-property-key-radio" in body
        assert 'value="DOI"' in body

    def test_properties_modal_property_key_picker_context_matches_keys_in_use(self, conn):
        _document(conn, uid="d1")
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "x"}])
        resp = notebook_router.document_properties_modal("d1", _bare_request("/notebook/d1/properties"), conn=conn)
        assert resp.context["property_key_items"] == db.list_notebook_property_keys_in_use(conn)

    def test_update_document_properties_persists_custom_properties(self, conn):
        _document(conn, uid="d1")
        notebook_router.update_document_properties(
            "d1", title="D1", note_type="", note_type_new="", tags_labels=[],
            property_key=["DOI", "Institution"], property_value=["10.1/x", "UBB"], conn=conn,
        )
        props = db.get_notebook_document(conn, "d1")["properties"]
        assert [(p["key"], p["value"]) for p in props] == [("DOI", "10.1/x"), ("Institution", "UBB")]

    def test_update_document_properties_drops_a_blank_key_row(self, conn):
        # A blank Add-row left untouched (e.g. clicked "+" then Save
        # without typing a name) shouldn't persist as a nameless property.
        _document(conn, uid="d1")
        notebook_router.update_document_properties(
            "d1", title="D1", note_type="", note_type_new="", tags_labels=[],
            property_key=["", "DOI"], property_value=["", "x"], conn=conn,
        )
        props = db.get_notebook_document(conn, "d1")["properties"]
        assert [p["key"] for p in props] == ["DOI"]

    def test_update_document_properties_empty_submission_clears_existing(self, conn):
        _document(conn, uid="d1")
        db.set_notebook_properties(conn, "d1", [{"key": "DOI", "value": "x"}])
        notebook_router.update_document_properties(
            "d1", title="D1", note_type="", note_type_new="", tags_labels=[],
            property_key=[], property_value=[], conn=conn,
        )
        assert db.get_notebook_document(conn, "d1")["properties"] == []

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

    def test_rows_carry_the_same_type_look_as_the_browse_page(self, conn):
        # 2026-10-02 direct request: note_type's look should be consistent
        # everywhere it renders, not just the Browse page -- same
        # db.notebook_note_type_looks source.
        _document(conn, uid="d1", note_type="person", tags=["University"])
        _paint_type(conn, "person", "orange", "user")
        data = dashboard_router._render_notebook_list(conn, {"label_name": "University"})
        assert data["documents"][0]["type_icon"] == db.notebook_note_type_looks(conn)["person"]["icon"] == "user"
        assert data["documents"][0]["type_color"] == "orange"
