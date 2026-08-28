"""SQLite storage for the web app's calendar/task/contact data.

2026-08-07: fixed a stale module docstring found while adding
`tasks.completed_at` -- this used to say "Radicale is the source of
truth... this database is a disposable, rebuildable mirror," which was
true before Phase 1 of the label-space rework (plans/
label-space-rework.md §1, 2026-08-06) and has been wrong ever since,
contradicted by literally every comment further down this same file. The
base pool (`tasks`/`events`/`contacts`) is plain SQL now, full stop -- no
Radicale relationship, no `href`/`etag`, nothing to "sync" into it.
Radicale is used for exactly one thing in this app post-rework:
materializing and serving opt-in Published Lists (`published_lists`
table, `src/published_lists.py`) -- a derived, one-way export of a
label-filtered subset, not this database's source of truth.

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
Subtasks existed via `tasks.parent_uid` (round-tripping through
RELATED-TO;RELTYPE=PARENT in ical_rows.py) until the 1.2 task-model
decision removed the hierarchy entirely -- tasks are flat and independent
(see the `tasks` CREATE TABLE comment), so nothing here round-trips a
parent relationship anymore.

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

import hashlib
import json
import logging
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

# habit_heatmap imports nothing from this module (or any router) -- see its
# own module docstring -- so db.py depending on it for
# habit_work_sessions_status's recurrence_frequency() lookup below doesn't
# risk a cycle.
from . import habit_heatmap

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- Phase 1 (label-space rework, 2026-08-06): dropped href/etag/
-- calendar_path/raw_ics -- base storage is plain SQL now, no Radicale
-- relationship at all (see features/architecture.md §1). Collection
-- membership (which calendar an event used to live in) became an
-- `object_labels` row via scripts/migrate_labels.py instead. Every other
-- column stays -- still enough to serialize a valid VEVENT on demand
-- (ical_rows.py) for export and for a future published List (Phase 6).
CREATE TABLE IF NOT EXISTS events (
    uid TEXT PRIMARY KEY,
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
    -- 1.6 ("Generalized recurrence and the non-working-day policy"): any
    -- recurring event -- not just a Schedule class meeting -- can specify
    -- how it behaves on non-working days. A holiday calendar (see
    -- `schedule_holidays` above) is deliberately a *different* kind of
    -- constraint from a weekend exclusion (open-priority.md: "A public
    -- holiday and a weekend are deliberately different kinds of
    -- constraints even though both may cause an occurrence to be
    -- skipped"), so these are three independent fields, not one enum:
    -- `holiday_calendar` (a calendar_name from schedule_holidays, or NULL
    -- = respects no calendar), `exclude_saturday`/`exclude_sunday`
    -- (independent booleans -- an event can exclude one weekend day, both,
    -- or neither, regardless of its holiday_calendar setting). Applied at
    -- *read* time by `recurrence_expand.expand_events` (never materialized
    -- into `exdates_json`), same "don't store derived values" rule as
    -- everywhere else in this app -- changing a holiday calendar's dates
    -- or an event's policy takes effect immediately, with no "regenerate"
    -- step required.
    holiday_calendar TEXT,
    exclude_saturday INTEGER NOT NULL DEFAULT 0,
    exclude_sunday INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);

-- Phase 1: dropped href/etag/calendar_path/list_path/raw_ics -- see the
-- `events` table comment above for the full rationale (same migration).
-- `completed_at` (2026-08-07, plans/open.md's
-- Streak widget): the one thing this table couldn't answer before --
-- *which day* a plain (non-recurring) task was completed. `status`
-- flipping to done/archived told you *that* it's done; `updated_at`
-- changes on any edit, not just completion, so it can't stand in for
-- this. Recurring tasks already had an equivalent (`task_completions`,
-- below) but that's a narrower, separate mechanism for per-occurrence
-- check-offs, not every task. Auto-managed by upsert_task (see its own
-- comment) -- set the moment status transitions to done/archived,
-- cleared the moment it transitions away, left alone on any edit that
-- doesn't touch status, and never overridden if a caller explicitly
-- supplies a value (e.g. scripts/JSON restore importing real history).
CREATE TABLE IF NOT EXISTS tasks (
    uid TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    start_at TEXT,
    due_at TEXT,
    -- 1.1 (virtual & derived states, plans/open-priority.md § Virtual &
    -- derived states) introduced Importance/Urgency as two explicit 1..3
    -- axes, replacing the old WebDAV `priority` concept. A later rework
    -- (side work, see this file's `_drop_column` calls below) removed the
    -- explicit axes entirely -- both are now purely computed
    -- (src/derived_state.py) from label rules + temporal state, never
    -- manually set, so the `importance`/`urgency` columns no longer exist
    -- on new databases. The old `priority` column stays physically on disk
    -- for pre-1.1 databases but is no longer referenced by app code.
    priority INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    progress REAL,
    -- 1.2 (task model, plans/open-priority.md § Subtask model -- the open
    -- conflict, resolved): the parent-task/subtask hierarchy is removed;
    -- tasks are flat, independent units of work (the outcome/parent
    -- aggregation is reproduced by a project label plus its tasks, and
    -- multiple work sessions on one task are work allocations in 1.4, not
    -- child tasks). The old `parent_uid` column stays physically on disk
    -- for pre-1.2 databases but is no longer referenced by app code --
    -- same "never force-drop old data" convention as the old `priority`
    -- column above. The idx_tasks_parent index was likewise removed from
    -- SCHEMA_SQL for new databases (an existing database keeps its own).
    parent_uid TEXT,
    recurrence TEXT,
    exdates_json TEXT NOT NULL DEFAULT '[]',
    completed_at TEXT,
    -- 2026-08-08: only meaningful for a habit-labeled task (see
    -- task_habit_settings/task_completions.value above) -- how many
    -- check-ins a day counts as "done" (1 = plain checkbox, >1 = a
    -- number-stepper habit like "glasses of water"). Harmless default for
    -- every ordinary task, which never reads it.
    target_per_day REAL NOT NULL DEFAULT 1,
    created_at TEXT,
    updated_at TEXT
);



-- Phase 1: dropped href/etag/addressbook_path/raw_vcard -- see `events`
-- table comment above for the full rationale. Phase 5 (label-space
-- rework, 2026-08-07) dropped `category` too -- it was a free-text
-- grouping field that duplicated what a label (object_labels) already
-- does; grouping/filtering contacts is now 100% by label, same mechanism
-- as tasks/events. See features/architecture.md §3 Phase 5.
CREATE TABLE IF NOT EXISTS contacts (
    uid TEXT PRIMARY KEY,
    full_name TEXT NOT NULL DEFAULT '',
    title TEXT,
    org TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    notes TEXT,
    -- Photo, added 2026-07-31 -- base64-encoded image bytes + the format
    -- ("JPEG"/"PNG"/...), round-tripped through the vCard PHOTO property
    -- (vcard_rows.py) rather than stored as a local file, so a photo
    -- uploaded here actually syncs to every other CardDAV client (phone,
    -- desktop) instead of being a web-app-only attachment.
    photo_b64 TEXT,
    photo_type TEXT,
    created_at TEXT,
    updated_at TEXT
);


-- Contacts field parity with Nextcloud Contacts (plans/open.md), slice 2 of
-- 6 (Phone/Email, following slice 1's Title). `contacts.phone`/`contacts.
-- email` above are single-value and stay physically present (never
-- force-dropped, this file's standing convention) but are DEAD from this
-- slice forward -- nothing here writes them anymore. A real person routinely
-- has more than one phone number or email address, each meaningfully typed
-- (home vs. work vs. cell), so a flat column was always going to need this
-- rework eventually; keeping it "live" as a synced mirror of some
-- designated-primary child row would mean reconciling two sources of truth
-- on every write for no real benefit (nothing left reads the flat column),
-- so it's simplest to just freeze it as a migration source (see
-- migrate_legacy_contact_phone_email below) and stop touching it. Same
-- natural-key-less "real owned child row" shape as task_checklist_items
-- (plain TEXT uid PK, no FOREIGN KEY constraint -- this app doesn't use
-- them anywhere, see _ensure_column's own docstring for the "no force-drop"
-- convention this table's dead-column choice above still honors) --
-- `contact_uid` is a real ownership column, not a natural key, since a
-- contact can have several phones/emails of the very same type ("Home" and
-- a second "Home" number is a real, if rare, case a natural key couldn't
-- represent). `type` is free text at the storage layer (vCard/Nextcloud's
-- vocabulary -- Home/Work/Cell/Fax/Pager for phone, Home/Work for email,
-- plus Other for both -- is enforced by the `<select>` in contact_form.html
-- and CONTACT_PHONE_TYPES/CONTACT_EMAIL_TYPES below, not a CHECK
-- constraint, matching this file's general preference for validating in
-- Python over SQL). `position` is the same float sort key task_checklist_
-- items uses so display order survives a full replace-on-save without
-- needing per-row uid tracking across an edit (see set_contact_phones/
-- set_contact_emails).
CREATE TABLE IF NOT EXISTS contact_phones (
    uid TEXT PRIMARY KEY,
    contact_uid TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'Other',
    value TEXT NOT NULL DEFAULT '',
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS contact_emails (
    uid TEXT PRIMARY KEY,
    contact_uid TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'Other',
    value TEXT NOT NULL DEFAULT '',
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT
);

-- Contacts field parity slice 3 of 6 -- Website. There has never been a
-- single-value website-ish column on `contacts` (confirmed by grepping
-- db.py/vcard_rows.py/contact_form.html/contact_detail.html before writing
-- this table -- unlike Phone/Email above, there is genuinely nothing to
-- auto-migrate here), so this is a brand-new field, multi-value from day
-- one -- same shape as contact_phones/contact_emails immediately above
-- (owned child rows keyed by `contact_uid`, no FOREIGN KEY constraint,
-- float `position` sort key). vCard's property is URL, not a typed multi-
-- instance property in the RFC 2426/6350 core the way TEL/EMAIL are, but
-- vobject supports repeated `URL;TYPE=...:` lines identically (confirmed
-- empirically -- see vcard_rows.py's module docstring) so the column is
-- named `url` (the vCard property name) rather than `value`, purely for
-- readability at this call site; the shape is otherwise identical.
CREATE TABLE IF NOT EXISTS contact_websites (
    uid TEXT PRIMARY KEY,
    contact_uid TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'Other',
    url TEXT NOT NULL DEFAULT '',
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT
);

-- Contacts field parity slice 5 of 6 -- Address (plans/open.md). The old
-- `contacts.address` column above is a single free-text line; a real vCard
-- ADR is a structured, typed, MULTI-instance property (RFC 2426/6350 --
-- box/extended/street/city/region/postal code/country, same 7-part
-- structure vobject.vcard.Address models directly), confirmed empirically
-- against vobject before writing this table: `card.add("adr")` is
-- repeatable and `card.adr_list` reads every line back, each with its own
-- `.type_param`, identically to `tel_list`/`email_list`/`url_list` (see
-- vcard_rows.py's module docstring). So this is the same owned-child-row
-- shape as contact_phones/contact_emails/contact_websites immediately
-- above (`contact_uid` ownership column, no FOREIGN KEY, float `position`
-- sort key), just with seven value columns instead of one. Type vocabulary
-- is Home/Work/Other (green-lit, AskUserQuestion, 2026-08-15 -- "same as
-- email/address" -- see CONTACT_ADDRESS_TYPES below), matching email/
-- website, not phone's wider Cell/Fax/Pager set (vCard's ADR has no
-- concept of those). Column names follow vobject.vcard.Address's own
-- attribute names (box/extended/street/city/region/code/country) except
-- `code` is spelled out as `postal_code` here for readability at this
-- table's own call sites -- purely a naming choice, no behavior
-- difference. Unlike Website, there IS a legacy single-value column to
-- migrate from (`contacts.address`) -- see migrate_legacy_contact_address
-- below, same "auto-migrate the old flat value into a single 'Other'-typed
-- entry" shape migrate_legacy_contact_phone_email already established.
CREATE TABLE IF NOT EXISTS contact_addresses (
    uid TEXT PRIMARY KEY,
    contact_uid TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'Other',
    po_box TEXT NOT NULL DEFAULT '',
    extended TEXT NOT NULL DEFAULT '',
    street TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    postal_code TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT
);

-- Contacts field parity slice 6 of 6 -- Social network (plans/open.md), the
-- last field in the build order. Round-trips via the standard X-
-- SOCIALPROFILE vCard property (green-lit, AskUserQuestion, 2026-08-15).
-- Same owned-child-row shape as contact_phones/contact_emails/
-- contact_websites (single `value` column, `contact_uid` ownership, no
-- FOREIGN KEY, float `position` sort key) -- unlike Address, X-
-- SOCIALPROFILE has no internal structure to split into columns, it's a
-- single value (a profile URL or handle) plus a TYPE= naming the network.
-- No pre-existing single-value social-network column ever existed on this
-- app (confirmed by grepping db.py/vcard_rows.py/contact_form.html before
-- writing this), so -- same as Website -- there is nothing to auto-
-- migrate. Type vocabulary is network names (db.CONTACT_SOCIAL_TYPES),
-- not the Home/Work/Other set every other typed contact field uses --
-- "which network" is the meaningful distinction here, not "which
-- location/context."
CREATE TABLE IF NOT EXISTS contact_social_profiles (
    uid TEXT PRIMARY KEY,
    contact_uid TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'Other',
    value TEXT NOT NULL DEFAULT '',
    position REAL NOT NULL DEFAULT 0,
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

-- Explicit event<->task relations (2026-08-09, "Relations", the webapp's
-- associative-link replacement for desktop's links graph -- see
-- features/architecture.md Phase 8, which left it an accepted gap).
-- This is a many-to-many graph link between two *different* object types:
-- one event row + one task row, either direction. Same no-FK, natural-key
-- convention as object_labels: the composite PK *is* the link, "deleting"
-- is a plain DELETE, and stale rows are cleaned up by delete_event/
-- delete_task's cascades below. (The 1.2 task-model decision removed the
-- task->task structural parent link -- `tasks.parent_uid`, which this
-- comment used to contrast against -- but the cross-type relation here is
-- a separate mechanism and is unaffected.) A relation is only ever created
-- when the two objects share at least one label (the UI filters its link
-- picker to candidates that already do, and the routers re-check
-- defensively) -- "both have at least one label in common" is the
-- definition of related here, and the label overlap is what the Relations
-- cards render under.
-- 1.4 (Work allocations, plans/open-priority.md § Work allocations): a work
-- allocation is *not* a new table -- it's an ordinary event_task_relations
-- row with `is_work_allocation=1`. "A work allocation... is a calendar
-- Event linked to that task, not a different kind of calendar object" --
-- the marker exists only so code can tell "this link is scheduled work
-- time" apart from an ordinary Relations-card link (same event, same task,
-- same table; the flag is the only difference). A relation can only ever
-- be one or the other for a given event/task pair since the PK is still
-- (event_uid, task_uid) -- no dual-purpose row needed, and none of the
-- ordinary-relation rules above (label-overlap requirement, associative
-- unlink) apply to a work-allocation row, which is created directly by
-- db.create_work_allocation, not the Relations picker.
CREATE TABLE IF NOT EXISTS event_task_relations (
    event_uid TEXT NOT NULL,
    task_uid TEXT NOT NULL,
    created_at TEXT,
    is_work_allocation INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (event_uid, task_uid)
);

CREATE INDEX IF NOT EXISTS idx_event_task_relations_task ON event_task_relations(task_uid);

-- Phase 1 (label-space rework) -- the one join table labels use. Not an
-- entity with a lifecycle (see features/architecture.md §0.1): no
-- surrogate id, `label_name` is the natural key, and "deleting" a label
-- is just removing every row that names it. `object_type` is
-- 'task'|'event'|'contact' for now; more types land in later phases.
-- Phase 2 (label-space rework): object_type now also covers
-- 'schedule_class'|'habit' -- each of those tables' former `project_uid`
-- FK column collapses onto this same table (see db.py's Phase 2 comments
-- on schedule_classes/habits below). object_type='database' rows existed
-- here too for a while (the Custom databases feature reused the same
-- project-link mechanism), but that feature is gone entirely as of
-- 2026-08-07 -- see the SCHEMA_SQL removal note further down.
CREATE TABLE IF NOT EXISTS object_labels (
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    label_name TEXT NOT NULL,
    PRIMARY KEY (object_type, object_id, label_name)
);

CREATE INDEX IF NOT EXISTS idx_object_labels_lookup ON object_labels(object_type, label_name);
CREATE INDEX IF NOT EXISTS idx_object_labels_object ON object_labels(object_type, object_id);

-- Sparse, optional per-label config -- a label with no row here still
-- fully works (default color, not a Space, still shows up in "manage
-- labels" purely because object_labels mentions it). Phase 2 adds the
-- behavior columns: `generate_space` (1 = this label gets a Space page,
-- aggregating direct object_labels membership only -- see
-- features/architecture.md §2/§5), `dashboard_preset_json` (reserved,
-- unused until a later phase). Every former `project_groups` row became a
-- label_config row with generate_space=1; every former `projects` row
-- became one with generate_space=0 and parent_name set to its former
-- Space's label name.
--
-- 2026-08-08: `enabled_modules_json` (Phase 4's per-label "Sections"
-- checkbox group, gating whether a Space page's Course info/Homework
-- blocks rendered) and `pinned` (a separate opt-in step to show a Space
-- in the nav rail) are both gone -- removed outright, not just unused,
-- same as the `grades`/`databases` tables above. Neither survived
-- contact with how this app's architecture actually works now: every
-- Space already shows Course info/Homework by default whenever it has
-- matching data (the "Sections" checkboxes only ever let someone
-- deliberately hide a section that had real data -- nobody did, and two
-- of its five options never gated anything to begin with), and a label
-- worth turning into a Space is a label worth finding quickly -- an
-- extra pin step was friction with no offsetting benefit, not real
-- functionality. See label_detail.html/labels_manage.html and
-- deps.py/base.html for what replaced both.
CREATE TABLE IF NOT EXISTS label_config (
    name TEXT PRIMARY KEY,
    color TEXT NOT NULL DEFAULT 'blue',
    icon TEXT,
    description TEXT,
    parent_name TEXT,
    label_group TEXT,
    generate_space INTEGER NOT NULL DEFAULT 0,
    dashboard_preset_json TEXT,
    -- 2026-08-09: a short alias (max 5 characters) for a label, used as a
    -- Space's display text in the nav rail (base.html) and accepted as a
    -- synonym wherever a label name is typed/saved (see
    -- set_object_labels). Optional -- a label without one just uses its
    -- full name everywhere.
    abbreviation TEXT,
    -- 1.1 (virtual & derived states, plans/open-priority.md § Virtual &
    -- derived states): label behavior rules feeding the Importance/Urgency
    -- effective-value derivation. `importance` is the importance this label
    -- implies for anything carrying it (1..3, NULL = no rule); `urgency_
    -- threshold_days` makes this label imply urgency (level 3) once the
    -- carrying entity's date falls within that many days ahead (NULL = no
    -- rule). Persistent, stored configuration belonging to the label -- the
    -- one category of derived-state input that is deliberately *not* a
    -- query-time calculation (see that section's "Project behavior and
    -- other persistent label behaviors are the exception").
    importance INTEGER,
    urgency_threshold_days INTEGER,
    -- 1.3 (Project-enabled label stack, plans/open-priority.md § Project-
    -- enabled label stack): a project is not a separate entity, it's a
    -- label with `is_project=1` plus a bounded period (`start_date`/
    -- `end_date`, ISO 'YYYY-MM-DD') and a lifecycle. Unlike
    -- generate_space (a display toggle), is_project changes what the
    -- label *means* -- see project_label_for's 1.3 note for how this
    -- supersedes the old "any non-Space label is the project" heuristic.
    -- `archived_at` is the one persisted lifecycle fact (the user's
    -- explicit confirmation that the project is finished, per the "end
    -- date does not silently archive it" rule) -- Open/Pending/Pending
    -- Archiving are all computed at read time from archived_at + task
    -- completion + end_date, see project_status() below, not stored,
    -- because they're derived from data that changes underneath the
    -- label (tasks completing) the same way Importance/Urgency are.
    is_project INTEGER NOT NULL DEFAULT 0,
    start_date TEXT,
    end_date TEXT,
    archived_at TEXT,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_at);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_at);
CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(full_name);
CREATE INDEX IF NOT EXISTS idx_checklist_task ON task_checklist_items(task_uid);
CREATE INDEX IF NOT EXISTS idx_contact_phones_contact ON contact_phones(contact_uid);
CREATE INDEX IF NOT EXISTS idx_contact_emails_contact ON contact_emails(contact_uid);
CREATE INDEX IF NOT EXISTS idx_contact_websites_contact ON contact_websites(contact_uid);
CREATE INDEX IF NOT EXISTS idx_contact_addresses_contact ON contact_addresses(contact_uid);
CREATE INDEX IF NOT EXISTS idx_contact_social_profiles_contact ON contact_social_profiles(contact_uid);

-- 1.6 (Schedule & recurrence rework, 2026-08-13): `schedule_classes` was
-- dropped from a brand-new database's schema then -- a university class
-- stopped being its own entity mirrored one-way into `events`, becoming a
-- real recurring `event` tagged with its course's project-enabled label
-- instead. An existing cache.sqlite from before that migration still
-- physically has this table and its rows on disk (never force-dropped,
-- same "don't touch old data automatically" convention as every other
-- table removal in this file), but nothing in this module's own code has
-- read/written it since.
--
-- 2026-08-15: the Schedule module itself (routers/schedule.py, schedule.py,
-- the `/schedule` UI, `schedule_settings`, and label_config's `course_*`
-- columns) is removed entirely -- odd/even-week recurrence is now
-- available directly on ordinary Calendar events, which fully superseded
-- Schedule's one distinguishing feature; see plans/STATE.md's removal
-- entry. `schedule_holidays` (below) is untouched -- it's a generic,
-- named holiday-calendar mechanism any recurring event can use, unrelated
-- to Schedule specifically (1.6 "Generalized non-working-day policy").

-- 2026-08-07: `grades` (the per-class assessment tracker) removed along
-- with the rest of the Databases/Grades feature -- see the `databases`/
-- `database_columns`/`database_rows` removal note further down and
-- features/architecture.md's Grades/Databases removal note. Grades
-- was explicitly chosen to go away *with* Databases, not survive as its
-- own thing, even though it had its own dedicated table (Phase 9) rather
-- than living on the generic databases engine.

-- 1.6 (Schedule & recurrence rework, "Generalized recurrence and the
-- non-working-day policy"): a holiday is now a dated range under a named,
-- reusable **holiday calendar** (`calendar_name` -- e.g. `Romania`,
-- `University`, `Personal`), not one single flat exclusion list shared by
-- everything. There is deliberately no separate `holiday_calendars` table
-- -- a calendar is just the set of distinct `calendar_name` values in use
-- here, same "a name is the identity, no surrogate row required" pattern
-- `object_labels`/labels already use; `db.list_holiday_calendar_names`
-- reads it back. `calendar_name` defaults to `'Default'` so every holiday
-- row that existed before this migration (all under one flat list) keeps
-- working unchanged under that name, still reachable from any event or
-- class that referenced holidays before this rework existed.
CREATE TABLE IF NOT EXISTS schedule_holidays (
    uid TEXT PRIMARY KEY,
    calendar_name TEXT NOT NULL DEFAULT 'Default',
    label TEXT NOT NULL DEFAULT '',
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL
);

-- Phase 2 (label-space rework, 2026-08-06): `tags`/`tag_groups`/
-- `project_groups`/`projects` are GONE -- every former row of each became
-- an `object_labels`/`label_config` row via scripts/migrate_labels.py (see
-- features/architecture.md §2/§3 Phase 2). object_labels is now the
-- sole assignment mechanism for tasks/events/contacts/habits; label_config
-- carries color/icon/description/parent_name/generate_space for any label
-- that needs them.

-- Habit tracking -- local-only, same category as the deleted
-- projects/tags tables above: no CalDAV/CardDAV concept for "a daily habit
-- and its check-in history." `target_per_day` is only used to scale
-- heatmap color intensity (e.g. a "drink water" habit logged 8/8 glasses
-- paints darker than 2/8) -- it is NOT a requirement for a day to "count";
-- any logged value > 0 counts as done for streak purposes (habits.py's
-- _streaks). Phase 2 dropped this table's own `tags_json`/`project_uid`
-- columns -- a habit's tags *and* its optional project link are now both
-- just `object_labels` rows (object_type='habit'); the one that also has
-- a `label_config` row with generate_space=0 is treated as "the project"
-- for display (db.py's `project_label_for`).
CREATE TABLE IF NOT EXISTS habits (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT 'blue',
    icon TEXT,
    target_per_day REAL NOT NULL DEFAULT 1,
    archived_at TEXT,
    created_at TEXT,
    updated_at TEXT
);

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

-- Recurring-task completions (Phase 5 rework) -- one row per (task, due
-- date), the daily check-off history for recurring tasks that drives their
-- heatmap/streak view. Local-only, same as habit_entries: a completion is
-- a property of the recurring task's *pattern*, not a separate CalDAV
-- event, so there's nothing to sync. A plain (non-recurring) task never
-- writes here -- it just flips to done like a normal task.
CREATE TABLE IF NOT EXISTS task_completions (
    task_uid TEXT NOT NULL,
    due_date TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    -- 2026-08-08: habit-tracked tasks (see the "habit label" feature,
    -- routers/tasks.py's habits_view) need the same "1 = done, or a real
    -- quantity for a target>1 habit" value habit_entries.value already
    -- has -- a plain recurring task's own checkbox-only completion still
    -- always writes 1 here, so this is purely additive.
    value REAL NOT NULL DEFAULT 1,
    PRIMARY KEY (task_uid, due_date)
);

-- 2026-08-08 ("add habits page as a view on tasks") -- app-wide setting
-- for which label name marks a task as habit-tracked (hidden from every
-- normal task view/widget, shown instead on Tasks > Habits with a
-- checkbox/stepper check-in and a heatmap, same shape as the standalone
-- Habits feature but sourced from labeled tasks + task_completions
-- instead of the habits/habit_entries tables). One row, same
-- id-must-be-1 singleton pattern task_habit_settings' own peers use.
CREATE TABLE IF NOT EXISTS task_habit_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    habit_label TEXT NOT NULL DEFAULT 'Habit'
);

-- 2026-08-07: `databases`/`database_columns`/`database_rows` (Phase 7's
-- Notion-like custom-table engine, plus `formula_engine.py`) removed
-- entirely -- deactivated and deleted, not just unlinked from nav, per
-- explicit instruction: Databases and everything built on it (including
-- Grades, which reused this engine) goes away. See plans/
-- label-space-rework.md's Grades/Databases removal note. A cache.sqlite
-- file from before this removal may still physically carry these tables
-- (never force-dropped, same "don't touch old data automatically"
-- convention as every other table removal in this file) -- nothing in
-- this module's own code reads/writes them anymore.

-- Dashboard widgets (Phase 8) -- local-only, per-device layout, same
-- category as everything else in this section. `type` is a key into
-- routers/dashboard.py's WIDGET_TYPES registry (e.g. 'today_agenda',
-- 'weekly_overview', 'upcoming_events') -- adding a new widget type later
-- is a new registry entry + render function, not a schema change, which
-- is what "extensible" means here concretely. `config_json` holds every
-- widget's filters (project_uid, tags, task_list_uids, calendar_uids) in
-- one blob rather than separate columns, since different widget types
-- use different subsets of the same filter vocabulary -- same "one JSON
-- blob, not a rigid column-per-field schema" tradeoff the now-removed
-- `database_rows` table used to make for the same reason. `position` is
-- the familiar float sort key.
-- Phase 2 (label-space rework): `space_uid`/`project_uid` collapse to one
-- `label_name` column -- a Space page and a Project page are now the same
-- kind of page (a label's page, see features/architecture.md §2 item
-- 4), so there's no need for two mutually-exclusive FK columns. NULL means
-- Home; a set value is the label whose page this widget belongs to. Which
-- *kind* of page that label renders (Space vs. plain label/"project" page)
-- is derived at read time from label_config.generate_space, not stored
-- redundantly here -- see _widget_row_to_dict.
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
-- settings (those live on their own real tables -- task_habit_settings,
-- etc.) -- this is strictly internal migration/bookkeeping state.
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Published Lists (Phase 6, label-space rework, 2026-08-07) -- a
-- Settings-created, named boolean filter over labels for exactly one
-- entity type (task/event/contact), materialized into a real Radicale
-- collection and published as a subscribable CalDAV/CardDAV URL. See
-- features/architecture.md §2/§3 Phase 6 and src/published_lists.py
-- for the materializer. `label_filter_json` holds a small structured
-- expression, not a query language -- {"all": [...], "any": [...],
-- "none": [...]} (AND of `all`, at least one of `any` if non-empty, NOT
-- any of `none`), evaluated by published_lists.evaluate_label_filter.
-- `radicale_collection_path` is the derived collection's own name --
-- globally unique so two Lists never collide on the same collection.
-- `sync_direction` only has `read_only` implemented in this version (the
-- column exists now so a future two-way mode doesn't need a migration).
-- Unlike a label (§0.1 -- no delete endpoint, "removing" just clears
-- membership), a published List is a real thing with a lifecycle: it has
-- a derived Radicale collection that must be created materializing and
-- torn down on delete, so THIS is the one real "delete" action left in
-- the whole plan (routers/published_lists.py's delete route).
CREATE TABLE IF NOT EXISTS published_lists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    label_filter_json TEXT NOT NULL,
    radicale_collection_path TEXT NOT NULL UNIQUE,
    sync_direction TEXT NOT NULL DEFAULT 'read_only',
    last_materialized_at TEXT,
    created_at TEXT
);

-- 1.6 ("Manual recurrence exceptions", plans/open-priority.md § Schedule &
-- recurrence rework): the recurrence system distinguishes three things --
-- the recurrence rule (events.recurrence), the generated occurrences
-- (computed, never stored -- recurrence_expand.py), and manual exceptions
-- or overrides for ONE specific occurrence, which is what this table is.
-- "uid" is a deterministic composite key (master_uid + '::' +
-- occurrence_date, see db.py's _occurrence_override_uid), not a random
-- uuid -- there's exactly one override per (master, original occurrence),
-- so upserting by that pair is more natural than tracking a separate id.
-- `occurrence_date` is the ORIGINAL occurrence's own start_at (the RFC
-- 5545 RECURRENCE-ID this overrides), always in ISO date or datetime
-- form matching the master's own DTSTART precision.
--
-- Cancelling an occurrence (`cancelled=1`) folds its `occurrence_date`
-- into the master's own EXDATE list at expand time (recurrence_expand.py)
-- -- the same proven exclusion mechanism `exdates_json` already uses, not
-- a separate code path. Moving/modifying an occurrence (`cancelled=0`,
-- `start_at` set) becomes a second real VEVENT sharing the master's UID
-- with a RECURRENCE-ID (ical_rows.py's `event_row_to_ical`
-- `recurrence_id` support) -- the standard RFC 5545 override mechanism,
-- which `recurring_ical_events` (already this app's expansion library)
-- resolves for free. `title`/`location` are optional per-occurrence
-- overrides (NULL = keep the master's own); day-to-day "move this one
-- lecture to Tuesday" only ever needs start_at/end_at.
CREATE TABLE IF NOT EXISTS event_occurrence_overrides (
    uid TEXT PRIMARY KEY,
    master_uid TEXT NOT NULL,
    occurrence_date TEXT NOT NULL,
    cancelled INTEGER NOT NULL DEFAULT 0,
    start_at TEXT,
    end_at TEXT,
    title TEXT,
    location TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_occurrence_overrides_master ON event_occurrence_overrides(master_uid);

-- 1.9 side work ("Sleep Time / Leisure Time", direct feedback): weekly
-- recurring soft-scheduling guidance blocks -- "this time of day, on these
-- days of the week, is meant for X" (e.g. sleep 00:00-05:59 Monday-Sunday,
-- leisure 21:00-21:59 Monday-Sunday). Deliberately NOT shaped like
-- schedule_holidays (a dated range under a user-named, open-ended
-- calendar) -- a time block has no date component at all, just a
-- time-of-day range plus a day-of-week set, and `kind` is one of exactly
-- two fixed categories (not a user-named set) since the feature request
-- named exactly these two. Rendered as a soft diagonal-hatch overlay on
-- the Week/Day grid (red for sleep, green for leisure, see
-- routers/calendar.py's `_time_block_overlays`) and produces a
-- non-blocking warning (never a hard block) when an event or work
-- allocation is scheduled to overlap one -- see static/time_blocks.js.
-- `days` is a comma-separated subset of db.TIME_BLOCK_DAYS, stored as full
-- weekday names so a row reads directly in the admin table with no lookup.
CREATE TABLE IF NOT EXISTS time_blocks (
    uid TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('sleep', 'leisure')),
    label TEXT NOT NULL DEFAULT '',
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    days TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_time_blocks_kind ON time_blocks(kind);

-- 1.8 slice 1 ("Field-HLC shadow store + sync API skeleton",
-- plans/open-priority.md § Offline-first editing & synchronization §9):
-- purely sync-infrastructure metadata, not a fourth kind of domain entity
-- (features/architecture.md §1.4) -- `tasks`/`events`/`contacts` keep
-- their own columns as the single source of truth for a field's *value*;
-- this table only remembers the HLC each field was last written at, so
-- the server can tell "is this incoming write newer than what I already
-- have" (§6) without conflating that with the value itself. `deleted_at`
-- is tracked here as an ordinary field name like any other (§4: a delete
-- is a field write, not a row removal -- see `tasks`/`events`/`contacts`'
-- own new `deleted_at` column below), which is what makes "an edit newer
-- than the tombstone un-deletes the row" fall out of the same per-field
-- LWW rule instead of needing special-case code.
-- HLC is the triple from §3, `(physical_time_ms, logical_counter,
-- device_id)`, stored as three columns rather than one packed string so
-- SQLite's row-value comparison (`(a, b, c) > (?, ?, ?)`, supported since
-- 3.15) can do the ordering directly in the pull query (§8) instead of
-- pulling every row into Python to compare.
CREATE TABLE IF NOT EXISTS field_versions (
    entity_type TEXT NOT NULL,
    entity_uid TEXT NOT NULL,
    field_name TEXT NOT NULL,
    hlc_physical INTEGER NOT NULL,
    hlc_logical INTEGER NOT NULL,
    hlc_device_id TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_uid, field_name)
);
CREATE INDEX IF NOT EXISTS idx_field_versions_hlc ON field_versions(hlc_physical, hlc_logical, hlc_device_id);

-- One row per device that has ever synced -- the pull cursor (§8) and the
-- "last sync time" line Data Health's own page already reserves a
-- placeholder for (src/data_health.py's health_summary `sync` key).
CREATE TABLE IF NOT EXISTS sync_devices (
    device_id TEXT PRIMARY KEY,
    last_pushed_physical INTEGER,
    last_pushed_logical INTEGER,
    last_pushed_device_id TEXT,
    last_pulled_physical INTEGER,
    last_pulled_logical INTEGER,
    last_pulled_device_id TEXT,
    last_seen_at TEXT
);

-- §5's applied-op_id idempotency ledger -- "an implementation detail for
-- the slice that builds it, not a modeling decision this doc needs to
-- fix" (§9). `result_json` is the exact response this op_id produced the
-- first time it was applied, replayed verbatim on a duplicate push
-- instead of re-applying (safe after a connection drop mid-push, since
-- the client can never be sure whether the server actually received the
-- last batch).
CREATE TABLE IF NOT EXISTS sync_applied_ops (
    op_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_uid TEXT NOT NULL,
    result_json TEXT NOT NULL,
    applied_at TEXT
);

-- 1.8 slice 2 ("Sync conflicts surface", plans/open-priority.md §
-- Offline-first editing & synchronization §§7b/c, 9): the two deliberate
-- exceptions to plain per-field LWW (§6/§7a, slice 1) -- a genuine
-- concurrent edit to the same event's start_at/end_at, or a synced batch
-- that gives one task two different project labels -- still pick a
-- winner automatically (so no device is ever blocked), but the losing
-- side is never silently discarded: it lands here instead, for the
-- person to restore or dismiss from Settings > Sync conflicts.
-- `losing_value`/`winning_hlc` are stored as plain text (a field value is
-- always one of the JSON-safe scalar types field_set ops already carry;
-- `winning_hlc` packed as "physical:logical:device_id" -- display-only,
-- never compared/sorted, so a single text column is simpler than three
-- more int/text columns nothing queries).
CREATE TABLE IF NOT EXISTS sync_conflicts (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_uid TEXT NOT NULL,
    field_name TEXT NOT NULL,
    losing_value TEXT,
    losing_hlc TEXT NOT NULL,
    winning_hlc TEXT NOT NULL,
    created_at TEXT,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_conflicts_unresolved ON sync_conflicts(resolved_at);

-- Quick Capture (plans/quick-capture.md) -- Notes are a fourth captured
-- entity type (`!n`), alongside the pre-existing tasks/events/contacts.
-- Deliberately minimal: a note is just free-text content plus labels
-- (via the same `object_labels` table every other type uses, object_type
-- 'note') -- no title field of its own (the content's first line serves
-- that purpose everywhere it's displayed, same as this app's habit-log
-- entries). Unrelated to `contacts.notes` (a free-text field on a
-- contact) -- same English word, different concept, no schema overlap.
CREATE TABLE IF NOT EXISTS notes (
    uid TEXT PRIMARY KEY,
    content TEXT NOT NULL DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);

-- Quick Capture's label resolution (plans/quick-capture.md § Labels and
-- Approximate Matching): "user corrections may also be retained as
-- aliases... future uses of #universitty can resolve directly to the
-- existing canonical label." One row per learned alias -- `alias` is the
-- exact (lowercased) misspelling/variant typed in a capture, mapping to
-- the real label's canonical name. Looked up before falling back to a
-- fuzzy (difflib) match on every capture (db.resolve_capture_label), and
-- written to once a fuzzy match is accepted -- see that function's own
-- docstring for why an accepted fuzzy match is treated as the "user
-- correction" the spec describes, there being no separate interactive
-- confirm-the-suggestion step in this v1.
CREATE TABLE IF NOT EXISTS label_aliases (
    alias TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    created_at TEXT
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


def migrate_legacy_contact_phone_email(conn: sqlite3.Connection) -> None:
    """Contacts field parity slice 2 of 6 (plans/open.md) -- the green-lit
    auto-migration: a contact whose legacy `phone`/`email` column already
    has a value gets that value copied into the new `contact_phones`/
    `contact_emails` table as a single row typed "Other" (the vocabulary's
    catch-all, since the old flat column never recorded which kind of
    number/address it was).

    Idempotent by construction, not by a separate "have I run" flag: a
    contact is only migrated if it has a legacy value AND zero existing
    child rows for that field, so running this again after the first row
    exists is a no-op for that contact -- covers both "called twice in a
    row" (schema setup runs on every `db.connect`) and "the contact
    already has real typed rows a user entered" (per this slice's own test
    list: a contact with real post-migration rows must be left alone even
    if the legacy column somehow still has a stale value, since nothing
    writes to the legacy column anymore -- see the contacts CREATE TABLE
    comment for why it's frozen, not kept live). A contact with no legacy
    value gets no rows at all -- no spurious "Other" entry from an empty
    field."""
    now = datetime.now(timezone.utc).isoformat()
    phone_rows = conn.execute(
        "SELECT uid, phone FROM contacts WHERE phone IS NOT NULL AND TRIM(phone) != '' "
        "AND uid NOT IN (SELECT DISTINCT contact_uid FROM contact_phones)"
    ).fetchall()
    for row in phone_rows:
        conn.execute(
            "INSERT INTO contact_phones (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), row["uid"], "Other", row["phone"], 0, now),
        )
    email_rows = conn.execute(
        "SELECT uid, email FROM contacts WHERE email IS NOT NULL AND TRIM(email) != '' "
        "AND uid NOT IN (SELECT DISTINCT contact_uid FROM contact_emails)"
    ).fetchall()
    for row in email_rows:
        conn.execute(
            "INSERT INTO contact_emails (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), row["uid"], "Other", row["email"], 0, now),
        )
    if phone_rows or email_rows:
        conn.commit()


def migrate_legacy_contact_address(conn: sqlite3.Connection) -> None:
    """Contacts field parity slice 5 of 6 -- the same green-lit auto-
    migration shape as migrate_legacy_contact_phone_email above: a contact
    whose legacy free-text `address` column already has a value gets that
    value copied into the new `contact_addresses` table as a single row
    typed "Other". Unlike phone/email (a single flat string that maps
    directly onto TEL/EMAIL's own single `value`), the legacy `address`
    column was never structured -- there's no reliable way to split an
    arbitrary free-text address into PO Box/Street/City/Region/Postal code/
    Country, so the whole legacy string is placed into `street` (the one
    ADR line meant for a general street-level address) and every other
    structured field is left blank; a user can split it into the real
    fields by hand from the edit form afterward if they want to.

    Same idempotence shape as migrate_legacy_contact_phone_email: only
    migrates a contact that has a legacy value AND zero existing
    contact_addresses rows, so a contact with real typed address rows
    already (or a second call after the first migrated it) is left alone."""
    now = datetime.now(timezone.utc).isoformat()
    address_rows = conn.execute(
        "SELECT uid, address FROM contacts WHERE address IS NOT NULL AND TRIM(address) != '' "
        "AND uid NOT IN (SELECT DISTINCT contact_uid FROM contact_addresses)"
    ).fetchall()
    for row in address_rows:
        conn.execute(
            "INSERT INTO contact_addresses "
            "(uid, contact_uid, type, po_box, extended, street, city, region, postal_code, country, position, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), row["uid"], "Other", "", "", row["address"], "", "", "", "", 0, now),
        )
    if address_rows:
        conn.commit()


def init_schema(conn: sqlite3.Connection) -> None:
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
    # Contacts field parity with Nextcloud Contacts (open.md), slice 1 of 6
    # (Title -> Phone/Email -> Website -> Birthday -> Address -> Social
    # network, per the build order recorded there). Title is the vCard
    # TITLE property (a person's job title, e.g. "Software Engineer") --
    # distinct from `org` (their organization's name, vCard ORG). Same
    # "column added after the table already existed on disk" situation as
    # photo_b64/photo_type immediately above.
    _ensure_column(conn, "contacts", "title", "TEXT")
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
    # Contacts field parity slice 4 of 6 -- Birthday. Single-value (unlike
    # Phone/Email/Website), so no child table -- just one more column, same
    # "added after the table already existed on disk" situation as title/
    # photo_b64/photo_type above. Stores the vCard BDAY value verbatim as
    # text: a full date "YYYY-MM-DD", or a year-less date "--MM-DD" (green-
    # lit 2026-08-15, AskUserQuestion) -- vobject treats a string BDAY value
    # as opaque text and serializes/reads it back unchanged either way
    # (confirmed directly against vobject before writing vcard_rows.py, not
    # assumed -- see that module's docstring), so there's no need to parse
    # into a `date` object anywhere in this app just to round-trip it.
    _ensure_column(conn, "contacts", "birthday", "TEXT")
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
    # Streak widget (2026-08-07) -- see the `tasks` CREATE TABLE comment
    # above for the full rationale.
    _ensure_column(conn, "tasks", "completed_at", "TEXT")
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
    # Phase 2 (label-space rework): dashboard_widgets.space_uid/project_uid
    # collapse to one `label_name` column (see the CREATE TABLE comment
    # above). Existing databases keep the old space_uid/project_uid columns
    # physically present (never force-dropped), but nothing in this module
    # reads/writes them anymore -- only `label_name`.
    _ensure_column(conn, "dashboard_widgets", "label_name", "TEXT")
    # Phase 2: label_config's behavior columns (generate_space/
    # dashboard_preset_json) -- see the CREATE TABLE comment above.
    # `enabled_modules_json`/`pinned` used to be added here too (Phase 4's
    # Sections gating, 2026-08-08's short-lived pin-to-sidebar step) --
    # both removed outright 2026-08-08, see the CREATE TABLE comment.
    # Nothing to add here for either anymore; an existing on-disk database
    # that already has those columns from before keeps them, unused and
    # harmless, same convention as every other removed column in this file.
    _ensure_column(conn, "label_config", "generate_space", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "label_config", "dashboard_preset_json", "TEXT")
    # 2026-08-09: label abbreviation (a max-5-char alias -- see the
    # CREATE TABLE comment). Added the same "never force-drop, just add"
    # convention as every other column; an existing on-disk database that
    # never wrote one simply defaults to NULL (= no abbreviation).
    _ensure_column(conn, "label_config", "abbreviation", "TEXT")
    # 1.1 (virtual & derived states) -- label behavior rules feeding the
    # Importance/Urgency derivation (see the label_config CREATE TABLE
    # comment above).
    _ensure_column(conn, "label_config", "importance", "INTEGER")
    _ensure_column(conn, "label_config", "urgency_threshold_days", "INTEGER")
    # 1.3 (Project-enabled label stack) -- see the label_config CREATE
    # TABLE comment above for the model.
    _ensure_column(conn, "label_config", "is_project", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "label_config", "start_date", "TEXT")
    _ensure_column(conn, "label_config", "end_date", "TEXT")
    _ensure_column(conn, "label_config", "archived_at", "TEXT")
    # CREATE INDEX statements that were moved out of SCHEMA_SQL
    # because they reference columns that may not exist yet in an
    # existing DB (the table predates the column).  `_ensure_column`
    # adds the column first; then the index is created safely.
    # 2026-08-07: the `grades`/`databases` index migrations that used to
    # live here are gone along with those tables (see the SCHEMA_SQL
    # comments above) -- an existing on-disk cache.sqlite that still
    # physically has those tables/indexes from before the removal is left
    # untouched, same "don't force-drop old data" convention as every
    # other removal in this file.
    # 2026-08-08: habit-labeled-task feature -- same "column added after
    # the table already existed on disk" situation as the others in this
    # function.
    _ensure_column(conn, "tasks", "target_per_day", "REAL NOT NULL DEFAULT 1")
    _ensure_column(conn, "task_completions", "value", "REAL NOT NULL DEFAULT 1")
    # 1.4 (Work allocations) -- see the event_task_relations CREATE TABLE
    # comment above for the model.
    _ensure_column(conn, "event_task_relations", "is_work_allocation", "INTEGER NOT NULL DEFAULT 0")
    # 2026-08-08: self-heal contacts already corrupted by the vcard_rows.py
    # bug fixed the same day -- a CardDAV-synced contact with an empty
    # ORG/TEL/EMAIL line got the literal string "None" stored instead of a
    # real NULL (str(None) on an unguarded vobject property with no
    # value), which then rendered as visible "None" text in the UI. The
    # parser itself no longer does this going forward; this just clears out
    # whatever's already on disk from before the fix. Cheap (three
    # single-column UPDATEs gated by an indexed-free equality check) and
    # runs every startup, but only ever touches rows that still have the
    # literal bad value, so it's a no-op after the first run clears them.
    conn.execute("UPDATE contacts SET org = NULL WHERE org = 'None'")
    conn.execute("UPDATE contacts SET phone = NULL WHERE phone = 'None'")
    conn.execute("UPDATE contacts SET email = NULL WHERE email = 'None'")
    # 2026-08-08: the same str(None) corruption the contacts fix above
    # clears also hit events (and tasks, for the same reason) -- a
    # CalDAV-synced event with an empty LOCATION/URL/RRULE line got the
    # literal string "None" stored instead of a real NULL, which then
    # rendered as visible "None" text in the event form's Location /
    # Meeting link / Recurrence fields and got re-saved on every edit.
    # The parser no longer does this going forward; this just clears out
    # whatever's already on disk from before the fix. Same cheap,
    # equality-gated UPDATE shape as the contacts rows above.
    conn.execute("UPDATE events SET location = NULL WHERE location = 'None'")
    conn.execute("UPDATE events SET meeting_url = NULL WHERE meeting_url = 'None'")
    conn.execute("UPDATE events SET recurrence = NULL WHERE recurrence = 'None'")
    conn.execute("UPDATE tasks SET recurrence = NULL WHERE recurrence = 'None'")
    _ensure_column(conn, "habits", "archived_at", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_habits_archived ON habits(archived_at)")
    _ensure_column(conn, "task_completions", "task_uid", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_completions_task ON task_completions(task_uid)")
    # 2026-08-07: fixes a real live bug (`sqlite3.IntegrityError: NOT NULL
    # constraint failed: events.href`) hit by an actual user on a database
    # that pre-dates the label-space rework -- see _relax_legacy_not_null's
    # own docstring for the full story. `calendar_path`/`list_path`/
    # `addressbook_path`'s *data* is deliberately preserved (not dropped),
    # since scripts/migrate_labels.py still needs to read it on a database
    # that hasn't been migrated yet -- this only removes the NOT NULL
    # constraint that was blocking new writes, nothing else.
    _relax_legacy_not_null(conn, "events", ("href", "etag", "calendar_path"))
    _relax_legacy_not_null(conn, "tasks", ("href", "etag", "calendar_path", "list_path"))
    _relax_legacy_not_null(conn, "contacts", ("href", "etag", "addressbook_path"))
    # 2026-08-18 -- one-time backfill of pre-existing rows into the sync
    # shadow store (see backfill_server_sync_writes). Runs last, after
    # every _ensure_column migration above, so the whitelist columns it
    # reads (deleted_at included) all exist.
    backfill_server_sync_writes(conn)
    # 2026-08-18 -- one-time backfill of the work-allocation sync flag
    # (see backfill_work_allocation_flags). Separate pass with its own
    # marker: on a real install sync_server_writes_backfilled may already
    # be set, but that covers entity columns only -- the flag lives in
    # event_task_relations, which that pass never reads.
    backfill_work_allocation_flags(conn)
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


def _attach_tags(conn: sqlite3.Connection, object_type: str, d: dict[str, Any]) -> dict[str, Any]:
    """Phase 2 (label-space rework): `tags` is no longer a stored JSON
    column on events/tasks/contacts/habits -- it's queried live from
    `object_labels` at read time and attached under the same `tags` key
    every template/ical_rows.py/vcard_rows.py caller already reads, so
    none of those callers needed to change. See
    features/architecture.md §2 item 2."""
    d["tags"] = list_labels_for_object(conn, object_type, d["uid"])
    return d


# --------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------- #

_EVENT_JSON_FIELDS = ("reminders_json", "exdates_json")


def upsert_event(
    conn: sqlite3.Connection, row: dict[str, Any], *, record_server_write: bool = True
) -> None:
    data = dict(row)
    if record_server_write:
        previous = _row_columns(conn, "events", str(data.get("uid")), _EVENT_SYNC_COLUMNS)
    data["reminders_json"] = json.dumps(data.get("reminders") or [])
    data["exdates_json"] = json.dumps(data.get("exdates") or [])
    # NOT NULL DEFAULT 0 columns -- must coerce None -> 0 explicitly here;
    # an INSERT that names the column with an explicit NULL value doesn't
    # fall back to the column's own DEFAULT the way omitting it would.
    data["exclude_saturday"] = 1 if data.get("exclude_saturday") else 0
    data["exclude_sunday"] = 1 if data.get("exclude_sunday") else 0
    tags = data.pop("tags", None)
    data.pop("reminders", None)
    data.pop("exdates", None)
    cols = [
        "uid", "title", "description",
        "start_at", "end_at", "all_day", "location", "meeting_url", "status",
        "recurrence", "exdates_json", "reminders_json",
        # 1.6 ("Generalized recurrence and the non-working-day policy") --
        # see the `events` CREATE TABLE comment. NULL/0 (not present in
        # `row`) is the correct default for every event that isn't a
        # recurring one specifying a policy, same "missing key -> column
        # default" convention every other upsert_* in this file already
        # relies on via data.get(c).
        "holiday_calendar", "exclude_saturday", "exclude_sunday",
        "created_at", "updated_at",
    ]
    values = [data.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid")
    conn.execute(
        f"INSERT INTO events ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        values,
    )
    if tags is not None:
        set_object_labels(conn, "event", data["uid"], tags)
    if record_server_write:
        record_server_sync_write(
            conn,
            "event",
            data["uid"],
            previous,
            _row_columns(conn, "events", data["uid"], _EVENT_SYNC_COLUMNS),
        )
    conn.commit()


def delete_event(
    conn: sqlite3.Connection, uid: str, *, record_server_write: bool = True
) -> None:
    if record_server_write:
        record_server_delete(conn, "event", uid)
    conn.execute("DELETE FROM events WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM object_labels WHERE object_type = 'event' AND object_id = ?", (uid,))
    # Relations are graph links, not ownership -- the task on the other end
    # stays, only this event's rows go (an event always owns the `event_uid`
    # side of an event_task_relations row).
    conn.execute("DELETE FROM event_task_relations WHERE event_uid = ?", (uid,))
    # 1.6 ("Manual recurrence exceptions") -- a per-occurrence override is
    # owned by its master event; deleting the master (the whole recurring
    # series) makes every override for it meaningless, same ownership
    # relationship as event_task_relations above.
    conn.execute("DELETE FROM event_occurrence_overrides WHERE master_uid = ?", (uid,))
    conn.commit()


def get_event(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM events WHERE uid = ?", (uid,)).fetchone()
    return _attach_tags(conn, "event", _row_to_dict(row, _EVENT_JSON_FIELDS)) if row else None


def list_events(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    """Real bug fix (found 2026-08-14 while building 1.6's manual
    recurrence exceptions, via a router test that moved an occurrence into
    a later week and it silently never rendered): a *recurring* row's own
    literal start_at/end_at only anchor its first occurrence -- the date
    range filter below used to exclude the row entirely once `start`/`end`
    fell far enough past that literal end_at, even though its RRULE would
    still generate real occurrences inside the window. Nothing caught this
    before because no existing test seeded a recurring event and then
    queried a week more than ~one occurrence-length past its own creation
    date. Fix: a recurring row (recurrence IS NOT NULL) is always a
    candidate regardless of its own literal bounds -- `recurrence_expand.
    expand_events` (which every caller of this function already runs
    recurring rows through) is what actually decides whether it produces
    any occurrence in the window, via the real RRULE/UNTIL/COUNT."""
    query = "SELECT * FROM events"
    params: list[str] = []
    bounds_clauses = []
    if start:
        bounds_clauses.append("(end_at IS NULL OR end_at >= ?)")
        params.append(start)
    if end:
        bounds_clauses.append("start_at <= ?")
        params.append(end)
    if bounds_clauses:
        query += " WHERE (recurrence IS NOT NULL OR (" + " AND ".join(bounds_clauses) + "))"
    query += " ORDER BY start_at ASC"
    rows = conn.execute(query, params).fetchall()
    return [_attach_tags(conn, "event", _row_to_dict(r, _EVENT_JSON_FIELDS)) for r in rows]


# --------------------------------------------------------------------- #
# Manual recurrence exceptions (1.6, "Manual recurrence exceptions") --
# see event_occurrence_overrides' own CREATE TABLE comment for the model.
# --------------------------------------------------------------------- #


def _occurrence_override_uid(master_uid: str, occurrence_date: str) -> str:
    """Deterministic key for the one override a given (master, original
    occurrence) pair can have -- lets upsert_event_occurrence_override use
    the same ON CONFLICT(uid) idiom every other upsert_* in this file uses,
    instead of a separate find-then-update step."""
    return f"{master_uid}::{occurrence_date}"


def upsert_event_occurrence_override(conn: sqlite3.Connection, row: dict[str, Any]) -> str:
    """Cancels or moves/modifies one occurrence of a recurring event
    without touching its recurrence rule. `row`: {master_uid,
    occurrence_date, cancelled, start_at, end_at, title, location,
    created_at, updated_at} -- cancelled=True and a moved start_at are
    mutually exclusive in practice (routers/calendar.py only ever sets
    one), but nothing here enforces that; recurrence_expand.py only reads
    start_at when cancelled is falsy. Returns the override's own uid."""
    uid = _occurrence_override_uid(row["master_uid"], row["occurrence_date"])
    conn.execute(
        "INSERT INTO event_occurrence_overrides "
        "(uid, master_uid, occurrence_date, cancelled, start_at, end_at, title, location, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET cancelled=excluded.cancelled, start_at=excluded.start_at, "
        "end_at=excluded.end_at, title=excluded.title, location=excluded.location, updated_at=excluded.updated_at",
        (
            uid, row["master_uid"], row["occurrence_date"],
            1 if row.get("cancelled") else 0,
            row.get("start_at"), row.get("end_at"), row.get("title"), row.get("location"),
            row.get("created_at"), row.get("updated_at"),
        ),
    )
    conn.commit()
    return uid


def delete_event_occurrence_override(conn: sqlite3.Connection, master_uid: str, occurrence_date: str) -> None:
    """Restores one occurrence back to whatever the recurrence rule alone
    would generate -- "undo" for a cancel or a move."""
    conn.execute(
        "DELETE FROM event_occurrence_overrides WHERE uid = ?",
        (_occurrence_override_uid(master_uid, occurrence_date),),
    )
    conn.commit()


def list_event_occurrence_overrides(conn: sqlite3.Connection, master_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM event_occurrence_overrides WHERE master_uid = ? ORDER BY occurrence_date",
        (master_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_event_occurrence_overrides_by_master(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """{master_uid: [override row, ...]} -- the shape
    `recurrence_expand.expand_events`'s `overrides_by_master` parameter
    expects. Built once per request, same "routers compute, pure logic
    just reads what it's given" layering `list_holidays_by_calendar`
    already follows."""
    by_master: dict[str, list[dict[str, Any]]] = {}
    rows = conn.execute("SELECT * FROM event_occurrence_overrides ORDER BY occurrence_date").fetchall()
    for row in rows:
        by_master.setdefault(row["master_uid"], []).append(dict(row))
    return by_master


def all_event_uids(conn: sqlite3.Connection) -> set[str]:
    return {r["uid"] for r in conn.execute("SELECT uid FROM events").fetchall()}


# --------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------- #

_TASK_JSON_FIELDS: tuple[str, ...] = ()


_TASK_DONE_STATUSES = ("done", "archived")


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

    def __init__(self, project_names: list[str]):
        self.project_names = list(project_names)
        names = ", ".join(self.project_names)
        super().__init__(f"A task may belong to only one project label at a time (got: {names}).")


def _reject_multiple_project_labels(conn: sqlite3.Connection, tags: list[str]) -> None:
    project_names = {cfg["name"] for cfg in list_project_labels(conn)}
    selected = sorted({t for t in tags if t in project_names}, key=str.lower)
    if len(selected) > 1:
        raise MultipleProjectLabelsError(selected)


def upsert_task(
    conn: sqlite3.Connection, row: dict[str, Any], *, record_server_write: bool = True
) -> None:
    data = dict(row)
    if record_server_write:
        previous = _row_columns(conn, "tasks", str(data.get("uid")), _TASK_SYNC_COLUMNS)
    tags = data.pop("tags", None)
    # Validated before anything is written (not just before set_object_labels
    # further down) so a rejected label set never leaves a partial write --
    # the task row's other columns and its labels are kept consistent by
    # never touching either on a rejected call.
    if tags is not None:
        _reject_multiple_project_labels(conn, tags)
    # completed_at (2026-08-07, see the `tasks` CREATE TABLE comment) is
    # always auto-managed here, deliberately ignoring whatever value the
    # caller's dict happens to carry -- every existing caller builds its
    # row from `dict(existing)` first (see the timeline_lane comment
    # below), which means a passed-in `completed_at` is almost always
    # just "whatever it already was," not a deliberate new value, so it
    # can't be used the way a real "did the caller explicitly ask for
    # this" check would need. The one path that genuinely needs to set a
    # specific historical `completed_at` (a JSON backup restore) does so
    # with its own explicit UPDATE after calling this function, not by
    # fighting this auto-detection -- see routers/export.py's
    # `restore_backup_payload`.
    existing_status = conn.execute("SELECT status FROM tasks WHERE uid = ?", (data.get("uid"),)).fetchone()
    was_done = bool(existing_status and existing_status["status"] in _TASK_DONE_STATUSES)
    now_done = data.get("status") in _TASK_DONE_STATUSES
    if now_done and not was_done:
        data["completed_at"] = datetime.now(timezone.utc).isoformat()
    elif not now_done:
        data["completed_at"] = None
    else:
        # Still done, was already done (e.g. editing title while status
        # stays "done") -- leave the existing completed_at exactly alone
        # rather than re-stamping "now" on every unrelated edit.
        prev = conn.execute("SELECT completed_at FROM tasks WHERE uid = ?", (data.get("uid"),)).fetchone()
        data["completed_at"] = prev["completed_at"] if prev else None
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
        "uid", "title", "description",
        "start_at", "due_at", "status", "progress",
        "recurrence", "completed_at", "created_at", "updated_at",
        "target_per_day",
    ]
    # parent_uid is deliberately absent from this list (1.2, task-model
    # decision): subtasks are removed, tasks are flat. The column stays
    # physically on disk for pre-1.2 databases but is never written or read
    # by app code -- same convention as the old `priority` column above.
    # target_per_day (2026-08-08, habit-labeled tasks) falls back to 1 --
    # same "NOT NULL DEFAULT 1" the column itself has -- for any caller
    # that builds its row without ever mentioning it (most: complete_task/
    # update_field/timeline reposition all pass `dict(existing)` through
    # unchanged, which already carries a real value once one's been set;
    # this default only matters for a genuinely fresh row).
    values = [(data.get(c) if c != "target_per_day" else (data.get(c) or 1)) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid")
    conn.execute(
        f"INSERT INTO tasks ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        values,
    )
    if tags is not None:
        set_object_labels(conn, "task", data["uid"], tags)
    # 1.4 (Work allocations, § Task & calendar semantics): "editing the task
    # updates the representation of its associated work allocations where
    # appropriate" -- keep every linked work-allocation event's title equal
    # to the task's current title. Cheap no-op when the task has none (the
    # UPDATE's subquery matches zero rows) and idempotent when the title
    # didn't actually change, so this runs unconditionally rather than
    # diffing old vs. new title first.
    if data.get("title") is not None:
        sync_work_allocation_titles(conn, data["uid"], data["title"])
    if record_server_write:
        record_server_sync_write(
            conn,
            "task",
            data["uid"],
            previous,
            _row_columns(conn, "tasks", data["uid"], _TASK_SYNC_COLUMNS),
        )
    conn.commit()


def delete_task(
    conn: sqlite3.Connection, uid: str, *, record_server_write: bool = True
) -> None:
    if record_server_write:
        record_server_delete(conn, "task", uid)
    conn.execute("DELETE FROM tasks WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM object_labels WHERE object_type = 'task' AND object_id = ?", (uid,))
    # Mirror of delete_event's relation cleanup -- the linked event survives,
    # only this task's rows go.
    conn.execute("DELETE FROM event_task_relations WHERE task_uid = ?", (uid,))
    conn.commit()


def delete_completed_tasks(conn: sqlite3.Connection) -> int:
    """Settings' "Purge completed" (2026-08-07) -- every task with
    status done/archived, deleted the same way a single delete_task
    would (object_labels cascade included), just looped. Doesn't touch
    task_checklist_items/task_completions for those tasks -- same gap
    delete_task already has for a single task, not something this purge
    action should silently start cleaning up on its own. Returns the
    count deleted, so the caller can report what actually happened."""
    rows = conn.execute("SELECT uid FROM tasks WHERE status IN ('done', 'archived')").fetchall()
    for row in rows:
        delete_task(conn, row["uid"])
    return len(rows)


def delete_old_completed_tasks(conn: sqlite3.Connection, days: int) -> int:
    """"Auto-archive completed tasks" (Settings > Advanced, 2026-08-08) --
    the automatic, age-based sibling of delete_completed_tasks above:
    deletes every done/archived task whose `completed_at` is older than
    `days`, instead of every completed task regardless of age. Same
    per-task delete_task() cascade (object_labels included, task_checklist
    _items/task_completions not -- identical gap, see
    delete_completed_tasks' own docstring).

    A task can be done/archived with `completed_at` NULL -- e.g. one
    whose status was set directly in the database, or synced in from
    somewhere that predates this column -- deliberately excluded here
    rather than treated as "infinitely old" and swept up immediately;
    an unknown completion date is a reason to leave a task alone, not
    delete it. `days <= 0` is a no-op (routers/tasks.py's lazy caller
    only invokes this when the Settings > Advanced preference is a
    positive number -- "Never" stores 0/empty and never reaches this at
    all -- but this function stays a safe no-op either way, not relying
    on the caller alone to enforce that)."""
    if days <= 0:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT uid FROM tasks WHERE status IN ('done', 'archived') AND completed_at IS NOT NULL AND completed_at < ?",
        (cutoff,),
    ).fetchall()
    for row in rows:
        delete_task(conn, row["uid"])
    return len(rows)


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
        # 1.6: schedule_classes dropped from SCHEMA_SQL (see its removal
        # note above) -- a brand-new database never has this table, so it's
        # no longer in this list. schedule_holidays stays -- it's the
        # generic named-holiday-calendar mechanism, unrelated to the
        # Schedule module itself (removed 2026-08-15, see plans/STATE.md);
        # schedule_settings is gone along with that module.
        "schedule_holidays", "habits",
        "habit_entries", "task_completions", "dashboard_widgets",
        "time_blocks",
        "published_lists", "app_meta",
    ]
    for table in tables:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def get_task(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM tasks WHERE uid = ?", (uid,)).fetchone()
    return _attach_tags(conn, "task", _row_to_dict(row, _TASK_JSON_FIELDS)) if row else None


def list_tasks(
    conn: sqlite3.Connection,
    status: str | None = None,
    q: str | None = None,
    include_habit_tasks: bool = False,
) -> list[dict[str, Any]]:
    """`include_habit_tasks` defaults False (2026-08-08, "add habits page
    as a view on tasks" -- "not appear in any other view or widget unless
    it's habit related") -- a task carrying the configured habit label
    (task_habit_settings.habit_label) is meant to live *only* on Tasks >
    Habits, not the normal Table/Timeline/Board/Calendar/dashboard-widget
    views this function backs almost everywhere in the app. Every one of
    those call sites gets the exclusion for free without needing its own
    change; the two callers that genuinely need every task regardless
    (routers/tasks.py's own habits_view, and export.py's full backup) pass
    True explicitly."""
    query = "SELECT * FROM tasks"
    params: list[str] = []
    clauses = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if q:
        clauses.append("title LIKE ?")
        params.append(f"%{q}%")
    if not include_habit_tasks:
        habit_label = get_task_habit_settings(conn)["habit_label"]
        excluded_uids = list_object_ids_for_label(conn, "task", habit_label)
        if excluded_uids:
            placeholders = ", ".join("?" for _ in excluded_uids)
            clauses.append(f"uid NOT IN ({placeholders})")
            params.extend(excluded_uids)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    # Importance/Urgency no longer sort here -- both are purely computed
    # (src/derived_state.py, label rules + temporal state), not raw
    # columns SQL can order by; a caller that needs importance/urgency
    # ordering does it in Python via derived_state's effective values
    # (see routers/tasks.py's _SORT_KEYS).
    query += " ORDER BY (due_at IS NULL), due_at ASC"
    rows = conn.execute(query, params).fetchall()
    return [_attach_tags(conn, "task", _row_to_dict(r, _TASK_JSON_FIELDS)) for r in rows]


def list_habit_tasks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The mirror image of list_tasks' default exclusion -- every task
    carrying the configured habit label, for Tasks > Habits itself."""
    habit_label = get_task_habit_settings(conn)["habit_label"]
    uids = list_object_ids_for_label(conn, "task", habit_label)
    if not uids:
        return []
    placeholders = ", ".join("?" for _ in uids)
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE uid IN ({placeholders}) ORDER BY title COLLATE NOCASE", uids
    ).fetchall()
    return [_attach_tags(conn, "task", _row_to_dict(r, _TASK_JSON_FIELDS)) for r in rows]


def all_task_uids(conn: sqlite3.Connection) -> set[str]:
    return {r["uid"] for r in conn.execute("SELECT uid FROM tasks").fetchall()}


def set_task_timeline_lane(conn: sqlite3.Connection, uid: str, lane: int | None) -> None:
    """Explicit setter for a task's manual Timeline row placement -- see
    the `tasks.timeline_lane` column comment in init_schema. Pass None to
    clear it (falls back to auto-packing, timeline_layout.py's
    assign_swimlanes). Not folded into upsert_task's own column list, same
    "a dedicated setter, not a field an ordinary save can clobber"
    convention as every other setter in this file (see upsert_task's own
    comment on why timeline_lane is deliberately excluded there)."""
    conn.execute("UPDATE tasks SET timeline_lane = ? WHERE uid = ?", (lane, uid))
    conn.commit()


# --------------------------------------------------------------------- #
# Event<->task relations -- 2026-08-09 ("Relations", associative graph
# links between events and tasks, the webapp's answer to desktop's old
# links/backlinks panel; see the event_task_relations CREATE TABLE comment
# above). One relation always connects exactly one event to exactly one
# task; `related_*` return full rows of the *other* type, and
# `list_*_sharing_labels` return the candidate pool an add-row's "link an
# existing object" picker is allowed to offer (an event and a task may only
# be related when they share at least one label).
# --------------------------------------------------------------------- #


def add_event_task_relation(
    conn: sqlite3.Connection, event_uid: str, task_uid: str, is_work_allocation: int = 0
) -> None:
    """Idempotent link insert (composite PK means a duplicate is a no-op) --
    the caller is responsible for the "must share a label" rule (the UI's
    picker enforces it, the routers re-check it defensively); the DB itself
    doesn't -- same "constraint lives in the app layer" convention as every
    other table in this file. `is_work_allocation` defaults to 0 (an
    ordinary Relations-card link, this function's original purpose) --
    routers/export.py's restore path is the one caller that passes a
    backed-up row's real value through, so a work allocation round-trips
    through a JSON backup as one instead of silently downgrading to a plain
    relation."""
    conn.execute(
        "INSERT OR IGNORE INTO event_task_relations (event_uid, task_uid, created_at, is_work_allocation) "
        "VALUES (?, ?, ?, ?)",
        (event_uid, task_uid, datetime.now(timezone.utc).isoformat(), int(is_work_allocation)),
    )
    conn.commit()


def remove_event_task_relation(conn: sqlite3.Connection, event_uid: str, task_uid: str) -> None:
    conn.execute(
        "DELETE FROM event_task_relations WHERE event_uid = ? AND task_uid = ?",
        (event_uid, task_uid),
    )
    conn.commit()


def list_event_task_relations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM event_task_relations ORDER BY created_at").fetchall()]


def related_tasks_for_event(conn: sqlite3.Connection, event_uid: str) -> list[dict[str, Any]]:
    """Every task currently linked to `event_uid`, ordered the same way
    list_tasks orders (undated last, then due date -- importance/urgency
    are computed, not SQL-orderable columns, see list_tasks' own comment)
    so a Relations card's list reads like every other task list in the
    app."""
    rows = conn.execute(
        "SELECT tasks.* FROM tasks JOIN event_task_relations r ON r.task_uid = tasks.uid "
        "WHERE r.event_uid = ? ORDER BY (tasks.due_at IS NULL), tasks.due_at ASC",
        (event_uid,),
    ).fetchall()
    return [_attach_tags(conn, "task", _row_to_dict(r, _TASK_JSON_FIELDS)) for r in rows]


def related_events_for_task(conn: sqlite3.Connection, task_uid: str) -> list[dict[str, Any]]:
    """Every event currently linked to `task_uid`, ordered by start time."""
    rows = conn.execute(
        "SELECT events.* FROM events JOIN event_task_relations r ON r.event_uid = events.uid "
        "WHERE r.task_uid = ? ORDER BY events.start_at ASC",
        (task_uid,),
    ).fetchall()
    return [_attach_tags(conn, "event", _row_to_dict(r, _EVENT_JSON_FIELDS)) for r in rows]


# --------------------------------------------------------------------- #
# Work allocations (1.4, plans/open-priority.md § Work allocations, §
# Task & calendar semantics)
#
# "A work allocation... is a calendar Event linked to that task, not a
# different kind of calendar object." Concretely: an ordinary `events` row,
# plus an `event_task_relations` row with `is_work_allocation=1` (see that
# table's CREATE TABLE comment). The functions below are the only place
# that flag is set or read -- everything else in this file treats a
# work-allocation row exactly like the events/relations it already is.
# --------------------------------------------------------------------- #


def create_work_allocation(
    conn: sqlite3.Connection, task_uid: str, start_at: str | None = None, end_at: str | None = None
) -> str:
    """Schedule a block of work on `task_uid`: a plain event titled after
    the task (kept in sync by upsert_task, see below) and inheriting the
    task's labels, linked back with `is_work_allocation=1`. Returns the new
    event's uid. Placing a task into "as many [calendar periods] as
    necessary keeps every allocation associated with the same task" -- so
    this is called once per block; calling it again for the same task just
    creates another independent event/relation pair, exactly as the spec
    describes for a task split across multiple sessions.

    Either both of `start_at`/`end_at` or neither may be given. A
    start/end pair schedules the block (renders on calendars, counts toward
    `db.task_work_hours`'s `scheduled`). Omitting both creates an
    UNSCHEDULED session placeholder -- no date yet, so the task still
    appears on the planning grids' "Unscheduled work" panel and the session
    is placed onto a real slot by dragging it there (see
    `set_work_allocation_times`/`first_undated_work_allocation_for_task`);
    this is what the task modal's Work sessions "+" button creates."""
    import uuid

    task = get_task(conn, task_uid)
    if task is None:
        raise ValueError(f"no such task: {task_uid}")
    now = datetime.now(timezone.utc).isoformat()
    event_uid = str(uuid.uuid4())
    upsert_event(
        conn,
        {
            "uid": event_uid,
            "title": task["title"],
            "description": "",
            "start_at": start_at,
            "end_at": end_at,
            "all_day": False,
            "status": "active",
            "tags": task.get("tags") or [],
            "created_at": now,
            "updated_at": now,
        },
    )
    conn.execute(
        "INSERT OR IGNORE INTO event_task_relations (event_uid, task_uid, created_at, is_work_allocation) "
        "VALUES (?, ?, ?, 1)",
        (event_uid, task_uid, now),
    )
    # 2026-08-18 -- offline "Upcoming" view: a device's pull only ever
    # learns the work-allocation flag through field_versions, and the flag
    # isn't an `events` column record_server_sync_write's diff can catch,
    # so the sync-flag entry is recorded explicitly (see
    # record_work_allocation_flag).
    record_work_allocation_flag(conn, event_uid)
    conn.commit()
    return event_uid


def list_work_allocations_for_task(conn: sqlite3.Connection, task_uid: str) -> list[dict[str, Any]]:
    """Every scheduled work block for `task_uid` -- the work-allocation-only
    counterpart to related_events_for_task above (which returns ordinary
    Relations-card links too). Ordered by creation time (not start time), so
    the Work sessions card's "Session 1/2/3" numbering stays the stable
    order sessions were added in and an undated session (start_at NULL, a
    "+"-added placeholder) keeps its position once it's placed later."""
    rows = conn.execute(
        "SELECT events.* FROM events JOIN event_task_relations r ON r.event_uid = events.uid "
        "WHERE r.task_uid = ? AND r.is_work_allocation = 1 ORDER BY events.created_at ASC, events.uid ASC",
        (task_uid,),
    ).fetchall()
    return [_attach_tags(conn, "event", _row_to_dict(r, _EVENT_JSON_FIELDS)) for r in rows]


def work_allocation_task_uid(conn: sqlite3.Connection, event_uid: str) -> str | None:
    """If `event_uid` is a work-allocation event, its task's uid; otherwise
    None. Used to redirect a title edit on the event back onto the task --
    see routers/calendar.py's update_event."""
    row = conn.execute(
        "SELECT task_uid FROM event_task_relations WHERE event_uid = ? AND is_work_allocation = 1",
        (event_uid,),
    ).fetchone()
    return row["task_uid"] if row else None


def work_allocation_event_uids(conn: sqlite3.Connection) -> set[str]:
    """Every event uid that is a work-allocation block, in one query -- the
    bulk counterpart to work_allocation_task_uid, for a page (e.g. Month)
    that needs to exclude every work-allocation event from a list it
    already fetched via db.list_events, without an N+1 per-event lookup."""
    rows = conn.execute("SELECT event_uid FROM event_task_relations WHERE is_work_allocation = 1").fetchall()
    return {row["event_uid"] for row in rows}


def delete_work_allocation(conn: sqlite3.Connection, event_uid: str) -> None:
    """"Deleting a work allocation removes only that scheduled block -- not
    the task. The user is removing planned working time, not the underlying
    work." delete_event already only ever cascades the event's own rows
    (object_labels, event_task_relations WHERE event_uid=...), never
    touches `tasks` -- so this is delete_event under a name that states the
    1.4 semantics explicitly at the call site."""
    delete_event(conn, event_uid)


def first_undated_work_allocation_for_task(conn: sqlite3.Connection, task_uid: str) -> dict[str, Any] | None:
    """The task's oldest work-allocation session that has no start/end yet
    (a "+"-added session placeholder awaiting placement on a planning grid),
    or None. `list_work_allocations_for_task` is creation-ordered, so the
    first undated one is the session a grid drop should place next."""
    for wa in list_work_allocations_for_task(conn, task_uid):
        if not wa.get("start_at"):
            return wa
    return None


def set_work_allocation_times(conn: sqlite3.Connection, event_uid: str, start_at: str, end_at: str) -> bool:
    """Give an existing work-allocation session its scheduled start/end --
    the "place this session" half of a session created undated from the task
    modal's Work sessions card (create_work_allocation with no dates). Only
    a real work allocation may be moved (work_allocation_task_uid guard, the
    same idiom the routers' move_allocation endpoints use); returns False if
    it isn't one or the range is invalid, otherwise updates the event and
    returns True."""
    if not start_at or not end_at or end_at <= start_at:
        return False
    if not work_allocation_task_uid(conn, event_uid):
        return False
    existing = get_event(conn, event_uid)
    if existing is None:
        return False
    row = dict(existing)
    row["start_at"] = start_at
    row["end_at"] = end_at
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    upsert_event(conn, row)
    return True


def unschedule_work_allocation(conn: sqlite3.Connection, event_uid: str) -> bool:
    """The inverse of `set_work_allocation_times`: clear an existing work-
    allocation session's start/end back to undated instead of deleting the
    session outright. This is what "unschedule" means for the planning
    grids' block interactions (drag a block back onto the "Unscheduled
    work" panel, or its own delete button) -- the block comes off the
    calendar, but the session itself is still there, now back on the panel
    as an unplaced session, exactly like a "+"-added placeholder. 2026-08-14:
    this used to fully `delete_work_allocation` the block, which silently
    shrank the task's total session count by one every time a block was
    unscheduled -- surprising when the point of unscheduling is "I'll place
    this later," not "I don't need this session anymore" (that's what the
    panel's own "−" stepper, or the task's Work sessions card, are for).
    Only a real work allocation may be unscheduled (`work_allocation_
    task_uid` guard, same idiom `set_work_allocation_times` uses); returns
    False if it isn't one or the event doesn't exist."""
    if not work_allocation_task_uid(conn, event_uid):
        return False
    existing = get_event(conn, event_uid)
    if existing is None:
        return False
    row = dict(existing)
    row["start_at"] = None
    row["end_at"] = None
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    upsert_event(conn, row)
    return True


def _hours_between(start_at: str | None, end_at: str | None) -> float:
    if not start_at or not end_at:
        return 0.0
    try:
        start = datetime.fromisoformat(start_at)
        end = datetime.fromisoformat(end_at)
    except ValueError:
        return 0.0
    return max((end - start).total_seconds() / 3600.0, 0.0)


def work_allocation_panel_info(conn: sqlite3.Connection, task_uid: str) -> dict[str, Any]:
    """Summary the planning grids' "Unscheduled work" panel needs for one
    task (week_view/timetable_view/project_calendar build the same item
    shape): session count plus the scheduled/total hours shown next to the
    title. `scheduled_hours` is the sum of dated session durations (the
    same number db.task_work_hours reports as `scheduled`); `total_hours`
    adds one default hour per undated session -- an undated session has no
    duration yet, so its planned contribution counts as the default 1-hour
    block it becomes when placed on a grid (project_calendar.js's
    DEFAULT_BLOCK_MINUTES), which makes the x/y read "hours on the calendar
    out of hours planned". `undated_count` is the number of sessions still
    awaiting placement -- the panel's "still unscheduled" rule
    (`count > 0 and undated_count == 0` drops a task off the list) needs
    it, and it's what separates the panel summary from task_work_hours."""
    allocations = list_work_allocations_for_task(conn, task_uid)
    scheduled = sum(_hours_between(a.get("start_at"), a.get("end_at")) for a in allocations)
    undated = sum(1 for a in allocations if not a.get("start_at"))
    return {
        "count": len(allocations),
        "scheduled_hours": scheduled,
        "total_hours": scheduled + undated,
        "undated_count": undated,
    }


def habit_work_sessions_status(
    conn: sqlite3.Connection, task_uid: str, recurrence: str | None, period_start: str, period_end: str
) -> dict[str, Any]:
    """Unscheduled-work visibility for a habit-tracked recurring task,
    scoped to `period_start`/`period_end` (ISO dates, inclusive) --
    routers/calendar.py's week_view picks the period per the habit's own
    cadence (the displayed week for daily/weekly, that week's calendar
    month for monthly/anything else) and passes it in here rather than
    this function guessing at "which week" from the task alone.

    Unlike a plain task's `work_allocation_panel_info` (which only ever
    asks "does every session have a date, at all, ever"), a habit needs a
    specific NUMBER of dated sessions before it's "handled" for the
    period: one per day for a daily habit (`required=7` for a 7-day
    period), just one for weekly/monthly/anything else -- 2026-08-29
    direct feedback ("a daily habit remains persistent and disappears
    from the unscheduled work only when the current week has all been
    taken care of; for a weekly task it's enough to add only one, and
    monthly the same"). `needed` (dated-in-period sessions still short of
    `required`, after crediting any undated placeholder sessions already
    added and awaiting placement) is what the caller checks for inclusion
    -- 0 means this period is fully covered and the habit drops off the
    panel; every value in between is the picture, ready-computed rather
    than callers reaching into `list_work_allocations_for_task`
    themselves."""
    allocations = list_work_allocations_for_task(conn, task_uid)
    dated_in_period = sum(
        1 for a in allocations if a.get("start_at") and period_start <= a["start_at"][:10] <= period_end
    )
    undated = sum(1 for a in allocations if not a.get("start_at"))
    required = 7 if habit_heatmap.recurrence_frequency(recurrence) == "daily" else 1
    return {
        "dated_in_period": dated_in_period,
        "undated_count": undated,
        "required": required,
        "needed": max(0, required - dated_in_period - undated),
    }


def remove_latest_work_allocation(conn: sqlite3.Connection, task_uid: str) -> str | None:
    """Remove the task's most recently added UNDATED work session -- the
    last still-undated one in `list_work_allocations_for_task`'s creation
    order, the "Unscheduled work" panel "−" button's undo of its own "+".
    Deliberately ignores dated (already-scheduled) sessions even if one of
    those is more recently created -- the panel's count is now "sessions
    still needing placement" (`work_allocation_panel_info`'s
    `undated_count`), so "−" must only ever touch that same pool; it must
    never silently delete an already-scheduled calendar block just because
    it happened to be the most recent thing created. Returns the removed
    event's uid, or None if the task has no undated sessions to remove
    (also None for a task that doesn't exist -- get_task guard, same as
    create_work_allocation). The task itself, and every dated session, are
    never touched."""
    if get_task(conn, task_uid) is None:
        return None
    undated = [wa for wa in list_work_allocations_for_task(conn, task_uid) if not wa.get("start_at")]
    if not undated:
        return None
    uid = undated[-1]["uid"]
    delete_event(conn, uid)
    return uid


def task_work_hours(conn: sqlite3.Connection, task_uid: str) -> dict[str, float]:
    """"The estimated work of a task is calculated from its actual calendar
    allocations... Total planned work is therefore the sum of the task's
    work blocks" -- `scheduled` is that sum; `completed` is the portion
    already in the past ("the application retains enough information to
    distinguish scheduled work from completed work"). A work-allocation
    event has no independent "done" flag -- whether the work happened is
    read off the clock, same as any other calendar event."""
    now = datetime.now(timezone.utc).isoformat()
    allocations = list_work_allocations_for_task(conn, task_uid)
    scheduled = sum(_hours_between(a.get("start_at"), a.get("end_at")) for a in allocations)
    completed = sum(
        _hours_between(a.get("start_at"), a.get("end_at"))
        for a in allocations
        if a.get("end_at") and a["end_at"] <= now
    )
    return {"scheduled": scheduled, "completed": completed, "remaining": max(scheduled - completed, 0.0)}


def task_work_hours_bulk(conn: sqlite3.Connection, task_uids: list[str]) -> dict[str, dict[str, float]]:
    """Batch counterpart to `task_work_hours` above -- one query for every
    task in `task_uids` instead of one `list_work_allocations_for_task`
    query per task. Added for the 1.5 "deadline vs. work allocation"
    surfacing slice (`plans/open-priority.md` § Task model): the global
    Tasks table and the project detail Tasks view both render every visible
    row's scheduled/completed hours, and calling the per-task function in a
    template loop would be a straightforward N+1 (one row -> one query) on
    any list beyond a handful of tasks. There was no existing "aggregate X
    across many tasks in one query" precedent in this module to follow
    (`_project_card`'s `progress` counts an already-fetched Python list, not
    a SQL aggregate) -- this is the first one, and `task_work_hours` itself
    is left untouched (same return shape, same semantics) so single-task
    call sites (task detail/edit modals) are unaffected.

    Returns a dict keyed by task_uid, every value the same
    `{"scheduled", "completed", "remaining"}` shape `task_work_hours`
    returns -- including a zero-filled entry for a task with no allocations
    at all, so callers never need an `if task_uid in result` branch."""
    result = {uid: {"scheduled": 0.0, "completed": 0.0, "remaining": 0.0} for uid in task_uids}
    if not task_uids:
        return result
    now = datetime.now(timezone.utc).isoformat()
    placeholders = ",".join("?" for _ in task_uids)
    rows = conn.execute(
        f"SELECT r.task_uid AS task_uid, events.start_at AS start_at, events.end_at AS end_at "
        f"FROM events JOIN event_task_relations r ON r.event_uid = events.uid "
        f"WHERE r.is_work_allocation = 1 AND r.task_uid IN ({placeholders})",
        tuple(task_uids),
    ).fetchall()
    for row in rows:
        uid = row["task_uid"]
        hours = _hours_between(row["start_at"], row["end_at"])
        result[uid]["scheduled"] += hours
        if row["end_at"] and row["end_at"] <= now:
            result[uid]["completed"] += hours
    for uid, hours in result.items():
        hours["remaining"] = max(hours["scheduled"] - hours["completed"], 0.0)
    return result


def sync_work_allocation_titles(conn: sqlite3.Connection, task_uid: str, title: str) -> None:
    """"Editing the task updates the representation of its associated work
    allocations where appropriate" -- called from upsert_task whenever a
    task's title changes, so every linked work-allocation event's title
    stays the task's title rather than drifting into an independent name.
    Ordinary Relations-linked events (is_work_allocation=0) are untouched --
    only a work allocation's title is owned by its task."""
    conn.execute(
        "UPDATE events SET title = ?, updated_at = ? WHERE uid IN ("
        "SELECT event_uid FROM event_task_relations WHERE task_uid = ? AND is_work_allocation = 1)",
        (title, datetime.now(timezone.utc).isoformat(), task_uid),
    )


def list_tasks_sharing_labels(conn: sqlite3.Connection, label_names: list[str]) -> list[dict[str, Any]]:
    """Every non-habit task carrying at least one of `label_names` -- the
    "link an existing task" pool for an event's Relations card. Mirrors
    list_tasks' default habit-task exclusion (a habit task is hidden from
    every non-Habits view, so it shouldn't surface as a link candidate
    here either) and the same label-membership test every label filter in
    this app uses (object_labels membership, case-sensitive on the stored
    name)."""
    labels = [n for n in (label_names or []) if n]
    if not labels:
        return []
    habit_label = get_task_habit_settings(conn)["habit_label"]
    placeholders = ", ".join("?" for _ in labels)
    rows = conn.execute(
        f"SELECT tasks.* FROM tasks "
        f"WHERE tasks.uid IN (SELECT DISTINCT object_id FROM object_labels "
        f"  WHERE object_type = 'task' AND label_name IN ({placeholders}) "
        f"  AND object_id NOT IN (SELECT object_id FROM object_labels "
        f"    WHERE object_type = 'task' AND label_name = ?)) "
        f"ORDER BY tasks.title COLLATE NOCASE",
        (*labels, habit_label),
    ).fetchall()
    return [_attach_tags(conn, "task", _row_to_dict(r, _TASK_JSON_FIELDS)) for r in rows]


def list_events_sharing_labels(conn: sqlite3.Connection, label_names: list[str]) -> list[dict[str, Any]]:
    """Every event carrying at least one of `label_names` -- the "link an
    existing event" pool for a task's Relations card."""
    labels = [n for n in (label_names or []) if n]
    if not labels:
        return []
    placeholders = ", ".join("?" for _ in labels)
    rows = conn.execute(
        f"SELECT events.* FROM events "
        f"WHERE events.uid IN (SELECT DISTINCT object_id FROM object_labels "
        f"  WHERE object_type = 'event' AND label_name IN ({placeholders})) "
        f"ORDER BY events.start_at ASC",
        labels,
    ).fetchall()
    return [_attach_tags(conn, "event", _row_to_dict(r, _EVENT_JSON_FIELDS)) for r in rows]


# --------------------------------------------------------------------- #
# search_entities -- 1.2 (universal command surface, see plans/open.md §
# Universal command surface). One shared query layer for the search /
# picker / command palette component: finds tasks, events, and contacts by
# name -- plus working filters -- and is the single source of truth every
# future invocation mode (Ctrl-K global search, the relation picker, the
# per-view search boxes) delegates to instead of each view's own q=
# handling. Fuzzy free-text over the meaningful indexed metadata (titles,
# descriptions, labels, contact fields); explicit filters AND together;
# multi-select labels are any-match (one shared label suffices), matching
# the app's established label-membership convention.
# --------------------------------------------------------------------- #


def search_entities(
    conn: sqlite3.Connection,
    q: str | None = None,
    types: list[str] | None = None,
    labels: list[str] | None = None,
    task_status: str | None = None,
    task_due_on: str | None = None,
    event_start: str | None = None,
    event_end: str | None = None,
    exclude_uids: dict[str, set[str]] | None = None,
    include_habit_tasks: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Search across tasks, events, contacts, and notes.

    Explicit filters (AND together):
      - `q`        -- free-text, case-insensitive substring across the
                      meaningful metadata: task title/description/labels;
                      event title/description/labels; contact name/org/
                      phone/email/labels; note content/labels. (Fuzzy = SQL
                      LIKE, the same mechanism list_tasks/list_contacts
                      already use -- no index, appropriate at personal-scale
                      volumes.)
      - `types`    -- subset of ("task", "event", "contact", "note");
                      None/empty means all four. ("note" added 2026-08-15,
                      Quick Capture -- every existing caller that passes an
                      explicit `types` list of its own, e.g. the relation
                      picker's `["event"]`/`["task"]`, is unaffected.)
      - `labels`   -- multi-select label filter, any-match (a result needs
                      just one of the chosen labels), case-sensitive on the
                      stored object_labels name like every other label
                      query here.
      - `task_status`  -- tasks only: exact status match.
      - `task_due_on`  -- tasks only: due on this exact ISO date (the
                      picker's "due date" filter).
      - `event_start`/`event_end` -- events only: start_at within this
                      ISO-date range.

    Implicit (applied by the caller, see the spec's "implicit" list):
      - `exclude_uids`     -- {type: {uid, ...}} of already-linked items to
                      drop ("not-already-linked" for the relation picker).
      - `include_habit_tasks` -- False hides habit-labeled tasks, the same
                      default list_tasks applies everywhere.

    Returns a flat list of result dicts, one per hit, ordered by type
    (tasks, events, contacts) and then by that type's natural order; each
    carries a `type` tag plus a compact title/subtitle/tags surface for the
    picker plus the full row under `entity`:
      {"type": ..., "uid": ..., "title": ..., "subtitle": ..., "tags": [...], "entity": {...}}
    """
    wanted = set(types or ())
    # Implicit type restriction (the spec's "type" implicit filter): a
    # type-specific filter like task_status/due only ever applies to that
    # type, so supplying one narrows the search to it even when `types`
    # wasn't passed -- the same way the relation picker pre-sets its type.
    if task_status or task_due_on:
        wanted = {"task"} if not wanted else wanted & {"task"}
    if event_start or event_end:
        wanted = {"event"} if not wanted else wanted & {"event"}
    result: list[dict[str, Any]] = []
    exclude = exclude_uids or {}

    if not wanted or "task" in wanted:
        result.extend(_search_tasks(conn, q, labels, task_status, task_due_on, exclude.get("task", set()), include_habit_tasks))
    if not wanted or "event" in wanted:
        result.extend(_search_events(conn, q, labels, event_start, event_end, exclude.get("event", set())))
    if not wanted or "contact" in wanted:
        result.extend(_search_contacts(conn, q, labels, exclude.get("contact", set())))
    if not wanted or "note" in wanted:
        result.extend(_search_notes(conn, q, labels, exclude.get("note", set())))

    if limit is not None:
        result = result[:limit]
    return result


def _search_tasks(
    conn: sqlite3.Connection,
    q: str | None,
    labels: list[str] | None,
    task_status: str | None,
    task_due_on: str | None,
    excluded: set[str],
    include_habit_tasks: bool,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM tasks"
    params: list[str] = []
    clauses: list[str] = []

    if q:
        like = f"%{q}%"
        # Labels match through object_labels membership so "find a task with
        # a label called X" and "find a task whose title is X" are one box.
        clauses.append(
            "(title LIKE ? OR description LIKE ? OR uid IN (SELECT object_id FROM object_labels "
            "WHERE object_type = 'task' AND label_name LIKE ?))"
        )
        params.extend([like, like, like])
    if task_status:
        clauses.append("status = ?")
        params.append(task_status)
    if task_due_on:
        clauses.append("due_at = ?")
        params.append(task_due_on)
    if labels:
        placeholders = ", ".join("?" for _ in labels)
        clauses.append(
            f"uid IN (SELECT DISTINCT object_id FROM object_labels WHERE object_type = 'task' AND label_name IN ({placeholders}))"
        )
        params.extend(labels)
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        clauses.append(f"uid NOT IN ({placeholders})")
        params.extend(excluded)
    if not include_habit_tasks:
        habit_label = get_task_habit_settings(conn)["habit_label"]
        excluded_uids = list_object_ids_for_label(conn, "task", habit_label)
        if excluded_uids:
            placeholders = ", ".join("?" for _ in excluded_uids)
            clauses.append(f"uid NOT IN ({placeholders})")
            params.extend(excluded_uids)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    # Importance/Urgency no longer sort here -- both are purely computed
    # (src/derived_state.py, label rules + temporal state), not raw
    # columns SQL can order by; a caller that needs importance/urgency
    # ordering does it in Python via derived_state's effective values
    # (see routers/tasks.py's _SORT_KEYS).
    query += " ORDER BY (due_at IS NULL), due_at ASC"
    rows = conn.execute(query, params).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _attach_tags(conn, "task", _row_to_dict(r, _TASK_JSON_FIELDS))
        out.append(
            {
                "type": "task",
                "uid": d["uid"],
                "title": d["title"],
                "subtitle": f"Due {d['due_at'][:10]}" if d.get("due_at") else "No due date",
                "tags": d["tags"],
                "entity": d,
            }
        )
    return out


def _search_events(
    conn: sqlite3.Connection,
    q: str | None,
    labels: list[str] | None,
    event_start: str | None,
    event_end: str | None,
    excluded: set[str],
) -> list[dict[str, Any]]:
    query = "SELECT * FROM events"
    params: list[str] = []
    clauses: list[str] = []

    if q:
        like = f"%{q}%"
        clauses.append(
            "(title LIKE ? OR description LIKE ? OR uid IN (SELECT object_id FROM object_labels "
            "WHERE object_type = 'event' AND label_name LIKE ?))"
        )
        params.extend([like, like, like])
    if event_start:
        clauses.append("end_at IS NULL OR end_at >= ?")
        params.append(event_start)
    if event_end:
        # Same end-of-day normalization every calendar view applies when
        # passing a bare date range to list_events (e.g. routers/calendar.py
        # appends "T23:59:59"), so "on this day" includes that day's events.
        clauses.append("start_at <= ?")
        params.append(event_end + "T23:59:59" if "T" not in event_end else event_end)
    if labels:
        placeholders = ", ".join("?" for _ in labels)
        clauses.append(
            f"uid IN (SELECT DISTINCT object_id FROM object_labels WHERE object_type = 'event' AND label_name IN ({placeholders}))"
        )
        params.extend(labels)
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        clauses.append(f"uid NOT IN ({placeholders})")
        params.extend(excluded)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY start_at ASC"
    rows = conn.execute(query, params).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _attach_tags(conn, "event", _row_to_dict(r, _EVENT_JSON_FIELDS))
        start = d.get("start_at") or ""
        subtitle = f"{start[:10]} {start[11:16]}" if start else "No start time"
        out.append(
            {
                "type": "event",
                "uid": d["uid"],
                "title": d["title"],
                "subtitle": subtitle,
                "tags": d["tags"],
                "entity": d,
            }
        )
    return out


def _search_contacts(
    conn: sqlite3.Connection,
    q: str | None,
    labels: list[str] | None,
    excluded: set[str],
) -> list[dict[str, Any]]:
    query = "SELECT * FROM contacts"
    params: list[str] = []
    clauses: list[str] = []

    if q:
        # Same "search both the dead legacy columns and the new child
        # tables" reasoning as list_contacts above.
        like = f"%{q}%"
        clauses.append(
            "(full_name LIKE ? OR title LIKE ? OR org LIKE ? OR phone LIKE ? OR email LIKE ? OR uid IN "
            "(SELECT object_id FROM object_labels WHERE object_type = 'contact' AND label_name LIKE ?) OR uid IN "
            "(SELECT contact_uid FROM contact_phones WHERE value LIKE ?) OR uid IN "
            "(SELECT contact_uid FROM contact_emails WHERE value LIKE ?) OR uid IN "
            "(SELECT contact_uid FROM contact_websites WHERE url LIKE ?))"
        )
        params.extend([like, like, like, like, like, like, like, like, like])
    if labels:
        placeholders = ", ".join("?" for _ in labels)
        clauses.append(
            f"uid IN (SELECT DISTINCT object_id FROM object_labels WHERE object_type = 'contact' AND label_name IN ({placeholders}))"
        )
        params.extend(labels)
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        clauses.append(f"uid NOT IN ({placeholders})")
        params.extend(excluded)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY full_name COLLATE NOCASE"
    rows = conn.execute(query, params).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _attach_contact_phones_emails(conn, _attach_tags(conn, "contact", _row_to_dict(r, _CONTACT_JSON_FIELDS)))
        first_email = d["emails"][0]["value"] if d.get("emails") else d.get("email")
        first_phone = d["phones"][0]["value"] if d.get("phones") else d.get("phone")
        subtitle = d.get("org") or d.get("title") or first_email or first_phone or ""
        out.append(
            {
                "type": "contact",
                "uid": d["uid"],
                "title": d["full_name"],
                "subtitle": subtitle,
                "tags": d["tags"],
                "entity": d,
            }
        )
    return out


def _search_notes(
    conn: sqlite3.Connection,
    q: str | None,
    labels: list[str] | None,
    excluded: set[str],
) -> list[dict[str, Any]]:
    query = "SELECT * FROM notes"
    params: list[str] = []
    clauses: list[str] = []

    if q:
        like = f"%{q}%"
        clauses.append(
            "(content LIKE ? OR uid IN (SELECT object_id FROM object_labels "
            "WHERE object_type = 'note' AND label_name LIKE ?))"
        )
        params.extend([like, like])
    if labels:
        placeholders = ", ".join("?" for _ in labels)
        clauses.append(
            f"uid IN (SELECT DISTINCT object_id FROM object_labels WHERE object_type = 'note' AND label_name IN ({placeholders}))"
        )
        params.extend(labels)
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        clauses.append(f"uid NOT IN ({placeholders})")
        params.extend(excluded)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY updated_at DESC"
    rows = conn.execute(query, params).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _attach_tags(conn, "note", _row_to_dict(r, _NOTE_JSON_FIELDS))
        title = note_title(d)
        body = (d.get("content") or "").strip()
        subtitle = body[len(title) :].strip()[:80] if body.startswith(title) else body[:80]
        out.append(
            {
                "type": "note",
                "uid": d["uid"],
                "title": title,
                "subtitle": subtitle,
                "tags": d["tags"],
                "entity": d,
            }
        )
    return out


# --------------------------------------------------------------------- #
# Task checklist items -- 2026-08-08: checklists and subtasks merged into
# one feature (task_detail.html/task_form.html showed a single list,
# backed entirely by real subtasks). The 1.2 task-model decision then
# removed subtasks outright, so the merged list is gone entirely.
# list_checklist_items/add_checklist_item/toggle_checklist_item/
# delete_checklist_item are gone; delete_checklist_items_for_task survives
# as cascade cleanup for any checklist rows a database from before this
# change still physically has -- the table itself is deliberately not
# dropped, same "don't force-drop old data" convention as every other
# removed-feature table in this file.
# --------------------------------------------------------------------- #


def delete_checklist_items_for_task(conn: sqlite3.Connection, task_uid: str) -> None:
    """Called when a task is deleted -- see routers/tasks.py's delete_task.
    Without this, a re-created task that happened to reuse the same uid
    (never actually possible, uids are uuid4) is the only scenario that'd
    resurrect stale rows, but it's cheap correctness hygiene regardless --
    an orphaned checklist row pointing at a task_uid that no longer exists
    in `tasks` serves no purpose."""
    conn.execute("DELETE FROM task_checklist_items WHERE task_uid = ?", (task_uid,))
    conn.commit()


# --------------------------------------------------------------------- #
# Contacts
# --------------------------------------------------------------------- #

_CONTACT_JSON_FIELDS: tuple[str, ...] = ()

# Contacts field parity slice 2 of 6 -- the vCard/Nextcloud type vocabulary,
# green-lit exactly as-is (AskUserQuestion, 2026-08-15): phone gets the full
# Home/Work/Cell/Fax/Pager/Other set, email the narrower Home/Work/Other
# (vCard has no CELL/FAX/PAGER concept for EMAIL). "Other" is also the type
# every legacy single-value phone/email auto-migrates to (see
# migrate_legacy_contact_phone_email). Used by contact_form.html to render
# the type `<select>` and by routers/contacts.py to fall back to "Other" for
# an unrecognized/blank type rather than rejecting the save outright -- kept
# permissive (not a CHECK constraint) since a hand-edited vCard from another
# CardDAV client could carry a TYPE token outside this list.
CONTACT_PHONE_TYPES: tuple[str, ...] = ("Home", "Work", "Cell", "Fax", "Pager", "Other")
CONTACT_EMAIL_TYPES: tuple[str, ...] = ("Home", "Work", "Other")
# Contacts field parity slice 3 of 6 -- Website. Same vocabulary as email/
# address (green-lit, AskUserQuestion, 2026-08-15) -- vCard's URL property
# has no CELL/FAX/PAGER concept either.
CONTACT_WEBSITE_TYPES: tuple[str, ...] = ("Home", "Work", "Other")
# Contacts field parity slice 5 of 6 -- Address. Same Home/Work/Other
# vocabulary as email/website (green-lit, AskUserQuestion, 2026-08-15 --
# "same as email/address"), not phone's wider set (vCard's ADR has no
# CELL/FAX/PAGER concept either).
CONTACT_ADDRESS_TYPES: tuple[str, ...] = ("Home", "Work", "Other")
# Contacts field parity slice 6 of 6 -- Social network. Network names, not
# Home/Work/Other -- matches vcard_rows.py's own _SOCIAL_TYPE_TO_VCARD
# mapping (every entry here except "Other" has a TYPE= token there).
CONTACT_SOCIAL_TYPES: tuple[str, ...] = ("Twitter", "Facebook", "Instagram", "LinkedIn", "Mastodon", "GitHub", "Other")

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


def parse_contact_birthday(value: str) -> str:
    v = (value or "").strip()
    if _BIRTHDAY_FULL_RE.match(v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Birthday must be YYYY-MM-DD or --MM-DD, got '{value}'") from exc
        return v
    if _BIRTHDAY_YEARLESS_RE.match(v):
        month, day = v[2:4], v[5:7]
        try:
            # 2000 is a leap year -- lets a real "--02-29" (Feb 29, no
            # year) validate, same as it would for someone born in an
            # actual leap year, without this function needing to know
            # which specific years were leap years.
            datetime.strptime(f"2000-{month}-{day}", "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Birthday must be YYYY-MM-DD or --MM-DD, got '{value}'") from exc
        return v
    raise ValueError(f"Birthday must be YYYY-MM-DD or --MM-DD, got '{value}'")


_BIRTHDAY_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def format_contact_birthday(value: str | None) -> str:
    """Human-readable display form for a stored birthday string --
    "May 17, 1990" for a full date, "May 17" (no year) for a year-less
    one. Returns the raw stored value unchanged if it doesn't match either
    known shape (a hand-edited vCard from another CardDAV client could
    carry a BDAY this app didn't write, e.g. a bare `19900517` -- showing
    the original text is safer than guessing at a reformat)."""
    v = (value or "").strip()
    if _BIRTHDAY_FULL_RE.match(v):
        year, month, day = v.split("-")
        return f"{_BIRTHDAY_MONTHS[int(month) - 1]} {int(day)}, {year}"
    if _BIRTHDAY_YEARLESS_RE.match(v):
        month, day = v[2:4], v[5:7]
        return f"{_BIRTHDAY_MONTHS[int(month) - 1]} {int(day)}"
    return v


def _birthday_event_uid(contact_uid: str) -> str:
    return f"birthday::{contact_uid}"


def sync_contact_birthday_event(conn: sqlite3.Connection, contact_uid: str, full_name: str | None, birthday: str | None) -> None:
    """Direct follow-up (2026-08-16) to Contacts field parity slice 4 of 6:
    a contact's Birthday shows up on the Calendar itself, as a real all-day
    event recurring yearly, tagged with the "Birthday" label -- not a
    separate widget. Called from upsert_contact on every save (so the
    event's title/date always tracks the contact's current full_name/
    birthday) and from delete_contact.

    The event's uid is deterministic (`_birthday_event_uid`), not a fresh
    uuid4 -- lets this function find-and-replace it idempotently without a
    separate contact<->event relation column/table, the same "derive the
    id instead of storing a relation" shape event_occurrence_overrides'
    `master_uid::occurrence_date` composite key already uses. A cleared
    birthday (`None`) deletes the event outright via `delete_event` (which
    also clears its `object_labels` row) rather than leaving a dangling
    dateless event around.

    A year-less "--MM-DD" birthday has no real year to anchor DTSTART on,
    so it uses a fixed placeholder year (1900) far enough in the past that
    `FREQ=YEARLY` always has a "this year" occurrence to expand, regardless
    of when the calendar is viewed -- RRULE recurrence only ever generates
    occurrences forward from DTSTART, never before it, which is also
    exactly correct for a *full* birthday date: recurrence naturally starts
    at the real birth year and never fires an occurrence before someone was
    born."""
    event_uid = _birthday_event_uid(contact_uid)
    if not birthday:
        delete_event(conn, event_uid)
        return
    v = birthday.strip()
    if v.startswith("--"):
        start_at = f"1900-{v[2:4]}-{v[5:7]}"
    else:
        start_at = v
    existing = get_event(conn, event_uid)
    now = datetime.now(timezone.utc).isoformat()
    upsert_event(
        conn,
        {
            "uid": event_uid,
            "title": f"{full_name}'s Birthday" if full_name else "Birthday",
            "description": "",
            "start_at": start_at,
            "end_at": None,
            "all_day": True,
            "location": None,
            "meeting_url": None,
            "status": "active",
            "recurrence": "FREQ=YEARLY",
            "tags": ["Birthday"],
            "reminders": [],
            "holiday_calendar": None,
            "exclude_saturday": False,
            "exclude_sunday": False,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        },
    )


def upsert_contact(
    conn: sqlite3.Connection, row: dict[str, Any], *, record_server_write: bool = True
) -> None:
    data = dict(row)
    if record_server_write:
        previous = _row_columns(conn, "contacts", str(data.get("uid")), _CONTACT_SYNC_COLUMNS)
    tags = data.pop("tags", None)
    # `phones`/`emails` (the new multi-value lists) are handled separately
    # below, same "pop the non-column keys, write the base row, then attach
    # the related rows" shape `tags` already used -- upsert_contact stays
    # the single call site every router/test uses to save a contact, it just
    # now also owns writing the child tables when the caller supplies them.
    phones = data.pop("phones", None)
    emails = data.pop("emails", None)
    # Contacts field parity slice 3 of 6 -- Website, same "pop, write the
    # base row, then attach the related rows" shape as phones/emails above.
    websites = data.pop("websites", None)
    # Contacts field parity slice 5 of 6 -- Address, same "pop, write the
    # base row, then attach the related rows" shape as phones/emails/
    # websites above.
    addresses = data.pop("addresses", None)
    # Contacts field parity slice 6 of 6 -- Social network, same "pop,
    # write the base row, then attach the related rows" shape as phones/
    # emails/websites/addresses above.
    social_profiles = data.pop("social_profiles", None)
    cols = [
        "uid", "full_name", "title", "org",
        "phone", "email", "address", "birthday", "notes",
        "photo_b64", "photo_type", "created_at", "updated_at",
    ]
    values = [data.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid")
    conn.execute(
        f"INSERT INTO contacts ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        values,
    )
    if tags is not None:
        set_object_labels(conn, "contact", data["uid"], tags)
    if phones is not None:
        set_contact_phones(conn, data["uid"], phones)
    if emails is not None:
        set_contact_emails(conn, data["uid"], emails)
    if websites is not None:
        set_contact_websites(conn, data["uid"], websites)
    if addresses is not None:
        set_contact_addresses(conn, data["uid"], addresses)
    if social_profiles is not None:
        set_contact_social_profiles(conn, data["uid"], social_profiles)
    if record_server_write:
        record_server_sync_write(
            conn,
            "contact",
            data["uid"],
            previous,
            _row_columns(conn, "contacts", data["uid"], _CONTACT_SYNC_COLUMNS),
        )
    conn.commit()
    # Direct follow-up (2026-08-16): keep the generated Birthday calendar
    # event in sync with every save -- see sync_contact_birthday_event's
    # own docstring. Runs unconditionally (not gated on "birthday" being in
    # `data`) since a hand-built row dict that omits the key entirely
    # (`data.get("birthday")` -> None) should behave exactly like an
    # explicit clear -- the same "missing key means no value" convention
    # `format_contact_birthday`/every other optional contact field here
    # already follows.
    sync_contact_birthday_event(conn, data["uid"], data.get("full_name"), data.get("birthday"))


def delete_contact(
    conn: sqlite3.Connection, uid: str, *, record_server_write: bool = True
) -> None:
    if record_server_write:
        record_server_delete(conn, "contact", uid)
    conn.execute("DELETE FROM contacts WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM object_labels WHERE object_type = 'contact' AND object_id = ?", (uid,))
    # Same cascade-cleanup reasoning as delete_checklist_items_for_task --
    # never actually reachable via a reused uid (uuid4), but an orphaned
    # phone/email/website row pointing at a gone contact serves no purpose
    # either.
    conn.execute("DELETE FROM contact_phones WHERE contact_uid = ?", (uid,))
    conn.execute("DELETE FROM contact_emails WHERE contact_uid = ?", (uid,))
    conn.execute("DELETE FROM contact_websites WHERE contact_uid = ?", (uid,))
    conn.execute("DELETE FROM contact_addresses WHERE contact_uid = ?", (uid,))
    conn.execute("DELETE FROM contact_social_profiles WHERE contact_uid = ?", (uid,))
    # Deletes the generated Birthday event (if one exists) along with the
    # contact itself -- see sync_contact_birthday_event's docstring for why
    # this is a plain delete_event on the deterministic uid, not a lookup
    # through any relation table.
    delete_event(conn, _birthday_event_uid(uid))
    conn.commit()


def get_contact(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM contacts WHERE uid = ?", (uid,)).fetchone()
    if not row:
        return None
    d = _attach_tags(conn, "contact", _row_to_dict(row, _CONTACT_JSON_FIELDS))
    return _attach_contact_phones_emails(conn, d)


def _attach_contact_phones_emails(conn: sqlite3.Connection, d: dict[str, Any]) -> dict[str, Any]:
    """Attaches `phones`/`emails`/`websites`/`addresses` (each a list of
    position-ordered dicts -- phones/emails are {"uid", "type", "value"},
    websites {"uid", "type", "url"}, addresses {"uid", "type", "po_box",
    "extended", "street", "city", "region", "postal_code", "country"},
    social_profiles {"uid", "type", "value"}) the same way `_attach_tags`
    attaches `tags` -- computed live from the child tables at read time,
    never a stored JSON blob on the contacts row itself."""
    d["phones"] = list_contact_phones(conn, d["uid"])
    d["emails"] = list_contact_emails(conn, d["uid"])
    d["websites"] = list_contact_websites(conn, d["uid"])
    d["addresses"] = list_contact_addresses(conn, d["uid"])
    d["social_profiles"] = list_contact_social_profiles(conn, d["uid"])
    return d


def list_contacts(
    conn: sqlite3.Connection,
    q: str | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM contacts"
    params: list[str] = []
    clauses = []
    if q:
        # Matches name, org, title, or any phone/email -- both the legacy
        # flat columns (harmless redundancy; a pre-migration value can only
        # exist there if migrate_legacy_contact_phone_email somehow hasn't
        # run yet, which it always has by the time any query executes -- see
        # that function's own call site in init_schema) and the new
        # multi-value child tables, so a search for a number/address still
        # finds the contact no matter which type it's tagged with.
        clauses.append(
            "(full_name LIKE ? OR title LIKE ? OR org LIKE ? OR phone LIKE ? OR email LIKE ? "
            "OR uid IN (SELECT contact_uid FROM contact_phones WHERE value LIKE ?) "
            "OR uid IN (SELECT contact_uid FROM contact_emails WHERE value LIKE ?) "
            "OR uid IN (SELECT contact_uid FROM contact_websites WHERE url LIKE ?))"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like, like, like, like, like])
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY full_name ASC"
    rows = conn.execute(query, params).fetchall()
    return [
        _attach_contact_phones_emails(conn, _attach_tags(conn, "contact", _row_to_dict(r, _CONTACT_JSON_FIELDS)))
        for r in rows
    ]


# --------------------------------------------------------------------- #
# Contact phones / emails -- Contacts field parity slice 2 of 6 (plans/
# open.md). Per-parent child-table CRUD, closest precedent is work
# allocations' list_work_allocations_for_task/create_work_allocation/
# delete_work_allocation trio -- but a contact's phone/email list is edited
# as a whole via one Save button (contact_form.html submits every row
# together as parallel phone_type[]/phone_value[] form arrays, same shape
# `tags_labels: list[str] = Form([])` already uses on this router), not
# through separate per-row add/remove endpoints the way work sessions or
# checklist items are -- so the primary write operation here is
# set_contact_phones/set_contact_emails ("replace everything for this
# contact with this ordered list"), not incremental add/update/delete
# calls. add_contact_phone/add_contact_email still exist standalone because
# migrate_legacy_contact_phone_email needs to insert exactly one row without
# disturbing anything else already there.
# --------------------------------------------------------------------- #


def list_contact_phones(conn: sqlite3.Connection, contact_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM contact_phones WHERE contact_uid = ? ORDER BY position ASC, created_at ASC",
        (contact_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_contact_emails(conn: sqlite3.Connection, contact_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM contact_emails WHERE contact_uid = ? ORDER BY position ASC, created_at ASC",
        (contact_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_contact_phone(conn: sqlite3.Connection, contact_uid: str, type_: str, value: str) -> str:
    """Appends one phone row after whatever's already there. Used by
    migrate_legacy_contact_phone_email (a single-row, non-destructive
    insert); the create/edit form uses set_contact_phones instead, since it
    always submits the full list at once."""
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM contact_phones WHERE contact_uid = ?",
        (contact_uid,),
    ).fetchone()
    new_uid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO contact_phones (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (new_uid, contact_uid, type_ or "Other", value, row["p"], datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return new_uid


def add_contact_email(conn: sqlite3.Connection, contact_uid: str, type_: str, value: str) -> str:
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM contact_emails WHERE contact_uid = ?",
        (contact_uid,),
    ).fetchone()
    new_uid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO contact_emails (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (new_uid, contact_uid, type_ or "Other", value, row["p"], datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return new_uid


def set_contact_phones(conn: sqlite3.Connection, contact_uid: str, items: list[dict[str, Any]]) -> None:
    """Replaces every phone row for `contact_uid` with `items` (each a
    {"type", "value"} dict), in the given order. The create/edit form always
    submits its whole ordered phone list together (one Save button, per
    plans/open.md's own reasoning for choosing form-array fields over
    per-row endpoints) so "delete everything, re-insert in submitted order"
    is simpler and just as correct as diffing against the previous set by
    uid -- position is always just the item's index, so display order keeps
    matching submission order. Blank values are dropped silently (an empty
    row in the form is "no phone here", not a phone with an empty number)."""
    conn.execute("DELETE FROM contact_phones WHERE contact_uid = ?", (contact_uid,))
    now = datetime.now(timezone.utc).isoformat()
    position = 0
    for item in items:
        value = (item.get("value") or "").strip()
        if not value:
            continue
        conn.execute(
            "INSERT INTO contact_phones (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), contact_uid, item.get("type") or "Other", value, position, now),
        )
        position += 1
    conn.commit()


def set_contact_emails(conn: sqlite3.Connection, contact_uid: str, items: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM contact_emails WHERE contact_uid = ?", (contact_uid,))
    now = datetime.now(timezone.utc).isoformat()
    position = 0
    for item in items:
        value = (item.get("value") or "").strip()
        if not value:
            continue
        conn.execute(
            "INSERT INTO contact_emails (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), contact_uid, item.get("type") or "Other", value, position, now),
        )
        position += 1
    conn.commit()


# --------------------------------------------------------------------- #
# Contact websites -- Contacts field parity slice 3 of 6 (plans/open.md).
# Same shape as contact_phones/contact_emails immediately above -- one
# Save-button replace-all write path (set_contact_websites), no separate
# add/remove endpoints. Unlike phone/email, there is no legacy single-value
# column to migrate from (confirmed by grep before this slice started), so
# there's no add_contact_website standalone helper -- nothing needs to
# insert exactly one row outside of set_contact_websites.
# --------------------------------------------------------------------- #


def list_contact_websites(conn: sqlite3.Connection, contact_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM contact_websites WHERE contact_uid = ? ORDER BY position ASC, created_at ASC",
        (contact_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def set_contact_websites(conn: sqlite3.Connection, contact_uid: str, items: list[dict[str, Any]]) -> None:
    """Replaces every website row for `contact_uid` with `items` (each a
    {"type", "url"} dict), in the given order -- same "delete everything,
    re-insert in submitted order" reasoning as set_contact_phones/
    set_contact_emails. Blank URLs are dropped silently."""
    conn.execute("DELETE FROM contact_websites WHERE contact_uid = ?", (contact_uid,))
    now = datetime.now(timezone.utc).isoformat()
    position = 0
    for item in items:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        conn.execute(
            "INSERT INTO contact_websites (uid, contact_uid, type, url, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), contact_uid, item.get("type") or "Other", url, position, now),
        )
        position += 1
    conn.commit()


# --------------------------------------------------------------------- #
# Contact addresses -- Contacts field parity slice 5 of 6 (plans/open.md).
# Same shape as contact_phones/contact_emails/contact_websites above (one
# Save-button replace-all write path, no separate add/remove endpoints),
# just with seven value fields per row instead of one. A row counts as
# "blank" (dropped on save) only when EVERY structured field is blank --
# unlike phone/email/website's single `value`/`url`, a real address could
# legitimately have e.g. only a city and country filled in, so there's no
# single field whose blankness alone means "no address here."
# --------------------------------------------------------------------- #

_CONTACT_ADDRESS_FIELDS: tuple[str, ...] = (
    "po_box", "extended", "street", "city", "region", "postal_code", "country",
)


def list_contact_addresses(conn: sqlite3.Connection, contact_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM contact_addresses WHERE contact_uid = ? ORDER BY position ASC, created_at ASC",
        (contact_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def format_contact_address(addr: dict[str, Any]) -> str:
    """Human-readable multi-line display for one structured address dict
    (contact_detail.html's `fmt_address` filter, deps.py) -- same line
    ordering vCard's own `vobject.vcard.Address.__str__` uses (PO Box/
    Extended/Street each get their own line if present, then "City, Region
    PostalCode" on one line, then Country on its own line), reimplemented
    here as a pure function of this app's dict shape rather than building a
    throwaway `vobject.vcard.Address` object just to stringify it. Blank
    fields are omitted entirely rather than leaving stray empty lines/
    commas."""
    lines = [addr.get(f) for f in ("po_box", "extended", "street") if (addr.get(f) or "").strip()]
    city, region, postal_code = addr.get("city") or "", addr.get("region") or "", addr.get("postal_code") or ""
    if city.strip() or region.strip() or postal_code.strip():
        city_line = ", ".join(p for p in (city.strip(), " ".join(p for p in (region.strip(), postal_code.strip()) if p)) if p)
        lines.append(city_line)
    if (addr.get("country") or "").strip():
        lines.append(addr["country"].strip())
    return "\n".join(lines)


def set_contact_addresses(conn: sqlite3.Connection, contact_uid: str, items: list[dict[str, Any]]) -> None:
    """Replaces every address row for `contact_uid` with `items` (each a
    {"type", "po_box", "extended", "street", "city", "region",
    "postal_code", "country"} dict, any key may be omitted), in the given
    order -- same "delete everything, re-insert in submitted order"
    reasoning as set_contact_phones/set_contact_emails/set_contact_websites.
    A row is dropped only when every one of the seven structured fields is
    blank (see this section's own comment for why that's a 7-way check,
    not a single-field one like the sibling setters)."""
    conn.execute("DELETE FROM contact_addresses WHERE contact_uid = ?", (contact_uid,))
    now = datetime.now(timezone.utc).isoformat()
    position = 0
    for item in items:
        values = {f: (item.get(f) or "").strip() for f in _CONTACT_ADDRESS_FIELDS}
        if not any(values.values()):
            continue
        conn.execute(
            "INSERT INTO contact_addresses "
            "(uid, contact_uid, type, po_box, extended, street, city, region, postal_code, country, position, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), contact_uid, item.get("type") or "Other",
                values["po_box"], values["extended"], values["street"],
                values["city"], values["region"], values["postal_code"], values["country"],
                position, now,
            ),
        )
        position += 1
    conn.commit()


# --------------------------------------------------------------------- #
# Contact social profiles -- Contacts field parity slice 6 of 6 (plans/
# open.md). Same shape as contact_phones/contact_emails/contact_websites
# (single `value` column, one Save-button replace-all write path, no
# separate add/remove endpoints, no legacy column to migrate -- same
# "confirmed by grep, nothing to migrate" situation as Website).
# --------------------------------------------------------------------- #


def list_contact_social_profiles(conn: sqlite3.Connection, contact_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM contact_social_profiles WHERE contact_uid = ? ORDER BY position ASC, created_at ASC",
        (contact_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def set_contact_social_profiles(conn: sqlite3.Connection, contact_uid: str, items: list[dict[str, Any]]) -> None:
    """Replaces every social-profile row for `contact_uid` with `items`
    (each a {"type", "value"} dict), in the given order -- same "delete
    everything, re-insert in submitted order" reasoning as
    set_contact_phones/set_contact_emails/set_contact_websites. Blank
    values are dropped silently."""
    conn.execute("DELETE FROM contact_social_profiles WHERE contact_uid = ?", (contact_uid,))
    now = datetime.now(timezone.utc).isoformat()
    position = 0
    for item in items:
        value = (item.get("value") or "").strip()
        if not value:
            continue
        conn.execute(
            "INSERT INTO contact_social_profiles (uid, contact_uid, type, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), contact_uid, item.get("type") or "Other", value, position, now),
        )
        position += 1
    conn.commit()


# --------------------------------------------------------------------- #
# Notes (Quick Capture, plans/quick-capture.md) -- see the `notes` CREATE
# TABLE comment above for what a note is/isn't. Same shape as contacts'
# own CRUD immediately above: upsert/get/delete/list, tags attached live
# via object_labels like every other type.
# --------------------------------------------------------------------- #

_NOTE_JSON_FIELDS: tuple[str, ...] = ()


def upsert_note(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    tags = data.pop("tags", None)
    cols = ["uid", "content", "created_at", "updated_at"]
    values = [data.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid")
    conn.execute(
        f"INSERT INTO notes ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        values,
    )
    if tags is not None:
        set_object_labels(conn, "note", data["uid"], tags)
    conn.commit()


def delete_note(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM notes WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM object_labels WHERE object_type = 'note' AND object_id = ?", (uid,))
    conn.commit()


def get_note(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM notes WHERE uid = ?", (uid,)).fetchone()
    return _attach_tags(conn, "note", _row_to_dict(row, _NOTE_JSON_FIELDS)) if row else None


def list_notes(conn: sqlite3.Connection, q: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM notes"
    params: list[str] = []
    if q:
        query += " WHERE content LIKE ?"
        params.append(f"%{q}%")
    query += " ORDER BY updated_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [_attach_tags(conn, "note", _row_to_dict(r, _NOTE_JSON_FIELDS)) for r in rows]


def note_title(note: dict[str, Any]) -> str:
    """A note has no title column (see the `notes` CREATE TABLE comment) --
    every list/search/picker surface that needs a short label for one uses
    this: the content's first non-blank line, truncated, or a placeholder
    for a still-empty note."""
    for line in (note.get("content") or "").splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return "(empty note)"


def list_object_label_names(conn: sqlite3.Connection, object_type: str) -> list[str]:
    """Distinct labels in use on every object of `object_type` -- the
    generic form of what list_contact_tag_names has done since Phase 7
    (Contacts' tag filter). Case-preserving on first occurrence, deduped
    case-insensitively, sorted case-insensitively -- object_labels' PK is
    exact-string, so "University" and "university" are two distinct rows
    there; this collapses them the same way list_tag_names_in_use always
    has. Reused by the Phase 9b toolbar rework for the Tasks and Calendar
    (event) label filters, which follow the exact same chip-based pattern
    Contacts pioneered."""
    rows = conn.execute(
        "SELECT DISTINCT label_name FROM object_labels WHERE object_type = ? ORDER BY label_name COLLATE NOCASE",
        (object_type,),
    ).fetchall()
    seen: dict[str, str] = {}
    for r in rows:
        seen.setdefault(r["label_name"].strip().lower(), r["label_name"])
    return sorted(seen.values(), key=str.lower)


def list_contact_tag_names(conn: sqlite3.Connection) -> list[str]:
    """Distinct labels across all contacts (Phase 7 rework -- the Contacts
    tag filter + the project People section; Phase 2 label-space rework --
    now backed by object_labels instead of tags_json). Thin wrapper over
    list_object_label_names, kept under its historical name since every
    existing caller (contacts.py, contacts_list.html) already uses it."""
    return list_object_label_names(conn, "contact")


def list_task_label_names(conn: sqlite3.Connection) -> list[str]:
    """Distinct labels across all tasks -- Phase 9b toolbar rework's new
    Tasks label filter (Table/Timeline/Board all share this)."""
    return list_object_label_names(conn, "task")


def list_event_label_names(conn: sqlite3.Connection) -> list[str]:
    """Distinct labels across all events -- Phase 9b toolbar rework's new
    Calendar label filter (Month/Week/Day/Agenda all share this)."""
    return list_object_label_names(conn, "event")


def all_contact_uids(conn: sqlite3.Connection) -> set[str]:
    return {r["uid"] for r in conn.execute("SELECT uid FROM contacts").fetchall()}


def find_contact_by_name(conn: sqlite3.Connection, full_name: str) -> dict[str, Any] | None:
    """Case-insensitive exact match on full_name. Exact-match rather than
    fuzzy on purpose: silently linking to
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
    return _attach_tags(conn, "contact", _row_to_dict(row, _CONTACT_JSON_FIELDS)) if row else None


# --------------------------------------------------------------------- #
# Holidays -- named holiday calendars any recurring event can reference
# (1.6, "Generalized non-working-day policy"). Unrelated to the Schedule
# module (removed 2026-08-15, see plans/STATE.md) -- these stayed because
# they're a generic recurrence mechanism, not something Schedule-specific.
# --------------------------------------------------------------------- #

# 2026-08-07: the Grades accessor functions (upsert_grade/get_grade/
# list_grades/delete_grade/delete_grades_by_class) that used to live here
# are gone along with the `grades` table -- see the SCHEMA_SQL comment
# above and features/architecture.md's Grades/Databases removal note.


def upsert_holiday(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO schedule_holidays (uid, calendar_name, label, date_from, date_to) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET calendar_name=excluded.calendar_name, label=excluded.label, "
        "date_from=excluded.date_from, date_to=excluded.date_to",
        (row["uid"], row.get("calendar_name") or "Default", row.get("label", ""), row["date_from"], row["date_to"]),
    )
    conn.commit()


def get_holiday(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM schedule_holidays WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None


def delete_holiday(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM schedule_holidays WHERE uid = ?", (uid,))
    conn.commit()


def list_holidays(conn: sqlite3.Connection, calendar_name: str | None = None) -> list[dict[str, Any]]:
    if calendar_name:
        rows = conn.execute(
            "SELECT * FROM schedule_holidays WHERE calendar_name = ? ORDER BY date_from", (calendar_name,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM schedule_holidays ORDER BY calendar_name COLLATE NOCASE, date_from").fetchall()
    return [dict(r) for r in rows]


def list_holiday_calendar_names(conn: sqlite3.Connection) -> list[str]:
    """Every distinct named holiday calendar in use -- there's no separate
    `holiday_calendars` table (see schedule_holidays' own CREATE TABLE
    comment), a calendar is just a name some holiday rows share. Powers the
    recurrence editor's "Holiday calendar" dropdown and the manage UI's own
    list of existing calendars."""
    rows = conn.execute(
        "SELECT DISTINCT calendar_name FROM schedule_holidays ORDER BY calendar_name COLLATE NOCASE"
    ).fetchall()
    return [r["calendar_name"] for r in rows]


def list_holidays_by_calendar(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """{calendar_name: [holiday rows]} -- the shape
    `recurrence_expand.expand_events`'s `holiday_calendars` parameter
    expects. Built once per request (never per-event), same "routers
    compute, pure logic just reads what it's given" layering every other
    feature in this app follows."""
    by_calendar: dict[str, list[dict[str, Any]]] = {}
    for row in list_holidays(conn):
        by_calendar.setdefault(row["calendar_name"], []).append(row)
    return by_calendar


# --------------------------------------------------------------------- #
# Sleep Time / Leisure Time (see time_blocks' own CREATE TABLE comment) --
# same minimal shape as the schedule_holidays functions directly above
# (plain dict rows, upsert-by-uid, explicit commit).
# --------------------------------------------------------------------- #

TIME_BLOCK_KINDS = ("sleep", "leisure")
TIME_BLOCK_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def upsert_time_block(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO time_blocks (uid, kind, label, start_time, end_time, days) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET kind=excluded.kind, label=excluded.label, "
        "start_time=excluded.start_time, end_time=excluded.end_time, days=excluded.days",
        (row["uid"], row["kind"], row.get("label", ""), row["start_time"], row["end_time"], row.get("days", "")),
    )
    conn.commit()


def get_time_block(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM time_blocks WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None


def delete_time_block(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM time_blocks WHERE uid = ?", (uid,))
    conn.commit()


def list_time_blocks(conn: sqlite3.Connection, kind: str | None = None) -> list[dict[str, Any]]:
    if kind:
        rows = conn.execute("SELECT * FROM time_blocks WHERE kind = ? ORDER BY start_time", (kind,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM time_blocks ORDER BY kind, start_time").fetchall()
    return [dict(r) for r in rows]


def time_block_days(row: dict[str, Any]) -> list[str]:
    """`row['days']` ("Monday,Wednesday,Friday") split back into a list --
    the one place both the settings table and the overlay/warning code
    parse this field, so they can't drift on the separator."""
    return [d.strip() for d in (row.get("days") or "").split(",") if d.strip()]


def get_task_habit_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM task_habit_settings WHERE id = 1").fetchone()
    if row is None:
        return {"habit_label": "Habit"}
    return dict(row)


def save_task_habit_settings(conn: sqlite3.Connection, habit_label: str) -> None:
    conn.execute(
        "INSERT INTO task_habit_settings (id, habit_label) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET habit_label=excluded.habit_label",
        (habit_label.strip() or "Habit",),
    )
    conn.commit()


# --------------------------------------------------------------------- #
# Object labels (Phase 1, label-space rework) -- the one join table
# labels use. `object_type` is 'task'|'event'|'contact' for now (more
# types land in later phases). No surrogate id/lifecycle -- see
# features/architecture.md §0.1: a label is just a name rows point
# at, "deleting" one is just no row pointing at it anymore.
# --------------------------------------------------------------------- #


def add_object_label(conn: sqlite3.Connection, object_type: str, object_id: str, label_name: str) -> None:
    label_name = (label_name or "").strip()
    if not label_name:
        return
    conn.execute(
        "INSERT OR IGNORE INTO object_labels (object_type, object_id, label_name) VALUES (?, ?, ?)",
        (object_type, object_id, label_name),
    )
    conn.commit()


def remove_object_label(conn: sqlite3.Connection, object_type: str, object_id: str, label_name: str) -> None:
    conn.execute(
        "DELETE FROM object_labels WHERE object_type = ? AND object_id = ? AND label_name = ?",
        (object_type, object_id, label_name),
    )
    conn.commit()


def set_object_labels(conn: sqlite3.Connection, object_type: str, object_id: str, label_names: list[str]) -> None:
    """Replaces every label currently on (object_type, object_id) with
    exactly `label_names` -- the common "save this object's label picker"
    write shape, one transaction instead of a diff of adds/removes.

    2026-08-09: each submitted name is resolved through
    `_resolve_label_name` first, so an abbreviation (label_config.
    abbreviation) typed anywhere a label name is expected lands as its
    full label -- an abbreviation is a synonym for its label, never a
    separate label of its own."""
    conn.execute(
        "DELETE FROM object_labels WHERE object_type = ? AND object_id = ?", (object_type, object_id)
    )
    seen: set[str] = set()
    for name in label_names or []:
        name = (name or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            name = _resolve_label_name(conn, name)
            conn.execute(
                "INSERT OR IGNORE INTO object_labels (object_type, object_id, label_name) VALUES (?, ?, ?)",
                (object_type, object_id, name),
            )
    conn.commit()


def _resolve_label_name(conn: sqlite3.Connection, name: str) -> str:
    """(2026-08-09) Maps a submitted label string through the
    abbreviation -> full-name synonym table, returning `name` unchanged
    when it isn't one. Rules, all deliberate:
      * A string that's already a real label always wins -- a label
        literally named e.g. "ABC" beats another label's "ABC"
        abbreviation, so an abbreviation can never shadow a genuine label.
      * The match is case-insensitive (labels are deduped
        case-insensitively everywhere, see effective_label_config_ci).
      * Only a *unique* abbreviation resolves -- if two config rows carry
        the same abbreviation (or it collides case-insensitively), the
        string is passed through untouched rather than guessing which
        label the user meant."""
    known = {n.lower() for n in list_all_label_names(conn)}
    known |= {r["name"].lower() for r in conn.execute("SELECT name FROM label_config").fetchall()}
    if name.lower() in known:
        return name
    rows = conn.execute(
        "SELECT name FROM label_config "
        "WHERE abbreviation IS NOT NULL AND abbreviation != '' AND abbreviation = ? COLLATE NOCASE",
        (name,),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]["name"]
    return name


def resolve_capture_label(conn: sqlite3.Connection, name: str) -> str:
    """Quick Capture's label resolution (plans/quick-capture.md § Labels
    and Approximate Matching) -- deliberately separate from
    `_resolve_label_name` above (that one only ever resolves an explicit
    `label_config.abbreviation` synonym; this is the spec's own
    approximate-matching pipeline for a capture's `#label` tokens, which
    have no such config row backing them):

      1. Exact match (case-insensitive) against every label already in
         use always wins -- "a label is first matched ... using an exact
         match."
      2. Exact match against a previously-learned alias (`label_aliases`)
         -- a typo already corrected once resolves instantly without
         recomputing the fuzzy match below.
      3. A close-but-not-exact match against every label in use
         (`difflib.get_close_matches`, cutoff 0.8 -- high on purpose, so
         only genuine near-typos resolve, e.g. "uunniversity"/
         "universitty"/"unisity" -> "university" from the spec's own
         examples, not merely related words) is picked automatically ("a
         very close match may be resolved automatically") and persisted
         as a new alias.
      4. Otherwise `name` is returned unchanged -- a genuinely new label,
         "preserving the ability to create genuinely new labels."

    Simplification, noted deliberately: the spec also describes an
    "uncertain match ... suggested for correction" tier sitting between
    (3) and (4), reviewed interactively before being accepted. Quick
    Capture v1 has no such review step (a capture is a single fire-and-
    forget submission, not a multi-turn form) -- step 3's automatic
    resolution doubles as the "user correction" step 4 of the spec
    describes recording into the alias table, since there's no separate
    moment where a person explicitly confirms it. A future interactive
    capture flow could split this back into two real tiers without
    changing the alias table's shape."""
    import difflib

    existing = list_all_label_names(conn)
    lower_map = {n.lower(): n for n in existing}
    if name.lower() in lower_map:
        return lower_map[name.lower()]

    alias_row = conn.execute(
        "SELECT canonical_name FROM label_aliases WHERE alias = ?", (name.lower(),)
    ).fetchone()
    if alias_row:
        return alias_row["canonical_name"]

    if existing:
        matches = difflib.get_close_matches(name.lower(), list(lower_map.keys()), n=1, cutoff=0.8)
        if matches:
            canonical = lower_map[matches[0]]
            conn.execute(
                "INSERT OR REPLACE INTO label_aliases (alias, canonical_name, created_at) VALUES (?, ?, ?)",
                (name.lower(), canonical, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            return canonical

    return name


def list_labels_for_object(conn: sqlite3.Connection, object_type: str, object_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT label_name FROM object_labels WHERE object_type = ? AND object_id = ? ORDER BY label_name COLLATE NOCASE",
        (object_type, object_id),
    ).fetchall()
    return [r["label_name"] for r in rows]


def list_object_ids_for_label(conn: sqlite3.Connection, object_type: str, label_name: str) -> list[str]:
    rows = conn.execute(
        "SELECT object_id FROM object_labels WHERE object_type = ? AND label_name = ?",
        (object_type, label_name),
    ).fetchall()
    return [r["object_id"] for r in rows]


def list_all_label_names(conn: sqlite3.Connection) -> list[str]:
    """Every distinct label name currently in use, across every object
    type -- powers a flat "manage labels" list without needing every
    label to also have a label_config row (see that table's own comment)."""
    rows = conn.execute("SELECT DISTINCT label_name FROM object_labels ORDER BY label_name COLLATE NOCASE").fetchall()
    return [r["label_name"] for r in rows]


def list_all_known_label_names(conn: sqlite3.Connection) -> list[str]:
    """Every label name known to the system -- the union of labels in use
    (object_labels) and labels with config (label_config). Used for the
    label picker dropdowns so a label created in the manage page appears
    immediately even before it's applied to anything."""
    names = set(list_all_label_names(conn))
    names |= {r["name"] for r in conn.execute("SELECT name FROM label_config").fetchall()}
    return sorted(names, key=str.lower)


def list_tag_names_in_use(conn: sqlite3.Connection) -> list[str]:
    """Phase 2 (label-space rework): the old tag registry is gone --
    labels are the only vocabulary now. Returns all known label names
    (from both object_labels and label_config) so the chip multiselect
    dropdown includes labels created in the manage page before they're
    applied to any object."""
    return list_all_known_label_names(conn)


_LABEL_CONFIG_DEFAULTS: dict[str, Any] = {
    "color": "blue",
    "icon": None,
    "description": None,
    "parent_name": None,
    "label_group": None,
    "generate_space": 0,
    "dashboard_preset_json": None,
    "abbreviation": None,
    "importance": None,
    "urgency_threshold_days": None,
    "is_project": 0,
    "start_date": None,
    "end_date": None,
    "archived_at": None,
    "created_at": None,
}


def get_label_config(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM label_config WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def effective_label_config(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    """A label's config with every default filled in -- a label with zero
    label_config rows (mentioned only via object_labels) still fully
    works, per the table's own "sparse, optional" contract."""
    return _effective_label_config(get_label_config(conn, name), name)


def effective_label_config_ci(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    """Case-insensitive variant of `effective_label_config` -- labels are
    deduplicated case-insensitively (`set_object_labels`), so a config row
    can legitimately sit under casing that differs from the tag text that
    asks about it; callers doing config lookups off raw label strings (e.g.
    routers/timeline.py resolving a block's color/icon from a task's tag)
    use this instead of the exact-match form."""
    row = conn.execute(
        "SELECT * FROM label_config WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    return _effective_label_config(dict(row) if row else None, name)


def _effective_label_config(row: dict[str, Any] | None, name: str) -> dict[str, Any]:
    cfg: dict[str, Any] = dict(row) if row else {"name": name}
    for key, default in _LABEL_CONFIG_DEFAULTS.items():
        cfg.setdefault(key, default)
    cfg["generate_space"] = bool(cfg.get("generate_space"))
    cfg["is_project"] = bool(cfg.get("is_project"))
    # `uid` mirrors `name` -- a label has no surrogate id (its name IS its
    # identity, see the label_config table comment), but templates that
    # used to render a project/space's `.uid` in a link/form field (e.g.
    # `/labels/{{ label.uid }}`) can keep doing exactly that unchanged.
    cfg["uid"] = cfg["name"]
    return cfg


def upsert_label_config(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Partial-field upsert -- any field not present in `row` keeps its
    existing value (or the default, for a brand-new label_config row),
    same "only touch what you're told to" convention as every setter in
    this file."""
    cols = (
        "name", "color", "icon", "description", "parent_name", "label_group",
        "generate_space", "dashboard_preset_json", "abbreviation",
        "importance", "urgency_threshold_days",
        "is_project", "start_date", "end_date", "archived_at",
        "created_at",
    )
    existing = get_label_config(conn, row["name"]) or {}
    data = dict(row)
    if "generate_space" in data:
        data["generate_space"] = 1 if data["generate_space"] else 0
    if "is_project" in data:
        data["is_project"] = 1 if data["is_project"] else 0
    for key, default in _LABEL_CONFIG_DEFAULTS.items():
        data.setdefault(key, existing.get(key, default))
    conn.execute(
        f"INSERT INTO label_config ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
        f"ON CONFLICT(name) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in cols if c != "name"),
        [data.get(c) for c in cols],
    )
    conn.commit()


def list_label_rules(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """{label name: effective label config} for every label -- the resolved
    rules the `important`/`urgent` derived-state filters and the dashboard's
    aggregation service feed to src/derived_state.py. Built once per view
    (never per task) via list_labels, which already returns each label's
    effective config filled with defaults, so an `Exam` label with
    `importance=3` configured contributes that rule to every task carrying
    it."""
    return {cfg["name"]: cfg for cfg in list_labels(conn)}


def list_labels(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every label currently known -- the union of every distinct
    object_labels.label_name and every label_config row (a label can exist
    purely as config with nothing pointing at it yet, or purely as usage
    with no config row at all) -- each with its effective config plus a
    live `usage_count` across every object type. Powers the "manage
    labels" list (routers/labels.py)."""
    names = set(list_all_label_names(conn))
    names |= {r["name"] for r in conn.execute("SELECT name FROM label_config").fetchall()}
    counts: dict[str, int] = {
        r["label_name"]: r["c"]
        for r in conn.execute("SELECT label_name, COUNT(*) c FROM object_labels GROUP BY label_name").fetchall()
    }
    result = []
    for name in sorted(names, key=str.lower):
        cfg = effective_label_config(conn, name)
        cfg["usage_count"] = counts.get(name, 0)
        result.append(cfg)
    return result


def list_space_labels(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every label with generate_space=1 -- the labels that get a
    generated page (routers/labels.py's label_detail)."""
    rows = conn.execute(
        "SELECT * FROM label_config WHERE generate_space = 1 ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [effective_label_config(conn, r["name"]) for r in rows]


def list_project_labels(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every label with is_project=1 -- the Projects page's own listing
    (routers/projects.py). Independent of generate_space: a project can
    also be a Space (or not), the two toggles are orthogonal (§ Project-
    enabled label stack: "the label stays usable across the rest of the
    application")."""
    rows = conn.execute(
        "SELECT * FROM label_config WHERE is_project = 1 ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [effective_label_config(conn, r["name"]) for r in rows]


def find_overlapping_project(
    conn: sqlite3.Connection, name: str, start_date: str | None, end_date: str | None
) -> dict[str, Any] | None:
    """The first other non-archived project whose [start_date, end_date]
    period overlaps this one's, or None. Backs the "projects may not
    overlap another project" rule (§ Project-enabled label stack) -- the
    UI must warn and require the user to resolve the conflict rather than
    silently accept it (see routers/projects.py's create/edit handlers).
    A project missing either date has no bounded period yet, so it can't
    overlap anything; an Archived project is closed history, not part of
    "the same project context" going forward, so it's excluded."""
    if not start_date or not end_date:
        return None
    for cfg in list_project_labels(conn):
        if cfg["name"] == name or cfg.get("archived_at"):
            continue
        other_start, other_end = cfg.get("start_date"), cfg.get("end_date")
        if not other_start or not other_end:
            continue
        if start_date <= other_end and other_start <= end_date:
            return cfg
    return None


def project_status(conn: sqlite3.Connection, cfg: dict[str, Any], today: date | None = None) -> str:
    """Computed lifecycle state -- Open / Pending / Pending Archiving /
    Archived (§ Project lifecycle). Only `archived_at` is stored (the
    user's explicit confirmation); the other three states are derived at
    read time from task completion + end_date, same "computed, not
    stored" treatment as Importance/Urgency, because both inputs change
    underneath the label without the label itself being edited.

    - Archived: `archived_at` is set (explicit user confirmation only --
      neither the end date passing nor every task completing gets here by
      itself).
    - Open: at least one incomplete task, or no tasks at all (a project
      with no work yet hasn't reached a completion point to leave Open
      from).
    - Pending: every task is completed (and there's at least one), but
      today is still before the project's end date -- completed early,
      not yet at its deadline.
    - Pending Archiving: every task is completed and today is on/after
      the end date (or there's no end date) -- ready for the user to
      confirm closure.
    """
    if cfg.get("archived_at"):
        return "Archived"
    tasks = [t for t in list_tasks(conn) if cfg["name"] in (t.get("tags") or [])]
    # ("done", "archived") mirrors routers/tasks.py's DONE_STATUSES --
    # duplicated here rather than imported to avoid a routers -> db ->
    # routers import cycle (db.py has no dependency on routers/*).
    if not tasks or any(t.get("status") not in ("done", "archived") for t in tasks):
        return "Open"
    end_date = cfg.get("end_date")
    if today is None:
        today = date.today()
    if end_date and today < date.fromisoformat(end_date):
        return "Pending"
    return "Pending Archiving"


def archive_project(conn: sqlite3.Connection, name: str) -> None:
    """The explicit user confirmation that closes a project (Pending
    Archiving -> Archived). Never automatic -- see project_status."""
    conn.execute(
        "UPDATE label_config SET archived_at = ? WHERE name = ?",
        (datetime.now(timezone.utc).isoformat(), name),
    )
    conn.commit()


def list_child_labels(conn: sqlite3.Connection, parent_name: str) -> list[dict[str, Any]]:
    """Labels whose parent_name points at `parent_name` -- e.g. a Space's
    nested course/project labels, for a Space page's own nav/listing."""
    rows = conn.execute(
        "SELECT * FROM label_config WHERE parent_name = ? ORDER BY name COLLATE NOCASE", (parent_name,)
    ).fetchall()
    return [effective_label_config(conn, r["name"]) for r in rows]


def rename_label(conn: sqlite3.Connection, old_name: str, new_name: str) -> None:
    """Renames a label everywhere in one transaction: every object_labels
    row that named it, the label_config row itself, and any child label's
    parent_name. A rename that collides (case-insensitively, but not
    identical) with a different existing label merges into it instead
    (mirrors the old tag-rename behavior) rather than raising a
    unique-constraint error a plain form can't act on -- see merge_labels
    below for the actual merge semantics."""
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not old_name or not new_name or old_name == new_name:
        return
    if old_name.lower() == new_name.lower():
        # Case-only rename -- same logical label, just a different display
        # casing -- rewrite everywhere but never treat it as a merge.
        conn.execute("UPDATE object_labels SET label_name = ? WHERE label_name = ?", (new_name, old_name))
        conn.execute("UPDATE label_config SET name = ? WHERE name = ?", (new_name, old_name))
        conn.execute("UPDATE label_config SET parent_name = ? WHERE parent_name = ?", (new_name, old_name))
        conn.commit()
        return
    collision = new_name.lower() in {n.lower() for n in list_all_label_names(conn)} or bool(get_label_config(conn, new_name))
    if collision:
        merge_labels(conn, old_name, new_name)
        return
    conn.execute("UPDATE object_labels SET label_name = ? WHERE label_name = ?", (new_name, old_name))
    conn.execute("UPDATE label_config SET name = ? WHERE name = ?", (new_name, old_name))
    conn.execute("UPDATE label_config SET parent_name = ? WHERE parent_name = ?", (new_name, old_name))
    conn.commit()


def merge_labels(conn: sqlite3.Connection, source_name: str, dest_name: str) -> None:
    """Unions `source_name`'s object_labels membership onto `dest_name`
    (deduplicated -- an object carrying both already is untouched),
    repoints any child label (parent_name == source_name) onto dest, and
    removes source's own label_config row if it had one -- `object_labels`
    rows are the only "membership" a label has, so once those are
    repointed the source label has nothing left pointing at it, same
    "deleting" semantics as every other label removal in this app (§0.1)."""
    if source_name == dest_name:
        return
    rows = conn.execute(
        "SELECT object_type, object_id FROM object_labels WHERE label_name = ?", (source_name,)
    ).fetchall()
    for r in rows:
        conn.execute(
            "INSERT OR IGNORE INTO object_labels (object_type, object_id, label_name) VALUES (?, ?, ?)",
            (r["object_type"], r["object_id"], dest_name),
        )
    conn.execute("DELETE FROM object_labels WHERE label_name = ?", (source_name,))
    conn.execute("UPDATE label_config SET parent_name = ? WHERE parent_name = ?", (dest_name, source_name))
    conn.execute("DELETE FROM label_config WHERE name = ?", (source_name,))
    conn.commit()


def clear_label(conn: sqlite3.Connection, name: str) -> None:
    """The "remove from everything" action (§0.1) -- strips this label
    from every object currently carrying it. Deliberately does NOT delete
    the label_config row -- a stale config row with nothing pointing at it
    is harmless (per the plan), and there is no delete-a-label endpoint at
    all in this app."""
    conn.execute("DELETE FROM object_labels WHERE label_name = ?", (name,))
    conn.commit()


def project_label_for(conn: sqlite3.Connection, object_type: str, object_id: str) -> str | None:
    """The one label treated as "the project" for this object. Deliberately
    a *derived view* over the object's real `object_labels` rows, not a
    separately tracked field -- there is no "this label is special, it's
    THE project" category (see features/architecture.md §0.1/§2: a label
    is a label, full stop). Used uniformly for schedule_class, habit, and
    database -- an earlier version of this rework gave habits/databases
    their own pseudo object_type (`f"{object_type}:project"`) to track
    this separately from real tags; that was a mistake (it made a habit's
    project invisible to any label page's aggregation, and reintroduced
    exactly the "project is a special kind of label" distinction this
    rework exists to remove) and was corrected 2026-08-06 -- see
    set_object_project_label_uniform below for the corresponding write
    path.

    1.3 (Project-enabled label stack) supersedes the old heuristic here:
    a label explicitly marked is_project=1 now wins outright, since a
    label can finally say "I'm the project" instead of it being inferred.
    Falls back to the pre-1.3 heuristic (the attached label whose config
    has generate_space=0 -- a course/list label, not a Space) only when
    nothing attached is explicitly project-enabled, so data written before
    1.3 (nothing has is_project=1 yet) keeps behaving exactly as before
    until the user actually promotes a label to a project."""
    names = sorted(list_labels_for_object(conn, object_type, object_id), key=str.lower)
    configs = {name: get_label_config(conn, name) for name in names}
    for name in names:
        cfg = configs.get(name)
        if cfg and cfg.get("is_project"):
            return name
    for name in names:
        cfg = configs.get(name)
        if not (cfg and cfg.get("generate_space")):
            return name
    return None


def project_label_config_for(
    conn: sqlite3.Connection, object_type: str, object_id: str
) -> dict[str, Any] | None:
    """The project label's *effective config* (every default filled in, so
    `name`/`icon`/`color` are all present) for an object, or None if it has
    no project label. Thin wrapper over `project_label_for` +
    `effective_label_config` so a planning grid's "Unscheduled work" panel
    can render the project pill (icon + name, 2026-08-14) without
    re-deriving the lookup at each of its three call sites. The returned
    dict is the label's config, not a name string -- callers that only
    needed the name (the older panel items) can read `["name"]` off it."""
    name = project_label_for(conn, object_type, object_id)
    if name is None:
        return None
    return effective_label_config(conn, name)


def set_object_project_label_uniform(conn: sqlite3.Connection, object_type: str, object_id: str, label_name: str | None) -> None:
    """Write path for project_label_for: replace whichever non-Space label
    this object currently carries with `label_name` (or just remove it, if
    None/""), leaving any Space labels (generate_space=1) already on the
    object untouched -- same rule set_schedule_class_project has always
    used, now shared by habit/database too instead of each having its own
    variant."""
    current = project_label_for(conn, object_type, object_id)
    if current:
        remove_object_label(conn, object_type, object_id, current)
    if label_name:
        add_object_label(conn, object_type, object_id, label_name)


def _apply_tags_and_project(
    conn: sqlite3.Connection,
    object_type: str,
    object_id: str,
    tags: list[str] | None,
    project_uid: str | None,
    has_project_key: bool,
) -> None:
    """Shared write path for upsert_habit/upsert_database: `tags` and
    `project_uid` are two form fields for the same underlying thing (a
    project is just a label -- §0.1), so when both arrive in the same call
    the project is folded into the tag set and the whole thing is applied
    as one full replace via set_object_labels -- no separate "guess which
    tag used to be the project and remove it" step needed, which is both
    simpler and avoids a real bug an earlier version of this function had
    (2026-08-06: fixed after it corrupted unrelated tags any time a form
    submitted `tags` and a blank `project_uid` together, which routers/
    habits.py's create/edit forms always do). Only a genuine partial
    update -- `project_uid` changing with `tags` not sent at all -- falls
    back to set_object_project_label_uniform's targeted swap."""
    if tags is not None:
        final_tags = list(dict.fromkeys(tags))
        if has_project_key and project_uid and project_uid not in final_tags:
            final_tags.append(project_uid)
        set_object_labels(conn, object_type, object_id, final_tags)
    elif has_project_key:
        set_object_project_label_uniform(conn, object_type, object_id, project_uid)


# --------------------------------------------------------------------- #
# Habits + habit entries -- local-only, see the `habits`/`habit_entries`
# CREATE TABLE comments above for the full rationale.
# --------------------------------------------------------------------- #

_HABIT_COLS = (
    "uid", "name", "description", "color", "icon", "target_per_day",
    "archived_at", "created_at", "updated_at",
)


def upsert_habit(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Full-row upsert. Phase 2 (label-space rework) dropped this table's
    own `tags_json`/`project_uid` columns -- a habit's tags are now
    `object_labels` rows (object_type='habit'), written the same way
    upsert_task/upsert_event handle `tags` (see set_object_labels). Its
    "project" is just whichever of those same labels isn't a Space (see
    project_label_for/set_object_project_label_uniform) -- there is no
    separate tracking for it, corrected 2026-08-06 (see project_label_for's
    docstring for why an earlier version's pseudo-object_type approach was
    wrong). `tags` is applied first so a caller passing both `tags` and
    `project_uid` in the same call gets the project label folded into the
    final tag set either way."""
    data = dict(row)
    data.setdefault("description", "")
    data.setdefault("color", "blue")
    data.setdefault("target_per_day", 1)
    tags = data.pop("tags", None)
    project_uid = data.pop("project_uid", None)
    has_project_key = "project_uid" in row
    cols = _HABIT_COLS
    conn.execute(
        f"INSERT INTO habits ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
        f"ON CONFLICT(uid) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid"),
        [data.get(c) for c in cols],
    )
    _apply_tags_and_project(conn, "habit", data["uid"], tags, project_uid, has_project_key)
    conn.commit()


def _habit_row_to_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["tags"] = list_labels_for_object(conn, "habit", d["uid"])
    d["project_uid"] = project_label_for(conn, "habit", d["uid"])
    return d


def get_habit(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM habits WHERE uid = ?", (uid,)).fetchone()
    return _habit_row_to_dict(conn, row) if row else None


def list_habits(
    conn: sqlite3.Connection, include_archived: bool = False, project_uid: str | None = None
) -> list[dict[str, Any]]:
    query = "SELECT * FROM habits"
    clauses = []
    params: list[Any] = []
    if not include_archived:
        clauses.append("archived_at IS NULL")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY name COLLATE NOCASE"
    rows = conn.execute(query, params).fetchall()
    habits = [_habit_row_to_dict(conn, r) for r in rows]
    if project_uid:
        # `project_uid` here is a label name (see
        # _habit_row_to_dict/get_object_project_label) -- kept as the same
        # parameter name so every existing caller (routers/habits.py,
        # routers/dashboard.py) needed no renaming, just a different
        # meaning for the same string.
        habits = [h for h in habits if h.get("project_uid") == project_uid]
    return habits


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
    conn.execute("DELETE FROM object_labels WHERE object_type = 'habit' AND object_id = ?", (uid,))
    conn.execute("DELETE FROM object_labels WHERE object_type = 'habit:project' AND object_id = ?", (uid,))
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


def upsert_task_completion(
    conn: sqlite3.Connection, task_uid: str, due_date: str, completed_at: str, value: float = 1
) -> None:
    """Records (or updates) that a recurring task was completed on `due_date`
    -- the row that feeds its heatmap/streak. `completed_at` is when the
    check-off actually happened (usually today), `due_date` the pattern's
    day being checked off. `value` (2026-08-08) is only meaningful for a
    habit-labeled task with target_per_day > 1 -- every other caller
    (the plain recurring-task complete_task path) leaves it at the
    default 1, same as before this column existed."""
    conn.execute(
        "INSERT INTO task_completions (task_uid, due_date, completed_at, value) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(task_uid, due_date) DO UPDATE SET completed_at=excluded.completed_at, value=excluded.value",
        (task_uid, due_date, completed_at, value),
    )
    conn.commit()


def delete_task_completion(conn: sqlite3.Connection, task_uid: str, due_date: str) -> None:
    conn.execute("DELETE FROM task_completions WHERE task_uid = ? AND due_date = ?", (task_uid, due_date))
    conn.commit()


def get_task_completion(conn: sqlite3.Connection, task_uid: str, due_date: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM task_completions WHERE task_uid = ? AND due_date = ?", (task_uid, due_date)
    ).fetchone()
    return dict(row) if row else None


def list_task_completions(conn: sqlite3.Connection, task_uid: str | None = None) -> list[dict[str, Any]]:
    """All completion rows, optionally scoped to one task. The backup
    (export.data.json) round-trips the whole table; the tasks page scopes
    to a single recurring task's history."""
    if task_uid is None:
        rows = conn.execute("SELECT * FROM task_completions ORDER BY task_uid, due_date ASC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM task_completions WHERE task_uid = ? ORDER BY due_date ASC", (task_uid,)
        ).fetchall()
    return [dict(r) for r in rows]






def habit_entries_by_date(
    conn: sqlite3.Connection, habit_uid: str, start: str | None = None, end: str | None = None
) -> dict[str, float]:
    """date -> value, for the heatmap builder (habits.py's _heatmap_weeks)
    and streak computation -- a plain dict lookup is simpler for both
    callers than re-scanning the row list repeatedly."""
    return {r["date"]: r["value"] for r in list_habit_entries(conn, habit_uid, start, end)}


# 2026-08-07: the Custom databases accessor functions (upsert_database/
# get_database/list_databases/archive_database/unarchive_database/
# delete_database, plus the column/row-level upsert_database_column/
# get_database_column/list_database_columns/next_column_position/
# delete_database_column/upsert_database_row/get_database_row/
# list_database_rows/next_row_position/delete_database_row/
# set_database_row_value) that used to live here are all gone along with
# the `databases`/`database_columns`/`database_rows` tables -- see the
# SCHEMA_SQL comment above and features/architecture.md's Grades/
# Databases removal note. `project_label_for`/`set_object_project_label_
# uniform` (above) are unaffected -- they're generic over `object_type`
# and were never database-specific.


# --------------------------------------------------------------------- #
# Dashboard widgets (Phase 8) -- local-only, see the `dashboard_widgets`
# CREATE TABLE comment above.
# --------------------------------------------------------------------- #


def upsert_dashboard_widget(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    data["config_json"] = json.dumps(data.get("config") or {})
    # `label_name` (Phase 2, label-space rework) is the single page-scope
    # column that replaced `space_uid`/`project_uid` -- NULL means Home, a
    # set value is the label whose generated page this widget belongs to.
    # Accepts `space_uid`/`project_uid` as aliases (whichever is set wins)
    # so callers that haven't been renamed yet still work.
    if "label_name" not in data:
        data["label_name"] = data.get("project_uid") or data.get("space_uid")
    # group_uid (2026-08-02 stacking) has to be in this explicit column
    # list -- ON CONFLICT UPDATE only touches columns named here, so
    # leaving it out wouldn't error, it would just silently never persist
    # that part of a widget's identity.
    cols = ("uid", "type", "title", "config_json", "position", "created_at", "group_uid", "label_name")
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
    # space_uid/project_uid (2026-08-05 and earlier) mirror label_name for
    # any caller/template not yet updated to the single column -- which
    # *kind* of page label_name renders (Space vs. plain label page) is
    # derived at read time from label_config.generate_space, not stored
    # redundantly here.
    d.setdefault("space_uid", d.get("label_name"))
    d.setdefault("project_uid", d.get("label_name"))
    return d


def get_dashboard_widget(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM dashboard_widgets WHERE uid = ?", (uid,)).fetchone()
    return _widget_row_to_dict(row) if row else None


def list_dashboard_widgets(
    conn: sqlite3.Connection, label_name: str | None = None,
    space_uid: str | None = None, project_uid: str | None = None,
) -> list[dict[str, Any]]:
    """Widgets for one page's grid -- Home (label_name=None, the default)
    or a specific label's generated page (label_name set). Includes both
    top-level widgets and stack members (callers that need to tell them
    apart filter on group_uid themselves -- see _build_widget_contexts).
    Use list_all_dashboard_widgets below instead when you need to look up
    a widget/stack by uid or group_uid without knowing which page it's on
    (e.g. dissolving a stack -- its uid is globally unique regardless of
    which page's grid it's in). `space_uid`/`project_uid` are accepted as
    aliases for `label_name` (pre-Phase-2 callers) -- whichever is set
    wins if more than one is passed."""
    label_name = label_name or project_uid or space_uid
    rows = conn.execute(
        "SELECT * FROM dashboard_widgets WHERE label_name IS ? ORDER BY position ASC", (label_name,)
    ).fetchall()
    return [_widget_row_to_dict(r) for r in rows]


def list_all_dashboard_widgets(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every widget on every page (Home + every label's page), regardless
    of label_name -- see list_dashboard_widgets' docstring for when to
    reach for this instead."""
    rows = conn.execute("SELECT * FROM dashboard_widgets ORDER BY position ASC").fetchall()
    return [_widget_row_to_dict(r) for r in rows]


def next_dashboard_widget_position(
    conn: sqlite3.Connection, label_name: str | None = None, _legacy_project_uid: str | None = None
) -> float:
    # Scoped to top-level widgets (group_uid IS NULL) on this one page --
    # always "the position that puts a widget at the end of *this page's*
    # top-level order" (a brand-new widget via add_widget, or one just
    # popped out of a stack via unstack_widget), never a stack member's
    # own position or another page's ordering. `_legacy_project_uid`
    # accepts a second positional arg so a pre-Phase-2 call site passing
    # (space_uid, project_uid) keeps working -- only the first non-empty
    # of the two is used.
    label_name = label_name or _legacy_project_uid
    max_pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) FROM dashboard_widgets WHERE group_uid IS NULL AND label_name IS ?",
        (label_name,),
    ).fetchone()[0]
    return max_pos + 1


# --------------------------------------------------------------------- #
# Published Lists (Phase 6, label-space rework) -- CRUD only. The boolean
# filter evaluator and the materializer that actually pushes rows to
# Radicale live in src/published_lists.py (pure logic + bridge I/O, kept
# out of this module the same way ical_rows.py/vcard_rows.py stayed
# separate from db.py's own CRUD).
# --------------------------------------------------------------------- #


def upsert_published_list(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    if "label_filter" in data:
        data["label_filter_json"] = json.dumps(data.pop("label_filter"))
    cols = [
        "id", "name", "entity_type", "label_filter_json",
        "radicale_collection_path", "sync_direction",
        "last_materialized_at", "created_at",
    ]
    data.setdefault("sync_direction", "read_only")
    values = [data.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    conn.execute(
        f"INSERT INTO published_lists ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )
    conn.commit()


def _published_list_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["label_filter"] = json.loads(d.pop("label_filter_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["label_filter"] = {"all": [], "any": [], "none": []}
    return d


def get_published_list(conn: sqlite3.Connection, list_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM published_lists WHERE id = ?", (list_id,)).fetchone()
    return _published_list_row_to_dict(row) if row else None


def list_published_lists(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM published_lists ORDER BY name COLLATE NOCASE").fetchall()
    return [_published_list_row_to_dict(r) for r in rows]


def set_published_list_materialized_at(conn: sqlite3.Connection, list_id: str, when: str) -> None:
    conn.execute(
        "UPDATE published_lists SET last_materialized_at = ? WHERE id = ?", (when, list_id)
    )
    conn.commit()


def delete_published_list(conn: sqlite3.Connection, list_id: str) -> None:
    """A real delete -- see the CREATE TABLE comment above. Only removes
    this row; the caller (routers/published_lists.py) is responsible for
    also tearing down the actual Radicale collection via the bridge,
    same division of responsibility as delete_calendar_collection/
    delete_addressbook_collection used to have."""
    conn.execute("DELETE FROM published_lists WHERE id = ?", (list_id,))
    conn.commit()


def delete_dashboard_widget(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM dashboard_widgets WHERE uid = ?", (uid,))
    conn.commit()


def swap_dashboard_widget_positions(conn: sqlite3.Connection, uid_a: str, uid_b: str) -> None:
    """Same swap-with-neighbor reorder primitive the now-removed
    routers/databases.py's move_column used -- simplest correct "move up"/
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


# --------------------------------------------------------------------- #
# User profile + page banners (2026-08-09) -- see routers/settings.py's
# profile-photo routes and routers/banners.py. Both live in app_meta,
# same store as the existing user-profile field DISPLAY_NAME_KEY
# ("dashboard_display_name", routers/dashboard.py). app_meta's module
# comment says it's "deliberately NOT a place for user-facing settings",
# but display name already lives here, and splitting one user's identity
# (name + picture) across two stores would be worse than the minor
# comment drift keeping them together -- a profile photo and a per-page
# banner are each one opaque blob, exactly what a key/value store holds.
# --------------------------------------------------------------------- #

PROFILE_PHOTO_B64_KEY = "profile_photo_b64"
PROFILE_PHOTO_TYPE_KEY = "profile_photo_type"
_PAGE_BANNER_PREFIX = "page_banner_"


def get_profile_photo(conn: sqlite3.Connection) -> dict[str, str] | None:
    """The app user's own profile picture -- {photo_b64, photo_type}
    (same shape as a contact's photo_b64/photo_type columns), or None when
    none is set. Unlike a contact's photo there's no vCard anywhere --
    this is app-level identity (Settings > General)."""
    b64 = get_app_meta(conn, PROFILE_PHOTO_B64_KEY)
    if not b64:
        return None
    return {
        "photo_b64": b64,
        "photo_type": get_app_meta(conn, PROFILE_PHOTO_TYPE_KEY) or "jpeg",
    }


def set_profile_photo(conn: sqlite3.Connection, photo_b64: str, photo_type: str) -> None:
    set_app_meta(conn, PROFILE_PHOTO_B64_KEY, photo_b64)
    set_app_meta(conn, PROFILE_PHOTO_TYPE_KEY, photo_type)


def clear_profile_photo(conn: sqlite3.Connection) -> None:
    """Both keys are cleared ("" stored, not deleted -- same "an existing
    key keeps existing, just empty" convention every other app_meta
    unset in this app uses), so a cleared photo reads as None."""
    set_app_meta(conn, PROFILE_PHOTO_B64_KEY, "")
    set_app_meta(conn, PROFILE_PHOTO_TYPE_KEY, "")


def _page_banner_key(page_key: str) -> str:
    """app_meta key for one dashboard page's banner -- "" is Home, any
    other value is that label's generated page (/labels/{name}). Label
    names are opaque strings here (kept raw in the key itself); the
    routers own the page-key mapping, this is just key assembly."""
    return f"{_PAGE_BANNER_PREFIX}{page_key}"


def get_page_banner(conn: sqlite3.Connection, page_key: str) -> dict[str, Any] | None:
    """One dashboard page's banner, or None when unset. Stored as a single
    JSON blob; returns only well-formed {kind: 'remote'|'upload', ...}
    dicts -- anything corrupt (e.g. an interrupted write) reads as None
    rather than crashing the page render. See routers/banners.py for the
    two kinds; templates only read image_url/image_b64/image_type/alt/
    version, so the optional source_url attribution is harmless extra.

    2026-08-10: upload banners also carry a short content hash as
    `version` -- it cache-busts the /banners/image URL in _page_banner.html
    so the browser can hold a banner at max-age=immutable without ever
    showing a stale one after a re-upload. New uploads store it up front
    (routers/banners.py's upload_banner); banners stored before that get
    it backfilled here exactly once (the hash is idempotent, so writing it
    into app_meta is a cheap one-time write, not a per-render cost)."""
    raw = get_app_meta(conn, _page_banner_key(page_key))
    if not raw:
        return None
    try:
        banner = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(banner, dict) or banner.get("kind") not in ("remote", "upload"):
        return None
    if banner.get("kind") == "upload" and not banner.get("version"):
        b64 = banner.get("image_b64") or ""
        banner["version"] = hashlib.md5(b64.encode("ascii")).hexdigest()[:12]
        set_app_meta(conn, _page_banner_key(page_key), json.dumps(banner))
    return banner


def set_page_banner(conn: sqlite3.Connection, page_key: str, banner: dict[str, Any]) -> None:
    set_app_meta(conn, _page_banner_key(page_key), json.dumps(banner))


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
    "note": "notes",
}

ENTITY_SYNC_FIELDS: dict[str, set[str]] = {
    "task": {
        "title", "description", "start_at", "due_at", "status", "progress",
        "recurrence", "exdates_json", "completed_at", "target_per_day",
        "created_at", "updated_at", "deleted_at",
    },
    "event": {
        "title", "description", "start_at", "end_at", "all_day", "location",
        "meeting_url", "status", "recurrence", "exdates_json", "reminders_json",
        "holiday_calendar", "exclude_saturday", "exclude_sunday",
        "created_at", "updated_at", "deleted_at",
    },
    "contact": {
        "full_name", "title", "org", "phone", "email", "address", "notes",
        "photo_b64", "photo_type", "created_at", "updated_at", "deleted_at",
    },
    "note": {
        "content", "created_at", "updated_at", "deleted_at",
    },
}


# --------------------------------------------------------------------- #
# The server as a sync author (2026-08-18 follow-up -- the fix for the
# "offline shows nothing" bug). The sync protocol delivers changes to a
# device *only* through field_versions, and field_versions was only ever
# written when a device pushed an op. The ordinary rendered web UI writes
# to the same tables through db.upsert_*/delete_* -- those writes never
# entered field_versions, so a fresh device's pull returned an empty delta
# and its local mirror stayed empty forever, leaving the /offline shell
# with nothing to render ("Nothing to load right now" on every page).
#
# The fix makes the server a first-class participant: every task/event/
# contact write it performs on behalf of the plain UI is recorded into
# field_versions under a server-minted HLC (device id "server"), exactly
# as if a device had pushed it. A device's pull then delivers it like any
# other change. The server stays a passive relay for device ops (the §5
# ledger still guarantees a retried push replays instead of re-applying);
# it is only an *author* for its own UI writes.
#
# The server HLC clock lives in app_meta and is merged forward past every
# device op the server applies (offline_sync.apply_op calls
# merge_server_hlc), so per §3 the server's own next write is guaranteed
# to sort strictly after anything it has already observed -- an ordinary
# online edit to a field a device last wrote offline genuinely outranks
# that device's write when the device next pushes it. Same read-modify-
# write shape (and same benign concurrency race under two requests in the
# same millisecond) as the existing sync_data_version counter just above.
# --------------------------------------------------------------------- #

SERVER_DEVICE_ID = "server"
_SERVER_HLC_KEY = "server_hlc_clock"


def get_server_hlc_clock(conn: sqlite3.Connection) -> tuple[int, int] | None:
    """The server's own HLC clock as (physical, logical) -- the stored
    state merge_server_hlc/mint_server_hlc read-modify-write. None before
    the server has ever minted or merged a write."""
    raw = get_app_meta(conn, _SERVER_HLC_KEY)
    if not raw:
        return None
    try:
        clock = json.loads(raw)
        return (clock[0], clock[1])
    except (TypeError, ValueError, IndexError):
        return None


def _put_server_hlc_clock(conn: sqlite3.Connection, clock: tuple[int, int]) -> None:
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_SERVER_HLC_KEY, json.dumps([clock[0], clock[1]])),
    )


def merge_server_hlc(conn: sqlite3.Connection, observed: tuple[int, int, str]) -> None:
    """§3's receive-side HLC merge, applied whenever the server applies a
    device op (offline_sync.apply_op): advance the server's clock past
    what it just observed so its own next minted write outranks it."""
    prev = get_server_hlc_clock(conn) or (0, 0)
    if observed[0] == prev[0]:
        logical = max(prev[1], observed[1]) + 1
    elif observed[0] > prev[0]:
        logical = observed[1] + 1
    else:
        logical = prev[1]
    _put_server_hlc_clock(conn, (max(prev[0], observed[0]), logical))


def mint_server_hlc(conn: sqlite3.Connection) -> tuple[int, int, str]:
    """Mints a fresh server HLC -- the timestamp every server-written field
    change is recorded under. Physical time never goes backwards (the
    clock is monotonic across the process's own writes and every device op
    it has observed via merge_server_hlc), and two server writes within
    the same millisecond get distinct logical values."""
    prev = get_server_hlc_clock(conn) or (0, 0)
    now = int(time.time() * 1000)
    if prev[0] >= now:
        physical, logical = prev[0], prev[1] + 1
    else:
        physical, logical = now, 0
    _put_server_hlc_clock(conn, (physical, logical))
    return (physical, logical, SERVER_DEVICE_ID)


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


def record_server_sync_write(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_uid: str,
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    hlc: tuple[int, int, str] | None = None,
) -> None:
    """Records a server-side UI write into field_versions (the server-as-
    author mechanism above). Diffs the entity's sync-whitelist columns
    before vs. after the write and records each one that actually changed
    under a single server HLC -- recording every column unconditionally
    would overwrite a device's newer HLC on fields the server didn't touch
    (see the module comment), so only real changes move the field HLCs.
    Bumps the sync data version iff anything was recorded, exactly like a
    device push that changed state. `hlc` lets a caller seed with a known
    clock value instead of minting one (tests seeding pre-sync data)."""
    fields = ENTITY_SYNC_FIELDS.get(entity_type)
    if not fields or not current:
        return
    changed = [
        f
        for f in fields
        if f in current and (previous or {}).get(f) != current[f]
    ]
    if not changed:
        return
    if hlc is None:
        hlc = mint_server_hlc(conn)
    for f in changed:
        set_field_hlc(conn, entity_type, entity_uid, f, hlc)
    bump_sync_data_version(conn)


def record_server_delete(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_uid: str,
    *,
    hlc: tuple[int, int, str] | None = None,
) -> None:
    """Records a server-side hard delete as a `deleted_at` field_versions
    entry -- the same tombstone a device's delete op creates, but with no
    stored value (the entity row is physically removed, unlike a sync
    soft-delete). offline_sync.pull() synthesizes a truthy deleted_at for
    a missing row (see _current_field_value), so a device's mirror learns
    "this entity is gone" and hides it. `hlc` lets a caller seed with a
    known clock value instead of minting one."""
    if hlc is None:
        hlc = mint_server_hlc(conn)
    set_field_hlc(conn, entity_type, entity_uid, "deleted_at", hlc)
    bump_sync_data_version(conn)


def record_work_allocation_flag(
    conn: sqlite3.Connection, event_uid: str, *, hlc: tuple[int, int, str] | None = None
) -> None:
    """Records a work-allocation event's `is_work_allocation` sync flag into
    field_versions, so a device's pull can deliver it. The flag is not an
    `events` column -- it lives in `event_task_relations.is_work_allocation`
    (see create_work_allocation) -- so record_server_sync_write's plain
    column diff can never see it; it gets its own field_versions entry
    here. The value itself is never stored: offline_sync.pull() reads it
    back from the relation table (offline_sync._current_field_value's
    special case), exactly as the deleted-at-tombstone value is synthesized
    rather than stored. Only ever recorded for work allocations -- a
    regular event has no flag entry, and a pull simply never mentions it,
    which the mirror reads as "not a work allocation." `hlc` lets a caller
    seed with a known clock value instead of minting one."""
    if hlc is None:
        hlc = mint_server_hlc(conn)
    set_field_hlc(conn, "event", event_uid, "is_work_allocation", hlc)
    bump_sync_data_version(conn)


# The sync-whitelist columns for each entity, as a fixed ORDERED list --
# the diff/read substrate for the server-as-author recording above (a
# stable ordering keeps the generated SELECTs deterministic).
_TASK_SYNC_COLUMNS = sorted(ENTITY_SYNC_FIELDS["task"])
_EVENT_SYNC_COLUMNS = sorted(ENTITY_SYNC_FIELDS["event"])
_CONTACT_SYNC_COLUMNS = sorted(ENTITY_SYNC_FIELDS["contact"])


# One-time backfill (2026-08-18) -- the same "offline shows nothing" fix,
# applied to data that already existed before the server-as-author change.
# New server writes now record themselves into field_versions going
# forward, but rows created *before* this fix have no entries at all, so
# without a backfill a device's first pull would still return an empty
# delta for them and the offline shell would still show "Nothing to load
# right now." Runs at the end of init_schema, gated on an app_meta marker
# so it happens exactly once on a real installation.
_SERVER_WRITES_BACKFILLED_KEY = "sync_server_writes_backfilled"


def backfill_server_sync_writes(conn: sqlite3.Connection) -> None:
    """One-time: records every existing task/event/contact's sync-whitelist
    columns into field_versions under a single server HLC, so a device's
    very first pull delivers the full pre-existing dataset. `INSERT OR
    IGNORE` (the field_versions primary key is entity_type+entity_uid+
    field_name) means a field a device has already synced keeps its own
    HLC untouched -- the backfill only ever adds *missing* entries and
    never overwrites device state. Idempotent: the app_meta marker is set
    even when there was nothing to backfill (a fresh database), so the
    scan never re-runs; the data version only moves when something was
    actually inserted."""
    if get_app_meta(conn, _SERVER_WRITES_BACKFILLED_KEY):
        return
    hlc = mint_server_hlc(conn)
    inserted = 0
    for entity_type, table in ENTITY_TABLES.items():
        uids = conn.execute(f"SELECT uid FROM {table}").fetchall()
        for (uid,) in uids:
            for field_name in ENTITY_SYNC_FIELDS[entity_type]:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO field_versions "
                    "(entity_type, entity_uid, field_name, hlc_physical, hlc_logical, hlc_device_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (entity_type, uid, field_name, hlc[0], hlc[1], hlc[2]),
                )
                inserted += cur.rowcount
    set_app_meta(conn, _SERVER_WRITES_BACKFILLED_KEY, "1")
    if inserted:
        bump_sync_data_version(conn)


# One-time backfill of the work-allocation sync flag (2026-08-18, the
# offline "Upcoming" view). The main sync_server_writes_backfilled marker
# above may already be set on a real install -- it covers the entity
# columns, but a work allocation's flag lives in event_task_relations, not
# an `events` column, so its field_versions entry needs a separate one-time
# pass, gated on its own marker.
_WORK_ALLOCATION_FLAGS_BACKFILLED_KEY = "sync_work_allocation_flags_backfilled"


def backfill_work_allocation_flags(conn: sqlite3.Connection) -> None:
    """One-time: records an `is_work_allocation` field_versions entry for
    every pre-existing work-allocation event (an event_task_relations row
    with is_work_allocation=1), so a device's pull -- which only ever
    learns the flag through field_versions -- sees pre-existing scheduled
    work sessions as work allocations in its local mirror. `INSERT OR
    IGNORE` (field_versions' primary key is entity_type+entity_uid+
    field_name) means a field a device has already synced keeps its own
    HLC untouched, same contract as backfill_server_sync_writes. Only the
    =1 rows get an entry: a relation with is_work_allocation=0 is an
    ordinary task/event link, and a regular event having *no* flag entry
    is exactly what a pull expects to mean "not a work allocation."
    Idempotent via its own app_meta marker, and only bumps the data
    version when something was actually inserted (so a device's round-skip
    pre-check notices the new flags)."""
    if get_app_meta(conn, _WORK_ALLOCATION_FLAGS_BACKFILLED_KEY):
        return
    hlc = mint_server_hlc(conn)
    inserted = 0
    rows = conn.execute(
        "SELECT event_uid FROM event_task_relations WHERE is_work_allocation = 1"
    ).fetchall()
    for (event_uid,) in rows:
        cur = conn.execute(
            "INSERT OR IGNORE INTO field_versions "
            "(entity_type, entity_uid, field_name, hlc_physical, hlc_logical, hlc_device_id) "
            "VALUES ('event', ?, 'is_work_allocation', ?, ?, ?)",
            (event_uid, hlc[0], hlc[1], hlc[2]),
        )
        inserted += cur.rowcount
    set_app_meta(conn, _WORK_ALLOCATION_FLAGS_BACKFILLED_KEY, "1")
    if inserted:
        bump_sync_data_version(conn)


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


def get_sync_applied_op(conn: sqlite3.Connection, op_id: str) -> dict[str, Any] | None:
    """§5's idempotency lookup -- a cached result means this exact op_id
    was already applied and should not be re-applied on a retried push."""
    row = conn.execute(
        "SELECT result_json FROM sync_applied_ops WHERE op_id = ?", (op_id,)
    ).fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def record_sync_applied_op(
    conn: sqlite3.Connection,
    op_id: str,
    entity_type: str,
    entity_uid: str,
    result: dict[str, Any],
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sync_applied_ops (op_id, entity_type, entity_uid, result_json, applied_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (op_id, entity_type, entity_uid, json.dumps(result), datetime.now(timezone.utc).isoformat()),
    )


def get_sync_device(conn: sqlite3.Connection, device_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT device_id, last_pushed_physical, last_pushed_logical, last_pushed_device_id, "
        "last_pulled_physical, last_pulled_logical, last_pulled_device_id, last_seen_at "
        "FROM sync_devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "device_id": row[0],
        "last_pushed_hlc": (row[1], row[2], row[3]) if row[1] is not None else None,
        "last_pulled_hlc": (row[4], row[5], row[6]) if row[4] is not None else None,
        "last_seen_at": row[7],
    }


# 2026-08-17 follow-up -- the server-side "database hash" a device
# compares against its own last-synced copy before deciding whether a
# sync round is needed at all. A monotonic counter over applied sync
# writes, not a literal hash of the entity tables: the sync protocol can
# only ever *deliver* changes that arrived through the sync path
# (field_versions), so a counter that moves exactly when a sync write
# actually lands is the only signal whose "did it change" answer matches
# what a pull would return. A whole-DB hash would also move on ordinary
# server-rendered app edits (which never enter field_versions) and would
# send every device into a pull that returns nothing new, forever.
# Stored in app_meta, same "sync bookkeeping is just a key/value row"
# convention as the sync-GC settings (data_health.py) -- no schema change.
_SYNC_DATA_VERSION_KEY = "sync_data_version"


def get_sync_data_version(conn: sqlite3.Connection) -> int:
    """The server's current data version -- 0 before any sync write has
    ever been applied. Compared client-side (offline_sync_client.js's
    round-skip pre-check) against the version the device saved the last
    time it pulled successfully."""
    raw = get_app_meta(conn, _SYNC_DATA_VERSION_KEY)
    return int(raw) if raw else 0


def bump_sync_data_version(conn: sqlite3.Connection) -> int:
    """Advances the version by one and commits. Called once per batch
    (offline_sync.apply_batch) when at least one op in it actually
    changed server state, and by purge_expired when GC physically removes
    anything -- so the version changes iff a pull would return something
    new (or force a resync), and never regresses."""
    version = get_sync_data_version(conn) + 1
    set_app_meta(conn, _SYNC_DATA_VERSION_KEY, str(version))
    return version


def touch_sync_device(
    conn: sqlite3.Connection,
    device_id: str,
    last_pushed_hlc: tuple[int, int, str] | None = None,
    last_pulled_hlc: tuple[int, int, str] | None = None,
) -> None:
    """Upserts `sync_devices`. Either HLC arg may be omitted (a push-only
    or pull-only round keeps the other field as it already was) -- uses
    `COALESCE(excluded.x, sync_devices.x)` so a NULL passed through
    `excluded` (arg omitted) doesn't clobber a previously-recorded value."""
    now = datetime.now(timezone.utc).isoformat()
    pushed = last_pushed_hlc or (None, None, None)
    pulled = last_pulled_hlc or (None, None, None)
    conn.execute(
        "INSERT INTO sync_devices (device_id, last_pushed_physical, last_pushed_logical, "
        "last_pushed_device_id, last_pulled_physical, last_pulled_logical, last_pulled_device_id, "
        "last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(device_id) DO UPDATE SET "
        "last_pushed_physical=COALESCE(excluded.last_pushed_physical, sync_devices.last_pushed_physical), "
        "last_pushed_logical=COALESCE(excluded.last_pushed_logical, sync_devices.last_pushed_logical), "
        "last_pushed_device_id=COALESCE(excluded.last_pushed_device_id, sync_devices.last_pushed_device_id), "
        "last_pulled_physical=COALESCE(excluded.last_pulled_physical, sync_devices.last_pulled_physical), "
        "last_pulled_logical=COALESCE(excluded.last_pulled_logical, sync_devices.last_pulled_logical), "
        "last_pulled_device_id=COALESCE(excluded.last_pulled_device_id, sync_devices.last_pulled_device_id), "
        "last_seen_at=excluded.last_seen_at",
        (device_id, *pushed, *pulled, now),
    )


def list_sync_devices(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """1.8 slice 6 -- every device that has ever pushed or pulled, most
    recently seen first. `data_health.health_summary`'s own "sync" field
    was a fixed `{"configured": False}` placeholder through slice 5
    (open.md's own note: "the field exists now so the page's shape doesn't
    change once it does") -- this is what that placeholder needed once a
    real sync engine (routers/sync_api.py, called by static/offline_sync_
    client.js) actually exists to populate `sync_devices` rows."""
    rows = conn.execute(
        "SELECT device_id, last_pushed_physical, last_pushed_logical, last_pushed_device_id, "
        "last_pulled_physical, last_pulled_logical, last_pulled_device_id, last_seen_at "
        "FROM sync_devices ORDER BY last_seen_at DESC"
    ).fetchall()
    return [
        {
            "device_id": row[0],
            "last_pushed_hlc": (row[1], row[2], row[3]) if row[1] is not None else None,
            "last_pulled_hlc": (row[4], row[5], row[6]) if row[4] is not None else None,
            "last_seen_at": row[7],
        }
        for row in rows
    ]


# --------------------------------------------------------------------- #
# 1.8 slice 2 -- sync_conflicts (§§7b/c, 9). See the table's own CREATE
# TABLE comment for what it's for. Plain CRUD helpers only -- the actual
# decision of *when* a conflict is worth recording lives in
# src/offline_sync.py, same layering as the field-HLC shadow store above.
# --------------------------------------------------------------------- #


def _hlc_to_str(hlc: tuple[int, int, str]) -> str:
    return f"{hlc[0]}:{hlc[1]}:{hlc[2]}"


def create_sync_conflict(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_uid: str,
    field_name: str,
    losing_value: Any,
    losing_hlc: tuple[int, int, str],
    winning_hlc: tuple[int, int, str],
) -> str:
    import uuid

    conflict_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sync_conflicts (id, entity_type, entity_uid, field_name, losing_value, "
        "losing_hlc, winning_hlc, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            conflict_id, entity_type, entity_uid, field_name,
            None if losing_value is None else str(losing_value),
            _hlc_to_str(losing_hlc), _hlc_to_str(winning_hlc),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return conflict_id


def get_sync_conflict(conn: sqlite3.Connection, conflict_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM sync_conflicts WHERE id = ?", (conflict_id,)).fetchone()
    return dict(row) if row else None


def list_sync_conflicts(conn: sqlite3.Connection, unresolved_only: bool = True) -> list[dict[str, Any]]:
    query = "SELECT * FROM sync_conflicts"
    if unresolved_only:
        query += " WHERE resolved_at IS NULL"
    query += " ORDER BY created_at DESC"
    return [dict(r) for r in conn.execute(query).fetchall()]


def resolve_sync_conflict(conn: sqlite3.Connection, conflict_id: str) -> None:
    """Dismiss -- the losing value is discarded for good, `resolved_at`
    set. Restoring the losing value instead is not a special "resolve"
    variant: it's a normal new `field_set` op with a fresh HLC (routers/
    settings.py's own restore action), applied through the same apply_op
    path as any other write, followed by this same dismissal call."""
    conn.execute(
        "UPDATE sync_conflicts SET resolved_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), conflict_id),
    )
    conn.commit()


def clear_page_banner(conn: sqlite3.Connection, page_key: str) -> None:
    set_app_meta(conn, _page_banner_key(page_key), "")
