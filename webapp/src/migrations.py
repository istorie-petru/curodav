"""Numbered, idempotent schema migrations (rules/backend-conventions.md, rule 3).

Each migration runs once, in order, on startup, and is safe to run twice. A migration that drops or reshapes data
is marked destructive: the database file is copied next to itself first. Released migrations are never edited;
a change is a new migration. Steps older than this runner still live in `db.init_schema`.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .migrations_citations import citation_editions


@dataclass(frozen=True)
class Migration:
    number: int
    name: str
    apply: Callable[[sqlite3.Connection], None]
    destructive: bool = False


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _note_templates(conn: sqlite3.Connection) -> None:
    if "is_template" not in _columns(conn, "notebook_documents"):
        conn.execute("ALTER TABLE notebook_documents ADD COLUMN is_template INTEGER NOT NULL DEFAULT 0")


def _field_config_without_required(conn: sqlite3.Connection) -> None:
    if "required" in _columns(conn, "notebook_field_config"):
        conn.execute("ALTER TABLE notebook_field_config DROP COLUMN required")


def _finance_tables(conn: sqlite3.Connection) -> None:
    from . import finance

    finance.ensure_schema(conn)


def _finance_looks(conn: sqlite3.Connection) -> None:
    from . import finance

    finance.add_look_columns(conn)


def _free_finance_tags(conn: sqlite3.Connection) -> None:
    from . import finance

    finance.free_tags(conn)


def _event_series_tables(conn: sqlite3.Connection) -> None:
    if "series_uid" not in _columns(conn, "events"):
        conn.execute("ALTER TABLE events ADD COLUMN series_uid TEXT")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS event_series (uid TEXT PRIMARY KEY, rule TEXT NOT NULL, anchor TEXT NOT NULL, "
        "extended_until TEXT, holiday_calendar TEXT, exclude_saturday INTEGER NOT NULL DEFAULT 0, exclude_sunday INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_series ON events(series_uid)")


def _repeating_events_become_rows(conn: sqlite3.Connection) -> None:
    """Every legacy repeating event (an RRULE plus per-occurrence exceptions) becomes a series of real event rows.
    The first occurrence keeps the original uid; cancelled occurrences are not created, moved ones are created
    where they were moved. A rule that cannot be read is left exactly as it was."""
    from . import db, event_series

    uids = [r[0] for r in conn.execute("SELECT uid FROM events WHERE recurrence IS NOT NULL AND TRIM(recurrence) != ''").fetchall()]
    for uid in uids:
        master = db.get_event(conn, uid)
        if master:
            event_series.migrate_master(conn, master)


def _notes_have_one_label_and_project(conn: sqlite3.Connection) -> None:
    """Notes keep their first project and first label; the dropped ones are kept as a report for the Notebook home."""
    import json

    from . import db

    report = db.enforce_one_label_and_project(conn)
    if report:
        db.set_app_meta(conn, "notebook_label_report", json.dumps(report))


def _glossary_terms_become_entries(conn: sqlite3.Connection) -> None:
    """Glossary terms gain a kind, alternate names and a wiki note; every existing term becomes an entry of kind Term."""
    cols = _columns(conn, "glossary_terms")
    if "kind" not in cols:
        conn.execute("ALTER TABLE glossary_terms ADD COLUMN kind TEXT NOT NULL DEFAULT 'Term'")
    if "aliases_json" not in cols:
        conn.execute("ALTER TABLE glossary_terms ADD COLUMN aliases_json TEXT NOT NULL DEFAULT '[]'")
    if "wiki_uid" not in cols:
        conn.execute("ALTER TABLE glossary_terms ADD COLUMN wiki_uid TEXT NOT NULL DEFAULT ''")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS entry_kinds (name TEXT PRIMARY KEY, icon TEXT NOT NULL DEFAULT 'tag', "
        "color TEXT NOT NULL DEFAULT 'teal', position REAL NOT NULL DEFAULT 0)"
    )
    conn.execute("INSERT OR IGNORE INTO entry_kinds (name, icon, color, position) VALUES ('Term', 'tag', 'teal', 0)")


_CITATION_EXTRA_COLUMNS = ['subtitle', 'edition', 'volume', 'issue', 'pages', 'publisher', 'place', 'isbn', 'issn', 'accessed', 'institution', 'degree', 'editors', 'note']


def _citations_get_academic_fields(conn: sqlite3.Connection) -> None:
    """Citations gain the fields academic formats need (publisher, place, edition, volume, issue, pages and more)."""
    have = _columns(conn, "citations")
    for column in _CITATION_EXTRA_COLUMNS:
        if column not in have:
            conn.execute(f"ALTER TABLE citations ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")


def _notes_can_be_journal_entries(conn: sqlite3.Connection) -> None:
    if "journal_date" not in _columns(conn, "notebook_documents"):
        conn.execute("ALTER TABLE notebook_documents ADD COLUMN journal_date TEXT NOT NULL DEFAULT ''")


def _notes_can_be_pinned(conn: sqlite3.Connection) -> None:
    if "pinned" not in _columns(conn, "notebook_documents"):
        conn.execute("ALTER TABLE notebook_documents ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")


def _journal_notes_become_weekly(conn: sqlite3.Connection) -> None:
    """Journal notes are one per ISO week (`2026-42`) instead of one per day; the first note of a week keeps the entry."""
    from datetime import date

    have = _columns(conn, "notebook_documents")
    if "journal_week" not in have:
        conn.execute("ALTER TABLE notebook_documents ADD COLUMN journal_week TEXT NOT NULL DEFAULT ''")
    if "journal_date" in have:
        taken: set[str] = set()
        for uid, day in conn.execute("SELECT uid, journal_date FROM notebook_documents WHERE journal_date != '' ORDER BY journal_date").fetchall():
            try:
                year, week, _ = date.fromisoformat(day).isocalendar()
            except ValueError:
                continue
            key = f"{year}-{week:02d}"
            if key not in taken:
                taken.add(key)
                conn.execute("UPDATE notebook_documents SET journal_week = ?, title = CASE WHEN title = ? THEN ? ELSE title END WHERE uid = ?", (key, day, key, uid))
        conn.execute("ALTER TABLE notebook_documents DROP COLUMN journal_date")


def _entry_kinds_get_fields(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS entry_kind_fields (kind TEXT NOT NULL, name TEXT NOT NULL, position REAL NOT NULL DEFAULT 0, "
        "PRIMARY KEY (kind, name))"
    )


def _references_get_pages(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(glossary_term_references)")}
    for column in ("page_start", "page_end"):
        if column not in existing:
            conn.execute(f"ALTER TABLE glossary_term_references ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")


def _timing_statistics(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS perf_daily (day TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, "
        "count INTEGER NOT NULL DEFAULT 0, total_ms REAL NOT NULL DEFAULT 0, max_ms REAL NOT NULL DEFAULT 0, "
        "slow INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, kind, name))"
    )


def _tag_tables(conn: sqlite3.Connection) -> None:
    from . import tags

    tags.ensure_schema(conn)


def _habit_is_not_a_label(conn: sqlite3.Connection) -> None:
    """Habits get their own flag: tasks carrying the habit label are marked, then the label disappears everywhere
    (links on tasks and events, its label row and the setting that named it)."""
    from .db.core import _ensure_column

    _ensure_column(conn, "tasks", "is_habit", "INTEGER NOT NULL DEFAULT 0")
    try:
        row = conn.execute("SELECT habit_label FROM task_habit_settings WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        row = None
    label = (row["habit_label"] if row else "") or "Habit"
    conn.execute("UPDATE tasks SET is_habit = 1 WHERE uid IN "
                 "(SELECT object_id FROM object_labels WHERE object_type = 'task' AND label_name = ?)", (label,))
    conn.execute("DELETE FROM object_labels WHERE label_name = ?", (label,))
    conn.execute("DELETE FROM label_config WHERE name = ?", (label,))
    try:
        conn.execute("DELETE FROM task_habit_settings")
    except sqlite3.OperationalError:
        pass


def _finance_tags_become_tags(conn: sqlite3.Connection) -> None:
    """Finance tags and their links move under the shelf Finance as ordinary tags (the old finance tag tables are dropped),
    and two unused leftovers of earlier versions go: the old `tags` table (not the new `label_tags`) and the `projects`
    table, whose rows became shelves long ago."""
    from . import tags

    tags.ensure_schema(conn)
    tags.move_finance_tags(conn)
    conn.execute("DROP TABLE IF EXISTS tags")
    conn.execute("DROP TABLE IF EXISTS projects")


def _projects_become_tags(conn: sqlite3.Connection) -> None:
    """Remaining projects become tags on the shelf Projects (see tags.fold_projects); auto-shelf lists go."""
    from . import tags

    tags.fold_projects(conn)


def _folder_readmes(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notebook_folder_readmes (label_name TEXT PRIMARY KEY, body TEXT NOT NULL DEFAULT '', "
        "updated_at TEXT)"
    )


def _series_share_tags(conn: sqlite3.Connection) -> None:
    """Occurrences of a repeating event that have no tag link take the tags of the series' first tagged occurrence."""
    from . import tags

    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'object_tags'").fetchone():
        return
    for series in conn.execute("SELECT DISTINCT series_uid FROM events WHERE series_uid IS NOT NULL").fetchall():
        uids = [r[0] for r in conn.execute("SELECT uid FROM events WHERE series_uid = ? ORDER BY start_at, uid", (series[0],))]
        linked = {u: tags.tags_for_object(conn, "event", u) for u in uids}
        source = next((t for t in linked.values() if t), None)
        for uid in uids:
            if source and not linked[uid]:
                tags.set_object_tags(conn, "event", uid, source)


def _links_get_a_kind(conn: sqlite3.Connection) -> None:
    """Every task and event link names its kind: a work session when it carried the old flag, otherwise related."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'event_task_relations'").fetchone():
        return
    if "kind" not in _columns(conn, "event_task_relations"):
        conn.execute("ALTER TABLE event_task_relations ADD COLUMN kind TEXT")
    conn.execute("UPDATE event_task_relations SET kind = CASE WHEN is_work_allocation = 1 THEN 'work_session' ELSE 'related' END "
                 "WHERE kind IS NULL")


def _university_tables(conn: sqlite3.Connection) -> None:
    """The University module's own tables: the semester record, the syllabus and the link from a topic to a class."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS university_semesters (
            uid TEXT PRIMARY KEY,
            shelf_name TEXT NOT NULL,
            name TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            class_end_date TEXT,
            exam_start TEXT,
            exam_end TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS university_topics (
            uid TEXT PRIMARY KEY,
            semester_uid TEXT NOT NULL,
            discipline_tag TEXT NOT NULL,
            number INTEGER NOT NULL,
            title TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'lecture',
            importance INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_university_topics_discipline ON university_topics(semester_uid, discipline_tag, number);
        CREATE TABLE IF NOT EXISTS university_topic_classes (
            topic_uid TEXT NOT NULL,
            event_uid TEXT NOT NULL,
            PRIMARY KEY (topic_uid, event_uid)
        );
        CREATE INDEX IF NOT EXISTS idx_university_topic_classes_event ON university_topic_classes(event_uid);
        """
    )


def _university_items(conn: sqlite3.Connection) -> None:
    """What the University module keeps about its classes, exams and readings: which series, task or event is its own."""
    if "holiday_calendar" not in _columns(conn, "university_semesters"):
        conn.execute("ALTER TABLE university_semesters ADD COLUMN holiday_calendar TEXT")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS university_slots (
            series_uid TEXT PRIMARY KEY,
            semester_uid TEXT NOT NULL,
            discipline_tag TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'lecture',
            weeks TEXT NOT NULL DEFAULT 'all'
        );
        CREATE TABLE IF NOT EXISTS university_exams (
            task_uid TEXT PRIMARY KEY,
            event_uid TEXT NOT NULL,
            semester_uid TEXT NOT NULL,
            discipline_tag TEXT NOT NULL,
            weight REAL
        );
        CREATE TABLE IF NOT EXISTS university_readings (
            task_uid TEXT PRIMARY KEY,
            semester_uid TEXT NOT NULL,
            discipline_tag TEXT NOT NULL,
            author TEXT,
            citation_id TEXT
        );
        """
    )


def _university_sheet(conn: sqlite3.Connection) -> None:
    """The course sheet of a discipline (fixed and custom fields) and what a reading says about a library book."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS university_sheet (
            semester_uid TEXT NOT NULL,
            discipline_tag TEXT NOT NULL,
            key TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            value TEXT NOT NULL DEFAULT '',
            position REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (semester_uid, discipline_tag, key)
        );
        """
    )
    cols = _columns(conn, "university_readings")
    for name in ("locator", "category", "notes"):
        if name not in cols:
            conn.execute(f"ALTER TABLE university_readings ADD COLUMN {name} TEXT")
    exam_cols = _columns(conn, "university_exams")
    for name in ("component", "notes"):
        if name not in exam_cols:
            conn.execute(f"ALTER TABLE university_exams ADD COLUMN {name} TEXT")
    if "credits_target" not in _columns(conn, "university_semesters"):
        conn.execute("ALTER TABLE university_semesters ADD COLUMN credits_target REAL")


def _university_sheet_columns(conn: sqlite3.Connection) -> None:
    """Columns that migration 32 gained after some databases had already run it: the semester's credits target, and an exam's evaluation link and notes."""
    if "credits_target" not in _columns(conn, "university_semesters"):
        conn.execute("ALTER TABLE university_semesters ADD COLUMN credits_target REAL")
    exam_cols = _columns(conn, "university_exams")
    for name in ("component", "notes"):
        if name not in exam_cols:
            conn.execute(f"ALTER TABLE university_exams ADD COLUMN {name} TEXT")


_CITATION_FTS_COLUMNS = "title, authors, container_title, publisher, isbn, doi, note"
_CITATION_FTS_AUTHORS = ("(SELECT group_concat(coalesce(json_extract(value, '$.family'), '') || ' ' || coalesce(json_extract(value, '$.given'), ''), ' ') "
                         "FROM json_each({row}.authors_json))")


def _citation_fts_values(row: str) -> str:
    return (f"{row}.title, coalesce({_CITATION_FTS_AUTHORS.format(row=row)}, ''), {row}.container_title, "
            f"{row}.publisher, {row}.isbn, {row}.doi, {row}.note")


def _citations_search_and_files(conn: sqlite3.Connection) -> None:
    """Citations gain a stored PDF (file_name, file_label), a keyset-friendly title index and an FTS5 search index kept by triggers."""
    have = _columns(conn, "citations")
    for column in ("file_name", "file_label"):
        if column not in have:
            conn.execute(f"ALTER TABLE citations ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_citations_title ON citations(title COLLATE NOCASE, uid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_citations_doi ON citations(doi) WHERE doi != ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_citations_isbn ON citations(isbn) WHERE isbn != ''")
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS citations_fts USING fts5({_CITATION_FTS_COLUMNS}, tokenize='unicode61 remove_diacritics 2')")
    cols = _CITATION_FTS_COLUMNS
    conn.execute(f"CREATE TRIGGER IF NOT EXISTS citations_fts_insert AFTER INSERT ON citations BEGIN INSERT INTO citations_fts(rowid, {cols}) VALUES (new.rowid, {_citation_fts_values('new')}); END")
    conn.execute(f"CREATE TRIGGER IF NOT EXISTS citations_fts_delete AFTER DELETE ON citations BEGIN DELETE FROM citations_fts WHERE rowid = old.rowid; END")
    conn.execute(f"CREATE TRIGGER IF NOT EXISTS citations_fts_update AFTER UPDATE ON citations BEGIN DELETE FROM citations_fts WHERE rowid = old.rowid; INSERT INTO citations_fts(rowid, {cols}) VALUES (new.rowid, {_citation_fts_values('new')}); END")
    conn.execute("DELETE FROM citations_fts")
    conn.execute(f"INSERT INTO citations_fts(rowid, {cols}) SELECT rowid, {_citation_fts_values('citations')} FROM citations")


def _university_milestones(conn: sqlite3.Connection) -> None:
    """Exams become milestones of a way of evaluating: each exam row moves over keeping its task and event, on the way its component
    points at (or on a new way named after it, with the exam's weight). The general form of evaluation goes."""
    import json
    import uuid

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS university_milestones (
            uid TEXT PRIMARY KEY,
            semester_uid TEXT NOT NULL,
            discipline_tag TEXT NOT NULL,
            way_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            day TEXT NOT NULL DEFAULT '',
            start TEXT NOT NULL DEFAULT '',
            end TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            due TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            event_uid TEXT,
            task_uid TEXT,
            position INTEGER NOT NULL DEFAULT 0
        )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_university_milestones_discipline ON university_milestones(semester_uid, discipline_tag)")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'university_exams'").fetchone():
        position = 0
        for exam in conn.execute("SELECT * FROM university_exams ORDER BY semester_uid, discipline_tag, rowid").fetchall():
            ways = {}
            for row in conn.execute("SELECT * FROM university_sheet WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE AND key LIKE 'eval:%'",
                                    (exam["semester_uid"], exam["discipline_tag"])).fetchall():
                try:
                    data = json.loads(row["value"] or "{}")
                except ValueError:
                    data = {}
                ways[data.get("id") or row["key"][5:]] = [sub.get("id") for sub in data.get("subs", [])]
            event = conn.execute("SELECT * FROM events WHERE uid = ?", (exam["event_uid"],)).fetchone()
            task = conn.execute("SELECT * FROM tasks WHERE uid = ?", (exam["task_uid"],)).fetchone()
            title = (task["title"] if task else "") or (event["title"] if event else "") or "Exam"
            way = exam["component"] if exam["component"] in ways else next((w for w, subs in ways.items() if exam["component"] in subs), None)
            if not way:
                way = uuid.uuid4().hex[:8]
                weight = "" if exam["weight"] is None else f"{exam['weight']:g}"
                conn.execute("INSERT INTO university_sheet (semester_uid, discipline_tag, key, label, value, position) VALUES (?, ?, ?, ?, ?, ?)",
                             (exam["semester_uid"], exam["discipline_tag"], f"eval:{way}", title,
                              json.dumps({"id": way, "form": "", "weight": weight, "subs": []}), 300))
            start_at, end_at = (event["start_at"] if event else "") or "", (event["end_at"] if event else "") or ""
            due = ((task["due_at"] if task else "") or "")[:10]
            conn.execute("INSERT OR IGNORE INTO university_milestones (uid, semester_uid, discipline_tag, way_id, title, day, start, end, location, due, notes, "
                         "event_uid, task_uid, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (exam["task_uid"], exam["semester_uid"], exam["discipline_tag"], way, title, start_at[:10], start_at[11:16], end_at[11:16],
                          (event["location"] if event else "") or "", due, exam["notes"] or "", exam["event_uid"] if event else None,
                          exam["task_uid"] if task else None, position))
            position += 1
        conn.execute("DROP TABLE university_exams")
    conn.execute("DELETE FROM university_sheet WHERE key = 'evaluation'")


def _milestone_end_day(conn: sqlite3.Connection) -> None:
    """An event milestone ends on a day of its own, which may differ from its start day."""
    if "end_day" not in _columns(conn, "university_milestones"):
        conn.execute("ALTER TABLE university_milestones ADD COLUMN end_day TEXT NOT NULL DEFAULT ''")
    conn.execute("UPDATE university_milestones SET end_day = day WHERE end_day = '' AND day != ''")


def _banners_become_files(conn: sqlite3.Connection) -> None:
    """Uploaded banner images move out of app_meta into the banners folder next to the database."""
    import base64
    import json

    from . import banner_files

    for key, raw in conn.execute("SELECT key, value FROM app_meta WHERE key LIKE 'page_banner_%'").fetchall():
        try:
            banner = json.loads(raw)
            data = base64.b64decode(banner["image_b64"], validate=True)
        except (ValueError, TypeError, KeyError):
            continue
        image_type = banner.get("image_type") if banner.get("image_type") in banner_files.IMAGE_TYPES else "jpeg"
        banner.pop("image_b64")
        banner.update(banner_files.store(conn, data, image_type))
        conn.execute("UPDATE app_meta SET value = ? WHERE key = ?", (json.dumps(banner), key))


def _login_sessions(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS login_sessions (sid TEXT PRIMARY KEY, created_at TEXT NOT NULL)")


def _secrets_leave_the_database(conn: sqlite3.Connection) -> None:
    from . import secret_store

    secret_store.move_from_database(conn)


MIGRATIONS: list[Migration] = [
    Migration(1, "notebook documents get an is_template flag", _note_templates),
    Migration(2, "frontmatter fields lose the required column", _field_config_without_required, destructive=True),
    Migration(3, "finance accounts, transactions and tags", _finance_tables),
    Migration(4, "finance scheduled transactions", _finance_tables),
    Migration(5, "finance scheduled transaction tags", _finance_tables),
    Migration(6, "finance account abbreviations and tag looks", _finance_looks),
    Migration(7, "finance tags no longer belong to a label group", _free_finance_tags),
    Migration(8, "events can belong to a series; series table", _event_series_tables),
    Migration(9, "repeating events become one real event per occurrence", _repeating_events_become_rows, destructive=True),
    Migration(10, "notes keep one label and one project", _notes_have_one_label_and_project, destructive=True),
    Migration(11, "glossary terms become entries with a kind", _glossary_terms_become_entries),
    Migration(12, "citations get academic fields", _citations_get_academic_fields),
    Migration(13, "notes can be journal entries", _notes_can_be_journal_entries),
    Migration(14, "notes can be pinned", _notes_can_be_pinned),
    Migration(15, "journal notes become weekly", _journal_notes_become_weekly, destructive=True),
    Migration(16, "entry kinds get fixed-name fields", _entry_kinds_get_fields),
    Migration(17, "entry references get start and end pages", _references_get_pages),
    Migration(18, "timing statistics per day", _timing_statistics),
    Migration(19, "notebook folder readmes", _folder_readmes),
    Migration(20, "app-wide tags and their links", _tag_tables),
    Migration(21, "app-wide tags live in label_tags (an older tags table already exists)", _tag_tables),
    Migration(22, "habits get their own flag and the habit label goes away", _habit_is_not_a_label, destructive=True),
    Migration(23, "finance tags become tags on the Finance shelf; old tags and projects tables are dropped", _finance_tags_become_tags, destructive=True),
    Migration(24, "projects become tags on the shelf Projects", _projects_become_tags, destructive=True),
    Migration(25, "occurrences of a repeating event share the series' tags", _series_share_tags, destructive=True),
    Migration(26, "task and event links get a kind", _links_get_a_kind, destructive=True),
    Migration(27, "University module tables", _university_tables),
    Migration(28, "University classes, exams and readings", _university_items),
    Migration(29, "banner images move from app_meta to files", _banners_become_files, destructive=True),
    Migration(30, "login sessions can be revoked", _login_sessions),
    Migration(31, "login secret, password hash and recovery token move to a file", _secrets_leave_the_database, destructive=True),
    Migration(32, "University course sheet and library references", _university_sheet),
    Migration(33, "University credits target, exam evaluation links and notes", _university_sheet_columns),
    Migration(34, "Citation search index and stored PDFs", _citations_search_and_files),
    Migration(35, "University exams become milestones of a way of evaluating", _university_milestones, destructive=True),
    Migration(36, "University event milestones get an end day", _milestone_end_day),
    Migration(40, "Citation editions with their own PDFs", citation_editions, destructive=True),
    Migration(41, "Books get status, rating and keywords; editions get a DOI", citation_editions, destructive=True),
]


def _database_file(conn: sqlite3.Connection) -> Path | None:
    row = conn.execute("PRAGMA database_list").fetchone()
    return Path(row[2]) if row and row[2] else None


class MigrationError(RuntimeError):
    """A migration could not be applied, or the database is ahead of this version."""


def _backup(conn: sqlite3.Connection, number: int) -> Path | None:
    """A consistent copy of the database next to it, through SQLite's own backup so pages still in the WAL are included."""
    source = _database_file(conn)
    if source is None or not source.exists():
        return None
    conn.commit()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = source.with_name(f"{source.name}.before-migration-{number:04d}-{stamp}")
    copy = sqlite3.connect(target)
    try:
        conn.backup(copy)
    finally:
        copy.close()
    compress_old_backups(source)
    return target


def known_numbers() -> set[int]:
    return {m.number for m in MIGRATIONS}


def applied_numbers(conn: sqlite3.Connection) -> set[int]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'").fetchone():
        return set()
    return {row[0] for row in conn.execute("SELECT number FROM schema_migrations")}


def ahead_of_this_version(conn: sqlite3.Connection) -> list[int]:
    """Migrations the database has that this code does not know: it was upgraded by a newer release."""
    return sorted(applied_numbers(conn) - known_numbers())


KEEP_UNCOMPRESSED_BACKUPS = 3


def compress_old_backups(source: Path, keep: int = KEEP_UNCOMPRESSED_BACKUPS) -> list[Path]:
    """Gzips all but the newest `keep` pre-migration copies; nothing is deleted."""
    copies = sorted(source.parent.glob(f"{source.name}.before-migration-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    packed = []
    for old in [c for c in copies if c.suffix != ".gz"][keep:]:
        target = old.with_name(old.name + ".gz")
        with old.open("rb") as src, gzip.open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        old.unlink()
        packed.append(target)
    return packed


def pending(conn: sqlite3.Connection) -> list[Migration]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (number INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    done = applied_numbers(conn)
    return sorted((m for m in MIGRATIONS if m.number not in done), key=lambda m: m.number)


def run(conn: sqlite3.Connection) -> list[int]:
    """Applies every pending migration in number order and returns the numbers applied.

    A database that a newer release has migrated is refused before anything is changed, since older code on a newer schema
    corrupts data quietly. One backup is taken before the first destructive migration of a run. A migration that fails rolls its
    own changes back, is not recorded, and stops the run with the backup's name in the message; those already applied stay recorded.
    """
    ahead = ahead_of_this_version(conn)
    if ahead:
        raise MigrationError(f"This database was migrated by a newer release (migrations {', '.join(map(str, ahead))}). "
                             f"Restore the backup taken before that update, or run the newer release: 'curodav-ctl revert' does the first.")
    todo = pending(conn)
    backup: Path | None = None
    applied = []
    for migration in todo:
        if migration.destructive and backup is None and _has_data(conn):
            backup = _backup(conn, migration.number)
        try:
            if not conn.in_transaction:
                conn.execute("BEGIN IMMEDIATE")  # DDL is transactional in SQLite; Python only opens a transaction for DML on its own
            migration.apply(conn)
            conn.execute("INSERT INTO schema_migrations (number, name, applied_at) VALUES (?, ?, ?)",
                         (migration.number, migration.name, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            hint = f" The database as it was before is in {backup.name}." if backup else ""
            raise MigrationError(f"Migration {migration.number} ({migration.name}) failed: {exc}.{hint}") from exc
        applied.append(migration.number)
    return applied


def _has_data(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'notebook_field_config'").fetchone() is not None


def dry_run(db_path: Path) -> list[int]:
    """Runs the pending migrations on a throw-away copy of the database, through the same start-up path the app uses, and
    returns their numbers. The real database is never touched; raises MigrationError when a migration would fail."""
    import tempfile

    from . import db

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / db_path.name
        source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        target = sqlite3.connect(copy)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        before = sqlite3.connect(copy)
        try:
            ahead = ahead_of_this_version(before)
            have = applied_numbers(before)
        finally:
            before.close()
        if ahead:
            raise MigrationError(f"The database is ahead of this version (migrations {', '.join(map(str, ahead))}).")
        try:
            with db.connect(copy):
                pass
        except MigrationError:
            raise
        except Exception as exc:
            raise MigrationError(f"Start-up on a copy of the database failed: {exc}") from exc
        after = sqlite3.connect(copy)
        try:
            return sorted(applied_numbers(after) - have)
        finally:
            after.close()


def main(argv: list[str]) -> int:
    """`python -m src.migrations check <database>`: what an update would migrate, tried on a copy. Exit 0 when it works."""
    if len(argv) != 2 or argv[0] != "check":
        sys.stderr.write("usage: python -m src.migrations check <database file>\n")
        return 2
    path = Path(argv[1])
    if not path.exists():
        sys.stdout.write("No database yet: nothing to migrate.\n")
        return 0
    try:
        numbers = dry_run(path)
    except MigrationError as exc:
        sys.stderr.write(f"Migration check failed: {exc}\n")
        return 1
    sys.stdout.write(f"Migration check passed: {', '.join(map(str, numbers)) if numbers else 'nothing pending'}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
