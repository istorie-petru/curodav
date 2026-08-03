"""SQLite Query Cache schema (REWORK_PLAN §6.3).

Mirrors ARCHITECTURE.md §4 tables. Populated incrementally via watchdog.
FTS5 virtual table over title + description + body for search.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS objects (
    id            TEXT PRIMARY KEY,
    workspace_id  TEXT NOT NULL DEFAULT 'default',
    type          TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    icon          TEXT,
    cover_path    TEXT,
    status        TEXT NOT NULL DEFAULT 'active',
    priority      INTEGER,
    progress      REAL,
    start_at      TEXT,
    due_at        TEXT,
    pinned        INTEGER NOT NULL DEFAULT 0,
    parent_id     TEXT REFERENCES objects(id),
    sort_key      TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    deleted_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_objects_type_status ON objects(type, status) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_objects_due ON objects(due_at) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_objects_parent ON objects(parent_id);

CREATE TABLE IF NOT EXISTS task_details (
    object_id      TEXT PRIMARY KEY REFERENCES objects(id),
    checklist      TEXT NOT NULL DEFAULT '[]',
    estimate_min   INTEGER,
    time_spent_min INTEGER NOT NULL DEFAULT 0,
    recurrence     TEXT,
    waiting_on     TEXT
);

CREATE TABLE IF NOT EXISTS event_details (
    object_id   TEXT PRIMARY KEY REFERENCES objects(id),
    end_at      TEXT,
    all_day     INTEGER NOT NULL DEFAULT 0,
    location    TEXT,
    meeting_url TEXT,
    recurrence  TEXT,
    calendar_id TEXT,
    reminders   TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS note_details (
    object_id  TEXT PRIMARY KEY REFERENCES objects(id),
    body       TEXT NOT NULL DEFAULT '',
    is_daily   INTEGER NOT NULL DEFAULT 0,
    daily_date TEXT,
    template   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS project_details (
    object_id  TEXT PRIMARY KEY REFERENCES objects(id),
    color      TEXT,
    milestones TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS board_details (
    object_id TEXT PRIMARY KEY REFERENCES objects(id),
    columns   TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS links (
    id         TEXT PRIMARY KEY,
    from_id    TEXT NOT NULL REFERENCES objects(id),
    to_id      TEXT NOT NULL REFERENCES objects(id),
    link_type  TEXT NOT NULL DEFAULT 'related',
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    UNIQUE(from_id, to_id, link_type)
);

CREATE INDEX IF NOT EXISTS idx_links_to ON links(to_id);

CREATE TABLE IF NOT EXISTS tags (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    color      TEXT,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS object_tags (
    object_id TEXT NOT NULL REFERENCES objects(id),
    tag_id    TEXT NOT NULL REFERENCES tags(id),
    PRIMARY KEY (object_id, tag_id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id         TEXT PRIMARY KEY,
    object_id  TEXT NOT NULL REFERENCES objects(id),
    sha256     TEXT NOT NULL,
    filename   TEXT NOT NULL,
    mime       TEXT,
    size_bytes INTEGER,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS activities (
    id        TEXT PRIMARY KEY,
    object_id TEXT NOT NULL,
    kind      TEXT NOT NULL,
    detail    TEXT,
    at        TEXT NOT NULL,
    device_id TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS objects_fts USING fts5(
    title, description, body,
    content='', tokenize='unicode61 remove_diacritics 2'
);

PRAGMA user_version = 1;
"""
