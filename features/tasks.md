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

**UI shipped so far:** a "Work sessions" card on the task detail/edit modals
(`_task_work_allocations.html`, `POST /tasks/{uid}/work-allocations` +
`/work-allocations/remove`) — a plain start/end datetime form, the
functional (non-drag) way to schedule a block today. **Not yet built:** the
project's Week Calendar view (the drag-and-drop surface the spec describes —
dragging a task onto a calendar block to create/resize/split an allocation),
and wiring `_project_card`'s `progress` to real scheduled-work hours instead
of task count (`db.task_work_hours` exists per-task; nothing yet aggregates
it to project level or hides a completed task's future allocations from the
active calendar — both explicitly deferred to the slice that builds the
calendar view, per `plans/STATE.md`'s 1.4 breadcrumbs).

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

**Deferred to 1.4/1.5** (not built): the project's own Tasks view + Week
Calendar view, hour-based project-card progress, the global Tasks page's
project grouping. A card's "Open" link goes to the label's existing
generated page (`routers/labels.py`'s `label_detail`) in the meantime. Work
allocations themselves (the underlying data model + a plain-form way to
schedule one) shipped as 1.4's first slice — see "Work allocations (1.4)"
above; the project-specific drag-and-drop calendar surface and the card
progress swap are still open.
