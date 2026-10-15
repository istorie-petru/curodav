"""Glossary (roadmap-mvp-to-full-product-checklist's "Glossary" section,
2026-10-03, "almost the same as citations") -- core slice coverage: db.py's
glossary_terms CRUD + search, routers/notebook.py's glossary_router (the
library). No per-document attach (unlike citations) -- not part of the
roadmap's document-sidebar section list."""

from __future__ import annotations

import pytest

from starlette.requests import Request

from src import db
from src.routers import export as export_router
from src.routers import notebook as notebook_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _bare_request(path="/notebook/glossary", query_string: bytes = b""):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": query_string,
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )


def _term(conn, uid="t1", term="Feudalism", **overrides):
    row = {"uid": uid, "term": term, "definition": "A medieval social system."}
    row.update(overrides)
    db.upsert_glossary_term(conn, row)
    return db.get_glossary_term(conn, uid)


def _document(conn, uid="d1", title="My Document", **overrides):
    import datetime as _dt
    row = {
        "uid": uid, "title": title, "content_json": '{"blocks": []}',
        "document_type": "full", "note_type": "notes",
        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    row.update(overrides)
    db.upsert_notebook_document(conn, row)
    return db.get_notebook_document(conn, uid)


def _citation(conn, uid="c1", title="A History of Something", **overrides):
    """Same helper as test_notebook_citations.py's own copy -- kept
    duplicated rather than imported cross-module, matching this suite's
    existing per-file fixture-helper convention."""
    row = {
        "uid": uid, "type": "book", "title": title,
        "authors": [{"family": "Bloch", "given": "Marc"}],
        "year": "1924", "container_title": "", "doi": "", "url": "",
    }
    row.update(overrides)
    db.upsert_citation(conn, row)
    return db.get_citation(conn, uid)


class TestGlossaryCrud:
    def test_upsert_then_get(self, conn):
        _term(conn)
        t = db.get_glossary_term(conn, "t1")
        assert t["term"] == "Feudalism"
        assert t["definition"] == "A medieval social system."

    def test_list_sorted_by_term(self, conn):
        _term(conn, uid="t1", term="Zealotry")
        _term(conn, uid="t2", term="Appeasement")
        terms = [t["term"] for t in db.list_glossary_terms(conn)]
        assert terms == ["Appeasement", "Zealotry"]

    def test_update_preserves_uid(self, conn):
        _term(conn)
        db.upsert_glossary_term(conn, {"uid": "t1", "term": "Renamed", "definition": ""})
        t = db.get_glossary_term(conn, "t1")
        assert t["term"] == "Renamed"
        assert len(db.list_glossary_terms(conn)) == 1

    def test_delete_removes_term(self, conn):
        _term(conn)
        db.delete_glossary_term(conn, "t1")
        assert db.get_glossary_term(conn, "t1") is None

    def test_search_matches_term_or_definition_case_insensitively(self, conn):
        _term(conn, uid="t1", term="Feudalism", definition="A medieval social system.")
        _term(conn, uid="t2", term="Capitalism", definition="An economic system.")
        assert [t["uid"] for t in db.list_glossary_terms(conn, "FEUD")] == ["t1"]
        assert [t["uid"] for t in db.list_glossary_terms(conn, "economic")] == ["t2"]

    def test_blank_search_returns_everything(self, conn):
        _term(conn, uid="t1", term="A")
        _term(conn, uid="t2", term="B")
        assert len(db.list_glossary_terms(conn, "")) == 2


class TestGlossaryLibraryRouter:
    def test_library_page_lists_terms(self, conn):
        _term(conn, term="Mercantilism")
        resp = notebook_router.glossary_library(_bare_request(), q="", conn=conn)
        assert "Mercantilism" in resp.body.decode()

    def test_library_page_filters_by_q(self, conn):
        _term(conn, uid="t1", term="Mercantilism")
        _term(conn, uid="t2", term="Socialism")
        resp = notebook_router.glossary_library(_bare_request(), q="Merc", conn=conn)
        assert [e["uid"] for g in resp.context["groups"] for e in g["entries"]] == ["t1"]

    def test_create_term_then_appears_in_library(self, conn):
        resp = notebook_router.create_glossary_term(
            term="New Term", definition="A new definition.", section_title=[], section_body=[], x_requested_with=None, conn=conn
        )
        assert resp.status_code == 303
        terms = db.list_glossary_terms(conn)
        assert len(terms) == 1
        assert terms[0]["term"] == "New Term"

    def test_create_term_blank_term_is_a_noop(self, conn):
        notebook_router.create_glossary_term(term="   ", definition="", x_requested_with=None, conn=conn)
        assert db.list_glossary_terms(conn) == []

    def test_update_term(self, conn):
        _term(conn)
        notebook_router.update_glossary_term(
            "t1", term="Updated Term", definition="Updated definition.", section_title=[], section_body=[], x_requested_with=None, conn=conn
        )
        t = db.get_glossary_term(conn, "t1")
        assert t["term"] == "Updated Term"
        assert t["definition"] == "Updated definition."

    def test_delete_term_route(self, conn):
        _term(conn)
        notebook_router.delete_glossary_term("t1", x_requested_with=None, conn=conn)
        assert db.get_glossary_term(conn, "t1") is None

    def test_no_match_still_renders_a_distinct_empty_state(self, conn):
        _term(conn, term="Mercantilism")
        resp = notebook_router.glossary_library(_bare_request(), q="nonexistent", conn=conn)
        assert resp.context["groups"] == []
        assert 'No entries match' in resp.body.decode()


class TestNotebookGlossaryTerms:
    """Per-document attach (2026-10-03 direct follow-up, "add a sidebar
    tab") -- notebook_glossary_terms, same shape as TestNotebookCitations
    in test_notebook_citations.py."""

    def test_set_then_list_round_trips_in_order(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="First")
        _term(conn, uid="t2", term="Second")
        db.set_notebook_glossary_terms(conn, "d1", ["t2", "t1"])
        attached = db.list_notebook_glossary_terms(conn, "d1")
        assert [t["uid"] for t in attached] == ["t2", "t1"]

    def test_set_replaces_whole_list(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1")
        _term(conn, uid="t2", term="Second")
        db.set_notebook_glossary_terms(conn, "d1", ["t1"])
        db.set_notebook_glossary_terms(conn, "d1", ["t2"])
        assert [t["uid"] for t in db.list_notebook_glossary_terms(conn, "d1")] == ["t2"]

    def test_a_term_can_attach_to_several_documents(self, conn):
        _document(conn, uid="d1")
        _document(conn, uid="d2")
        _term(conn, uid="t1")
        db.set_notebook_glossary_terms(conn, "d1", ["t1"])
        db.set_notebook_glossary_terms(conn, "d2", ["t1"])
        assert [t["uid"] for t in db.list_notebook_glossary_terms(conn, "d1")] == ["t1"]
        assert [t["uid"] for t in db.list_notebook_glossary_terms(conn, "d2")] == ["t1"]

    def test_delete_term_removes_its_attachments(self, conn):
        _document(conn, uid="d1")
        _term(conn)
        db.set_notebook_glossary_terms(conn, "d1", ["t1"])
        db.delete_glossary_term(conn, "t1")
        assert db.list_notebook_glossary_terms(conn, "d1") == []


class TestGlossaryAttachRoutes:
    def test_attach_modal_lists_existing_and_attached_terms(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="Attachable Term")
        db.set_notebook_glossary_terms(conn, "d1", ["t1"])
        req = _bare_request("/notebook/d1/glossary")
        resp = notebook_router.document_glossary_modal("d1", req, conn=conn)
        assert resp.context["attached_uids"] == ["t1"]
        assert any(i["uid"] == "t1" for i in resp.context["term_items"])

    def test_update_glossary_sets_attached_terms(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1")
        _term(conn, uid="t2", term="Second")
        resp = notebook_router.update_document_glossary(
            "d1", term_uids=["t1", "t2"], x_requested_with=None, conn=conn
        )
        assert resp.status_code == 303
        assert {t["uid"] for t in db.list_notebook_glossary_terms(conn, "d1")} == {"t1", "t2"}

    def test_document_page_carries_attached_terms(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="Rendered Term")
        db.set_notebook_glossary_terms(conn, "d1", ["t1"])
        req = _bare_request("/notebook/d1")
        body = notebook_router.document_page("d1", req, conn=conn).body.decode()
        assert "Rendered Term" in body and "/notebook/d1/glossary" in body

    def test_glossary_route_missing_document_redirects(self, conn):
        resp = notebook_router.update_document_glossary(
            "missing", term_uids=["t1"], x_requested_with=None, conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/notebook"


class TestGlossaryTermReferences:
    """A term's own "further reading" list (roadmap item F, 2026-10-03) --
    glossary_term_references, owned by the term rather than a document (the
    inverse direction of TestNotebookGlossaryTerms above)."""

    def test_set_then_list_round_trips_in_order_with_resolved_names(self, conn):
        _document(conn, uid="d1", title="Notebook Doc")
        _citation(conn, uid="c1", title="Citation Title")
        _term(conn, uid="t1")
        db.set_glossary_term_references(conn, "t1", [("citation", "c1"), ("notebook", "d1")])
        refs = db.list_glossary_term_references(conn, "t1")
        assert [(r["ref_type"], r["ref_uid"]) for r in refs] == [("citation", "c1"), ("notebook", "d1")]
        assert refs[0]["name"].startswith("Bloch, M. (1924)")
        assert refs[1]["name"] == "Notebook Doc"

    def test_set_replaces_whole_list(self, conn):
        _document(conn, uid="d1")
        _document(conn, uid="d2")
        _term(conn, uid="t1")
        db.set_glossary_term_references(conn, "t1", [("notebook", "d1")])
        db.set_glossary_term_references(conn, "t1", [("notebook", "d2")])
        assert [r["ref_uid"] for r in db.list_glossary_term_references(conn, "t1")] == ["d2"]

    def test_invalid_ref_type_is_dropped(self, conn):
        _term(conn, uid="t1")
        db.set_glossary_term_references(conn, "t1", [("bogus", "x1")])
        assert db.list_glossary_term_references(conn, "t1") == []

    def test_a_reference_missing_its_target_is_silently_skipped(self, conn):
        """A term_uid/ref_uid pair survives in the join table even if its
        target is gone some other way than the cascading deletes below
        (e.g. restoring an old backup after the target was later deleted
        elsewhere) -- list_glossary_term_references has nothing to resolve
        a name from, so it drops the row rather than rendering broken."""
        _term(conn, uid="t1")
        db.attach_glossary_term_reference(conn, "t1", "notebook", "missing-doc")
        assert db.list_glossary_term_references(conn, "t1") == []

    def test_delete_term_removes_its_references(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1")
        db.set_glossary_term_references(conn, "t1", [("notebook", "d1")])
        db.delete_glossary_term(conn, "t1")
        assert db.list_glossary_term_references(conn, "t1") == []

    def test_delete_citation_removes_references_to_it(self, conn):
        _citation(conn, uid="c1")
        _term(conn, uid="t1")
        db.set_glossary_term_references(conn, "t1", [("citation", "c1")])
        db.delete_citation(conn, "c1")
        assert db.list_glossary_term_references(conn, "t1") == []

    def test_delete_notebook_document_removes_references_to_it(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1")
        db.set_glossary_term_references(conn, "t1", [("notebook", "d1")])
        db.delete_notebook_document(conn, "d1")
        assert db.list_glossary_term_references(conn, "t1") == []

    def test_create_term_route_sets_references(self, conn):
        _document(conn, uid="d1", title="My Doc")
        _citation(conn, uid="c1")
        resp = notebook_router.create_glossary_term(
            term="New Term", definition="", reference_keys=["notebook:d1", "citation:c1"], section_title=[], section_body=[],
            x_requested_with=None, conn=conn,
        )
        new_uid = [t for t in db.list_glossary_terms(conn) if t["term"] == "New Term"][0]["uid"]
        assert [r["ref_uid"] for r in db.list_glossary_term_references(conn, new_uid)] == ["c1"]

    def test_update_term_route_sets_references(self, conn):
        _term(conn, uid="t1")
        _citation(conn, uid="c1")
        notebook_router.update_glossary_term(
            "t1", term="Feudalism", definition="", reference_keys=["citation:c1"], section_title=[], section_body=[],
            x_requested_with=None, conn=conn,
        )
        assert [r["ref_uid"] for r in db.list_glossary_term_references(conn, "t1")] == ["c1"]

    def test_edit_modal_context_carries_reference_items_and_selection(self, conn):
        _document(conn, uid="d1", title="Doc One")
        _citation(conn, uid="c1")
        _term(conn, uid="t1")
        db.set_glossary_term_references(conn, "t1", [("notebook", "d1"), ("citation", "c1")])
        resp = notebook_router.edit_glossary_term_modal("t1", _bare_request(), conn=conn)
        assert resp.context["selected_reference_keys"] == ["citation:c1"]
        assert [i["uid"] for i in resp.context["reference_items"]] == ["citation:c1"]
        assert "ms_search_always" not in resp.body.decode() and 'aria-label="Search references"' in resp.body.decode()

    def test_library_page_shows_reference_names(self, conn):
        _document(conn, uid="d1", title="Further Reading Doc")
        _citation(conn, uid="c1")
        _term(conn, uid="t1", term="Mercantilism")
        db.set_glossary_term_references(conn, "t1", [("notebook", "d1"), ("citation", "c1")])
        body = notebook_router.entry_view_modal("t1", _bare_request(), conn=conn).body.decode()
        assert "Further reading" in body
        assert "Further Reading Doc" not in body


class TestBackupRoundTrip:
    def test_terms_survive_backup_restore(self, conn, tmp_path):
        _term(conn, term="Backed Up Term")
        payload = export_router.build_backup_payload(conn)
        assert payload["glossary_terms"][0]["term"] == "Backed Up Term"

        with db.connect(tmp_path / "restored.sqlite") as fresh:
            export_router.restore_backup_payload(fresh, payload)
            assert db.get_glossary_term(fresh, "t1")["term"] == "Backed Up Term"

    def test_attachments_survive_backup_restore(self, conn, tmp_path):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="Backed Up Term")
        db.set_notebook_glossary_terms(conn, "d1", ["t1"])
        payload = export_router.build_backup_payload(conn)
        assert payload["notebook_glossary_terms"] == [
            {
                "notebook_uid": "d1", "term_uid": "t1", "position": 0,
                "created_at": payload["notebook_glossary_terms"][0]["created_at"], "auto": 0,
            }
        ]

        with db.connect(tmp_path / "restored.sqlite") as fresh:
            export_router.restore_backup_payload(fresh, payload)
            assert [t["uid"] for t in db.list_notebook_glossary_terms(fresh, "d1")] == ["t1"]

    def test_term_references_survive_backup_restore(self, conn, tmp_path):
        _document(conn, uid="d1", title="Referenced Doc")
        _citation(conn, uid="c1")
        _term(conn, uid="t1", term="Backed Up Term")
        db.set_glossary_term_references(conn, "t1", [("notebook", "d1"), ("citation", "c1")])
        payload = export_router.build_backup_payload(conn)
        assert {(r["ref_type"], r["ref_uid"]) for r in payload["glossary_term_references"]} == {
            ("notebook", "d1"), ("citation", "c1"),
        }

        with db.connect(tmp_path / "restored.sqlite") as fresh:
            export_router.restore_backup_payload(fresh, payload)
            refs = db.list_glossary_term_references(fresh, "t1")
            assert {(r["ref_type"], r["ref_uid"]) for r in refs} == {("notebook", "d1"), ("citation", "c1")}


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "data": {"text": text}}


class TestGlossaryAutoDetect:
    """Roadmap item H (session 7) -- content-save text scan auto-attaches/
    auto-removes glossary term references, without disturbing anything the
    attach modal set manually."""

    def test_save_content_auto_attaches_detected_term(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="Feudalism")
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("The feudalism system shaped Europe.")]})
        attached = db.list_notebook_glossary_terms(conn, "d1")
        assert [t["uid"] for t in attached] == ["t1"]
        assert attached[0]["auto"] == 1

    def test_no_match_leaves_nothing_attached(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="Feudalism")
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("Nothing relevant here.")]})
        assert db.list_notebook_glossary_terms(conn, "d1") == []

    def test_match_is_case_insensitive(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="feudalism")
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("FEUDALISM shaped Europe.")]})
        assert [t["uid"] for t in db.list_notebook_glossary_terms(conn, "d1")] == ["t1"]

    def test_match_respects_word_boundaries(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="Cat")
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("A whole category of things.")]})
        assert db.list_notebook_glossary_terms(conn, "d1") == []

    def test_html_tag_stripping_does_not_fuse_adjacent_words(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="wikilink")
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("<b>wiki</b>link in the body.")]})
        assert db.list_notebook_glossary_terms(conn, "d1") == []

    def test_code_block_text_is_not_scanned(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="Feudalism")
        db.set_notebook_document_content(
            conn, "d1", {"blocks": [{"type": "code", "data": {"code": "feudalism = True"}}]}
        )
        assert db.list_notebook_glossary_terms(conn, "d1") == []

    def test_auto_attached_term_removed_when_text_changes(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="Feudalism")
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("Feudalism shaped Europe.")]})
        assert len(db.list_notebook_glossary_terms(conn, "d1")) == 1
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("Something unrelated now.")]})
        assert db.list_notebook_glossary_terms(conn, "d1") == []

    def test_manual_attachment_survives_text_without_the_term(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="Feudalism")
        db.set_notebook_glossary_terms(conn, "d1", ["t1"])
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("Nothing relevant here.")]})
        attached = db.list_notebook_glossary_terms(conn, "d1")
        assert [t["uid"] for t in attached] == ["t1"]
        assert attached[0]["auto"] == 0

    def test_manual_removal_of_auto_match_is_not_resurrected_on_resave(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="Feudalism")
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("Feudalism shaped Europe.")]})
        assert len(db.list_notebook_glossary_terms(conn, "d1")) == 1
        # Attach modal submitted with nothing checked -- the user is
        # overriding a false-positive match.
        db.set_notebook_glossary_terms(conn, "d1", [])
        assert db.list_notebook_glossary_terms(conn, "d1") == []
        # Re-saving the same content (term still literally present) must
        # not resurrect the override.
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("Feudalism shaped Europe.")]})
        assert db.list_notebook_glossary_terms(conn, "d1") == []

    def test_re_adding_an_excluded_term_via_the_modal_clears_the_override(self, conn):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="Feudalism")
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("Feudalism shaped Europe.")]})
        db.set_notebook_glossary_terms(conn, "d1", [])  # override it
        db.set_notebook_glossary_terms(conn, "d1", ["t1"])  # user re-checks it manually
        attached = db.list_notebook_glossary_terms(conn, "d1")
        assert [t["uid"] for t in attached] == ["t1"]
        assert attached[0]["auto"] == 0  # re-added manually, not auto
        # Removing it again afterwards must still create a fresh override.
        db.set_notebook_glossary_terms(conn, "d1", [])
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("Feudalism shaped Europe.")]})
        assert db.list_notebook_glossary_terms(conn, "d1") == []

    def test_excluded_terms_survive_backup_restore(self, conn, tmp_path):
        _document(conn, uid="d1")
        _term(conn, uid="t1", term="Feudalism")
        db.set_notebook_document_content(conn, "d1", {"blocks": [_paragraph("Feudalism shaped Europe.")]})
        db.set_notebook_glossary_terms(conn, "d1", [])
        payload = export_router.build_backup_payload(conn)
        assert [r["term_uid"] for r in payload["notebook_glossary_excluded_terms"]] == ["t1"]

        with db.connect(tmp_path / "restored.sqlite") as fresh:
            export_router.restore_backup_payload(fresh, payload)
            db.set_notebook_document_content(fresh, "d1", {"blocks": [_paragraph("Feudalism shaped Europe.")]})
            assert db.list_notebook_glossary_terms(fresh, "d1") == []


class TestGlossarySections:
    def test_sections_are_saved_in_order_and_blank_ones_dropped(self, conn):
        _term(conn)
        notebook_router.update_glossary_term(
            "t1", term="Feudalism", definition="", section_title=["Example", "", "Remember"],
            section_body=["A lord and a vassal.", "", "Fealty"], reference_keys=[], x_requested_with=None, conn=conn,
        )
        assert [(r["title"], r["body"]) for r in db.list_glossary_sections(conn, "t1")] == [("Example", "A lord and a vassal."), ("Remember", "Fealty")]

    def test_sections_are_removed_with_their_term(self, conn):
        _term(conn)
        db.set_glossary_sections(conn, "t1", [("Example", "x")])
        db.delete_glossary_term(conn, "t1")
        assert db.list_glossary_sections(conn, "t1") == []

    def test_the_edit_modal_and_the_view_modal_list_sections(self, conn):
        _term(conn)
        db.set_glossary_sections(conn, "t1", [("Example", "Shown in both modals")])
        assert "Shown in both modals" in notebook_router.edit_glossary_term_modal("t1", _bare_request(), conn=conn).body.decode()
        assert "Shown in both modals" in notebook_router.entry_view_modal("t1", _bare_request(), conn=conn).body.decode()

