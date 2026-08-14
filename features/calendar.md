# Calendar

`routers/calendar.py` — four views over the universal `events` pool (plus tasks
shown as chips in day cells). No per-calendar partitioning; organization is by
label, and an event's color is its first (alphabetical) label's color
(`_annotate_calendar_colors`).

## Views

- **Month** (`/calendar`) — one flat per-day list: all-day colored rows → timed
  events → tasks; `MONTH_MAX_VISIBLE_ITEMS=4` then "+N more" → Day view.
  Timetabled tasks (work-allocation events) are excluded entirely
  (`db.work_allocation_event_uids`, filtered before `_month_grid` runs) —
  they'd just duplicate the task's own due-date chip; Week is where they're
  meant to be prominent. Non-recurring event chips (all-day and timed) are
  **draggable to a different day cell** (`static/calendar_month_drag.js`,
  alongside the existing click-and-hold drag-to-*create* script) — reuses
  `POST /events/{uid}/reschedule`, shifting the event's start/end by the
  whole-day delta between origin and drop cell, time-of-day untouched. A
  recurring event's chip renders with no `data-uid` at all, so it's not
  draggable (dragging one occurrence would reschedule the whole series) —
  click still opens it normally. On drop the page reloads (a Month move can
  shift an item across two cells' own overflow-count/"+N more" state, which
  only a fresh render keeps consistent, unlike the Week grid's single-block
  optimistic move).
- **4-Week** (`/calendar/fourweek`) — a continuous 28-day window whose current
  week sits in a configurable row 1–4 (Settings → General); prev/next move one
  week.
- **Week** (`/calendar/week`) — single-pane 24-hour grid, fits viewport and
  scrolls internally (`grid_layout.py` overlap packing), all-day strip + task
  chips. **Merged with the former "Timetable" sub-view** (1.9 side work,
  2026-08-14, direct feedback: "merge the calendar's week view with the
  timetable view") — ONE grid now carries both capabilities at once, not two
  separate pages:
  - Ordinary calendar events stay fully interactive, exactly as before the
    merge: draggable/resizable (`static/calendar.js`, `POST
    /events/{uid}/reschedule`), clickable to open, and empty grid space still
    drag-creates a new event (`.calendar-create-col`).
  - Every work-allocation event (a task's scheduled work session) renders
    prominently as a draggable `.work-allocation` block
    (`static/project_calendar.js`, form-POST move/resize/delete, block only,
    never the task, endpoints under `/calendar/week/allocations...`)
    alongside an "Unscheduled work" sidebar that drags a task onto the grid
    to create/place a session. A task stays on the panel as long as any of
    its work sessions is still **undated** (the task modal's Work sessions
    "+" button adds one with no date yet), and dragging such a task onto a
    slot **places that session** (the oldest undated one) rather than
    creating another block, exactly as `/week` and the project Week Calendar
    do (see `features/tasks.md` § Work allocations). A plain click anywhere
    on a scheduled block's body (not a drag, not the delete button, not the
    resize handle) opens the block's task **view modal** via
    `project_calendar.js` interaction 4 (`taskUrlBase` config) — same
    behavior the sibling planning grids (`/week`, the project Week Calendar)
    have. The title (`.te-name`) is a plain `<span>`, not a nested `<a>`
    (direct feedback, immediate follow-up: "why can't it function like any
    other event so that the whole div is a link and can be moved at the
    same time?") — the block can't itself be a real `<a>` (it also contains
    a delete `<form>`/`<button>`, invalid inside `<a>`), so instead the
    title dropped link semantics and the WHOLE block, title text included,
    is one uniform drag target, matching an ordinary `.time-event`
    (itself a single `<a>`, draggable from anywhere on itself). Before this,
    the title was a real nested `<a>` that `project_calendar.js`'s
    pointerdown handler had to exclude from drag-start so its native click
    could navigate — meaning a block couldn't be moved by grabbing its
    title specifically.
  - Grid columns carry BOTH `.calendar-create-col` (calendar.js) and
    `.project-calendar-col` (project_calendar.js) so both scripts'
    interactions coexist; `calendar.js`'s own `.time-event` selector
    excludes `.work-allocation` (`:not(.work-allocation)`) so the two
    scripts never double-attach a pointerdown handler to the same block, and
    `style.css`'s planning-surface cursor override
    (`.project-calendar-col{cursor:default}`, which kills the "click-drag to
    create" cursor on the *planning-only* grids `/week`/the project Week
    Calendar) is scoped with `:not(.calendar-create-col)` so Week keeps the
    create-drag cursor.
  - The "Unscheduled work" sidebar is **collapsible** — a header button
    (`static/unscheduled_panel_toggle.js`) collapses it to a narrow rail,
    state persisted per-device (`localStorage`, no server involvement).
  - A `.work-allocation` block is a **thick colored border, never a solid
    fill** (direct feedback, immediate follow-up) — its `.cal-<hue>` class
    no longer paints the background; a `style.css` override (after the
    `.cal-*` swatch block, so it wins) gives it `background:var(--bg-
    elevated)` and `border:3px solid var(--wa-border)`, `--wa-border` set
    inline per block to the hue's own `var(--cal-bg-<hue>)`.
  - The task-panel drag's preview always shows the real drop size —
    `window.__ccGridDragActive` (set by every `project_calendar.js` drag)
    tells `calendar.js`'s own 30-minute hover-preview ghost to stand down
    while a scheduling drag is in progress (it would otherwise also render,
    since these columns carry `.calendar-create-col` too), and
    `project_calendar.js` shows its own grid-anchored preview sized to
    exactly `DEFAULT_BLOCK_MINUTES` (60) at the snapped drop position.
  - `GET /calendar/timetable` and the old `/calendar/timetable/allocations`
    endpoint trio are gone; `/calendar/timetable` redirects to
    `/calendar/week` (any old bookmark still lands somewhere real).
- **Day** (`/calendar/day/{date}`) — same grid for one day; `/calendar/agenda`
  redirects here (the old agenda page was merged then removed).

**Sleep Time / Leisure Time (1.9 side work, Settings > Sleep & Leisure
Time)** — weekly recurring guidance hours (`db.time_blocks`, no date
component, just a `"HH:MM"` range + day-of-week set), rendered as a soft
diagonal hatch behind the grid on both Week and Day (`.time-block-overlay
.time-block-sleep`/`.time-block-leisure`, red/green via `var(--danger)`/
`var(--success)`, `pointer-events:none` so every drag interaction passes
straight through it) — `routers/calendar.py::_time_block_overlays_for_day`
resolves each day's applicable blocks by weekday name
(`date.strftime('%A')`, matching `db.TIME_BLOCK_DAYS`'s own storage
format) into top/height px, same math `grid_layout.position_event` uses
for a real event. Purely advisory, never a hard constraint: dropping an
event (`static/calendar.js`) or a work-allocation block/create-drag
(`static/project_calendar.js`) onto an overlapping slot still saves
normally, but a shared `static/time_blocks.js` (loaded only on
`calendar_week.html`/`calendar_day.html`, reading a page-local
`<script type="application/json" id="cc-time-blocks">` payload built by
`routers/calendar.py::_time_blocks_client_payload`) shows a `toast-warning`
toast ("Heads up: this overlaps Sleep Time...") alongside the save. Month
has no time-of-day axis at all, so neither the hatching nor the warning
apply there. Config lives in Settings > Sleep & Leisure Time
(`features/settings.md`).

**Unscheduled-work panel (2026-08-14)** — each panel item (shared
`_unscheduled_task_item.html` partial, same on Week, `/week`, and the
project Week Calendar) shows a **−/count/+ session stepper** ("+" adds an
undated session placeholder via `POST /tasks/{uid}/work-allocations`; "−"
removes the most recently added undated one via `/remove-latest`, hidden at
zero undated sessions) — the count reflects sessions still needing
placement, not the task's total session count. **Unschedule doesn't delete**
— dragging a block back onto the panel (or its ✕) clears that ONE session's
start/end back to undated (`db.unschedule_work_allocation`), so the task's
overall session count never changes just from scheduling/unscheduling a
block. The create drag is **pointer-based** (a ghost follows the cursor, the
grid auto-scrolls near its top/bottom edge), and block move/resize has
pointercancel revert + scroll-aware positioning. See `features/tasks.md` §
Work allocations.

A segmented subnav (Month/4-Week/Week/Day) switches views while preserving
the label filter.

## Recurrence

`recurrence_expand.expand_events` expands recurring events across the visible
window; RRULE is free text with a `recurrence_picker.js` helper.

**Recurrence end condition** (side work, shipped 2026-08-14): the picker's
FREQ presets (Daily/Weekly/Monthly/Yearly) gained an "Ends" sub-panel —
Never (no suffix), "On date" (`UNTIL=YYYY-MM-DD`, the app's existing
dashed-date convention normalized at export time by
`ical_rows.py::_normalize_rrule`), or "After N occurrences" (`COUNT=N`).
Entirely client-side (`recurrence_picker.js::parseValue`/`endsSuffix`) —
`routers/calendar.py`'s `create_event`/`update_event` still do zero
server-side parsing of `recurrence`, same as every other preset. On reload,
`parseValue` strips any `UNTIL=`/`COUNT=` token from the stored string before
matching it against a FREQ preset, so an existing end condition round-trips
into the "Ends" radios instead of falling through to the raw Custom field.
The Ends group only shows once a real preset (not "Does not repeat", not
Custom — Custom already manages `UNTIL=`/`COUNT=` as free text) is selected.
`COUNT=` needed no expansion-side changes: `recurring_ical_events` (already
this app's expansion library, see this section's own note above) resolves it
for free, same as `UNTIL=`; see `test_recurrence_expand.py`'s
`test_count_recurrence_*` tests.

**Custom RRULE option removed** (side work, shipped 2026-08-14): direct
follow-up ("remove the custom option for recurring") — the free-text
"Custom RRULE" row is gone from `recurrence_picker.js`; the five fixed
presets (Does not repeat/Daily/Weekly/Monthly/Yearly) plus their Ends
sub-choice are now the only thing the picker UI can produce. An existing
recurrence value that doesn't match one of the five presets (e.g. a
hand-authored `BYDAY=...` rule, or anything written directly via the API or
Schedule) is left with **no preset radio checked** and shown read-only as
the trigger's summary text — `sync()` only overwrites the hidden input once
a preset is actually selected, so opening and closing the form can never
silently clobber a rule this picker doesn't model. Selecting any preset does
replace it, same as switching between any two presets always has.

**Ends is its own dropdown** (side work, shipped 2026-08-14): direct
follow-up ("could we make ends another drop down menu?") — the Ends choice
(Never/On date/After N occurrences) moved out of a sub-panel nested inside
the FREQ dropdown into a second, separate `.multiselect` dropdown
(`recurrence-ends-select`), a sibling of the FREQ preset dropdown, reusing
the exact same markup contract (`.multiselect-trigger`/`.multiselect-panel`)
so `app.js`'s generic multiselect click/portal/position handling picks it up
for free — no JS changes needed there. Hidden entirely until a real preset
(not "Does not repeat") is selected, same rule as before, just applied to
`endsWrap.hidden` instead of a nested group's.

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
