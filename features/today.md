# Today

`GET /today` (`routers/today.py::today_view`), the first surface of 1.7
(Information architecture & view surfaces, `plans/open-priority.md` §
Information architecture & view surfaces' "Today — execution" bullet):
"What am I dealing with now?" A single-page operational view of the current
day, distinct from the Dashboard's broader orientation widgets. No separate
Today data model — everything is read straight off `db.list_events`/
`list_tasks` and the shared derived-state aggregation service (1.1,
`src/derived_state.py`) each request.

## Sections

- **At-a-glance strip** (reuses `_widget_at_a_glance.html`'s own CSS
  classes) — overdue count, due-today count, today's event count, and
  today's total scheduled work hours.
- **Due & overdue** — every open task whose `due_at` is today or earlier
  (`overdue_tasks` + `due_today_tasks`), most-overdue first, each row a
  plain "mark done" checkbox + link, same idiom as the Dashboard's
  `today_agenda`/`overdue_tasks` widgets.
- **Today's schedule** — today's events, split into two kinds:
  - ordinary calendar events (`calendar_events`)
  - scheduled task work (`scheduled_work`) — today's work-allocation events
    (`db.work_allocation_task_uid`, the same per-event lookup
    `routers/projects.py::project_calendar` uses to tell a work allocation
    apart from an ordinary event), each showing its task link and hours.
- **Important & urgent, not due today** (`important_upcoming`) — open tasks
  whose `derived_state.virtual_states` includes `important` or `urgent`,
  excluding anything already shown in Due & overdue above (no task appears
  twice on the page). Capped at 8, sorted by effective importance, then
  effective urgency, then due date.

## Notes

- Added a `/today` tab to the primary tabbar (`base.html`), right after
  Home — `active_tab == "today"`.
- Nothing here is stored; a reload always reflects current task/event state,
  same as every other page in this app.
- Week (planning) and Spaces (context), 1.7's other two surfaces, are
  separate, later slices — see `plans/STATE.md`.
