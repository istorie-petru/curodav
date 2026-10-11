"""Export and import of notes (Markdown), finance, citations and glossary through the Data & Maintenance import and export."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone

import pytest

from src import data_exchange, db, finance
from src.routers import export as export_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


class FakeUpload:
    def __init__(self, name: str, body: bytes):
        self.filename = name
        self.file = io.BytesIO(body)


def _import(conn, name, body, merge="1"):
    resp = export_router.import_auto(FakeUpload(name, body), merge=merge, conn=conn)
    return resp.headers["location"]


def _note(conn, uid, title, blocks, **extra):
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_notebook_document(conn, {"uid": uid, "title": title, "content_json": '{"blocks": []}', "document_type": "full",
                                       "note_type": "", "created_at": now, "updated_at": now, **extra})
    db.set_notebook_document_content(conn, uid, {"blocks": blocks})


def _account(conn, name="Cash"):
    clean, _ = finance.validate_account(conn, dict(name=name, type="cash", currency="RON", opening_balance="10", opening_date="2026-01-01"))
    return finance.save_account(conn, clean)


def test_notes_export_as_one_markdown_file_each_with_templates_in_their_own_folder(conn):
    _note(conn, "n1", "Plan", [{"type": "paragraph", "data": {"text": "Hello <b>there</b>"}}], note_type="wiki")
    _note(conn, "t1", "Person template", [], is_template=1)
    resp = export_router.download_selective(data_type="notes", conn=conn)
    bundle = zipfile.ZipFile(io.BytesIO(resp.body))
    assert sorted(bundle.namelist()) == ["Notes/Plan.md", "Templates/Person template.md"]
    text = bundle.read("Notes/Plan.md").decode()
    assert 'title: "Plan"' in text and "Hello **there**" in text


def test_a_markdown_zip_imports_back_as_notes_and_templates(conn):
    _note(conn, "n1", "Plan", [{"type": "header", "data": {"text": "Goals", "level": 2}}], note_type="wiki", tags=["Work"])
    _note(conn, "t1", "Template", [], is_template=1)
    body = export_router.download_selective(data_type="notes", conn=conn).body
    db.purge_all_data(conn)
    location = _import(conn, "notes.zip", body)
    assert "Imported%202%20notes" in location
    plan = db.get_notebook_document(conn, "n1")
    assert plan["note_type"] == "wiki" and plan["tags"] == ["Work"]
    assert db.get_notebook_document_content(conn, "n1")["blocks"][0]["data"]["text"] == "Goals"
    assert db.get_notebook_document(conn, "t1")["is_template"] == 1


def test_a_single_markdown_file_becomes_a_note_titled_by_its_first_heading(conn):
    _import(conn, "ideas.md", b"# Big idea\n\nSome *text*\n")
    [doc] = db.list_notebook_documents(conn)
    assert doc["title"] == "Big idea"
    assert db.get_notebook_document_content(conn, doc["uid"])["blocks"][0]["data"]["text"] == "Some <i>text</i>"


def test_importing_without_merge_leaves_an_existing_note_alone(conn):
    _note(conn, "n1", "Mine", [{"type": "paragraph", "data": {"text": "keep"}}])
    _import(conn, "x.md", b"---\nuid: n1\ntitle: Other\n---\nreplaced\n", merge="")
    assert db.get_notebook_document(conn, "n1")["title"] == "Mine"
    _import(conn, "x.md", b"---\nuid: n1\ntitle: Other\n---\nreplaced\n", merge="1")
    assert db.get_notebook_document(conn, "n1")["title"] == "Other"


def test_finance_exports_and_imports_accounts_then_transactions(conn, tmp_path):
    a = _account(conn)
    clean, _ = finance.validate_transaction(conn, dict(date="2026-02-01", type="expense", amount="5.50", account_uid=a,
                                                      description="Coffee", label="Food", tags=["out"]))
    finance.save_transaction(conn, clean)
    bundle = zipfile.ZipFile(io.BytesIO(export_router.download_selective(data_type="finance", conn=conn).body))
    with db.connect(tmp_path / "other.sqlite") as other:
        assert "Imported 1 account." in export_router._import_one(other, "accounts.csv", bundle.read("finance/accounts.csv"), False)
        note = export_router._import_one(other, "transactions.csv", bundle.read("finance/transactions.csv"), False)
        assert "Imported 1 transaction." in note
        row = finance.list_transactions(other)[0]
        assert row["description"] == "Coffee" and row["amount"] == 550 and row["label"] == "Food" and row["tags"] == ["out"]


def test_a_finance_zip_imports_in_one_go(conn, tmp_path):
    a = _account(conn)
    clean, _ = finance.validate_transaction(conn, dict(date="2026-02-01", type="income", amount="9", account_uid=a))
    finance.save_transaction(conn, clean)
    body = export_router.download_selective(data_type="finance", conn=conn).body
    with db.connect(tmp_path / "other.sqlite") as other:
        export_router.import_auto(FakeUpload("finance.zip", body), merge="1", conn=other)
        assert len(finance.list_accounts(other)) == 1 and len(finance.list_transactions(other)) == 1


def test_importing_transactions_without_merge_skips_exact_duplicates(conn):
    a = _account(conn)
    clean, _ = finance.validate_transaction(conn, dict(date="2026-02-01", type="expense", amount="5", account_uid=a, description="Tea"))
    finance.save_transaction(conn, clean)
    body = data_exchange.transactions_csv(conn)
    assert export_router._import_one(conn, "t.csv", body, True).startswith("Imported 0 transactions.")
    assert export_router._import_one(conn, "t.csv", body, False).startswith("Imported 1 transaction.")


def test_citations_and_glossary_round_trip_through_csv(conn):
    db.upsert_citation(conn, {"uid": "c1", "type": "book", "title": "Origin", "authors": [{"family": "Darwin", "given": "Charles"}], "year": "1859"})
    db.upsert_glossary_term(conn, {"uid": "g1", "term": "Entropy", "definition": "Disorder"})
    cites = export_router.download_selective(data_type="citations", conn=conn).body
    terms = export_router.download_selective(data_type="glossary", conn=conn).body
    db.purge_all_data(conn)
    assert "Imported 1 citation." in export_router._import_one(conn, "citations.csv", cites, False)
    assert "Imported 1 glossary term." in export_router._import_one(conn, "glossary.csv", terms, False)
    assert db.get_citation(conn, "c1")["authors"] == [{"family": "Darwin", "given": "Charles"}]
    assert db.list_glossary_terms(conn)[0]["definition"] == "Disorder"


def test_an_unknown_file_is_rejected_with_the_list_of_supported_types(conn):
    location = _import(conn, "mystery.bin", b"just text")
    assert "error" in location and "zip" in location.lower()


def test_the_import_and_export_dialogs_list_what_can_be_imported_and_exported(conn):
    from starlette.requests import Request
    request = Request({"type": "http", "method": "GET", "path": "/export/modal", "query_string": b"", "scheme": "http",
                       "server": ("testserver", 80), "root_path": "", "headers": []})
    for body in (export_router.import_modal(request).body.decode(), export_router.export_modal(request, conn=conn).body.decode()):
        assert "Supported data" in body and "Finance transactions" in body and "Notes and templates" in body
    assert 'value="notes"' in export_router.export_modal(request, conn=conn).body.decode()

