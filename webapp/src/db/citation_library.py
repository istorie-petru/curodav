"""The citation library at scale: FTS5 search, keyset-paged listing, duplicate checks, usage counts and stored PDFs.

Feature document: curodav-notes/documentation/features/bibliography.md
"""

from __future__ import annotations

import base64
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import config
from .notebook import _attach_citation_authors

PAGE_SIZE = 50
MAX_PDF_BYTES = 50 * 1024 * 1024

_YEAR = "CASE WHEN trim(year) != '' AND trim(year) NOT GLOB '*[^0-9-]*' THEN CAST(year AS INTEGER) END"
_FIRST_FAMILY = "json_extract(authors_json, '$[0].family')"
_AUTHOR_KEY = ("CASE WHEN trim(coalesce(json_extract(value, '$.family'), '')) != '' AND trim(coalesce(json_extract(value, '$.given'), '')) != '' "
               "THEN trim(json_extract(value, '$.family')) || ', ' || trim(json_extract(value, '$.given')) "
               "ELSE trim(coalesce(json_extract(value, '$.family'), '') || coalesce(json_extract(value, '$.given'), '')) END")
SORT_EXPRESSIONS = {
    "title": "title COLLATE NOCASE",
    "type": "type",
    "year": f"coalesce(-({_YEAR}), 99999999)",
    "author": f"CASE WHEN {_FIRST_FAMILY} IS NULL THEN char(1114111) ELSE lower({_FIRST_FAMILY}) END",
}


def fts_query(text: str) -> str:
    """Every word becomes a quoted prefix term, so user punctuation can never be FTS syntax."""
    words = re.findall(r"\w+", text or "")
    return " ".join(f'"{w}"*' for w in words)


def encode_cursor(values: list[Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values).encode()).decode()


def decode_cursor(cursor: str) -> list[Any] | None:
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, TypeError):
        return None
    return values if isinstance(values, list) else None


def page_citations(conn: sqlite3.Connection, *, q: str = "", types: list[str] | None = None, authors: list[str] | None = None,
                   year_lo: int | None = None, year_hi: int | None = None, sources: list[str] | None = None, sort: str = "title", sort2: str = "title",
                   after: str = "", limit: int = PAGE_SIZE) -> dict[str, Any]:
    """One keyset page (never OFFSET): rows ordered by (sort, sort2, title, uid), the cursor of the next page or "", and the match count."""
    where, args = ["1 = 1"], []
    match = fts_query(q)
    if match:
        where.append("rowid IN (SELECT rowid FROM citations_fts WHERE citations_fts MATCH ?)")
        args.append(match)
    if types:
        where.append(f"type IN ({','.join('?' for _ in types)})")
        args += types
    if authors:
        where.append(f"EXISTS (SELECT 1 FROM json_each(authors_json) WHERE ({_AUTHOR_KEY}) IN ({','.join('?' for _ in authors)}))")
        args += authors
    if year_lo is not None:
        where.append(f"({_YEAR}) >= ?")
        args.append(year_lo)
    if year_hi is not None:
        where.append(f"({_YEAR}) <= ?")
        args.append(year_hi)
    if sources:
        has_file = "EXISTS (SELECT 1 FROM citation_editions e WHERE e.citation_uid = citations.uid AND e.file_name != '')"
        clauses = {"file": has_file, "url": "url != ''", "none": f"url = '' AND NOT {has_file}"}
        where.append("(" + " OR ".join(f"({clauses[k]})" for k in sources if k in clauses) + ")") if any(k in clauses for k in sources) else None
    total = conn.execute(f"SELECT count(*) FROM citations WHERE {' AND '.join(where)}", args).fetchone()[0]

    keys = [SORT_EXPRESSIONS.get(sort, SORT_EXPRESSIONS["title"]), SORT_EXPRESSIONS.get(sort2, SORT_EXPRESSIONS["title"]), SORT_EXPRESSIONS["title"], "uid"]
    cursor = decode_cursor(after) if after else None
    if cursor and len(cursor) == len(keys):
        where.append(f"({', '.join(keys)}) > ({', '.join('?' for _ in keys)})")
        args += cursor
    select_keys = ", ".join(f"{k} AS _k{i}" for i, k in enumerate(keys))
    rows = conn.execute(f"SELECT *, {select_keys} FROM citations WHERE {' AND '.join(where)} ORDER BY {', '.join(keys)} LIMIT ?",
                        [*args, limit + 1]).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor([rows[-1][f"_k{i}"] for i in range(len(keys))]) if more and rows else ""
    items = []
    for row in rows:
        d = dict(row)
        for i in range(len(keys)):
            d.pop(f"_k{i}")
        items.append(_attach_citation_authors(d))
    return {"items": items, "next": next_cursor, "total": total}


def search_citations(conn: sqlite3.Connection, q: str, limit: int = 20) -> list[dict[str, Any]]:
    return page_citations(conn, q=q, limit=limit)["items"]


def _normal_isbn(value: str) -> str:
    return re.sub(r"[\s-]", "", value or "").lower()


def find_duplicate(conn: sqlite3.Connection, row: dict[str, Any], exclude_uid: str = "") -> dict[str, Any] | None:
    """An existing book with the same DOI or ISBN (on the book or any edition), or the same title, year and first author."""
    doi = (row.get("doi") or "").strip().lower()
    if doi:
        hit = conn.execute("SELECT uid, title FROM citations c WHERE uid != ? AND (lower(doi) = ? OR EXISTS "
                           "(SELECT 1 FROM citation_editions e WHERE e.citation_uid = c.uid AND lower(e.doi) = ?)) LIMIT 1", (exclude_uid, doi, doi)).fetchone()
        if hit:
            return dict(hit)
    isbn = _normal_isbn(row.get("isbn", ""))
    if isbn:
        clean = "replace(replace(lower({}), '-', ''), ' ', '')"
        hit = conn.execute(f"SELECT uid, title FROM citations c WHERE uid != ? AND (({clean.format('isbn')}) = ? OR EXISTS "
                           f"(SELECT 1 FROM citation_editions e WHERE e.citation_uid = c.uid AND e.isbn != '' AND ({clean.format('e.isbn')}) = ?)) LIMIT 1",
                           (exclude_uid, isbn, isbn)).fetchone()
        if hit:
            return dict(hit)
    title = (row.get("title") or "").strip().lower()
    if not title:
        return None
    authors = row.get("authors") or []
    family = ((authors[0].get("family") if authors else "") or "").strip().lower()
    hit = conn.execute(f"SELECT uid, title FROM citations WHERE lower(title) = ? AND trim(year) = ? AND coalesce(lower({_FIRST_FAMILY}), '') = ? AND uid != ? LIMIT 1",
                       (title, (row.get("year") or "").strip(), family, exclude_uid)).fetchone()
    return dict(hit) if hit else None


def citation_usage(conn: sqlite3.Connection, uid: str) -> dict[str, int]:
    """How many notes, university readings and glossary terms use this entry."""
    one = lambda sql: conn.execute(sql, (uid,)).fetchone()[0]
    return {
        "notes": one("SELECT count(*) FROM notebook_citations WHERE citation_uid = ?"),
        "readings": one("SELECT count(*) FROM university_readings WHERE citation_id = ?"),
        "terms": one("SELECT count(*) FROM glossary_term_references WHERE ref_type = 'citation' AND ref_uid = ?"),
    }


def files_dir(conn: sqlite3.Connection) -> Path:
    row = conn.execute("PRAGMA database_list").fetchone()
    base = Path(row[2]).parent if row and row[2] else config.default_db_path().parent
    return base / "library_files"


EDITION_FIELDS = ("edition", "year", "publisher", "place", "isbn", "doi", "url")


def list_editions(conn: sqlite3.Connection, citation_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM citation_editions WHERE citation_uid = ? ORDER BY year, created_at, uid", (citation_uid,)).fetchall()
    return [_edition_state(conn, dict(r)) for r in rows]


def get_edition(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM citation_editions WHERE uid = ?", (uid,)).fetchone()
    return _edition_state(conn, dict(row)) if row else None


def _edition_state(conn: sqlite3.Connection, e: dict[str, Any]) -> dict[str, Any]:
    """Adds `file_state` (none, ok, or missing: recorded but gone from the disk), `source` (none, link or local) and `display`."""
    e["file_state"] = ("ok" if (files_dir(conn) / e["file_name"]).is_file() else "missing") if e["file_name"] else "none"
    e["source"] = "local" if e["file_name"] else ("link" if e["url"] else "none")
    e["display"] = " · ".join(x for x in (f"{e['edition']} ed." if e["edition"] else "", e["publisher"], e["year"]) if x) or "Edition"
    return e


def save_edition(conn: sqlite3.Connection, citation_uid: str, fields: dict[str, str], uid: str = "") -> str:
    values = {k: (fields.get(k) or "").strip() for k in EDITION_FIELDS}
    if uid:
        conn.execute(f"UPDATE citation_editions SET {', '.join(f'{k} = ?' for k in values)} WHERE uid = ?", [*values.values(), uid])
    else:
        uid = str(uuid.uuid4())
        conn.execute(f"INSERT INTO citation_editions (uid, citation_uid, created_at, {', '.join(values)}) VALUES (?, ?, ?, {', '.join('?' for _ in values)})",
                     [uid, citation_uid, datetime.now(timezone.utc).isoformat(), *values.values()])
    conn.commit()
    return uid


def delete_edition(conn: sqlite3.Connection, uid: str) -> None:
    clear_edition_file(conn, uid)
    conn.execute("DELETE FROM citation_editions WHERE uid = ?", (uid,))
    conn.commit()


def delete_citation_editions(conn: sqlite3.Connection, citation_uid: str) -> None:
    for row in conn.execute("SELECT uid FROM citation_editions WHERE citation_uid = ?", (citation_uid,)).fetchall():
        delete_edition(conn, row[0])


def set_edition_file(conn: sqlite3.Connection, uid: str, data: bytes, label: str) -> str | None:
    """Stores a PDF for the edition; returns an error message, or None when saved."""
    if len(data) > MAX_PDF_BYTES:
        return "The PDF is too large (at most 50 MB)"
    if not data.startswith(b"%PDF"):
        return "That file is not a PDF"
    folder = files_dir(conn)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uid}-{uuid.uuid4().hex[:8]}.pdf"
    (folder / name).write_bytes(data)
    clear_edition_file(conn, uid)
    conn.execute("UPDATE citation_editions SET file_name = ?, file_label = ? WHERE uid = ?", (name, (label or "document.pdf")[:200], uid))
    conn.commit()
    return None


def clear_edition_file(conn: sqlite3.Connection, uid: str) -> None:
    row = conn.execute("SELECT file_name FROM citation_editions WHERE uid = ?", (uid,)).fetchone()
    if row and row["file_name"]:
        (files_dir(conn) / row["file_name"]).unlink(missing_ok=True)
    conn.execute("UPDATE citation_editions SET file_name = '', file_label = '' WHERE uid = ?", (uid,))
    conn.commit()


def edition_file_path(conn: sqlite3.Connection, uid: str) -> Path | None:
    row = conn.execute("SELECT file_name FROM citation_editions WHERE uid = ?", (uid,)).fetchone()
    if not row or not row["file_name"]:
        return None
    path = files_dir(conn) / row["file_name"]
    return path if path.is_file() else None


def sources_for(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """One query for a page: per entry the edition count, files held and files missing, and whether it has a URL."""
    uids = [c["uid"] for c in items]
    stats = {u: {"editions": 0, "files": 0, "missing": 0} for u in uids}
    if uids:
        rows = conn.execute(f"SELECT citation_uid, file_name FROM citation_editions WHERE citation_uid IN ({','.join('?' for _ in uids)})", uids).fetchall()
        folder = files_dir(conn)
        for row in rows:
            st = stats[row["citation_uid"]]
            st["editions"] += 1
            if row["file_name"]:
                st["files"] += 1
                st["missing"] += 0 if (folder / row["file_name"]).is_file() else 1
    return {c["uid"]: {**stats[c["uid"]], "url": bool(c.get("url"))} for c in items}


def picker_items(conn: sqlite3.Connection, selected: list[str], q: str = "", limit: int = 30) -> list[dict[str, str]]:
    """Options for a server-searched dropdown: the selected entries first, then the best matches, never the whole library."""
    from .notebook import format_citation_display, get_citation

    items = [{"uid": u, "name": format_citation_display(c)} for u in selected if (c := get_citation(conn, u))]
    taken = {i["uid"] for i in items}
    for c in page_citations(conn, q=q, limit=limit)["items"]:
        if c["uid"] not in taken:
            items.append({"uid": c["uid"], "name": format_citation_display(c)})
    return items


def author_options(conn: sqlite3.Connection, q: str = "", selected: list[str] | None = None, limit: int = 30) -> list[dict[str, str]]:
    """Distinct author names ("Family, Given") matching `q`, the selected ones first; a few at a time, never every author."""
    items = [{"uid": a, "name": a} for a in (selected or [])]
    taken = set(selected or [])
    needle = f"%{q.strip().lower()}%"
    rows = conn.execute(f"SELECT DISTINCT {_AUTHOR_KEY} AS k FROM citations, json_each(citations.authors_json) "
                        "WHERE k != '' AND lower(k) LIKE ? ORDER BY lower(k) LIMIT ?", (needle, limit + len(taken))).fetchall()
    items += [{"uid": r[0], "name": r[0]} for r in rows if r[0] not in taken][:limit]
    return items


MEDIA_TYPES = frozenset({"webpage", "article-journal", "conference-paper", "other"})


def book_noun(c: dict[str, Any] | None) -> str:
    """"Media" for web pages, articles and the like, "Book" for the rest; the word the library's windows use for an entry."""
    return "Media" if c and c.get("type") in MEDIA_TYPES else "Book"
