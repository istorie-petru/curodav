"""Books and manga in the Calibre library: each edition of a book or manga entry is one Calibre book, holding its files and cover.

Curodav writes what Calibre has a place for (title, authors, date, publisher, ISBN, DOI, keywords as tags, summary, rating,
cover, files) and keeps the rest (status, progress, criteria, place, edition) in its own tables, joined by the Calibre uuid.
Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import io
import os
import sqlite3
from pathlib import Path
from typing import Any

from . import calibre_library as cl
from . import db
from .log import get_logger

log = get_logger("media")

PATH_KEY = "media_calibre_path"
MAX_FILE_BYTES = 200 * 1024 * 1024
ACCEPT = ",".join(f".{ext}" for ext in cl.FORMATS)
MIME = {"PDF": "application/pdf", "EPUB": "application/epub+zip", "CBZ": "application/vnd.comicbook+zip", "CBR": "application/vnd.comicbook-rar",
        "MOBI": "application/x-mobipocket-ebook", "DJVU": "image/vnd.djvu", "TXT": "text/plain", "MD": "text/markdown"}


ENV_PATH = "CC_LIBRARY_PATH"


def library_path(conn: sqlite3.Connection) -> Path | None:
    """The folder chosen in Settings, else the one `curodav-ctl install --library` wrote into the environment."""
    value = db.get_app_meta(conn, PATH_KEY) or os.environ.get(ENV_PATH, "")
    return Path(value) if value else None


def set_library_path(conn: sqlite3.Connection, value: str) -> str | None:
    """Sets the library folder; an empty folder becomes a new library. Returns an error message, or None."""
    value = (value or "").strip()
    if not value:
        db.set_app_meta(conn, PATH_KEY, "")
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        return "Give the full path of the folder"
    try:
        if not cl.is_library(path):
            if path.exists() and any(path.iterdir()):
                return "That folder holds other files and no Calibre library"
            cl.create(path)
        cl.Library(path)
    except (OSError, cl.CalibreError) as exc:
        return f"That folder cannot be used: {exc}"
    db.set_app_meta(conn, PATH_KEY, str(path))
    return None


def library(conn: sqlite3.Connection) -> cl.Library | None:
    path = library_path(conn)
    if path is not None and not cl.is_library(path) and path.is_dir() and not any(path.iterdir()):
        try:
            cl.create(path)
        except (OSError, cl.CalibreError) as exc:
            log.warning("Could not start a Calibre library in %s: %s", path, exc)
    if path is None or not cl.is_library(path):
        return None
    try:
        return cl.Library(path)
    except cl.CalibreError as exc:
        log.warning("Calibre library at %s cannot be opened: %s", path, exc)
        return None


def _display_name(a: dict[str, str]) -> str:
    return " ".join(x for x in ((a.get("given") or "").strip(), (a.get("family") or "").strip()) if x)


def _sort_name(a: dict[str, str]) -> str:
    family, given = (a.get("family") or "").strip(), (a.get("given") or "").strip()
    return f"{family}, {given}" if family and given else (family or given)


def meta_for(conn: sqlite3.Connection, c: dict[str, Any], edition: dict[str, Any]) -> cl.BookMeta:
    """What Calibre holds for one edition of the entry `c` (as stored, not read up from editions)."""
    authors = [a for a in (c.get("authors") or []) if _display_name(a)]
    overall = db.overall_ratings(conn, [c]).get(c["uid"])
    title = c["title"] + (f": {c['subtitle']}" if c.get("subtitle") else "")
    return cl.BookMeta(title=title, authors=[_display_name(a) for a in authors], author_sorts=[_sort_name(a) for a in authors],
                       pubdate=edition.get("year") or c.get("year") or "", publisher=edition.get("publisher") or "", isbn=edition.get("isbn") or "",
                       doi=edition.get("doi") or "", tags=list(c.get("keywords") or []), comments=c.get("summary") or "",
                       rating=round(overall / 10) if overall else 0)


def _jpeg(webp_path: Path | None) -> bytes | None:
    if webp_path is None:
        return None
    from PIL import Image

    try:
        with Image.open(webp_path) as img:
            out = io.BytesIO()
            img.convert("RGB").save(out, "JPEG", quality=90)
            return out.getvalue()
    except OSError:
        return None


def uses_calibre(conn: sqlite3.Connection, type_key: str) -> bool:
    return db.kind_of(conn, type_key).uploads and library(conn) is not None


def push(conn: sqlite3.Connection, citation_uid: str) -> None:
    """Writes the entry's editions into the Calibre library, making a Calibre book for each one that has none yet."""
    lib = library(conn)
    c = db.get_citation_raw(conn, citation_uid)
    if lib is None or c is None or not db.kind_of(conn, c["type"]).uploads:
        return
    editions = db.list_editions(conn, citation_uid)
    if not editions:
        db.save_edition(conn, citation_uid, {})
        editions = db.list_editions(conn, citation_uid)
    cover = _jpeg(db.cover_path(conn, citation_uid))
    for e in editions:
        meta = meta_for(conn, c, e)
        if e.get("calibre_uuid") and lib.book(e["calibre_uuid"]):
            lib.update_book(e["calibre_uuid"], meta)
        else:
            db.set_edition_calibre(conn, e["uid"], lib.add_book(meta), "")
            e = db.get_edition(conn, e["uid"])
        if cover:
            lib.set_cover(e["calibre_uuid"], cover)


def store_file(conn: sqlite3.Connection, edition_uid: str, data: bytes, filename: str) -> str | None:
    """Puts an uploaded file into the edition's Calibre book (one file per format); returns an error message, or None."""
    lib = library(conn)
    e = db.get_edition(conn, edition_uid)
    if lib is None or e is None:
        return "The book library is not set up"
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if ext not in cl.FORMATS:
        return f"Books and manga are kept as {', '.join(sorted(cl.FORMATS))}"
    if len(data) > MAX_FILE_BYTES:
        return "The file is too large (at most 200 MB)"
    if not e.get("calibre_uuid"):
        push(conn, e["citation_uid"])
        e = db.get_edition(conn, edition_uid)
    lib.add_format(e["calibre_uuid"], data, ext)
    refresh_formats(conn, edition_uid)
    return None


def refresh_formats(conn: sqlite3.Connection, edition_uid: str) -> None:
    lib = library(conn)
    e = db.get_edition(conn, edition_uid)
    if lib is None or e is None or not e.get("calibre_uuid"):
        return
    book = lib.book(e["calibre_uuid"])
    formats = ",".join(f["format"] for f in book["formats"] if f["path"].is_file()) if book else ""
    db.set_edition_calibre(conn, edition_uid, e["calibre_uuid"] if book else "", formats)


def remove_files(conn: sqlite3.Connection, edition_uid: str) -> None:
    lib = library(conn)
    e = db.get_edition(conn, edition_uid)
    if lib is None or e is None or not e.get("calibre_uuid"):
        return
    book = lib.book(e["calibre_uuid"])
    for f in (book or {}).get("formats", []):
        lib.remove_format(e["calibre_uuid"], f["format"])
    refresh_formats(conn, edition_uid)


def file_for(conn: sqlite3.Connection, edition_uid: str, fmt: str = "") -> tuple[Path, str, str] | None:
    """(path, download name, media type) of one of the edition's files in Calibre: the asked format, else the first."""
    lib = library(conn)
    e = db.get_edition(conn, edition_uid)
    if lib is None or e is None or not e.get("calibre_uuid"):
        return None
    book = lib.book(e["calibre_uuid"])
    files = [f for f in (book or {}).get("formats", []) if f["path"].is_file()]
    pick = next((f for f in files if f["format"] == fmt.upper()), files[0] if files else None)
    if pick is None:
        return None
    return pick["path"], pick["path"].name, MIME.get(pick["format"], "application/octet-stream")


def delete_edition(conn: sqlite3.Connection, edition_uid: str) -> None:
    """Deletes the edition's Calibre book with its files; the Curodav edition itself is deleted by the caller."""
    lib = library(conn)
    e = db.get_edition(conn, edition_uid)
    if lib is not None and e and e.get("calibre_uuid") and lib.book(e["calibre_uuid"]):
        lib.delete_book(e["calibre_uuid"])


def delete_work(conn: sqlite3.Connection, citation_uid: str) -> None:
    for e in db.list_editions(conn, citation_uid):
        delete_edition(conn, e["uid"])


def _manga(book: dict[str, Any]) -> bool:
    return any(f["format"] in ("CBZ", "CBR", "CB7") for f in book["formats"]) or any(t.lower() == "manga" for t in book["tags"])


def import_plan(conn: sqlite3.Connection) -> dict[str, Any]:
    """What an import from the Calibre library would do: the books not yet in Curodav, and how many already are."""
    lib = library(conn)
    if lib is None:
        return {"new": [], "linked": 0, "formats": 0}
    linked = db.calibre_uuids(conn)
    books = lib.books()
    new = [b for b in books if b["uuid"] not in linked]
    return {"new": new, "linked": len(books) - len(new), "formats": sum(len(b["formats"]) for b in new)}


def import_books(conn: sqlite3.Connection) -> int:
    """Makes an entry with one edition for every Calibre book not yet in Curodav; the files stay where Calibre keeps them."""
    from . import media_metadata

    count = 0
    for b in import_plan(conn)["new"]:
        authors = []
        for name, sort in zip(b["authors"], b["author_sorts"]):
            family, _, given = sort.partition(",") if "," in sort else (name, "", "")
            authors.append({"family": family.strip(), "given": given.strip()} if given else media_metadata.split_name(name))
        uid = db.upsert_citation(conn, {"title": b["title"], "type": "manga" if _manga(b) else "book", "authors": authors, "year": b["pubdate"][:4],
                                        "keywords": b["tags"], "summary": _plain(b["comments"]), "score": float(b["rating"] * 10) if b["rating"] else None})
        edition = db.save_edition(conn, uid, {"year": b["pubdate"][:4], "publisher": b["publisher"], "isbn": b["isbn"], "doi": b["doi"]})
        db.set_edition_calibre(conn, edition, b["uuid"], ",".join(f["format"] for f in b["formats"]))
        if b["cover"] and b["cover"].is_file():
            webp = media_metadata.to_webp(b["cover"].read_bytes())
            if webp:
                db.set_cover(conn, uid, webp, "fetched")
        count += 1
    return count


def _plain(html_text: str) -> str:
    from .media_metadata import _text

    return _text(html_text)


def legacy_files(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Book and manga editions whose file still sits in the old store (library_files), not in Calibre."""
    out = []
    for e in db.editions_with_local_files(conn):
        if db.kind_of(conn, e["type"]).uploads:
            out.append(e)
    return out


def move_legacy_files(conn: sqlite3.Connection) -> tuple[int, list[str]]:
    """Moves each such file into the edition's Calibre book; the old copy is removed only once Calibre holds it."""
    moved, problems = 0, []
    for e in legacy_files(conn):
        path = db.edition_file_path(conn, e["uid"])
        if path is None:
            problems.append(f'"{e["title"]}": the stored file is missing')
            continue
        error = store_file(conn, e["uid"], path.read_bytes(), e["file_label"] or path.name)
        if error:
            problems.append(f'"{e["title"]}": {error}')
            continue
        db.clear_edition_file(conn, e["uid"])
        moved += 1
    return moved, problems



def push_all(conn: sqlite3.Connection) -> int:
    """Writes every book and manga entry that has no Calibre book yet into the library; returns how many."""
    if library(conn) is None:
        return 0
    linked = db.calibre_uuids(conn)
    count = 0
    for c in db.list_citations(conn):
        if db.kind_of(conn, c["type"]).uploads:
            editions = db.list_editions(conn, c["uid"])
            if not editions or any(e["calibre_uuid"] not in linked or not e["calibre_uuid"] for e in editions):
                push(conn, c["uid"])
                count += 1
    return count


SYNC_KEY = "media_calibre_synced"
MTIME_KEY = "media_calibre_mtime"


def _authors_from(book: dict[str, Any]) -> list[dict[str, str]]:
    from .media_metadata import split_name

    out = []
    for name, sort in zip(book["authors"], book["author_sorts"]):
        family, _, given = sort.partition(",")
        out.append({"family": family.strip(), "given": given.strip()} if given.strip() else split_name(name))
    return out


def _title_fields(c: dict[str, Any], calibre_title: str) -> dict[str, str]:
    """The work's title and subtitle after Calibre's title, which Curodav writes as "Title: Subtitle"."""
    if calibre_title in (c["title"], f"{c['title']}: {c['subtitle']}"):
        return {}
    if calibre_title.startswith(f"{c['title']}: "):
        return {"subtitle": calibre_title[len(c["title"]) + 2:]}
    return {"title": calibre_title, "subtitle": ""}


def _pull_book(conn: sqlite3.Connection, e: dict[str, Any], book: dict[str, Any], sole: bool) -> None:
    db.save_edition(conn, e["citation_uid"], {**{k: e[k] for k in ("edition", "place", "url")}, "year": book["pubdate"][:4] or e["year"],
                                              "publisher": book["publisher"], "isbn": book["isbn"], "doi": book["doi"]}, e["uid"])
    db.set_edition_calibre(conn, e["uid"], book["uuid"], ",".join(f["format"] for f in book["formats"] if f["path"].is_file()))
    if not sole:
        return
    c = db.get_citation_raw(conn, e["citation_uid"])
    row: dict[str, Any] = {"uid": c["uid"], "type": c["type"], "title": c["title"], "year": c["year"], "container_title": c["container_title"],
                           "authors": c["authors"], **_title_fields(c, book["title"])}
    authors = _authors_from(book)
    if [_display_name(a) for a in authors] != [_display_name(a) for a in c["authors"]] and book["authors"] != ["Unknown"]:
        row["authors"] = authors
    row["keywords"] = book["tags"]
    row["summary"] = _plain(book["comments"])
    overall = db.overall_ratings(conn, [c]).get(c["uid"])
    if book["rating"] != (round(overall / 10) if overall else 0) and not db.citation_ratings(conn, c["uid"]):
        row["score"] = float(book["rating"] * 10) if book["rating"] else None
    db.upsert_citation(conn, row)
    if book["cover"] and book["cover"].is_file() and not c.get("cover_custom") and not c.get("cover_fetched"):
        from .media_metadata import to_webp

        webp = to_webp(book["cover"].read_bytes())
        if webp:
            db.set_cover(conn, c["uid"], webp, "fetched")


def pull(conn: sqlite3.Connection, force: bool = False) -> dict[str, int]:
    """Reads what changed in the Calibre library since the last time (in Calibre, Calibre-Web or by hand) into Curodav:
    edited books update their editions and works, deleted ones lose their link, new ones become entries."""
    lib = library(conn)
    if lib is None:
        return {"updated": 0, "unlinked": 0, "added": 0}
    try:
        mtime = str(lib.db_path.stat().st_mtime_ns)
    except OSError:
        return {"updated": 0, "unlinked": 0, "added": 0}
    if not force and db.get_app_meta(conn, MTIME_KEY) == mtime:
        return {"updated": 0, "unlinked": 0, "added": 0}
    since = db.get_app_meta(conn, SYNC_KEY) or ""
    started = cl._now()
    books = {b["uuid"]: b for b in lib.books()}
    linked = db.editions_in_calibre(conn)
    per_work: dict[str, int] = {}
    for e in linked:
        per_work[e["citation_uid"]] = per_work.get(e["citation_uid"], 0) + 1
    updated = unlinked = 0
    for e in linked:
        book = books.get(e["calibre_uuid"])
        if book is None:
            db.set_edition_calibre(conn, e["uid"], "", "")
            unlinked += 1
        elif force or (book["last_modified"] or "") > since:
            _pull_book(conn, e, book, per_work[e["citation_uid"]] == 1 and len(db.list_editions(conn, e["citation_uid"])) == 1)
            updated += 1
    added = import_books(conn)
    db.set_app_meta(conn, SYNC_KEY, started)
    db.set_app_meta(conn, MTIME_KEY, str(lib.db_path.stat().st_mtime_ns))
    if updated or unlinked or added:
        log.info("Calibre library read: %s updated, %s gone, %s added", updated, unlinked, added)
    return {"updated": updated, "unlinked": unlinked, "added": added}
