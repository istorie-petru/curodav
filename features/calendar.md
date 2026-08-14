# Calendar

`routers/calendar.py` — four views over the universal `events` pool (plus tasks
shown as chips in day cells). No per-calendar partitioning; organization is by
label, and an event's color is its first (alphabetical) label's color
(`_annotate_calendar_colors`).

## Views

- **Month** (`/calendar`) — one flat per-day list: all-day colored rows → timed
  events → tasks; `MONTH_MAX_VISIBLE_ITEMS=4` then "+N more" → Day view.
- **4-Week** (`/calendar/fourweek`) — a continuous 28-day window whose current
  week sits in a configurable row 1–4 (Settings → General); prev/next move one
  week.
- **Week** (`/calendar/week`) — single-pane 24-hour grid, fits viewport and
  scrolls internally (`grid_layout.py` overlap packing), all-day strip + task
  chips.
- **Day** (`/calendar/day/{date}`) — same grid for one day; `/calendar/agenda`
  redirects here (the old agenda page was merged then removed).

A segmented subnav switches views while preserving the label filter.

## Recurrence

`recurrence_expand.expand_events` expands recurring events across the visible
window; RRULE is free text with a `recurrence_picker.js` helper.

**Non-working-day policy** (1.6, "Generalized recurrence and the non-working-
day policy"): any recurring event can set `holiday_calendar` (a named,
reusable holiday calendar — `db.list_holiday_calendar_names`/
`db.list_holidays_by_calendar`, see `features/schedule.md`), `exclude_saturday`,
and `exclude_sunday` — three independent constraints, not one enum. Applied at
*read* time (`expand_events`'s optional `holiday_calendars` param, passed by
every caller as `db.list_holidays_by_calendar(conn)`), never materialized into
`exdates_json` — a holiday added/removed or an event's own policy change takes
effect immediately, on every view, with no regenerate step. `_event_form_
fields.html` exposes all three on the event form (Holiday calendar text field
+ datalist, Exclude Saturday/Sunday checkboxes).

## Interactions

- **Drag to move / resize** on Week/Day (15-min snap) → `POST /events/{uid}/reschedule`
  (JSON, no reload).
- **Drag-to-create all-day spans** on Month/4-Week → `POST` via
  `/events/new?date=&end_date=` (all-day prefill).
- `.calendar-create-col` for timed create on Week/Day.
- Label filter via the single-select fancy dropdown (`_calendar_filters.html`).

## Event CRUD & fields

Routes: `/events/new`, `POST /events`, `/events/{uid}` (read-only detail page),
`/events/{uid}/edit`, `POST /events/{uid}`, `/events/{uid}/delete`,
`/events/{uid}/reschedule`. Fields: title, description, start/end, all-day,
location, meeting URL, labels, recurrence, reminders (minutes before). `_NONE_LIKE`
cleanup normalizes literal "None"/"Nothing" strings.

## Relations & education

- **Event ↔ task links** (`event_task_relations`): link existing, or "+ New
  task…" that inherits the event's labels; gated by a shared label.
  `_event_relations.html`; `POST /events/{uid}/relations`,
  `/events/{uid}/relations/remove`.
- **Next lectures** badge strip (`_education_next_lectures.html`) when filtered to
  a Space label that has schedule classes.
