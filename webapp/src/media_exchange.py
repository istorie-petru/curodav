"""Media lists in open formats: MyAnimeList XML for anime and manga, Letterboxd CSV for films, and JSON for everything.

Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import csv
import io
import json
import xml.etree.ElementTree as ET
from typing import Any
from xml.sax.saxutils import escape

from . import db, media

_MAL_STATUS = {"anime": {"current": "Watching", "planned": "Plan to Watch"}, "manga": {"current": "Reading", "planned": "Plan to Read"}}
_MAL_COMMON = {"finished": "Completed", "paused": "On-Hold", "dropped": "Dropped"}
_FROM_MAL = {"watching": "current", "reading": "current", "completed": "finished", "on-hold": "paused", "dropped": "dropped",
             "plan to watch": "planned", "plan to read": "planned"}


def _entries(conn, type_key: str) -> list[dict[str, Any]]:
    items = [c for c in db.list_citations(conn) if c["type"] == type_key]
    overall = db.overall_ratings(conn, items)
    for c in items:
        c["overall"] = overall.get(c["uid"])
    return items


def _mal_date(value: str) -> str:
    return value if value and len(value) == 10 else "0000-00-00"


def mal_xml(conn, kind: str) -> bytes:
    """The anime (`kind` anime) or manga list as MyAnimeList's export XML, which AniList and MAL import."""
    statuses = {**_MAL_COMMON, **_MAL_STATUS[kind]}
    out = ['<?xml version="1.0" encoding="UTF-8" ?>', "<myanimelist>", "  <myinfo>", f"    <user_export_type>{1 if kind == 'anime' else 2}</user_export_type>", "  </myinfo>"]
    for c in _entries(conn, kind):
        ids = db.external_ids(c)
        score = round(c["overall"] / 10) if c["overall"] else 0
        common = [f"    <my_start_date>{_mal_date(c['started_on'])}</my_start_date>", f"    <my_finish_date>{_mal_date(c['finished_on'])}</my_finish_date>",
                  f"    <my_score>{score}</my_score>", f"    <my_status>{statuses.get(c['status'], 'Plan to Watch' if kind == 'anime' else 'Plan to Read')}</my_status>",
                  f"    <my_comments><![CDATA[{c['note']}]]></my_comments>", "    <update_on_import>1</update_on_import>"]
        if kind == "anime":
            out += ["  <anime>", f"    <series_animedb_id>{escape(ids.get('mal', '0'))}</series_animedb_id>", f"    <series_title><![CDATA[{c['title']}]]></series_title>",
                    f"    <series_episodes>{c['progress_total']}</series_episodes>", f"    <my_watched_episodes>{c['progress']}</my_watched_episodes>",
                    f"    <my_times_watched>{c['repeats']}</my_times_watched>", *common, "  </anime>"]
        else:
            out += ["  <manga>", f"    <manga_mangadb_id>{escape(ids.get('mal', '0'))}</manga_mangadb_id>", f"    <manga_title><![CDATA[{c['title']}]]></manga_title>",
                    f"    <manga_chapters>{c['progress_total']}</manga_chapters>", f"    <my_read_chapters>{c['progress']}</my_read_chapters>",
                    f"    <my_times_read>{c['repeats']}</my_times_read>", *common, "  </manga>"]
    out.append("</myanimelist>")
    return ("\n".join(out) + "\n").encode("utf-8")


LETTERBOXD_COLUMNS = ["Title", "Year", "Directors", "Rating", "WatchedDate", "Rewatch", "Tags", "Review"]


def letterboxd_csv(conn) -> bytes:
    """Films as a CSV in the columns Letterboxd's importer reads (rating out of 5 in half stars)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(LETTERBOXD_COLUMNS)
    for c in _entries(conn, "film"):
        rating = media.to_scale(c["overall"], "stars5half")
        directors = ", ".join(" ".join(x for x in (a.get("given", ""), a.get("family", "")) if x) for a in c["authors"])
        writer.writerow([c["title"], c["year"], directors,
                         media.format_value(rating), c["finished_on"], "true" if c["repeats"] else "false", ", ".join(c["keywords"]), c["note"]])
    return buf.getvalue().encode("utf-8")


_JSON_FIELDS = ("uid", "type", "title", "subtitle", "authors", "year", "status", "progress", "progress_total", "season", "started_on", "finished_on",
                "repeats", "score", "keywords", "summary", "note", "url", "external_json")


def media_json(conn) -> bytes:
    """Every entry with its tracking and criteria ratings, plus the custom kinds and criteria, as JSON."""
    entries = []
    for c in db.list_citations(conn):
        row = {k: c.get(k) for k in _JSON_FIELDS}
        row["ratings"] = db.citation_ratings(conn, c["uid"])
        entries.append(row)
    return json.dumps({"format": "curodav-media", "version": 1, "kinds": db.list_media_kinds(conn), "criteria": db.list_rating_criteria(conn),
                       "entries": entries}, ensure_ascii=False, indent=1).encode("utf-8")


def _find(conn, type_key: str, title: str, external: tuple[str, str] | None) -> dict[str, Any] | None:
    for c in db.list_citations(conn):
        if c["type"] != type_key:
            continue
        if external and external[1] not in ("", "0") and db.external_ids(c).get(external[0]) == external[1]:
            return c
        if c["title"].strip().lower() == title.strip().lower():
            return c
    return None


def _save(conn, type_key: str, title: str, fields: dict[str, Any], external: tuple[str, str] | None = None) -> bool:
    """Creates the entry or updates the one with the same title (or service id); True when it was new."""
    current = _find(conn, type_key, title, external)
    row = {"type": type_key, "title": title, **fields}
    if current:
        row.update({"uid": current["uid"], "authors": current["authors"], "year": fields.get("year") or current["year"],
                    "container_title": current["container_title"]})
    uid = db.upsert_citation(conn, row)
    if external and external[1] not in ("", "0"):
        ids = db.external_ids(current or {})
        ids[external[0]] = external[1]
        db.set_tracking(conn, uid, {"external_json": json.dumps(ids)})
    return current is None


def _int(text: str | None) -> int:
    return media.parse_count(text or 0)


def _date(text: str | None) -> str:
    text = (text or "").strip()
    return text if len(text) == 10 and not text.startswith("0000") else ""


def import_mal(conn, data: bytes) -> tuple[int, int]:
    """A MyAnimeList (or AniList) XML export; returns (added, updated)."""
    root = ET.fromstring(data)  # noqa: S314 (the owner's own export file; no entities are expanded by ElementTree)
    added = updated = 0
    for node in list(root.findall("anime")) + list(root.findall("manga")):
        anime = node.tag == "anime"
        get = lambda tag: (node.findtext(tag) or "").strip()  # noqa: E731
        title = get("series_title" if anime else "manga_title")
        if not title:
            continue
        score = _int(get("my_score"))
        fields = {"status": _FROM_MAL.get(get("my_status").lower(), ""),
                  "progress": _int(get("my_watched_episodes" if anime else "my_read_chapters")),
                  "progress_total": _int(get("series_episodes" if anime else "manga_chapters")),
                  "started_on": _date(get("my_start_date")), "finished_on": _date(get("my_finish_date")),
                  "repeats": _int(get("my_times_watched" if anime else "my_times_read")), "score": float(score * 10) if score else None}
        if get("my_comments"):
            fields["note"] = get("my_comments")
        new = _save(conn, "anime" if anime else "manga", title, fields, ("mal", get("series_animedb_id" if anime else "manga_mangadb_id")))
        added, updated = added + new, updated + (not new)
    return added, updated


def import_letterboxd(conn, data: bytes) -> tuple[int, int]:
    """A Letterboxd export (diary, watched, ratings or watchlist CSV) or a file in its import columns; returns (added, updated)."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    added = updated = 0
    watchlist = reader.fieldnames is not None and "Rating" not in reader.fieldnames and "Watched Date" not in reader.fieldnames and "WatchedDate" not in reader.fieldnames
    for row in reader:
        title = (row.get("Name") or row.get("Title") or "").strip()
        if not title:
            continue
        rating = media.from_scale(row.get("Rating") or "", "stars5half")
        watched = _date(row.get("Watched Date") or row.get("WatchedDate") or "")
        fields = {"year": (row.get("Year") or "").strip(), "status": "planned" if watchlist else "finished", "finished_on": watched}
        if rating is not None:
            fields["score"] = rating
        if (row.get("Rewatch") or "").strip().lower() in ("yes", "true"):
            fields["repeats"] = 1
        if row.get("Tags"):
            fields["keywords"] = [t.strip() for t in row["Tags"].split(",") if t.strip()]
        new = _save(conn, "film", title, fields, ("letterboxd", (row.get("Letterboxd URI") or row.get("LetterboxdURI") or "").strip()))
        added, updated = added + new, updated + (not new)
    return added, updated


def import_json(conn, data: bytes) -> tuple[int, int]:
    """Curodav's own media JSON; entries are matched by uid, so importing the same file twice changes nothing."""
    payload = json.loads(data)
    if payload.get("format") != "curodav-media":
        raise ValueError("This is not a Curodav media file")
    known_kinds = {k["uid"] for k in db.list_media_kinds(conn)}
    for k in payload.get("kinds", []):
        if k.get("uid") and k["uid"] not in known_kinds:
            db.save_media_kind(conn, k, k["uid"])
    known_criteria = {c["uid"] for c in db.list_rating_criteria(conn)}
    for c in payload.get("criteria", []):
        if c.get("uid") and c["uid"] not in known_criteria:
            db.save_rating_criterion(conn, c.get("name", ""), c.get("weight", 1), c.get("kinds", []), c["uid"])
    criteria = {c["uid"] for c in db.list_rating_criteria(conn)}
    added = updated = 0
    for e in payload.get("entries", []):
        exists = db.get_citation_raw(conn, e.get("uid") or "") is not None
        row = {k: e[k] for k in _JSON_FIELDS if k in e and k != "external_json"}
        uid = db.upsert_citation(conn, row)
        if e.get("external_json"):
            db.set_tracking(conn, uid, {"external_json": e["external_json"]})
        db.set_citation_ratings(conn, uid, {k: v for k, v in (e.get("ratings") or {}).items() if k in criteria})
        added, updated = added + (not exists), updated + exists
    return added, updated


def import_file(conn, data: bytes, filename: str) -> tuple[int, int]:
    """Picks the importer from the file: XML is MyAnimeList, CSV is Letterboxd, JSON is Curodav's own."""
    name = (filename or "").lower()
    head = data.lstrip()[:64]
    if name.endswith(".xml") or head.startswith(b"<"):
        return import_mal(conn, data)
    if name.endswith(".json") or head.startswith(b"{"):
        return import_json(conn, data)
    return import_letterboxd(conn, data)
