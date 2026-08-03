"""SQLite cache for the web app's calendar/task/contact views.

Radicale is the source of truth (per the "Radicale stays source of truth,
this app is a client" decision) -- this database is a disposable,
rebuildable mirror, the same relationship the desktop app's SQLite cache
has to its file tree (see desktop/src/core/db/). Every row here can be
reconstructed from a full pull via sync.py; nothing in this file should
ever be treated as durable on its own, and every table keeps enough of the
raw CalDAV/CardDAV resource (`raw_ics`/`raw_vcard`) to never lose data this
schema doesn't happen to have a column for.

Deliberately no `links`/`tags-as-graph` tables -- those are desktop-only
graph features (see the caldav migration discussion) with no CalDAV
equivalent and no clear single-object owner, so they stayed out.

`task_checklist_items` (below) is the one deliberate exception, added
2026-07-31 at explicit user request for tasks feature-parity with desktop's
checklist editor. Same reasoning as `schedule_classes`/`schedule_holidays`:
there's no standard iCalendar property for "a task's own checklist," so
this table is the authoritative, local-only store for it -- nothing here
round-trips through CalDAV, and a checklist made here won't show up if the
same task is opened from another CalDAV client. Kanban (routers/tasks.py's
board view) needed no new table at all -- it's just VTODO STATUS grouped
into columns, the same `tasks.status` column the table view already reads.
Subtasks likewise needed no new table -- `tasks.parent_uid` already existed
and round-trips via RELATED-TO;RELTYPE=PARENT (ical_rows.py), so a subtask
created here is a real, portable VTODO on any other CalDAV client, just
without this app's own nested-list presentation.

`tags`/`tag_groups`/`projects`/`project_groups` (added 2026-08-01) are
local-only for the same reason as `task_checklist_items` above -- no
CalDAV/CardDAV equivalent -- but note they are NOT the generic `links`/
"tags-as-graph" table this docstring says stayed out: tag *assignment* is
still the existing `tasks`/`events`/`contacts.tags_json` column (already
real, synced data via CATEGORIES), and a project doesn't own objects
directly -- it's a `project_uid` FK column on `task_lists`/`calendars`/
`addressbooks`/`schedule_classes`, not a new any-to-any link table. See
each table's own comment further down for the full rationale.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    uid TEXT PRIMARY KEY,
    href TEXT NOT NULL,
    etag TEXT,
    calendar_path TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    start_at TEXT,
    end_at TEXT,
    all_day INTEGER NOT NULL DEFAULT 0,
    location TEXT,
    meeting_url TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    recurrence TEXT,
    exdates_json TEXT NOT NULL DEFAULT '[]',
    reminders_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT,
    updated_at TEXT,
    raw_ics TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    uid TEXT PRIMARY KEY,
    href TEXT NOT NULL,
    etag TEXT,
    calendar_path TEXT NOT NULL,
    list_path TEXT NOT NULL DEFAULT 'tasks',
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    start_at TEXT,
    due_at TEXT,
    priority INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    progress REAL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    parent_uid TEXT,
    recurrence TEXT,
    exdates_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT,
    updated_at TEXT,
    raw_ics TEXT
);

-- Multi-calendar: each row is one real CalDAV collection (uid = the
-- collection's path segment, e.g. "personal", "work"). Name/color are
-- local-only display metadata -- CalDAV has an unofficial calendar-color
-- extension with inconsistent client support, not worth depending on for
-- what's fundamentally just a UI label. The collection itself is real and
-- interoperable; the label/color you see for it is this app's own.
CREATE TABLE IF NOT EXISTS calendars (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT 'blue',
    created_at TEXT
);

-- Multiple task lists, added 2026-07-31 at explicit user request -- same
-- idea as `calendars` above, but each row is a separate real CalDAV VTODO
-- collection (caldav_bridge.py's `_task_calendar(list_path)`), not a
-- local-only tag. `tasks.list_path` points at one of these by uid, exactly
-- how `events.calendar_path` already pointed at `calendars.uid`. The
-- default row (uid='tasks') is the same collection name this app always
-- used before multi-list existed, so upgrading in place doesn't orphan
-- any existing tasks -- see ensure_default_task_list().
CREATE TABLE IF NOT EXISTS task_lists (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT 'blue',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
    uid TEXT PRIMARY KEY,
    href TEXT NOT NULL,
    etag TEXT,
    addressbook_path TEXT NOT NULL,
    full_name TEXT NOT NULL DEFAULT '',
    org TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    category TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    -- Photo, added 2026-07-31 -- base64-encoded image bytes + the format
    -- ("JPEG"/"PNG"/...), round-tripped through the vCard PHOTO property
    -- (vcard_rows.py) rather than stored as a local file, so a photo
    -- uploaded here actually syncs to every other CardDAV client (phone,
    -- desktop) instead of being a web-app-only attachment.
    photo_b64 TEXT,
    photo_type TEXT,
    created_at TEXT,
    updated_at TEXT,
    raw_vcard TEXT
);

-- Multiple address books, same pattern/rationale as `task_lists` above --
-- each row is a real separate CardDAV addressbook collection
-- (caldav_bridge.py's `_addressbook(path)`). `contacts.addressbook_path`
-- already existed as a column (every contact row always recorded which
-- collection it came from) even when only one addressbook could ever
-- exist; this table is what turns that into something the UI can actually
-- offer more than one of. Default row uid='contacts' matches the
-- collection name this app always used, so existing contacts aren't
-- orphaned -- see ensure_default_addressbook().
CREATE TABLE IF NOT EXISTS addressbooks (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT 'blue',
    created_at TEXT
);

-- Local-only checklist items for a task -- see the module docstring above
-- for why this is the one exception to "no graph/desktop-only tables."
-- `position` is a plain float/int sort key (new items append at
-- max(position)+1) so reordering later doesn't require renumbering every
-- row, same idea as a fractional-indexing scheme.
CREATE TABLE IF NOT EXISTS task_checklist_items (
    uid TEXT PRIMARY KEY,
    task_uid TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0,
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_at);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_at);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_uid);
CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(full_name);
CREATE INDEX IF NOT EXISTS idx_contacts_addressbook ON contacts(addressbook_path);
CREATE INDEX IF NOT EXISTS idx_checklist_task ON task_checklist_items(task_uid);

-- Schedule ("repeat endlessly between dates, excepting certain dates" --
-- university/school timetables). Local-only: there's no standard CalDAV
-- object type for a recurring-class-with-parity-and-credits, so this is
-- the authoritative structured store. Each class additionally gets
-- mirrored one-way into `events` (and Radicale) as a plain VEVENT with an
-- RRULE + computed EXDATEs, purely so it shows up in any calendar client
-- (including this app's own Calendar tab) -- that mirrored event is a
-- courtesy export, never parsed back into these columns. See schedule.py.
CREATE TABLE IF NOT EXISTS schedule_classes (
    uid TEXT PRIMARY KEY,
    day TEXT NOT NULL,              -- 'Monday'..'Sunday'
    start_time TEXT NOT NULL,       -- 'HH:MM'
    end_time TEXT NOT NULL,         -- 'HH:MM'
    name TEXT NOT NULL DEFAULT '',
    acronym TEXT,
    class_type TEXT,
    professor TEXT,
    -- Added 2026-07-31: optional link to a real contact (contacts.uid).
    -- `professor` stays a plain display-name column (still what
    -- class_to_event_row folds into the mirrored VEVENT's description --
    -- see schedule.py) rather than being replaced by a join, so a class
    -- whose linked contact is later deleted doesn't lose the professor's
    -- name, just the link. See routers/schedule.py's `_resolve_professor`
    -- for how a class gets linked: picking an existing contact from the
    -- dropdown links straight to it; typing a name that doesn't match any
    -- contact creates a new, mostly-empty one and links to that instead
    -- -- either way there's always a real contacts.uid on the other end
    -- once `professor` is non-empty, not just a free-text string.
    professor_contact_uid TEXT,
    room TEXT,
    credits REAL NOT NULL DEFAULT 0,
    parity TEXT NOT NULL DEFAULT 'all',  -- 'all' | 'odd' | 'even'
    enrolled INTEGER NOT NULL DEFAULT 1,
    event_uid TEXT,                 -- uid of the mirrored VEVENT in `events`
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS schedule_holidays (
    uid TEXT PRIMARY KEY,
    label TEXT NOT NULL DEFAULT '',
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    semester_start TEXT,
    semester_end TEXT,
    credits_needed REAL,
    reminder_minutes INTEGER NOT NULL DEFAULT 15,
    target_calendar_uid TEXT
);

-- Global tag registry, added for the projects/tags rework. NOT the tag
-- *assignment* -- that already exists and is already real, synced data:
-- tasks/events/contacts each carry their own `tags_json` column, which
-- round-trips through iCalendar/vCard CATEGORIES (ical_rows.py,
-- vcard_rows.py) to Radicale and any other CalDAV/CardDAV client. This
-- table is purely local metadata *about* a tag name -- its display color
-- and (optional) group -- the same "local-only annotation on top of synced
-- data" role photo_type/professor_contact_uid play elsewhere in this file.
-- Renaming or merging a tag here must still write through to every
-- affected row's tags_json *and* push that change back through the
-- CalDAV/CardDAV bridge (not just this cache) or it'll silently revert on
-- the next background sync -- same bug class desktop's tag-rename fix
-- documented (see features/tags-and-linking.md). That write-through lives
-- in the router layer (needs the bridge), not here.
CREATE TABLE IF NOT EXISTS tag_groups (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS tags (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT 'blue',
    group_uid TEXT,
    created_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_name ON tags(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_tags_group ON tags(group_uid);

-- Projects: local-only structural grouping, same category as tag_groups
-- above and for the same reason -- there's no CalDAV/CardDAV concept a
-- "project" maps onto, so unlike tags (which annotate real synced rows)
-- a project and its membership are entirely this app's own data. A
-- project doesn't own tasks/events/contacts directly (no object graph --
-- see the module docstring's "deliberately no links/tags-as-graph tables"
-- reasoning); instead whole *lists* (a task list, a calendar, an address
-- book, a schedule class) point at a project via their own `project_uid`
-- column, added below via _ensure_column. That keeps the "a project
-- centralizes everything under it" behavior a plain join per collection
-- type, consistent with how this app already models multi-calendar/
-- multi-list ownership, rather than introducing the generic graph table
-- this file has twice now explicitly avoided.
--
-- `archived_at` implements "archive, don't delete": set (not NULL) means
-- retired. Archiving a project does not cascade a write to every list
-- that points at it -- retirement of those lists is derived at query time
-- (a list is retired if its project_uid's project is archived), so
-- unarchiving instantly un-retires everything under it with no cascade
-- bookkeeping to get wrong or undo.
CREATE TABLE IF NOT EXISTS project_groups (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT 'blue',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT 'blue',
    icon TEXT,
    cover_image_b64 TEXT,
    cover_image_type TEXT,
    group_uid TEXT,
    archived_at TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_projects_group ON projects(group_uid);
CREATE INDEX IF NOT EXISTS idx_projects_archived ON projects(archived_at);

-- Habit tracking -- local-only, same category as projects/tags above: no
-- CalDAV/CardDAV concept for "a daily habit and its check-in history."
-- `target_per_day` is only used to scale heatmap color intensity (e.g. a
-- "drink water" habit logged 8/8 glasses paints darker than 2/8) -- it is
-- NOT a requirement for a day to "count"; any logged value > 0 counts as
-- done for streak purposes (habits.py's _streaks). `project_uid` links a
-- habit to a project the same FK-column way every other list does (see
-- the `projects` table comment above) -- e.g. a "Study 1h/day" habit
-- under a University project.
CREATE TABLE IF NOT EXISTS habits (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT 'blue',
    icon TEXT,
    target_per_day REAL NOT NULL DEFAULT 1,
    tags_json TEXT NOT NULL DEFAULT '[]',
    project_uid TEXT,
    archived_at TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_habits_archived ON habits(archived_at);
CREATE INDEX IF NOT EXISTS idx_habits_project ON habits(project_uid);

-- One row per (habit, calendar day) actually logged -- a day with no row
-- simply has no entry, not a zero-value row, so "how many days has this
-- habit ever been touched" is just `COUNT(*)`. `value` is a plain count
-- (most habits: 1 = done that day; a "glasses of water" habit: how many),
-- editable after the fact (see upsert_habit_entry) so backfilling exact
-- past data -- explicitly requested -- is a normal write, not a special
-- path. UNIQUE(habit_uid, date) is what makes "click a day to toggle" and
-- "edit today's value" both resolve to one row per day rather than
-- accumulating duplicate log entries.
CREATE TABLE IF NOT EXISTS habit_entries (
    uid TEXT PRIMARY KEY,
    habit_uid TEXT NOT NULL,
    date TEXT NOT NULL,
    value REAL NOT NULL DEFAULT 1,
    note TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_habit_entries_habit_date ON habit_entries(habit_uid, date);
CREATE INDEX IF NOT EXISTS idx_habit_entries_habit ON habit_entries(habit_uid);

-- Custom databases (Phase 7) -- local-only, same bucket as everything
-- else in this section: no CalDAV/CardDAV concept for a user-defined
-- table. Grade tracking (a class-as-project with a database of
-- assignments and a weighted-average summary formula) is the driving
-- example, but the shape is fully generic.
--
-- Deliberately two tables, not three: `database_columns` defines the
-- schema (name, type, formula/summary_formula for formula-bearing
-- columns), and `database_rows` stores each row's non-formula cell
-- values as one JSON blob (`values_json`, column_uid -> raw value) rather
-- than a normalized cells table. A formula column's value is NEVER
-- stored -- computed live on every read (formula_engine.py), same
-- "derived, never stored" principle this app already applies to task
-- progress (routers/tasks.py's _progress_for_status) and project
-- progress (routers/projects.py's _project_scope). At personal-scale row
-- counts, one JSON blob per row is simpler than a normalized cells table
-- and costs nothing meaningful.
CREATE TABLE IF NOT EXISTS databases (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT 'blue',
    icon TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    project_uid TEXT,
    archived_at TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_databases_archived ON databases(archived_at);
CREATE INDEX IF NOT EXISTS idx_databases_project ON databases(project_uid);

-- `type`: 'text' | 'number' | 'date' | 'select' | 'checkbox' | 'formula'.
-- `formula` (type='formula' only) is a per-row expression
-- (formula_engine.py) -- bare column-name references resolve against
-- that row's own values. `summary_formula` (any type, optional) is a
-- single footer value for the whole column -- e.g. a 'grade' number
-- column's summary_formula might be `WEIGHTAVG(grade, weight)`; no bare
-- references are valid there since there's no single row, only aggregate
-- functions. `options_json` (type='select' only) is the fixed choice
-- list. `position` is a plain float sort key, same fractional-indexing
-- idea as task_checklist_items.position -- a new column appends at
-- max(position)+1, so reordering later doesn't require renumbering.
CREATE TABLE IF NOT EXISTS database_columns (
    uid TEXT PRIMARY KEY,
    database_uid TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'text',
    formula TEXT,
    summary_formula TEXT,
    options_json TEXT NOT NULL DEFAULT '[]',
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_database_columns_database ON database_columns(database_uid);

CREATE TABLE IF NOT EXISTS database_rows (
    uid TEXT PRIMARY KEY,
    database_uid TEXT NOT NULL,
    values_json TEXT NOT NULL DEFAULT '{}',
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_database_rows_database ON database_rows(database_uid);

-- Dashboard widgets (Phase 8) -- local-only, per-device layout, same
-- category as everything else in this section. `type` is a key into
-- routers/dashboard.py's WIDGET_TYPES registry (e.g. 'today_agenda',
-- 'weekly_overview', 'upcoming_events') -- adding a new widget type later
-- is a new registry entry + render function, not a schema change, which
-- is what "extensible" means here concretely. `config_json` holds every
-- widget's filters (project_uid, tags, task_list_uids, calendar_uids) in
-- one blob rather than separate columns, since different widget types
-- use different subsets of the same filter vocabulary -- same "one JSON
-- blob, not a rigid column-per-field schema" tradeoff database_rows makes
-- for the same reason. `position` is the familiar float sort key.
CREATE TABLE IF NOT EXISTS dashboard_widgets (
    uid TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_dashboard_widgets_position ON dashboard_widgets(position);

-- Tiny generic key/value store for one-off, app-level bookkeeping that
-- doesn't belong to any real domain table -- so far just one thing:
-- routers/dashboard.py's "has the mini-calendar backfill migration run
-- yet" flag (2026-08-01). Deliberately NOT a place for user-facing
-- settings (those live on their own real tables -- schedule_settings,
-- etc.) -- this is strictly internal migration/bookkeeping state.
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


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


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    _ensure_column(conn, "events", "exdates_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "schedule_settings", "target_calendar_uid", "TEXT")
    # `list_path` is new (multi-task-list support, 2026-07-31) -- an
    # existing tasks table predates it, same situation exdates_json was in.
    # The default 'tasks' matches every existing row's real collection (the
    # only one that ever existed before), so this migration doesn't need to
    # backfill anything beyond what DEFAULT already gives new/existing rows.
    _ensure_column(conn, "tasks", "list_path", "TEXT NOT NULL DEFAULT 'tasks'")
    # Must run after the _ensure_column above, not inside SCHEMA_SQL's
    # executescript -- `CREATE INDEX ... ON tasks(list_path)` isn't
    # skipped by `IF NOT EXISTS` the way `CREATE TABLE IF NOT EXISTS` is:
    # against a pre-existing tasks table that doesn't have the column yet,
    # it fails outright with "no such column: list_path" instead of being
    # a no-op. This bit a real upgrade from an existing cache.sqlite (the
    # table-level IF NOT EXISTS silently skipped re-creating `tasks` since
    # it already existed, but the index statement still ran against it).
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_list ON tasks(list_path)")
    # Contact photo, same "column added after the table already existed on
    # disk" situation as list_path above. No index needed (never queried
    # by, just read/written per-row), so no landmine here.
    _ensure_column(conn, "contacts", "photo_b64", "TEXT")
    _ensure_column(conn, "contacts", "photo_type", "TEXT")
    # Schedule class -> contact link, same "column added after the table
    # already existed on disk" situation as the others above.
    _ensure_column(conn, "schedule_classes", "professor_contact_uid", "TEXT")
    # Project links, added for the projects/tags rework -- see the
    # `projects` table's own comment above for why this is a plain FK
    # column per collection type rather than a generic link table. Every
    # collection a project can "own" gets one nullable column; NULL means
    # unassigned, exactly like professor_contact_uid above.
    _ensure_column(conn, "task_lists", "project_uid", "TEXT")
    _ensure_column(conn, "calendars", "project_uid", "TEXT")
    _ensure_column(conn, "addressbooks", "project_uid", "TEXT")
    _ensure_column(conn, "schedule_classes", "project_uid", "TEXT")
    # Timeline view (Phase 11) -- see timeline_layout.py's module
    # docstring for the full rationale. `timeline_lane` is a task's
    # explicit, user-dragged manual row placement within its list's
    # swimlane block (desktop: `Object.details["timeline_lane"]`; this app
    # has no generic details blob on tasks, so it's a plain nullable
    # column instead -- same "flat column, not a JSON blob" convention
    # this file already uses throughout). `timeline_row_names_json` is the
    # per-list map of custom swimlane row display labels (desktop:
    # `Object.details["timeline_row_names"]` on the *project* object;
    # here the swimlane owner is the task list, so it lives on
    # `task_lists` instead -- see set_task_list_row_name).
    _ensure_column(conn, "tasks", "timeline_lane", "INTEGER")
    _ensure_column(conn, "task_lists", "timeline_row_names_json", "TEXT NOT NULL DEFAULT '{}'")
    # Dashboard widget stacking (2026-08-02) -- a widget with a non-NULL
    # group_uid is a *member* of the stack container widget whose uid
    # equals this value (that container is itself just another
    # dashboard_widgets row, type="stack" -- see routers/dashboard.py's
    # module docstring). NULL (the default, and every pre-existing row's
    # value after this migration) means "top-level, not in any stack",
    # same as every widget before stacking existed. `position` is reused
    # as-is for ordering *within* whichever collection a widget belongs to
    # (top-level, or a specific stack's members) -- it was never a
    # globally-comparable value even before this, only ever compared
    # against siblings in the same ORDER BY, so grouped widgets sharing
    # the same small range of position values as other stacks' members is
    # fine.
    _ensure_column(conn, "dashboard_widgets", "group_uid", "TEXT")
    # Space page per-group tint (2026-08-02, spaces-home-pipeline) -- same
    # "column added after the table already existed on disk" situation as
    # every other _ensure_column call above. Default 'blue' matches
    # upsert_project_group's own default for a group created before this
    # migration ran.
    _ensure_column(conn, "project_groups", "color", "TEXT NOT NULL DEFAULT 'blue'")
    # Per-space widget grid (2026-08-02, spaces-home-pipeline follow-up) --
    # a widget with a non-NULL space_uid belongs to that Space's own
    # widget grid (routers/projects.py's space_detail) instead of Home's.
    # NULL (the default, and every pre-existing row's value after this
    # migration) means "Home", same convention group_uid already uses for
    # "not in any stack". Orthogonal to group_uid -- a widget can be a
    # top-level widget on a Space page (space_uid set, group_uid NULL) or a
    # member of a stack *on* that Space page (both set).
    _ensure_column(conn, "dashboard_widgets", "space_uid", "TEXT")
    # Per-space task date range (§2 Spaces v2, 2026-08-03) -- "a task list,
    # date range set per space (Personal: ~90 days; University: upcoming
    # week/month) — a plain setting on the space, not a big config
    # framework." NULL means "use the widget's own default" (7 for
    # weekly_overview); an explicit value (e.g. 90 for Personal, 7 for
    # University) overrides the seeded weekly_overview's range_days.
    _ensure_column(conn, "project_groups", "default_range_days", "INTEGER")
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


# --------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------- #

_EVENT_JSON_FIELDS = ("reminders_json", "tags_json", "exdates_json")


def upsert_event(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    data["reminders_json"] = json.dumps(data.get("reminders") or [])
    data["tags_json"] = json.dumps(data.get("tags") or [])
    data["exdates_json"] = json.dumps(data.get("exdates") or [])
    data.pop("reminders", None)
    data.pop("tags", None)
    data.pop("exdates", None)
    cols = [
        "uid", "href", "etag", "calendar_path", "title", "description",
        "start_at", "end_at", "all_day", "location", "meeting_url", "status",
        "recurrence", "exdates_json", "reminders_json", "tags_json", "created_at",
        "updated_at", "raw_ics",
    ]
    values = [data.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid")
    conn.execute(
        f"INSERT INTO events ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        values,
    )
    conn.commit()


def delete_event(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM events WHERE uid = ?", (uid,))
    conn.commit()


def delete_events_by_calendar(conn: sqlite3.Connection, calendar_path: str) -> None:
    """Called when a calendar is deleted (routers/calendars.py) -- the
    CalDAV collection delete already removed these on the server; this
    just keeps the local cache from holding orphaned rows pointing at a
    collection that no longer exists."""
    conn.execute("DELETE FROM events WHERE calendar_path = ?", (calendar_path,))
    conn.commit()


def get_event(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM events WHERE uid = ?", (uid,)).fetchone()
    return _row_to_dict(row, _EVENT_JSON_FIELDS) if row else None


def list_events(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
    exclude_calendars: list[str] | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM events"
    params: list[str] = []
    clauses = []
    if start:
        clauses.append("(end_at IS NULL OR end_at >= ?)")
        params.append(start)
    if end:
        clauses.append("start_at <= ?")
        params.append(end)
    if exclude_calendars:
        placeholders = ", ".join("?" for _ in exclude_calendars)
        clauses.append(f"calendar_path NOT IN ({placeholders})")
        params.extend(exclude_calendars)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY start_at ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r, _EVENT_JSON_FIELDS) for r in rows]


def all_event_uids(conn: sqlite3.Connection) -> set[str]:
    return {r["uid"] for r in conn.execute("SELECT uid FROM events").fetchall()}


def all_event_uids_in_calendar(conn: sqlite3.Connection, calendar_path: str) -> set[str]:
    """Used by sync.py when a single calendar's Radicale listing fails
    part-way through a refresh (see full_refresh) -- lets the refresh
    treat that calendar's already-cached events as "still seen" for this
    round instead of deleting them as stale, since a failed listing says
    nothing about whether they still exist on the server."""
    rows = conn.execute("SELECT uid FROM events WHERE calendar_path = ?", (calendar_path,)).fetchall()
    return {r["uid"] for r in rows}


# --------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------- #

_TASK_JSON_FIELDS = ("tags_json",)


def upsert_task(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    data["tags_json"] = json.dumps(data.get("tags") or [])
    data.pop("tags", None)
    # timeline_lane is deliberately NOT in this column list -- same
    # "upsert never touches it, only a dedicated setter does" pattern as
    # schedule_classes.project_uid (see set_task_timeline_lane below).
    # Every existing caller of upsert_task builds its row from
    # `dict(existing)` first (routers/tasks.py's update_task/update_field/
    # complete_task), so omitting it here just means those callers' own
    # unrelated edits can never accidentally clobber a manual timeline
    # placement to NULL -- there'd be no way to *un*-clobber it via the
    # round-trip pattern if it were in this list and a caller ever forgot
    # to carry it through.
    cols = [
        "uid", "href", "etag", "calendar_path", "list_path", "title", "description",
        "start_at", "due_at", "priority", "status", "progress", "tags_json",
        "parent_uid", "recurrence", "created_at", "updated_at", "raw_ics",
    ]
    data.setdefault("list_path", "tasks")
    values = [data.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid")
    conn.execute(
        f"INSERT INTO tasks ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        values,
    )
    conn.commit()


def delete_task(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM tasks WHERE uid = ?", (uid,))
    conn.commit()


def delete_tasks_by_list(conn: sqlite3.Connection, list_path: str) -> None:
    """Called when a task list is deleted (routers/task_lists.py) -- the
    CalDAV collection delete already removed these server-side; this just
    keeps the local cache from holding orphaned rows, same role
    delete_events_by_calendar plays for `calendars`."""
    conn.execute("DELETE FROM tasks WHERE list_path = ?", (list_path,))
    conn.commit()


def get_task(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM tasks WHERE uid = ?", (uid,)).fetchone()
    return _row_to_dict(row, _TASK_JSON_FIELDS) if row else None


def list_tasks(
    conn: sqlite3.Connection,
    status: str | None = None,
    q: str | None = None,
    list_path: str | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM tasks"
    params: list[str] = []
    clauses = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if q:
        clauses.append("title LIKE ?")
        params.append(f"%{q}%")
    if list_path:
        clauses.append("list_path = ?")
        params.append(list_path)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY (due_at IS NULL), due_at ASC, priority ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r, _TASK_JSON_FIELDS) for r in rows]


def all_task_uids(conn: sqlite3.Connection) -> set[str]:
    return {r["uid"] for r in conn.execute("SELECT uid FROM tasks").fetchall()}


def all_task_uids_in_list(conn: sqlite3.Connection, list_path: str) -> set[str]:
    """Same role as all_event_uids_in_calendar for sync.py's per-collection
    partial-failure handling -- see that function's docstring."""
    rows = conn.execute("SELECT uid FROM tasks WHERE list_path = ?", (list_path,)).fetchall()
    return {r["uid"] for r in rows}


def list_subtasks(conn: sqlite3.Connection, parent_uid: str) -> list[dict[str, Any]]:
    """Direct children only (one level) -- matches desktop's subtask tree,
    which also doesn't recurse into grandchildren on the parent's own detail
    view (each subtask gets its own detail page for that)."""
    rows = conn.execute(
        "SELECT * FROM tasks WHERE parent_uid = ? ORDER BY (due_at IS NULL), due_at ASC, priority ASC",
        (parent_uid,),
    ).fetchall()
    return [_row_to_dict(r, _TASK_JSON_FIELDS) for r in rows]


# --------------------------------------------------------------------- #
# Task checklist items (local-only, see module docstring)
# --------------------------------------------------------------------- #


def list_checklist_items(conn: sqlite3.Connection, task_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM task_checklist_items WHERE task_uid = ? ORDER BY position ASC",
        (task_uid,),
    ).fetchall()
    return [dict(r) | {"done": bool(r["done"])} for r in rows]


def add_checklist_item(conn: sqlite3.Connection, task_uid: str, uid: str, text: str, created_at: str) -> None:
    max_pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) FROM task_checklist_items WHERE task_uid = ?",
        (task_uid,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO task_checklist_items (uid, task_uid, text, done, position, created_at) "
        "VALUES (?, ?, ?, 0, ?, ?)",
        (uid, task_uid, text, max_pos + 1, created_at),
    )
    conn.commit()


def toggle_checklist_item(conn: sqlite3.Connection, item_uid: str) -> None:
    conn.execute(
        "UPDATE task_checklist_items SET done = 1 - done WHERE uid = ?", (item_uid,)
    )
    conn.commit()


def delete_checklist_item(conn: sqlite3.Connection, item_uid: str) -> None:
    conn.execute("DELETE FROM task_checklist_items WHERE uid = ?", (item_uid,))
    conn.commit()


def delete_checklist_items_for_task(conn: sqlite3.Connection, task_uid: str) -> None:
    """Called when a task is deleted -- see routers/tasks.py's delete_task,
    which also cascades to subtasks. Without this, a re-created task that
    happened to reuse the same uid (never actually possible, uids are
    uuid4) is the only scenario that'd resurrect stale rows, but it's cheap
    correctness hygiene regardless -- an orphaned checklist row pointing at
    a task_uid that no longer exists in `tasks` serves no purpose."""
    conn.execute("DELETE FROM task_checklist_items WHERE task_uid = ?", (task_uid,))
    conn.commit()


# --------------------------------------------------------------------- #
# Contacts
# --------------------------------------------------------------------- #

_CONTACT_JSON_FIELDS = ("tags_json",)


def upsert_contact(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    data["tags_json"] = json.dumps(data.get("tags") or [])
    data.pop("tags", None)
    cols = [
        "uid", "href", "etag", "addressbook_path", "full_name", "org",
        "phone", "email", "address", "category", "tags_json", "notes",
        "photo_b64", "photo_type", "created_at", "updated_at", "raw_vcard",
    ]
    data.setdefault("addressbook_path", "contacts")
    values = [data.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid")
    conn.execute(
        f"INSERT INTO contacts ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        values,
    )
    conn.commit()


def delete_contact(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM contacts WHERE uid = ?", (uid,))
    conn.commit()


def delete_contacts_by_addressbook(conn: sqlite3.Connection, addressbook_path: str) -> None:
    """Called when an address book is deleted (routers/addressbooks.py) --
    mirrors delete_events_by_calendar/delete_tasks_by_list."""
    conn.execute("DELETE FROM contacts WHERE addressbook_path = ?", (addressbook_path,))
    conn.commit()


def get_contact(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM contacts WHERE uid = ?", (uid,)).fetchone()
    return _row_to_dict(row, _CONTACT_JSON_FIELDS) if row else None


def list_contacts(
    conn: sqlite3.Connection,
    q: str | None = None,
    category: str | None = None,
    addressbook_path: str | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM contacts"
    params: list[str] = []
    clauses = []
    if q:
        # Matches name, org, phone, or email -- a single search box covering
        # every field someone's likely to actually remember about a contact,
        # rather than separate name-only vs. org-only inputs.
        clauses.append("(full_name LIKE ? OR org LIKE ? OR phone LIKE ? OR email LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like])
    if category:
        clauses.append("category = ?")
        params.append(category)
    if addressbook_path:
        clauses.append("addressbook_path = ?")
        params.append(addressbook_path)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY full_name ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r, _CONTACT_JSON_FIELDS) for r in rows]


def list_contact_categories(conn: sqlite3.Connection) -> list[str]:
    """Distinct, non-empty categories currently in use -- powers the filter
    chip bar (contacts_list.html) without needing a separate lookup table;
    `category` is a free-text field (see contact_form.html), so this is
    just whatever values people have actually typed so far."""
    rows = conn.execute(
        "SELECT DISTINCT category FROM contacts WHERE category IS NOT NULL AND category != '' ORDER BY category"
    ).fetchall()
    return [r[0] for r in rows]


def all_contact_uids(conn: sqlite3.Connection) -> set[str]:
    return {r["uid"] for r in conn.execute("SELECT uid FROM contacts").fetchall()}


def find_contact_by_name(conn: sqlite3.Connection, full_name: str) -> dict[str, Any] | None:
    """Case-insensitive exact match on full_name -- used by
    routers/schedule.py's `_resolve_professor` to decide whether a typed
    professor name should link to an existing contact or create a new
    one. Exact-match rather than fuzzy on purpose: silently linking to
    the *wrong* same-ish-named contact would be a worse outcome than
    occasionally creating a near-duplicate that the user can merge by
    hand, and this app has no fuzzy-match/merge UI to clean that up
    safely anyway. If more than one contact happens to share the exact
    same name, this deterministically picks one (`LIMIT 1`) rather than
    guessing further -- an edge case rare enough not to warrant a
    disambiguation UI here."""
    row = conn.execute(
        "SELECT * FROM contacts WHERE full_name = ? COLLATE NOCASE LIMIT 1", (full_name,)
    ).fetchone()
    return _row_to_dict(row, _CONTACT_JSON_FIELDS) if row else None


# --------------------------------------------------------------------- #
# Schedule (classes / holidays / settings) -- local-only, see schema note
# --------------------------------------------------------------------- #

_SCHEDULE_DAY_ORDER = "CASE day WHEN 'Monday' THEN 0 WHEN 'Tuesday' THEN 1 WHEN 'Wednesday' THEN 2 WHEN 'Thursday' THEN 3 WHEN 'Friday' THEN 4 WHEN 'Saturday' THEN 5 WHEN 'Sunday' THEN 6 ELSE 7 END"


def upsert_schedule_class(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    cols = [
        "uid", "day", "start_time", "end_time", "name", "acronym",
        "class_type", "professor", "professor_contact_uid", "room", "credits", "parity", "enrolled",
        "event_uid", "created_at", "updated_at",
    ]
    data = dict(row)
    data["enrolled"] = 1 if data.get("enrolled", True) else 0
    values = [data.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid")
    conn.execute(
        f"INSERT INTO schedule_classes ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        values,
    )
    conn.commit()


def set_schedule_class_project(conn: sqlite3.Connection, uid: str, project_uid: str | None) -> None:
    """upsert_schedule_class deliberately doesn't list project_uid in its
    column set, so it never touches this column at all (not even via
    COALESCE) -- the same "don't clobber a field the caller didn't mean to
    touch" outcome as the COALESCE trick used for task_lists/calendars/
    addressbooks, achieved here just by omission since this function's
    column list is already explicit rather than derived from an arbitrary
    dict. This is the only way to actually set or clear it."""
    conn.execute("UPDATE schedule_classes SET project_uid = ? WHERE uid = ?", (project_uid, uid))
    conn.commit()


def delete_schedule_class(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM schedule_classes WHERE uid = ?", (uid,))
    conn.commit()


def get_schedule_class(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM schedule_classes WHERE uid = ?", (uid,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["enrolled"] = bool(d["enrolled"])
    return d


def list_schedule_classes(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT * FROM schedule_classes ORDER BY {_SCHEDULE_DAY_ORDER}, start_time"
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["enrolled"] = bool(d["enrolled"])
        result.append(d)
    return result


def upsert_holiday(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO schedule_holidays (uid, label, date_from, date_to) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET label=excluded.label, date_from=excluded.date_from, date_to=excluded.date_to",
        (row["uid"], row.get("label", ""), row["date_from"], row["date_to"]),
    )
    conn.commit()


def delete_holiday(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM schedule_holidays WHERE uid = ?", (uid,))
    conn.commit()


def list_holidays(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM schedule_holidays ORDER BY date_from").fetchall()
    return [dict(r) for r in rows]


def get_schedule_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM schedule_settings WHERE id = 1").fetchone()
    if row is None:
        return {
            "semester_start": None,
            "semester_end": None,
            "credits_needed": None,
            "reminder_minutes": 15,
            "target_calendar_uid": None,
        }
    return dict(row)


def set_schedule_target_calendar(conn: sqlite3.Connection, calendar_uid: str) -> None:
    """Which real calendar the Schedule's mirrored class events live in --
    changed via the Schedule > Export flow (routers/schedule.py), kept
    separate from save_schedule_settings (semester dates etc.) since it has
    its own dedicated form/action and shouldn't require re-submitting the
    whole settings form just to redirect the export target."""
    conn.execute(
        "INSERT INTO schedule_settings (id, target_calendar_uid) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET target_calendar_uid=excluded.target_calendar_uid",
        (calendar_uid,),
    )
    conn.commit()


def save_schedule_settings(conn: sqlite3.Connection, settings: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO schedule_settings (id, semester_start, semester_end, credits_needed, reminder_minutes) "
        "VALUES (1, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET semester_start=excluded.semester_start, "
        "semester_end=excluded.semester_end, credits_needed=excluded.credits_needed, "
        "reminder_minutes=excluded.reminder_minutes",
        (
            settings.get("semester_start"),
            settings.get("semester_end"),
            settings.get("credits_needed"),
            settings.get("reminder_minutes", 15),
        ),
    )
    conn.commit()


# --------------------------------------------------------------------- #
# Calendars (multi-calendar: name/color metadata for each CalDAV
# collection `events.calendar_path` can point at)
# --------------------------------------------------------------------- #

DEFAULT_CALENDAR_UID = "calendar"


def upsert_calendar(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    # See upsert_task_list's comment: project_uid is COALESCE'd, not
    # clobbered, for the same reason. Use set_calendar_project to change it.
    conn.execute(
        "INSERT INTO calendars (uid, name, color, created_at, project_uid) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET name=excluded.name, color=excluded.color, "
        "project_uid=COALESCE(excluded.project_uid, calendars.project_uid)",
        (row["uid"], row["name"], row.get("color", "blue"), row.get("created_at"), row.get("project_uid")),
    )
    conn.commit()


def set_calendar_project(conn: sqlite3.Connection, uid: str, project_uid: str | None) -> None:
    conn.execute("UPDATE calendars SET project_uid = ? WHERE uid = ?", (project_uid, uid))
    conn.commit()


def delete_calendar(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM calendars WHERE uid = ?", (uid,))
    conn.commit()


def get_calendar(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM calendars WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None


def list_calendars(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM calendars ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def ensure_default_calendar(conn: sqlite3.Connection) -> None:
    """Every install needs at least one calendar to put events in --
    called once at startup (see main.py). A no-op once any calendar
    exists, so it never overwrites a name/color the user picked."""
    if list_calendars(conn):
        return
    from datetime import datetime, timezone

    upsert_calendar(
        conn,
        {
            "uid": DEFAULT_CALENDAR_UID,
            "name": "Personal",
            "color": "blue",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )


# --------------------------------------------------------------------- #
# Task lists (multiple VTODO collections `tasks.list_path` can point at) --
# same shape/rationale as `calendars` above.
# --------------------------------------------------------------------- #

DEFAULT_TASK_LIST_UID = "tasks"


def upsert_task_list(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    # project_uid is deliberately COALESCE'd, not clobbered: existing
    # callers (routers/task_lists.py's rename/recolor flow) never pass it,
    # since project assignment has its own dedicated setter
    # (set_task_list_project, below) -- same split as
    # save_schedule_settings vs. set_schedule_target_calendar. Without the
    # COALESCE, every rename/recolor would silently null out the project
    # link, exactly the class of bug the desktop docs warn about
    # (write-through that clobbers a field the caller didn't mean to touch).
    conn.execute(
        "INSERT INTO task_lists (uid, name, color, created_at, project_uid) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET name=excluded.name, color=excluded.color, "
        "project_uid=COALESCE(excluded.project_uid, task_lists.project_uid)",
        (row["uid"], row["name"], row.get("color", "blue"), row.get("created_at"), row.get("project_uid")),
    )
    conn.commit()


def set_task_list_project(conn: sqlite3.Connection, uid: str, project_uid: str | None) -> None:
    """Explicit setter for the project link -- pass None to unassign.
    Separate from upsert_task_list because that function COALESCEs
    project_uid to avoid clobbering it on an unrelated rename/recolor; an
    explicit unassign needs a real UPDATE, not an upsert a COALESCE would
    make a no-op."""
    conn.execute("UPDATE task_lists SET project_uid = ? WHERE uid = ?", (project_uid, uid))
    conn.commit()


def set_task_timeline_lane(conn: sqlite3.Connection, uid: str, lane: int | None) -> None:
    """Explicit setter for a task's manual Timeline row placement -- see
    the `tasks.timeline_lane` column comment in init_schema. Pass None to
    clear it (falls back to auto-packing, timeline_layout.py's
    assign_swimlanes)."""
    conn.execute("UPDATE tasks SET timeline_lane = ? WHERE uid = ?", (lane, uid))
    conn.commit()


def delete_task_list(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM task_lists WHERE uid = ?", (uid,))
    conn.commit()


def _task_list_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw = d.pop("timeline_row_names_json", "{}")
    try:
        d["timeline_row_names"] = json.loads(raw) if raw is not None else {}
    except (json.JSONDecodeError, TypeError):
        d["timeline_row_names"] = {}
    return d


def get_task_list(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM task_lists WHERE uid = ?", (uid,)).fetchone()
    return _task_list_row_to_dict(row) if row else None


def list_task_lists(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM task_lists ORDER BY name").fetchall()
    return [_task_list_row_to_dict(r) for r in rows]


def set_task_list_row_name(conn: sqlite3.Connection, uid: str, local_idx: int, name: str | None) -> None:
    """Port of desktop's `TimelineCanvas._set_row_name` -- persists a
    custom display label for Timeline swimlane row `local_idx` of this
    list. An empty/None name clears the override instead of storing a
    redundant empty entry, same as desktop. Desktop stores this on the
    *project* object's `details`; here the swimlane owner is the task
    list itself (see timeline_layout.py's module docstring), so it lives
    on `task_lists.timeline_row_names_json`."""
    existing = get_task_list(conn, uid)
    if existing is None:
        return
    names = dict(existing["timeline_row_names"])
    key = str(local_idx)
    if name:
        names[key] = name
    else:
        names.pop(key, None)
    conn.execute(
        "UPDATE task_lists SET timeline_row_names_json = ? WHERE uid = ?",
        (json.dumps(names), uid),
    )
    conn.commit()


def ensure_default_task_list(conn: sqlite3.Connection) -> None:
    """Same role as ensure_default_calendar -- called once at startup
    (main.py). uid matches DEFAULT_TASK_LIST_UID ('tasks'), the collection
    name this app always used before multi-list existed, so every task
    created before this feature shipped still resolves to a real row here
    instead of pointing at a list_lists entry that doesn't exist."""
    if list_task_lists(conn):
        return
    from datetime import datetime, timezone

    upsert_task_list(
        conn,
        {
            "uid": DEFAULT_TASK_LIST_UID,
            "name": "Tasks",
            "color": "blue",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )


# --------------------------------------------------------------------- #
# Address books (multiple CardDAV collections `contacts.addressbook_path`
# can point at) -- same shape/rationale as `calendars`/`task_lists`.
# --------------------------------------------------------------------- #

DEFAULT_ADDRESSBOOK_UID = "contacts"
ARCHIVED_ADDRESSBOOK_UID = "contacts-archived"


def upsert_addressbook(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    # See upsert_task_list's comment: project_uid is COALESCE'd, not
    # clobbered, for the same reason. Use set_addressbook_project to change it.
    conn.execute(
        "INSERT INTO addressbooks (uid, name, color, created_at, project_uid) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET name=excluded.name, color=excluded.color, "
        "project_uid=COALESCE(excluded.project_uid, addressbooks.project_uid)",
        (row["uid"], row["name"], row.get("color", "blue"), row.get("created_at"), row.get("project_uid")),
    )
    conn.commit()


def set_addressbook_project(conn: sqlite3.Connection, uid: str, project_uid: str | None) -> None:
    conn.execute("UPDATE addressbooks SET project_uid = ? WHERE uid = ?", (project_uid, uid))
    conn.commit()


def delete_addressbook(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM addressbooks WHERE uid = ?", (uid,))
    conn.commit()


def get_addressbook(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM addressbooks WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None


def list_addressbooks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM addressbooks ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def ensure_default_addressbook(conn: sqlite3.Connection) -> None:
    """Same role as ensure_default_calendar/ensure_default_task_list.
    Now always ensures the Active addressbook exists (uid='contacts'),
    even if other addressbooks already exist -- the two-addressbook model
    (Active + Archived) requires this specific uid to always be present."""
    from datetime import datetime, timezone

    if get_addressbook(conn, DEFAULT_ADDRESSBOOK_UID) is None:
        upsert_addressbook(
            conn,
            {
                "uid": DEFAULT_ADDRESSBOOK_UID,
                "name": "Active",
                "color": "blue",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )


def ensure_default_archived_addressbook(conn: sqlite3.Connection) -> None:
    """Ensures the Archived addressbook (uid='contacts-archived') exists.
    Called alongside ensure_default_addressbook at every startup/sync --
    the two-addressbook model requires both to always be present."""
    from datetime import datetime, timezone

    if get_addressbook(conn, ARCHIVED_ADDRESSBOOK_UID) is None:
        upsert_addressbook(
            conn,
            {
                "uid": ARCHIVED_ADDRESSBOOK_UID,
                "name": "Archived",
                "color": "gray",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )


def migrate_addressbooks_to_two(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Data-layer half of the two-addressbook migration.

    For every addressbook that is neither DEFAULT_ADDRESSBOOK_UID ('contacts')
    nor ARCHIVED_ADDRESSBOOK_UID ('contacts-archived'):
      - Add the addressbook's *name* as a tag to every contact in that book
        (merging into the contact's existing tags_json, deduplicating
        case-insensitively).
      - Update those contacts' addressbook_path to DEFAULT_ADDRESSBOOK_UID
        ('contacts', the Active book).

    Returns a list of dicts describing each addressbook that was migrated,
    so the caller (sync.py's _run_addressbook_migration) can also perform
    the matching CardDAV operations (moving vCards + deleting the old
    collections) before deleting the old DB rows -- the DB rows themselves
    are NOT deleted here, to keep this function purely data-layer / testable
    without a bridge.

    Idempotent: contacts already in Active/Archived are not touched."""
    _KEEP = {DEFAULT_ADDRESSBOOK_UID, ARCHIVED_ADDRESSBOOK_UID}
    addressbooks = list_addressbooks(conn)
    migrated = []
    for ab in addressbooks:
        if ab["uid"] in _KEEP:
            continue
        tag_name = ab["name"]
        # All contacts in this addressbook
        rows = conn.execute(
            "SELECT uid, tags_json FROM contacts WHERE addressbook_path = ?", (ab["uid"],)
        ).fetchall()
        for row in rows:
            contact_uid = row["uid"]
            try:
                existing_tags: list[str] = json.loads(row["tags_json"] or "[]")
            except (json.JSONDecodeError, TypeError):
                existing_tags = []
            # Add tag_name if not already present (case-insensitive check)
            lower_tags = {t.lower() for t in existing_tags}
            if tag_name.lower() not in lower_tags:
                existing_tags = existing_tags + [tag_name]
            conn.execute(
                "UPDATE contacts SET tags_json = ?, addressbook_path = ? WHERE uid = ?",
                (json.dumps(existing_tags), DEFAULT_ADDRESSBOOK_UID, contact_uid),
            )
        conn.commit()
        migrated.append(ab)
    return migrated


# --------------------------------------------------------------------- #
# Tag groups + tags (local-only registry; actual tag *assignment* lives in
# tasks/events/contacts.tags_json and is real synced data -- see the
# `tags`/`tag_groups` CREATE TABLE comment above for the full rationale.
# --------------------------------------------------------------------- #


def upsert_tag_group(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO tag_groups (uid, name, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET name=excluded.name",
        (row["uid"], row["name"], row.get("created_at")),
    )
    conn.commit()


def delete_tag_group(conn: sqlite3.Connection, uid: str) -> None:
    """Ungroups (doesn't delete) every tag in the group -- a tag group is
    purely organizational, so removing the group must not take its tags
    down with it, same principle as archiving a project not deleting it."""
    conn.execute("UPDATE tags SET group_uid = NULL WHERE group_uid = ?", (uid,))
    conn.execute("DELETE FROM tag_groups WHERE uid = ?", (uid,))
    conn.commit()


def list_tag_groups(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM tag_groups ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def upsert_tag(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Registers/updates a tag's color and group. Does NOT touch any
    tasks/events/contacts row -- creating a tag here doesn't retroactively
    apply it anywhere, and it isn't required before a tag name can be used
    (any task/event/contact can carry an arbitrary tag string in its own
    tags_json, same as before this table existed; this registry just gives
    known tags a color/group and is what powers autocomplete). Raises
    sqlite3.IntegrityError on a case-insensitive duplicate name (idx_tags_name)
    -- callers should catch that and treat it as "tag already exists,"
    not a crash."""
    conn.execute(
        "INSERT INTO tags (uid, name, color, group_uid, created_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET name=excluded.name, color=excluded.color, "
        "group_uid=excluded.group_uid",
        (row["uid"], row["name"], row.get("color", "blue"), row.get("group_uid"), row.get("created_at")),
    )
    conn.commit()


def ensure_tags_registered(conn: sqlite3.Connection, names: list[str]) -> None:
    """Auto-registers any tag name that doesn't already have a registry
    row, with a default color and no group -- called by the task/event/
    contact create/update routers right after saving, so typing a
    brand-new tag on any of those forms makes it show up in Settings >
    Tags immediately (with a default color you can then change), not only
    once someone separately adds it there by hand. Mirrors desktop's
    "an autocompleting add-tag input creates a new tag on the fly if it
    doesn't exist yet" (features/tags-and-linking.md). Silently skips a
    name that's already registered (case-insensitive) -- this is meant to
    be called on every save regardless of whether any given tag is new."""
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    for name in names:
        name = str(name).strip()
        if name and not get_tag_by_name(conn, name):
            upsert_tag(conn, {"uid": str(uuid.uuid4()), "name": name, "color": "gray", "created_at": now})


def get_tag(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM tags WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None


def get_tag_by_name(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM tags WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    return dict(row) if row else None


def delete_tag(conn: sqlite3.Connection, uid: str) -> None:
    """Deletes the registry entry only (color/group metadata) -- does not
    touch tags_json on any task/event/contact, since the tag name itself
    remains perfectly valid free-form data on those rows (this registry is
    additive metadata, not a foreign key those rows depend on). A tag
    manager UI that wants "delete everywhere" is a separate, explicit
    operation (strip the name from every row's tags_json, which -- for
    tasks/events/contacts -- also needs to write through the CalDAV/CardDAV
    bridge, not just this cache), left to the router layer once that UI
    exists, same split as rename/merge noted on the `tags` table comment."""
    conn.execute("DELETE FROM tags WHERE uid = ?", (uid,))
    conn.commit()


def _tag_usage_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Case-insensitive usage count per tag name, across tasks/events/
    contacts.tags_json. Done in Python, not SQL -- these are JSON arrays,
    not a real object_tags join table (this app was explicit about not
    building a generic graph table), and at personal-scale row counts a
    full Python pass over three tables is cheap and far simpler than
    SQLite JSON1 functions."""
    counts: dict[str, int] = {}

    def _tally(rows: list[dict[str, Any]]) -> None:
        for r in rows:
            for name in r.get("tags") or []:
                key = str(name).strip().lower()
                if key:
                    counts[key] = counts.get(key, 0) + 1

    _tally(list_tasks(conn))
    _tally(list_events(conn))
    _tally(list_contacts(conn))
    return counts


def list_tags(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every registered tag, plus a `usage_count` computed live from
    tasks/events/contacts.tags_json -- powers Settings > Tags (name/color/
    usage-count list, same shape desktop's tag manager has)."""
    usage = _tag_usage_counts(conn)
    rows = conn.execute("SELECT * FROM tags ORDER BY name COLLATE NOCASE").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["usage_count"] = usage.get(d["name"].strip().lower(), 0)
        result.append(d)
    return result


def list_tag_names_in_use(conn: sqlite3.Connection) -> list[str]:
    """Every distinct tag name actually in use on a task/event/contact,
    unioned with every registered tag name -- feeds autocomplete so typing
    a tag suggests both "tags someone already applied" and "tags with a
    configured color/group" even if those two sets aren't identical (e.g.
    a tag synced in from a phone's Calendar app that was never registered
    here). Case-preserving on first occurrence, deduped case-insensitively."""
    seen: dict[str, str] = {}
    for r in conn.execute("SELECT DISTINCT name FROM tags").fetchall():
        seen.setdefault(r["name"].strip().lower(), r["name"])
    for rows in (list_tasks(conn), list_events(conn), list_contacts(conn)):
        for row in rows:
            for name in row.get("tags") or []:
                name = str(name).strip()
                if name:
                    seen.setdefault(name.lower(), name)
    return sorted(seen.values(), key=str.lower)


# --------------------------------------------------------------------- #
# Project groups + projects (local-only -- see the `projects` CREATE TABLE
# comment above for why membership is per-collection FK columns, not a
# graph table, and why archiving doesn't cascade a write.)
# --------------------------------------------------------------------- #


def upsert_project_group(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO project_groups (uid, name, color, default_range_days, created_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET name=excluded.name, color=excluded.color, "
        "default_range_days=COALESCE(excluded.default_range_days, project_groups.default_range_days)",
        (row["uid"], row["name"], row.get("color") or "blue", row.get("default_range_days"), row.get("created_at")),
    )
    conn.commit()


def delete_project_group(conn: sqlite3.Connection, uid: str) -> None:
    """Ungroups (doesn't delete/archive) every project in the group --
    same reasoning as delete_tag_group."""
    conn.execute("UPDATE projects SET group_uid = NULL WHERE group_uid = ?", (uid,))
    conn.execute("DELETE FROM project_groups WHERE uid = ?", (uid,))
    conn.commit()


def list_project_groups(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM project_groups ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def get_project_group(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    """Single-row lookup for the new Space detail page (spaces-home-pipeline,
    2026-08-02) -- list_project_groups above already existed for the manage
    page's flat listing, but nothing needed one group by uid until now."""
    row = conn.execute("SELECT * FROM project_groups WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None


_PROJECT_COLS = (
    "uid", "name", "description", "color", "icon", "cover_image_b64",
    "cover_image_type", "group_uid", "archived_at", "created_at", "updated_at",
)


def upsert_project(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Full-row upsert -- unlike task_lists/calendars/addressbooks, a
    project has no separate "rename" vs. "assign membership" split to
    protect, since project_uid lives on the *other* side of the
    relationship (task_lists.project_uid etc., not a column on `projects`
    itself). archived_at IS included here deliberately reachable through a
    plain save -- archive_project/unarchive_project (below) are the normal
    path, but the edit form doesn't need special-casing to preserve it as
    long as callers round-trip the existing value, same convention
    get_project/list_projects already return it in."""
    data = dict(row)
    data.setdefault("description", "")
    data.setdefault("color", "blue")
    conn.execute(
        f"INSERT INTO projects ({', '.join(_PROJECT_COLS)}) VALUES ({', '.join('?' for _ in _PROJECT_COLS)}) "
        f"ON CONFLICT(uid) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in _PROJECT_COLS if c != "uid"),
        [data.get(c) for c in _PROJECT_COLS],
    )
    conn.commit()


def get_project(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM projects WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None


def list_projects(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict[str, Any]]:
    query = "SELECT * FROM projects"
    if not include_archived:
        query += " WHERE archived_at IS NULL"
    query += " ORDER BY name COLLATE NOCASE"
    rows = conn.execute(query).fetchall()
    return [dict(r) for r in rows]


def archive_project(conn: sqlite3.Connection, uid: str, when: str) -> None:
    conn.execute("UPDATE projects SET archived_at = ? WHERE uid = ?", (when, uid))
    conn.commit()


def unarchive_project(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("UPDATE projects SET archived_at = NULL WHERE uid = ?", (uid,))
    conn.commit()


def delete_project(conn: sqlite3.Connection, uid: str) -> None:
    """Hard delete -- distinct from archive_project. Unassigns (does not
    delete) every list that pointed at this project, across all four
    collection types, so deleting a project never silently deletes tasks/
    events/contacts/classes -- consistent with this app never cascading
    deletes onto real synced data anywhere else."""
    for table in ("task_lists", "calendars", "addressbooks", "schedule_classes"):
        conn.execute(f"UPDATE {table} SET project_uid = NULL WHERE project_uid = ?", (uid,))
    conn.execute("DELETE FROM projects WHERE uid = ?", (uid,))
    conn.commit()


def project_is_archived(conn: sqlite3.Connection, project_uid: str | None) -> bool:
    """True only if project_uid points at a project that is actually
    archived -- an unset/None project_uid is never "archived" by this
    check. Used by list views to derive "is this list retired" from its
    project link at query time rather than storing a redundant flag (see
    the `projects` table comment on why archiving doesn't cascade a
    write)."""
    if not project_uid:
        return False
    row = conn.execute(
        "SELECT archived_at FROM projects WHERE uid = ?", (project_uid,)
    ).fetchone()
    return bool(row and row["archived_at"])


def projects_by_uid(conn: sqlite3.Connection, include_archived: bool = True) -> dict[str, dict[str, Any]]:
    """uid -> project dict, for templates/routers that need to resolve a
    list's project_uid to a name/color/icon without a per-row query --
    e.g. rendering a "Project: X" badge next to every task list in
    Settings. include_archived defaults True here (unlike list_projects)
    because a list pointing at an archived project still needs to resolve
    that project's name to render "retired" state correctly, not silently
    show no badge."""
    return {p["uid"]: p for p in list_projects(conn, include_archived=include_archived)}


def merge_projects(conn: sqlite3.Connection, source_uid: str, dest_uid: str) -> None:
    """Every list pointing at source_uid is repointed at dest_uid, then
    source_uid is deleted. Mirrors desktop's tag-merge semantics (features/
    tags-and-linking.md) applied to projects instead of tags."""
    if source_uid == dest_uid:
        return
    for table in ("task_lists", "calendars", "addressbooks", "schedule_classes"):
        conn.execute(
            f"UPDATE {table} SET project_uid = ? WHERE project_uid = ?", (dest_uid, source_uid)
        )
    conn.execute("DELETE FROM projects WHERE uid = ?", (source_uid,))
    conn.commit()


# --------------------------------------------------------------------- #
# Habits + habit entries -- local-only, see the `habits`/`habit_entries`
# CREATE TABLE comments above for the full rationale.
# --------------------------------------------------------------------- #

_HABIT_COLS = (
    "uid", "name", "description", "color", "icon", "target_per_day",
    "tags_json", "project_uid", "archived_at", "created_at", "updated_at",
)


def upsert_habit(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Full-row upsert, same shape as upsert_project -- project_uid has no
    separate COALESCE-protected setter here the way task_lists/calendars/
    addressbooks do, because (unlike those) there's no existing "just
    rename/recolor" flow for a habit that doesn't already round-trip
    project_uid through its own edit form; the router always passes the
    current value explicitly, same as every other habit field."""
    data = dict(row)
    data.setdefault("description", "")
    data.setdefault("color", "blue")
    data.setdefault("target_per_day", 1)
    data["tags_json"] = json.dumps(data.get("tags") or [])
    cols = _HABIT_COLS
    conn.execute(
        f"INSERT INTO habits ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
        f"ON CONFLICT(uid) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid"),
        [data.get(c) for c in cols],
    )
    conn.commit()


def _habit_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw = d.pop("tags_json", "[]")
    try:
        d["tags"] = json.loads(raw) if raw is not None else []
    except (json.JSONDecodeError, TypeError):
        d["tags"] = []
    return d


def get_habit(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM habits WHERE uid = ?", (uid,)).fetchone()
    return _habit_row_to_dict(row) if row else None


def list_habits(
    conn: sqlite3.Connection, include_archived: bool = False, project_uid: str | None = None
) -> list[dict[str, Any]]:
    query = "SELECT * FROM habits"
    clauses = []
    params: list[Any] = []
    if not include_archived:
        clauses.append("archived_at IS NULL")
    if project_uid:
        clauses.append("project_uid = ?")
        params.append(project_uid)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY name COLLATE NOCASE"
    rows = conn.execute(query, params).fetchall()
    return [_habit_row_to_dict(r) for r in rows]


def archive_habit(conn: sqlite3.Connection, uid: str, when: str) -> None:
    conn.execute("UPDATE habits SET archived_at = ? WHERE uid = ?", (when, uid))
    conn.commit()


def unarchive_habit(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("UPDATE habits SET archived_at = NULL WHERE uid = ?", (uid,))
    conn.commit()


def delete_habit(conn: sqlite3.Connection, uid: str) -> None:
    """Hard delete -- cascades to habit_entries (unlike projects/task
    lists, a habit's daily log has no independent existence or meaning
    once the habit itself is gone; nothing else can ever point at a
    dangling habit_uid, so there's no "keep it around, just unassign"
    case the way there is for project_uid on a task list)."""
    conn.execute("DELETE FROM habit_entries WHERE habit_uid = ?", (uid,))
    conn.execute("DELETE FROM habits WHERE uid = ?", (uid,))
    conn.commit()


def upsert_habit_entry(
    conn: sqlite3.Connection, habit_uid: str, date: str, value: float, note: str | None, when: str
) -> None:
    """Insert-or-update the one entry for (habit_uid, date) -- this is
    both how a fresh backfill entry is created and how an existing day's
    value is corrected, since UNIQUE(habit_uid, date) makes them the same
    operation. `uid` is only regenerated on first insert (ON CONFLICT
    keeps the existing row's uid), consistent with every other upsert in
    this file treating uid as immutable once assigned."""
    import uuid

    conn.execute(
        "INSERT INTO habit_entries (uid, habit_uid, date, value, note, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(habit_uid, date) DO UPDATE SET value=excluded.value, note=excluded.note, updated_at=excluded.updated_at",
        (str(uuid.uuid4()), habit_uid, date, value, note, when, when),
    )
    conn.commit()


def delete_habit_entry(conn: sqlite3.Connection, habit_uid: str, date: str) -> None:
    conn.execute("DELETE FROM habit_entries WHERE habit_uid = ? AND date = ?", (habit_uid, date))
    conn.commit()


def get_habit_entry(conn: sqlite3.Connection, habit_uid: str, date: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM habit_entries WHERE habit_uid = ? AND date = ?", (habit_uid, date)
    ).fetchone()
    return dict(row) if row else None


def toggle_habit_entry(conn: sqlite3.Connection, habit_uid: str, date: str, when: str) -> bool:
    """The heatmap's click-to-toggle: no entry (or a zero-value one) ->
    create with value=1; any logged entry -> remove it entirely (not just
    zero it out, so a toggled-off day goes back to true "no data," not a
    visually-empty-but-still-present row). Returns True if the day is now
    logged, False if it was just cleared -- lets the router respond
    without a second read."""
    existing = get_habit_entry(conn, habit_uid, date)
    if existing and existing["value"] > 0:
        delete_habit_entry(conn, habit_uid, date)
        return False
    upsert_habit_entry(conn, habit_uid, date, 1, None, when)
    return True


def list_habit_entries(
    conn: sqlite3.Connection, habit_uid: str, start: str | None = None, end: str | None = None
) -> list[dict[str, Any]]:
    query = "SELECT * FROM habit_entries WHERE habit_uid = ?"
    params: list[Any] = [habit_uid]
    if start:
        query += " AND date >= ?"
        params.append(start)
    if end:
        query += " AND date <= ?"
        params.append(end)
    query += " ORDER BY date ASC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def habit_entries_by_date(
    conn: sqlite3.Connection, habit_uid: str, start: str | None = None, end: str | None = None
) -> dict[str, float]:
    """date -> value, for the heatmap builder (habits.py's _heatmap_weeks)
    and streak computation -- a plain dict lookup is simpler for both
    callers than re-scanning the row list repeatedly."""
    return {r["date"]: r["value"] for r in list_habit_entries(conn, habit_uid, start, end)}


# --------------------------------------------------------------------- #
# Custom databases (Phase 7) -- local-only, see the `databases`/
# `database_columns`/`database_rows` CREATE TABLE comments above.
# --------------------------------------------------------------------- #

_DATABASE_COLS = (
    "uid", "name", "description", "color", "icon", "tags_json",
    "project_uid", "archived_at", "created_at", "updated_at",
)


def upsert_database(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    data.setdefault("description", "")
    data.setdefault("color", "blue")
    data["tags_json"] = json.dumps(data.get("tags") or [])
    conn.execute(
        f"INSERT INTO databases ({', '.join(_DATABASE_COLS)}) VALUES ({', '.join('?' for _ in _DATABASE_COLS)}) "
        f"ON CONFLICT(uid) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in _DATABASE_COLS if c != "uid"),
        [data.get(c) for c in _DATABASE_COLS],
    )
    conn.commit()


def _database_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw = d.pop("tags_json", "[]")
    try:
        d["tags"] = json.loads(raw) if raw is not None else []
    except (json.JSONDecodeError, TypeError):
        d["tags"] = []
    return d


def get_database(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM databases WHERE uid = ?", (uid,)).fetchone()
    return _database_row_to_dict(row) if row else None


def list_databases(
    conn: sqlite3.Connection, include_archived: bool = False, project_uid: str | None = None
) -> list[dict[str, Any]]:
    query = "SELECT * FROM databases"
    clauses = []
    params: list[Any] = []
    if not include_archived:
        clauses.append("archived_at IS NULL")
    if project_uid:
        clauses.append("project_uid = ?")
        params.append(project_uid)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY name COLLATE NOCASE"
    rows = conn.execute(query, params).fetchall()
    return [_database_row_to_dict(r) for r in rows]


def archive_database(conn: sqlite3.Connection, uid: str, when: str) -> None:
    conn.execute("UPDATE databases SET archived_at = ? WHERE uid = ?", (when, uid))
    conn.commit()


def unarchive_database(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("UPDATE databases SET archived_at = NULL WHERE uid = ?", (uid,))
    conn.commit()


def delete_database(conn: sqlite3.Connection, uid: str) -> None:
    """Hard delete -- cascades to its own columns and rows (unlike
    projects/task-lists, a database's columns/rows have no independent
    meaning once the database itself is gone, same reasoning
    delete_habit's cascade to habit_entries documents)."""
    conn.execute("DELETE FROM database_rows WHERE database_uid = ?", (uid,))
    conn.execute("DELETE FROM database_columns WHERE database_uid = ?", (uid,))
    conn.execute("DELETE FROM databases WHERE uid = ?", (uid,))
    conn.commit()


# --- Columns ----------------------------------------------------------- #

_DATABASE_COLUMN_COLS = (
    "uid", "database_uid", "name", "type", "formula", "summary_formula", "options_json", "position", "created_at",
)


def upsert_database_column(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    data["options_json"] = json.dumps(data.get("options") or [])
    conn.execute(
        f"INSERT INTO database_columns ({', '.join(_DATABASE_COLUMN_COLS)}) "
        f"VALUES ({', '.join('?' for _ in _DATABASE_COLUMN_COLS)}) "
        f"ON CONFLICT(uid) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in _DATABASE_COLUMN_COLS if c != "uid"),
        [data.get(c) for c in _DATABASE_COLUMN_COLS],
    )
    conn.commit()


def _column_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw = d.pop("options_json", "[]")
    try:
        d["options"] = json.loads(raw) if raw is not None else []
    except (json.JSONDecodeError, TypeError):
        d["options"] = []
    return d


def get_database_column(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM database_columns WHERE uid = ?", (uid,)).fetchone()
    return _column_row_to_dict(row) if row else None


def list_database_columns(conn: sqlite3.Connection, database_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM database_columns WHERE database_uid = ? ORDER BY position ASC", (database_uid,)
    ).fetchall()
    return [_column_row_to_dict(r) for r in rows]


def next_column_position(conn: sqlite3.Connection, database_uid: str) -> float:
    max_pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) FROM database_columns WHERE database_uid = ?", (database_uid,)
    ).fetchone()[0]
    return max_pos + 1


def delete_database_column(conn: sqlite3.Connection, uid: str) -> None:
    """Doesn't touch database_rows.values_json -- a deleted column's
    key just becomes harmless unreferenced data in every row's JSON blob
    (no other column can ever collide with its uid), simpler than
    rewriting every row to strip it. See the `databases` table comment on
    why rows store one JSON blob rather than a normalized cells table."""
    conn.execute("DELETE FROM database_columns WHERE uid = ?", (uid,))
    conn.commit()


# --- Rows ---------------------------------------------------------------- #


def upsert_database_row(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    data["values_json"] = json.dumps(data.get("values") or {})
    cols = ("uid", "database_uid", "values_json", "position", "created_at", "updated_at")
    conn.execute(
        f"INSERT INTO database_rows ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
        f"ON CONFLICT(uid) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid"),
        [data.get(c) for c in cols],
    )
    conn.commit()


def _row_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw = d.pop("values_json", "{}")
    try:
        d["values"] = json.loads(raw) if raw is not None else {}
    except (json.JSONDecodeError, TypeError):
        d["values"] = {}
    return d


def get_database_row(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM database_rows WHERE uid = ?", (uid,)).fetchone()
    return _row_row_to_dict(row) if row else None


def list_database_rows(conn: sqlite3.Connection, database_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM database_rows WHERE database_uid = ? ORDER BY position ASC", (database_uid,)
    ).fetchall()
    return [_row_row_to_dict(r) for r in rows]


def next_row_position(conn: sqlite3.Connection, database_uid: str) -> float:
    max_pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) FROM database_rows WHERE database_uid = ?", (database_uid,)
    ).fetchone()[0]
    return max_pos + 1


def delete_database_row(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM database_rows WHERE uid = ?", (uid,))
    conn.commit()


def set_database_row_value(conn: sqlite3.Connection, row_uid: str, column_uid: str, value: Any, when: str) -> None:
    """Single-cell edit -- reads the row's current values_json, sets one
    key, writes the whole blob back. This is the write path the database
    detail page's inline cell editing actually uses; upsert_database_row
    (whole-row replace) exists for row creation and any future bulk-edit
    UI, not per-cell edits."""
    existing = get_database_row(conn, row_uid)
    if existing is None:
        return
    values = dict(existing["values"])
    values[column_uid] = value
    conn.execute(
        "UPDATE database_rows SET values_json = ?, updated_at = ? WHERE uid = ?",
        (json.dumps(values), when, row_uid),
    )
    conn.commit()


# --------------------------------------------------------------------- #
# Dashboard widgets (Phase 8) -- local-only, see the `dashboard_widgets`
# CREATE TABLE comment above.
# --------------------------------------------------------------------- #


def upsert_dashboard_widget(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    data["config_json"] = json.dumps(data.get("config") or {})
    # group_uid (2026-08-02 stacking) and space_uid (2026-08-02 per-space
    # widgets) both have to be in this explicit column list -- ON CONFLICT
    # UPDATE only touches columns named here, so leaving either out
    # wouldn't error, it would just silently never persist that part of a
    # widget's identity.
    cols = ("uid", "type", "title", "config_json", "position", "created_at", "group_uid", "space_uid")
    conn.execute(
        f"INSERT INTO dashboard_widgets ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
        f"ON CONFLICT(uid) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid"),
        [data.get(c) for c in cols],
    )
    conn.commit()


def _widget_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw = d.pop("config_json", "{}")
    try:
        d["config"] = json.loads(raw) if raw is not None else {}
    except (json.JSONDecodeError, TypeError):
        d["config"] = {}
    return d


def get_dashboard_widget(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM dashboard_widgets WHERE uid = ?", (uid,)).fetchone()
    return _widget_row_to_dict(row) if row else None


def list_dashboard_widgets(conn: sqlite3.Connection, space_uid: str | None = None) -> list[dict[str, Any]]:
    """Widgets for one page's grid -- Home (space_uid=None, the default,
    matching every pre-existing widget's value after the space_uid
    migration) or a specific Space (routers/projects.py's space_detail).
    Includes both top-level widgets and stack members (same as before this
    scoping existed) -- callers that need to tell them apart already
    filter on group_uid themselves (see _build_widget_contexts). Use
    list_all_dashboard_widgets below instead when you need to look up a
    widget/stack by uid or group_uid without knowing which page it's on
    (e.g. dissolving a stack -- its uid is globally unique regardless of
    which page's grid it's in)."""
    rows = conn.execute(
        "SELECT * FROM dashboard_widgets WHERE space_uid IS ? ORDER BY position ASC", (space_uid,)
    ).fetchall()
    return [_widget_row_to_dict(r) for r in rows]


def list_all_dashboard_widgets(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every widget on every page (Home + every Space), regardless of
    space_uid -- see list_dashboard_widgets' docstring for when to reach
    for this instead."""
    rows = conn.execute("SELECT * FROM dashboard_widgets ORDER BY position ASC").fetchall()
    return [_widget_row_to_dict(r) for r in rows]


def next_dashboard_widget_position(conn: sqlite3.Connection, space_uid: str | None = None) -> float:
    # Scoped to top-level widgets (group_uid IS NULL) on this one page
    # (space_uid) -- this always means "the position that puts a widget at
    # the end of *this page's* top-level order" (a brand-new widget via
    # add_widget, or one just popped out of a stack via unstack_widget),
    # never a stack member's own position (a completely separate, usually
    # much smaller range) or another page's ordering.
    max_pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) FROM dashboard_widgets WHERE group_uid IS NULL AND space_uid IS ?",
        (space_uid,),
    ).fetchone()[0]
    return max_pos + 1


def delete_dashboard_widget(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM dashboard_widgets WHERE uid = ?", (uid,))
    conn.commit()


def swap_dashboard_widget_positions(conn: sqlite3.Connection, uid_a: str, uid_b: str) -> None:
    """Same swap-with-neighbor reorder primitive as
    routers/databases.py's move_column -- simplest correct "move up"/
    "move down" without renumbering the rest of the list."""
    a = get_dashboard_widget(conn, uid_a)
    b = get_dashboard_widget(conn, uid_b)
    if a is None or b is None:
        return
    conn.execute("UPDATE dashboard_widgets SET position = ? WHERE uid = ?", (b["position"], uid_a))
    conn.execute("UPDATE dashboard_widgets SET position = ? WHERE uid = ?", (a["position"], uid_b))
    conn.commit()


def get_app_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_app_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
