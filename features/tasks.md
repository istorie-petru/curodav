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

## Auto-archive

`TASK_AUTO_ARCHIVE_DAYS_KEY` ("Never"/7/14/30/90), lazy `_auto_archive_if_configured`
DELETE on each Table visit.
