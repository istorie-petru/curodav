"""Automatic backups: a complete copy of the database at 10:00 and 18:00 and at every server start, kept a week, and the
ways back from one: the whole database, or only one note or one discipline.

Feature document: curodav-notes/documentation/features/api-and-mcp.md (Backups)

A copy is made with SQLite's online backup API and stored gzipped in `<backup_dir>/snapshots`, named
`curodav-<YYYYMMDD-HHMM>-<kind>.sqlite.gz` in the user's time. A daily copy that was missed because the server was off is
made when the scheduler first runs after its time. The JSON backups of Settings, Data stay for moving data elsewhere.
A whole restore keeps a "before restoring" copy first; restoring one thing records an API change, so it has its own Undo.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from . import clock
from .log import get_logger

logger = get_logger(__name__)

DAILY = {"morning": "10:00", "evening": "18:00"}
KINDS = {"morning": "Morning", "evening": "Evening", "start": "Server start", "restore": "Before restoring"}
KEEP_DAYS = 7
KEEP_START = 5
_NAME = re.compile(r"^curodav-(\d{8})-(\d{4})-(morning|evening|start|restore)\.sqlite\.gz$")
_lock = threading.Lock()


def folder(backup_dir: Path) -> Path:
    return Path(backup_dir) / "snapshots"


def _local_now() -> datetime:
    return clock.now().astimezone()


def make(db_path: Path, backup_dir: Path, kind: str) -> Path:
    """Copies the live database into a new compressed backup and prunes old ones."""
    target_dir = folder(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = _local_now().strftime("%Y%m%d-%H%M")
    path = target_dir / f"curodav-{stamp}-{kind}.sqlite.gz"
    with _lock, tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "copy.sqlite"
        source, copy = sqlite3.connect(db_path), sqlite3.connect(raw)
        try:
            source.backup(copy)
        finally:
            copy.close()
            source.close()
        partial = path.with_suffix(".gz.part")
        with open(raw, "rb") as fin, gzip.open(partial, "wb", compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout)
        partial.replace(path)
    prune(backup_dir)
    return path


def _entry(path: Path) -> dict[str, Any] | None:
    match = _NAME.match(path.name)
    if not match:
        return None
    at = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M")
    return {"name": path.name, "kind": match.group(3), "label": KINDS[match.group(3)], "at": at, "day": at.date().isoformat(),
            "time": at.strftime("%H:%M"), "size": path.stat().st_size, "size_label": f"{path.stat().st_size / 1_000_000:.1f} MB"}


def list_backups(backup_dir: Path) -> list[dict[str, Any]]:
    """Every automatic backup, newest first."""
    target = folder(backup_dir)
    if not target.exists():
        return []
    found = [e for e in (_entry(p) for p in target.glob("curodav-*.sqlite.gz")) if e]
    return sorted(found, key=lambda e: (e["at"], e["name"]), reverse=True)


def timeline(backup_dir: Path) -> list[dict[str, Any]]:
    """The last KEEP_DAYS days, newest first, each with its backups in time order."""
    today = _local_now().date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(KEEP_DAYS)]
    by_day: dict[str, list[dict[str, Any]]] = {d: [] for d in days}
    for e in list_backups(backup_dir):
        if e["day"] in by_day:
            by_day[e["day"]].append(e)
    return [{"day": d, "backups": sorted(by_day[d], key=lambda e: e["at"])} for d in days]


def prune(backup_dir: Path) -> int:
    """Removes backups older than KEEP_DAYS, and start backups beyond the last KEEP_START."""
    cutoff = (_local_now() - timedelta(days=KEEP_DAYS)).replace(tzinfo=None)
    removed, starts = 0, 0
    for e in list_backups(backup_dir):
        old = e["at"] < cutoff
        if e["kind"] == "start":
            starts += 1
            old = old or starts > KEEP_START
        if old:
            (folder(backup_dir) / e["name"]).unlink(missing_ok=True)
            removed += 1
    return removed


def due(backup_dir: Path) -> list[str]:
    """The daily backups whose time has come today and that are not made yet."""
    now = _local_now()
    today = now.date().isoformat()
    made = {e["kind"] for e in list_backups(backup_dir) if e["day"] == today}
    return [kind for kind, at in DAILY.items() if now.strftime("%H:%M") >= at and kind not in made]


def run_due(db_path: Path, backup_dir: Path) -> list[Path]:
    out = []
    for kind in due(backup_dir):
        try:
            out.append(make(db_path, backup_dir, kind))
        except Exception:
            logger.exception("Automatic %s backup failed", kind)
    return out


def start_scheduler(db_path: Path, backup_dir: Path) -> threading.Event:
    """Makes the server-start backup, then checks once a minute for a daily one that is due."""
    stop = threading.Event()

    def loop() -> None:
        try:
            make(db_path, backup_dir, "start")
        except Exception:
            logger.exception("Server start backup failed")
        while not stop.is_set():
            run_due(db_path, backup_dir)
            stop.wait(60)

    threading.Thread(target=loop, daemon=True, name="auto-backups").start()
    return stop


def _path(backup_dir: Path, name: str) -> Path:
    if not _NAME.match(name or ""):
        raise FileNotFoundError(name)
    path = folder(backup_dir) / name
    if not path.exists():
        raise FileNotFoundError(name)
    return path


@contextmanager
def opened(backup_dir: Path, name: str) -> Iterator[sqlite3.Connection]:
    """A read-only connection to a backup, unpacked to a temporary file."""
    path = _path(backup_dir, name)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "backup.sqlite"
        with gzip.open(path, "rb") as fin, open(raw, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        conn = sqlite3.connect(f"file:{raw}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


_AREAS = {
    "Notes": "SELECT count(*), max(updated_at) FROM notebook_documents WHERE is_template = 0",
    "Tasks": "SELECT count(*), max(updated_at) FROM tasks",
    "Events": "SELECT count(*), max(updated_at) FROM events",
    "Contacts": "SELECT count(*), max(updated_at) FROM contacts",
    "Library": "SELECT count(*), max(updated_at) FROM citations",
}


def _counts(conn: sqlite3.Connection) -> dict[str, tuple[int, str]]:
    out = {}
    for area, sql in _AREAS.items():
        try:
            n, latest = conn.execute(sql).fetchone()
        except sqlite3.Error:
            n, latest = 0, None
        out[area] = (n or 0, (latest or "")[:16].replace("T", " "))
    return out


def _disciplines(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for table in ("university_sheet", "university_slots", "university_milestones", "university_topics", "university_readings"):
        try:
            keys |= {(r[0], r[1]) for r in conn.execute(f"SELECT DISTINCT semester_uid, discipline_tag FROM {table}")}
        except sqlite3.Error:
            pass
    return keys


def compare(live: sqlite3.Connection, backup_dir: Path, name: str) -> dict[str, Any]:
    """What differs between a backup and now: counts per area, and the notes and disciplines that are not the same."""
    from . import api_history

    with opened(backup_dir, name) as old:
        before, now = _counts(old), _counts(live)
        areas = [{"area": a, "then": before[a][0], "now": now[a][0], "then_latest": before[a][1], "now_latest": now[a][1]} for a in _AREAS]
        then_notes = {r["uid"]: (r["title"], r["updated_at"]) for r in old.execute("SELECT uid, title, updated_at FROM notebook_documents WHERE is_template = 0")}
        now_notes = {r["uid"]: (r["title"], r["updated_at"]) for r in live.execute("SELECT uid, title, updated_at FROM notebook_documents WHERE is_template = 0")}
        notes = [{"uid": uid, "title": then[0] or "Untitled", "state": "deleted since" if uid not in now_notes else "changed since"}
                 for uid, then in then_notes.items() if now_notes.get(uid) != then]
        semesters = {r["uid"]: r["name"] for r in old.execute("SELECT uid, name FROM university_semesters")} if _has(old, "university_semesters") else {}
        disciplines = []
        for sem, tag in sorted(_disciplines(old)):
            if not _same(api_history.take(old, "discipline", [sem, tag]), api_history.take(live, "discipline", [sem, tag])):
                disciplines.append({"semester_uid": sem, "semester": semesters.get(sem, ""), "name": tag})
    notes.sort(key=lambda n: n["title"].lower())
    return {"areas": areas, "notes": notes, "disciplines": disciplines}


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def restore_all(db_path: Path, backup_dir: Path, name: str) -> Path:
    """Replaces the whole database with a backup, keeping the current one as a "before restoring" backup first. The
    pages are copied into the live file, so open connections see the restored data; migrations then bring an older
    backup up to date."""
    from . import db

    path = _path(backup_dir, name)
    safety = make(db_path, backup_dir, "restore")
    with _lock, tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "restore.sqlite"
        with gzip.open(path, "rb") as fin, open(raw, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        source, live = sqlite3.connect(raw), sqlite3.connect(db_path)
        try:
            source.backup(live)
        finally:
            source.close()
            live.close()
    with db.connect(db_path):
        pass
    return safety


def restore_one(live: sqlite3.Connection, backup_dir: Path, name: str, kind: str, key: Any) -> str:
    """Brings back one note or one discipline as it was in the backup; returns the change uid, whose Undo reverses it."""
    from . import api_history

    if kind not in ("note", "discipline"):
        raise ValueError(kind)
    with opened(backup_dir, name) as old:
        then = api_history.take(old, kind, key)
    then = json.loads(json.dumps(then, default=str))
    now = api_history.take(live, kind, key)
    label = (then or {}).get("doc", {}).get("title") if kind == "note" else (key[1] if then else "")
    api_history.RESTORES[kind](live, key, then)
    return api_history.record(live, tool="restore_from_backup", summary=f"Restored {label or 'an item'} from the {name[8:21]} backup",
                              kind=kind, key=key, before=now, after=api_history.take(live, kind, key), source="backup")
