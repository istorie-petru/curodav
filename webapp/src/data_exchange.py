"""Notes (Markdown), finance, citations and glossary as export files, and their importers (Settings > Data & Maintenance).

Used by routers/export.py; CSV shapes here are what its content sniffing recognises.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone

from . import db, finance, finance_stats, notebook_markdown

ACCOUNT_COLUMNS = ["name", "type", "currency", "opening_balance", "opening_date"]
CITATION_COLUMNS = ["uid", "type", "title", "authors", "year", "container title", "doi", "url"]
GLOSSARY_COLUMNS = ["uid", "term", "definition"]
EXTRA_CSV_SHAPES: dict[str, list[str]] = {
    "finance accounts": ACCOUNT_COLUMNS,
    "finance transactions": finance_stats.CSV_COLUMNS,
    "citations": CITATION_COLUMNS,
    "glossary": GLOSSARY_COLUMNS,
}


def _csv(header: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", title).strip(" .") or "Untitled"


# Export

def notes_files(conn) -> list[tuple[str, bytes]]:
    """One .md file per note (templates in their own folder), named by title."""
    files, used = [], set()
    for doc in db.list_notebook_documents(conn, scope="all"):
        folder = "Templates" if doc["is_template"] else "Notes"
        name = f"{folder}/{_safe_name(doc['title'])}.md"
        if name.lower() in used:
            name = f"{folder}/{_safe_name(doc['title'])} ({doc['uid'][:6]}).md"
        used.add(name.lower())
        blocks = db.inline_content_images(conn, db.get_notebook_document_content(conn, doc["uid"]) or {}).get("blocks", [])
        files.append((name, notebook_markdown.note_to_markdown(doc, blocks).encode("utf-8")))
    return files


def accounts_csv(conn) -> bytes:
    rows = [[a["name"], a["type"], a["currency"], finance_stats.amount_input(a["opening_balance"]), a["opening_date"]]
            for a in finance.list_accounts(conn)]
    return _csv(ACCOUNT_COLUMNS, rows)


def transactions_csv(conn) -> bytes:
    return finance_stats.to_csv(finance.list_transactions(conn)).encode("utf-8")


def finance_files(conn) -> list[tuple[str, bytes]]:
    return [("finance/accounts.csv", accounts_csv(conn)), ("finance/transactions.csv", transactions_csv(conn))]


def _author_text(authors: list[dict]) -> str:
    return "; ".join(f"{a.get('family', '')}, {a.get('given', '')}".strip(", ") for a in authors)


def citations_csv(conn) -> bytes:
    rows = [[c["uid"], c["type"], c["title"], _author_text(c.get("authors") or []), c["year"], c["container_title"], c["doi"], c["url"]]
            for c in db.list_citations(conn)]
    return _csv(CITATION_COLUMNS, rows)


def glossary_csv(conn) -> bytes:
    return _csv(GLOSSARY_COLUMNS, [[t["uid"], t["term"], t["definition"]] for t in db.list_glossary_terms(conn)])


# Import

def import_note(conn, text: str, filename: str, skip_existing: bool) -> bool:
    note = notebook_markdown.parse_note(text, filename)
    uid = note["uid"] or str(uuid.uuid4())
    if skip_existing and db.get_notebook_document(conn, uid) is not None:
        return False
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_notebook_document(conn, {
        "uid": uid, "title": note["title"], "content_json": json.dumps({"blocks": note["blocks"]}),
        "document_type": "full", "note_type": note["note_type"], "is_template": note["is_template"],
        "created_at": now, "updated_at": now, "tags": note["tags"], "properties": note["properties"],
    })
    db.set_notebook_document_content(conn, uid, {"blocks": note["blocks"]})
    return True


def _rows(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in reader]


def import_accounts_csv(conn, text: str, skip_existing: bool) -> tuple[int, list[str]]:
    added, problems = 0, []
    for number, row in enumerate(_rows(text), start=2):
        existing = conn.execute("SELECT uid FROM finance_accounts WHERE name = ? COLLATE NOCASE", (row["name"],)).fetchone()
        if existing and skip_existing:
            continue
        clean, error = finance.validate_account(conn, row, existing["uid"] if existing else None)
        if error:
            problems.append(f"Line {number}: {error['message']}")
            continue
        finance.save_account(conn, clean, existing["uid"] if existing else None)
        added += 1
    return added, problems


def import_transactions_csv(conn, text: str, skip_existing: bool) -> tuple[int, list[str]]:
    rows, problems = finance_stats.parse_csv(text)
    if skip_existing:
        have = {(t["date"], t["description"], t["account_name"], t["type"], t["amount"]) for t in finance.list_transactions(conn)}
        rows = [r for r in rows if (r["date"], r["description"], r["account"], r["type"], r["amount"]) not in have]
    created, more = finance.import_rows(conn, rows)
    return created, problems + more


def _authors(text: str) -> list[dict]:
    people = []
    for part in (p.strip() for p in text.split(";") if p.strip()):
        family, _, given = part.partition(",")
        people.append({"family": family.strip(), "given": given.strip()})
    return people


def import_citations_csv(conn, text: str, skip_existing: bool) -> int:
    added = 0
    for row in _rows(text):
        if skip_existing and row.get("uid") and db.get_citation(conn, row["uid"]) is not None:
            continue
        db.upsert_citation(conn, {
            "uid": row.get("uid") or None, "type": row.get("type") if row.get("type") in dict(db.CITATION_TYPES) else "other",
            "title": row["title"], "authors": _authors(row.get("authors", "")), "year": row.get("year", ""),
            "container_title": row.get("container title", ""), "doi": row.get("doi", ""), "url": row.get("url", ""),
        })
        added += 1
    return added


def import_glossary_csv(conn, text: str, skip_existing: bool) -> int:
    added = 0
    for row in _rows(text):
        existing = conn.execute("SELECT uid FROM glossary_terms WHERE uid = ?", (row.get("uid", ""),)).fetchone() if row.get("uid") else None
        if existing and skip_existing:
            continue
        db.upsert_glossary_term(conn, {"uid": row.get("uid") or None, "term": row["term"], "definition": row.get("definition", "")})
        added += 1
    return added


# Flat backup rows: join tables that belong to no single owner, exported under their own keys.

def object_label_rows(conn) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT object_type, object_id, label_name FROM object_labels").fetchall()
    return [dict(r) for r in rows]


def notebook_image_rows(conn) -> list[dict]:
    """Every stored figure picture, base64 so the JSON backup carries them."""
    import base64

    return [
        {"id": r["id"], "mime": r["mime"], "data_b64": base64.b64encode(r["data"]).decode("ascii")}
        for r in conn.execute("SELECT id, mime, data FROM notebook_images").fetchall()
    ]


def notebook_citation_rows(conn) -> list[dict[str, Any]]:
    """Flat join rows (notebook_uid, citation_uid, position, created_at) --
    same "separate flat export key, not nested under one owning parent"
    treatment as object_labels above, since a citation can be attached to
    many documents (not a one-document-owns-it relationship like
    properties/tags)."""
    rows = conn.execute(
        "SELECT notebook_uid, citation_uid, position, created_at FROM notebook_citations"
    ).fetchall()
    return [dict(r) for r in rows]


def notebook_glossary_term_rows(conn) -> list[dict[str, Any]]:
    """Flat join rows, same "separate flat export key" treatment as
        _export_notebook_citations above. `auto` (roadmap item H,
        session 7) round-trips too, so a restored document doesn't lose the
        manual-vs-auto-detected distinction on its attached terms.
    """
    rows = conn.execute(
        "SELECT notebook_uid, term_uid, position, created_at, auto FROM notebook_glossary_terms"
    ).fetchall()
    return [dict(r) for r in rows]


def notebook_glossary_excluded_rows(conn) -> list[dict[str, Any]]:
    """Flat rows for the auto-detect override table (roadmap item H,
    session 7) -- same "separate flat export key" treatment as the other
    glossary join tables. Without this, a restore would lose every
    "manually removed this false-positive match" override, and the next
    content save's auto-detect pass would silently re-attach it."""
    rows = conn.execute(
        "SELECT notebook_uid, term_uid, created_at FROM notebook_glossary_excluded_terms"
    ).fetchall()
    return [dict(r) for r in rows]


def glossary_reference_rows(conn) -> list[dict[str, Any]]:
    """Flat join rows (term_uid, ref_type, ref_uid, position, created_at) --
        same "separate flat export key" treatment as the two functions above. Raw table rows, not
        db.list_glossary_term_references' resolved-name shape -- a backup
        should round-trip the actual stored reference, not a name that was
        only ever a read-time convenience.
    """
    rows = conn.execute(
        "SELECT term_uid, ref_type, ref_uid, position, created_at, page_start, page_end FROM glossary_term_references"
    ).fetchall()
    return [dict(r) for r in rows]


def glossary_section_ref_rows(conn) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT term_uid, section_key, citation_uid, page_start, page_end FROM glossary_section_refs")]


def glossary_section_rows(conn) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT uid, term_uid, title, body, position FROM glossary_term_sections")]
