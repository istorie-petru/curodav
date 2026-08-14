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
- **Timetable** (`/calendar/timetable`) — the Week (planning) surface
  (`/week`, see `features/week.md`) copied into the Calendar page as a
  fifth sub-view, exactly how `/week` renders it: columns
  `.time-col.project-calendar-col`, work allocations prominent and
  draggable (`.work-allocation`, form-POST move/resize/delete, block only
  never the task), ordinary calendar events subdued context
  (`.context-event`). An "Unscheduled work" sidebar   drags onto the grid to
  create a work allocation (`POST /calendar/timetable/allocations`), and a
  scheduled block dragged back onto the panel is unscheduled (deleted,
  task kept). A task stays on the panel as long as any of its work
  sessions is still **undated** — the task modal's Work sessions "+" button
  adds a session with no date yet (`db.create_work_allocation` with neither
  start nor end), and dragging such a task onto a slot **places that
  session** (the oldest undated one) rather than creating another block,
  exactly as `/week` and the project Week Calendar do (see
  `features/tasks.md` § Work allocations). A plain click anywhere on a
  scheduled block's body (not a drag, not the delete button, not the
  resize handle) opens the block's task **view modal** — not the edit
  form — via `project_calendar.js` interaction 4 (`taskUrlBase` config,
  same destination as the block's own title link). The same whole-block-
  click and task-view title apply on the sibling planning grids (`/week`
  and the project Week Calendar), which also override the shared
  `.time-col`
  `cursor:copy` (the Calendar grid's drag-to-create affordance) to plain
  `default` via `.project-calendar-col` — empty-space drag on a planning
  grid isn't a create gesture, so the misleading "add" mouse is gone there.
  Only `static/project_calendar.js` runs, reused verbatim with a
  `window.PROJECT_CALENDAR` config pointed at the timetable's own
  endpoints. Adding normal calendar events is done via the page's calendar
  chrome (the New button, or the Week/Day views), not on the scheduling
  grid. The standalone `/week` page and tab remain for backwards
  compatibility.

  **Unscheduled-work panel (2026-08-14)** — each panel item (shared
  `_unscheduled_task_item.html` partial, same on `/week` and the project
  Week Calendar) now shows a **scheduled/total hours x/y** next to the task
  title and a **−/count/+ session stepper** ("+" adds an undated session
  placeholder via `POST /tasks/{uid}/work-allocations`; "−" removes the most
  recently added one via `/remove-latest`, hidden at count 1). **Unschedule
  now collapses** — dragging a block back onto the panel (or its ✕) deletes
  *all* the task's sessions and leaves exactly one undated one
  (`db.collapse_task_work_allocations`), so the task returns to the panel at
  a count of one. The create drag is **pointer-based** (a ghost follows the
  cursor, the grid auto-scrolls near its top/bottom edge), replacing the old
  native HTML5 drag-and-drop, and block move/resize gained pointercancel
  revert + scroll-aware positioning. See `features/tasks.md` § Work
  allocations.

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

**Manual recurrence exceptions** (1.6, shipped 2026-08-14): a specific
occurrence can be cancelled or moved/modified without touching the master's
own recurrence rule — three distinguished things, per `open-priority.md`'s
spec: the rule (`events.recurrence`), the generated occurrences (computed,
never stored), and manual per-occurrence overrides
(`event_occurrence_overrides` table, `db.py`'s own CREATE TABLE comment has
the full model). A cancelled occurrence folds its date into the master's own
EXDATE list at expand time (the same proven exclusion mechanism
`exdates_json` already used); a moved/modified occurrence becomes a second
real VEVENT sharing the master's UID with a `RECURRENCE-ID` — the standard
RFC 5545 override, which `recurring_ical_events` (already this app's
expansion library) resolves for free
(`recurrence_expand.py::_build_override_component`/`expand_events`'s
`overrides_by_master` param, `db.list_event_occurrence_overrides_by_master`).
Every expanded occurrence carries its own original slot as `occurrence_date`
(the RECURRENCE-ID `recurring_ical_events` tags every occurrence with, even
non-overridden ones — `ical_rows.py::ical_to_event_row`), which
calendar_month/week/fourweek/day.html append to each occurrence's own link
(`?occurrence_date=...`) so `event_detail.html`'s "This occurrence" card
(Cancel / Move / Restore, `POST /events/{uid}/occurrences/cancel`
`/move` `/restore`) always targets the right instance, even one that's
already been moved once.

**Note:** `db.list_events`'s date-range query had a real bug (found while
building this: a recurring row's own literal `start_at`/`end_at` only anchor
its *first* occurrence, but the SQL filter excluded the whole row once the
queried window fell far enough past that anchor, regardless of whether the
RRULE would still generate real occurrences inside it) — fixed alongside this
subsection; a recurring row (`recurrence IS NOT NULL`) is now always a query
candidate, and `expand_events` is what actually decides whether it produces
anything in the window.

**Configurable terminology** (1.6, shipped 2026-08-14): Settings > General's
"Recurrence terminology" toggle (`standard`/`playful`, app_meta-backed via
`deps.py`'s `RECURRENCE_TERMINOLOGY_KEY`/`recurrence_terminology()` Jinja
global, same pattern as Week starts on/Time format) swaps only the *on-screen
label* of the holiday-calendar/weekend controls on `_event_form_fields.html`
and `schedule_classes.html`'s Settings panel — "Holiday calendar" / "Exclude
Saturday" / "Exclude Sunday" (standard) vs. "Respects Labor Laws" / "Marx
Weekend: Saturday" / "Marx Weekend: Sunday" (playful). The underlying
`holiday_calendar`/`exclude_saturday`/`exclude_sunday` field names, form
field `name=` attributes, database columns, and API shape never change —
presentation-layer only, per `open-priority.md`'s own framing.

**1.6 (Schedule & recurrence rework) is now fully shipped** — see
`plans/roadmap.md`'s 1.6 row and `features/schedule.md`.

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
