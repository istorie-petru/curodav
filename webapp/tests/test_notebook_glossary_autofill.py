"""The Glossary sidebar's Auto-fill button attaches every term found in the saved document."""

from __future__ import annotations

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


def _doc(conn, text):
    now = datetime.now(timezone.utc).isoformat()
    content = {"blocks": [{"type": "paragraph", "data": {"text": text}}]}
    db.upsert_notebook_document(conn, {"uid": "d1", "title": "Doc", "content_json": json.dumps(content), "document_type": "full",
                                       "note_type": "", "created_at": now, "updated_at": now, "tags": []})


def _terms(conn):
    return sorted(t["term"] for t in db.list_notebook_glossary_terms(conn, "d1"))


def test_autofill_attaches_every_term_found_and_nothing_else(conn):
    db.upsert_glossary_term(conn, {"term": "Hoplite", "definition": ""})
    db.upsert_glossary_term(conn, {"term": "Trireme", "definition": ""})
    db.upsert_glossary_term(conn, {"term": "Agora", "definition": ""})
    _doc(conn, "A hoplite and a Trireme met.")
    result = db.autofill_notebook_glossary_terms(conn, "d1")
    assert sorted(result["added"]) == ["Hoplite", "Trireme"] and result["restored"] == 0
    assert _terms(conn) == ["Hoplite", "Trireme"]


def test_autofill_is_idempotent_and_keeps_manual_terms(conn):
    uid = db.upsert_glossary_term(conn, {"term": "Hoplite", "definition": ""})
    manual = db.upsert_glossary_term(conn, {"term": "Agora", "definition": ""})
    _doc(conn, "A hoplite.")
    db.set_notebook_glossary_terms(conn, "d1", [manual])
    db.autofill_notebook_glossary_terms(conn, "d1")
    assert db.autofill_notebook_glossary_terms(conn, "d1")["added"] == []
    assert _terms(conn) == ["Agora", "Hoplite"]


def test_autofill_brings_back_a_term_the_user_removed(conn):
    uid = db.upsert_glossary_term(conn, {"term": "Hoplite", "definition": ""})
    _doc(conn, "A hoplite.")
    db.autofill_notebook_glossary_terms(conn, "d1")
    db.set_notebook_glossary_terms(conn, "d1", [])
    assert _terms(conn) == []
    result = db.autofill_notebook_glossary_terms(conn, "d1")
    assert result == {"added": ["Hoplite"], "restored": 1}
    assert db.list_notebook_glossary_terms(conn, "d1")[0]["term"] == "Hoplite"


def test_the_autofill_route_reports_what_it_added(conn):
    db.upsert_glossary_term(conn, {"term": "Hoplite", "definition": "A soldier"})
    _doc(conn, "hoplite")
    resp = notebook_router.autofill_document_glossary("d1", conn=conn)
    assert json.loads(resp.body)["added"] == ["Hoplite"]
    assert notebook_router.autofill_document_glossary("missing", conn=conn).status_code == 404
