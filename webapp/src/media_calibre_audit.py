"""The Calibre audit: where the book library and Curodav disagree, and the fixes for each.

Findings are plain rows with an id (`kind:key`), so a page can list them and apply the ones a person confirms.
Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from . import db, media_books as mb

KINDS = {
    "dupe": "Entered twice",
    "new": "Only in Calibre",
    "match": "Looks like the same book",
    "unlinked": "Only in Curodav",
    "gone": "Gone from Calibre",
    "diff": "Details differ",
    "file": "File outside Calibre",
    "dup": "Twice in Calibre",
}
FIXES = {
    "dupe": "Remove the copies",
    "new": "Add to Curodav",
    "match": "Link them",
    "unlinked": "Write into Calibre",
    "gone": "Unlink",
    "diff": "Use Calibre",
    "file": "Move into Calibre",
    "dup": "",
}


def auto_on(conn: sqlite3.Connection) -> bool:
    return db.get_app_meta(conn, mb.AUTO_KEY) != "0"


def set_auto(conn: sqlite3.Connection, on: bool) -> None:
    db.set_app_meta(conn, mb.AUTO_KEY, "1" if on else "0")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _family(name: str) -> str:
    return _norm(name.split()[-1]) if name.strip() else ""


def _by(book: dict[str, Any]) -> str:
    return ", ".join(book["authors"]) if book["authors"] and book["authors"] != ["Unknown"] else ""


def _touched(conn: sqlite3.Connection, c: dict[str, Any]) -> bool:
    """An entry someone has worked on: a status, rating, progress, own cover or a note that cites it."""
    if c.get("status") or c.get("score") or c.get("progress") or c.get("cover_custom") or c.get("summary_custom"):
        return True
    return bool(conn.execute("SELECT 1 FROM notebook_citations WHERE citation_uid = ? LIMIT 1", (c["uid"],)).fetchone()
                or conn.execute("SELECT 1 FROM glossary_term_references WHERE ref_type = 'citation' AND ref_uid = ? LIMIT 1", (c["uid"],)).fetchone())


def duplicates(conn: sqlite3.Connection, only: str = "") -> dict[str, list[dict[str, Any]]]:
    """Calibre uuid -> editions linked to it, for each uuid held by more than one edition; the best one to keep comes first."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for e in (db.editions_for_uuid(conn, only) if only else db.editions_in_calibre(conn)):
        groups.setdefault(e["calibre_uuid"], []).append(e)
    out = {}
    for uuid_, eds in groups.items():
        if len(eds) < 2:
            continue
        works = {e["uid"]: db.get_citation_raw(conn, e["citation_uid"]) for e in eds}
        eds.sort(key=lambda e: (not (works[e["uid"]] and _touched(conn, works[e["uid"]])), e.get("created_at") or ""))
        out[uuid_] = eds
    return out


def remove_copies(conn: sqlite3.Connection, uuid_: str) -> int:
    """Keeps the first entry of a Calibre book and deletes the untouched copies (only Curodav's entries; Calibre's book and files stay)."""
    eds = duplicates(conn, uuid_).get(uuid_, [])
    gone = 0
    for e in eds[1:]:
        c = db.get_citation_raw(conn, e["citation_uid"])
        if c is not None and not _touched(conn, c) and len(db.list_editions(conn, c["uid"])) == 1:
            db.delete_citation(conn, c["uid"])
            gone += 1
    return gone


def audit(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every difference between the Calibre library and Curodav; empty when there is no library."""
    lib = mb.library(conn)
    if lib is None:
        return []
    books = {b["uuid"]: b for b in lib.books()}
    linked = db.editions_in_calibre(conn)
    linked_uuids = {e["calibre_uuid"] for e in linked}
    rows: list[dict[str, Any]] = []

    def row(kind: str, key: str, title: str, by: str, detail: str, calibre: str = "", curodav: str = "") -> None:
        rows.append({"id": f"{kind}:{key}", "kind": kind, "label": KINDS[kind], "fix": FIXES[kind], "title": title, "by": by,
                     "detail": detail, "calibre": calibre, "curodav": curodav})

    for uuid_, eds in duplicates(conn).items():
        c = db.get_citation_raw(conn, eds[0]["citation_uid"])
        row("dupe", uuid_, c["title"] if c else "", "", f"{len(eds)} entries for one Calibre book")
    new = [b for u, b in books.items() if u not in linked_uuids]
    unlinked = []
    for c in db.list_citations(conn):
        if not db.kind_of(conn, c["type"]).uploads:
            continue
        eds = db.list_editions(conn, c["uid"])
        if not any(e.get("calibre_uuid") for e in eds):
            unlinked.append(c)

    taken: set[str] = set()
    for c in unlinked:
        full = c["title"] + (f": {c['subtitle']}" if c.get("subtitle") else "")
        authors = {_family(mb._display_name(a)) for a in c.get("authors") or [] if mb._display_name(a)}
        eds = db.list_editions(conn, c["uid"])
        isbns = {e["isbn"].replace("-", "") for e in eds if e.get("isbn")}
        hit = None
        for b in new:
            if b["uuid"] in taken or _norm(b["title"]) not in (_norm(full), _norm(c["title"])):
                continue
            same_isbn = bool(b["isbn"]) and b["isbn"].replace("-", "") in isbns
            theirs = {_family(a) for a in b["authors"]}
            if same_isbn or not authors or not theirs or authors & theirs:
                hit = b
                break
        by = ", ".join(mb._display_name(a) for a in c.get("authors") or [] if mb._display_name(a))
        if hit:
            taken.add(hit["uuid"])
            row("match", f"{c['uid']}:{hit['uuid']}", c["title"], by, "Same title and author, not linked yet", hit["title"], full)
        else:
            row("unlinked", c["uid"], c["title"], by, "Not in the Calibre library")
    for b in new:
        if b["uuid"] not in taken:
            row("new", b["uuid"], b["title"], _by(b), "Not in Curodav")

    for e in linked:
        book = books.get(e["calibre_uuid"])
        c = db.get_citation_raw(conn, e["citation_uid"])
        if c is None:
            continue
        if book is None:
            row("gone", e["uid"], c["title"], "", "Its Calibre book was deleted")
            continue
        meta = mb.meta_for(conn, c, e)
        diffs = []
        if _norm(book["title"]) != _norm(meta.title):
            diffs.append(("Title", book["title"], meta.title))
        if book["authors"] != ["Unknown"] and [_norm(a) for a in book["authors"]] != [_norm(a) for a in meta.authors]:
            diffs.append(("Authors", ", ".join(book["authors"]), ", ".join(meta.authors)))
        if (book["pubdate"] or "")[:4] != (meta.pubdate or "")[:4]:
            diffs.append(("Year", (book["pubdate"] or "")[:4], (meta.pubdate or "")[:4]))
        if (book["publisher"] or "").strip() != meta.publisher.strip():
            diffs.append(("Publisher", book["publisher"] or "", meta.publisher))
        if (book["isbn"] or "").replace("-", "") != meta.isbn.replace("-", ""):
            diffs.append(("ISBN", book["isbn"] or "", meta.isbn))
        if diffs:
            row("diff", e["uid"], c["title"], _by(book), "; ".join(d[0] for d in diffs),
                "\n".join(f"{n}: {a or 'none'}" for n, a, _ in diffs), "\n".join(f"{n}: {b or 'none'}" for n, _, b in diffs))

    seen: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for b in books.values():
        seen.setdefault((_norm(b["title"]), _family(b["authors"][0]) if b["authors"] else ""), []).append(b)
    for group in seen.values():
        if len(group) > 1:
            row("dup", group[0]["uuid"], group[0]["title"], _by(group[0]), f"{len(group)} Calibre books share this title and author")

    for e in mb.legacy_files(conn):
        row("file", e["uid"], e["title"], "", "Its file is in Curodav's own store")
    order = list(KINDS)
    rows.sort(key=lambda r: (order.index(r["kind"]), r["title"].lower()))
    return rows


def _apply_one(conn: sqlite3.Connection, issue_id: str, side: str) -> bool:
    kind, _, key = issue_id.partition(":")
    lib = mb.library(conn)
    if lib is None:
        return False
    if kind == "dupe":
        return remove_copies(conn, key) > 0
    if kind == "new":
        book = lib.book(key)
        if book is None or key in db.calibre_uuids(conn):
            return False
        before = db.calibre_uuids(conn)
        mb.import_books(conn)
        return key in db.calibre_uuids(conn) - before or key in db.calibre_uuids(conn)
    if kind == "match":
        cuid, _, buid = key.partition(":")
        book = lib.book(buid)
        if book is None:
            return False
        eds = db.list_editions(conn, cuid) or [db.get_edition(conn, db.save_edition(conn, cuid, {}))]
        formats = ",".join(f["format"] for f in book["formats"])
        db.set_edition_calibre(conn, eds[0]["uid"], buid, formats)
        return True
    if kind == "unlinked":
        mb.push(conn, key)
        return True
    if kind == "gone":
        db.set_edition_calibre(conn, key, "", "")
        return True
    if kind == "diff":
        e = db.get_edition(conn, key)
        book = lib.book(e["calibre_uuid"]) if e else None
        if book is None:
            return False
        if side == "curodav":
            mb.push(conn, e["citation_uid"])
        else:
            mb._pull_book(conn, e, book, len(db.list_editions(conn, e["citation_uid"])) == 1)
        return True
    if kind == "file":
        e = db.get_edition(conn, key)
        path = db.edition_file_path(conn, key)
        if e is None or path is None:
            return False
        if mb.store_file(conn, key, path.read_bytes(), e["file_label"] or path.name):
            return False
        db.clear_edition_file(conn, key)
        return True
    return False


def apply(conn: sqlite3.Connection, issue_ids: list[str], side: str = "calibre") -> int:
    """Applies the chosen fixes, each as the finding describes; returns how many were done."""
    return sum(1 for i in issue_ids if _apply_one(conn, i, side))


def fix_all(conn: sqlite3.Connection) -> int:
    """Every suggested fix at once: what the manual audit would confirm, applied without asking row by row."""
    return apply(conn, [r["id"] for r in audit(conn) if r["fix"]])


JOBS = {
    "check": ("Check for duplicates", "Counts the entries that share one Calibre book, changing nothing", ""),
    "dedupe": ("Remove duplicates", "Deletes extra entries of the same Calibre book and keeps the one you worked on", "Delete the extra entries that share a Calibre book? Entries you have a status, rating or note on stay. Calibre is not touched."),
    "reimport_list": ("Reimport the list", "Adds the Calibre books Curodav does not have, and links the ones that match an entry", ""),
    "reimport_metadata": ("Reimport metadata", "Reads every book's details from Calibre again; Calibre's values replace Curodav's", "Read every book's details from Calibre again? Where they differ, Calibre's values replace the ones in Curodav."),
    "write_metadata": ("Write metadata to Calibre", "Writes every book entry's details into Calibre; Curodav's values replace Calibre's", "Write the details of every book entry into Calibre? Where they differ, Curodav's values replace Calibre's."),
}
JOB_KEY = "media_calibre_job"


def job_state(conn: sqlite3.Connection) -> dict[str, Any]:
    import json

    try:
        return json.loads(db.get_app_meta(conn, JOB_KEY) or "{}")
    except ValueError:
        return {}


def _set_job(conn: sqlite3.Connection, job: str, state: str, message: str = "", done: int = 0, total: int = 0) -> None:
    import json

    db.set_app_meta(conn, JOB_KEY, json.dumps({"job": job, "label": JOBS[job][0], "state": state, "message": message, "done": done, "total": total, "at": mb.cl._now()}))


def _reporter(conn: sqlite3.Connection, job: str):
    """A progress callback for a job: it saves how far the job is, at most every few items."""
    seen = {"n": -1}

    def report(done: int, total: int) -> None:
        if done == total or done - seen["n"] >= max(1, total // 100):
            seen["n"] = done
            _set_job(conn, job, "running", f"{done} of {total}", done, total)

    return report


def _run(conn: sqlite3.Connection, job: str) -> str:
    report = _reporter(conn, job)
    if job == "check":
        groups = duplicates(conn)
        extra = sum(len(g) - 1 for g in groups.values())
        return f"{len(groups)} books have more than one entry ({extra} extra entries)" if groups else "No book has more than one entry"
    if job == "dedupe":
        todo = list(duplicates(conn))
        gone = 0
        for i, u in enumerate(todo, 1):
            gone += remove_copies(conn, u)
            report(i, len(todo))
        return f"{gone} extra entries removed"
    if job == "reimport_list":
        return f"{mb.import_books(conn, report)} books added"
    if job == "reimport_metadata":
        got = mb.pull(conn, force=True, progress=report)
        return f"{got['updated']} books read again, {got['added']} added, {got['unlinked']} unlinked"
    if job == "write_metadata":
        books = [c for c in db.list_citations(conn) if db.kind_of(conn, c["type"]).uploads]
        for i, c in enumerate(books, 1):
            mb.push(conn, c["uid"])
            report(i, len(books))
        return f"{len(books)} entries written to Calibre"
    raise ValueError(job)


def run_job(conn: sqlite3.Connection, job: str) -> None:
    _set_job(conn, job, "running")
    try:
        with mb._lock:
            message = _run(conn, job)
        total = job_state(conn).get("total", 0)
        _set_job(conn, job, "done", message, total, total)
    except Exception as exc:  # noqa: BLE001  a failed job is reported on the settings page, not raised
        mb.log.exception("Calibre job %s failed", job)
        _set_job(conn, job, "failed", str(exc))


def start_job(conn: sqlite3.Connection, job: str) -> bool:
    """Starts a maintenance job in the background; False when another is running or the name is unknown."""
    import threading

    if job not in JOBS or job_state(conn).get("state") == "running":
        return False
    row = conn.execute("PRAGMA database_list").fetchone()
    path = row[2] if row and row[2] else ""
    if not path:
        run_job(conn, job)
        return True
    _set_job(conn, job, "running")
    from pathlib import Path

    def work() -> None:
        with db.connect(Path(path)) as c:
            run_job(c, job)

    threading.Thread(target=work, daemon=True, name="calibre-job").start()
    return True
