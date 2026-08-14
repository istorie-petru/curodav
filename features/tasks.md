# Tasks

`routers/tasks.py` — four views over the universal `tasks` pool. Statuses
`active / in_progress / waiting / done / archived`; two 1–3 axes — **Importance**
and **Urgency** (0/None = unset) — replace the old single WebDAV priority (1.1,
see [`open-priority.md`](open-priority.md) § Virtual & derived states); progress
is derived from status (`_progress_for_status`).

## Views (shared `_tasks_toolbar.html`)

- **Table** (`/tasks`) — open/completed split into two tbody sections; sortable
  (title/due/importance/urgency/status); inline pill-selects for
  status/importance/urgency + date cell → `POST /tasks/{uid}/update-field`
  (JSON, single field, no reload); bulk-actions bar (checkbox select → `POST
  /tasks/bulk` with `delete`/`status`/`tag` add-remove). Every task delete is
  the undo path — tasks are flat (1.2), so no delete cascades.
- **Board** (`/tasks/board`) — kanban columns per status (archived excluded),
  pointer-event drag-drop (`DRAG_THRESHOLD=6`), optimistic move via the same
  `update-field` endpoint. Cards carry both axes as pills.
- **Timeline** (`/tasks/timeline`) — Gantt via `timeline_layout.py`; gutter
  grouped by label blocks (+ "(No label)"); swimlanes, zoom-aligned range,
  day/week headers; drag reschedule/resize →
  `POST /tasks/{uid}/timeline-reschedule`, vertical lane drag →
  `/tasks/{uid}/timeline-lane` (persisted `timeline_lane`), click-drag-create →
  `POST /tasks/timeline/create`. Double-click opens the card.
- **Habits** (`/tasks/habits`) — see `habits.md`.

Search box + five inline fancy dropdowns (Date / Status / Importance / Urgency /
Label) in row 1, all submitting immediately; active-filter badge. Filters AND
together. The Date dropdown also carries the virtual states `overdue` / `today` /
`tomorrow` / `this_week` / `this_month` / `important` / `urgent` — query
projections over the derived values, not labels (see below).

## Importance, Urgency, and the virtual states (1.1)

Two explicit 1–3 axes replace the single priority. Effective values are computed
deterministically in `src/derived_state.py`:
`effective importance = max(explicit, label-derived)` (a label's
`label_config.importance` rule), `effective urgency = max(explicit,
label-threshold, time-remaining)` — urgency rises as the due/end date
approaches and hits level 3 once overdue or due today (a label's
`urgency_threshold_days` rule implies urgency inside its window). Nothing
derived is ever stored. The `Important` / `Urgent` virtual states trigger at
level 3 and behave exactly like the other `DATE_FILTERS` values; the shared
aggregation service (`derived_state.count_by_state`, `dashboard.py`'s
at-a-glance widget) reads the same derivation, so every surface agrees.
WebDAV export (`ical_rows.py`) maps the combined axes to iCal `PRIORITY` via a
fixed urgency-dominant table; import maps `PRIORITY` back to explicit urgency
only (this app is the write-source). Tasks CSV export emits `Importance` /
`Urgency` columns. Sorting (`_SORT_KEYS`) orders higher axes first.

## Recurring tasks / completions

RRULE recurrence; checking off records a daily completion → heatmap + current/
longest streaks on the detail page. Endpoints: `POST /tasks/{uid}/complete`,
`/tasks/{uid}/completion/{date}/toggle`, `POST /tasks/{uid}/completions`
(explicit value).

## Relations (task ↔ event)

Task ↔ event links via `event_task_relations` (shared-label rule),
`_task_relations.html`; "+ New event…" inherits task labels. The card was the
merged Checklist+Subtasks card (2026-08-08), then gained the Related events
half (2026-08-09); the **1.2 task-model decision removed the subtasks half
outright** — tasks are flat (`parent_uid` no longer written or read, no cascade
delete, no iCal RELATED-TO round-trip), so the card now holds related events
only.

The "Add a related event…" row is the shared picker overlay (1.2 side work,
`static/command_palette.js`), not a `<select>` — see "Search & the command
surface" below. It replaced the old inline dropdown that pre-rendered every
candidate event on every page load; the overlay now asks
`GET /api/search?for_task=<uid>` for exactly the page of shared-label,
not-already-linked candidates it needs.

**Hide/show the card (2026-08-14)** — Settings > Appearance's "Show the
Relations card" toggle (`deps.py`'s `show_relations_card()` global, default
on) hides or shows the card across all four of its homes (task detail/edit,
event detail/edit), presentation-layer only — the underlying relations data
and all their endpoints are untouched.

## Work allocations (1.4)

A work allocation is *not* a new object — it's an ordinary `event_task_relations`
row with `is_work_allocation=1` (see `open-priority.md` § Work allocations, §
Task & calendar semantics). `db.create_work_allocation(conn, task_uid,
start_at, end_at)` creates a plain event titled after the task, inheriting its
labels, linked with the flag set; `db.list_work_allocations_for_task`/
`db.task_work_hours` read it back (`scheduled`/`completed`/`remaining` hours,
computed from each block's actual start/end — no independent estimate field).
`db.delete_work_allocation` is `delete_event` under a name that states the
1.4 rule at the call site: removes the scheduled block, never the task.

**Title semantics** — a work allocation's title is owned by its task, not
independently editable: `upsert_task` calls `db.sync_work_allocation_titles`
whenever it runs, pushing the task's current title onto every linked
allocation event; editing a work-allocation event's own title
(`routers/calendar.py`'s `update_event`) redirects the new value onto the
task instead of writing it to the event, which then gets synced back onto
every allocation of that task (including the one just edited) — so the
task is the single source of truth for the text, never a name conflict
between the two.

**UI shipped:** a "Work sessions" card on the task detail/edit modals
(`_task_work_allocations.html`, `POST /tasks/{uid}/work-allocations` +
`/work-allocations/remove`); and (1.4 slice 3) the project's own Week
Calendar view (`GET /projects/{name}/calendar`) — the drag-and-drop surface
the spec describes, dragging a task onto the grid to create an allocation,
dragging/resizing an existing block to move it. See § Projects' "Week
Calendar view" below for the full shape.

**Add-undated-sessions (2026-08-14):** the card's start/end datetime inputs
are gone — a single "+" button in the card's header adds a session with no
date at all (`db.create_work_allocation(conn, task_uid)` with neither
`start_at` nor `end_at`, the new both-or-neither signature). Such a session
is an **undated session placeholder** (an event with NULL `start_at`/
`end_at`; `events.start_at` is nullable, so no schema change): it has no
slot yet, so the task stays on the planning grids' "Unscheduled work"
panel (the Timetable sub-view, `/week`, the project Week Calendar) until
the session is placed. Dragging the task onto a grid slot **places the
task's oldest undated session** — `db.first_undated_work_allocation_for_
task` + `db.set_work_allocation_times` in all three create endpoints
(`week.py`/`calendar.py`/`projects.py` `create_allocation`) — rather than
creating yet another block, so repeated "+" sessions each get placed by one
drag. A task drops off the panel only when every one of its sessions is
dated. The card renders sessions in creation order ("Session 1/2/3", since
`list_work_allocations_for_task` now orders by creation time) with the
session's date+hour at the row's end (blank while undated). Undated
sessions are private placeholders and are skipped by every publishable
outlet (`events.ics` export and published event Lists), so they can never
leak out as DTSTART-less VEVENTs.

**Unscheduled-work panel rework (2026-08-14):** each planning grid's
"Unscheduled work" sidebar item is now a shared partial
(`_unscheduled_task_item.html`, imported `with context` by the Timetable
sub-view, `/week`, and the project Week Calendar) showing, per task:
- a **scheduled/total hours x/y** next to the title —
  `db.work_allocation_panel_info`: `scheduled_hours` is the sum of dated
  session durations (same number as `task_work_hours.scheduled`),
  `total_hours` adds one default hour per undated session (its planned
  contribution, the 1-hour block it becomes when placed) so the readout is
  "hours on the calendar out of hours planned", e.g. `2/3h`;
- a **−/count/+ session stepper**: "+" posts `POST /tasks/{uid}/work-
  allocations` (adds an undated placeholder), "−" posts `POST /tasks/{uid}/
  work-allocations/remove-latest` (removes the most recently added UNDATED
  session, `db.remove_latest_work_allocation` — never an already-scheduled
  one) and **renders whenever `undated_count > 0`**. The number itself is
  `undated_count` — sessions still needing placement — NOT the task's total
  session count (`count`); direct feedback (2026-08-14, same day as the
  fixes above) was that dropping one of a task's sessions onto the grid
  didn't move the panel's number when it showed the total ("the counter
  doesn't update from 2 to 1"). Placing a session (or unscheduling one back
  off the grid) automatically moves it in/out of this number, since it's
  just "how many of this task's sessions have no start/end yet." Reaching 0
  remaining is a normal state (everything's placed), not a floor the panel
  avoids — that's a change from the count's old semantics, where the panel
  deliberately never let you reach zero *total* sessions (that's still the
  task modal's Work sessions card's job). Both forms carry a same-origin
  `next` path (validated by `tasks.py::_safe_next` against open-redirect
  payloads) so the reload lands back on the grid they were used from.
- **Unschedule never changes the task's session count** — the three delete
  endpoints (`db.unschedule_work_allocation`) clear ONLY the one session's
  start/end back to undated instead of deleting it; the task's other
  sessions are untouched and the session count stays exactly what it was.
  (2026-08-14, two earlier designs the same day, both wrong: first this
  collapsed *every* session down to one undated placeholder on any single
  unschedule — `db.collapse_task_work_allocations`, since deleted — until
  direct feedback flagged that as silently discarding a task's other
  planned sessions, "the session count doesn't hold as a guide"; the first
  fix for that then hard-deleted just the one session via `db.
  delete_work_allocation`, which visibly dropped a single-session task's
  count to zero the moment its only block was unscheduled — also wrong,
  since unscheduling isn't "I don't need this session anymore," that's what
  the panel's own −/+ stepper or the task's Work sessions card are for.)
  The block's delete button and the drag-onto-panel gesture both skip the
  generic delete-confirmation popover now too (`data-confirmed="1"` on the
  form) since neither is destructive anymore.
- **Pointer-based drag** (static/project_calendar.js interaction 1) replaces
  native HTML5 drag-and-drop: a fixed ghost clone follows the cursor, the
  hovered column lights up, and the grid auto-scrolls near its top/bottom
  edge so any time is reachable; the block move/resize path gained
  pointercancel revert, scroll-aware positioning, and an edge auto-scroll of
  its own. Panel items no longer carry a native `draggable` attribute.

**Still open, deferred:** wiring `_project_card`'s `progress` to real
scheduled-work hours instead of task count, and hiding a completed task's
future allocations from the active calendar — see `plans/STATE.md`.

## Task model (1.5)

**Single project per task (shipped 2026-08-13)** — a task may carry exactly
one `is_project=1` label plus any number of ordinary labels; multiple project
ownership at once is rejected (`open-priority.md` § Task model). Enforced at
the single write boundary all label writes go through, `db.upsert_task`'s
`tags` argument: if the resulting label set would include more than one
project label, it raises `db.MultipleProjectLabelsError` *before* anything is
written (no partial task-row-without-labels write). The task create/edit
forms (`routers/tasks.py`'s `create_task`/`update_task`) and the Tasks page's
bulk "Add label" action (`POST /tasks/bulk` action `"tag"`) all catch it and
surface a plain 400 with the offending label names — the create/edit forms
via `HTTPException(400, ...)` (same convention as this app's other
plain-form validation errors, e.g. `routers/banners.py`'s upload checks);
the bulk path applies per-uid (so tasks with no conflict in the same batch
still get their label) and returns `{"ok": false, "error": ..., "failed":
[...]}` at 400 listing which uids were rejected. No client-side prevention in
the labels picker itself — `_widget_list_multiselect.html` is shared by
tasks/events/contacts/habits and has no project-label concept, so adding
mutual exclusion there would leak a task-only rule into unrelated pickers;
server-side rejection with a clear message was the smaller, more consistent
change. Enforcement is write-boundary only: a task that already carries two
project labels from before this change (direct DB edit, restored backup)
keeps them untouched until something next calls `upsert_task` with a new
`tags` list for it — no migration strips existing data. See
`tests/test_single_project_per_task.py`.

**Table view groupable by project (shipped 2026-08-13)** — `GET /tasks`
takes a `group_by` query param (`"none"` default/absent, `"project"`);
absent/`"none"` renders exactly as before (fully backward-compatible with
existing links/bookmarks). `group_by=project`
(`routers/tasks.py::_group_tasks_by_project`) clusters the already-filtered,
already-sorted task list under project-name headers, reusing
`db.project_label_for` per task — the same "which label is the project"
lookup the project detail page uses — rather than a second implementation.
Named groups sort alphabetically (case-insensitive); tasks with no project
label fall into a "No project" bucket rendered last. Grouping is applied
independently to the open and completed splits (composes with the existing
"completed stays visible, pushed below open, separated by a divider" rule,
`tasks_list.html`) and after every other filter (date/status/importance/
urgency/label/search) and after the active `sort`/`dir`, so within a group
tasks keep the page's current sort order. The toggle lives in
`_tasks_toolbar.html` as a "Group by" fancy dropdown (None/Project),
Table-view only, following the same `_filter_dropdown.html` single-select
pattern and shared `#tasks-filters-form` every other Tasks filter already
uses, so switching it preserves every other active query param. Grouping
only adds header `<tr>`s and splits rows across more `<tbody>` elements —
row markup itself (`_task_row.html`) and `static/tasks_table.js`'s
`tr[data-uid]`/`.row-select`/`select.pill-select` selectors are unchanged.
See `tests/test_tasks_grouping.py`.

**Deadline-vs-work-allocation distinction (shipped 2026-08-13)** — a task
deadline (`due_at`, "the work must be completed by a particular time") and a
work allocation (`db.task_work_hours`, "the user intends to spend a
particular amount of time on it at a particular time") already existed as
separate fields/mechanisms, but the global Tasks table and the project
detail page's Tasks view (both rendering the shared `_task_row.html` macro)
only showed "Due" — work-allocation status was invisible on the primary
task-management surface unless the detail modal was opened. A "Scheduled"
column was added next to "Due": `{completed}/{scheduled}h` (rounded to one
decimal) when the task has at least one work allocation, an em-dash
otherwise — plain text, not an editable input, and a distinct header label,
so it can't be mistaken for the same kind of thing as the editable "Due"
date cell. `db.task_work_hours_bulk(conn, task_uids)` computes it for every
row on a page in one query (grouped by `task_uid`) instead of one
`list_work_allocations_for_task` query per row — wired into both
`routers/tasks.py::list_tasks` and `routers/projects.py::project_detail`,
which attach each task's totals as `task["work_hours"]` before rendering.
`db.task_work_hours` itself (single-task call sites: task detail/edit
modals) is unchanged. See `tests/test_task_scheduled_column.py`. **This was
1.5's last piece — 1.5 is now fully shipped.**

## Search & the command surface

`Ctrl-K`/`Cmd-K` from anywhere, the tabbar's Search entry, or `/search`
directly opens one shared picker overlay backed by `db.search_entities` (a
single query layer over tasks, events, and contacts — free-text over
title/description/labels, plus type and label filters) and its HTTP surface,
`routers/search.py`'s `GET /api/search`. Picking a result opens it (the same
`data-modal` mechanism every entity link already uses); picking a Tasks/
Events/Contacts entry with no query yet navigates there directly. The same
overlay, opened with an implicit `for_task`/`for_event` filter instead, is
the Relations card's picker described above — one implementation for both
invocation modes, not two independent search UIs.

**What's shipped:** the query layer, `/api/search`, `/search`, Ctrl-K,
navigate-to-result, and the Relations picker wiring (`plans/open.md`'s
Universal command surface steps 1–4 and 6). **Not yet built:** context-
dependent commands/actions beyond navigation — creating, completing,
deleting, or labeling an entity directly from the palette, with destructive-
action confirmation (step 5's fuller scope). The overlay searches and
navigates today; it isn't a full command palette yet.

## Auto-archive

`TASK_AUTO_ARCHIVE_DAYS_KEY` ("Never"/7/14/30/90), lazy `_auto_archive_if_configured`
DELETE on each Table visit.

## Projects (1.3)

`routers/projects.py` (`/projects`) — a project is a label with
`label_config.is_project=1` plus `start_date`/`end_date`; no separate
entity (see [`open-priority.md`](open-priority.md) § Project-enabled label
stack). Promote (`POST /projects/promote`, name + dates — existing or
brand-new label), edit dates (`POST /projects/{name}/dates`), demote
(`POST /projects/{name}/demote` — clears `is_project`/dates/`archived_at`,
label + membership untouched), archive (`POST /projects/{name}/archive` —
the only way `archived_at` gets set). `labels_manage.html`'s Project column
links here rather than writing `is_project` itself, since promoting needs
dates up front.

**Lifecycle** (`db.project_status`) — Open / Pending / Pending Archiving /
Archived, computed at read time (only `archived_at` is stored): Open = any
incomplete task or zero tasks; Pending = every task done, today before
`end_date`; Pending Archiving = every task done, today on/after `end_date`
(or no `end_date`); Archived = `archived_at` set (explicit confirm only —
neither the end date passing nor task completion archives by itself).

**Overlap** (`db.find_overlapping_project`) — two non-Archived projects may
not share an overlapping `[start_date, end_date]`; promote/dates redirects
back with `?overlap=<name>` and a "save anyway" confirm (`confirm_overlap`)
instead of silently accepting the conflict.

**`project_label_for` supersession** — an attached `is_project=1` label now
wins outright; falls back to the pre-1.3 "first non-Space label,
alphabetical" heuristic only when nothing attached is explicitly
project-enabled (data written before 1.3).

**Cards** (`/projects`, `_project_card`) — status, `start_date`/`end_date`,
task count, completed/remaining, nearest incomplete due date, and
`progress` = completed/total *task count* (not hours — work allocations
don't exist until 1.4, so there's no scheduled-work total to compute a real
hour-based percentage from yet).

**Project detail page + Tasks view (1.4 slice 2)** — `GET /projects/{name}`
(`routers/projects.py::project_detail`) is the project's own page the spec
calls for ("opening a project provides two principal views"); a card's
"Open" link and title now go here instead of the label's generated page
(`routers/labels.py`'s `label_detail`, which stays reachable directly but is
no longer what a project links to). Ships the **Tasks view**: every task
carrying the project's label, open/completed split same as the global Tasks
page, with the identical interactive row — status/importance/urgency
pill-selects and inline due date driven by `static/tasks_table.js`,
delete-with-undo — extracted into a shared macro (`_task_row.html`, `{% from
"_task_row.html" import task_row with context %}`) so both pages render the
exact same markup instead of two copies. "+ New task" opens
`/tasks/new?project=<name>`; `new_task_form` pre-checks that label on the
form's chip multiselect (still removable) — including for a brand-new,
empty project whose label has no `object_labels` rows yet, which
`list_tag_names_in_use` alone wouldn't offer.

No sort links or bulk-action bar on this table yet (the global Tasks page's
`_tasks_toolbar.html` is tightly coupled to `/tasks*` routes/params — not
reused here). No project-scoped filtering either; every project task shows.
The project detail page now has a Tasks/Week Calendar tab switcher
(`.segmented.calendar-subnav`, same plain-link pattern
`calendar_week.html`'s own subnav uses) linking to the Week Calendar view
below.

**Week Calendar view (1.4 slice 3)** — `GET /projects/{name}/calendar`
(`routers/projects.py::project_calendar`) is the project's scheduling
surface: the current week's grid (reusing `grid_layout.layout_day`, the
same function `routers/calendar.py::week_view` calls, rather than a second
copy of that math), with an "Unscheduled tasks" list beside it (open
project tasks with no work allocation yet — since the 2026-08-14 panel
rework each item is the shared `_unscheduled_task_item.html` partial: the
`{project} > {task}` title with a scheduled/total-hours x/y and a −/count/+
session stepper). Dragging a list item onto the grid
POSTs `task_uid`/`start_at`/`end_at` to `POST
/projects/{name}/calendar/allocations` (`create_allocation`), which
defensively re-checks the task actually carries this project's label
before calling `db.create_work_allocation` — or placing the task's oldest
undated session (`db.set_work_allocation_times`, for a session the Work
sessions "+" added without a date) — the same helpers the task-detail
"Work sessions" card's own endpoint already calls, kept as the alongside
fallback, not replaced. Dragging or resizing an existing block
POSTs to `POST /projects/{name}/calendar/allocations/{event_uid}/move`
(`move_allocation`) — a plain `start_at`/`end_at` edit via `db.upsert_event`,
the same technique `routers/calendar.py::reschedule_event` already uses for
the global grid's own drag, just a form-POST/redirect endpoint instead of
that route's JSON/fetch contract, to match this page's other actions. Each
block's delete button POSTs to `.../{event_uid}/delete`
(`delete_allocation` -> `db.unschedule_work_allocation`) — clears only that
one session's start/end back to undated; the task's other sessions, the
task itself, and the task's total session count are all untouched. Ordinary
calendar events (and any other project's own work allocations) render as
visually subdued context (`.context-event`, reduced opacity); only this
project's own work allocations (`.work-allocation`) are prominent and
interactive.

**Still open, deferred** (doesn't block 1.5+): hour-based project-card
progress (`_project_card`'s `progress` is still completed/total task
count — `db.task_work_hours` exists per-task since slice 1 but nothing
aggregates it to project level). Hiding a completed task's future
allocations from the active calendar (the Week Calendar view now exists
but doesn't filter for this yet). The global Tasks page's project grouping
(1.5's job).
