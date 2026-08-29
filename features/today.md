# Today — retired, folded into the Dashboard (1.9 side work)

`GET /today` (`routers/today.py::today_view`) shipped in 1.7 slice 1
("Today — execution", `plans/open-priority.md` § Information architecture &
view surfaces). It is **retired** — `routers/today.py`,
`templates/today.html`, and `tests/test_today.py` are gone. `GET /today` now
redirects (302, `routers/dashboard.py::today_redirect`) to `/`, the same
"any bookmark still lands somewhere real" precedent this repo already
established for `/calendar/timetable` (see `features/calendar.md`).

## Where its content lives now

Before this page existed, the Dashboard already covered most of what it
showed (via `today_agenda`/`at_a_glance`/`overdue_tasks`); the two sections
that were genuinely unique to `/today` became their own Dashboard widget
types (`routers/dashboard.py`'s `WIDGET_TYPES` registry), addable/removable/
stackable/scopable exactly like every other widget:

- **Important & urgent, not due today** became the `important_urgent`
  widget type. Both that widget type and the Importance/Urgency feature
  behind it (`src/derived_state.py`) are since removed outright — no
  longer something this app offers.
- **Scheduled work hours today** (the at-a-glance strip's "scheduled work"
  stat + the "Today's schedule" list's work-allocation half) → the
  `scheduled_work_today` widget type (`_render_scheduled_work_today` /
  `_widget_scheduled_work_today.html`). Same `db.work_allocation_task_uid`
  lookup /today used to tell a work-allocation event apart from an ordinary
  one, plus a completed-hours-today total.
- Everything else /today showed (overdue/due-today tasks, today's ordinary
  calendar events) already had a direct Dashboard equivalent
  (`today_agenda`/`overdue_tasks`).

See `features/dashboard.md` for the full widget registry, including these
two.

## Notes

- The `/today` tabbar entry is gone (`base.html`) — Home, Calendar, Tasks,
  Projects, Schedule, and Contacts remain.
- No data was lost at the time of the port: both new widget types read the
  exact same `db.list_tasks`/`db.list_events`/`src/derived_state.py` sources
  /today did, confirmed working (rendered + tested) before /today's own
  router/template/tests were deleted, per this session's own content-loss
  guard.
