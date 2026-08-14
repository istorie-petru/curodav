# Week (planning)

`GET /week` (`routers/week.py::week_view`), 1.7 slice 2 (Information
architecture & view surfaces, `plans/open-priority.md` § Information
architecture & view surfaces' "Week — planning" bullet): "How should I
allocate my time over the coming week?" A cross-project scheduling surface
over the same week-grid geometry `routers/calendar.py::week_view` and
`routers/projects.py::project_calendar` already render
(`grid_layout.layout_day`) — this is a third *purpose* over that geometry,
not a third implementation of it.

## What it shows

- **Unscheduled work** (left panel) — every open task with no work
  allocation at all yet, across every project (or none), each showing its
  project label (`db.project_label_for`) if it has one and its due date if
  set. Sorted by due date, soonest first; no-due-date tasks last. Same
  "already-allocated tasks drop off the list entirely" rule
  `routers/projects.py::project_calendar`'s own unscheduled list uses, just
  not scoped to one project.
- **The week grid** (right) — every event in the week; every work-allocation
  event (`db.work_allocation_task_uid`) renders prominently regardless of
  which task/project it belongs to (unlike the project-scoped calendar,
  which only prominents ONE project's own allocations); ordinary events
  render as subdued context (`.context-event`).
- **Due-date chips** — open tasks due each day appear in that day's all-day
  strip, same idea as `routers/calendar.py::week_view`'s own `day_tasks`.

## Scheduling interaction

Drag an unscheduled task onto the grid to create a work allocation
(`POST /week/allocations`); drag an existing block to move it, or its resize
handle to resize it (`POST /week/allocations/{event_uid}/move`); delete
removes only the block, never the task (`POST
/week/allocations/{event_uid}/delete`, `db.delete_work_allocation`). All
three are the same shape as `routers/projects.py`'s
`create_allocation`/`move_allocation`/`delete_allocation`, just without the
"must carry this project's label" scoping — any open task is a valid target
on this global page. The client-side drag/move/resize logic is
`static/project_calendar.js` reused verbatim (its own
`window.PROJECT_CALENDAR` config object, just pointed at `/week/allocations`
instead of a project's own endpoint) — no second copy of that JS.

## Relationship to other week-shaped pages

- `routers/calendar.py::week_view` (`/calendar/week`) is the **management**
  surface for events — "what's on my calendar this week."
- `routers/projects.py::project_calendar` (`/projects/{name}/calendar`) is
  **one project's own** scheduling surface — "when can I do THIS project's
  work."
- This page is the **global planning** surface — "how do I spend the week
  overall," across every project's unscheduled work at once.

All three render the same underlying `events`/`event_task_relations` data,
just projected differently — no duplicated management logic, per
`open-priority.md`'s "Core management views" note.

## Notes

- Added a `/week` tab to the primary tabbar (`base.html`), after
  Calendar — `active_tab == "week"`.
- No "available time" number is computed — same interpretation
  `project_calendar` already established for the spec's identical language:
  open grid space visually communicates availability, no separate
  calculation.
- A freshly-unscheduled task's `hours.remaining` is always 0.0h (it has no
  allocations yet — `db.task_work_hours` is derived entirely from actual
  allocations, not a separate estimate field). Same pre-existing display
  quirk `project_calendar`'s own unscheduled list has; not addressed here.
