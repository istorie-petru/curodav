# Tasks

`routers/tasks.py` — four views over the universal `tasks` pool. Statuses
`active / in_progress / waiting / done / archived`; two 1–3 axes — **Importance**
and **Urgency** (0/None = unset) — replace the old single WebDAV priority (1.1,
see [`open-priority.md`](open-priority.md) § Virtual & derived states); progress
is derived from status (`_progress_for_status`). Side work (post-1.1, direct
feedback: "just calculated automatically, no manual input") later removed the
per-task *explicit* axes entirely — both are now purely computed, see the
section below.

## Views (shared `_tasks_toolbar.html`)

- **Table** (`/tasks`) — open/completed split into two tbody sections; sortable
  (title/due/status); status has an inline pill-select + inline date cell →
  `POST /tasks/{uid}/update-field` (JSON, single field, no reload). Importance/
  Urgency do **not** appear as table columns (direct feedback: "I don't want
  importance and urgency to show in the tasks table view" — a further
  follow-up on the axes rework below; they were briefly read-only pills here
  first, then dropped from this view entirely). Both axes are still fully
  computed and still shown on Board (pills) and the task detail modal (meta
  grid); the toolbar's Importance/Urgency filter dropdowns are untouched —
  this was a column removal, not a filter removal. `_sort_keys` still knows
  how to sort by either axis (used by Board/other surfaces if ever needed),
  it's just not linked from a Table column header anymore. Bulk-actions bar
  (checkbox select → `POST /tasks/bulk` with `delete`/`status`/`tag`
  add-remove). Every task delete is the undo path — tasks are flat (1.2), so
  no delete cascades. **Pagination (1.9, Webapp usability Phase B)** — the
  Open section pages via `?page=`/`?limit=` (default 50/page, clamped
  1-200), applied after filtering/sorting; a `_tasks_pager.html` Prev/Next
  bar renders below Open when there's more than one page, preserving every
  active filter/sort/search param. Ungrouped view only (`group_by=none`,
  the default): `group_by=project` clusters tasks under per-project header
  rows where a flat page boundary would arbitrarily split a project's own
  tasks, so grouped mode still shows everything, unpaginated. Completed
  tasks are never paginated (already visually separated below Open, and
  bounded in practice by the auto-archive setting).
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

## Importance, Urgency, and the virtual states (1.1; explicit axes removed, side work)

Two 1–3 axes replace the single priority. 1.1 shipped them as *explicit*
per-task fields (`tasks.importance`/`tasks.urgency`) combined with label
rules via max-precedence; a later side-work slice (direct feedback: "just
calculated automatically, no manual input") removed the explicit axes
outright — the `tasks.importance`/`urgency` columns are dropped from the
schema (`db._drop_column`, a deliberate exception to this file's usual
"never force-drop old data" convention), and there is no manual "set this
task's importance/urgency" input anywhere in the app (no form field, no
inline pill-select). Effective values are now computed purely in
`src/derived_state.py`: `effective importance = label-derived` (a label's
`label_config.importance` rule — configured once per label, not per task,
so this is *not* a manual per-task input), `effective urgency =
max(label-threshold, time-remaining)` — urgency rises as the due date
approaches and hits level 3 once overdue or due today (a label's
`urgency_threshold_days` rule implies urgency inside its window). A
consequence of dropping the explicit axis: urgency level 1 ("Low") has no
source left and is effectively unreachable (label thresholds only ever
imply level 3, temporal state only ever yields 0/2/3) — not something this
slice added a workaround for. Nothing derived is ever stored. The
`Important` / `Urgent` virtual states trigger at level 3 and behave exactly
like the other `DATE_FILTERS` values; the shared aggregation service
(`derived_state.count_by_state`, `dashboard.py`'s at-a-glance widget) reads
the same derivation, so every surface agrees.

Display reads the computed value via two Jinja globals,
`effective_importance(request, task)` / `effective_urgency(request, task)`
(`deps.py`, label rules memoized per request the same way `label_icon`
is) — the one template-facing entry point, so no router needs to
precompute/attach the value onto every task dict just to render a pill.
Board (pills) and the task detail modal (meta grid) use them; the Table
view does **not** — a further follow-up removed the two columns from
Table entirely (see "Views" above), so on that page the axes are only
reachable via the toolbar's filter dropdowns, not shown per-row. WebDAV
export (`ical_rows.py`) still maps the combined *effective* axes to iCal
`PRIORITY` via the same fixed urgency-dominant table (callers —
`routers/export.py`'s tasks.ics, `published_lists.py`'s materialize —
resolve label rules once and attach the effective values onto a row copy
before calling `task_row_to_ical`, since that module itself stays
DB-free); import no longer maps `PRIORITY` back to anything (dropped
silently, this app is the write-source for its own tasks). Tasks CSV
export emits `Importance` / `Urgency` columns populated with the
effective values. `routers/tasks.py::_sort_keys` (a factory — it needs
`label_rules` to compute the value) still knows how to sort by either
axis; nothing links to it from a Table column header anymore, but the
filters/underlying capability are unchanged.

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
`/work-allocations/remove`); and drag-and-drop scheduling on the merged
`/calendar/week` grid (`static/project_calendar.js`) — dragging a task onto
the grid to create an allocation, dragging/resizing an existing block to
move it. (1.4 slice 3 originally shipped this as the project's own,
now-retired Week Calendar view — see § Projects below.)

**Add-undated-sessions (2026-08-14):** the card's start/end datetime inputs
are gone — a single "+" button in the card's header adds a session with no
date at all (`db.create_work_allocation(conn, task_uid)` with neither
`start_at` nor `end_at`, the new both-or-neither signature). Such a session
is an **undated session placeholder** (an event with NULL `start_at`/
`end_at`; `events.start_at` is nullable, so no schema change): it has no
slot yet, so the task stays on the planning grids' "Unscheduled work"
panel (Calendar's Week view, the project Week Calendar — the standalone
`/week` planning page these were originally triplicated with is retired,
1.9 side work, see `features/week.md`) until the session is placed.
Dragging the task onto a grid slot **places the task's oldest undated
session** — `db.first_undated_work_allocation_for_task` +
`db.set_work_allocation_times` in both create endpoints (`calendar.py`/
`projects.py` `create_allocation`) — rather than creating yet another
block, so repeated "+" sessions each get placed by one drag. A task drops
off the panel only when every one of its sessions is
dated. The card renders sessions in creation order ("Session 1/2/3", since
`list_work_allocations_for_task` now orders by creation time) with the
session's date+hour at the row's end (blank while undated). Undated
sessions are private placeholders and are skipped by every publishable
outlet (`events.ics` export and published event Lists), so they can never
leak out as DTSTART-less VEVENTs.

**Unscheduled-work panel rework (2026-08-14):** each planning grid's
"Unscheduled work" sidebar item is now a shared partial
(`_unscheduled_task_item.html`, imported `with context` by Calendar's Week
view and the project Week Calendar) showing, per task:
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
separate fields/mechanisms, but the global Tasks table (rendering the
shared `_task_row.html` macro) only showed "Due" — work-allocation status
was invisible on the primary task-management surface unless the detail
modal was opened. A "Scheduled" column was added next to "Due":
`{completed}/{scheduled}h` (rounded to one decimal) when the task has at
least one work allocation, an em-dash otherwise — plain text, not an
editable input, and a distinct header label, so it can't be mistaken for
the same kind of thing as the editable "Due" date cell.
`db.task_work_hours_bulk(conn, task_uids)` computes it for every row on a
page in one query (grouped by `task_uid`) instead of one
`list_work_allocations_for_task` query per row — wired into
`routers/tasks.py::list_tasks`, which attaches each task's totals as
`task["work_hours"]` before rendering (originally also wired into the now-
retired project detail page's Tasks view, which shared the same macro; see
§ Projects below). `db.task_work_hours` itself (single-task call sites: task
detail/edit modals) is unchanged. See `tests/test_task_scheduled_column.py`.
**This was 1.5's last piece — 1.5 is now fully shipped.**

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
navigate-to-result, the Relations picker wiring (`plans/open.md`'s Universal
command surface steps 1–4 and 6), and — **Command palette actions**, complete
2026-08-15 — step 5's context-dependent commands, additive to all of the
above:

- **Mark done** — a task result (not already `done`) gets a "Mark done"
  action button; posts to the existing `POST /tasks/{uid}/complete`
  unchanged.
- **Add label** — every result type gets an "Add label" button that
  retargets the same overlay into a third mode (label mode, alongside
  global/relation): type-to-filter over `GET /api/labels` (every label
  already in use — new, thin wrapper around `db.list_tag_names_in_use`),
  or type a brand-new name. Picking one posts `POST
  /api/entities/{task,event,contact}/{uid}/labels` (new; `{"label": ...}`).
  A task's add still goes through `db.upsert_task`'s full tags list (not
  `db.add_object_label` directly), so 1.5's single-project-per-task guard
  (`db.MultipleProjectLabelsError`) still applies — the palette is a fourth
  write path onto `tasks.tags`, not a bypass of the rule; events/contacts
  have no such constraint and use `db.add_object_label` directly.
- **Delete** — every result type gets a "Delete" action, confirmed via
  `window.ccConfirmSheet` (the same destructive-action convention as the
  rest of the app) before posting to the existing per-type delete route
  (`/tasks/{uid}/delete`, `/events/{uid}/delete`, `/contacts/{uid}/delete`).
- **Create** — global mode (not relation mode) now appends "Create task:
  '\<query>'" / "Create event: '\<query>'" rows whenever there's a query,
  mirroring relation mode's pre-existing "Create new" row. Picking one opens
  the ordinary new-task/new-event form (`CCModal.open`) with the typed text
  prefilled — `new_task_form`/`new_event_form` gained a `title` query param
  for this (`prefill_title` in the template context, `(task.title if task
  else (prefill_title or ''))` in `_task_form_fields.html`/
  `_event_form_fields.html`), blank for every other existing caller.

Action buttons only render in global mode — relation-picker rows exist to be
picked as a link target, not acted on. See `static/command_palette.js`'s own
header comment for the full three-mode shape. 28 new/updated tests
(`test_command_palette_actions.py`, plus one `test_search_api.py` assertion
updated for `_picker_result`'s new `status` field — a task's status, `None`
for the other two types, needed so the palette can hide "Mark done" on an
already-done task).

**Page navigation and Quick Capture**, complete 2026-08-15, both direct
follow-up feedback and both layered on top of global mode rather than new
modes of their own:

- **Page navigation** — global-mode results now also include the app's own
  pages: Dashboard/Calendar/Tasks/Contacts/Notes/Settings plus every Space
  (`generate_space=1` label), matched by title the same substring way
  entities are (`routers/search.py`'s `_matching_pages`, new). A page result
  is synthetic (`type: "page"`, no `uid`/tags/status that mean anything —
  `uid` doubles as its URL) and carries no action buttons; picking one is a
  plain `window.location.href` navigation, not `CCModal.open`, since a page
  replaces the whole view rather than layering a detail modal over wherever
  you already were. Excluded from relation-picker mode and from any request
  that already narrows `types` itself — a page isn't a link target, and an
  explicit type filter has already said it wants only that type.
- **Quick Capture** (`plans/quick-capture.md`) — a single-field capture
  syntax (`!t`/`!e`/`!c`/`!n` markers, `#label`s, dates, time ranges,
  phone/email) layered onto global mode's own input: typing a standalone
  marker token anywhere switches the results panel to a live-parsed preview
  (`GET /api/quick-capture/preview`, new `src/quick_capture.py` — a pure,
  `conn`-free parser, unit-tested directly against every example in the
  design doc) instead of search results, for as long as the marker is
  present; Enter posts the same raw text to `POST /api/quick-capture` (new
  `routers/quick_capture.py`), which parses again, resolves each `#label`
  through `db.resolve_capture_label` (exact match → learned alias → a high-
  confidence `difflib` fuzzy match, persisting a new alias on that path, per
  the design doc's own "user corrections may also be retained as aliases" —
  else a genuinely new label), and creates the right entity: a task (with
  its due date and any timeblocks, each a real `db.create_work_allocation`
  call), an event, a contact, or a **note** — the fourth entity type this
  added, see [`notes.md`](notes.md). Preview never resolves/persists a
  label itself (that would write a new alias on every debounced keystroke
  of a still-uncommitted label) — only an actual create does. `!n` is also
  what makes Notes findable afterward: `db.search_entities` gained a fourth
  `_search_notes` branch alongside tasks/events/contacts, so a captured note
  shows up in Ctrl-K/`/search` immediately, and the palette's Add label/
  Delete actions apply to it exactly like any other type (it just never
  gets a "Mark done" button — that's task-only). See
  `plans/quick-capture.md` for the full grammar and every simplification
  this v1 makes explicit (short-date year inference, the fuzzy-match cutoff,
  no interactive "suggested for correction" review step).

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

**Viewing pages — retired (2026-08-15 side work).** `/projects` (the square
card listing), `/projects/{name}` (the Tasks view), and
`/projects/{name}/calendar` (the Week Calendar view) are all **gone** —
direct feedback that they were redundant with capability that already
existed elsewhere: the Tasks view duplicated `/tasks?group_by=project`
(1.5); the Week Calendar view duplicated the merged `/calendar/week` grid
(2026-08-14 side work) filtered to one project, which already shows every
work allocation regardless of project. **Presentation-only** — every
lifecycle field/endpoint above (`promote`/`set_dates`/`demote`/`archive`,
`db.project_status`, `db.find_overlapping_project`, `project_label_for`'s
supersession) is completely unchanged, still reached from Settings > Labels.
All three old paths now just redirect (`routers/projects.py::
list_projects_redirect`/`project_detail_redirect`/`project_calendar_redirect`
— `GET /projects` → `/tasks?group_by=project`, `GET /projects/{name}[/
calendar]` → `/tasks?label={name}`), so any bookmark still lands somewhere
real, same precedent as `/today`/`/week`/`/calendar/timetable`'s own
retirements (`features/today.md`, `features/week.md`). `base.html`'s
"Projects" tabbar entry is gone; the Dashboard's `quick_links` widget tiles
and `_widget_project_preview.html`'s per-project rows both now link to
`/tasks?label={name}` instead of the old detail page. `_project_card` (the
card-data helper the deleted pages used) was removed along with them —
project progress as a Dashboard-visible number still exists via the
`project_preview` widget's own independent tasks-done/total computation
(`routers/dashboard.py::_render_project_preview`), unaffected by this.

**Still open, deferred:** hour-based project progress (every remaining
progress readout — `project_preview`'s widget — is still completed/total
*task count*; `db.task_work_hours` exists per-task since 1.4 slice 1 but
nothing aggregates it to project level). Hiding a completed task's future
allocations from the active calendar. Both pre-date this retirement and
are unaffected by it.
