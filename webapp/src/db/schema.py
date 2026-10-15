"""The SQL that creates the tables.

Part of the db package; src/db/__init__.py re-exports every name.
"""

from __future__ import annotations


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
    -- explicit axes' per-task columns, replacing them with a purely
    -- computed derivation (src/derived_state.py) from label rules +
    -- temporal state; that whole feature is since removed outright (no
    -- longer something this app offers). The old `priority` column stays
    -- physically on disk for pre-1.1 databases but is no longer
    -- referenced by app code.
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
    -- 2026-08-29 (STATE.md backlog item 3): the same non-working-day
    -- policy as `events` (see that CREATE TABLE's own comment) -- only
    -- meaningful for a recurring task, read by habit_heatmap.
    -- excluded_dates_in_range/streaks, not recurrence_expand.
    holiday_calendar TEXT,
    exclude_saturday INTEGER NOT NULL DEFAULT 0,
    exclude_sunday INTEGER NOT NULL DEFAULT 0,
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

-- The contacts a task or event involves (the Contacts field on their forms).
-- Same link-table shape as object_labels; a deleted contact's rows go with it.
CREATE TABLE IF NOT EXISTS object_contacts (
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    contact_uid TEXT NOT NULL,
    PRIMARY KEY (object_type, object_id, contact_uid)
);
CREATE INDEX IF NOT EXISTS idx_object_contacts_contact ON object_contacts(contact_uid);

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
    -- derived states) added these two columns as label behavior rules
    -- feeding the Importance/Urgency effective-value derivation. That
    -- whole feature is since removed outright (no longer something this
    -- app offers) -- app code no longer reads or writes either column.
    -- Both stay physically on disk, unused, same "never force-drop old
    -- data" convention as every other removed column in this file.
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
    created_at TEXT,
    -- 2026-09-25 (labels-as-modules, plans/ui-cleanup-2026-09.md item 4,
    -- slice a): generic per-label module fields that replace the Space/
    -- Project special cases. Written and backfilled here; the UI still
    -- reads generate_space/is_project until slices b-d switch it over
    -- (see _mirror_legacy_module_fields for the interim sync).
    -- `label_group` (above) is the group, plain text -- Peter's call,
    -- 2026-09-25: groups are text, not labels. `archived_at` (above) is
    -- the archive flag; `start_date` is kept on disk but not used any more.
    sidebar_pin INTEGER NOT NULL DEFAULT 0,
    widget_pin INTEGER NOT NULL DEFAULT 0,
    has_deadline INTEGER NOT NULL DEFAULT 0,
    deadline_date TEXT,
    has_dashboard INTEGER NOT NULL DEFAULT 0,
    page_type TEXT NOT NULL DEFAULT 'sections',
    agenda_widget INTEGER NOT NULL DEFAULT 1,
    tasks_widget INTEGER NOT NULL DEFAULT 1,
    contacts_widget INTEGER NOT NULL DEFAULT 1,
    notebook_widget INTEGER NOT NULL DEFAULT 1
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
-- 2026-09-24 (plans/ui-cleanup-2026-09.md item 14): the standalone Habit
-- entity is removed -- no code reads or writes `habits`/`habit_entries`
-- anymore (a habit is a habit-labeled task, see habit_view.py). Both
-- tables stay here, never force-dropped, so an existing cache.sqlite is
-- untouched and purge_all_data still clears them.
CREATE TABLE IF NOT EXISTS habits (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT 'blue',
    icon TEXT,
    target_per_day REAL NOT NULL DEFAULT 1,
    archived_at TEXT,
    -- 2026-08-29 (STATE.md backlog item 3): same non-working-day policy as
    -- `tasks`/`events` above -- always applies (a habit is implicitly
    -- daily, no RRULE to gate on).
    holiday_calendar TEXT,
    exclude_saturday INTEGER NOT NULL DEFAULT 0,
    exclude_sunday INTEGER NOT NULL DEFAULT 0,
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
    -- 2026-09-24 (habits H3): optional day note; also added to existing
    -- databases via _ensure_column in init_schema.
    note TEXT,
    PRIMARY KEY (task_uid, due_date)
);

-- 2026-09-24 (plans/ui-cleanup-2026-09.md item 7, Web Push slice P1): one
-- row per browser/device that turned notifications on. `endpoint` is the
-- push service URL (unique per subscription); p256dh/auth are the
-- subscription's public key + secret the payload is encrypted to (not
-- credentials for this app). Pruned automatically when the push service
-- answers 404/410 (the browser dropped it).
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at TEXT,
    last_ok_at TEXT
);

-- Web Push P2 (2026-09-24): which reminders already went out -- one row
-- per reminder key (e.g. "event:<uid>:<start>:<minutes>",
-- "tasks:<date>"), so the scheduler never sends one twice, even across a
-- restart. Pruned after a few days.
CREATE TABLE IF NOT EXISTS push_sent (
    key TEXT PRIMARY KEY,
    sent_at TEXT NOT NULL
);

-- 2026-09-24 (habits H6): vacation / pause ranges. `task_uid` NULL pauses
-- every habit; otherwise one habit. Paused days are neutral for streaks
-- (habit_schedule.habit_stats' `paused_dates`). Local-only like
-- task_completions; start/end are inclusive ISO dates.
CREATE TABLE IF NOT EXISTS habit_pauses (
    uid TEXT PRIMARY KEY,
    task_uid TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_habit_pauses_task ON habit_pauses(task_uid);

-- 2026-09-26 (Peter: groups are standalone): a group is a row of its own,
-- not just text on its labels. Labels still point at it by name
-- (label_config.label_group); a group may have no labels at all. Its
-- look (icon, color) lives here -- it used to be app_meta
-- "group_style:<name>" -- and its page/banner stay keyed by
-- group_page_key(name).
CREATE TABLE IF NOT EXISTS label_groups (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    icon TEXT,
    color TEXT NOT NULL DEFAULT 'gray',
    created_at TEXT,
    page_type TEXT NOT NULL DEFAULT 'dashboard'
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

-- Notebook layout preference (2026-10-04 direct request) -- one app-wide
-- choice between the two sidebar "design philosophies": 'stacked' (the
-- default -- Outline/Endnotes/Bibliography/Glossary/Relationships all
-- flow in one reading-order column, on both desktop and mobile, no
-- separate side panel at all) and 'sidebar' (desktop keeps a real right-
-- hand panel hosting all of those as tabs instead of separate page
-- sections; mobile in this mode shows the editor body only -- none of
-- that content, not even stacked, confirmed directly rather than guessed:
-- the sidebar is a desktop-only affordance in this mode). Same
-- id-must-be-1 singleton shape as task_habit_settings above.
CREATE TABLE IF NOT EXISTS notebook_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    sidebar_layout TEXT NOT NULL DEFAULT 'stacked'
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

-- Notebook (curodav-notes/documentation/plans/STATE.md +
-- architecture-notes-module-2026-09-29.md, 2026-09-29) -- a block-based
-- note-taking module, MVP schema only (Phase 0 of the 0-to-MVP roadmap).
-- `content_json` holds Editor.js's own OutputData JSON verbatim -- no
-- markdown translation layer, no custom serialization -- viable only
-- because this module deliberately dropped live Obsidian/markdown
-- compatibility (see STATE.md's "no live Obsidian compatibility"
-- decision); it's read/written as raw JSON by exactly one pair of routes
-- (GET/PUT /notebook/{uid}/content), the one deliberate exception to this
-- app's "never fetch JSON directly" rule, since there's no HTML fragment
-- that represents live rich-block-editor state.
-- `document_type` ('full' | 'simple') is app-set, not user-facing: 'full'
-- for a document someone deliberately sat down to write, 'simple' for a
-- lightweight note the app creates as a byproduct of something else
-- (post-MVP; nothing creates 'simple' rows yet).
-- `note_type` is user-set, free text for MVP -- STATE.md's canonical,
-- enforced-in-code vocabulary (notes/analysis/wiki/research/person/
-- country/...) is a post-MVP addition once the entity-kind/relationships-
-- sidebar use of this column actually exists; nothing needs to reject an
-- unrecognized value yet. Blank by default (2026-10-02, direct request)
-- -- a new document shouldn't arrive with a specific suggestion already
-- picked, just an empty Type until the properties modal sets one.
-- No folder/parent column -- organization is via `object_labels`
-- (object_type='notebook', reusing the existing label_config/label_groups
-- infrastructure as-is), not a hierarchy on this table. See STATE.md's
-- "notes organization is Groups + Labels, not folders" decision.
CREATE TABLE IF NOT EXISTS notebook_documents (
    uid TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    content_json TEXT NOT NULL DEFAULT '{"blocks": []}',
    document_type TEXT NOT NULL DEFAULT 'full',
    note_type TEXT NOT NULL DEFAULT '',
    is_template INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    journal_week TEXT NOT NULL DEFAULT '',
    pinned INTEGER NOT NULL DEFAULT 0
);

-- Custom document properties (2026-10-02, curodav-notes/documentation/
-- plans/architecture-notes-module-2026-09-29.md §4 + STATE.md) -- arbitrary
-- user-named key/value fields per document (institution, author(s), DOI,
-- date, ...), directly inspired by Obsidian's Properties/frontmatter
-- block. Deliberately *not* a typed-field schema or a mechanism for
-- defining new entity "types" -- same spirit as object_labels, just a
-- plain EAV table. Same "real owned child row" shape as
-- task_checklist_items/contact_phones (string uid PK, no FOREIGN KEY --
-- this app doesn't use them anywhere; float position as the sort key) --
-- not a composite (notebook_uid, key) natural key, since two rows with the
-- same key by mistake should be an editable duplicate, not a write
-- conflict. keywords/short_title are NOT stored here -- STATE.md proposes
-- those as dedicated notebook_documents columns instead, since backend
-- logic (search, wikilink display) needs to query them directly; that's a
-- separate, still-unconfirmed decision, not resolved by this table.
CREATE TABLE IF NOT EXISTS notebook_properties (
    uid TEXT PRIMARY KEY,
    notebook_uid TEXT NOT NULL,
    key TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL DEFAULT '',
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_notebook_properties_notebook ON notebook_properties(notebook_uid);

-- 2026-10-02: Settings > Notebook's frontmatter field schema (curodav-notes
-- STATE.md's "custom frontmatter field schema" decision) -- a *descriptive*
-- catalogue of the properties a Notebook document can carry (key, display
-- label, type, default, whether it's required), edited via Settings the
-- same Field/Type/Default/Required/Actions table shape as Labels/Holidays.
-- Deliberately separate from `notebook_properties` (the actual per-document
-- EAV values): this table describes the *shape* documents are expected to
-- follow, that table stores what a given document actually has. v1 is
-- descriptive only -- nothing here is enforced against notebook_properties
-- on save yet (STATE.md flags validation as the next priority once this
-- schema UI ships, not part of it).
--
-- `builtin` (2026-10-02 direct request, "all frontmatter should always
-- appear in the settings... title and author... note_type should appear
-- because i want to change icon and color"): three rows
-- (_BUILTIN_NOTEBOOK_FIELDS below) are seeded once and can never be
-- deleted -- title/author are locked to Text with only `label` editable
-- (everything else about a document's title/author is fixed, there's
-- nothing else to configure); note_type is locked to Select with its
-- option *values* fixed to STATE.md's canonical list (still not a
-- user-editable note_type registry -- the list of types itself stays
-- hardcoded) but each option's color/icon fully editable, which is what
-- actually paints note_type's badge/dropdown everywhere it renders
-- (routers/notebook.py's `_notebook_type_icon` and friends). A plain
-- user-created field (`builtin=0`) is fully editable/deletable, unchanged.
CREATE TABLE IF NOT EXISTS notebook_field_config (
    uid TEXT PRIMARY KEY,
    key TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT 'text',
    default_value TEXT,
    position REAL NOT NULL DEFAULT 0,
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT
);

-- A Select/Multi-select field's own option list (value + color + icon),
-- same "real owned child row, float position as the sort key" shape as
-- notebook_properties/task_checklist_items above -- not a FOREIGN KEY, same
-- convention as every other child table in this file. Reuses the exact
-- look_picker (color + icon) mechanism Labels already uses, per-option.
CREATE TABLE IF NOT EXISTS notebook_field_options (
    uid TEXT PRIMARY KEY,
    field_uid TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    color TEXT,
    icon TEXT,
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_notebook_field_options_field ON notebook_field_options(field_uid);

-- Citations (2026-10-03, curodav-notes STATE.md's "citations are the
-- priority feature" decision + architecture-notes-module-2026-09-29.md
-- §5) -- document-level, not inline: a citation is never anchored to a
-- specific block, so there's no `block_id` column here (an earlier draft
-- of this schema had one, corrected before any code existed -- see that
-- doc's own note). `authors_json` is a JSON array of {family, given}
-- objects (CSL-JSON's own author shape), not a single free-text string,
-- so author-index/"used in" style lookups stay possible later without a
-- re-parse-and-guess step. `type` is a short, app-defined list
-- (CITATION_TYPES below) close to CSL-JSON's own type vocabulary, not
-- freeform text or a DB enum -- same reasoning as `note_type`.
CREATE TABLE IF NOT EXISTS citations (
    uid TEXT PRIMARY KEY,
    type TEXT NOT NULL DEFAULT 'book',
    title TEXT NOT NULL DEFAULT '',
    authors_json TEXT NOT NULL DEFAULT '[]',
    year TEXT NOT NULL DEFAULT '',
    container_title TEXT NOT NULL DEFAULT '',
    doi TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    created_at TEXT,
    updated_at TEXT,
    subtitle TEXT NOT NULL DEFAULT '',
    edition TEXT NOT NULL DEFAULT '',
    volume TEXT NOT NULL DEFAULT '',
    issue TEXT NOT NULL DEFAULT '',
    pages TEXT NOT NULL DEFAULT '',
    publisher TEXT NOT NULL DEFAULT '',
    place TEXT NOT NULL DEFAULT '',
    isbn TEXT NOT NULL DEFAULT '',
    issn TEXT NOT NULL DEFAULT '',
    accessed TEXT NOT NULL DEFAULT '',
    institution TEXT NOT NULL DEFAULT '',
    degree TEXT NOT NULL DEFAULT '',
    editors TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT ''
);

-- A document's attached citation list -- the bibliography (sidebar) and
-- footnotes (bottom, read-only) sections both read this same join table,
-- no separate storage per placement (STATE.md's "document apparatus"
-- framing). Composite PK, not a surrogate uid: a document can't attach
-- the same citation twice, so there's nothing a duplicate row would ever
-- mean. `position` is the document's own citation order (set whole-list,
-- same "replace on every save" convention as notebook_properties/
-- tags_labels), not citation-library order.
CREATE TABLE IF NOT EXISTS notebook_citations (
    notebook_uid TEXT NOT NULL,
    citation_uid TEXT NOT NULL,
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT,
    PRIMARY KEY (notebook_uid, citation_uid)
);

CREATE INDEX IF NOT EXISTS idx_notebook_citations_notebook ON notebook_citations(notebook_uid);
CREATE INDEX IF NOT EXISTS idx_notebook_citations_citation ON notebook_citations(citation_uid);

-- Glossary (2026-10-03, roadmap-mvp-to-full-product-checklist's "Glossary"
-- section -- "structurally identical to the citations table"), a flat,
-- global, cross-document pool, same as `citations` above.
CREATE TABLE IF NOT EXISTS glossary_terms (
    uid TEXT PRIMARY KEY,
    term TEXT NOT NULL DEFAULT '',
    definition TEXT NOT NULL DEFAULT '',
    created_at TEXT,
    updated_at TEXT,
    kind TEXT NOT NULL DEFAULT 'Term',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    wiki_uid TEXT NOT NULL DEFAULT ''
);

-- The fields every entry of a kind has; a field's name is fixed once it is created.
CREATE TABLE IF NOT EXISTS entry_kind_fields (
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    position REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, name)
);

-- The kinds an entry can have (Term, Person, Place, ...), each with its own icon and color.
CREATE TABLE IF NOT EXISTS entry_kinds (
    name TEXT PRIMARY KEY,
    icon TEXT NOT NULL DEFAULT 'tag',
    color TEXT NOT NULL DEFAULT 'teal',
    position REAL NOT NULL DEFAULT 0
);

-- Extra titled text blocks on a term (Example, "Remember", ...), user-defined per entry.
-- Not part of the definition and never shown in the editor sidebar.
CREATE TABLE IF NOT EXISTS glossary_term_sections (
    uid TEXT PRIMARY KEY,
    term_uid TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    position REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_glossary_term_sections_term ON glossary_term_sections(term_uid);

-- A document's attached term list (2026-10-03 direct follow-up, "add a
-- sidebar tab" -- full parity with notebook_citations above, including a
-- per-document attach, not just the global library). Same shape as
-- notebook_citations: composite PK (a document can't attach the same term
-- twice), `position` is the document's own order, set whole-list on every
-- save. `auto` (roadmap item H, session 7) distinguishes a row the attach
-- modal's user explicitly checked (0) from one `_rebuild_notebook_glossary_
-- terms` added itself by finding the term's literal text in the document
-- (1) -- the auto-detect/auto-remove pass only ever touches auto=1 rows,
-- so a manual attachment can never be silently removed by a later text
-- edit elsewhere in the document.
CREATE TABLE IF NOT EXISTS notebook_glossary_terms (
    notebook_uid TEXT NOT NULL,
    term_uid TEXT NOT NULL,
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT,
    auto INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (notebook_uid, term_uid)
);

CREATE INDEX IF NOT EXISTS idx_notebook_glossary_terms_notebook ON notebook_glossary_terms(notebook_uid);
CREATE INDEX IF NOT EXISTS idx_notebook_glossary_terms_term ON notebook_glossary_terms(term_uid);

-- A term the user has explicitly detached from this document via the
-- attach modal (roadmap item H, session 7) -- "manually remove an
-- auto-applied [match] to override a false positive" needs to stick
-- across later saves, otherwise the very next content save's text scan
-- would just re-detect the same literal text and re-attach it. Checked by
-- `_rebuild_notebook_glossary_terms` before auto-attaching a detected term;
-- written/cleared only by `set_notebook_glossary_terms` (the attach
-- modal's own save path), never by the auto-detect pass itself.
CREATE TABLE IF NOT EXISTS notebook_glossary_excluded_terms (
    notebook_uid TEXT NOT NULL,
    term_uid TEXT NOT NULL,
    created_at TEXT,
    PRIMARY KEY (notebook_uid, term_uid)
);

-- A glossary term's own "further reading" list (2026-10-03, roadmap item F)
-- -- Notebook documents and/or citations that term points readers to for
-- deeper context. Owned by the term, not by a document (the inverse
-- direction of notebook_citations/notebook_glossary_terms above, which are
-- owned by the document), so the composite PK leads with term_uid.
-- `ref_type` ('notebook' or 'citation') plus `ref_uid` together identify the
-- target row rather than a single FK column, since the target can live in
-- either of two tables with no shared uid space to point at generically.
-- `position` is this term's own reference order, set whole-list on every
-- save, same "replace on every save" convention as notebook_citations.
CREATE TABLE IF NOT EXISTS glossary_term_references (
    term_uid TEXT NOT NULL,
    ref_type TEXT NOT NULL,
    ref_uid TEXT NOT NULL,
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT,
    PRIMARY KEY (term_uid, ref_type, ref_uid)
);

CREATE INDEX IF NOT EXISTS idx_glossary_term_references_term ON glossary_term_references(term_uid);

-- Wikilinks & relationships (2026-10-03, roadmap-mvp-to-full-product-
-- checklist's "Wikilinks & relationships" section) -- a derived cache,
-- fully rebuilt from a document's own content_json every time it's saved
-- (_rebuild_notebook_links below), never written to directly by a route
-- the way notebook_citations/notebook_glossary_terms are. Powers the
-- Relationships sidebar tab's "Linked from" (backlink) query -- the
-- "Links to" (outbound) side doesn't need this table at all, since that
-- document's content is already loaded client-side (static/notebook/
-- notebook_wikilinks.js walks the live DOM, same approach notebook_toc.js
-- already uses for headings). No `position` column -- unlike citations/
-- glossary, there's no document-controlled attach order here; the
-- Relationships tab always groups+sorts by the target's note_type/title
-- instead, so these rows carry no natural order of their own.
CREATE TABLE IF NOT EXISTS notebook_links (
    source_uid TEXT NOT NULL,
    target_uid TEXT NOT NULL,
    created_at TEXT,
    PRIMARY KEY (source_uid, target_uid)
);

CREATE INDEX IF NOT EXISTS idx_notebook_links_source ON notebook_links(source_uid);
CREATE INDEX IF NOT EXISTS idx_notebook_links_target ON notebook_links(target_uid);
"""
