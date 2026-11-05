"""Media in the library: the reading and watching now page, covers, automatic details and the Library settings.

Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response

from .. import clock, db, media, media_books, media_exchange, media_metadata
from .. import tags as tag_store
from ..deps import get_db, respond, templates, validation_response

router = APIRouter(prefix="/library", tags=["media"])
settings_router = APIRouter(prefix="/settings/library", tags=["media"])

SETTINGS = "/settings/library"
DATA_SETTINGS = "/settings/data-maintenance"
WIKI_URL = "https://github.com/istorie-petru/curodav/wiki/Library-and-Media"
RECENT_DAYS = 30
NOW_LIMIT = 60
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


def now_sections(conn, filters: dict, statuses: list[str], recent_first: bool) -> dict[str, list[dict]]:
    """What is being read and watched, on hold, up next and finished lately, narrowed by the Library's filters."""
    since = (clock.now().date() - timedelta(days=RECENT_DAYS)).isoformat()
    out = {}
    for key, status in (("current", "current"), ("paused", "paused"), ("planned", "planned"), ("finished", "finished")):
        if statuses and status not in statuses:
            out[key] = []
            continue
        items = db.page_citations(conn, statuses=[status], limit=NOW_LIMIT, **filters)["items"]
        if status == "finished":
            items = [c for c in items if (c.get("finished_on") or "") >= since]
        if recent_first:
            items.sort(key=lambda c: (c.get("finished_on") or "", c.get("updated_at") or "") if status == "finished" else (c.get("updated_at") or ""), reverse=True)
        out[key] = decorate(conn, items)
    reading = [c for c in out["current"] if c["kind"].verb != "watch"]
    watching = [c for c in out["current"] if c["kind"].verb == "watch"]
    return {"reading": reading, "watching": watching, "paused": out["paused"], "planned": out["planned"], "finished": out["finished"]}


@router.get("/now")
def now_page():
    return RedirectResponse("/library", status_code=303)


@router.get("/lookup/cover")
def lookup_cover(u: str = ""):
    """A result's cover, fetched by the server so the page only ever loads images from Curodav itself."""
    data = media_metadata.download_cover(u, thumbnail=True)
    if data is None:
        raise HTTPException(404)
    return Response(data, media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})


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

@settings_router.get("")
def library_settings(request: Request, conn=Depends(get_db)):
    criteria = db.list_rating_criteria(conn)
    names = dict(db.type_options(conn, db.CITATION_TYPES))
    for c in criteria:
        c["kind_names"] = ", ".join(names.get(k, k) for k in c["kinds"]) or "All kinds"
    return templates.TemplateResponse("settings_library.html", {
        "request": request, "criteria": criteria, "scale": db.rating_scale(conn),
        "scales": [{"uid": k, "name": v[0]} for k, v in media.SCALES.items()], "auto_covers": db.auto_covers(conn), "advanced_rating": db.advanced_rating(conn),
        **_book_library_state(conn), "sources": _sources(conn), "wiki_url": WIKI_URL,
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
    media_books.pull(conn)
    plan = media_books.import_plan(conn) if lib else {"new": [], "linked": 0}
    return {"calibre_path": str(media_books.library_path(conn) or ""), "calibre_ready": lib is not None,
            "calibre_new": len(plan["new"]), "calibre_linked": plan["linked"], "legacy_files": len(media_books.legacy_files(conn)) if lib else 0}


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
    count = media_books.import_books(conn)
    return respond(x_requested_with, f"{SETTINGS}?{urlencode({'note': f'{count} books added from the library'})}", imported=count)


@settings_router.post("/books/move-files")
def move_book_files(x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    moved, problems = media_books.move_legacy_files(conn)
    note = f"{moved} files moved into the library" + (f"; {len(problems)} could not be moved: {'; '.join(problems[:3])}" if problems else "")
    return respond(x_requested_with, f"{SETTINGS}?{urlencode({'note': note})}", moved=moved, problems=problems)


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


def view_context(conn, c: dict) -> dict:
    """What the view window shows for tracking, ratings and the cover."""
    scale = db.rating_scale(conn)
    item = decorate(conn, [dict(c)])[0]
    values = db.citation_ratings(conn, c["uid"])
    ratings = [{"name": cr["name"], "value": media.stars(values.get(cr["uid"]), scale)}
               for cr in media.criteria_for(db.list_rating_criteria(conn), c.get("type") or "") if values.get(cr["uid"]) is not None]
    return {"m": item, "ratings": ratings, "edit_url": f"/library/{c['uid']}/edit"}


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
    """The Library page's kind chips (kinds that have entries, with counts) and its sortable column links."""
    from urllib.parse import urlencode as _enc

    params = [(k, v) for k, v in request.query_params.multi_items() if k not in ("after", "type", "sort")]
    counts = db.count_by_type(conn)
    names = dict(db.type_options(conn, db.CITATION_TYPES))
    chips = [{"label": "All", "count": sum(counts.values()), "href": "/library?" + _enc(params + ([("sort", sort)] if sort != "title" else [])), "active": not types}]
    for key, name in db.type_options(conn, db.CITATION_TYPES):
        if counts.get(key):
            chips.append({"label": name, "count": counts[key], "active": key in types,
                          "href": "/library?" + _enc(params + [("type", key)] + ([("sort", sort)] if sort != "title" else [])),
                          "icon": db.kind_of(conn, key).icon})
    for key in ("tag", "shelf"):
        for value in request.query_params.getlist(key):
            rest = [(k, v) for k, v in request.query_params.multi_items() if k != "after" and not (k == key and v == value)]
            chips.append({"label": value, "count": "", "active": True, "href": "/library?" + _enc(rest), "icon": "tag" if key == "tag" else "folder",
                          "removable": True})
    keep = params + [("type", t) for t in types]
    sorts = {key: "/library?" + _enc(keep + ([("sort", key)] if key != "title" else [])) for key in ("title", "type", "year", "rating", "author")}
    return {"kind_chips": chips, "sort_hrefs": sorts, "sort": sort, "kind_names": names}
