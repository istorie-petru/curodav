"""Library edits shared by the REST API and the MCP server: add or change an entry, its tracking and its ratings.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

The steps follow the library window (routers/notebook.py's `_write_citation`): the same duplicate check, status dates,
rating scale and the copy into the Calibre library for books and manga. Files, covers and editions stay with the window.
Nothing here deletes an entry.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import api_service, clock, db, media
from .api_write import EditError

TEXT_FIELDS = ("title", "subtitle", "year", "container_title", "publisher", "place", "edition", "volume", "issue", "pages",
               "doi", "isbn", "issn", "url", "accessed", "institution", "degree", "editors", "note", "summary")


def entry_types(conn: sqlite3.Connection) -> dict[str, str]:
    """Every type an entry can have, key to name: the built-in kinds, the reading types and the user's own kinds."""
    from .db import media as media_db

    out = {k: v.name for k, v in media.BUILTIN.items()} | dict(media._READ_TYPES)
    for uid, row in media_db.media_kinds_by_uid(conn).items():
        out[media.CUSTOM_PREFIX + uid] = row["name"]
    return out


def _authors(value: Any) -> list[dict[str, str]]:
    """Authors as [{family, given}], from that shape or from plain names ("Kant, Immanuel" or "Immanuel Kant")."""
    out = []
    for a in value or []:
        if isinstance(a, dict):
            family, given = str(a.get("family") or "").strip(), str(a.get("given") or "").strip()
        else:
            name = str(a).strip()
            if "," in name:
                family, given = (p.strip() for p in name.split(",", 1))
            else:
                parts = name.rsplit(" ", 1)
                family, given = (parts[1], parts[0]) if len(parts) == 2 else (name, "")
        if family or given:
            out.append({"family": family, "given": given})
    return out


def save_entry(conn: sqlite3.Connection, *, entry: dict[str, Any], uid: str = "", allow_duplicate: bool = False) -> dict[str, Any]:
    """Adds a library entry, or changes the one with `uid` (fields left out keep their value)."""
    existing = db.get_citation_raw(conn, uid) if uid else None
    if uid and existing is None:
        raise EditError("not_found", f"No library entry with uid {uid}")
    types = entry_types(conn)
    row: dict[str, Any] = {"uid": uid} if uid else {}
    row["type"] = str(entry.get("type") or (existing or {}).get("type") or "book")
    if row["type"] not in types:
        raise EditError("invalid", f"type must be one of {', '.join(types)}")
    for name in TEXT_FIELDS:
        if name in entry:
            row[name] = str(entry[name] if entry[name] is not None else "")
    if not uid and not (row.get("title") or "").strip():
        raise EditError("invalid", "a new entry needs a title")
    if existing:
        row.setdefault("title", existing["title"])
        row.setdefault("year", existing["year"])
        row.setdefault("container_title", existing["container_title"])
        row["authors"] = existing["authors"]
    if "authors" in entry:
        row["authors"] = _authors(entry["authors"])
    if "keywords" in entry:
        row["keywords"] = [str(k) for k in entry["keywords"] or []]
    if not allow_duplicate:
        twin = db.find_duplicate(conn, row, uid)
        if twin:
            raise EditError("invalid", f'"{twin["title"]}" (uid {twin["uid"]}) is already in the library; pass allow_duplicate to keep both')
    saved = db.upsert_citation(conn, row)
    media_books_push(conn, saved)
    return {"uid": saved, "entry": api_service.get_citation(conn, saved)}


def set_tracking(conn: sqlite3.Connection, *, uid: str, status: str | None = None, progress: int | None = None,
                 progress_total: int | None = None, season: int | None = None, started_on: str | None = None,
                 finished_on: str | None = None, rating: float | str | None = None, criteria: dict[str, Any] | None = None) -> dict[str, Any]:
    """Status, progress, dates and ratings of one entry. Ratings are in the user's own scale; a criterion goes by name."""
    from .db import media as media_db

    existing = db.get_citation_raw(conn, uid)
    if existing is None:
        raise EditError("not_found", f"No library entry with uid {uid}")
    scale = media_db.rating_scale(conn)
    row: dict[str, Any] = {"uid": uid}
    for name, value in (("progress", progress), ("progress_total", progress_total), ("season", season),
                        ("started_on", started_on), ("finished_on", finished_on)):
        if value is not None:
            row[name] = value
    if rating is not None:
        row["score"] = media.from_scale(rating, scale)
    if status is not None:
        normal = media.normal_status(status)
        if status and not normal:
            raise EditError("invalid", f"status must be one of {', '.join(media.STATUS_KEYS)}")
        row["status"] = normal
        if normal != (existing.get("status") or ""):
            row = {**media.on_status_change({**existing, **row}, normal, clock.today().isoformat()), **row}
    known = {c["name"].lower(): c["uid"] for c in media_db.list_rating_criteria(conn)}
    unknown = [k for k in (criteria or {}) if k.lower() not in known]
    if unknown:
        raise EditError("invalid", f"unknown rating criteria: {', '.join(unknown)}; known: {', '.join(c for c in known) or 'none'}")
    db.upsert_citation(conn, {**existing, **row})
    if criteria:
        media_db.set_citation_ratings(conn, uid, {known[k.lower()]: media.from_scale(v, scale) for k, v in criteria.items()})
    media_books_push(conn, uid)
    return {"uid": uid, "entry": api_service.get_citation(conn, uid)}


def media_books_push(conn: sqlite3.Connection, uid: str) -> None:
    from . import media_books

    media_books.push(conn, uid)
