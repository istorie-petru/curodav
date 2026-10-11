"""Connection, init,  shared helpers and app settings.

Part of the db package; src/db/__init__.py re-exports every name.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from .schema import SCHEMA_SQL


logger = logging.getLogger(__name__)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, coldef: str) -> None:
    """Lightweight migration for columns added to a table that already
    existed on disk. `CREATE TABLE IF NOT EXISTS` (below) only helps for
    tables that are entirely new -- it's a silent no-op against an
    existing table missing a newer column, which is exactly what happened
    when `exdates_json` was added to `events`: anyone with a cache.sqlite
    from before that change got `sqlite3.OperationalError: table events
    has no column named exdates_json` on every write, since the DB file
    persists across app restarts/updates."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")


def _drop_column(conn: sqlite3.Connection, table: str, column: str) -> None:
    """Inverse of `_ensure_column`, for the rare case a column's data
    should actually be discarded rather than left inert (see this app's
    usual "never force-drop old data" convention -- this is a deliberate
    exception, decided per-column, not the default). Plain `ALTER TABLE
    ... DROP COLUMN` (SQLite 3.35+, no shadow-table rebuild needed since
    nothing here has an index/generated-column dependency on these
    columns). Guarded the same way `_ensure_column` is guarded, so it's
    safe to call on every startup: a no-op once the column is already
    gone."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column in existing:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _relax_legacy_not_null(conn: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> None:
    """Fix for a real bug (found 2026-08-07 via a live crash report, not a
    test -- the test suite always connects to a brand-new tmp_path
    database via `SCHEMA_SQL`'s current CREATE TABLE, so it never
    exercises what an *existing*, pre-label-space-rework cache.sqlite
    actually looks like on disk).

    Every Phase 1/2/5 column-removal comment in this file says some
    version of "the old column stays physically present, deliberately,
    nothing reads/writes it anymore" -- true, and deliberately so:
    scripts/migrate_labels.py still needs to read `calendar_path`/
    `list_path`/`addressbook_path` (which collection an object used to
    live in) on a pre-migration database, so those columns and their
    *data* must not be dropped or destroyed before that script has had a
    chance to run. But several of them (`href`, `etag`, and the
    `*_path` columns themselves, at minimum) were originally declared
    NOT NULL with no default. Once upsert_event/upsert_task/
    upsert_contact correctly stopped supplying a value for them, every
    INSERT against an existing database that still physically has that
    NOT NULL constraint started failing outright:
    `sqlite3.IntegrityError: NOT NULL constraint failed: events.href` --
    not a hypothetical, this is the exact error a real user hit trying
    to create an event.

    Fix: relax the NOT NULL constraint in place -- keep the column, keep
    every existing row's value, just stop requiring a value on new
    writes. SQLite has no `ALTER TABLE ... ALTER COLUMN` for constraints,
    so this does the standard rebuild: create a shadow table with the
    exact same columns/types/data (including every other column and
    every existing row, untouched) except the target columns lose their
    NOT NULL, copy the data across, drop the old table, rename the
    shadow into place, then recreate whatever indexes existed on it.
    Guarded to only run when at least one target column is both present
    AND still actually NOT NULL (`PRAGMA table_info`'s notnull flag) --
    a no-op on a brand-new database, and a no-op the second time this
    runs against an already-fixed one, so it's safe to call on every
    startup rather than needing its own one-time-migration bookkeeping."""
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    by_name = {row[1]: row for row in info}
    needs_fix = any(
        name in by_name and by_name[name][3] == 1 and by_name[name][4] is None
        for name in columns
    )
    if not needs_fix:
        return
    indexes = [
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,)
        ).fetchall()
    ]
    index_sql = [
        row[0] for row in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,)
        ).fetchall()
    ]
    col_defs = []
    col_names = []
    for cid, name, coltype, notnull, dflt, pk in info:
        col_names.append(name)
        parts = [name, coltype or ""]
        if pk:
            parts.append("PRIMARY KEY")
        if notnull and name not in columns:
            parts.append("NOT NULL")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        col_defs.append(" ".join(p for p in parts if p))
    shadow = f"{table}__relax_not_null"
    conn.execute(f"DROP TABLE IF EXISTS {shadow}")
    conn.execute(f"CREATE TABLE {shadow} ({', '.join(col_defs)})")
    cols_csv = ", ".join(col_names)
    conn.execute(f"INSERT INTO {shadow} ({cols_csv}) SELECT {cols_csv} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {shadow} RENAME TO {table}")
    for sql in index_sql:
        # sqlite_master's stored index SQL still names the shadow table
        # implicitly via CREATE INDEX ... ON <table>(...) -- the ON
        # clause already says the real table name (indexes aren't
        # renamed when their table is), so these can be replayed as-is.
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as exc:
            logger.warning("Could not recreate index on %s after NOT NULL relax (%s): %s", table, sql, exc)
    logger.info("Relaxed legacy NOT NULL constraints on %s%s", table, f" ({', '.join(columns)})")


def init_schema(conn: sqlite3.Connection) -> None:
    from .labels import _LABEL_MODULE_COLUMNS, backfill_group_rows, backfill_label_modules, migrate_spaces_to_groups
    from .sync import backfill_server_sync_writes
    from .tasks import backfill_work_allocation_flags
    from .contacts import migrate_archived_contact_label, migrate_legacy_contact_address, migrate_legacy_contact_phone_email
    from .pages import migrate_label_page_type
    from .notebook import seed_builtin_notebook_fields
    conn.executescript(SCHEMA_SQL)
    # 1.8 slice 1 -- §4's tombstone model ("deleting an entity offline is a
    # delete operation, not a row removal ... this design adds one
    # (deleted_at + the deleting op's HLC)"). A plain sync-unaware write
    # (every existing router) never sets this column and nothing existing
    # reads it -- it's additive, inert until the sync API (routers/
    # sync_api.py) is actually used.
    _ensure_column(conn, "tasks", "deleted_at", "TEXT")
    _ensure_column(conn, "events", "deleted_at", "TEXT")
    _ensure_column(conn, "contacts", "deleted_at", "TEXT")
    _ensure_column(conn, "events", "exdates_json", "TEXT NOT NULL DEFAULT '[]'")
    # 1.6 ("Generalized recurrence and the non-working-day policy") -- see
    # the `events` CREATE TABLE comment above for the model.
    _ensure_column(conn, "events", "holiday_calendar", "TEXT")
    _ensure_column(conn, "events", "exclude_saturday", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "events", "exclude_sunday", "INTEGER NOT NULL DEFAULT 0")
    # Same 1.6 subsection -- see schedule_holidays' own CREATE TABLE
    # comment for why every pre-existing holiday keeps working unchanged
    # under the 'Default' calendar name.
    _ensure_column(conn, "schedule_holidays", "calendar_name", "TEXT NOT NULL DEFAULT 'Default'")
    # Phase 1 (label-space rework): task_lists/calendars/addressbooks and
    # every href/etag/*_path/raw_ics/raw_vcard column are no longer part
    # of SCHEMA_SQL for a brand-new database. An *existing* cache.sqlite
    # from before this migration still physically has those tables/columns
    # on disk (CREATE TABLE IF NOT EXISTS never drops anything) -- that's
    # deliberate, not an oversight: scripts/migrate_labels.py reads them
    # directly via raw SQL to backfill object_labels before anyone decides
    # to reclaim the disk space by hand. Nothing in this module's own
    # code path (upserts/getters below) references those old
    # tables/columns anymore.
    #
    # Contact photo, same "column added after the table already existed on
    # disk" situation exdates_json was in for events. No index needed
    # (never queried by, just read/written per-row), so no landmine here.
    _ensure_column(conn, "contacts", "photo_b64", "TEXT")
    _ensure_column(conn, "contacts", "photo_type", "TEXT")
    _ensure_column(conn, "contacts", "photo_version", "TEXT")
    # Contacts field parity with Nextcloud Contacts (open.md), slice 1 of 6
    # (Title -> Phone/Email -> Website -> Birthday -> Address -> Social
    # network, per the build order recorded there). Title is the vCard
    # TITLE property (a person's job title, e.g. "Software Engineer") --
    # distinct from `org` (their organization's name, vCard ORG). Same
    # "column added after the table already existed on disk" situation as
    # photo_b64/photo_type immediately above.
    _ensure_column(conn, "contacts", "title", "TEXT")
    _ensure_column(conn, "contacts", "pseudonym", "TEXT")
    _ensure_column(conn, "contacts", "role", "TEXT")
    # Contacts field parity slice 2 of 6 -- Phone/Email. contact_phones/
    # contact_emails (SCHEMA_SQL above) are brand-new tables, so `CREATE
    # TABLE IF NOT EXISTS` already handles a pre-slice-2 database (unlike a
    # column added to an existing table, no _ensure_column needed for the
    # tables themselves). What DOES need a migration is the *data*: a
    # pre-slice-2 database has real values sitting in the now-dead
    # `contacts.phone`/`contacts.email` columns that would otherwise vanish
    # from view the moment the UI stops reading them. Runs on every
    # connect, same as every other migration in this function -- see
    # migrate_legacy_contact_phone_email's own docstring for why it's safe
    # to call unconditionally (idempotent).
    migrate_legacy_contact_phone_email(conn)
    # Contacts field parity slice 5 of 6 -- Address. contact_addresses
    # (SCHEMA_SQL above) is a brand-new table, same "CREATE TABLE IF NOT
    # EXISTS already handles it" situation as contact_websites -- the
    # migration below only needs to move the *data* sitting in the now-
    # dead `contacts.address` column. Runs on every connect, same
    # idempotence contract as migrate_legacy_contact_phone_email.
    migrate_legacy_contact_address(conn)
    _ensure_column(conn, "contacts", "birthday", "TEXT")
    _ensure_column(conn, "contacts", "archived_at", "TEXT")
    # A draft is the buffer row behind an unsaved new-contact form (so a photo
    # can be uploaded and cropped before Save). It never syncs and never shows
    # in lists or search; Save turns it into a real contact, anything else
    # deletes it.
    _ensure_column(conn, "contacts", "is_draft", "INTEGER NOT NULL DEFAULT 0")
    # Schedule class -> contact link, same "column added after the table
    # already existed on disk" situation as the others above. Guarded on
    # table existence (unlike every other _ensure_column call here) because
    # 1.6 dropped `schedule_classes` from SCHEMA_SQL entirely -- a brand-new
    # database never has this table, and _ensure_column's own ALTER TABLE
    # would error against a table that doesn't exist. Only a pre-1.6
    # cache.sqlite that still physically carries the table (see that
    # table's own removal note above) needs this.
    if _table_exists(conn, "schedule_classes"):
        _ensure_column(conn, "schedule_classes", "professor_contact_uid", "TEXT")
    # Phase 2 (label-space rework): schedule_classes.project_uid is GONE --
    # a class's optional project link is now an object_labels row
    # (object_type='schedule_class', see scripts/migrate_schedule_classes_
    # to_events.py). Existing databases from before this migration still
    # physically carry the column (never force-dropped, same "don't touch
    # old data automatically" convention as every other Phase 1/2 column
    # removal in this file) -- nothing in this module's own code reads/
    # writes it anymore.
    # Timeline view (Phase 11) -- see timeline_layout.py's module
    # docstring for the full rationale. `timeline_lane` is a task's
    # explicit, user-dragged manual row placement (desktop:
    # `Object.details["timeline_lane"]`; this app has no generic details
    # blob on tasks, so it's a plain nullable column instead -- same "flat
    # column, not a JSON blob" convention this file already uses
    # throughout). Phase 1 drops `task_lists`, which used to own the
    # per-list swimlane row-name map (`timeline_row_names_json`) -- there
    # is currently only one implicit swimlane grid until Phase 3 gives
    # Timeline a label-based grouping to replace it (see
    # routers/timeline.py).
    _ensure_column(conn, "tasks", "timeline_lane", "INTEGER")
    # Side work (post-1.1) -- Importance/Urgency's explicit per-task axes
    # are gone: both are now purely computed from label rules + temporal
    # state (src/derived_state.py), never manually set, so a database that
    # still physically carries the 1.1 `importance`/`urgency` columns has
    # them dropped outright here -- a deliberate exception to this file's
    # usual "never force-drop old data" convention (see `_drop_column`'s
    # own docstring), decided because a stale explicit value left inert
    # would otherwise keep influencing filters/sort through the ORDER BY
    # clauses below if a future change ever re-read it by accident.
    _drop_column(conn, "tasks", "importance")
    _drop_column(conn, "tasks", "urgency")
    _ensure_column(conn, "tasks", "completed_at", "TEXT")
    _ensure_column(conn, "dashboard_widgets", "group_uid", "TEXT")
    # Phase 2 (label-space rework): dashboard_widgets.space_uid/project_uid
    # collapse to one `label_name` column (see the CREATE TABLE comment
    # above). Existing databases keep the old space_uid/project_uid columns
    # physically present (never force-dropped), but nothing in this module
    # reads/writes them anymore -- only `label_name`.
    _ensure_column(conn, "dashboard_widgets", "label_name", "TEXT")
    _ensure_column(conn, "label_config", "generate_space", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "label_config", "dashboard_preset_json", "TEXT")
    _ensure_column(conn, "label_config", "abbreviation", "TEXT")
    # 1.1 (virtual & derived states) -- label behavior rules that used to
    # feed the Importance/Urgency derivation, a feature since removed
    # outright (see the label_config CREATE TABLE comment above).
    _ensure_column(conn, "label_config", "importance", "INTEGER")
    _ensure_column(conn, "label_config", "urgency_threshold_days", "INTEGER")
    # 1.3 (Project-enabled label stack) -- see the label_config CREATE
    # TABLE comment above for the model.
    _ensure_column(conn, "label_config", "is_project", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "label_config", "start_date", "TEXT")
    _ensure_column(conn, "label_config", "end_date", "TEXT")
    _ensure_column(conn, "label_config", "archived_at", "TEXT")
    for col, decl in _LABEL_MODULE_COLUMNS:
        _ensure_column(conn, "label_config", col, decl)
    _ensure_column(conn, "tasks", "target_per_day", "REAL NOT NULL DEFAULT 1")
    _ensure_column(conn, "tasks", "habits_per_period", "INTEGER")
    _ensure_column(conn, "task_completions", "note", "TEXT")
    _ensure_column(conn, "tasks", "habit_unit", "TEXT")
    _ensure_column(conn, "tasks", "habit_kind", "TEXT")
    _ensure_column(conn, "tasks", "reminder_time", "TEXT")
    _ensure_column(conn, "tasks", "habit_icon", "TEXT")
    _ensure_column(conn, "tasks", "habit_color", "TEXT")
    _ensure_column(conn, "task_completions", "value", "REAL NOT NULL DEFAULT 1")
    _ensure_column(conn, "tasks", "holiday_calendar", "TEXT")
    _ensure_column(conn, "tasks", "exclude_saturday", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "tasks", "exclude_sunday", "INTEGER NOT NULL DEFAULT 0")
    # 1.4 (Work allocations) -- see the event_task_relations CREATE TABLE
    # comment above for the model.
    _ensure_column(conn, "event_task_relations", "is_work_allocation", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "event_task_relations", "hours_estimate", "REAL")
    _ensure_column(conn, "event_task_relations", "difficulty", "TEXT")
    _ensure_column(conn, "event_task_relations", "own_title", "INTEGER NOT NULL DEFAULT 0")
    conn.execute("UPDATE contacts SET org = NULL WHERE org = 'None'")
    conn.execute("UPDATE contacts SET phone = NULL WHERE phone = 'None'")
    conn.execute("UPDATE contacts SET email = NULL WHERE email = 'None'")
    conn.execute("UPDATE events SET location = NULL WHERE location = 'None'")
    conn.execute("UPDATE events SET meeting_url = NULL WHERE meeting_url = 'None'")
    conn.execute("UPDATE events SET recurrence = NULL WHERE recurrence = 'None'")
    conn.execute("UPDATE tasks SET recurrence = NULL WHERE recurrence = 'None'")
    _ensure_column(conn, "habits", "archived_at", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_habits_archived ON habits(archived_at)")
    _ensure_column(conn, "habits", "holiday_calendar", "TEXT")
    _ensure_column(conn, "habits", "exclude_saturday", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "habits", "exclude_sunday", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "task_completions", "task_uid", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_completions_task ON task_completions(task_uid)")
    _relax_legacy_not_null(conn, "events", ("href", "etag", "calendar_path"))
    _relax_legacy_not_null(conn, "tasks", ("href", "etag", "calendar_path", "list_path"))
    _relax_legacy_not_null(conn, "contacts", ("href", "etag", "addressbook_path"))
    _ensure_column(conn, "published_lists", "visibility", "TEXT NOT NULL DEFAULT 'private'")
    _ensure_column(conn, "published_lists", "public_token", "TEXT")
    _ensure_column(conn, "label_groups", "page_type", "TEXT NOT NULL DEFAULT 'dashboard'")
    _ensure_column(conn, "published_lists", "contact_name_field", "TEXT NOT NULL DEFAULT 'full_name'")
    backfill_server_sync_writes(conn)
    backfill_work_allocation_flags(conn)
    backfill_label_modules(conn)
    migrate_label_page_type(conn)
    migrate_spaces_to_groups(conn)
    backfill_group_rows(conn)
    migrate_archived_contact_label(conn)
    _ensure_column(conn, "notebook_field_config", "builtin", "INTEGER NOT NULL DEFAULT 0")
    seed_builtin_notebook_fields(conn)
    from .. import migrations
    migrations.run(conn)
    _ensure_column(conn, "notebook_glossary_terms", "auto", "INTEGER NOT NULL DEFAULT 0")
    conn.commit()


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI's `get_db` dependency (deps.py) is a
    # sync generator, which normally runs in the threadpool same as sync
    # route handlers -- but an `async def` route (e.g. reschedule_event,
    # which needs `await request.json()`) runs directly on the event loop
    # thread instead, a *different* thread than whichever threadpool
    # worker executed the dependency and created this connection. sqlite3's
    # default same-thread check then raises. Safe to disable here because
    # each request gets its own fresh connection via this context manager
    # (see deps.get_db) -- it's never shared *concurrently* across threads,
    # just potentially closed by a different thread than opened it.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        init_schema(conn)
        yield conn
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row, json_fields: tuple[str, ...]) -> dict[str, Any]:
    """Decode each `*_json` column and rename it to its bare form (e.g.
    `tags_json` -> `tags`) -- every caller (templates, ical_rows.py,
    caldav_bridge.py) reads/writes the bare name, matching the flat-row
    contract those modules document. Previously this decoded the JSON but
    left the column name as `tags_json`/`reminders_json`, so `event.tags`
    and `event.reminders` were silently always empty in every template and
    in the edit-form pre-fill -- a real bug, just not one that crashed
    anything, so it went unnoticed until multi-calendar work started
    reading these fields more carefully."""
    d = dict(row)
    for f in json_fields:
        if f in d:
            raw = d.pop(f)
            bare = f.removesuffix("_json")
            try:
                d[bare] = json.loads(raw) if raw is not None else []
            except (json.JSONDecodeError, TypeError):
                d[bare] = []
    return d


class MultipleProjectLabelsError(ValueError):
    """Raised by upsert_task when its `tags` would give a task more than one
    is_project=1 label at once (1.5, § Task model: "never multiple projects
    at once, because multiple project ownership would make workload,
    progress, deadlines, and scheduling ambiguous"). Carries the offending
    project label names so the caller (routers/tasks.py) can surface a
    clear 400, the same "raise, don't silently corrupt or 500" pattern
    db.find_overlapping_project's callers already follow for the sibling
    "projects may not overlap" rule -- except here there's no confirm-anyway
    escape hatch, since the rule has no legitimate override the way a
    calendar overlap does.

    Deliberately checked only at this write boundary (upsert_task's `tags`
    argument), not as a stored CHECK constraint or a startup scan: a task
    that already carries two project labels via a pre-1.5 data state (direct
    DB edit, restored backup, etc.) is left exactly as-is until the next time
    something calls upsert_task with a new tags list for it -- see
    plans/open-priority.md § Task model and this rule's own test coverage in
    test_single_project_per_task.py for the "don't silently corrupt existing
    data" requirement."""

    def __init__(self, project_names: list[str], noun: str = "task"):
        self.project_names = list(project_names)
        names = ", ".join(self.project_names)
        super().__init__(f"A {noun} may belong to only one project label at a time (got: {names}).")


def purge_all_data(conn: sqlite3.Connection) -> None:
    """Settings' "Purge all" (2026-08-07) -- a full data wipe, confirmed
    explicitly by the user as "everything in the app," not just tasks.
    Deletes every row from every table this schema defines, including
    app_meta -- clearing app_meta's seeded-dashboard flags is
    deliberate, not collateral damage: it means the next visit to Home
    (or any label page) re-seeds a fresh default widget layout instead
    of landing on a permanently empty grid, same "purge should leave a
    usable app, not a bricked one" reasoning as a fresh install.

    Known limitation, not silently swept under the rug: this only
    clears this app's own SQLite tables. Any collection a Published
    List (published_lists table) had already materialized into Radicale
    is NOT torn down here -- doing that needs a live CalDavBridge, which
    this function deliberately doesn't take a dependency on (a purge
    button living in Settings has no natural bridge to inject without
    threading Radicale credentials through a page that otherwise never
    touches them). The orphaned Radicale collection is harmless (nothing
    still points at it from this app) but won't disappear from Radicale
    itself without manual cleanup there."""
    tables = [
        "events", "tasks", "contacts", "task_checklist_items",
        "event_task_relations", "object_labels", "label_config",
        "schedule_holidays", "habits",
        "habit_entries", "task_completions", "habit_pauses", "push_subscriptions", "push_sent", "dashboard_widgets",
        "time_blocks",
        "published_lists", "app_meta",
        "notebook_documents", "notebook_properties",
        "notebook_field_config", "notebook_field_options",
        "citations", "notebook_citations",
        "glossary_terms", "notebook_glossary_terms", "glossary_term_references",
        # Auto-detect override bookkeeping (item H, session 7) -- same
        # "purge wipes everything" treatment as the glossary tables above.
        "notebook_glossary_excluded_terms",
        "notebook_links",
        # Personal finance (Phase P) -- same "purge wipes everything".
        "finance_accounts", "finance_transactions", "finance_scheduled", "finance_scheduled_tags", "finance_tags", "finance_transaction_tags",
    ]
    for table in tables:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def _hours_between(start_at: str | None, end_at: str | None) -> float:
    if not start_at or not end_at:
        return 0.0
    try:
        start = datetime.fromisoformat(start_at)
        end = datetime.fromisoformat(end_at)
    except ValueError:
        return 0.0
    return max((end - start).total_seconds() / 3600.0, 0.0)

# Contacts field parity slice 4 of 6 -- Birthday. Single-value, so there's
# no *_TYPES vocabulary the way phone/email/website have one -- just the
# two accepted storage shapes (see upsert_contact's ensure_column comment
# for why raw text, not a `date`). `parse_contact_birthday` is what
# routers/contacts.py calls to validate a create/edit form's raw
# `birthday` field before it ever reaches upsert_contact -- returns the
# canonical stored string, or raises ValueError on anything else (leading/
# trailing whitespace tolerated, an empty string is the caller's job to
# treat as "no birthday" before calling this at all).
_BIRTHDAY_FULL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BIRTHDAY_YEARLESS_RE = re.compile(r"^--\d{2}-\d{2}$")


_BIRTHDAY_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def list_templates_using_field(conn: sqlite3.Connection, key: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT d.uid, d.title FROM notebook_documents d JOIN notebook_properties p ON p.notebook_uid = d.uid "
        "WHERE d.is_template = 1 AND LOWER(p.key) = LOWER(?) GROUP BY d.uid ORDER BY d.title COLLATE NOCASE",
        (key,),
    )]


# Matches a wikilink marker's `data-target-uid` attribute inside
# content_json's own JSON-serialized text (static/notebook/
# notebook_wikilinks.js stamps this onto each `.cdx-wikilink` span at
# link-creation time). A plain regex over the whole serialized dict, not a
# recursive walk of blocks/data/items/cells, finds every marker regardless
# of which block type (paragraph, list item, table cell, quote caption...)
# it ended up inside, without this needing to know Editor.js's own
# per-tool data shape. The optional `\\?` either side covers both an
# escaped quote (content_json's own on-disk JSON text) and a plain one (a
# caller that passed an already-parsed dict straight through, e.g. a test).
_WIKILINK_TARGET_RE = re.compile(r'data-target-uid=\\?"([0-9a-fA-F-]+)\\?"')
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _collect_block_text(value: Any, out: list[str]) -> None:
    """Recursively collects every string leaf out of an Editor.js block's
    `data` payload, used by `_extract_notebook_plain_text` below.
    Deliberately not restricted to a known per-tool key ("text"/"items"/
    "caption"/table "content" rows/...) so a block type added later still
    participates without this function needing updating -- same "don't
    need to know every tool's shape" reasoning `_extract_wikilink_target_
    uids`'s own comment uses, just scoped to a block's `data` rather than
    the whole serialized dict."""
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _collect_block_text(v, out)
    elif isinstance(value, list):
        for v in value:
            _collect_block_text(v, out)


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def annotate_item_colors(conn: sqlite3.Connection, items: list[dict[str, Any]], *, key: str = "calendar_color") -> list[dict[str, Any]]:
    """A task/event row's display color is its first label's color
    (alphabetical, for a stable pick when it carries more than one),
    falling back to 'blue' for an unlabeled row -- moved here from
    routers/calendar.py's `_annotate_calendar_colors` (2026-08-07 fix,
    kept there as a thin wrapper for its own existing call sites/tests) so
    routers/dashboard.py and routers/projects.py can reuse it too without
    importing routers/calendar, which already imports routers/dashboard
    (a real circular-import risk, not a style preference). Mutates and
    returns the same list. `key` defaults to `calendar_color` (the name
    every calendar template already reads via `cal-{{ e.calendar_color
    }}`) but the Agenda-style widgets reuse this for a plain `.cal-*` dot
    under the same key, direct request: "the color... of an event/task
    should be as the label's, not default on blue or any other accent
    color"."""
    from .labels import effective_label_config
    color_by_label: dict[str, str] = {}
    for item in items:
        tags = sorted(item.get("tags") or [], key=str.lower)
        color = "blue"
        for name in tags:
            if name not in color_by_label:
                color_by_label[name] = effective_label_config(conn, name).get("color") or "blue"
            color = color_by_label[name]
            break
        item[key] = color
    return items


def _mirror_legacy_module_fields(row: dict[str, Any], existing: dict[str, Any], data: dict[str, Any]) -> None:
    """Translates the legacy Space/Project fields (generate_space,
    parent_name, a project's end_date) into the module fields, using the
    same rules as backfill_label_modules. Since labels-as-modules slice c
    (2026-09-25) nothing in the app writes those legacy fields; the one
    remaining source is restoring a backup taken before 2026-09-25
    (routers/export.py upserts its label rows as-is). Without this, such a
    restore would bring labels back ungrouped and unpinned. A new-field key
    passed explicitly in `row` always wins, so a newer backup's own values
    are kept. It only ever turns things on; it never guesses an "off"."""
    def put(key: str, value: Any) -> None:
        if key not in row:
            data[key] = value

    if row.get("generate_space"):
        put("sidebar_pin", 1)
        put("widget_pin", 1)
        put("page_type", "dashboard")
        if not data.get("label_group"):
            put("label_group", data["name"])
    if row.get("is_project"):
        put("sidebar_pin", 1)
        put("widget_pin", 1)
        put("page_type", "dashboard")
    if "parent_name" in row:
        if row["parent_name"]:
            put("label_group", row["parent_name"])
            put("sidebar_pin", 1)
        elif existing.get("parent_name") and existing.get("label_group") == existing.get("parent_name"):
            # Moved out of its Space -- leave the group it came from too.
            put("label_group", None)
    if "end_date" in row and data.get("is_project"):
        put("deadline_date", row["end_date"] or None)
        put("has_deadline", 1 if row["end_date"] else 0)


def get_app_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_app_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


PROFILE_PHOTO_B64_KEY = "profile_photo_b64"
PROFILE_PHOTO_TYPE_KEY = "profile_photo_type"
PROFILE_PHOTO_VERSION_KEY = "profile_photo_version"

_SEASON_DATE_FIELD = {"task": "due_at", "event": "start_at"}


def season_for_date(value: Any) -> str | None:
    """Meteorological Northern-Hemisphere season for a stored start_at/
    due_at value ("2026-09-07" or a full "...T..." datetime string) --
    Dec/Jan/Feb winter, Mar/Apr/May spring, Jun/Jul/Aug summer, Sep/Oct/Nov
    autumn. None for anything missing or unparseable (a bare date's first
    10 characters cover both shapes) -- callers treat that exactly like
    "no season resolved" and fall through to the next tier rather than
    guessing a season for a malformed value."""
    if not value or not isinstance(value, str):
        return None
    try:
        month = date.fromisoformat(value[:10]).month
    except ValueError:
        return None
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")


def month_for_date(value: Any) -> str | None:
    """Same input/None-handling contract as `season_for_date` above (in
    fact the same parsing -- kept as its own function rather than having
    one derive the other so neither has to know the other exists), just
    at calendar-month instead of season granularity: `MONTH_BANNER_SCOPES`
    keys, lowercase English month name."""
    if not value or not isinstance(value, str):
        return None
    try:
        month = date.fromisoformat(value[:10]).month
    except ValueError:
        return None
    return _MONTH_NAMES[month - 1]


def get_profile_photo(conn: sqlite3.Connection) -> dict[str, str] | None:
    """The app user's own profile picture -- {photo_b64, photo_type,
    version} (same shape as a contact's photo_b64/photo_type/photo_version
    columns), or None when none is set. Unlike a contact's photo there's
    no vCard anywhere -- this is app-level identity (Settings >
    General)."""
    b64 = get_app_meta(conn, PROFILE_PHOTO_B64_KEY)
    if not b64:
        return None
    version = get_app_meta(conn, PROFILE_PHOTO_VERSION_KEY)
    if not version:
        version = hashlib.md5(b64.encode("ascii")).hexdigest()[:12]
        set_app_meta(conn, PROFILE_PHOTO_VERSION_KEY, version)
    return {
        "photo_b64": b64,
        "photo_type": get_app_meta(conn, PROFILE_PHOTO_TYPE_KEY) or "jpeg",
        "version": version,
    }


def set_profile_photo(conn: sqlite3.Connection, photo_b64: str, photo_type: str) -> None:
    set_app_meta(conn, PROFILE_PHOTO_B64_KEY, photo_b64)
    set_app_meta(conn, PROFILE_PHOTO_TYPE_KEY, photo_type)
    set_app_meta(conn, PROFILE_PHOTO_VERSION_KEY, hashlib.md5(photo_b64.encode("ascii")).hexdigest()[:12])


def clear_profile_photo(conn: sqlite3.Connection) -> None:
    """Both keys are cleared ("" stored, not deleted -- same "an existing
    key keeps existing, just empty" convention every other app_meta
    unset in this app uses), so a cleared photo reads as None."""
    set_app_meta(conn, PROFILE_PHOTO_B64_KEY, "")
    set_app_meta(conn, PROFILE_PHOTO_TYPE_KEY, "")
    set_app_meta(conn, PROFILE_PHOTO_VERSION_KEY, "")


# --------------------------------------------------------------------- #
# 1.8 slice 1 -- field-HLC shadow store (plans/open-priority.md §
# Offline-first editing & synchronization §§6, 9). See field_versions'
# own CREATE TABLE comment for what this table does and doesn't store.
# The comparison/apply *logic* (§§6-7) lives in src/offline_sync.py, kept
# pure and independent of routers/HTTP -- these are just the plain reads/
# writes against the shadow-store tables themselves, same "db.py never
# contains a router-shaped decision" convention as everywhere else in
# this file.
# --------------------------------------------------------------------- #

# The entity tables and per-field sync whitelist, shared by offline_sync.py
# (which only ever receives *device* ops) and the server-write recording
# below (which makes the server itself a participant in the same scheme).
# One copy lives here, not two -- offline_sync.py aliases it so a field
# added to the sync protocol in one place can't silently diverge from the
# other. Deliberately excludes `importance`/`urgency`: those axes were
# removed as columns in an earlier side-work rework (see the `tasks`
# CREATE TABLE comment), so a device op or server write targeting them has
# no column to land in.
ENTITY_TABLES: dict[str, str] = {
    "task": "tasks",
    "event": "events",
    "contact": "contacts",
}

ENTITY_SYNC_FIELDS: dict[str, set[str]] = {
    "task": {
        "title", "description", "start_at", "due_at", "status", "progress",
        "recurrence", "exdates_json", "completed_at", "target_per_day",
        "habits_per_period", "habit_unit", "habit_kind",
        "created_at", "updated_at", "deleted_at",
    },
    "event": {
        "title", "description", "start_at", "end_at", "all_day", "location",
        "meeting_url", "status", "recurrence", "exdates_json", "reminders_json",
        "holiday_calendar", "exclude_saturday", "exclude_sunday",
        "created_at", "updated_at", "deleted_at",
    },
    "contact": {
        "full_name", "pseudonym", "title", "role", "org", "phone", "email", "address", "notes",
        "photo_b64", "photo_type", "created_at", "updated_at", "deleted_at",
    },
}


SERVER_DEVICE_ID = "server"
_SERVER_HLC_KEY = "server_hlc_clock"


def _row_columns(
    conn: sqlite3.Connection, table: str, uid: str, columns: list[str]
) -> dict[str, Any]:
    """Raw stored values for a fixed set of columns -- the diff substrate
    for record_server_sync_write. Reads the real column names straight off
    the table (not via get_*, which decodes *_json columns into bare names
    and attaches labels), so the comparison always operates on the stored
    representation, the same values a pull would deliver."""
    row = conn.execute(
        f"SELECT {', '.join(columns)} FROM {table} WHERE uid = ?", (uid,)
    ).fetchone()
    return dict(row) if row else {}


_SERVER_WRITES_BACKFILLED_KEY = "sync_server_writes_backfilled"


def get_field_hlc(
    conn: sqlite3.Connection, entity_type: str, entity_uid: str, field_name: str
) -> tuple[int, int, str] | None:
    row = conn.execute(
        "SELECT hlc_physical, hlc_logical, hlc_device_id FROM field_versions "
        "WHERE entity_type = ? AND entity_uid = ? AND field_name = ?",
        (entity_type, entity_uid, field_name),
    ).fetchone()
    return (row[0], row[1], row[2]) if row else None


def set_field_hlc(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_uid: str,
    field_name: str,
    hlc: tuple[int, int, str],
) -> None:
    conn.execute(
        "INSERT INTO field_versions (entity_type, entity_uid, field_name, "
        "hlc_physical, hlc_logical, hlc_device_id) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(entity_type, entity_uid, field_name) DO UPDATE SET "
        "hlc_physical=excluded.hlc_physical, hlc_logical=excluded.hlc_logical, "
        "hlc_device_id=excluded.hlc_device_id",
        (entity_type, entity_uid, field_name, hlc[0], hlc[1], hlc[2]),
    )


def list_field_versions_since(
    conn: sqlite3.Connection, cursor_hlc: tuple[int, int, str] | None
) -> list[dict[str, Any]]:
    """Every field write with a stored HLC strictly newer than `cursor_hlc`
    -- the incremental pull delta (§8). `cursor_hlc=None` means "give me
    everything" (a brand-new device's first pull, or the fresh-cursor
    reset a forced full resync performs). Row-value comparison
    (`(a, b, c) > (?, ?, ?)`) matches HLC's own lexicographic total order
    (§3) directly in SQL."""
    if cursor_hlc is None:
        rows = conn.execute(
            "SELECT entity_type, entity_uid, field_name, hlc_physical, hlc_logical, hlc_device_id "
            "FROM field_versions ORDER BY hlc_physical, hlc_logical, hlc_device_id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT entity_type, entity_uid, field_name, hlc_physical, hlc_logical, hlc_device_id "
            "FROM field_versions WHERE (hlc_physical, hlc_logical, hlc_device_id) > (?, ?, ?) "
            "ORDER BY hlc_physical, hlc_logical, hlc_device_id",
            cursor_hlc,
        ).fetchall()
    return [
        {
            "entity_type": r[0],
            "entity_uid": r[1],
            "field_name": r[2],
            "hlc": (r[3], r[4], r[5]),
        }
        for r in rows
    ]


def max_field_hlc(conn: sqlite3.Connection) -> tuple[int, int, str] | None:
    """The server's own newest known HLC across every tracked field --
    what a forced full resync (§8, stale cursor) resets a device's cursor
    to once it has re-fetched everything, so the device's next incremental
    pull only asks for changes after that point rather than replaying the
    resync itself."""
    row = conn.execute(
        "SELECT hlc_physical, hlc_logical, hlc_device_id FROM field_versions "
        "ORDER BY hlc_physical DESC, hlc_logical DESC, hlc_device_id DESC LIMIT 1"
    ).fetchone()
    return (row[0], row[1], row[2]) if row else None


# --------------------------------------------------------------------- #
# 1.8 slice 2 -- sync_conflicts (§§7b/c, 9). See the table's own CREATE
# TABLE comment for what it's for. Plain CRUD helpers only -- the actual
# decision of *when* a conflict is worth recording lives in
# src/offline_sync.py, same layering as the field-HLC shadow store above.
# --------------------------------------------------------------------- #


def _hlc_to_str(hlc: tuple[int, int, str]) -> str:
    return f"{hlc[0]}:{hlc[1]}:{hlc[2]}"
