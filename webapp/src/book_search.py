"""Searching inside books for the MCP server and the REST API: a rebuildable index of passages, searched by words, phrase or regex.

Feature document: curodav-notes/documentation/features/book-search.md

The index is `book_search.sqlite` beside the main database. A book is read into it on its first search and again when its file
changes. Nothing here returns a file or a path; text leaves only through `read`, which is capped per call and per hour.
"""

from __future__ import annotations

import bisect
import re
import sqlite3
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import book_text, config, db, media_books
from .book_text import BookError
from .db.citation_library import files_dir, fts_query

MAX_HITS = 20
SNIPPET_CHARS = 200
READ_CALL_CHARS = 6000
READ_HOUR_CHARS = 60_000
REGEX_MAX = 200
GREP_SECONDS = 10
FORMAT_ORDER = ["epub", "pdf", "fb2", "txt", "md"]
MODES = ("words", "phrase", "regex")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (key TEXT PRIMARY KEY, size INTEGER, mtime REAL, first_rowid INTEGER, passages INTEGER, kind TEXT, indexed_at TEXT);
CREATE TABLE IF NOT EXISTS sections (book TEXT, idx INTEGER, title TEXT, page INTEGER, first_seq INTEGER, passages INTEGER, PRIMARY KEY (book, idx));
CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(text, section UNINDEXED, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS reads (token TEXT, book TEXT, at TEXT, chars INTEGER);
"""


def _index_path(conn: sqlite3.Connection) -> Path:
    row = conn.execute("PRAGMA database_list").fetchone()
    return (Path(row[2]).parent if row and row[2] else config.default_db_path().parent) / "book_search.sqlite"


def _open(conn: sqlite3.Connection) -> sqlite3.Connection:
    path = _index_path(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    idx = sqlite3.connect(path, timeout=30)
    idx.row_factory = sqlite3.Row
    idx.executescript(SCHEMA)
    return idx


def _readable(conn: sqlite3.Connection, edition: dict[str, Any], fmt: str) -> tuple[Path, str] | None:
    """The edition's file in the wanted format (the best one when none is asked for) and that format's lowercase name."""
    found = []
    if edition.get("file_name"):
        legacy = files_dir(conn) / edition["file_name"]
        if legacy.is_file():
            found.append((legacy, legacy.suffix.lstrip(".").lower() or "pdf"))
    for name in (edition.get("calibre_formats") or "").split(","):
        if name.strip():
            hit = media_books.file_for(conn, edition["uid"], name.strip())
            if hit and hit[0].is_file():
                found.append((hit[0], hit[0].suffix.lstrip(".").lower()))
    if fmt:
        found = [f for f in found if f[1] == fmt.lower()]
    found.sort(key=lambda f: FORMAT_ORDER.index(f[1]) if f[1] in FORMAT_ORDER else len(FORMAT_ORDER))
    return found[0] if found else None


def locate(conn: sqlite3.Connection, citation_uid: str, edition_uid: str = "", fmt: str = "") -> tuple[str, Path, str]:
    """(index key, file, format) of the book to search; raises BookError when there is none to read."""
    if db.get_citation(conn, citation_uid) is None:
        raise BookError(f"No library entry with uid {citation_uid}")
    editions = db.list_editions(conn, citation_uid)
    if edition_uid:
        editions = [e for e in editions if e["uid"] == edition_uid]
        if not editions:
            raise BookError(f"That entry has no edition {edition_uid}")
    for e in editions:
        got = _readable(conn, e, fmt)
        if got:
            return f"{e['uid']}:{got[1]}", got[0], got[1]
    raise BookError("That entry has no book file to search" + (f" in {fmt.upper()}" if fmt else ""))


def _ensure(conn: sqlite3.Connection, idx: sqlite3.Connection, key: str, path: Path, fmt: str) -> sqlite3.Row:
    stat = path.stat()
    row = idx.execute("SELECT * FROM books WHERE key = ?", (key,)).fetchone()
    if row and row["size"] == stat.st_size and abs(row["mtime"] - stat.st_mtime) < 1:
        return row
    with _lock:
        row = idx.execute("SELECT * FROM books WHERE key = ?", (key,)).fetchone()
        if row and row["size"] == stat.st_size and abs(row["mtime"] - stat.st_mtime) < 1:
            return row
        sections = book_text.sections_of(path, fmt)
        _forget(idx, key)
        first = (idx.execute("SELECT COALESCE(MAX(rowid), 0) FROM passages").fetchone()[0]) + 1
        seq = 0
        for i, s in enumerate(sections):
            pieces = book_text.passages(s["text"])
            s["first"], s["count"] = seq, len(pieces)
            idx.executemany("INSERT INTO passages (rowid, text, section) VALUES (?, ?, ?)", [(first + seq + n, p, i) for n, p in enumerate(pieces)])
            idx.execute("INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?)", (key, i, s["title"], s["page"], s["first"], s["count"]))
            seq += len(pieces)
        idx.execute("INSERT INTO books VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (key, stat.st_size, stat.st_mtime, first, seq, "pages" if fmt == "pdf" else "chapters", datetime.now(timezone.utc).isoformat()))
        idx.commit()
        return idx.execute("SELECT * FROM books WHERE key = ?", (key,)).fetchone()


def _forget(idx: sqlite3.Connection, key: str) -> None:
    row = idx.execute("SELECT first_rowid, passages FROM books WHERE key = ?", (key,)).fetchone()
    if row:
        idx.execute("DELETE FROM passages WHERE rowid BETWEEN ? AND ?", (row["first_rowid"], row["first_rowid"] + row["passages"] - 1))
    idx.execute("DELETE FROM sections WHERE book = ?", (key,))
    idx.execute("DELETE FROM books WHERE key = ?", (key,))


def _where(idx: sqlite3.Connection, book: sqlite3.Row, seq: int) -> dict[str, Any]:
    s = idx.execute("SELECT * FROM sections WHERE book = ? AND first_seq <= ? ORDER BY idx DESC LIMIT 1", (book["key"], seq)).fetchone()
    return {"section": s["idx"], "title": s["title"], "page": s["page"]}


def _words(query: str) -> list[str]:
    return re.findall(r"\w+", query, re.UNICODE)


def _fts_hits(idx: sqlite3.Connection, book: sqlite3.Row, query: str, mode: str, limit: int) -> list[dict[str, Any]]:
    words = _words(query)
    if not words:
        raise BookError("Give at least one word to search for")
    match = '"' + " ".join(words) + '"' if mode == "phrase" else fts_query(" ".join(words))
    lo, hi = book["first_rowid"], book["first_rowid"] + book["passages"] - 1
    rows = idx.execute(
        "SELECT rowid, snippet(passages, 0, '[', ']', '…', 32) AS snip FROM passages WHERE passages MATCH ? AND rowid BETWEEN ? AND ? "
        "ORDER BY rank LIMIT ?", (match, lo, hi, limit)).fetchall()
    return [{"hit": r["rowid"] - lo, "snippet": " ".join(r["snip"].split())} for r in rows]


def _regex_hits(idx: sqlite3.Connection, book: sqlite3.Row, pattern: str, limit: int) -> list[dict[str, Any]]:
    if not pattern or len(pattern) > REGEX_MAX:
        raise BookError(f"A regex must be between 1 and {REGEX_MAX} characters")
    lo = book["first_rowid"]
    texts = [r[0] for r in idx.execute("SELECT text FROM passages WHERE rowid BETWEEN ? AND ? ORDER BY rowid", (lo, lo + book["passages"] - 1))]
    with tempfile.NamedTemporaryFile("wb", suffix=".txt", prefix="curodav-grep-") as f:
        starts, offset = [], 0
        for t in texts:
            line = (" ".join(t.split()) + "\n").encode("utf-8")
            starts.append(offset)
            offset += len(line)
            f.write(line)
        f.flush()
        try:
            run = subprocess.run(["grep", "-E", "-i", "-o", "-b", "-m", str(limit * 3), "-e", pattern, f.name], capture_output=True, timeout=GREP_SECONDS, check=False)
        except subprocess.TimeoutExpired:
            raise BookError("That pattern took too long; try a simpler one") from None
        except FileNotFoundError:
            raise BookError("Regex search needs grep on the server") from None
    if run.returncode == 2:
        raise BookError("That is not a valid extended regular expression")
    hits: dict[int, dict[str, Any]] = {}
    for line in run.stdout.decode("utf-8", "replace").splitlines():
        off, _, matched = line.partition(":")
        if not off.isdigit():
            continue
        at = int(off)
        seq = bisect.bisect_right(starts, at) - 1
        if seq in hits or seq < 0:
            continue
        text = " ".join(texts[seq].split())
        pre = len((text.encode("utf-8")[: at - starts[seq]]).decode("utf-8", "ignore"))
        a, b = max(0, pre - SNIPPET_CHARS // 2), min(len(text), pre + len(matched) + SNIPPET_CHARS // 2)
        hits[seq] = {"hit": seq, "snippet": ("…" if a else "") + text[a:pre] + "[" + text[pre:pre + len(matched)] + "]" + text[pre + len(matched):b] + ("…" if b < len(text) else "")}
        if len(hits) >= limit:
            break
    return sorted(hits.values(), key=lambda h: h["hit"])


def search(conn: sqlite3.Connection, citation_uid: str, query: str, *, mode: str = "words", edition: str = "", fmt: str = "",
           limit: int = 10) -> dict[str, Any]:
    if mode not in MODES:
        raise BookError(f"mode must be one of {', '.join(MODES)}")
    limit = max(1, min(int(limit or 10), MAX_HITS))
    key, path, fmt = locate(conn, citation_uid, edition, fmt)
    idx = _open(conn)
    try:
        book = _ensure(conn, idx, key, path, fmt)
        hits = _regex_hits(idx, book, query, limit) if mode == "regex" else _fts_hits(idx, book, query, mode, limit)
        for h in hits:
            h.update(_where(idx, book, h["hit"]))
        return {"format": fmt.upper(), "passages": book["passages"], "mode": mode, "hits": hits}
    finally:
        idx.close()


def contents(conn: sqlite3.Connection, citation_uid: str, *, edition: str = "", fmt: str = "") -> dict[str, Any]:
    key, path, fmt = locate(conn, citation_uid, edition, fmt)
    idx = _open(conn)
    try:
        book = _ensure(conn, idx, key, path, fmt)
        rows = idx.execute("SELECT idx, title, page, passages FROM sections WHERE book = ? ORDER BY idx", (key,)).fetchall()
        out: dict[str, Any] = {"format": fmt.upper(), "kind": book["kind"], "sections": len(rows), "passages": book["passages"]}
        if book["kind"] == "pages":
            out["note"] = "Each page is a section: read_book with section = page number - 1."
        else:
            out["items"] = [{"section": r["idx"], "title": r["title"], "passages": r["passages"]} for r in rows[:400]]
            out["truncated"] = len(rows) > 400
        return out
    finally:
        idx.close()


def _spent(idx: sqlite3.Connection, token: str, book: str) -> tuple[int, str]:
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    row = idx.execute("SELECT COALESCE(SUM(chars), 0) AS n, MIN(at) AS first FROM reads WHERE token = ? AND book = ? AND at > ?", (token, book, since)).fetchone()
    return row["n"], row["first"] or ""


def read(conn: sqlite3.Connection, citation_uid: str, *, token: str = "", hit: int | None = None, section: int | None = None,
         before: int = 1, after: int = 1, edition: str = "", fmt: str = "") -> dict[str, Any]:
    """Passages around a hit, or from the start of a section, at most READ_CALL_CHARS characters and READ_HOUR_CHARS an hour per book."""
    if (hit is None) == (section is None):
        raise BookError("Give either hit (from search_book) or section (from book_contents)")
    key, path, fmt = locate(conn, citation_uid, edition, fmt)
    idx = _open(conn)
    try:
        book = _ensure(conn, idx, key, path, fmt)
        if section is not None:
            row = idx.execute("SELECT first_seq, passages FROM sections WHERE book = ? AND idx = ?", (key, section)).fetchone()
            if row is None:
                raise BookError(f"No section {section}; book_contents lists them")
            start, end = row["first_seq"], row["first_seq"] + max(row["passages"], 1) - 1
        else:
            if not 0 <= hit < book["passages"]:
                raise BookError(f"No hit {hit} in this book")
            start, end = max(0, hit - max(0, min(before, 5))), min(book["passages"] - 1, hit + max(0, min(after, 5)))
        spent, first = _spent(idx, token, key)
        room = min(READ_CALL_CHARS, READ_HOUR_CHARS - spent)
        if room <= 0:
            reset = (datetime.fromisoformat(first) + timedelta(hours=1)).strftime("%H:%M UTC") if first else "within the hour"
            raise BookError(f"Reading limit for this book reached ({READ_HOUR_CHARS} characters an hour); it resets around {reset}")
        lo = book["first_rowid"]
        texts, used = [], 0
        for seq in range(start, end + 1):
            t = idx.execute("SELECT text FROM passages WHERE rowid = ?", (lo + seq,)).fetchone()[0]
            if texts and used + len(t) > room:
                break
            texts.append(t[:room])
            used += len(texts[-1])
            if used >= room:
                break
        got_end = start + len(texts) - 1
        idx.execute("INSERT INTO reads VALUES (?, ?, ?, ?)", (token, key, datetime.now(timezone.utc).isoformat(), used))
        idx.execute("DELETE FROM reads WHERE at < ?", ((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),))
        idx.commit()
        out = {"from": _where(idx, book, start), "text": "\n\n".join(texts), "first_hit": start, "last_hit": got_end}
        if got_end < book["passages"] - 1:
            out["next_hit"] = got_end + 1
        return out
    finally:
        idx.close()

