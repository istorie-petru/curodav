# Tasks

`routers/tasks.py` — four views over the universal `tasks` pool. Statuses
`active / in_progress / waiting / done / archived`; priorities 1–4; progress is
derived from status (`_progress_for_status`).

## Views (shared `_tasks_toolbar.html`)

- **Table** (`/tasks`) — open/completed split into two tbody sections; sortable
  (title/due/priority/status); inline pill-selects for status/priority + date
  cell → `POST /tasks/{uid}/update-field` (JSON, single field, no reload);
  bulk-actions bar (checkbox select → `POST /tasks/bulk` with `delete`/`status`/
  `tag` add-remove); subtask-aware delete confirmation.
- **Board** (`/tasks/board`) — kanban columns per status (archived excluded),
  pointer-event drag-drop (`DRAG_THRESHOLD=6`), optimistic move via the same
  `update-field` endpoint.
- **Timeline** (`/tasks/timeline`) — Gantt via `timeline_layout.py`; gutter
  grouped by label blocks (+ "(No label)"); swimlanes, zoom-aligned range,
  day/week headers; drag reschedule/resize →
  `POST /tasks/{uid}/timeline-reschedule`, vertical lane drag →
  `/tasks/{uid}/timeline-lane` (persisted `timeline_lane`), click-drag-create →
  `POST /tasks/timeline/create`. Double-click opens the card.
- **Habits** (`/tasks/habits`) — see `habits.md`.

Search box + four inline fancy dropdowns (Date / Status / Priority / Label) in
row 1, all submitting immediately; active-filter badge. Filters AND together.

## Recurring tasks / completions

RRULE recurrence; checking off records a daily completion → heatmap + current/
longest streaks on the detail page. Endpoints: `POST /tasks/{uid}/complete`,
`/tasks/{uid}/completion/{date}/toggle`, `POST /tasks/{uid}/completions`
(explicit value).

## Subtasks & relations

Checklist and subtasks merged (2026-08-08) into one "Relations" card — real
subtasks (`parent_uid`) with inline quick-add; cascade delete to subtasks.
Task ↔ event links via `event_task_relations` (shared-label rule),
`_task_relations.html`; "+ New event…" inherits task labels.

## Auto-archive

`TASK_AUTO_ARCHIVE_DAYS_KEY` ("Never"/7/14/30/90), lazy `_auto_archive_if_configured`
DELETE on each Table visit.
