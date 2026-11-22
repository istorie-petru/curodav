"""Media in the library: the reading and watching now page, covers, automatic details and the Library settings.

Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import json
import re
from pathlib import PurePath
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from .. import book_annotations, book_bookmarks, book_speech, book_stats, book_convert, book_define, book_reader, book_search, citation_formats, clock, db, media, media_books, media_calibre_audit, media_exchange, media_metadata
from .. import tags as tag_store
from ..deps import get_db, respond, templates, validation_response

router = APIRouter(prefix="/library", tags=["media"])
settings_router = APIRouter(prefix="/settings/library", tags=["media"])
calibre_router = APIRouter(prefix="/settings/calibre", tags=["media"])

SETTINGS = "/settings/library"
DATA_SETTINGS = "/settings/data-maintenance"
WIKI_URL = "https://github.com/istorie-petru/curodav/wiki/Library-and-Media"
_CROPPED_COVER_MAX = 6 * 1024 * 1024


def _today() -> str:
    return clock.now().date().isoformat()


def decorate(conn, items: list[dict]) -> list[dict]:
    """Adds what a row or a card shows: kind, status word, progress, overall rating and the cover address."""
    scale = db.rating_scale(conn)
    custom = db.media_kinds_by_uid(conn)
    overall = db.overall_ratings(conn, items)
    tag_store.attach_items(conn, "media", items)
    for c in items:
        kind = media.kind_for(c.get("type") or "", custom)
        c["kind"] = kind
        c["status_label"] = media.status_label(c.get("status") or "", kind.verb) if c.get("status") else ""
        c["overall"] = overall.get(c["uid"])
        c["stars"] = media.stars(c["overall"], scale)
        c["cover"] = db.cover_url(c)
        c["display_authors"] = db.format_citation_authors(c.get("authors") or [])
    return items


def _guess(filename: str) -> tuple[str, list[dict[str, str]]]:
    """A title and authors from a file name: "Author - Title.epub", "Title (Author).epub" or just the title."""
    stem = PurePath(filename).stem.replace("_", " ").strip()
    if " - " in stem:
        author, _, title = stem.partition(" - ")
        return title.strip() or stem, [media_metadata.split_name(author)]
    m = re.match(r"^(.*?)\s*\(([^()]+)\)$", stem)
    if m and m.group(1):
        return m.group(1).strip(), [media_metadata.split_name(m.group(2))]
    return stem, []


@router.get("/add-books")
def add_books_modal(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse("library_add_books_modal.html", {
        "request": request, "accept": media_books.ACCEPT if media_books.library(conn) else "application/pdf", "ready": media_books.library(conn) is not None})


@router.post("/add-books")
async def add_books(files: list[UploadFile] = File([]), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    added, problems = [], []
    for f in files:
        if not f.filename:
            continue
        data = await f.read(media_books.MAX_FILE_BYTES + 1)
        title, authors = _guess(f.filename)
        inside = book_convert.read_metadata(data, f.filename)
        if inside.get("title") and inside["title"].lower() not in ("unknown", f.filename.lower()):
            title = inside["title"]
            if inside.get("authors"):
                authors = [media_metadata.split_name(a) for a in inside["authors"].split(" & ")]
        manga = PurePath(f.filename).suffix.lower() in (".cbz", ".cbr", ".cb7")
        uid = db.upsert_citation(conn, {"title": title, "type": "manga" if manga else "book", "authors": authors})
        edition = db.save_edition(conn, uid, {})
        error = media_books.store_file(conn, edition, data, f.filename)
        if error:
            media_books.delete_work(conn, uid)
            db.delete_citation(conn, uid)
            problems.append(f'"{f.filename}": {error}')
        else:
            media_books.push(conn, uid)
            added.append(uid)
    note = f"{len(added)} books added" + (f"; {len(problems)} not added: {'; '.join(problems[:3])}" if problems else "")
    return respond(x_requested_with, "/library?" + urlencode({"note": note}), added=added, problems=problems)


@router.get("/lookup/cover")
def lookup_cover(u: str = ""):
    """A result's cover, fetched by the server so the page only ever loads images from Curodav itself."""
    data = media_metadata.download_cover(u, thumbnail=True)
    if data is None:
        raise HTTPException(404)
    return Response(data, media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})


def _paged_source(conn, uid: str, edition: str) -> dict | None:
    """What the page reader opens for this entry: {"edition", "format", "converted", "kind", "ocr"} or None. kind is pdf, comic or book.
    Files the reader draws as they are come first (a PDF with a searchable copy made by OCR uses that); a Word, OpenDocument, RTF, text,
    CBR or CB7 file counts when Calibre can convert it, and is used only when nothing else opens."""
    found: list[tuple[int, str, str]] = []
    convertible: list[tuple[str, str]] = []
    for e in db.list_editions(conn, uid):
        if edition and e["uid"] != edition:
            continue
        formats = [f.strip().lower() for f in (e.get("calibre_formats") or "").split(",") if f.strip()]
        for fmt in formats:
            if fmt in book_reader.PAGED_FORMATS and media_books.file_for(conn, e["uid"], fmt.upper()):
                found.append((book_reader.PAGED_FORMATS.index(fmt), e["uid"], fmt.upper()))
            elif fmt in book_convert.CONVERTIBLE and book_convert.tools_available() and media_books.file_for(conn, e["uid"], fmt.upper()):
                convertible.append((e["uid"], fmt.upper()))
        if e.get("file_name") and "pdf" not in formats and db.edition_file_path(conn, e["uid"]) is not None:
            found.append((book_reader.PAGED_FORMATS.index("pdf"), e["uid"], "PDF"))
    if found:
        _, euid, fmt = min(found, key=lambda f: f[0])
        ocr = False
        if fmt == "PDF":
            src = media_books.file_for(conn, euid, "PDF")
            path = src[0] if src else db.edition_file_path(conn, euid)
            ocr = bool(path and book_convert.ocr_path(conn, path))
        kind = "pdf" if fmt == "PDF" else "comic" if fmt.lower() in book_reader.COMIC_FORMATS else "book"
        return {"edition": euid, "format": fmt, "converted": ocr, "kind": kind, "ocr": ocr}
    if convertible:
        euid, fmt = convertible[0]
        return {"edition": euid, "format": fmt, "converted": True, "kind": "comic" if fmt.lower() in book_reader.COMIC_FORMATS else "book", "ocr": False}
    return None


@router.get("/editions/{euid}/converted")
def converted_edition(euid: str, format: str = "", conn=Depends(get_db)):
    """The edition's file in the form the reader opens: a Word, OpenDocument, RTF or text file as an EPUB, a CBR or CB7 as a CBZ (made on
    the first request, kept after), or a PDF's searchable copy made by OCR."""
    if format.upper() == "PDF":
        src = media_books.file_for(conn, euid, "PDF")
        path = src[0] if src else db.edition_file_path(conn, euid)
        ocr = book_convert.ocr_path(conn, path) if path else None
        if ocr is None:
            raise HTTPException(404)
        return FileResponse(ocr, media_type="application/pdf", filename="book.pdf", content_disposition_type="inline")
    found = media_books.file_for(conn, euid, format)
    if not found:
        raise HTTPException(404)
    try:
        path = book_convert.to_epub(conn, found[0])
    except book_search.BookError as exc:
        raise HTTPException(422, str(exc)) from None
    mime = "application/vnd.comicbook+zip" if path.suffix == ".cbz" else "application/epub+zip"
    return FileResponse(path, media_type=mime, filename=f"book{path.suffix}", content_disposition_type="inline")


def _ocr_source(conn, euid: str):
    src = media_books.file_for(conn, euid, "PDF")
    path = src[0] if src else db.edition_file_path(conn, euid)
    if path is None:
        raise HTTPException(404)
    return path


@router.get("/editions/{euid}/ocr")
def ocr_state(euid: str, conn=Depends(get_db)):
    import json

    path = _ocr_source(conn, euid)
    state = json.loads(db.get_app_meta(conn, f"ocr_{euid}") or "{}")
    if book_convert.ocr_path(conn, path):
        state = {"state": "done", "message": "Searchable copy ready"}
    return JSONResponse({"available": book_convert.ocr_available(), **state})


@router.post("/editions/{euid}/ocr")
def ocr_start(euid: str, conn=Depends(get_db)):
    """Makes a searchable copy of a scanned PDF in the background; the original is kept."""
    import json
    import threading
    from pathlib import Path

    path = _ocr_source(conn, euid)
    if not book_convert.ocr_available():
        return JSONResponse({"available": False, "state": "failed", "message": "OCR needs ocrmypdf and tesseract on the server"})
    key = f"ocr_{euid}"
    if json.loads(db.get_app_meta(conn, key) or "{}").get("state") == "running":
        return JSONResponse({"available": True, "state": "running", "message": "Reading the pages"})
    db.set_app_meta(conn, key, json.dumps({"state": "running", "message": "Reading the pages"}))
    db_file = book_convert.database_file(conn)

    def work() -> None:
        with db.connect(Path(db_file)) as c:
            try:
                book_convert.ocr_pdf(c, path)
                db.set_app_meta(c, key, json.dumps({"state": "done", "message": "Searchable copy ready"}))
            except Exception as exc:  # noqa: BLE001  reported to the reader, not raised
                db.set_app_meta(c, key, json.dumps({"state": "failed", "message": str(exc)}))

    if db_file:
        threading.Thread(target=work, daemon=True, name="pdf-ocr").start()
    else:
        work_conn_state = {"state": "failed", "message": "No database file"}
        db.set_app_meta(conn, key, json.dumps(work_conn_state))
    return JSONResponse({"available": True, "state": "running", "message": "Reading the pages"})


@router.get("/tts")
def read_aloud(text: str = "", lang: str = "en"):
    """One sentence read aloud by the server (espeak-ng), for the reader when the browser has no voices."""
    audio = book_speech.speak(text, lang)
    if audio is None:
        raise HTTPException(503, "Reading aloud needs espeak-ng on the server")
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/define")
def define_text(q: str = "", lang: str = "en"):
    """The meaning of the selected word or phrase, for the reader's Define action."""
    return JSONResponse(book_define.define(q, lang))


@router.post("/{uid}/reading-time")
def add_reading_time(uid: str, seconds: int = Form(0), conn=Depends(get_db)):
    """A beat of reading time from the reader (a few seconds while the book is open and in use)."""
    if db.get_citation_raw(conn, uid) is None:
        raise HTTPException(404)
    return JSONResponse({"today": book_stats.add_time(conn, uid, clock.today().isoformat(), seconds)})


@router.get("/stats")
def reading_stats(range: str = "year", conn=Depends(get_db)):
    """Reading statistics for the week, month, year or all time that holds today."""
    start, end = book_stats.period(range if range in ("week", "month", "year", "all") else "year", clock.today())
    return JSONResponse(book_stats.stats(conn, start, end, clock.today()))


@router.post("/{uid}/bookmarks")
def add_bookmark(uid: str, section: int = Form(0), cfi: str = Form(""), label: str = Form(""), fraction: float = Form(0.0), conn=Depends(get_db)):
    if db.get_citation_raw(conn, uid) is None:
        raise HTTPException(404)
    return JSONResponse({"uid": book_bookmarks.add(conn, uid, section, cfi, label, fraction)})


@router.post("/{uid}/bookmarks/{bid}/delete")
def delete_bookmark(uid: str, bid: str, conn=Depends(get_db)):
    book_bookmarks.remove(conn, uid, bid)
    return JSONResponse({"ok": True})


@router.get("/{uid}/read")
def read_in_app(uid: str, request: Request, edition: str = "", conn=Depends(get_db)):
    c = db.get_citation_raw(conn, uid)
    if c is None:
        raise HTTPException(404)
    paged = _paged_source(conn, uid, edition)
    if paged:
        authors = ", ".join(" ".join(x for x in (a.get("given", ""), a.get("family", "")) if x) for a in c.get("authors") or [])
        euid, fmt, converted, kind = paged["edition"], paged["format"], paged["converted"], paged["kind"]
        ext = "cbz" if kind == "comic" and converted else "epub" if converted and kind == "book" else fmt.lower()
        return templates.TemplateResponse("library_reader_book.html", {
            "request": request, "c": c, "authors": authors,
            "file_url": f"/library/editions/{euid}/converted?format={fmt}" if converted else f"/library/editions/{euid}/file?format={fmt}",
            "file_name": f"book.{ext}", "book_language": (db.get_edition(conn, euid) or {}).get("language") or "", "kind": kind, "is_pdf": kind == "pdf", "is_comic": kind == "comic", "converted": converted, "edition_uid": euid,
            "file_format": fmt, "manga": c.get("type") == "manga", "ocr_available": book_convert.ocr_available(),
            "crumbs": [{"url": "/library", "name": "Library"}],
            "reader": book_reader.settings(conn), "lookups": [x for x in book_reader.lookups(conn) if x["on"]], "colors": book_annotations.COLORS,
            "reader_choices": {k: v[2] for k, v in book_reader.SETTINGS.items()},
            "reader_labels": {k: v[0] for k, v in book_reader.SETTINGS.items()}, "position": book_reader.position(conn, uid), "annotations": book_annotations.listing(conn, uid),
            "bookmarks": book_bookmarks.listing(conn, uid),
            "cited_by": db.list_entries_citing(conn, uid), "reference": citation_formats.bibliography(c), "footnote": citation_formats.footnote(c),
        })
    has_file = any(e.get("calibre_formats") or e.get("file_name") for e in db.list_editions(conn, uid))
    message = ("Its file can't be opened here; the reader opens EPUB, MOBI, FB2, PDF and comics, and Word, OpenDocument, RTF and text"
               " files when Calibre is installed on the server.") if has_file else "It has no book file yet."
    return templates.TemplateResponse("library_reader_missing.html", {"request": request, "c": c, "crumbs": [{"url": "/library", "name": "Library"}],
                                                                       "message": message, "has_file": has_file})


@router.post("/{uid}/annotations")
def add_annotation(uid: str, section: int = Form(0), quote: str = Form(""), note: str = Form(""), cfi: str = Form(""), color: str = Form("yellow"),
                   x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    if db.get_citation_raw(conn, uid) is None:
        raise HTTPException(404)
    made = book_annotations.add(conn, uid, section, quote, note, cfi, color)
    return respond(x_requested_with, f"/library/{uid}/read?section={section}", uid=made)


@router.post("/{uid}/reading-position")
def save_reading_position(uid: str, cfi: str = Form(""), fraction: float = Form(0.0), conn=Depends(get_db)):
    if db.get_citation_raw(conn, uid) is None:
        raise HTTPException(404)
    book_reader.save_position(conn, uid, cfi, fraction)
    return JSONResponse({"ok": True})


@router.post("/{uid}/annotations/{aid}")
def update_annotation(uid: str, aid: str, note: str | None = Form(None), color: str | None = Form(None), conn=Depends(get_db)):
    book_annotations.update(conn, uid, aid, note, color)
    return JSONResponse({"ok": True})


@router.get("/{uid}/search")
def search_in_book(uid: str, q: str = "", edition: str = "", format: str = "", conn=Depends(get_db)):
    """Where the words are in the book, for the reader's search view: a few words around each hit and its page or chapter."""
    if not q.strip():
        return JSONResponse({"hits": []})
    try:
        found = book_search.search(conn, uid, q, edition=edition, fmt=format, limit=book_search.MAX_HITS)
    except book_search.BookError as exc:
        return JSONResponse({"hits": [], "error": str(exc)})
    hits = [{"snippet": h.get("snippet", ""), "section": h["section"], "title": h.get("title") or "", "page": h.get("page")} for h in found["hits"]]
    return JSONResponse({"hits": hits})


@router.post("/{uid}/annotations/{aid}/delete")
def delete_annotation(uid: str, aid: str, section: int = Form(0), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    book_annotations.remove(conn, uid, aid)
    return respond(x_requested_with, f"/library/{uid}/read?section={section}")


@router.get("/{uid}/cover")
def cover_image(uid: str, conn=Depends(get_db)):
    path = db.cover_path(conn, uid)
    if path is None:
        raise HTTPException(404)
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/{uid}/cover/modal")
def cover_modal(uid: str, request: Request, conn=Depends(get_db)):
    """The shared upload modal (upload_modal.html) for a custom cover."""
    c = db.get_citation_raw(conn, uid)
    if c is None:
        raise HTTPException(404)
    return templates.TemplateResponse("upload_modal.html", {
        "request": request, "title": "Cover", "form_id": "cover-upload-form", "upload_action": f"/library/{uid}/cover",
        "field_name": "cover", "input_class": "cover-upload-input", "zone_label": "Choose or drop a cover",
        "preview_url": db.cover_url(c), "delete_url": f"/library/{uid}/cover/remove" if c.get("cover_custom") else "",
        "delete_label": "Remove your cover and show the fetched one again?" if c.get("cover_fetched") else "Remove this cover?",
        "back_url": f"/library/{uid}", "back_mode": "modal",
    })


@router.post("/{uid}/cover")
async def upload_cover(uid: str, cover: UploadFile | None = File(None), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    if db.get_citation_raw(conn, uid) is None:
        raise HTTPException(404)
    data = await cover.read(_CROPPED_COVER_MAX + 1) if cover is not None else b""
    webp = media_metadata.to_webp(data) if data and len(data) <= _CROPPED_COVER_MAX else None
    if webp is None:
        return validation_response({"field": "cover", "message": "That file is not an image Curodav can read"}, x_requested_with, f"/library/{uid}")
    db.set_cover(conn, uid, webp, "custom")
    media_books.push(conn, uid)
    return respond(x_requested_with, f"/library/{uid}")


@router.post("/{uid}/cover/remove")
def remove_cover(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    db.clear_cover(conn, uid, "custom")
    media_books.push(conn, uid)
    return respond(x_requested_with, f"/library/{uid}")


@router.get("/lookup/results")
def lookup_results(kind: str = "book", q: str = "", conn=Depends(get_db)):
    """The Find details pane of the entry window: candidates from the kind's source, as JSON the window fills its fields from."""
    try:
        results = media_metadata.search(kind, q, db.tmdb_key(conn), db.sources_off(conn))
    except media_metadata.LookupError_:
        return {"results": [], "source": _provider_name(conn, kind), "error": f"{_provider_name(conn, kind)} could not be reached. Try again in a moment."}
    return {"results": results, "source": _provider_name(conn, kind), "error": ""}


def _provider_name(conn, kind: str) -> str:
    return media_metadata.PROVIDERS.get(media_metadata.provider_for(kind, db.tmdb_key(conn), db.sources_off(conn)), "No source")


def apply_found(conn, uid: str, found: dict) -> None:
    """What the entry window carries beyond its fields: the source's ids, the total, and the cover (an uploaded one, a removal, or the chosen result's)."""
    current = db.get_citation_raw(conn, uid) or {}
    if found.get("provider") or found.get("id"):
        ids = db.external_ids(current)
        ids[found.get("provider") or "source"] = found.get("id") or ""
        db.set_tracking(conn, uid, {"external_json": json.dumps(ids)})
    if found.get("total") and not current.get("progress_total"):
        db.set_tracking(conn, uid, {"progress_total": media.parse_count(found["total"])})
    if found.get("cover_bytes"):
        webp = media_metadata.to_webp(found["cover_bytes"]) if len(found["cover_bytes"]) <= _CROPPED_COVER_MAX else None
        if webp:
            db.set_cover(conn, uid, webp, "custom")
    elif found.get("cover_remove"):
        db.clear_cover(conn, uid, "custom")
    elif found.get("cover_url") and db.auto_covers(conn):
        data = media_metadata.download_cover(found["cover_url"])
        if data:
            db.set_cover(conn, uid, data, "fetched")


# Settings > Library

def _modal_page(name: str, request: Request, **ctx):
    return templates.TemplateResponse(name, {"request": request, **ctx})


@settings_router.get("/ratings")
def ratings_modal(request: Request, conn=Depends(get_db)):
    criteria = db.list_rating_criteria(conn)
    names = dict(db.type_options(conn, db.CITATION_TYPES))
    for c in criteria:
        c["kind_names"] = ", ".join(names.get(k, k) for k in c["kinds"]) or "All kinds"
    return _modal_page("media_settings_ratings_modal.html", request, scale=db.rating_scale(conn), advanced_rating=db.advanced_rating(conn),
                       scales=[{"uid": k, "name": v[0]} for k, v in media.SCALES.items()], criteria=criteria)


@settings_router.post("/ratings")
def save_ratings(scale: str = Form(media.DEFAULT_SCALE), advanced: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    db.set_rating_scale(conn, scale)
    db.set_advanced_rating(conn, bool(advanced))
    return respond(x_requested_with, SETTINGS)


@settings_router.get("/find")
def find_details_redirect():
    return RedirectResponse(SETTINGS, status_code=303)


@settings_router.post("/find")
def save_find_details(auto_covers: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    db.set_auto_covers(conn, bool(auto_covers))
    return respond(x_requested_with, SETTINGS)


@settings_router.get("/folder")
def book_folder_modal(request: Request, conn=Depends(get_db)):
    return _modal_page("media_settings_library_modal.html", request, **_book_library_state(conn), wiki_url=WIKI_URL)


@settings_router.get("/maintenance")
def maintenance_page(request: Request, conn=Depends(get_db)):
    return _modal_page("settings_library_maintenance.html", request, crumbs=[{"url": SETTINGS, "name": "Library"}], calibre_ready=media_books.library(conn) is not None,
                       jobs=[{"key": k, "label": v[0], "hint": v[1], "confirm": v[2]} for k, v in media_calibre_audit.JOBS.items()], job=media_calibre_audit.job_state(conn))


@settings_router.get("/reader")
def reader_modal(request: Request, conn=Depends(get_db)):
    return _modal_page("media_settings_reader_modal.html", request, reader_rows=book_reader.rows(conn), reader=book_reader.settings(conn))


@settings_router.get("/lookups")
def lookups_modal(request: Request, conn=Depends(get_db)):
    return _modal_page("media_settings_lookups_modal.html", request, on_keys=[l["key"] for l in book_reader.lookups(conn) if l["on"]])


@settings_router.get("")
def library_settings(request: Request, conn=Depends(get_db)):
    criteria = db.list_rating_criteria(conn)
    names = dict(db.type_options(conn, db.CITATION_TYPES))
    for c in criteria:
        c["kind_names"] = ", ".join(names.get(k, k) for k in c["kinds"]) or "All kinds"
    return templates.TemplateResponse("settings_library.html", {
        "request": request, "criteria": criteria, "scale": db.rating_scale(conn),
        "scales": [{"uid": k, "name": v[0]} for k, v in media.SCALES.items()], "auto_covers": db.auto_covers(conn), "advanced_rating": db.advanced_rating(conn),
        **_book_library_state(conn), "sources": _sources(conn), "wiki_url": WIKI_URL, "reader_rows": book_reader.rows(conn), "lookups": book_reader.lookups(conn),
        "jobs": [{"key": k, "label": v[0], "hint": v[1], "confirm": v[2]} for k, v in media_calibre_audit.JOBS.items()], "job": media_calibre_audit.job_state(conn),
        "scale_name": media.SCALES.get(db.rating_scale(conn), ("",))[0], "reader_set": book_reader.settings(conn), "criteria_count": len(criteria),
    })


def _sources(conn) -> list[dict]:
    """One row per lookup source: what it is used for and whether it works right now."""
    key, off = db.tmdb_key(conn), db.sources_off(conn)
    rows = []
    for source, info in media_metadata.SOURCES.items():
        if source in off:
            status = "Off"
        elif info["keyed"] and not key:
            status = "Needs a key"
        else:
            status = "On"
        rows.append({"key": source, "name": media_metadata.PROVIDERS[source], "used_for": info["used_for"], "status": status})
    return rows


@settings_router.get("/sources/{source}/edit")
def source_modal(source: str, request: Request, conn=Depends(get_db)):
    if source not in media_metadata.SOURCES:
        raise HTTPException(404)
    return templates.TemplateResponse("media_source_modal.html", {
        "request": request, "source": source, "name": media_metadata.PROVIDERS[source], "info": media_metadata.SOURCES[source],
        "on": source not in db.sources_off(conn), "has_key": bool(db.tmdb_key(conn)) if source == "tmdb" else False,
    })


@settings_router.post("/sources/{source}")
def save_source(source: str, on: str = Form(""), api_key: str = Form(""), clear_key: str = Form(""),
                x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    if source not in media_metadata.SOURCES:
        raise HTTPException(404)
    db.set_source_off(conn, source, not on)
    if media_metadata.SOURCES[source]["keyed"]:
        if clear_key:
            db.set_tmdb_key(conn, "")
        elif api_key.strip():
            db.set_tmdb_key(conn, api_key)
    return respond(x_requested_with, SETTINGS)


def _book_library_state(conn) -> dict:
    lib = media_books.library(conn)
    media_books.pull_soon(conn)
    new, linked = media_books.counts(conn)
    return {"calibre_path": str(media_books.library_path(conn) or ""), "calibre_ready": lib is not None,
            "calibre_new": new, "calibre_linked": linked, "legacy_files": len(media_books.legacy_files(conn)) if lib else 0}


@settings_router.post("/books")
def save_book_library(path: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    error = media_books.set_library_path(conn, path)
    if error:
        return validation_response({"field": "path", "message": error}, x_requested_with, SETTINGS)
    written = media_books.push_all(conn)
    note = f"{written} books and manga written into the library" if written else ""
    return respond(x_requested_with, f"{SETTINGS}?{urlencode({'note': note})}" if note else SETTINGS, written=written)


@settings_router.post("/books/import")
def import_book_library(x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    media_books.pull_soon(conn, force=True)
    return respond(x_requested_with, f"{SETTINGS}?{urlencode({'note': 'Adding the books in the background, it can take a few minutes'})}", started=True)


@settings_router.post("/books/job")
def run_book_job(job: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    started = media_calibre_audit.start_job(conn, job)
    note = "Started, it runs in the background" if started else "Another job is running, or that job does not exist"
    return respond(x_requested_with, f"{SETTINGS}?{urlencode({'note': note})}", started=started, **media_calibre_audit.job_state(conn))


@settings_router.get("/books/job")
def book_job_state(conn=Depends(get_db)):
    return JSONResponse(media_calibre_audit.job_state(conn))


@settings_router.post("/books/move-files")
def move_book_files(x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    moved, problems = media_books.move_legacy_files(conn)
    note = f"{moved} files moved into the library" + (f"; {len(problems)} could not be moved: {'; '.join(problems[:3])}" if problems else "")
    return respond(x_requested_with, f"{SETTINGS}?{urlencode({'note': note})}", moved=moved, problems=problems)


CALIBRE = "/settings/calibre"


@calibre_router.get("")
def calibre_page(request: Request, conn=Depends(get_db)):
    lib = media_books.library(conn)
    issues = media_calibre_audit.audit(conn) if lib else []
    counts = {k: sum(1 for i in issues if i["kind"] == k) for k in media_calibre_audit.KINDS}
    return templates.TemplateResponse("settings_calibre.html", {
        "request": request, "crumbs": [{"url": SETTINGS, "name": "Library"}], "ready": lib is not None, "path": str(media_books.library_path(conn) or ""), "issues": issues,
        "counts": {k: v for k, v in counts.items() if v}, "kinds": media_calibre_audit.KINDS, "auto": media_calibre_audit.auto_on(conn),
        "books": len(lib.books()) if lib else 0, "linked": len(db.calibre_uuids(conn)),
        "fixable": sum(1 for i in issues if i["fix"]), "chosen": request.query_params.get("kind", ""),
    })


@calibre_router.post("/auto")
def calibre_auto(auto: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    media_calibre_audit.set_auto(conn, bool(auto))
    return respond(x_requested_with, CALIBRE)


@calibre_router.post("/apply")
def calibre_apply(issue: list[str] = Form([]), side: str = Form("calibre"), all: str = Form(""),
                  x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    done = media_calibre_audit.fix_all(conn) if all else media_calibre_audit.apply(conn, issue, side)
    return respond(x_requested_with, f"{CALIBRE}?{urlencode({'note': f'{done} fixed'})}", fixed=done)


@calibre_router.post("/refresh")
def calibre_refresh(x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    got = media_books.pull(conn, force=True)
    note = f"Read the library: {got['added']} added, {got['updated']} updated, {got['unlinked']} unlinked"
    return respond(x_requested_with, f"{CALIBRE}?{urlencode({'note': note})}")


@settings_router.post("/lookups")
async def save_reader_lookups(request: Request, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    form = await request.form()
    error = book_reader.save_lookups(conn, [str(v) for v in form.getlist("on")], str(form.get("add_name") or ""), str(form.get("add_url") or ""), str(form.get("remove") or ""))
    if error:
        return validation_response({"field": "add_url", "message": error}, x_requested_with, SETTINGS)
    return respond(x_requested_with, SETTINGS)


@settings_router.post("/lookups/toggle")
def toggle_reader_lookup(key: str = Form(""), on: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    keys = {l["key"] for l in book_reader.lookups(conn) if l["on"]}
    keys = (keys | {key}) if on else (keys - {key})
    book_reader.save_lookups(conn, sorted(keys))
    return respond(x_requested_with, SETTINGS)


@settings_router.post("/lookups/remove")
def remove_reader_lookup(key: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    book_reader.save_lookups(conn, [l["key"] for l in book_reader.lookups(conn) if l["on"] and l["key"] != key], remove=key)
    return respond(x_requested_with, SETTINGS)


@settings_router.post("/reader")
async def save_reader_settings(request: Request, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    form = await request.form()
    book_reader.save_settings(conn, {k: str(form.get(f"reader_{k}") or "") for k in book_reader.SETTINGS})
    return respond(x_requested_with, SETTINGS)


@settings_router.post("/rating")
def save_rating_mode(advanced: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    db.set_advanced_rating(conn, bool(advanced))
    return respond(x_requested_with, SETTINGS)


@settings_router.post("")
def save_library_settings(scale: str = Form(media.DEFAULT_SCALE), auto_covers: str = Form(""),
                          x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    db.set_rating_scale(conn, scale)
    db.set_auto_covers(conn, bool(auto_covers))
    return respond(x_requested_with, SETTINGS)


def _kind_choices(conn) -> list[dict[str, str]]:
    return [{"uid": k, "name": v} for k, v in db.type_options(conn, db.CITATION_TYPES)]


@settings_router.get("/criteria/new")
@settings_router.get("/criteria/{uid}/edit")
def criterion_modal(request: Request, uid: str = "", conn=Depends(get_db)):
    criterion = next((c for c in db.list_rating_criteria(conn) if c["uid"] == uid), None) if uid else None
    return templates.TemplateResponse("media_criterion_modal.html", {
        "request": request, "criterion": criterion, "kind_items": _kind_choices(conn),
        "weights": [{"uid": w, "name": w} for w in ("0.5", "1", "1.5", "2", "3", "4", "5")],
    })


@settings_router.post("/criteria")
def save_criterion(name: str = Form(...), weight: str = Form("1"), kinds: list[str] = Form([]),
                   uid: str = Form(""), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    if not name.strip():
        return validation_response({"field": "name", "message": "The criterion needs a name"}, x_requested_with, SETTINGS)
    picked = kinds if isinstance(kinds, list) else []
    valid = {k["uid"] for k in _kind_choices(conn)}
    db.save_rating_criterion(conn, name, weight, [k for k in picked if k in valid], uid)
    return respond(x_requested_with, SETTINGS)


@settings_router.post("/criteria/{uid}/delete")
def delete_criterion(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    db.delete_rating_criterion(conn, uid)
    return respond(x_requested_with, SETTINGS)


def form_context(conn, c: dict | None) -> dict:
    """What the book and media window needs for kinds, tracking and ratings."""
    scale = db.rating_scale(conn)
    types = db.type_options(conn, db.CITATION_TYPES)
    custom = db.media_kinds_by_uid(conn)
    kinds = {k: media.kind_for(k, custom) for k, _ in types}
    values = db.citation_ratings(conn, c["uid"]) if c else {}
    criteria = []
    for cr in db.list_rating_criteria(conn):
        shown = cr["kinds"] or [k for k, _ in types]
        criteria.append({**cr, "types": " ".join(shown), "value": media.format_value(media.to_scale(values.get(cr["uid"]), scale))})
    verb = kinds.get((c or {}).get("type") or "", media.BUILTIN["book"]).verb
    return {
        "citation_types": types,
        "statuses": media.status_options(verb),
        "status_verbs": {k: kind.verb for k, kind in kinds.items()},
        "verb_labels": {v: [media.status_label(s, v) for s in media.STATUS_KEYS] for v in media.VERBS},
        "score_choices": [{"uid": k, "name": v} for k, v in media.scale_choices(scale)],
        "score_value": media.format_value(media.to_scale((c or {}).get("score"), scale)),
        "scale_top": media.SCALES[scale][1],
        "criteria": criteria,
        "edition_types": " ".join(k for k, kind in kinds.items() if not kind.screen and not kind.custom),
        "link_types": " ".join(k for k, kind in kinds.items() if kind.screen or kind.custom),
        "series_items": [{"uid": n, "name": n} for n in db.series_options(conn)],
        "advanced_rating": db.advanced_rating(conn),
        "upload_accept": media_books.ACCEPT if media_books.library(conn) else "application/pdf",
    }


def noun(conn, type_key: str) -> str:
    """The word a window uses for an entry: the kind's own name (Book, Manga, Film, a custom kind), else Book or Media."""
    if type_key == "media":
        return "Media"
    kind = db.kind_of(conn, type_key) if conn else media.kind_for(type_key)
    if type_key in media.BUILTIN or kind.custom:
        return kind.name
    return db.book_noun({"type": type_key})


STATUS_COLORS = {"": "gray", "planned": "gray", "current": "blue", "paused": "amber", "finished": "green", "dropped": "coral"}


@router.post("/{uid}/update-field")
async def update_field(uid: str, request: Request, conn=Depends(get_db)):
    """In-place edit from the view window: status, year, and the publisher and ISBN of the first edition."""
    payload = await request.json()
    field, value = payload.get("field"), (payload.get("value") or "")
    value = value.strip()[:200] if isinstance(value, str) else ""
    c = db.get_citation_raw(conn, uid)
    if c is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if field == "status":
        db.set_tracking(conn, uid, {"status": media.normal_status(value)})
    elif field == "score":
        db.set_tracking(conn, uid, {"score": media.from_scale(value, db.rating_scale(conn)) if value else None})
    elif field == "year":
        db.set_citation_year(conn, uid, value)
    elif field in ("publisher", "isbn"):
        editions = db.list_editions(conn, uid) or [db.get_edition(conn, db.save_edition(conn, uid, {}))]
        e = editions[0]
        db.save_edition(conn, uid, {**{k: e.get(k) or "" for k in ("edition", "place", "url", "year", "publisher", "isbn", "doi")}, field: value}, e["uid"])
    else:
        return JSONResponse({"error": f"field '{field}' is not inline-editable"}, status_code=400)
    media_books.push(conn, uid)
    return JSONResponse({"ok": True})


@router.post("/{uid}/sync")
def sync_to_calibre(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    media_books.push(conn, uid)
    return respond(x_requested_with, f"/library/{uid}")


def view_context(conn, c: dict) -> dict:
    """What the view window shows for tracking, ratings and the cover."""
    scale = db.rating_scale(conn)
    item = decorate(conn, [dict(c)])[0]
    values = db.citation_ratings(conn, c["uid"])
    ratings = [{"name": cr["name"], "value": media.stars(values.get(cr["uid"]), scale)}
               for cr in media.criteria_for(db.list_rating_criteria(conn), c.get("type") or "") if values.get(cr["uid"]) is not None]
    verb = db.kind_of(conn, c.get("type") or "book").verb
    return {"m": item, "ratings": ratings, "edit_url": f"/library/{c['uid']}/edit",
            "status_choices": [(k, l, STATUS_COLORS[k]) for k, l in media.status_options(verb)],
            "status_color": STATUS_COLORS.get(c.get("status") or "", "gray"),
            "score_choices": [{"uid": "", "name": "None"}] + [{"uid": k, "name": media.stars(media.from_scale(k, scale), scale) or v} for k, v in media.scale_choices(scale)],
            "score_value": media.format_value(media.to_scale(c.get("score"), scale)), "advanced_rating": db.advanced_rating(conn), "edition_first": (db.list_editions(conn, c["uid"]) or [{}])[0], "has_book": db.kind_of(conn, c.get("type") or "book").uploads}


_EXPORTS = {
    "anime": ("anime-list.xml", "application/xml", lambda conn: media_exchange.mal_xml(conn, "anime")),
    "manga": ("manga-list.xml", "application/xml", lambda conn: media_exchange.mal_xml(conn, "manga")),
    "films": ("films-letterboxd.csv", "text/csv", media_exchange.letterboxd_csv),
    "all": ("curodav-media.json", "application/json", media_exchange.media_json),
}


@settings_router.get("/export/{what}")
def export_media(what: str, conn=Depends(get_db)):
    if what not in _EXPORTS:
        raise HTTPException(404)
    name, mime, build = _EXPORTS[what]
    return Response(build(conn), media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@settings_router.post("/import")
async def import_media(file: UploadFile | None = File(None), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    data = await file.read(20 * 1024 * 1024 + 1) if file is not None and file.filename else b""
    if not data or len(data) > 20 * 1024 * 1024:
        return validation_response({"field": "file", "message": "Choose a MyAnimeList XML, Letterboxd CSV or Curodav JSON file up to 20 MB"}, x_requested_with, DATA_SETTINGS)
    try:
        added, updated = media_exchange.import_file(conn, data, file.filename)
    except (ValueError, UnicodeDecodeError, ET.ParseError) as exc:
        return validation_response({"field": "file", "message": f"That file could not be read: {exc}"}, x_requested_with, DATA_SETTINGS)
    return respond(x_requested_with, f"{DATA_SETTINGS}?{urlencode({'note': f'{added} added, {updated} updated'})}", added=added, updated=updated)


def list_controls(request: Request, conn, types: list[str], sort: str) -> dict:
    """The Library table's sortable column links."""
    from urllib.parse import urlencode as _enc

    keep = [(k, v) for k, v in request.query_params.multi_items() if k not in ("offset", "limit", "fragment", "sort")]
    sorts = {key: "/library?" + _enc(keep + ([("sort", key)] if key != "status" else [])) for key in ("title", "type", "year", "rating", "author")}
    return {"sort_hrefs": sorts, "sort": sort}
