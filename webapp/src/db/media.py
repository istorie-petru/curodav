"""Media in the library: custom kinds, rating criteria and values, covers, progress and the reading and watching now page.

Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import media
from .citation_library import files_dir
from .core import get_app_meta, set_app_meta

SCALE_KEY = "media_rating_scale"
AUTO_COVERS_KEY = "media_auto_covers"
TMDB_KEY = "media_tmdb_key"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rating_scale(conn: sqlite3.Connection) -> str:
    value = get_app_meta(conn, SCALE_KEY)
    return value if value in media.SCALES else media.DEFAULT_SCALE


def set_rating_scale(conn: sqlite3.Connection, scale: str) -> None:
    if scale in media.SCALES:
        set_app_meta(conn, SCALE_KEY, scale)


def auto_covers(conn: sqlite3.Connection) -> bool:
    return get_app_meta(conn, AUTO_COVERS_KEY) != "0"


def set_auto_covers(conn: sqlite3.Connection, on: bool) -> None:
    set_app_meta(conn, AUTO_COVERS_KEY, "1" if on else "0")


def tmdb_key(conn: sqlite3.Connection) -> str:
    """The TMDB key lives with the other secrets, outside the database, so backups never carry it."""
    from .. import secret_store

    return secret_store.get(conn, TMDB_KEY) or ""


def set_tmdb_key(conn: sqlite3.Connection, key: str) -> None:
    from .. import secret_store

    if key.strip():
        secret_store.put(conn, TMDB_KEY, key.strip())
    else:
        secret_store.remove(conn, TMDB_KEY)


# Custom kinds

def list_media_kinds(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM media_kinds ORDER BY position, name COLLATE NOCASE")]


def media_kinds_by_uid(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {k["uid"]: k for k in list_media_kinds(conn)}


def save_media_kind(conn: sqlite3.Connection, fields: dict[str, Any], uid: str = "") -> str:
    values = {
        "name": (fields.get("name") or "").strip()[:60] or "Other",
        "icon": fields.get("icon") if fields.get("icon") in media.ICONS else "folder",
        "verb": fields.get("verb") if fields.get("verb") in media.VERBS else "read",
        "unit": fields.get("unit") if fields.get("unit") in media.UNITS else "none",
    }
    if uid and conn.execute("SELECT 1 FROM media_kinds WHERE uid = ?", (uid,)).fetchone():
        conn.execute(f"UPDATE media_kinds SET {', '.join(f'{k} = ?' for k in values)} WHERE uid = ?", [*values.values(), uid])
    else:
        uid = uid or str(uuid.uuid4())
        position = conn.execute("SELECT coalesce(max(position), 0) + 1 FROM media_kinds").fetchone()[0]
        conn.execute("INSERT INTO media_kinds (uid, name, icon, verb, unit, position, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (uid, *values.values(), position, _now()))
    conn.commit()
    return uid


def media_kind_usage(conn: sqlite3.Connection, uid: str) -> int:
    return conn.execute("SELECT count(*) FROM citations WHERE type = ?", (media.CUSTOM_PREFIX + uid,)).fetchone()[0]


def delete_media_kind(conn: sqlite3.Connection, uid: str) -> None:
    """The entries of a deleted kind are kept and become Other."""
    conn.execute("UPDATE citations SET type = 'other' WHERE type = ?", (media.CUSTOM_PREFIX + uid,))
    conn.execute("DELETE FROM media_kinds WHERE uid = ?", (uid,))
    conn.execute("UPDATE rating_criteria SET kinds_json = (SELECT json_group_array(value) FROM json_each(rating_criteria.kinds_json) WHERE value != ?)",
                 (media.CUSTOM_PREFIX + uid,))
    conn.commit()


def type_options(conn: sqlite3.Connection, builtin: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Every type an entry can take: the built-in ones, then the custom kinds before Other."""
    custom = [(media.CUSTOM_PREFIX + k["uid"], k["name"]) for k in list_media_kinds(conn)]
    return [t for t in builtin if t[0] != "other"] + custom + [t for t in builtin if t[0] == "other"]


def kind_of(conn: sqlite3.Connection, type_key: str) -> media.Kind:
    return media.kind_for(type_key, media_kinds_by_uid(conn) if type_key.startswith(media.CUSTOM_PREFIX) else None)


# Rating criteria

def list_rating_criteria(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = []
    for r in conn.execute("SELECT * FROM rating_criteria ORDER BY position, name COLLATE NOCASE"):
        d = dict(r)
        try:
            d["kinds"] = [str(k) for k in json.loads(d.pop("kinds_json") or "[]")]
        except (ValueError, TypeError):
            d["kinds"] = []
        rows.append(d)
    return rows


def save_rating_criterion(conn: sqlite3.Connection, name: str, weight: Any, kinds: list[str], uid: str = "") -> str:
    try:
        w = min(max(float(str(weight).replace(",", ".")), 0.1), 10.0)
    except (TypeError, ValueError):
        w = 1.0
    values = (name.strip()[:60] or "Criterion", w, json.dumps(sorted(set(kinds))))
    if uid and conn.execute("SELECT 1 FROM rating_criteria WHERE uid = ?", (uid,)).fetchone():
        conn.execute("UPDATE rating_criteria SET name = ?, weight = ?, kinds_json = ? WHERE uid = ?", (*values, uid))
    else:
        uid = uid or str(uuid.uuid4())
        position = conn.execute("SELECT coalesce(max(position), 0) + 1 FROM rating_criteria").fetchone()[0]
        conn.execute("INSERT INTO rating_criteria (uid, name, weight, kinds_json, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (uid, *values, position, _now()))
    conn.commit()
    return uid


def delete_rating_criterion(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM citation_ratings WHERE criterion_uid = ?", (uid,))
    conn.execute("DELETE FROM rating_criteria WHERE uid = ?", (uid,))
    conn.commit()


def citation_ratings(conn: sqlite3.Connection, citation_uid: str) -> dict[str, float]:
    return {r[0]: r[1] for r in conn.execute("SELECT criterion_uid, value FROM citation_ratings WHERE citation_uid = ?", (citation_uid,))}


def set_citation_ratings(conn: sqlite3.Connection, citation_uid: str, values: dict[str, float | None]) -> None:
    """Replaces the criteria values named in `values`; None clears one."""
    for criterion, value in values.items():
        conn.execute("DELETE FROM citation_ratings WHERE citation_uid = ? AND criterion_uid = ?", (citation_uid, criterion))
        if value is not None:
            conn.execute("INSERT INTO citation_ratings (citation_uid, criterion_uid, value) VALUES (?, ?, ?)", (citation_uid, criterion, value))
    conn.commit()


def overall_ratings(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> dict[str, float | None]:
    """The overall rating of each entry of a page, read in one query for the criteria values."""
    uids = [c["uid"] for c in items]
    values: dict[str, dict[str, float]] = {u: {} for u in uids}
    if uids:
        for r in conn.execute(f"SELECT citation_uid, criterion_uid, value FROM citation_ratings WHERE citation_uid IN ({','.join('?' for _ in uids)})", uids):
            values[r[0]][r[1]] = r[2]
    criteria = list_rating_criteria(conn)
    return {c["uid"]: media.overall(c.get("score"), media.criteria_for(criteria, c.get("type") or ""), values[c["uid"]]) for c in items}


def delete_citation_media(conn: sqlite3.Connection, citation_uid: str) -> None:
    """Removes the ratings and cover files of an entry about to be deleted."""
    row = conn.execute("SELECT cover_fetched, cover_custom FROM citations WHERE uid = ?", (citation_uid,)).fetchone()
    if row:
        for name in (row[0], row[1]):
            if name:
                (covers_dir(conn) / name).unlink(missing_ok=True)
    conn.execute("DELETE FROM citation_ratings WHERE citation_uid = ?", (citation_uid,))
    conn.execute("DELETE FROM media_progress_log WHERE citation_uid = ?", (citation_uid,))
    conn.execute("DELETE FROM object_tags WHERE object_type = 'media' AND object_id = ?", (citation_uid,))


# Covers

def covers_dir(conn: sqlite3.Connection) -> Path:
    return files_dir(conn) / "covers"


def set_cover(conn: sqlite3.Connection, citation_uid: str, data: bytes, which: str) -> str:
    """Stores already converted WebP bytes as the fetched or the custom cover; returns the file name."""
    column = "cover_custom" if which == "custom" else "cover_fetched"
    folder = covers_dir(conn)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{citation_uid}-{which}-{hashlib.md5(data).hexdigest()[:10]}.webp"
    (folder / name).write_bytes(data)
    clear_cover(conn, citation_uid, which, commit=False)
    conn.execute(f"UPDATE citations SET {column} = ? WHERE uid = ?", (name, citation_uid))
    conn.commit()
    return name


def clear_cover(conn: sqlite3.Connection, citation_uid: str, which: str, commit: bool = True) -> None:
    column = "cover_custom" if which == "custom" else "cover_fetched"
    row = conn.execute(f"SELECT {column} FROM citations WHERE uid = ?", (citation_uid,)).fetchone()
    if row and row[0]:
        (covers_dir(conn) / row[0]).unlink(missing_ok=True)
    conn.execute(f"UPDATE citations SET {column} = '' WHERE uid = ?", (citation_uid,))
    if commit:
        conn.commit()


def cover_name(c: dict[str, Any]) -> str:
    """The cover shown: the custom one when there is one, else the fetched one."""
    return c.get("cover_custom") or c.get("cover_fetched") or ""


def cover_path(conn: sqlite3.Connection, citation_uid: str) -> Path | None:
    row = conn.execute("SELECT cover_custom, cover_fetched FROM citations WHERE uid = ?", (citation_uid,)).fetchone()
    name = (row[0] or row[1]) if row else ""
    path = covers_dir(conn) / name if name else None
    return path if path and path.is_file() else None


def cover_url(c: dict[str, Any]) -> str:
    name = cover_name(c)
    return f"/library/{c['uid']}/cover?v={name.rsplit('-', 1)[-1].split('.')[0]}" if name else ""


# Tracking

def set_tracking(conn: sqlite3.Connection, citation_uid: str, fields: dict[str, Any]) -> None:
    allowed = {"progress", "progress_total", "season", "repeats", "status", "started_on", "finished_on", "score", "summary", "external_json"}
    values = {k: v for k, v in fields.items() if k in allowed}
    if values:
        conn.execute(f"UPDATE citations SET {', '.join(f'{k} = ?' for k in values)}, updated_at = ? WHERE uid = ?", [*values.values(), _now(), citation_uid])
        conn.commit()


def external_ids(c: dict[str, Any]) -> dict[str, str]:
    try:
        data = json.loads(c.get("external_json") or "{}")
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def now_sections(conn: sqlite3.Connection, recent_since: str, limit: int = 24) -> dict[str, list[dict[str, Any]]]:
    """The entries of the now page: in progress, on hold, up next and finished since `recent_since`, newest activity first."""
    from .notebook import _attach_citation_authors

    def rows(where: str, order: str, args: tuple = ()) -> list[dict[str, Any]]:
        found = conn.execute(f"SELECT * FROM citations WHERE {where} ORDER BY {order} LIMIT ?", (*args, limit)).fetchall()
        return [_attach_citation_authors(dict(r)) for r in found]

    return {
        "current": rows("status = 'current'", "updated_at DESC"),
        "paused": rows("status = 'paused'", "updated_at DESC"),
        "planned": rows("status = 'planned'", "updated_at DESC"),
        "finished": rows("status = 'finished' AND finished_on >= ?", "finished_on DESC, updated_at DESC", (recent_since,)),
    }


# Editions kept in the Calibre library

def set_edition_calibre(conn: sqlite3.Connection, edition_uid: str, calibre_uuid: str, formats: str) -> None:
    conn.execute("UPDATE citation_editions SET calibre_uuid = ?, calibre_formats = ? WHERE uid = ?", (calibre_uuid, formats, edition_uid))
    conn.commit()


def calibre_uuids(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT calibre_uuid FROM citation_editions WHERE calibre_uuid != ''")}


def editions_with_local_files(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Editions whose file is in Curodav's own store, with the entry's title and type."""
    rows = conn.execute("SELECT e.uid, e.citation_uid, e.file_label, c.title, c.type FROM citation_editions e JOIN citations c ON c.uid = e.citation_uid "
                        "WHERE e.file_name != '' ORDER BY c.title COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def editions_in_calibre(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM citation_editions WHERE calibre_uuid != '' ORDER BY citation_uid, created_at").fetchall()
    return [dict(r) for r in rows]


def count_by_type(conn: sqlite3.Connection) -> dict[str, int]:
    return {r[0]: r[1] for r in conn.execute("SELECT type, count(*) FROM citations GROUP BY type")}


def log_progress(conn: sqlite3.Connection, citation_uid: str, day: str, before: int, after: int) -> None:
    """Adds a change of progress to the day's row of the work's log; nothing is logged when it did not move."""
    if after == before:
        return
    conn.execute("INSERT INTO media_progress_log (citation_uid, day, delta, progress) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(citation_uid, day) DO UPDATE SET delta = delta + excluded.delta, progress = excluded.progress",
                 (citation_uid, day, after - before, after))
    conn.commit()


def progress_log(conn: sqlite3.Connection, citation_uid: str, limit: int = 14) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT day, delta, progress FROM media_progress_log WHERE citation_uid = ? AND delta != 0 ORDER BY day DESC LIMIT ?",
                        (citation_uid, limit)).fetchall()
    return [dict(r) for r in rows]
