# Roadmap

The single build order across both open-work docs. It merges the rework
([`open-priority.md`](open-priority.md)) with the app-local and low-priority
work ([`open.md`](open.md)) into nine minor releases — **1.1 → 1.9** — that
culminate in the next full release, **2.0**.

**Version:** the app is at **1.5** (1.0 was the first full release; 1.1 —
Virtual & derived states — shipped 2026-08-13; 1.2 — task model settled,
Universal command surface side work — shipped 2026-08-13; 1.3 — project-
enabled labels + lifecycle — shipped 2026-08-13; 1.4 — work allocations +
project week calendar — shipped 2026-08-13; 1.5 — task management &
grouping — shipped 2026-08-13). Minor releases are numbered
`1.1` … `1.9`; once everything on this roadmap is implemented, the next
full release is **2.0**. See the versioning rules in
[`abandoned.md`](abandoned.md).

## The two tracks

- **Track A — the rework** (`open-priority.md`): changes that reshape the
  architecture and presentation. This is the main line of the roadmap.
- **Track B — app-local & low priority** (`open.md`): features that don't
  touch the whole app. Non-blocking; slotted alongside Track A releases.

Track B items are "side work" — they can be moved between releases freely and
never hold Track A up.

## Release map

| Release | Main work (Track A) | Side work (Track B) | Depends on |
|---|---|---|---|
| `1.1` | ~~Virtual & derived states~~ — **shipped 2026-08-13** | ~~Data health~~ **shipped 2026-08-14**; Contacts parity | — |
| `1.2` | ~~Task-model decision~~ **resolved 2026-08-13** (flat tasks + work allocations, subtasks removed) | ~~Universal command surface~~ **shipped 2026-08-13** (search/navigate; command actions optional follow-up) | 1.1 |
| `1.3` | ~~Project-enabled labels + lifecycle~~ **shipped 2026-08-13** | Widget consolidation (not started — optional, doesn't block 1.4+) | 1.2 |
| `1.4` | ~~Work allocations + project week calendar~~ **shipped 2026-08-13** | Project check-in (optional, not started — doesn't block 1.5+) | 1.3 |
| `1.5` | ~~Task management & grouping~~ **shipped 2026-08-13** | — | 1.3–1.4 |
| `1.6` | ~~Schedule & recurrence rework~~ **shipped 2026-08-14** | Configurable views + optional Schedule (not started — optional, doesn't block 1.7+) | 1.3 |
| `1.7` | ~~Information architecture & view surfaces~~ **shipped 2026-08-14** | — | 1.1, 1.3, 1.4 + widgets |
| `1.8` | Offline-first editing & synchronization | Pagination | 1.1 (WebDAV) + ~~data health~~ (shipped) |
| `1.9` | Deployment & polish: DAVx5 hosting | Remaining app-local items | domain + server |
| `2.0` | Full release — everything implemented | — | all of 1.1–1.9 |

## Release detail

### 1.1 — Model foundations

**SHIPPED 2026-08-13** — see `features/tasks.md` (§ Importance, Urgency, and
the virtual states) and the now-removed § Virtual & derived states in
`open-priority.md`. Everything else reads the output of this release, so it went
first: temporal states (`Today`, `Overdue`, …) are query projections, not
labels; the shared aggregation service computes the counts and workload every
surface needs; Importance/Urgency replace WebDAV priority (with the WebDAV
representation settled here — the sync work in 1.8 builds on it).

Side work (independent): ~~**Data health & maintenance**~~ (verified backups —
the prerequisite for trusting offline sync in 1.8 — **shipped 2026-08-14**,
see `features/settings.md`) and **Contacts field parity**.

### 1.2 — Task model settled

**Task-model decision** (`open-priority.md` § Subtask model — the open
conflict): **resolved 2026-08-13** — **flat tasks + work allocations**. The
subtask hierarchy is removed outright; the schema change is applied (the old
`tasks.parent_uid` column stays on disk, never written or read again) before any
further task work. Small, but a hard gate for 1.3.

Side work (independent): **Universal command surface** (search / picker /
command palette) — **shipped 2026-08-13**: `db.search_entities` query layer,
`GET /api/search` + `/search`, Ctrl-K/Cmd-K, and the Relations-card picker
(`features/tasks.md` § Search & the command surface). Command-palette
*actions* (create/complete/delete/label from the overlay) didn't ship —
tracked as an optional follow-up in `open.md` § Command palette actions.

### 1.3 — The project stack

**SHIPPED 2026-08-13** — projects are labels with Project behavior:
`label_config.is_project` + a bounded `start_date`/`end_date`, the
Open → Pending → Pending Archiving → Archived lifecycle (computed at read
time — only `archived_at` is stored, the user's explicit confirmation — see
`db.project_status`), the overlap rule (`db.find_overlapping_project`), and
a dedicated `/projects` page with progress cards. `project_label_for`'s old
"any non-Space label is the project" heuristic is superseded (an explicit
`is_project=1` label now wins; the heuristic is only a fallback for data
that predates 1.3). See `features/tasks.md` § Projects for the shipped
shape. Card progress is completed/total *task count*, not hours — real
work-based (hour) progress needs 1.4's work allocations, which don't exist
yet; the project's own Tasks/Week Calendar views are 1.4's job too, not
this release's.

Side work (not started, optional, doesn't block 1.4+): **Widget
consolidation + Streak + Next Deadline** — must land before 1.7's Dashboard
rework so the widget grid is already consolidated.

### 1.4 — Work & time

**SHIPPED 2026-08-13** — **Work allocations + project week calendar**
(`open-priority.md` § Work allocations, Task & calendar semantics):
allocations as calendar events linked to tasks (a task's estimated work =
the sum of its blocks), the project scheduling surface with draggable
unscheduled tasks, and the task↔event edit/delete semantics.

**Slice 1** — the data model + semantics (allocations as linked events,
hour aggregation, title-sync, delete-only-removes-the-block) plus a
plain-form task-detail UI to schedule one; see `features/tasks.md` § Work
allocations (1.4).

**Slice 2** — the project detail page (`GET /projects/{name}`) and its
Tasks view (tasks filtered by the project's label, reusing the global Tasks
page's row/inline-editing markup via a new shared `_task_row.html` macro);
see `features/tasks.md` § Projects, "Project detail page + Tasks view".

**Slice 3** — the Week Calendar view (`GET /projects/{name}/calendar`): the
drag-and-drop scheduling surface (unscheduled tasks list, drag-to-create/
move/resize/delete a work allocation), reusing the global Week grid's own
layout math (`grid_layout.layout_day`) rather than duplicating it, ordinary
events shown as subdued context and the project's own allocations
prominent, plus the Tasks/Week Calendar tab switcher on the project detail
page. See `features/tasks.md` § Projects, "Week Calendar view". **Still
open, deferred to a later slice** (doesn't block 1.5+): the project-card
hour-based progress swap (`_project_card`'s `progress` is still
completed/total *task count*) and hiding a completed task's future
allocations from the active calendar — see `plans/STATE.md`.

Side work (optional, not started — doesn't block 1.5+): **Project
check-in** — a small post-stack addition.

### 1.5 — Task management

**Task management & grouping** (`open-priority.md` § Task model): the global
Tasks page as a table groupable by project, single-project-per-task, deadline
vs. work-allocation distinction, completed tasks staying visible. Uses the
allocations from 1.4.

- ~~Single-project-per-task~~ **shipped 2026-08-13** — `db.upsert_task`
  rejects a `tags` list carrying more than one `is_project=1` label
  (`db.MultipleProjectLabelsError`), surfaced as a plain 400 from the task
  create/edit forms and the bulk "Add label" action. Still open: the Tasks
  page as a groupable-by-project table, and the deadline-vs-work-allocation
  distinction.
- ~~Tasks page as a table groupable by project~~ **shipped 2026-08-13** —
  `GET /tasks?group_by=project` clusters the open/completed splits under
  project-name headers (`routers/tasks.py::_group_tasks_by_project`, reusing
  `db.project_label_for`), "No project" bucket sorted last, composes with
  every existing filter/sort; a "Group by" toggle in `_tasks_toolbar.html`.
- ~~Deadline-vs-work-allocation distinction~~ **shipped 2026-08-13** — a
  "Scheduled" column (`{completed}/{scheduled}h`, distinct label/styling
  from "Due") added to the shared `_task_row.html` macro, so both the
  global Tasks table and the project detail Tasks view surface work-
  allocation status alongside the deadline instead of only the deadline.
  `db.task_work_hours_bulk` added to compute it in one batched query per
  page instead of one query per row. **1.5 is now fully shipped.**

### ~~1.6 — Scheduling~~ — fully shipped 2026-08-14

**Schedule & recurrence rework** (`open-priority.md` § Schedule & recurrence
rework): courses become project labels + recurring events; generalized
non-working-day policy, named holiday calendars, manual occurrence exceptions,
and configurable terminology. `pyproject.toml` bumped to `1.6.0`.

- ~~Classes as project labels + recurring events~~ **shipped 2026-08-14** —
  `schedule_classes` dropped from `SCHEMA_SQL` entirely; a class meeting is a
  real recurring `events` row tagged with the Schedule system label + its
  course's `is_project=1` label. Course-only facts (acronym/type/credits/
  professor) moved to that label's own `label_config` row
  (`course_acronym`/`course_type`/`course_credits`/
  `course_professor_contact_uid`); day/parity are derived from the event's
  own `start_at`/`recurrence`, never stored. `scripts/migrate_schedule_
  classes_to_events.py` converts any pre-1.6 database. See
  `features/schedule.md`. Still open: configurable terminology.
- ~~Generalized non-working-day policy + named holiday calendars~~
  **shipped 2026-08-14** — `schedule_holidays` rows belong to a named,
  reusable `calendar_name` (default `'Default'` for every pre-1.6 holiday)
  instead of one flat list; any recurring `events` row (not just a Schedule
  class) can set `holiday_calendar`/`exclude_saturday`/`exclude_sunday` --
  three independent constraints, applied at *read* time by
  `recurrence_expand.expand_events`, never materialized into `exdates_json`.
  Schedule's own class events switched from per-write EXDATE-stuffing to
  just carrying `schedule_settings.holiday_calendar`. See
  `features/calendar.md`'s Recurrence section and `features/schedule.md`.
- ~~Manual recurrence exceptions~~ **shipped 2026-08-14** — a specific
  occurrence can be cancelled or moved/modified without touching the
  master's own recurrence rule (`event_occurrence_overrides` table). A
  cancelled occurrence folds into the master's own EXDATE list at expand
  time; a moved/modified one becomes a real second VEVENT sharing the
  master's UID with a RECURRENCE-ID -- the standard RFC 5545 override,
  which `recurring_ical_events` resolves for free
  (`recurrence_expand.py`'s `overrides_by_master` param). `event_detail.
  html`'s "This occurrence" card (Cancel/Move/Restore) is reached via
  `?occurrence_date=...`, which every calendar view now appends to a
  recurring occurrence's own link. Found and fixed a real pre-existing bug
  in `db.list_events`'s date-range query along the way (a recurring row's
  own literal start_at/end_at wrongly excluded it from far-future
  windows). See `features/calendar.md`'s Recurrence section.
- ~~Configurable terminology~~ **shipped 2026-08-14** — Settings > General's
  "Recurrence terminology" toggle (`standard`/`playful`, app_meta-backed,
  same pattern as Week starts on/Time format). Presentation-layer only: the
  underlying `holiday_calendar`/`exclude_saturday`/`exclude_sunday` field
  names and semantics never change, only the on-screen label
  (`_event_form_fields.html`/`schedule_classes.html`, gated by `deps.py`'s
  `recurrence_terminology()` Jinja global) — "Holiday calendar" / "Exclude
  Saturday" / "Exclude Sunday" in standard mode, "Respects Labor Laws" /
  "Marx Weekend: Saturday" / "Marx Weekend: Sunday" in playful mode. **1.6
  is now fully shipped.**

Side work: **Configurable views + optional Schedule module** — best landed now
that the reworked views are stable, since it toggles them.

### ~~1.7 — New surfaces~~ — shipped 2026-08-14

**Information architecture & view surfaces** (`open-priority.md` §
~~Information architecture & view surfaces~~): Dashboard (orientation), Today
(execution), Week (planning), Spaces (context), built on the aggregation
service (1.1), the project stack (1.3), and work allocations (1.4), with the
consolidated widget grid (1.3). Today and Week were built fresh this release;
Dashboard and Spaces were confirmed to already satisfy the spec from earlier
phases (Dashboard's widget-grid Home, Spaces' `generate_space` label pages +
University module) and closed out without new code. See `plans/STATE.md`'s
1.7 entries.

### 1.8 — Trust & offline

**Offline-first editing & synchronization** (`open-priority.md` § Offline-first
editing & synchronization) — the largest engineering item. Both preconditions
are now met: verified backups **shipped 2026-08-14** (Settings > Data health),
and the sync model itself (entity identifiers, HLC ordering, tombstones,
per-field conflict detection, the two conflict-surfacing exceptions for
work-allocation/event time fields and single-project-per-task) is **designed,
2026-08-14** — see `open-priority.md`'s own section for the full model and its
7-slice implementation breakdown. **Slice 1 (field-HLC shadow store + sync API
skeleton) shipped 2026-08-14** — `field_versions`/`sync_devices`/
`sync_applied_ops`, `src/offline_sync.py`'s §6 per-field LWW apply logic, and
`POST /api/sync/push`/`/api/sync/pull` (`routers/sync_api.py`). Server-only,
no browser/PWA client yet; slice 2 (`sync_conflicts` surface + §7b/c's two
conflict-surfacing exceptions) is next.

Side work: **Pagination / collapsible sections** (Phase B of webapp usability).

### 1.9 — Deployment & polish

**DAVx5 mobile hosting** (`open.md` § Webapp usability + DAVx5 hosting) —
CalDAV/CardDAV sync to a phone via a public HTTPS reverse proxy. Pure infra, no
app code; blocked on an external domain + server. Any remaining app-local items
(Contacts parity if not already shipped, project check-in, leftover Track B work)
close out here.

### 2.0 — Full release

With 1.1–1.9 implemented, the next full release is **2.0**: a stable, supported
version of the reworked app.

## Things that can slip past the map

- **DAVx5 hosting** is blocked on infrastructure the repo can't provide
  (domain + server) — run it whenever that exists, not strictly in 1.9.
- **Project check-in** is explicitly optional — skip it without affecting
  anything.
- All side work can move between releases; only the Track A dependencies in the
  release map are load-bearing.

## Reading the plan

- Section-level detail lives in the two source docs; this roadmap is only the
  ordering. Each section in those docs still gets expanded into a full phase
  spec (acceptance line, concrete slices) when you give it a go-ahead, and is
  removed from `plans/` once shipped — see "How open work gets tracked" in
  either doc.
