# State

Single source of truth for "where are we right now." Read this file — and
only this file — at the start of a session working toward 2.0. Don't re-read
`roadmap.md` / `open-priority.md` / `open.md` in full; they're expanded specs
for reference, not session-start context. Update this file at the end of every
session, right before the final commit of that session.

## Right now

- **Shipped:** `1.3`, complete (2026-08-13) — project-enabled label stack:
  `label_config.is_project` + `start_date`/`end_date`/`archived_at`, the
  computed Open/Pending/Pending Archiving/Archived lifecycle
  (`db.project_status`), the overlap rule (`db.find_overlapping_project`),
  `project_label_for`'s supersession (an explicit `is_project=1` label now
  wins over the old "first non-Space label" heuristic), and the dedicated
  `/projects` page (`routers/projects.py`) with promote/dates/demote/archive
  actions and progress cards. See `features/tasks.md` § Projects.
- **Shipped:** `1.4` slice 1, complete (2026-08-13) — work allocations' data
  model + semantics: `event_task_relations.is_work_allocation`,
  `db.create_work_allocation`/`list_work_allocations_for_task`/
  `task_work_hours`/`delete_work_allocation`/`work_allocation_task_uid`,
  title-sync both directions (`upsert_task` -> allocation events; editing an
  allocation event's title -> the task), and a plain-form "Work sessions"
  card on the task detail/edit modals (`POST /tasks/{uid}/work-allocations`
  [`/remove`]). See `features/tasks.md` § Work allocations (1.4). 20 new
  tests (`test_work_allocations.py`).
- **Shipped:** `1.4` slice 2, complete (2026-08-14) — the project detail
  page: `GET /projects/{name}` (`routers/projects.py::project_detail`) and
  its Tasks view (every task carrying the project's label, open/completed
  split, the same interactive row — pill-selects, inline due date,
  delete-with-undo — the global Tasks page uses, extracted into a shared
  `_task_row.html` macro so neither page duplicates the markup). "+ New
  task" opens `/tasks/new?project=<name>`, which now pre-checks that label
  on the form even for a brand-new project with no tasks yet (a real gap
  `list_tag_names_in_use` alone had — fixed in `new_task_form`). Project
  cards' "Open" link now points here instead of `label_detail`. See
  `features/tasks.md` § Projects, "Project detail page + Tasks view". 12
  new tests (`test_project_detail.py`), full suite 980 passed.
- **Shipped:** `1.4` slice 3, complete (2026-08-13) — the project's **Week
  Calendar view**: `GET /projects/{name}/calendar`
  (`routers/projects.py::project_calendar`), reusing the global Week grid's
  own layout math (`grid_layout.layout_day`) rather than duplicating it. An
  "Unscheduled tasks" list (open project tasks with no work allocation yet,
  `{project} > {task} · {remaining}h` items using `db.task_work_hours`, not
  `_task_row.html`) drags onto the grid to create a work allocation
  (`create_allocation` -> `db.create_work_allocation`); existing blocks
  drag to move/resize (`move_allocation`, a plain `start_at`/`end_at` edit)
  or delete (`delete_allocation` -> `db.delete_work_allocation`, block
  only, never the task). Ordinary events and other projects' allocations
  render as subdued context (`.context-event`); this project's own
  allocations are prominent (`.work-allocation`). Added a Tasks/Week
  Calendar tab switcher to `project_detail.html`, following
  `calendar_week.html`'s own `.segmented.calendar-subnav` precedent. This
  was the last piece of "Project pages & views" and closes out 1.4's main
  line — see `features/tasks.md` § Projects, "Week Calendar view". 15 new
  tests (`test_project_calendar.py`), full suite 995 passed. **1.4 is now
  fully shipped** (`pyproject.toml` bumped to `1.4.0`); still open and
  deliberately deferred (doesn't block 1.5+): `_project_card`'s `progress`
  wired to real `db.task_work_hours` totals (still the 1.3 task-count
  proxy), and hiding a completed task's future allocations from the
  calendar (`open-priority.md` § Task & calendar semantics' "future
  allocations are hidden" rule).
- **Shipped:** `1.5` slice — **single-project-per-task**, complete
  (2026-08-13) — `db.upsert_task`'s `tags` argument now rejects a label set
  carrying more than one `is_project=1` label at once
  (`db.MultipleProjectLabelsError`, raised before anything is written, so a
  rejected call leaves no partial write). Wired into the task create/edit
  forms (`routers/tasks.py`'s `create_task`/`update_task`, surfaced as
  `HTTPException(400, ...)`, same convention as this app's other plain-form
  validation errors) and the Tasks page's bulk "Add label" action (`POST
  /tasks/bulk`, applied per-uid so non-conflicting tasks in the same batch
  still get their label, 400 with the rejected uids listed) — the three real
  paths that could put a second project label on a task. No client-side
  prevention in the labels picker itself (`_widget_list_multiselect.html` is
  shared by tasks/events/contacts/habits with no project concept); rejecting
  server-side with a clear message was the smaller, more consistent change.
  Enforcement is write-boundary only — a pre-existing task with two project
  labels (direct DB edit, restored backup) is left untouched until something
  next writes new tags for it, confirmed by test. See `features/tasks.md`
  § Task model, 12 new tests (`test_single_project_per_task.py`), full suite
  1007 passed.
- **Shipped:** `1.5` slice — **Tasks page groupable by project**, complete
  (2026-08-13) — `GET /tasks` takes a `group_by` query param (`"none"`
  default/absent, fully backward-compatible with existing links/bookmarks;
  `"project"`). `group_by=project` clusters the Table view's open/completed
  splits under project-name headers (`routers/tasks.py::
  _group_tasks_by_project`, reusing `db.project_label_for` — the same
  per-task "which label is the project" lookup the project detail page
  uses), named groups sorted alphabetically, a "No project" bucket sorted
  last. Composes with every existing date/status/importance/urgency/label/
  search filter and the active `sort`/`dir` — grouping is applied after
  both, so a group's tasks keep the page's sort order; the existing
  completed-stays-visible-but-separated split is preserved, just grouped
  independently on each side. A "Group by" toggle (None/Project) was added
  to `_tasks_toolbar.html`, Table-view only, following the same
  `_filter_dropdown.html` single-select pattern and shared
  `#tasks-filters-form` every other Tasks filter already uses. Grouping
  only adds header `<tr>`s and splits rows across more `<tbody>` elements —
  `_task_row.html` markup and `static/tasks_table.js`'s selectors are
  unchanged. See `features/tasks.md` § Task model, "Table view groupable by
  project", 10 new tests (`test_tasks_grouping.py`), full suite 1017
  passed.
- **Shipped:** `1.5` slice — **deadline-vs-work-allocation distinction**,
  complete (2026-08-13) — the two concepts already existed as separate
  fields/mechanisms (`due_at` vs. `db.task_work_hours`), but the global
  Tasks table and the project detail page's Tasks view (shared
  `_task_row.html` macro) only ever showed "Due" — work-allocation status
  was invisible on the primary task-management surface. Added a
  "Scheduled" column (`{completed}/{scheduled}h`, plain text and a
  distinct label from the editable "Due" date cell) to both. Added
  `db.task_work_hours_bulk(conn, task_uids)` — one batched query per page
  (grouped by `task_uid`) instead of an N+1 of `list_work_allocations_for_
  task` calls, since no existing "aggregate X across many tasks" batch
  precedent existed in `db.py` to reuse; `db.task_work_hours` itself is
  unchanged. Wired into `routers/tasks.py::list_tasks` and
  `routers/projects.py::project_detail`, both attaching `task["work_hours"]`
  before rendering. See `features/tasks.md` § Task model, "Deadline-vs-
  work-allocation distinction," 8 new tests (`test_task_scheduled_
  column.py`), full suite 1025 passed. **1.5 is now fully shipped**
  (`pyproject.toml` bumped to `1.5.0`).
- **Shipped:** `1.6` slice — **Classes as project labels + recurring
  events**, complete (2026-08-14) — `schedule_classes` dropped from
  `SCHEMA_SQL` entirely (`db.py`'s removal note); a class meeting (lecture,
  seminar, ...) is now a real recurring `events` row tagged with the
  per-install Schedule system label plus its course's `is_project=1`
  label, instead of a separate mirrored-from entity. `label_config` gained
  four sparse course-only fields (`course_acronym`/`course_type`/
  `course_credits`/`course_professor_contact_uid` — the facts that
  describe a course, not any one meeting, and have no VEVENT property to
  round-trip through); day/parity are derived from the event's own
  `start_at`/`recurrence` (`schedule.event_day`/`event_parity`), never
  stored. `routers/schedule.py` rewritten to read/write real events
  end-to-end; `schedule_classes.html`/`schedule_class_form.html` needed no
  template changes at all (`_class_row` builds the same enriched shape the
  old schedule_classes row used to be). `scripts/migrate_schedule_
  classes_to_events.py` (idempotent, `--dry-run`) converts any pre-1.6
  database's existing rows. See `features/schedule.md`. Full suite 1042
  passed (new `test_migrate_schedule_classes_to_events.py`, a rewritten
  `test_schedule.py`, and several other test files updated off the
  removed `db.upsert_schedule_class` test-seeding helper).
- **Shipped:** `1.6` slice — **Generalized non-working-day policy + named
  holiday calendars**, complete (2026-08-14) — `schedule_holidays` rows
  belong to a named, reusable `calendar_name` now (default `'Default'` for
  every pre-1.6 holiday, so nothing already-configured changes behavior);
  `db.list_holiday_calendar_names`/`list_holidays_by_calendar` read it back.
  Any recurring `events` row — not just a Schedule class — can set
  `holiday_calendar`/`exclude_saturday`/`exclude_sunday` (three independent
  constraints, per `open-priority.md`'s "a public holiday and a weekend are
  deliberately different kinds of constraints" rule), applied at *read*
  time by `recurrence_expand.expand_events`'s new `holiday_calendars` param
  (every one of its 6 call sites now passes `db.list_holidays_by_calendar
  (conn)`), never materialized into `exdates_json` — a holiday add/remove
  takes effect immediately, no regenerate step. `_event_form_fields.html`
  exposes all three on the ordinary Calendar event form. Schedule's own
  class events switched from per-write EXDATE-stuffing
  (`compute_excluded`/`generate_occurrences`, both deleted) to just
  carrying `schedule_settings.holiday_calendar` (new field, default
  `'Default'`) — `schedule.build_class_event_row` no longer takes a
  `holidays` list at all. See `features/calendar.md`'s Recurrence section
  and `features/schedule.md`. Full suite 1056 passed (new
  `test_holiday_calendars.py`, extended `test_recurrence_expand.py`/
  `test_schedule.py`).
- **Shipped:** `1.6` slice — **Manual recurrence exceptions**, complete
  (2026-08-14) — new `event_occurrence_overrides` table (deterministic
  `master_uid::occurrence_date` key) distinguishes the recurrence rule
  (`events.recurrence`), the generated occurrences (computed, never
  stored), and manual per-occurrence overrides, resolving "the
  recurring-event single-occurrence editing" risk. A cancelled occurrence
  folds into the master's own EXDATE list at expand time; a moved/modified
  one becomes a second real VEVENT sharing the master's UID with a
  RECURRENCE-ID (`ical_rows.py`'s new `recurrence_id` support,
  `recurrence_expand.py`'s `_build_override_component`/`overrides_by_
  master` param) — the standard RFC 5545 override, which
  `recurring_ical_events` (already this app's expansion library) resolves
  for free, confirmed empirically before committing to the design. Every
  expanded occurrence now carries its own original slot as
  `occurrence_date` (the RECURRENCE-ID the library tags every occurrence
  with, not just overridden ones — `ical_to_event_row`), which
  calendar_month/week/fourweek/day.html append to each occurrence's link
  (`?occurrence_date=...`) so `event_detail.html`'s new "This occurrence"
  card (Cancel / Move / Restore — `POST /events/{uid}/occurrences/
  cancel|move|restore`) always targets the right instance. Found and fixed
  a real pre-existing bug in `db.list_events` along the way: a recurring
  row's own literal `start_at`/`end_at` (its first occurrence only) wrongly
  excluded the whole row from a date-range query once the window fell far
  enough past that anchor, regardless of whether the RRULE would still
  generate real occurrences inside it — nothing had ever caught this
  because no prior test queried a week more than ~one occurrence-length
  past a recurring event's own creation date. See `features/calendar.md`'s
  Recurrence section. Full suite 1078 passed (new
  `test_manual_recurrence_exceptions.py`, extended
  `test_recurrence_expand.py`).
- **Shipped:** `1.6` slice — **Configurable terminology**, complete
  (2026-08-14) — Settings > General's "Recurrence terminology" toggle
  (`standard`/`playful`, `deps.py`'s `RECURRENCE_TERMINOLOGY_KEY`,
  app_meta-backed, same memoized-per-request pattern as `week_start`/
  `time_format`; `POST /settings/recurrence-terminology`). Presentation-
  layer only, per spec: the underlying `holiday_calendar`/
  `exclude_saturday`/`exclude_sunday` field names and semantics never
  change, only the on-screen label
  (`_event_form_fields.html`/`schedule_classes.html`, gated by the new
  `recurrence_terminology()` Jinja global) — "Holiday calendar" / "Exclude
  Saturday" / "Exclude Sunday" (standard) vs. "Respects Labor Laws" /
  "Marx Weekend: Saturday" / "Marx Weekend: Sunday" (playful). See
  `features/calendar.md`'s Recurrence section. Full suite 1088 passed (new
  `test_recurrence_terminology.py`). **1.6 is now fully shipped**
  (`pyproject.toml` bumped to `1.6.0`).
- **Shipped:** `1.7` slice 1 — **Today (execution)**, complete
  (2026-08-14) — `GET /today` (`routers/today.py::today_view`), a `/today`
  tabbar entry right after Home (`{{ icon('sun') }}`). An at-a-glance stats
  strip (overdue / due today / events today / scheduled hours today, reusing
  `_widget_at_a_glance.html`'s own CSS classes), a Due & overdue list, a
  Today's schedule list splitting today's ordinary calendar events from
  today's scheduled task work (work-allocation events, via the same
  `db.work_allocation_task_uid` per-event lookup
  `routers/projects.py::project_calendar` already uses), and an Important &
  urgent list (open tasks whose `derived_state.virtual_states` includes
  `important`/`urgent`, excluding anything already shown in Due & overdue —
  no task appears twice). No separate Today data model — everything reads
  straight off `db.list_events`/`list_tasks` plus the shared aggregation
  service (1.1, `src/derived_state.py`) each request, same as the spec's own
  "no separate Today data model" line. New `.today-grid`/`.today-grid-full`
  CSS (mirrors `.habit-task-grid`'s two-column-collapsing-to-one shape). See
  `features/today.md`, 12 new tests (`test_today.py`), full suite 1100
  passed.
- **Shipped:** `1.7` slice 2 — **Week (planning)**, complete (2026-08-14) —
  `GET /week` (`routers/week.py::week_view`), a `/week` tabbar entry after
  Calendar (`{{ icon('clock') }}`). Reuses the same week-grid geometry
  (`grid_layout.layout_day`) `routers/calendar.py::week_view` and
  `routers/projects.py::project_calendar` already render — a third
  *purpose* over that geometry (cross-project planning), not a third
  implementation. Unscheduled work (every open task with no allocation yet,
  across every project or none, sorted by due date, each showing its
  project label via `db.project_label_for`) lists beside the grid and drags
  onto it (`POST /week/allocations`) to create a work allocation; existing
  blocks drag to move/resize (`POST /week/allocations/{event_uid}/move`) or
  delete (`POST /week/allocations/{event_uid}/delete`, block only) — same
  three-endpoint shape as `routers/projects.py`'s own trio, minus the "must
  belong to this project" re-check, and the same `static/
  project_calendar.js` drag/resize script reused verbatim (its own
  `window.PROJECT_CALENDAR` config, just pointed at `/week/allocations`).
  Every work allocation renders prominently regardless of task/project
  (unlike the project-scoped calendar); due-today tasks show as chips per
  day (`day.due_tasks`, open tasks only). New `week_planning.html` reuses
  `project_calendar.html`'s own `.project-calendar-*` CSS classes verbatim
  — no new CSS needed. **Not implemented**: a computed "available time"
  number (open grid space visually communicates it instead, same
  interpretation `project_calendar` already established). See
  `features/week.md`, 16 new tests (`test_week_planning.py`), full suite
  1116 passed.
- **Shipped:** `1.7` slice 3 — **Spaces (context), confirmed complete**,
  closing 1.7, complete (2026-08-14) — checked Spaces against
  `open-priority.md`'s spec ("what belongs to this area of my life,"
  contextual projections generated from labels, extended by specialized
  modules) before writing any code, per this file's own standing
  instruction to verify rather than assume a from-scratch build. Found it
  already fully built (2026-08-08, predating 1.7): `routers/labels.py`'s
  generated label page (`generate_space=1` -> a Space, direct
  `object_labels` membership only) and nav rail list
  (`deps.py::_sidebar_spaces`), the shared widget grid folding in child
  labels' content (`routers/dashboard.py::widget_page_context`), and the
  University module (`_project_university_section.html` — course info incl.
  credits, professor mailto links, next-lecture badges, and a Homework
  table) — the spec's own concrete "courses, schedule, professors, credits,
  assignments" example, already rendering whenever a Space's data exists.
  Dashboard (orientation) was likewise already the existing widget-grid home
  page, no rebuild needed. No code changes; closed out via docs only —
  `plans/open-priority.md` and `plans/roadmap.md`'s 1.7 sections marked
  shipped, `features/labels.md` got a short closing cross-reference. See
  `tests/test_phase2_labels.py` for existing coverage (`generate_space`,
  `is_space` context, University-scoped classes). **1.7 is now fully
  shipped** (`pyproject.toml` bumped to `1.7.0`).
- **Shipped:** side work — **Calendar "Timetable" sub-view**, complete
  (2026-08-14) — `GET /calendar/timetable`
  (`routers/calendar.py::timetable_view`), the Week (planning) surface
  (`/week`, 1.7) folded into the main Calendar page as a "Timetable" entry
  in the Month/4-Week/Week/Day segmented subnav (all four existing calendar
  templates got the new link). It is the `/week` page copied into the
  Calendar page, not a third implementation or a calendar.js merge: same
  grid markup/CSS classes as `week_planning.html` (columns
  `.time-col.project-calendar-col`, work allocations prominent and
  draggable as `.work-allocation`, ordinary calendar events subdued
  context as `.context-event`), `static/project_calendar.js` reused
  verbatim with a `window.PROJECT_CALENDAR` config pointing at this page's
  own `POST /calendar/timetable/allocations[...]` create/move/delete
  endpoints (same shape/validation as `routers/week.py`'s trio, duplicated
  with a cross-reference comment because `routers/week.py` imports this
  router (calendar) and so this router cannot import week back) so
  create/move/delete redirect back here instead of to `/week`.   Drag a
  scheduled block back onto the "Unscheduled work" panel to unschedule it
  (a config-driven addition to `project_calendar.js` interaction 3,
  `deleteUrlBase`/`unscheduleDropSelector`), and a plain click anywhere on
  a scheduled block's body opens that task's edit view (where more work
  sessions can be added) via interaction 4 (`taskEditUrlBase` config, the
  same destination the block's title link carries) — applied consistently
  to the sibling planning grids `/week` and the project Week Calendar too.
  All three override `.time-col`'s `cursor:copy` (the Calendar grid's
  drag-to-create affordance, wrong where empty-space drag isn't a create
  gesture) to plain `default` via `.project-calendar-col`, so the
  misleading "mouse add" cursor is gone from every planning surface. The standalone `/week` page
  and tab are left intact (additive change, no bookmarks/tests broken); a
  later slice could retire them in favor of the sub-view. The timetable
  keeps the calendar page's chrome (subnav, prev/next, label filter, New
  button, next-lecture badges); adding normal calendar events is done there
  as on any calendar view, not on the scheduling grid. See
  `features/calendar.md`. 14 new tests (`test_calendar_timetable.py`), full
  suite 1130 passed.
- **Shipped:** side work — **Holidays moved into Settings**, complete
  (2026-08-14) — a named holiday calendar is a reusable resource any
  recurring event can reference (1.6), not a Schedule-only setting, so it
  moved off `schedule_classes.html`'s compact `<details>` panel into its
  own `GET /settings/holidays` hub category (`routers/settings.py::
  settings_holidays`), the same "Labels get their own page" shape already
  established for Labels. Rendered as a Tasks-table-style grid
  (`settings_holidays.html`, `id="holiday-table"`, columns Title/Calendar/
  Start date/End date) with inline editing — new `POST /settings/holidays/
  {uid}/update-field` (`static/settings_holidays.js`, mirrors `static/
  tasks_table.js`'s pattern) — where the old panel only ever supported add/
  delete. The Calendar column uses `_widget_list_multiselect.html` in
  `single`+`allow_new` mode (pick an existing named calendar or type a new
  one) instead of the old free-text-plus-datalist input, both on the "add
  holiday" row and per-existing-row reassignment; per-row instances are
  named `calendar_name__{uid}` so the holiday's uid travels with the
  change event via the input's own `name` rather than a DOM-position
  lookup, which would break once `app.js` portals an open panel out to
  `#multiselect-portal`. `create_holiday`/`delete_holiday` moved from
  `routers/schedule.py` (`/schedule/holidays...`) to `routers/settings.py`
  (`/settings/holidays...`); new `db.get_holiday` added alongside the
  existing `upsert_holiday`/`delete_holiday`/`list_holidays*` (no separate
  "update" helper needed — a holiday's uid never changes, so upsert-by-uid
  already is the update). Schedule's own `<details>` Settings panel keeps
  its `holiday_calendar` field (which named calendar the semester's
  classes respect) and now links out to `/settings/holidays` to manage the
  calendars' own contents. See `routers/settings.py`'s "2026-08-14
  follow-up" docstring note for the full "why Holidays is the one
  exception to Schedule-settings-stay-contextual" reasoning. 16 new tests
   (`test_settings_holidays.py`), `test_holiday_calendars.py`/
   `test_phase8_settings_hub.py` updated for the moved routes/new hub
   category, full suite 1145 passed.
- **Shipped:** side work — **Work sessions card: add undated sessions**,
  complete (2026-08-14) — the task edit modal's "Work sessions" card (1.4
  slice 1) dropped its start/end datetime inputs for a single "+" button
  (`_task_work_allocations.html`; `POST /tasks/{uid}/work-allocations` now
  treats absent dates as valid). A "+"-added session is an **undated
  session placeholder** — an event with no `start_at`/`end_at`
  (`db.create_work_allocation`'s new both-or-neither signature;
  `events.start_at` is nullable, so no schema change) that keeps the task
  on the planning grids' "Unscheduled work" panel until the session is
  placed. Three consequences, each implemented and tested:
  - The unscheduled-panel rule in `routers/week.py`/`routers/calendar.py`/
    `routers/projects.py` changed from "has any allocation" to "has
    allocations AND every one is dated" — a task whose only session is
    undated (or that has none) still lists on the panel.
  - The three create endpoints (week/calendar/projects `create_allocation`)
    now **place the task's oldest undated session** onto the dropped slot
    (`db.first_undated_work_allocation_for_task` +
    `db.set_work_allocation_times`) instead of creating yet another block —
    so repeated "+" sessions each get placed by one drag. Session numbering
    stays stable ("Session 1/2/3" on the card) because
    `db.list_work_allocations_for_task` now orders by creation, not start
    time.
  - Undated events are private scheduling placeholders, never publishable:
    `routers/export.py`'s `events.ics` and `src/published_lists.py`'s event
    materialization both skip rows without `start_at`, so a placeholder
    can't leak out as a DTSTART-less VEVENT.
  The card renders each session as `Session n` with its date+hour
  (`{date} &ndash; {hh:mm}`) at the row's end (`.session-when`, blank while
  undated) and the same per-row remove form; the "+" button sits at the end
  of the "Work sessions" header (`.work-sessions-head`,
  `.work-session-add`). See `features/tasks.md` § Work allocations. ~15 new
  tests across `test_work_allocations.py`/`test_week_planning.py`/
  `test_calendar_timetable.py`/`test_project_calendar.py`/
  `test_phase10_export.py`/`test_phase6_published_lists.py`, full suite
  1161 passed.
- **Shipped:** side work — **block click opens task view + Relations card
  toggle**, complete (2026-08-14) — two direct-feedback refinements:
  - Clicking a scheduled work block on a planning grid (its body via
    `project_calendar.js` interaction 4, or its title link) now opens the
    block's task **view modal** (`/tasks/{uid}`) instead of the edit form
    (`/tasks/{uid}/edit`) — the config is renamed from `taskEditUrlBase`
    to `taskUrlBase` (it no longer appends `/edit`) across the Timetable
    sub-view, `/week`, and the project Week Calendar, with tests updated
    to assert the `/edit` href is gone.
  - Settings > Appearance gained a "Show the Relations card" toggle
    (`deps.py`'s `show_relations_card()` Jinja global, `SHOW_RELATIONS_
    CARD_KEY` app_meta, default **on** — an install that's never touched
    it stores nothing and shows the card exactly as it always has; `"0"`
    hides it). The card (`_task_relations.html`/`_event_relations.html`)
    is now gated at all four of its homes — task detail, task edit, event
    detail, event edit — via `{% if show_relations_card(request) %}`,
    presentation-layer only (the underlying relations data and all their
    endpoints are untouched; the sibling Work sessions card still renders
    when Relations is hidden). 12 new tests
    (`test_display_prefs_settings.py`'s TestShowRelationsCard/
    TestShowRelationsCardInRenderedPages/TestSettingsAppearanceRelationsCard),
    full suite 1173 passed.
- **Shipped:** side work — **"Unscheduled work" panel: session stepper +
  scheduled/total hours + collapse-on-unschedule + pointer-based drag**,
  complete (2026-08-14) — the planning grids' (Timetable, `/week`, project
  Week Calendar) unscheduled-work panel reworked:
  - Each panel item is now a shared partial
    (`_unscheduled_task_item.html`, imported `with context` by all three
    templates — replacing the triplicated old markup) showing the task
    title with a **scheduled/total hours x/y readout** next to it
    (`db.work_allocation_panel_info`: `scheduled_hours` = sum of dated
    session durations, `total_hours` = that plus one default hour per
    undated session, so an unplaced placeholder reads "hours on the
    calendar out of hours planned"), plus a **−/count/+ session stepper**:
    "+" adds an undated session placeholder (`POST
    /tasks/{uid}/work-allocations`), "−" removes the most recently added
    one (`POST /tasks/{uid}/work-allocations/remove-latest`,
    `db.remove_latest_work_allocation`) and is **hidden at count 1** (the
    panel never removes the last session — reaching zero is the task modal's
    Work sessions card; "a task can have no timeblock" stays the plain
    unscheduled state). Both forms post a same-origin `next` path (validated
    by `tasks.py`'s `_safe_next`, open-redirect-safe) so the reload returns
    to the grid they were used from.
  - **Unschedule now collapses**: the three delete endpoints
    (`week.py::delete_allocation`, `calendar.py::delete_timetable_
    allocation`, `projects.py::delete_allocation`) no longer delete just the
    one block — they delete **all** of the task's work sessions and leave
    exactly **one undated session** behind
    (`db.collapse_task_work_allocations`), so the task returns to the panel
    at a count of one ("when unscheduling a task it is deleted and only one
    work session remains"); the block's ✕ tooltip says so.
  - **Pointer-based drag** (static/project_calendar.js interaction 1): the
    old native HTML5 drag-and-drop is replaced by the same
    pointerdown/pointermove/pointerup model the block move/resize already
    used — a fixed ghost clone follows the cursor (`drag-ghost`), the hovered
    column lights up, and the grid **auto-scrolls near its top/bottom edge**
    so any time is reachable; block move/resize got pointercancel handling
    (revert-and-submit-nothing), scroll-aware positioning
    (`origTop + dy + scrollDelta` keeps a moved block glued to the pointer
    through an auto-scroll), and the resize-handle click now correctly skips
    the task-view modal (a latent `mode`-already-nulled bug fixed). Panel
    items carry no native `draggable` attribute anymore. New `icon-minus`
    sprite symbol and `.unscheduled-*`/`.drag-ghost` CSS. See
    `features/tasks.md` § Work allocations. ~24 new tests
    (`test_work_allocations.py`'s TestPanelInfoAndSessionStepper, and
    stepper/collapse classes in `test_week_planning.py`/
    `test_calendar_timetable.py`/`test_project_calendar.py`), full suite
    1197 passed.
- **Shipped:** side work — **"Unscheduled work" panel: one-line card +
  project icons**, complete (2026-08-14) — direct follow-up feedback on the
  panel item above: collapse it to strictly one line — a project pill
  (icon + name) and the task title on the left, the session-count stepper
  on the right — and drop the scheduled/total hours readout and due date
  entirely (`_unscheduled_task_item.html` trimmed; the `item.sessions`
  dict built by `week.py`/`projects.py`/`calendar.py::timetable_view` still
  carries `scheduled_hours`/`total_hours` from `db.work_allocation_
  panel_info`, just unused by the template now — left in rather than
  stripped from the return shape, since nothing else about that summary
  changed). "Add icons to projects" was backend-only, as asked: `label_
  config.icon` already existed (the general per-label icon field behind
  Settings > Appearance's "Show icons next to labels", 2026-08-09) — new
  `db.project_label_config_for(conn, object_type, object_id)` wraps
  `project_label_for` + `effective_label_config` so the panel gets the
  project's full config (name + icon, defaults filled in) in one call
  instead of just a name string; no icon-picker or other client work was
  needed since labels already have one. New `.unscheduled-project-pill`
  CSS (rounded pill, icon + name, ellipsis-truncated). Caught and fixed a
  real bug while integrating this: an editor merge had silently dropped
  the `@router.post("/settings/label-icons")` decorator during the
  Relations-card-toggle slice above, off the tail end of `set_relations_
  card` — the route was gone from the app (`set_label_icons` was still a
  plain function, never registered) even though every existing test still
  passed, since this app's settings tests call router functions directly
  rather than through the ASGI app; confirmed the fix by listing `router.
  routes` directly, not just re-running pytest. See `features/tasks.md` §
  Work allocations and `features/week.md`. Tests trimmed to assert the
  hours readout and due date are gone (`"unscheduled-hours" not in body`)
  and to cover the project-icon pill (`test_project_calendar.py`/
  `test_week_planning.py`/`test_calendar_timetable.py`), full suite 1199
  passed.
- **Fixed:** side work — **unscheduling a block no longer changes a task's
  session count at all**, complete (2026-08-14), reported directly against
  the Timetable ("deleting/drag-drop doesn't work at all... doesn't hold the
  number of work sessions to be a guide"). Reproduced live (headless
  Chromium against a real seeded app instance, not just reading code) before
  changing anything, and again after each fix attempt -- went through three
  designs the same day:
  1. Original ("Unschedule now collapses" side work, earlier the same day):
     any single block delete/unschedule collapsed ALL of the task's
     sessions to exactly one undated placeholder (`db.
     collapse_task_work_allocations`, called unconditionally by all three
     planning grids' delete endpoints). A task with 3 sessions (1 scheduled
     + 2 still-undated) lost the other 2 the moment just one was
     unscheduled -- confirmed live, and confirmed with the user this was
     the actual bug before reversing a very recent explicit decision.
  2. First fix: swapped in `db.delete_work_allocation` (a real, permanent
     delete of just the one session) -- fixed the "wipes other sessions"
     part, but now a single-session task's count visibly dropped to 0 the
     instant its only block was unscheduled, since "unschedule" isn't "I
     don't need this session anymore." User caught this immediately
     ("why when i drag a work time block onto unschedule, i says 0
     sessions").
  3. Final fix: new `db.unschedule_work_allocation` clears the one
     session's start/end back to undated (mirrors the already-existing
     `set_work_allocation_times`) instead of deleting anything -- the
     task's session count never changes just from scheduling/unscheduling a
     block; only the panel's own −/+ stepper (or the task's Work sessions
     card) adds/removes sessions. `db.collapse_task_work_allocations`
     deleted outright (dead code, and leaving it around risked a future
     "fix" reintroducing #1). Since unscheduling is no longer destructive,
     the block's delete-button form got `data-confirmed="1"` so it skips
     `app.js`'s generic delete-confirmation popover and submits instantly,
     matching the drag-onto-panel gesture's already-immediate behavior.
  Updated the three delete-button tooltips (`week_planning.html`/
  `calendar_timetable.html`/`project_calendar.html`),
  `project_calendar.js`'s header comment, and `features/tasks.md`'s two
  references, off the stale wording each round. Tests in
  `test_week_planning.py`/`test_calendar_timetable.py`/
  `test_project_calendar.py`'s `TestDeleteAllocation` now assert the
  unscheduled session survives (undated) and the other sessions are
  untouched; 2 now-pointless `db.collapse_task_work_allocations` unit tests
  removed from `test_work_allocations.py`. Full suite 1198 passed.
- **Fixed:** side work — **the "Unscheduled work" panel's number now counts
  down as sessions get placed**, complete (2026-08-14), immediate follow-up
  feedback on the fix directly above ("i have two work sessions. why after
  droping one, the counter... doesn't update from 2 to 1"). Root cause: the
  panel displayed `item.sessions.count` — the task's TOTAL session count —
  which by design (confirmed with the user earlier the same day, "the count
  ... keeps acting as an accurate running total of planned sessions") never
  changes just from scheduling one of them. That's correct for "how much
  work did I plan," but the user's actual mental model for this specific
  number was "how many sessions still need placing" — asked directly via
  AskUserQuestion given two prior same-day pivots already, confirmed:
  "sessions still needing placement." `_unscheduled_task_item.html` now
  shows `item.sessions.undated_count` instead (the field already existed on
  `db.work_allocation_panel_info`, just wasn't the one rendered) — this
  automatically counts down as sessions are placed and back up when
  unscheduled, no router changes needed for the display itself. The "−"
  stepper button visibility changed from `count > 1` to `undated_count > 0`
  (available whenever there's an unplaced session to remove, including down
  to exactly one — reaching 0 remaining is now a normal state, not a floor
  the panel avoids). `db.remove_latest_work_allocation` (the "−" button's
  handler) changed to only ever consider undated sessions when picking
  "most recently added" — it used to pick the literal last-created session
  regardless of scheduled state, which could have silently deleted an
  already-scheduled block if that happened to be more recent than any
  undated one; now it's guaranteed to only ever touch the same pool the
  displayed number represents. Verified live again (headless Chromium,
  a task with 2 undated sessions): counter read 2, dropped one onto the
  grid, counter read 1. Updated `_unscheduled_task_item.html`'s and
  `features/tasks.md`'s stepper documentation off the old "total count"
  wording. `TestUnscheduledPanelStepper` rewritten across `test_week_
  planning.py`/`test_calendar_timetable.py`/`test_project_calendar.py` (−
  now shown at exactly 1 undated session, hidden only at 0 even if the task
  has dated sessions; new count-decrements-on-placement assertions); one new
  `test_work_allocations.py` test (`test_remove_latest_never_touches_a_
  dated_session`). Full suite 1205 passed.
- **Shipped:** side work — **Data health & maintenance**, complete
  (2026-08-14) — 1.8's precondition ("trusted only once verified backups
  exist"). New Settings > Data health hub category (`/settings/data-health`,
  `routers/settings.py`): database integrity (`PRAGMA integrity_check`),
  last successful backup, last backup verification, a fixed "sync not
  configured — ships in 1.8" placeholder, storage usage, entity stats, and a
  Backups table (per-row Verify/Restore). Every operation lives as a plain
  function in new `src/data_health.py` (`create_backup`/`list_backups`/
  `verify_backup`/`restore_backup`/`check_integrity`/`compact_and_reindex`/
  `storage_stats`/`entity_stats`/`health_summary`) — both the Settings routes
  and new `scripts/data_health.py` (CLI: `status`/`backup`/`list`/`verify`/
  `restore`/`integrity-check`/`repair`) call the same functions, satisfying
  open.md's "GUI and CLI use the same underlying maintenance services"
  requirement directly, not by convention. A backup is the identical payload
  `routers/export.py`'s `build_backup_payload` produces (factored out of
  `export_data_json` so the on-demand data.json download and these
  server-side backups share one definition); verification (JSON structure,
  required top-level keys, list-shaped collections, every task/event/contact
  row has a `uid`) caches its result as a `<file>.verify.json` filesystem
  sidecar next to the backup, not in the app database — no schema change,
  and a backup + its sidecar travel together. Restore always takes a fresh
  safety-snapshot backup of the current state first and aborts untouched if
  the target fails verification — "preserve a recoverable backup of the
  current state where practical" (open.md). Backup filenames carry
  microsecond precision plus a collision-retry loop, found necessary when a
  restore's own safety-snapshot landed in the same wall-clock second as the
  backup being restored from and silently overwrote it before it could be
  read — caught by a same-session test, not in the wild. `config.py` gained
  `backup_dir` (env `CC_BACKUP_DIR`, default `db_path.parent / "backups"`) on
  the `Settings` dataclass — the one call site outside `load_settings()` that
  constructs `Settings` directly (`test_caldav_bridge_live.py`, a live-server
  fixture) needed updating for the new required field. See
  `features/settings.md`, `plans/open.md`/`plans/roadmap.md`'s 1.1 side-work
  rows marked shipped. 26 new tests (`test_data_health.py`), full suite 1231
  passed.
- **Shipped:** side work — **1.8's sync model, designed** (docs only, no
  code), complete (2026-08-14) — `open-priority.md` § Offline-first editing
  & synchronization expanded from a one-paragraph decision record into a
  full model, per this file's own standing instruction to write the sync
  model as its own slice before any implementation code. Covers: entity
  identifiers (existing `uid`s, client-generated on offline create, no
  central allocation needed — single-user app); an append-only local
  operation log (field-level, not whole-row, so conflict resolution can be
  per field); a Hybrid Logical Clock, `(physical_time_ms, logical_counter,
  device_id)`, for a total order across devices that survives clock skew
  (prior art: the ported-forward HLC per-field merge decision in
  `abandoned.md`); soft-delete tombstones with a configurable GC retention
  horizon (a device reconnecting past it forces a full resync rather than
  risking resurrecting an already-deleted row); an `op_id` idempotency
  ledger for safe retries; per-field newer-wins conflict detection as the
  default, with two deliberate, explicitly-named exceptions where a plain
  per-field LWW would violate "must never result in silent data loss":
  concurrent edits to the *same* work-allocation/event's `start_at`/
  `end_at` (two real scheduling decisions, not the same fact measured
  twice) and two devices attaching *different* project labels to the same
  task while offline (violates 1.5's existing single-project-per-task
  invariant only as a *combination*, even though each individual label-add
  op is independently valid) — both surfaced to a new Sync conflicts list
  instead of auto-resolved or silently dropped. A push-then-pull protocol
  shape (§8) and the three new sync-infrastructure tables it needs
  (`field_versions`, `sync_devices`, `sync_conflicts` — metadata, not a new
  domain object type, per `features/architecture.md` §1.4). Closes with an
  acceptance line and a 7-slice implementation breakdown (§11) so
  implementation sessions can each ship one slice standalone, starting with
  a server-only, browser-independent field-HLC shadow store + sync API
  skeleton (slice 1) before any PWA/client work (slices 3+). See
  `open-priority.md`'s own section for the full text;
  `plans/roadmap.md`'s 1.8 subsection updated to match.
- **Shipped:** `1.8` slice 1 — **field-HLC shadow store + sync API
  skeleton**, complete (2026-08-14) — `open-priority.md` § Offline-first
  editing & synchronization §11, slice 1. New `field_versions` (per-field
  HLC only, no value — the value stays solely on `tasks`/`events`/
  `contacts`), `sync_devices` (per-device push/pull cursor bookkeeping),
  and `sync_applied_ops` (§5's idempotency ledger) tables. New
  `src/offline_sync.py`: pure §6 per-field last-write-wins apply logic
  (`apply_op`/`apply_batch`) and §8's `pull` (incremental delta since a
  cursor, or a `full_resync` signal once a non-`None` cursor is older than
  the 90-day retention horizon — a `None` cursor, a brand-new device's
  first-ever pull, is just a plain "everything" delta, not a staleness
  case). New `routers/sync_api.py`: `POST /api/sync/push`/`/api/sync/pull`,
  the thin HTTP wrapper (request parsing + `sync_devices` cursor writes
  only), wired into `main.py` (named `sync_api` specifically to not shadow
  the already-imported, unrelated `src/sync.py` Radicale/Published-Lists
  background sync). `tasks`/`events`/`contacts` each gained a `deleted_at`
  column (§4's tombstone model: delete is a field write, not a row
  removal) — a delete op sets it via the same per-field HLC path as any
  other field, which is also what makes "an edit newer than the tombstone
  un-deletes the row" fall out for free, no special-case code. Label
  add/remove (`entity_type: "object_label"`) needs no HLC arbitration at
  all (§7a, commutative by construction) — applying twice converges
  either way. Deliberately out of scope, per the slice's own boundary: the
  `sync_conflicts` table and §7b/c's two conflict-*surfacing* exceptions
  (event `start_at`/`end_at` concurrent-edit detection,
  single-project-per-task re-validation after a batch) — every field,
  including those two, gets plain §6 LWW for now; slice 2 wires the
  exceptions into this slice's own `apply_op` path. No PWA/browser client
  exists yet — tested entirely server-side (`test_offline_sync.py`,
  router-function-call convention, `asyncio.run` + a synthetic JSON
  `Request` for the two async endpoints), same as every other slice in
  this app. 19 new tests, full suite 1250 passed.
- **Shipped:** `1.8` slice 2 — **Sync conflicts surface**, complete
  (2026-08-14) — `open-priority.md` § Offline-first editing &
  synchronization §11, slice 2. New `sync_conflicts` table (§9: `id`,
  `entity_type`, `entity_uid`, `field_name`, `losing_value`, `losing_hlc`,
  `winning_hlc`, `created_at`, `resolved_at`; HLCs stored as display-only
  `"physical:logical:device_id"` text, never compared/sorted) + a new
  `/settings/sync-conflicts` hub category (`routers/settings.py`,
  `settings_sync_conflicts.html`) listing every unresolved conflict with
  Restore (re-applies the losing value as a fresh op through the normal
  `offline_sync.apply_op` path, a synthetic `"settings-restore"` device id
  + a `now` HLC so it always outranks every real prior write, then marks
  the conflict resolved) and Dismiss (`resolved_at` set, value discarded)
  actions. Wired both of §7's deliberate LWW exceptions into slice 1's
  `src/offline_sync.py` apply path:
  - **§7b** (event `start_at`/`end_at`) — `_apply_field_write` now
    surfaces a conflict instead of a plain silent stale no-op whenever the
    losing write's `device_id` differs from the winner's. The concurrency
    test is a deliberate simplification, not full causal/version-vector
    tracking (§10 explicitly rules CRDTs out): per §3's HLC merge rule, a
    device that had already observed another device's write would have
    merged its own clock past it and could never subsequently lose to
    that same write — so "different device_id on both sides of a losing
    write" is concurrency's own observable signature, with no extra state
    needed. A losing write from the *same* device as the winner (a
    reordered/replayed op from that device's own causal history) is left
    as an ordinary §6 stale no-op, not surfaced.
  - **§7c** (single-project-per-task) — `apply_batch` re-validates after
    every op in the batch has applied, not per-op (each individual
    `label_add` is independently valid per §7a; only the *combination*
    can violate the invariant). Highest-HLC `label_add` for a task wins;
    a project label the task already carried *before* this batch always
    outranks anything newly added within it (no in-batch HLC to lose
    against). Every losing add is reverted from `object_labels`, recorded
    as a conflict, and that op's own result status is patched to
    `"rejected_invariant"` in the batch's returned results.
  Still no PWA/browser client anywhere — everything above is exercised
  server-side, same router-function-call convention as slice 1. 11 new
  tests extending `test_offline_sync.py` (30 total in that file), plus a
  hub-categories fixture update in `test_phase8_settings_hub.py`, full
  suite 1261 passed.
- **Shipped:** `1.8` slice 3 — **PWA shell**, complete (2026-08-14) —
  `open-priority.md` § Offline-first editing & synchronization §11, slice
  3. New `static/manifest.webmanifest` (name/icons/`display:
  "standalone"`/`start_url: "/"`, linked from `base.html` plus a
  `theme-color` meta tag) and `static/sw.js`, the app-shell service
  worker. `sw.js` is served at the root path by new `routers/pwa.py`'s
  `GET /sw.js` (not `/static/sw.js` — a service worker's default scope is
  the directory of the URL it's fetched from, so serving it under
  `/static/` would cap its scope at `/static/*` instead of the whole
  app), registered by new `static/pwa.js` (loaded globally in
  `base.html`, last, as a progressive enhancement guarded by a feature
  check). It precaches every static asset `base.html` loads on every page
  plus a new `GET /offline` fallback page (`templates/offline.html`,
  extends `base.html` so the tabbar/nav renders identically offline — a
  plain "you're offline" message where content would go, since there's no
  local data layer yet) and serves that fallback for any navigation
  request that fails with the network down — `ofline-first-pwa.md`'s
  "opening the application offline should lead directly to the normal
  interface rather than an error page" line, for the app-shell-only scope
  this slice covers. Static assets use a cache-first strategy (safe
  because every asset URL is already cache-busted by `deps.py`'s
  `static_url()`); real page navigations stay network-first, since this
  app's pages are server-rendered from live SQLite state and must never
  serve a stale copy when the network is actually reachable. Deliberately
  out of scope, per the slice's own boundary: sync, IndexedDB, and any
  local read/write path (slices 4-5) — this slice is purely "can the app
  open at all with no network." The first genuinely browser-dependent
  piece of 1.8: a real service worker install/fetch cycle can't be
  exercised by this app's router-function-call pytest convention, so
  `test_pwa_shell.py`'s 10 tests cover what *is* server-verifiable
  (manifest validity, every icon it references existing on disk,
  `/sw.js`'s content-type/no-store header, the precache list only naming
  assets that exist on disk, `/offline` rendering full chrome, and
  `routers/pwa.py` actually being wired into `main.py` — confirmed via
  `app.routes` directly, the same style of check that caught the
  `settings.py` route-registration bug the same day slice 2 shipped, not
  just by calling the router function). Actual install/offline-navigation
  behavior needs manual browser verification, not performed as part of
  this slice (this sandbox has no browser and no reachable Radicale
  server to boot the full app against). Full suite 1271 passed.
- **Shipped:** `1.8` slice 4 — **Local IndexedDB store + read path**,
  complete (2026-08-14) — `open-priority.md` § Offline-first editing &
  synchronization §11, slice 4. New `static/offline_db.js`: an IndexedDB
  database (`cc-offline`) mirroring `tasks`/`events`/`contacts` (written
  incrementally, field by field, never a whole-row replace) plus a
  `field_hlc` store replaying the same §6 per-field-HLC-wins rule the
  server's `field_versions` table applies — a pull can never regress a
  field even out of order — and a `meta` store for `device_id`
  (`crypto.randomUUID()`, generated once and persisted) and the pull
  cursor. New `static/offline_sync_client.js` is §8's pull half,
  client-side: `POST /api/sync/pull` with the stored cursor on the page's
  `load` and the browser's `online` event, applies the returned changes
  into the mirror, advances the cursor. Deliberately push-free (nothing
  local to push yet) and retry-free (§5 backoff is slice 6) — one
  best-effort attempt per trigger, silent no-op on failure. A
  `full_resync` response just clears the cursor and re-pulls once, which
  is exactly correct today since nothing has ever been physically purged
  (§4's GC is slice 7). Both scripts load globally in `base.html` (not
  just `/offline`) so the mirror is warm from ordinary online browsing
  before the network ever drops. `templates/offline.html` gained
  `#offline-local-data`, rendered by new `static/offline_shell.js`
  straight from the mirror (`getAllTasks`/`getAllEvents`, soft-deleted
  rows filtered) with no network call of its own — open tasks by due
  date and upcoming events by start time, reusing `search.html`'s own
  `.checklist`/`.checklist-row` styling. Deliberately partial: labels/
  tags aren't mirrored (`object_label` ops are commutative, §7a, never
  flow through the field-HLC pull this mirrors) — title/due/time only,
  no project pill. `sw.js`'s precache list bumped to `cc-shell-v2` to
  cover the three new scripts. Still read-only — no local writes
  anywhere yet (slice 5). Verified two ways: `test_pwa_shell.py`'s 6 new
  structural checks (same "read the JS source, assert the shape" level
  as slice 3's own sw.js tests, full suite 1277 passed), plus a one-off
  Node + `fake-indexeddb` smoke run (not added to the pytest suite, no
  new runtime dependency introduced there) that exercised the real merge
  logic end to end: newer-HLC writes apply, older-HLC writes are
  rejected, a `deleted_at` write removes the row from `getAllTasks`, and
  `device_id`/cursor round-trip correctly through IndexedDB.
- **Shipped:** `1.8` slice 5 — **Local write path + outbox**, complete
  (2026-08-14) — `open-priority.md` § Offline-first editing &
  synchronization §11, slice 5. New `static/offline_write.js`: offline
  create/complete/delete on a task queues a real §2 op into a new
  IndexedDB `outbox` store (`offline_db.js`'s `enqueueOp`/`getOutboxOps`/
  `getOutboxCount`) and applies it immediately to the local mirror through
  the same per-field-HLC-wins path a pull already uses (`applyChanges`) —
  a same-device optimistic write can never lose to itself. `offline_db.js`
  gained this device's own §3 HLC clock (`nextHlc`/`mergeHlc` — nothing
  through slice 4 ever minted its own HLC, only applied server-supplied
  ones); `offline_sync_client.js` now merges the clock forward after every
  pull. `create` stamps every field with one shared HLC per §2; a
  `field_set` shares its HLC with the `updated_at` write riding along with
  it. Deliberately scoped to tasks only (create/complete/delete) — events/
  contacts get no offline write UI yet. `/offline`'s task list
  (`offline_shell.js`) gained an inline "add a task" form and per-row
  complete/delete buttons (reusing `.checklist-check`/`.checklist-delete`)
  plus an outbox-count-driven "N local changes saved, waiting for sync
  support" note — no claim that anything syncs yet (slice 6). A device
  that's never completed a pull can now create its very first task offline
  (slice 4's render-nothing-until-`lastSynced` gate removed for the task
  section only). Found and fixed a real bug via a one-off Node +
  fake-indexeddb smoke script (slice 4's pattern, not added to pytest):
  `getOutboxOps()`'s plain `getAll()` returned ops in IndexedDB's default
  key-order (a random `op_id` UUID keyPath), not queued order — fixed by
  sorting on each op's own top-level `hlc` (now stamped onto
  `create`/`field_set` too, not just `delete`). `sw.js` precache bumped to
  `cc-shell-v3`. 8 new tests extending `test_pwa_shell.py`, full suite 1285
  passed.
- **Shipped:** `1.8` slice 6 — **Sync engine**, complete (2026-08-14) —
  `open-priority.md` § Offline-first editing & synchronization §11, slice
  6. `static/offline_sync_client.js` grew a push half alongside its
  existing pull half: `pushOnce()` sends every outbox op (already HLC-
  ordered by `offline_db.js`'s `getOutboxOps`) to `POST /api/sync/push`,
  then acknowledges via a new `offline_db.js::removeOutboxOps` — an
  acknowledged op is dropped immediately rather than kept in a separate
  "acknowledged but retained" state, one of §2's two explicitly-allowed
  options. `syncNow()` wraps both halves in §8's own push-then-pull order.
  §5's retry policy: exponential backoff with jitter capped at 30s, reset
  on the browser's `online` event or any successful round; a local write
  (`offline_write.js`'s `submitOp`) now calls new `requestSync()`
  immediately after queuing rather than waiting for the next periodic
  retry. Status is computed live, never stored — new `getStatus()` derives
  `offline`/`synchronizing`/`pending`/`synced` fresh from `{navigator.
  onLine, in-flight, outbox size}` every time, dispatching
  `cc-offline-status-change` whenever it might have changed, so it can
  never drift from what's actually true. New `static/offline_status.js` is
  the small indicator itself (`ofline-first-pwa.md`'s own line) — a pure
  renderer, no IndexedDB/network calls of its own — hidden entirely in the
  `synced` state ("successful background sync stays unobtrusive, while
  errors are visible") and a small top-right pill otherwise.
  `data_health.py`'s Data health "sync" field, a fixed
  `{"configured": false}` placeholder since slice 1, now reflects real
  `sync_devices` rows via new `db.list_sync_devices` — flips to
  "Configured" once any device has actually synced. `sw.js` precache
  bumped to `cc-shell-v4`. Verified two ways: `test_pwa_shell.py`'s
  structural checks (8 new tests) plus a one-off Node + fake-indexeddb
  smoke script (not added to pytest) with a faked `fetch` exercising push-
  drains-outbox / failed-push-keeps-the-op / recovery-drains-it-again /
  offline-skips-the-network end to end — caught and fixed a real Node-
  specific gotcha along the way (Node 21+'s built-in read-only `navigator`
  global silently no-ops a plain reassignment; needed `Object.
  defineProperty` instead). Full suite 1293 passed. This wires slices 1-5
  together end to end — an offline write now actually leaves the device
  once one comes back online.
- **Shipped:** `1.8` slice 7 — **Tombstone GC**, complete (2026-08-14) —
  `open-priority.md` § Offline-first editing & synchronization §11, slice
  7. New `offline_sync.purge_expired(conn, retention_days, now_ms)`: any
  entity whose tombstone (`deleted_at`'s own stored HLC in
  `field_versions`, not a string-timestamp comparison) is older than the
  horizon is physically removed via the *existing* `db.delete_task`/
  `delete_event`/`delete_contact` (so related-row cleanup —
  `object_labels`, `event_task_relations`, ... — matches every other hard
  delete in this app) plus its now-orphaned `field_versions` rows; an
  edit newer than the tombstone (an un-delete, §4) naturally falls outside
  the query with no special-casing, since that edit already advanced
  `field_versions`' own `deleted_at` HLC past the old one. A second half
  purges `sync_applied_ops` rows past the same horizon. New
  `data_health.py` wrappers (`sync_gc_retention_days`/
  `set_sync_gc_retention_days`/`run_sync_gc`/`sync_gc_last_run`) give this
  the same "GUI and CLI share one implementation, no cron — check lazily
  on a natural request path" treatment as every other Data health action:
  `routers/sync_api.py`'s `pull` handler now calls `run_sync_gc` before
  computing its own response (a pull is the sync engine's own heartbeat);
  Settings > Data health gained a retention preset field (0/14/30/90/180
  days, same fixed-choices convention as the existing auto-archive field)
  and a "Run cleanup now" button; `scripts/data_health.py` gained a
  `sync-gc` subcommand.
  Closed a real correctness gap the slice's own acceptance line demanded:
  once the server can physically purge an old tombstone, a plain
  "re-pull and applyChanges" on a `full_resync` response could never tell
  a badly-stale device that an already-purged entity is gone (nothing
  left server-side to say so) — new `offline_db.js::clearMirror` wipes the
  local `tasks`/`events`/`contacts`/`field_hlc` stores (outbox and device
  identity untouched) before a full resync re-pulls, so "start over"
  means an actual rebuild, not a merge into a mirror that might still
  hold something the server has since forgotten.
  Found and fixed a second real bug via a one-off Node + fake-indexeddb
  smoke script purpose-built to exercise a genuine full-resync round trip
  (every earlier smoke script's fake pull response had used a `null`
  cursor, which never touched this code path): `offline_db.js::mergeHlc`
  had been destructuring its argument as a `[physical, logical,
  device_id]` array since slice 5, but every real caller passes the
  `{physical, logical, device_id}` dict payload shape the wire protocol
  actually uses — it silently threw against any real pull response
  carrying a non-null cursor.
  This closes 1.8's 7-slice breakdown. `pyproject.toml` bumped to
  `1.8.0` — also caught and fixed a stale-versioning gap while doing so:
  it had stayed at `1.3.0` since 1.4 despite this file's own session logs
  claiming a bump at the end of each of 1.4/1.5/1.6/1.7; those bumps were
  never actually committed. Not investigated further or backfilled — this
  slice's bump just catches the number up to the app's real feature set.
  `open-priority.md`'s own section heading struck through and marked
  shipped (kept as the reference spec, per this repo's "How open work
  gets tracked" convention); new `features/offline-sync.md` is the
  outcome doc. 16 new tests (12 extending `test_offline_sync.py`/
  `test_data_health.py`, 4 extending `test_pwa_shell.py`), full suite
  1309 passed. **1.8 is now fully shipped.**
- **Shipped:** side work — **recurrence end condition (Never/On date/After N
  occurrences)**, complete (2026-08-14) — direct feedback ("recurrence should
  also have the ability to set an end date, until X, or for the event to
  repeat a set number of times"). `recurrence_picker.js`'s FREQ presets
  (Daily/Weekly/Monthly/Yearly) gained an "Ends" sub-panel nested in the same
  dropdown panel: Never (no suffix), "On date" (`UNTIL=YYYY-MM-DD`, the app's
  existing dashed-date convention), or "After N occurrences" (`COUNT=N`) —
  entirely client-side, same "zero server-side recurrence parsing" contract
  `routers/calendar.py`'s create/update handlers already had. New
  `parseValue()` strips any `UNTIL=`/`COUNT=` token from the stored string
  before matching a FREQ preset on reload, so an existing end condition
  round-trips into the Ends radios instead of falling through to Custom; the
  Ends group only shows once a real preset (not "Does not repeat", not
  Custom) is selected. No expansion-side change needed — `COUNT=` already
  worked end-to-end via `recurring_ical_events`, confirmed and locked in by
  two new tests (`test_recurrence_expand.py`'s `test_count_recurrence_*`).
  New `.recurrence-ends-*` CSS reusing `.multiselect-option`/
  `.multiselect-new-input` conventions. See `features/calendar.md`'s
  Recurrence section. 3 new tests (2 in `test_recurrence_expand.py`, 1
  structural check in `test_modal_footer_and_inputs.py`), full suite 1312
  passed.
- **Removed:** side work — **Custom RRULE option removed from the recurrence
  picker**, complete (2026-08-14) — direct follow-up ("remove the custom
  option for recurring"). `recurrence_picker.js`'s free-text "Custom RRULE"
  row is gone; the five fixed presets (Does not repeat/Daily/Weekly/Monthly/
  Yearly) plus the "Ends" sub-choice from the slice above are now the only
  thing the picker can produce. An existing value that doesn't match one of
  the five presets is left with no preset radio checked and shown read-only
  as the trigger summary — `sync()` never overwrites the hidden input until
  a preset is actually picked, so this can't silently clobber a rule the
  picker doesn't model just by opening/closing the form. See
  `features/calendar.md`'s Recurrence section. Full suite 1312 passed (no
  new tests — pure removal, existing structural/server-pass-through tests
  already cover the remaining shape).
- **Shipped:** side work — **"Ends" split into its own dropdown**, complete
  (2026-08-14) — direct follow-up ("could we make ends another drop down
  menu?"). The Ends choice (Never/On date/After N occurrences) moved out of
  a sub-panel nested inside the FREQ preset dropdown into a second, separate
  `.multiselect` dropdown (`recurrence-ends-select`), a sibling of the FREQ
  dropdown reusing the same trigger/panel markup contract so `app.js`'s
  generic multiselect click/portal/position handling picks it up with no JS
  changes there. Still hidden entirely until a real preset (not "Does not
  repeat") is selected — same rule, just driven off `endsWrap.hidden`
  instead of a nested group. See `features/calendar.md`'s Recurrence
  section. 1 new structural test
  (`test_recurrence_picker_js_ends_is_a_separate_dropdown`), full suite 1313
  passed.
- **Shipped:** side work — **event holiday fields: recurring-only + real
  dropdown**, complete (2026-08-14) — two direct follow-ups on
  `_event_form_fields.html`'s Holiday calendar / Exclude Saturday / Exclude
  Sunday fields ("make the holiday selector for events to appear only if
  the event is recurring" + "make the menu a drop down where the use does
  not need to type, but only select the calendar"):
  - Each field now carries a shared `holiday-field` class and starts
    `hidden` unless the event already has a `recurrence` value (server-
    rendered, so a recurring event's fields are visible on first paint with
    no JS-dependent flash); `static/recurrence_picker.js`'s existing
    `sync()` (already the single place that knows whether the current
    preset is "Does not repeat" or a real recurring one) now also toggles
    `hidden` on every `.holiday-field` sibling it finds inside the same
    `.field-grid` on every preset change. Kept as three separate grid items
    rather than one wrapping container, so `.field-grid`'s two-column
    layout is unaffected. `task_form.html`/`habit_task_form.html` share the
    same picker but have no `.holiday-field` siblings, so this is a no-op
    there.
  - `holiday_calendar` changed from a free-text input + `<datalist>`
    (type-to-filter, but still typeable) to a plain `<select>` populated
    from `db.list_holiday_calendar_names` (already passed into every
    caller of this partial) — the event form now only ever offers a
    calendar that actually exists; creating a new named calendar stays a
    Settings > Holidays action. Server-side handling (`routers/
    calendar.py`/`dashboard.py`'s create/update) needed no change — an
    empty `<select>` value round-trips as `""`/`None` exactly like the old
    empty text input did.
  No new tests (pure presentation change to an already-covered code path —
  `test_holiday_calendars.py`/`test_recurrence_terminology.py`/
  `test_modal_footer_and_inputs.py` still assert `name="holiday_calendar"`
  and the create/update round-trip, which the `<select>` still satisfies).
  Full suite 1313 passed.
- **Fixed:** side work — **holiday fields' `hidden` attribute was silently
  a no-op**, complete (2026-08-14), immediate follow-up on the slice above
  ("Holiday calendar still appears when Recurrence is on Do not repeat").
  Root cause: `style.css`'s `.field{display:flex; ...}` (author CSS) is the
  same specificity as the browser's own `[hidden]{display:none}` UA rule,
  and author styles always win that fight regardless of selector order --
  so toggling `.hidden` on a `.field`/`.field-toggle` element (both the new
  `holiday-field`s and, on reflection, the exact same reason
  `.event-start-end-field` already uses an explicit `display:none` `:has()`
  rule rather than the bare attribute) never actually hid anything, it just
  silently set an attribute the box model ignored. New
  `.field.holiday-field[hidden]{display:none;}` in `style.css` gives it the
  specificity it needs. No JS/template change needed -- `recurrence_picker.
  js`'s `sync()` and `_event_form_fields.html`'s server-rendered initial
  `hidden` attribute were both already correct, just invisible. Full suite
  1313 passed (no new tests -- CSS-only fix, existing structural tests
  already assert the `hidden` attribute's presence/absence, which was
  never the broken part).
- **Shipped:** side work — **Exclude Saturday/Sunday folded into the
  Holiday calendar dropdown**, complete (2026-08-14), direct follow-up
  ("add exclude saturday and sunday into the holiday drop down menu as
  checkboxes at the end"). `_widget_list_multiselect.html` (the shared
  single/multi-select dropdown Recurrence/Ends/Labels already use) gained
  two new optional params: `ms_extra_checkboxes` (a list of independent
  `{name, id, label, checked}` boolean fields, each its own real form
  field, rendered as extra rows after a new `.multiselect-option-divider`
  separator at the end of the panel — not part of the picker's own
  single/multi-select group) and `ms_hidden` (starts the outer `.field`
  with the `hidden` attribute set). `_event_form_fields.html`'s three
  separate Holiday calendar / Exclude Saturday / Exclude Sunday fields
  collapsed into one such dropdown — `holiday_calendar` (single-select
  radios, an explicit `{'uid': '', 'name': '(none)'}` leading the list so
  "no calendar" is a real selectable option instead of the widget's
  "nothing selected -> defaults to the first item" fallback silently
  forcing whichever calendar sorts first) plus the two exclude checkboxes
  via `ms_extra_checkboxes`. The whole dropdown keeps the single
  `holiday-field` class from the slice above, so
  `recurrence_picker.js`/`style.css`'s recurring-only show/hide is
  unaffected — it now toggles one dropdown instead of three fields. No
  server-side change: `routers/calendar.py`/`dashboard.py`'s create/update
  still read the same three plain form field names. Verified by rendering
  `calendar_router.new_event_form` directly (temporary test, not kept) —
  radios/divider/checkboxes render in the right order inside one panel.
  Full suite 1313 passed (no new tests — presentation-only regrouping of
  three already-covered fields; `test_holiday_calendars.py`/
  `test_recurrence_terminology.py`/`test_modal_footer_and_inputs.py` still
  assert the same field names/round-trip).
- **Shipped:** side work — **Calendar Week + Timetable merged, "Unscheduled
  work" sidebar made collapsible**, complete (2026-08-14), direct feedback
  ("merge the calendar's week view with the timetable view. make the
  Unscheduled work block collapsible via a sidebar button"). The separate
  "Timetable" sub-view (side work, 2026-08-14 earlier the same day) is gone
  as its own page -- `routers/calendar.py::week_view` (`GET /calendar/week`)
  now renders ONE grid with both capabilities at once: ordinary events stay
  fully interactive (drag-to-move/resize, drag-to-create on empty space, via
  `static/calendar.js`) AND every work-allocation event renders prominently
  as a draggable `.work-allocation` block (`static/project_calendar.js`)
  alongside the "Unscheduled work" sidebar that drags a task onto the grid
  to schedule it. `templates/calendar_timetable.html` deleted;
  `calendar_week.html` absorbed its grid/sidebar markup — grid columns now
  carry BOTH `.calendar-create-col` and `.project-calendar-col`, so both
  scripts' interactions coexist on the same page. Two real conflicts this
  surfaced and fixed:
  - `calendar.js`'s own `.time-event` selector would have double-attached a
    pointerdown handler to every `.work-allocation` block (which
    `project_calendar.js` already owns) -- changed to
    `.time-event:not(.work-allocation)`.
  - `style.css`'s `.project-calendar-col{cursor:default}` (written to kill
    the Calendar grid's "click-drag to create" cursor on the planning-only
    surfaces) would have silently killed it here too, where drag-to-create
    is still a real gesture -- scoped to
    `.project-calendar-col:not(.calendar-create-col)`.
  `GET /calendar/timetable` and the old `/calendar/timetable/allocations...`
  trio are gone; the page redirects to `/calendar/week` (any bookmark still
  lands somewhere real) and the allocation endpoints moved to
  `/calendar/week/allocations...` (`create_week_allocation`/
  `move_week_allocation`/`delete_week_allocation`). Every calendar
  template's subnav (`calendar_month.html`/`_fourweek.html`/`_day.html`)
  dropped its separate "Timetable" entry -- Month/4-Week/Week/Day, four
  tabs, not five.
  New `static/unscheduled_panel_toggle.js`: a header button
  (`#unscheduled-panel-toggle`, `{{ icon('sidebar', ...) }}`) collapses/
  expands the sidebar to a narrow rail, state persisted per-device
  (`localStorage`, same category as `timeline.js`'s gutter-width
  preference) -- no server state, nothing to sync.
  `tests/test_calendar_timetable.py` deleted; replaced by
  `tests/test_calendar_week_scheduling.py` (29 tests, testing the merged
  `week_view`/`create_week_allocation`/`move_week_allocation`/
  `delete_week_allocation`/`timetable_view_redirect`, plus new coverage for
  the collapse toggle button, the redirect, and that ordinary events stay
  fully interactive instead of subdued `.context-event` context). One
  existing assertion updated for the real, deliberate class-list change
  (`test_calendar_viewport_layout.py`'s exact-match now expects
  `"card calendar-viewport project-calendar-grid"`). Full suite 1317
  passed.
- **Fixed:** side work — **merged Week view: work-allocation blocks are
  border-only (no fill), and the scheduling-drag ghost matched its real
  1-hour outcome**, complete (2026-08-14), immediate follow-up feedback on
  the merge above. Two independent fixes:
  - **Styling** ("timetable tasks time allocation should never be colored,
    only a thick colored border") — `.time-event.work-allocation` no longer
    inherits its `.cal-<hue>` class's solid background fill; a new override
    rule (placed AFTER the `.cal-*` swatch block in `style.css` so it wins
    the same-specificity cascade) gives it `background:var(--bg-elevated)`
    and a `3px solid` border instead, colored via a `--wa-border` CSS custom
    property each template now sets inline (`var(--cal-bg-<hue>)`, the same
    vivid hue variable the fill used to read) -- `calendar_week.html`,
    `week_planning.html`, and `project_calendar.html` (every template that
    renders a `.work-allocation` block) all updated.
  - **Drag-preview/outcome mismatch** ("shows 30 minute event but after
    dropping it is 1 hour... should always be 1 hour") — root cause,
    confirmed live: `calendar.js`'s own click-to-create hover-preview ghost
    (always 30 minutes tall, its own default) was ALSO rendering while
    dragging a task from the Unscheduled work panel, because the merged
    grid's columns now carry `.calendar-create-col` (calendar.js's trigger
    class) in addition to `.project-calendar-col` -- something that could
    never happen before the merge, since calendar.js was never loaded
    alongside project_calendar.js on the same page. Fixed with a shared
    `window.__ccGridDragActive` flag: `project_calendar.js` sets it true for
    the duration of ANY of its own drags (the task-panel drag, and block
    move/resize, for the same reason) and false when the drag ends;
    `calendar.js`'s hover-preview pointermove/pointerdown handlers check it
    first and stand down entirely while set. `project_calendar.js`'s
    task-panel drag (interaction 1) also gained its own accurate
    replacement: a real grid-anchored `slotGhost` (reusing calendar.js's own
    `.schedule-ghost` look), always exactly `DEFAULT_BLOCK_MINUTES` (60)
    tall at the snapped drop position inside the hovered column -- computed
    with the identical snap math `end()` uses to actually create the
    allocation, so the preview and the outcome can never disagree again.
  New `TestGridDragConflictFix` in `test_calendar_week_scheduling.py` (3
  structural JS-source tests, same convention as `test_pwa_shell.py`'s own
  JS structural checks -- no browser in this test environment). Full suite
  1320 passed.
- **Fixed:** side work — **work-allocation blocks are one uniform drag
  target, title included**, complete (2026-08-14), immediate follow-up
  ("why can't it function like any other event so that the whole div is a
  link and can be moved at the same time?"). Root cause: `.te-name` (the
  block's title) was a real nested `<a href="/tasks/{uid}" data-modal>`,
  and `project_calendar.js`'s block pointerdown handler had to explicitly
  exclude clicks starting on it (`e.target.closest(".te-name")`) so its
  native click could still navigate -- meaning you could NOT move a block
  by grabbing its title text, only by grabbing the surrounding padding,
  unlike an ordinary `.time-event` (itself a single `<a>`, draggable
  anywhere on itself, since calendar.js owns click-vs-drag uniformly at the
  JS level with no competing native link). The block can't itself become a
  real `<a>` the same way (it also contains a delete `<form>`/`<button>`,
  which `<a>` cannot legally contain), so instead `.te-name` dropped its
  `<a>`/`href`/`data-modal` down to a plain `<span>` across all three
  templates that render a `.work-allocation` block (`calendar_week.html`,
  `week_planning.html`, `project_calendar.html`) -- opening the task view
  is already handled uniformly by `project_calendar.js`'s own interaction 4
  (any non-drag click, anywhere on the block) via `taskUrlBase`, so nothing
  about "click to open the task" changed; only "click-drag to move" now
  works from anywhere on the block, title included. `project_calendar.js`'s
  pointerdown handler's `.te-name` exclusion removed (the
  `.work-allocation-delete` exclusion stays, so the delete button keeps
  working). Three tests updated (`test_calendar_week_scheduling.py`/
  `test_week_planning.py`/`test_project_calendar.py`, each had one
  `'href="/tasks/t1"' in body` assertion -- now asserts that href is GONE
  and the title renders as a plain `<span>`). Full suite 1320 passed.
- **Shipped:** side work — **Month view: events draggable to move, timetabled
  tasks hidden**, complete (2026-08-15), direct feedback ("in calendar, month
  view, events should be able to be moved via mouse. Timetabled tasks should
  not be visible in the calendar view"). Two independent changes to
  `routers/calendar.py::month_view`/`templates/calendar_month.html`:
  - **Timetabled tasks (work-allocation events) excluded from Month** — new
    `db.work_allocation_event_uids(conn)` (one bulk query, the N+1-avoiding
    counterpart to `db.work_allocation_task_uid`) filters `month_view`'s
    `events` list before `_month_grid` ever sees it, so a scheduled work
    block never renders as a third kind of Month item duplicating the task's
    own due-date chip. Week/Timetable is untouched (work allocations stay
    deliberately prominent there, per `week_view`'s own docstring) — this is
    Month-only, since that's the surface the feedback named.
  - **Drag-to-move an event chip between day cells** — new
    `static/calendar_month_drag.js`, loaded alongside the existing
    click-and-hold drag-to-*create* script (`calendar_month.js`, unchanged).
    Reuses the Week/Day grid's own `POST /events/{uid}/reschedule` JSON
    endpoint (`static/calendar.js`) rather than adding a new route — Month
    has no time axis, so a drop only ever shifts the event's existing
    start/end timestamps by the whole-day delta between the origin and
    target cell, time-of-day untouched. `calendar_month.html`'s all-day and
    timed "event" kind chips (not task chips) gained a shared
    `.month-event-item` class plus `data-uid`/`data-start`/`data-end`/
    `data-all-day` — but only when the event is non-recurring: a recurring
    event's chip renders with no `data-uid` at all, so the drag script never
    attaches to it (only the whole `events` row exists to reschedule, and
    shifting it would move the entire series, not the one occurrence being
    dragged — same footgun manual-recurrence-exceptions exists to avoid
    elsewhere; a click still opens a recurring chip normally, only the drag
    affordance is withheld). Click-vs-drag disambiguation mirrors
    `calendar.js`'s own `CLICK_THRESHOLD_PX` pattern so a plain click still
    navigates via the chip's `href`. On a successful drop the page does a
    full reload (not an optimistic DOM patch) — unlike the Week grid's
    single block's top/left, a Month move can shift an item between two
    cells' own `rows`/overflow-count/`"+N more"` lists, which only a fresh
    server render keeps consistent. New `.month-day-cell.drop-hover`/
    `.month-event-item.dragging` CSS, same vocabulary as the Week grid's own
    `.time-col.drop-hover`/`.time-event.dragging`.
  4-Week view (`calendar_fourweek.html`) has its own separate markup and was
  not touched — still shows work-allocation events and has no drag-to-move,
  since the feedback named Month specifically. 21 existing tests
  (`test_calendar_month_bars.py`/`test_calendar_month_quickcreate.py`)
  still pass unchanged; no new tests added (drag interactions need a real
  browser, same "structural JS-source checks only" ceiling as the app's
  other pointer-drag scripts — no assertion gap opened here that other
  Month tests weren't already leaving). Full suite 1316 passed, 4 pre-existing
  failures in `test_today.py` confirmed unrelated (reproduce identically on
  the pre-slice commit via `git stash`; a UTC-vs-local `date.today()` /
  test-module-import-time date mismatch in this sandbox, not caused by this
  slice).
- **Shipped:** side work — **Sleep Time / Leisure Time**, complete
  (2026-08-15), direct feedback ("Add an option in the settings to set-up
  Leisure Time and Sleep Time... similar to the holiday settings, but just
  adding the hours... and days... a soft hatching... that when placing an
  event to timetable an event there gives a warning"). New `time_blocks`
  table (`db.py`: `kind` fixed to `'sleep'`/`'leisure'` — not a user-named
  open-ended set like a holiday calendar — plus `label`, `start_time`/
  `end_time` as plain `"HH:MM"`, `days` a comma-joined subset of the new
  `db.TIME_BLOCK_DAYS`; no date component at all, this is a weekly
  recurring rule, not a dated range) plus `upsert_time_block`/
  `get_time_block`/`delete_time_block`/`list_time_blocks`/`time_block_days`,
  same minimal shape as `schedule_holidays`' own functions.
  - **Settings > Sleep & Leisure Time** (`/settings/time-blocks`,
    `routers/settings.py`, new hub category) — same Tasks-table-style grid
    as Holidays, two sections (Sleep, Leisure), each row inline-editable
    (`POST /settings/time-blocks/{uid}/update-field`,
    `_TIME_BLOCK_UPDATABLE_FIELDS`). Days picked via
    `_widget_list_multiselect.html` in `filter` (multi-select) mode rather
    than Holidays' `single` mode — "days" genuinely is a set, not one
    choice. Deliberately two duplicated top-level template sections rather
    than one Jinja macro wrapping the shared multiselect include — that
    partial's own set-then-include pattern is only proven directly inside a
    template body/for-loop elsewhere in this codebase, not inside a macro's
    local scope, so this didn't risk a scoping surprise for a two-line
    saving.
  - **Week/Day grid hatching** — `routers/calendar.py::
    _time_block_overlays_for_day` resolves each visible day's applicable
    blocks (by `date.strftime('%A')` against `days`) into top/height px,
    same math `grid_layout.position_event` uses for a real event; both
    `week_view` and `day_view` compute this per day and
    `calendar_week.html`/`calendar_day.html` render a `pointer-events:none`
    `.time-block-overlay.time-block-{sleep,leisure}` div per block, behind
    every real event (z-index 1 vs events' 3) so no drag/click interaction
    is affected. Red/green via the app's existing `--danger`/`--success`
    vars, not new colors. Month has no time axis and was left untouched —
    "the calendar view" in the feedback read as Week/Day, the two views
    that actually have hours to hatch.
  - **Scheduling warning** — new `static/time_blocks.js` (loaded only on
    `calendar_week.html`/`calendar_day.html`, reading a page-local
    `<script type="application/json" id="cc-time-blocks">` tag built by
    `routers/calendar.py::_time_blocks_client_payload`) exposes
    `window.ccTimeBlocks.warnIfOverlapping(dateStr, startMin, endMin)`.
    Wired into `static/calendar.js`'s block-move/resize `end()` and
    `static/project_calendar.js`'s work-allocation create-drag and
    move-drag `end()`s (both guarded by `if (window.ccTimeBlocks)`, a
    silent no-op on `/week`/the project Week Calendar, which render no
    `cc-time-blocks` tag) — a `toast-warning` toast ("Heads up: this
    overlaps Sleep Time...") fires alongside the save, never blocking or
    reverting it (the feature request's own "gives a warning," not "gives
    an error"). The drag-to-*create a brand-new plain event* path
    (calendar.js's `finishCreate`) deliberately has no warning call — it
    only opens the New Event form prefilled, nothing is placed yet at that
    point. New `.toast-warning` CSS (`var(--warning)`, dark text — the app's
    existing amber "caution" color, distinct from `.toast-error`'s red).
  24 new tests (`test_settings_time_blocks.py`: the Settings page/routes,
  `_time_block_overlays_for_day`, `_time_blocks_client_payload`, and that
  Month renders no hatching), plus `test_phase8_settings_hub.py`'s hub-URL
  set updated for the new category. Full suite 1340 passed (same 4
  pre-existing unrelated `test_today.py` failures as the slice above).
- **Shipped:** side work — **Week/Day never opens scrolled to a Sleep hour
  + fixed a real 12h/24h bug in the Work sessions card**, complete
  (2026-08-15), direct follow-up feedback on the slice above ("the calendar
  week view should never start at an hour that is marked as sleep... if
  sleep from 00-06 AM, the week/day views should start from 6 AM, not 12
  AM. Also, the app should respect the user choice of date preference 12
  or 24 hours").
  - **Initial scroll** — `static/time_blocks.js` (already loaded on
    `calendar_week.html`/`calendar_day.html`) now also runs, once per page
    load, over every visible `.time-col[data-date]`'s own date; if ANY of
    them has a Sleep block covering midnight (`start_min <= 0 <
    end_min`), it sets `.time-grid-wrap.scrollTop` past the LATEST such
    block's end time (measuring `.time-grid-body`'s real rendered offset —
    it sits below the sticky `.time-grid-top` header in normal flow — plus
    its own half-hour top padding, rather than assuming a fixed header
    height). Leisure blocks never affect this — only Sleep, and only a
    block that actually covers minute 0, per the feedback's own example. A
    no-op (grid opens at the top exactly as before) when no configured
    Sleep block covers midnight on any visible day. No server-side change
    needed — reuses the same `cc-time-blocks` JSON payload the scheduling
    warning (slice above) already reads.
  - **12h/24h audit turned up one real, unrelated bug**, fixed alongside:
    `_task_work_allocations.html`'s "Work sessions" card (task detail/edit
    modals) was slicing the raw stored ISO string directly
    (`wa.start_at[:16]`/`wa.end_at[11:16]`) instead of going through
    `deps.py`'s `fmt_time` filter — the one place in the app that still
    showed a session's time in bare 24h regardless of the "24-hour time"
    Settings > General preference. Fixing the field alone wasn't enough:
    `task_detail.html`/`task_form.html` import that card as a Jinja macro
    across a file boundary (`{% from "_task_work_allocations.html" import
    task_work_allocations_section %}`), and a macro imported that way does
    NOT inherit the caller's template context (so `fmt_time`'s
    `@pass_context` read of `request` silently saw `None` and fell back to
    its 24h default) unless imported `with context` — both import lines
    needed that added, the same fix `_unscheduled_task_item.html`'s own
    import already used for the identical reason. Confirmed live via a
    synthetic-request smoke test before writing the fix (empirically, not
    from reading the filter's source alone) — the bug reproduced exactly
    as described, and the fix's before/after were both verified against a
    real `request.app.state.settings.db_path`-backed Request, not a bare
    one (a bare `Request({...})` with no `.app` at all silently falls back
    to the 24h default through a *different* path — `_cached_app_meta`'s
    own broad except — which would have hidden this bug's real cause
    during manual testing). No other `fmt_time`/`fmt_hour` call site had
    this problem — checked every template using either filter; the rest
    are either not macros or already `{% include %}`d (context-inheriting
    by default, unlike `{% from %}` import).
  9 new tests: 4 structural JS-source checks in `test_settings_time_
  blocks.py` (`TestSleepAwareInitialScroll` — no browser in this test
  environment to assert a real scrollTop, same ceiling
  `test_pwa_shell.py`'s own pointer-drag script tests already accept), 5 in
  `test_display_prefs_settings.py` (`TestFmtTimeFilterInWorkSessionsCard`
  — 24h default, 12h when set, and that `task_form.html`'s edit view
  respects it too). Full suite 1347 passed (same 4 pre-existing unrelated
  `test_today.py` failures).
- **Shipped:** side work — **`/today` and `/week` retired, folded into the
  Dashboard and Calendar**, complete (2026-08-15), a single large session
  (user-approved deviation from this file's own one-slice default) covering
  three ordered pieces:
  1. **New Dashboard widget types, built and verified before anything was
     deleted** (the session's own content-loss guard) — `routers/
     dashboard.py`'s `WIDGET_TYPES` registry grew three entries:
     `important_urgent` (open tasks flagged important/urgent that aren't
     already due/overdue, `_render_important_urgent` — the exact
     `derived_state.virtual_states` logic `/today` used, right down to
     excluding anything already shown as due/overdue) and
     `scheduled_work_today` (today's work-allocation sessions + a
     completed-hours total, `_render_scheduled_work_today` — the same
     `db.work_allocation_task_uid` per-event lookup `/today` used), both
     addable through the existing Source/View picker
     (`important_urgent_view`/`scheduled_work_view` under the
     `calendar_tasks` source). Also added `quick_links` (a visual tile grid
     of every Space + every open project, `label_config.icon`/`color` and
     `filled_cards`' own `.filled-card` CSS reused, no new visual language
     — the "more visual, less data-heavy" ask; the app has no separate
     "pinned"/"favorite" concept, confirmed by reading `label_config`'s own
     schema comment first rather than inventing one, so "every Space + every
     open project" is the deliberately-simple v1), its own new
     `quick_links`/`quick_links_view` source since it reads `label_config`
     directly (`uses: set()`, same shape as `project_preview`/
     `filled_cards`) and is excluded on Space/Project page scopes for the
     same "meaningless once you're already inside one" reason those two
     already were. Found and fixed a real Jinja footgun while wiring these
     up: a render function's returned dict must never use the key name
     `"items"` — Jinja's attribute-then-item lookup silently resolves
     `data.items` to `dict.items` (the builtin method) instead of the
     stored key, reproduced live before renaming to `rows`/`tiles`. Also
     audited every `_widget_*.html` partial for the double-line date+time
     wrap bug already found in `_widget_upcoming_events.html` (a fixed
     110px `<td>` holding both a date and a time, per this slice's own
     starting brief) — that was the only one; every sibling widget shows
     either just a time or just a date in its narrow column, never both.
     Widened to 150px + `white-space:nowrap`. 19 new tests.
  2. **`/today` retired as a redirect** — `routers/today.py`,
     `templates/today.html`, `tests/test_today.py` deleted; `GET /today`
     now redirects (302, `routers/dashboard.py::today_redirect`) to `/`.
  3. **`/week` retired as a redirect** — confirmed first, by reading both
     routers/templates directly rather than assuming, that its entire
     cross-project planning capability (Unscheduled work sidebar,
     drag-to-schedule, block move/resize/delete, session stepper) was
     already fully present at `/calendar/week`, a leftover from the earlier
     "Calendar Week + Timetable merged" side work (2026-08-14) — `/week` had
     become a third copy of the same thing, not a distinct surface.
     `routers/week.py`, `templates/week_planning.html`,
     `tests/test_week_planning.py` deleted; `GET /week` now redirects (302,
     `routers/calendar.py::week_redirect`, registered on that module's
     unprefixed `events_router` since the redirect's own path can't live
     under `router`'s `prefix="/calendar"`) to `/calendar/week`, preserving
     `?date_=`. Same "any bookmark still lands somewhere real" precedent
     `timetable_view_redirect` already set for `/calendar/timetable`.
  Both tabbar entries removed from `base.html` (Home/Calendar/Tasks/
  Projects/Schedule/Contacts remain) — the explanatory comment there is a
  Jinja `{# #}` comment, not an HTML `<!-- -->`, so the retired path text
  doesn't leak into rendered markup (an HTML comment would have broken
  `test_calendar_week_scheduling.py`'s own "no stale `/calendar/timetable`
  text anywhere in the body" assertion the same way). `main.py`'s router
  imports/`include_router` calls for `today`/`week` removed.
  `features/today.md`/`features/week.md` rewritten as short retirement
  notices (where their content lives now / why the merge was safe),
  `features/dashboard.md` documents all 3 new widget types (now 14 total)
  and the scope-exclusion change, `features/calendar.md`/`features/
  tasks.md` had their stray `/week` mentions updated to stop implying a
  separate page still exists, `features/README.md`'s table/tour updated.
  `plans/roadmap.md`/`open-priority.md` needed no changes — their 1.7
  Today/Week entries were already struck-through shipped history, not
  open items, so nothing there was stale. New
  `tests/test_dashboard_today_week_widgets.py` (24 tests: the 3 render
  functions incl. tag-filter/limit/archived-project edge cases, both
  redirects incl. `/week`'s `?date_=` passthrough, the tabbar/router-file
  removal, the double-line fix). Full suite **1337 passed** — the 4
  previously-pre-existing `test_today.py` failures are gone along with the
  file itself (a UTC-vs-local `date.today()` test-environment quirk, not
  worked around, just moot now that the file is gone), confirmed this is
  the *only* change in the failure count by running the full suite after
  each of the three commits, not just at the end.
- **Shipped:** side work — **/projects rework: square colored cards,
  click-to-open, create/edit moved into Settings**, complete (2026-08-15),
  direct feedback ("square colored cards... open with click, not an open
  button... creating/editing done entirely in settings"). `templates/
  projects.html` is now a pure display surface: each project is one
  `<a class="project-card-square cal-{{ p.color }}">` (new `.project-grid`/
  `.project-card-square*` CSS, `static/style.css`) — the whole card is the
  link (no inner Open button), full-bleed in the project's own `.cal-*`
  swatch (the same palette every other `.cal-*` consumer already uses, not
  a second one), `aspect-ratio:1` via `auto-fill`/`minmax` grid, status
  pill + progress bar + task/deadline line inside, Archived cards dimmed
  via `.is-archived`. The promote-a-label form, per-project dates form,
  and Archive/Demote actions moved off this page entirely onto Settings >
  Labels (`templates/labels_manage.html`'s existing Project `<td>`, using
  the `.label-table details > summary` styling that already existed
  there unused): not-yet-a-project rows get a `<details>` "promote" popover
  (dates + submit -> `/projects/promote`), is_project rows get one showing
  status + an inline dates-save form + conditional Archive + Demote,
  matching every other per-label control's "own cell on this row" shape.
  `routers/labels.py::manage_labels` now computes `project_status` per
  is_project row (`db.project_status`) and accepts the same `overlap`/
  `pending_*` query params `routers/projects.py`'s promote/dates conflict
  redirects already produced — `_redirect_with_conflict` and every
  promote/dates/demote/archive success redirect in `routers/projects.py`
  now target `/labels` instead of `/projects` (the overlap-warning card
  itself moved into `labels_manage.html`, `projects.html` dropped
  `overlap_name`/`pending`/`existing_labels` from its context entirely).
  No schema/endpoint changes — `promote`/`set_dates`/`demote`/`archive`
  are the same functions with the same params, only their redirect target
  and the form markup that posts to them moved; `tests/test_project_
  stack.py`'s router-level tests (status-code/location-substring only,
  never asserting on `/projects` specifically) needed no changes and all
  still pass. Verified both pages render end-to-end (not just unit-level)
  via a one-off script seeding a real project + tasks and calling
  `list_projects`/`manage_labels` directly, checking the actual rendered
  HTML for the card markup, the promote/dates/demote forms, and the
  overlap-warning card together — router-function-call convention doesn't
  by itself prove Jinja renders without error, since most existing tests
  only assert on `resp.context`, not `resp.body`. Full suite still 1337
  passed (no test count change — this was a display/relocation change, not
  new behavior needing new coverage).
- **Shipped:** side work — **Settings > Labels: table replaced by a
  simple list + full edit modal, Space/Project made mutually exclusive**,
  complete (2026-08-15), direct feedback ("the table should be
  transform[ed] into a simple list... a button that opens a modal window
  to edit labels with all the colors, icons, etc... becoming a project
  should be mutual exclusive to a space — selected via a fancy dropdown
  menu. Spaces or project settings appear only after being selected").
  `templates/labels_manage.html`'s `<table>` (one column per control) is
  now `.label-list` (`static/style.css`): one flex row per label showing
  a color dot, icon, name/abbreviation, usage count, a Space/Project role
  badge, and a single Edit button (`data-modal="/labels/{name}/edit"`).
  Every per-label control that used to be its own column — rename,
  color, icon, parent, abbreviation, description, Space, Project
  (promote/dates/archive/demote, which had briefly landed as this page's
  own `<details>` popover earlier the same day, see this file's prior
  entry), Merge, Remove — moved into one new modal (`templates/
  label_edit_modal.html`) with a single Save button
  (`routers/labels.py`'s new `GET /labels/{name}/edit` +
  `POST /labels/{name}/update`, replacing that popover's calls into
  `routers/projects.py` for the UI's own purposes — those endpoints are
  untouched and still directly tested by `tests/test_project_stack.py`,
  just no longer linked to from anywhere).

  **Space and Project are now one mutually-exclusive Role** (segmented
  radio: Plain / Space / Project — `routers/labels.py::_label_role`),
  not two independent checkboxes: picking "Project" always clears
  `generate_space`, picking "Space" always clears `is_project`/dates/
  `archived_at`, so a label saved through this form can never end up
  with both set (a pre-existing label saved before this rework that
  somehow has both keeps `is_project` winning until next edited — no
  migration script, matching this app's usual "correct going forward,
  don't rewrite history" convention). The Project date fields render
  `hidden` until "Project" is selected and reveal with no page reload
  (new `static/label_role_picker.js`, same `init(root)`-called-by-
  `modal.js` pattern `task_habit_field_toggle.js` established, loaded
  globally in `base.html` since this page is only ever opened via
  `data-modal`). Switching *away* from a role with real data asks for
  confirmation first (`data-confirm-sheet`, purely client-side, computed
  once at GET time into `data-original-role`/`data-warn-role` and kept
  in sync with the live radio selection) — a Project always (loses its
  period + lifecycle), a Space only if it actually has child labels
  grouped under it (`db.list_child_labels`); switching between two roles
  that both had nothing to lose (e.g. Plain → Space) asks nothing.
  Promoting to Project still runs the existing overlap check
  (`db.find_overlapping_project`) — inside a modal there's no clean way
  to show the old page's rich "Save anyway" warning card (`modal.js`'s
  keep-open forms re-fetch their own URL on success and never render a
  POST's own response body), so a conflict is a 409 + toast instead, with
  a plain "Allow this period to overlap" checkbox in the form
  (`confirm_overlap`) as the override — a real UX simplification, not
  just a stopgap, noted here in case a future session wants to revisit
  it. `static/label_search.js` generalized from table/tbody-specific
  selectors to the new div-based list (same `data-label-group`/
  `data-label-row`/`data-label-group-header` attributes, only the
  container id changed). Four `tests/test_modal_input_phaseC_swatch_
  grid.py` tests that asserted the color/icon picker markup on the old
  table rows updated to assert it on the new edit modal instead (same
  intent, moved surface) — one split in two for the "no picker on the
  list, has one in the modal" distinction, net +1 test. Full suite
  **1338 passed**, plus a one-off script exercising both pages end-to-end
  (list rendering, all three role states' modal markup, missing-dates
  400, overlap 409, successful promote, the mutual-exclusivity clear on
  a Project→Space switch, and rename-through-Save) — router-function-
  call tests alone don't prove the client-side confirm/reveal JS
  actually gates anything, so that part is reasoned from reading
  `label_role_picker.js` and `modal.js`'s own submit-handling code
  directly rather than executed (no browser in this sandbox).
- **Fixed/reworked:** side work — **Settings > Labels follow-up: fixed
  the Role reveal bug, Group limited to Spaces only, overlap always
  allowed, Merge moved back to the list, footer is Cancel/Delete/Save**,
  complete (2026-08-15), same-day direct feedback on the slice above.
  - **Bug, found and fixed:** the Project date fields never actually
    appeared when picking "Project" in the Role control. Root cause:
    `.field{display:flex}` (style.css) is author CSS of equal specificity
    to the browser's own `[hidden]{display:none}` UA rule, and author
    always wins that fight regardless of specificity — the exact
    pre-existing footgun `.field.holiday-field[hidden]{display:none}`
    was already added to work around once (recurrence_picker.js's
    holiday-calendar fields, see that rule's own comment). Same fix:
    `.field.label-project-fields[hidden]{display:none}`.
  - **Overlapping project periods are always allowed now** — "shouldn't
    exist because it should always be true" — the `confirm_overlap`
    checkbox and the whole 409-conflict path removed from
    `update_label`/`label_edit_modal.html` entirely. `db.find_
    overlapping_project` and routers/projects.py's own promote/set_dates
    (still directly tested) are untouched; nothing in the UI calls the
    check anymore.
  - **"Parent label" renamed to "Group" and limited to Spaces only** —
    confirmed with the user this should stay wording-only for what
    Group *does* (still both the Settings-list grouping key and what
    feeds a Space's generated page), but *how it's set* changed: a
    `<select>` of existing Space labels only (`edit_label_modal`'s new
    `space_label_names`, plus the label's own current parent even if
    stale/non-Space, so Save can never silently drop it), not a free-text
    field that could name anything. `update_label` enforces the same
    constraint server-side (400 if `parent_name` isn't blank or an actual
    `generate_space` label). Direct follow-up ask: "the list UI should
    display Spaces differently and always keep their children in their
    group" — `manage_labels` rewritten to build `space_groups` (each a
    Space label plus its resolved `children`, i.e. every label whose
    `parent_name` names it) and `ungrouped` instead of a flat
    `parent_display` groupby; a Space's own row IS its group's heading now
    (`.is-space`, bold/tinted) with children rendered directly under it
    indented (`.is-child`), not a disconnected text divider naming the
    same string. **Named the context variable `space_groups`, not
    `spaces`** — found live, the hard way: `base.html`'s nav rail already
    does `{% set spaces = sidebar_spaces(request) %}` at its own top
    level, which silently shadows a same-named context variable for the
    rest of that render (Jinja `{% set %}` writes to shared `Context.vars`,
    checked before the original context dict) — the page rendered its
    empty state even with a correctly populated `spaces` sitting right
    there in the router's own returned context, extremely confusing to
    debug until traced to this collision. `static/label_search.js`
    updated for "a group's header can itself be a real, searchable label
    row" (a Space's own name now matches too, not just its children).
  - **Merge reverted back out of the edit modal to its own small modal**
    (direct follow-up: "I was wrong about that") — new `GET /labels/
    {name}/merge-modal` + `label_merge_modal.html` (just the destination
    picker + confirm, posting to the unchanged `/labels/{name}/merge`), a
    Merge icon-button added back to each list row (hidden when there's
    only one label total, nothing to merge into).
  - **Edit modal footer is now exactly Cancel / Delete / Save** — the old
    "Remove from everything" wording relabeled to "Delete" (same
    `/labels/{name}/clear` action underneath, `btn danger` styling
    matching `habit_form.html`'s own Delete convention). Also dropped the
    explanatory paragraph under Role per direct feedback ("remove the
    abundant labels").
  Full suite still **1338 passed** (no test-count change — every change
  here is UI/validation-shape, not new testable surface within this
  session's scope), plus a fresh end-to-end script re-verifying all of
  the above against real seeded data (grouping/nesting, overlap no longer
  blocking, Group's Space-only enforcement both directions, the edit
  modal's shape, the merge modal, and the CSS fix's presence).
- **Fixed:** side work — **Labels list: gray group titles instead of
  tree-like grouping, bigger icons, no cell-tag/color-dot, narrower
  list**, complete (2026-08-15), direct follow-up feedback on the row
  above's "a Space's own row IS its group's heading" design ("I would
  preffer to not have tree like grouping, but grouping like it was
  before"). `labels_manage.html`'s `label_row` macro dropped its
  `is_space`/`is_header` params entirely: a group's heading is now always
  a plain gray `.label-list-group-header` text title (the Space's name,
  or "Ungrouped"), and the Space itself renders as an ordinary
  non-bold `.is-child` row directly under its own heading, at the same
  indent as its children — no row doubles as both a heading and a list
  item anymore. Also dropped the per-row `.color-dot` and the
  Project/Space `.cell-tag` role badge (direct feedback, "remove their
  cell-tag") — a row is icon + name + usage count only now, role/color
  still live in the Edit modal. Icons bumped from the default 15px to
  19px (`.label-list-icon .icon`, direct feedback, "the icons a bit
  bigger") since the icon is now the only per-row color/identity cue
  left. `.label-list` capped at `max-width:480px` (direct feedback,
  "make the list more narrow"). `static/label_search.js` needed no
  changes — the new plain-text header still carries `data-label-group-
  header` + a lowercased `data-label-name` for the same "searching a
  Space's own name keeps it visible" behavior. Full suite still 1338
  passed (no test-count change, same reasoning as the row above — pure
  CSS/markup rework, no new testable surface).
- **Shipped:** side work — **`/projects` page retired, folded into the
  Tasks table**, complete (2026-08-15), direct feedback ("the projects page
  and pages derived from it... are not worth existing... Task view for
  projects could just be a way to group tasks in the Table view"). Scoped
  first via `plans/open.md`'s decision record (now removed from that file
  per its own "ships -> describe outcome, remove the section" convention),
  then implemented same session. **Presentation-only**, confirmed explicitly
  with the user: the label/project data model, Settings > Labels, and
  `promote`/`set_dates`/`demote`/`archive` are completely untouched — only
  the dedicated pages built to *view* a project are gone, both redundant
  with capability that already existed: the Tasks view duplicated
  `/tasks?group_by=project` (1.5, already shipped); the Week Calendar view
  duplicated the merged `/calendar/week` grid (2026-08-14 side work)
  filtered to one project, which already shows every work allocation
  regardless of project — the same "third copy of the same thing" reasoning
  that retired the standalone `/week` page.
  - `routers/projects.py::list_projects`/`project_detail`/`project_calendar`
    (and that page's own `create_allocation`/`move_allocation`/
    `delete_allocation` -- its own drag-and-drop backend, unused anywhere
    else since `/calendar/week` has its own independent, cross-project
    allocation endpoints) replaced by three thin redirects:
    `list_projects_redirect` (`GET /projects` -> `/tasks?group_by=project`)
    and `project_detail_redirect`/`project_calendar_redirect` (`GET
    /projects/{name}[/calendar]` -> `/tasks?label={name}`) — any bookmark
    still lands somewhere real, same precedent as `/today`/`/week`/
    `/calendar/timetable`'s own retirements. `_project_card` (now unused
    outside the deleted page routes) removed too.
  - `templates/projects.html`/`project_detail.html`/`project_calendar.html`
    deleted; `base.html`'s tabbar "Projects" entry dropped (Jinja comment,
    not HTML, in its place — same "no stale path text in rendered markup"
    reasoning as the `/today`/`/week` tabbar removals).
  - The two other Dashboard surfaces that linked to `/projects/{name}`
    repointed to `/tasks?label={name}` instead: `dashboard.py`'s
    `quick_links` widget tiles, and `_widget_project_preview.html`'s
    per-project rows (which used to go to `/labels/{name}`, the label's
    generated widget-grid page — confirmed with the user this should be
    the plain filtered Tasks table instead, no `group_by`, since grouping
    is meaningless once already filtered to one label).
  - `tests/test_project_detail.py` (12 tests) and `tests/
    test_project_calendar.py` (24 tests) deleted; `test_project_stack.py`'s
    `TestProjectsPage` (2 tests, called `list_projects` for its card data)
    replaced with `TestProjectPageRedirects` (3 tests, asserting the three
    redirect targets) — `promote`/`set_dates`/`demote`/`archive` coverage
    in that file untouched; `test_task_scheduled_column.py`'s
    `TestProjectDetailPage` (2 tests, called `project_detail` directly)
    removed, its "Scheduled column" coverage still intact via
    `TestGlobalTasksPage`. Net **1301 passed** (was 1338; -37 removed +3
    added, confirmed exactly matches the deleted-test count, not a
    regression).
  - **Not implemented, flagged for later if it matters:** whether
    `_task_row.html`'s project-scoped extraction (built for the now-gone
    project detail Tasks view, 1.4 slice 2) is still worth keeping as a
    shared macro now its only caller is the global Tasks page — left as-is,
    still works fine either way.
- **Shipped:** side work — **Importance/Urgency: explicit per-task axes
  removed, purely computed now**, complete (2026-08-15), direct feedback
  ("I want them to just be calculated automatically. No manual input").
  1.1 shipped the two axes as *explicit* fields combined with label rules
  via max-precedence; this slice drops the explicit half entirely.
  `tasks.importance`/`tasks.urgency` columns dropped from the schema
  outright (`db._drop_column`, new — a deliberate, narrow exception to
  this file's usual "never force-drop old data" convention, confirmed with
  the user before implementing; existing manually-set values are
  discarded, not migrated). `src/derived_state.py`: `effective_importance`
  = label-derived only, `effective_urgency` = max(label-derived, temporal)
  — no more `explicit` term anywhere in that module. No form field, no
  inline pill-select, exists for either axis anywhere in the app anymore;
  Table/Board/Detail render them read-only via two new Jinja globals
  (`effective_importance`/`effective_urgency`, `deps.py`, label rules
  memoized per request the same way `label_icon` already is) instead of
  reading a stored column, so no router needs to precompute/attach the
  value onto every task dict just to display a pill. `_task_row.html`'s
  Importance/Urgency pill-selects became read-only `.pill-static` spans;
  `_task_form_fields.html` dropped the two multiselect fields outright.
  Filters/sort (`routers/tasks.py`) switched from matching the raw stored
  value to matching the *computed* one (`_sort_keys` is now a factory
  taking `label_rules`, since sorting needs it); `_UPDATABLE_FIELDS` no
  longer accepts either axis via the inline-edit endpoint (400 if tried).
  WebDAV/CSV export still writes the *effective* value (routers/export.py,
  published_lists.py resolve label rules once and attach the computed
  values onto a row copy before calling `ical_rows.task_row_to_ical`,
  which itself stays DB-free); import no longer maps iCal `PRIORITY` back
  to anything (confirmed with the user: silently dropped, this app is the
  write-source) — `ical_rows._priority_from_ical` deleted as dead code.
  One real behavior consequence, not papered over: urgency level 1
  ("Low") has no source left under the purely-computed model (label
  thresholds only ever imply level 3, temporal state only ever yields
  0/2/3) and is effectively unreachable now — flagged in
  `features/tasks.md`, not fixed as out of this slice's scope. See
  `features/tasks.md` § Importance, Urgency, and the virtual states.
  Touched ~15 source files and 9 test files (mostly seed-helper rewrites:
  a manually-set axis is now reproduced in tests via a dedicated per-task
  label + label_config rule, not a raw stored field); full suite 1291
  passed (down from 1301 — one whole obsolete test class covering the
  removed manual-input UI deleted outright, several schema/round-trip
  tests rewritten to assert the opposite of before, not a coverage
  regression).
- **Shipped:** side work — **Importance/Urgency dropped from the Tasks
  Table columns**, complete (2026-08-15), immediate follow-up feedback on
  the slice directly above ("I don't want importance and urgency to show
  in the tasks table view"). `_task_row.html`'s two read-only `.pill-static`
  cells removed, `tasks_list.html`'s two sortable `<th>` headers removed —
  Table now shows Title/Status/Due/Scheduled/Labels only. **Table-view-only
  removal, not a feature removal**: both axes are still fully computed
  (`src/derived_state.py`, unchanged) and still visible on Board (pills)
  and the task detail modal (meta grid); the toolbar's Importance/Urgency
  filter dropdowns are untouched (this was about the columns, not
  filtering by the axis). `routers/tasks.py::_sort_keys` still supports
  sorting by either axis, just with no Table column header linking to it
  anymore. One test rewritten (`test_table_renders_both_as_read_only_pills`
  -> `test_table_does_not_render_either_axis`, asserting the columns are
  gone while the toolbar filters remain). Full suite 1291 passed (no
  count change — a markup-only removal, same reasoning as other pure-
  presentation slices in this file).
- **Removed:** the **Schedule module + Spaces University module**,
  complete (2026-08-15), direct user request ("I just want to drop
  Schedule entirely. It doesn't have a function right now.") — the
  university-timetable "classes" feature (`/schedule`, day/time/parity
  blocks, semester settings, credits, conflicts) is dropped entirely:
  `routers/schedule.py`, `src/schedule.py`, `schedule_classes.html`/
  `schedule_class_form.html`, `schedule_grid.js`/`schedule_table.js`,
  `scripts/migrate_schedule_classes_to_events.py`, and their dedicated
  tests are deleted outright; `main.py`'s router registration and
  `base.html`'s tabbar entry/scripts are removed. `db.py`'s
  `schedule_settings` table (+ `get_schedule_settings`/
  `save_schedule_settings`/`set_schedule_target_calendar`,
  `list_schedule_class_events`, `list_course_types`) and
  `label_config`'s `course_acronym`/`course_type`/`course_credits`/
  `course_professor_contact_uid` columns are gone. The Spaces
  "University module" (`_project_university_section.html`'s Course
  info/next-lecture badges/Homework table, `_education_next_lectures.html`,
  `routers/calendar.py::_group_education_next_lectures`) is removed
  alongside it — confirmed with the user directly — since it only ever
  got its data from Schedule's class-creation form and would be
  permanently empty otherwise; `routers/labels.py::label_detail`'s scope
  is back to plain tasks/events/contacts. Why now, not deferred:
  1.6's odd/even-week recurrence (`recurrence_picker.js`) is already
  available on ordinary Calendar/Task events, which was Schedule's one
  distinguishing feature — the dedicated module had nothing left to
  offer. `schedule_holidays` (named holiday calendars) and everything
  under "scheduled work"/work allocations (`db.task_work_hours`, the Week
  Calendar's Unscheduled-work panel, `routers/week.py`,
  `routers/projects.py`'s calendar, the Timetable sub-view) are unrelated
  and untouched — see `CLAUDE.md`'s own "what NOT to touch" note for this
  session. `features/schedule.md` deleted; see `plans/abandoned.md` for
  the full removal record. Full suite 1226 passed (net count: several
  Schedule-only test files/classes deleted, a couple of nav/export tests
  extended to assert Schedule's absence).
- **Shipped:** `1.9` slice — **Tasks table pagination**, complete
  (2026-08-15) — `GET /tasks?page=&limit=` (`routers/tasks.py::list_tasks`)
  paginates the Open section, default 50/page, `limit` clamped to 1-200,
  applied after every existing filter/sort. Ungrouped view only
  (`group_by=none`, the default): `group_by=project` clusters tasks under
  per-project header rows where a flat page boundary would split a
  project's own tasks arbitrarily, so grouped mode still shows everything,
  unpaginated — a deliberate, documented scope cut, not an oversight.
  Completed tasks are never paginated (already visually separated below
  Open, bounded in practice by the auto-archive setting). New
  `_tasks_pager.html` partial (Prev/Next `.icon-btn`s, preserves every
  active filter/sort/search param), `.pager`/`.pager-summary` styles in
  `style.css`. `db.task_work_hours_bulk`'s call site was also narrowed to
  only the tasks actually rendered post-pagination (open page + all
  completed) instead of the whole filtered set, a small efficiency
  side-benefit of the same change. This was Webapp usability's Phase B
  (the DAVx5 Phase C piece is unrelated and still blocked on infra); see
  `features/tasks.md` § Views. 13 new tests (`test_tasks_pagination.py`),
  full suite 1239 passed.
- **Shipped:** side work — **Command palette actions**, complete
  (2026-08-15), Track B's top-priority item (`open.md` § Command palette
  actions, now removed from that file per its own "ships -> describe outcome,
  remove the section" convention). Turns the Ctrl-K/Cmd-K overlay (1.2 side
  work: `db.search_entities`, `GET /api/search`, `static/command_palette.js`)
  from search-and-navigate-only into a real command surface, additive
  throughout — the query layer and the Relations-picker wiring are
  unchanged. Global-mode result rows (not relation-mode rows, which exist to
  be picked as a link target, not acted on) now carry action buttons:
  **Mark done** (tasks, posts to the existing `POST /tasks/{uid}/complete`),
  **Delete** (any type, confirmed via `window.ccConfirmSheet` before posting
  to the existing per-type `/{uid}/delete` route — no new delete endpoints
  needed, every one already existed), and **Add label**, which retargets the
  overlay into a new third mode (label mode, alongside the existing global/
  relation modes) backed by two new endpoints: `GET /api/labels` (type-to-
  filter over `db.list_tag_names_in_use`) and `POST
  /api/entities/{task,event,contact}/{uid}/labels`. A task's add goes
  through `db.upsert_task`'s full tags list rather than
  `db.add_object_label` directly, so 1.5's single-project-per-task guard
  (`db.MultipleProjectLabelsError`) still applies — confirmed by test, the
  palette is a fourth write path onto `tasks.tags`, not a bypass; events/
  contacts have no such constraint and use `db.add_object_label` directly.
  Global mode also gained **Create task/event: "\<query>"** rows (mirroring
  relation mode's pre-existing "Create new" row), opening the ordinary new-
  task/event form prefilled via a new `title` query param on
  `new_task_form`/`new_event_form` (`prefill_title` in the template context,
  a fallback added to `_task_form_fields.html`/`_event_form_fields.html`'s
  title `value=`, blank for every other existing caller of either route).
  `_picker_result` (routers/search.py) gained one new field, `status` (a
  task's status, `None` for the other two types) so the palette can hide
  "Mark done" on an already-done task — every other consumer of that shape
  (search.html, the Relations picker) ignores the extra key. See
  `features/tasks.md` § Search & the command surface. 28 new/updated tests
  (`test_command_palette_actions.py`, plus one pre-existing
  `test_search_api.py` assertion updated for the new `status` field), full
  suite 1253 passed.
- **Shipped:** side work — **Page navigation + Quick Capture in the command
  palette**, complete (2026-08-15), direct follow-up feedback right after
  Command palette actions above ("I would like it to also allow to navigate
  to pages. And to quick capture according to the design document" —
  `plans/quick-capture.md`, a previously-unreferenced standalone spec, now
  marked implemented at its own top).
  - **Page navigation** — global-mode results now also include the app's
    own pages (Dashboard/Calendar/Tasks/Contacts/Notes/Settings, every
    Space), computed server-side (`routers/search.py`'s new
    `_matching_pages`) and tagged `type: "page"` — a synthetic row (no
    `uid` that means anything beyond doubling as its URL), no action
    buttons, picked via a plain navigation rather than `CCModal.open`.
    Excluded from relation-picker mode and from any already-type-filtered
    request.
  - **Quick Capture** — a single-field capture syntax (`!t`/`!e`/`!c`/`!n`
    markers, `#label`s, dates, time ranges, phone/email) layered onto
    global mode's own input. New `src/quick_capture.py`: a pure,
    `conn`-free parser (`parse()` dispatches to `parse_task`/
    `parse_event`/`parse_contact`/`parse_note`), verified against every
    example in the design doc verbatim plus edge cases the doc doesn't
    spell out (multiple bare dates, short-date year inference, malformed
    tokens) — 27 tests, `test_quick_capture_parser.py`. New
    `routers/quick_capture.py`: `GET /api/quick-capture/preview` (parse
    only, feeds the palette's live preview row — deliberately does NOT
    resolve/persist labels, since that would write a new alias on every
    debounced keystroke of a still-uncommitted label) and
    `POST /api/quick-capture` (parse + resolve labels + create). A
    captured task's timeblocks become real `db.create_work_allocation`
    calls, same helper 1.4's Work sessions card already uses.
  - **Notes** — the fourth entity type `!n` needed (none existed before).
    Deliberately minimal per the design doc's own scope: `notes` table
    (`uid`/`content`/`created_at`/`updated_at`) + `object_labels` tags,
    same CRUD shape as contacts (`db.upsert_note`/`get_note`/`delete_note`/
    `list_notes`), a bare `routers/notes.py` (list/new/edit/delete) and two
    minimal templates. Not a tabbar destination (a deliberate, separate UI
    decision left unmade) — reached via the palette or a direct `/notes`
    visit. `db.search_entities` gained a fourth `_search_notes` branch so a
    captured note is actually findable afterward, not a write-only row.
    See `features/notes.md`.
  - **Label fuzzy matching** (`plans/quick-capture.md` § Labels and
    Approximate Matching) — new `db.resolve_capture_label`: exact match →
    a previously-learned alias (new `label_aliases` table) → a
    `difflib.get_close_matches` fuzzy match at a deliberately high cutoff
    (0.8 — covers the spec's own three typo examples,
    "uunniversity"/"universitty"/"unisity" → "university", without
    matching unrelated words) → else treated as a genuinely new label. An
    accepted fuzzy match is persisted as a new alias immediately — this v1
    has no separate interactive "suggested for correction" review step
    (a single fire-and-forget capture, not a multi-turn form), so an
    automatic high-confidence resolution doubles as the spec's own "user
    correction," noted explicitly in the function's docstring and in
    `quick-capture.md`'s own new status line.
  See `features/tasks.md` § Search & the command surface (page nav +
  capture outcome) and `features/notes.md` (the new entity). 64 new tests
  total (`test_quick_capture_parser.py`, `test_quick_capture.py`, plus
  `TestPageNavigation` in `test_search_api.py` and one added case in
  `test_command_palette_actions.py`), full suite 1317 passed.
- **Shipped:** side work — **Widget consolidation (original design)**,
  complete (2026-08-15), `plans/open.md` § Widget consolidation — the
  next scoped priority per the reprioritization below, confirmed with the
  user before starting since that section was explicitly marked "waiting
  on your go-ahead" (the three newer expanded-scope asks stay unbuilt,
  still needing a design pass, per the user's own choice). 11 widget
  types → 8 (11 counting the untouched 1.9-side-work additions):
  `today_agenda`/`weekly_overview`/`upcoming_events`/`overdue_tasks` → one
  configurable `agenda` type (`config["range"]`: today/next_7_days/
  next_30_days/all_upcoming, `config["show"]`: a subset of overdue/tasks/
  events); `project_preview`/`filled_cards` → one `spaces_projects` type
  (`config["style"]`: list/cards); `calendar_agenda` cut outright (no
  replacement type — reproduce it by placing Mini Calendar next to
  Agenda); new `streak` (current/longest run of consecutive days with
  >=1 task completed, reading `tasks.completed_at`) and `next_deadline`
  (soonest open task due date + soonest upcoming event) types. New
  `_migrate_widget_consolidation` (`app_meta`-guarded, runs from
  `widget_page_context` so it covers Home + every label page) rewrites
  every existing `dashboard_widgets` row's type/config in place —
  confirmed no dashboard loses a widget, though every migrated (and
  newly default-seeded) Agenda widget now renders at Agenda's one static
  `default_width` ("half") regardless of which of the four old types'
  own width it used to carry, an unavoidable trade-off once 4 types
  collapse into 1 with no per-instance width override (removed
  2026-08-07). The Source/View/Range picker's `_SELECTION_TO_TYPE`/
  `_TYPE_TO_SELECTION` value shape changed from `(type, range_days:
  int|None)` to `(type, extra_config: dict)` to carry Agenda's string
  `range` (and, via `_config_from_form`'s new `style`/`show` params, the
  Style radio/Show checkboxes threaded through `add_widget`/
  `edit_widget`/`preview_widget`) — a real internal-shape change, not
  just new registry entries, documented in `_resolve_selection`'s/
  `_selection_from_widget`'s own updated docstrings. `calendar_agenda`'s
  old (view, range) dead-mapping precedent ("cards"/"filled_cards_view",
  2026-08-07) was deliberately NOT repeated here — every real row is
  rewritten by the migration, so no live widget can still carry a type
  the registry no longer resolves. See `features/dashboard.md` (rewritten
  widget-types table + new Migration section), `plans/open.md`'s section
  trimmed to just the still-open expanded-scope bullets,
  `plans/roadmap.md`'s 1.3 side-work row marked shipped. Test-file rewrite
  delegated to a subagent given the scope (type renames + config-shape
  fixes across `test_dashboard_router.py`/`test_dashboard_usability_
  rework.py`/`test_dashboard_today_week_widgets.py`, one whole obsolete
  test class deleted — `TestCalendarAgendaWidget`, no surviving intent
  once that type was cut with no replacement); full suite 1313 passed (net
  -6 from the deleted class, confirmed against the pre-slice 1319-total
  baseline, not a coverage regression).
- **Reprioritized (direct steer, 2026-08-15):** the next sessions should
  work Track B (`open.md`) in this order, not pick arbitrarily: (1)
  **Command palette actions** (`open.md` § Command palette actions —
  turning the search overlay into a real command surface, decision already
  recorded), (2) **Dashboard widgets, expanded scope** (`open.md` § Widget
  consolidation... — original consolidation design plus three new,
  not-yet-fully-scoped asks: a per-Space Project/Space links widget, a new
  "what needs organizing today" action widget, and widgets being more
  customizable in general — needs a design pass before slice 2 starts),
  (3) two small items, either order: **Tasks page filter cleanup**
  (`open.md`, new section — Important/Urgent move into their own dropdowns,
  Overdue needs a new home, not decided) and **Event format for simple
  events** (`open.md`, new section — a Format: In person/Online field on
  events replacing the always-both-shown Location/Meeting URL fields), (4)
  **Contacts field parity**, (5) **Project check-in**, (6) **Modal window
  uniformization** (`open.md`, new section — deliberately last since it
  cuts across every modal the items above still touch). DAVx5 mobile
  hosting (Phase C of Webapp usability) stays blocked on an external
  domain + server the user doesn't have yet — don't start it until that
  changes. Configurable views + optional Schedule module and collapsible
  sections (Phase B's other half) weren't part of this reprioritization;
  they're still fair game for a session that wants a change of pace, just
  not the default next pick anymore.
- **Shipped:** side work — **Widget consolidation, expanded scope**,
  complete (2026-08-15), the three items `plans/open.md` § Widget
  consolidation left open after the original design shipped earlier the
  same day, design-discussed with the user (AskUserQuestion) before
  writing any code:
  - **Spaces & Projects Scope toggle** — `config["scope"]` (`"space"`
    default, or `"everything"`) on the consolidated `spaces_projects`
    type, a per-widget-instance override rather than a second widget
    type (per the user's own framing of this ask). A Space/Project page's
    instance auto-scopes to that page via `config["label_name"]` as
    before; `scope: "everything"` makes one instance ignore that and
    render the app-wide list instead. `db.list_child_labels` already
    doesn't distinguish project vs. Space children, so "This Space"
    already included sub-Spaces with no code change needed there,
    confirmed by a new test rather than assumed. New "Scope" field in the
    builder/edit forms, shown only when the widget already belongs to a
    Space/Project page (Home has nothing to opt out of).
  - **New `organize_today` widget** ("What Needs Organizing") — due-soon
    (3 days) open tasks with no work session yet, open Urgency=3 tasks
    with none regardless of date, and today's/tomorrow's events with no
    location or meeting link (a proxy for the not-yet-shipped Event
    format field, `plans/open.md`'s own still-separate section — needs no
    changes once that ships, since it'll keep reading the same
    `location`/`meeting_url` columns). "No session yet" reuses
    `routers/calendar.py::week_view`'s own unscheduled-task rule verbatim
    (`db.work_allocation_panel_info`: no allocations at all, or at least
    one still undated). Task rows reuse the shared
    `_unscheduled_task_item.html` partial (project pill + title + the
    "+"/"−" session stepper) directly, per the user's "inline quick
    actions" choice, rather than plain links -- verified the exact
    `{"task", "project", "sessions"}` item shape that partial expects by
    reading `week_view`'s own construction of it, not guessing.
  - **Limit field exposed for more Views** — investigated the user's
    "widgets should be more customizable" ask concretely instead of
    assuming a gap existed: per-widget Labels/Space filtering turned out
    to already be universal across every task/event-backed widget type
    (the Labels chip multiselect has never been gated by type). The real,
    narrow gap found instead: `contact_list`/`important_urgent`'s own
    render functions already read `config["limit"]`, but the builder's
    Limit field was hardcoded to only ever show for one View. Generalized
    to a `has_limit` flag on `WIDGET_VIEWS` (`agenda_view`,
    `contact_list_view`, `important_urgent_view`), read by both the JS
    gating (`dashboard_widget_preview.js`) and the per-widget edit form's
    server-rendered gate.
  See `features/dashboard.md` (widget-types table + Scope/Migration
  sections), `plans/open.md`'s Widget consolidation section fully removed
  (both the original design and the expanded-scope follow-ups are now
  shipped). 19 new tests across `TestSpacesProjectsScope`/
  `TestOrganizeTodayWidget`/`TestLimitFieldExposedForMoreViews`
  (`test_dashboard_router.py`), full suite 1332 passed.
- **Shipped:** two direct-feedback widget-picker polish items + a new
  **Weekly Schedule** widget, complete (2026-08-15). Design-discussed via
  AskUserQuestion before building (whether to merge Quick Links/Spaces &
  Projects too -- declined, "leave both, just add new widget types").
  - **Data source picker: two rows, not one** — `.widget-source-select`
    switched from the shared `.tile-select`'s flex/nowrap to a 3-column
    grid, so 4-5 sources wrap to a readable 2-row layout instead of
    fighting for a shrinking equal share of one enforced row (the
    2026-08-07 one-row decision was made for 4 sources, before Spaces &
    Projects' source made it 5).
  - **Tile icons keep their color when selected** — dropped `.tile-option:
    has(.tile-radio:checked) .tile-icon`'s recolor-to-accent-neutral rule;
    a selected tile is already clear from its border/background/label-text
    change.
  - **View/Range picker: non-applicable options actually hide, not just
    disable** — root cause was the exact same `.field{display:flex}`-
    beats-`[hidden]{display:none}` specificity footgun already hit twice
    this app (`.field.holiday-field`/`.field.label-project-fields`):
    `filterMsOptions` (`dashboard_widget_preview.js`) already set the
    `hidden` attribute correctly, but `.multiselect-option{display:flex}`
    silently won, so a non-applicable View just sat there visibly disabled
    instead of disappearing. New `.multiselect-option[hidden]{display:
    none}` fixes both View and Range (same shared component).
  - **New `weekly_schedule` widget type** ("Weekly Schedule") — see
    `features/dashboard.md`'s own table entry and
    `_render_weekly_schedule`'s docstring for the full design (static
    weekday+time-of-day grid straight off each qualifying event's own
    `start_at`/`end_at`, not a real week's expanded occurrences; new
    `_is_long_lived_recurrence` filters to recurring events whose own rule
    spans >= 30 days first-to-last occurrence, via one `recurrence_expand.
    expand_events` call per candidate over its own 2-year window). New
    `src/recurrence_expand` import in `routers/dashboard.py` (previously
    unused there). Deliberately does NOT revive the removed Schedule
    module (`plans/abandoned.md`, dropped 2026-08-15 same day) — no course/
    semester data model, purely a presentation over ordinary recurring
    Calendar events that already exist.
  See `features/dashboard.md`. 12 new tests (`TestIsLongLivedRecurrence`/
  `TestWeeklyScheduleWidget` in `test_dashboard_router.py`), full suite
  1344 passed.
- **Shipped:** side work — **Tasks page filter cleanup**, complete
  (2026-08-15), `plans/open.md` § Tasks page filter cleanup (build-order
  item 3 of the 2026-08-15 reprioritization). The Table/Board/Timeline
  toolbar's Date dropdown (`routers/tasks.py`'s `DATE_FILTERS`) used to
  carry `overdue`/`important`/`urgent` alongside the real date buckets —
  direct feedback said that reads as clutter/wrong-drawer. Two of three
  moves were already decided (Important -> Importance dropdown, Urgent ->
  Urgency dropdown, each an "(any level)" option alongside the explicit
  Low/Medium/High values); **Overdue's new home was left to this session's
  call** — went with folding it into the Status dropdown as a virtual
  pseudo-status (`STATUS_FILTERS`'s new trailing `"overdue"` entry) over
  the toolbar-chip alternative, since it isn't a value on any real axis and
  a chip would've been a second, redundant filtering mechanism sitting next
  to dropdowns that already cover every other axis. `DATE_FILTERS` is back
  to just the five real date buckets. `_apply_status_filter` gained a
  `label_rules` parameter (mirroring the shape `_apply_importance_filter`/
  `_apply_urgency_filter` already had) since the virtual `overdue` branch
  needs it; every call site (Table, Board, Timeline) updated. The
  Dashboard's At-a-glance widget's outbound links updated to match
  (`status_filter=overdue`, `importance_filter=important`,
  `urgency_filter=urgent` instead of `date_filter=...`) — caught by its own
  existing link-assertion tests. Direct function calls with the old
  `date_filter=overdue/important/urgent` values still happened to work
  unchanged (`_apply_date_filter` never validated against `DATE_FILTERS`,
  it just intersects whatever string it's given against
  `derived_state.virtual_states`), so most of the pre-existing filter tests
  needed no changes at all — only the three link-assertion tests that
  literally spelled out `date_filter=overdue`. See `features/tasks.md` §
  Tasks page filter cleanup. 8 new tests (`TestFilterOptionListsAfter
  FilterCleanup`, `test_overdue_is_a_virtual_pseudo_status`,
  `test_important_any_level_option`/`test_urgent_any_level_option`, etc. in
  `test_tasks_view_rework.py`), full suite 1352 passed.
- **Shipped:** side work — **Event format for simple events**, complete
  (2026-08-15), `plans/open.md` § Event format for simple events (build-order
  item 4 of the 2026-08-15 reprioritization). `_event_form_fields.html`
  gained a Format field (`.event-format-segmented`, the same `.seg-btn`/
  `.seg-radio`/`:has()` radio pattern `label_edit_modal.html`'s Role picker
  already established) with two options, **In person** / **Online**, that
  reveals only the relevant field (In person → Location, Online → Meeting
  URL) instead of always showing both — resolving the one open sub-decision
  left in the spec: "neither picked" (both fields hidden) is a real, default
  third state, not just a fallback — a brand-new event starts with neither
  radio checked. No backing column — Format is derived from which of
  `events.location`/`events.meeting_url` already has a value (an existing
  event with only Location set opens with In person pre-checked, etc.;
  Location wins the tie for legacy rows that somehow have both set, since
  there's no real "both" state in the new model); `create_event`/
  `update_event` are completely unchanged. Show/hide is plain CSS
  (`#event-form:has(#event_format_in_person:checked) .field-format-location`,
  `style.css`, same `:has()` progressive-disclosure pattern as `#all_day`/
  `.holiday-field` above); new `static/event_format_toggle.js` (loaded
  globally in `base.html`, re-initialized on modal-injected content via
  `modal.js`'s `wireContent()`, same convention as `task_habit_field_
  toggle.js`) clears the *other* field's value on switch, so a hidden stale
  value (e.g. a Meeting URL typed in before switching to In person) can't
  silently resubmit and repopulate both columns behind the derivation's
  back. `sw.js`'s precache list gained the new script (`cc-shell-v7`). No
  changes needed to `event_detail.html` (already conditionally shows
  Location/Meeting only when set) or the `organize_today` dashboard widget
  (already reads the same two columns, per its own 2026-08-15 slice note).
  See `features/calendar.md` § Event CRUD & fields, `plans/open.md`'s Event
  format section removed. 13 new tests (`test_event_format_field.py`), plus
  `test_pwa_shell.py`'s cache-name pin updated to v7, full suite 1365
  passed.
- **Shipped:** `Contacts field parity` slice 1 of 6 — **Title**, complete
  (2026-08-15), build-order item 5 of the 2026-08-15 reprioritization.
  Green-lit this session via AskUserQuestion (all five of `open.md`'s open
  questions answered: vCard/Nextcloud type vocabulary, auto-migrate-as-
  "Other" for existing single-value data, full vCard ADR structure for
  Address, both full and year-less Birthday dates, `X-SOCIALPROFILE` for
  Social network — recorded in `open.md`'s Contacts field parity section for
  the 5 slices still to come). This slice: new `contacts.title` column
  (`db.py`, `_ensure_column` migration for pre-existing databases), vCard
  TITLE round-trip (`vcard_rows.py`), `title` Form field on
  `create_contact`/`update_contact` (`routers/contacts.py`, same `"none"`/
  `"nothing"` sentinel-clearing convention as `org`/`phone`/etc.), a Title
  input on `contact_form.html`, and "Title at Org" (falling back to
  whichever is present) on both `contact_detail.html`'s header and
  `contacts_list.html`'s row subtitle. Contact search (`db.list_contacts`/
  `db._search_contacts`) now matches `title` too. See `features/contacts.md`.
  17 new tests (`test_contacts_field_parity_title.py`), plus 5 existing
  contact-route call sites across `test_phase5_contacts.py`/
  `test_phase1_universal_pool.py`/`test_modal_input_phaseB_chip_
  multiselect.py` updated to pass the new `title` param (calling the router
  function directly with a param omitted binds FastAPI's raw `Form(...)`
  sentinel object, not `""` — caught by the full suite, not this slice's own
  new tests), full suite 1382 passed. **Next in this build order:** Phone/
  Email (multi-value), then Website, Birthday, Address, Social network — see
  `open.md`'s Contacts field parity section.
- **Shipped:** `Contacts field parity` slice 2 of 6 — **Phone/Email**,
  complete (2026-08-15), build-order item 5 of the 2026-08-15
  reprioritization, following slice 1's Title. New `contact_phones`/
  `contact_emails` tables (`db.py`) give a contact any number of phone
  numbers/email addresses, each typed from the vCard/Nextcloud vocabulary
  green-lit in slice 1's own session (Home/Work/Cell/Fax/Pager/Other for
  phone, Home/Work/Other for email) — owned child rows keyed by
  `contact_uid`, no FOREIGN KEY constraint (confirmed via grep that
  nothing in `SCHEMA_SQL` uses them), `position` a float sort key, same
  shape as `task_checklist_items`. The old flat `contacts.phone`/
  `contacts.email` columns are never dropped (this file's standing
  convention) but are now dead by design, not kept live: reconciling two
  sources of truth (a flat column plus a real multi-value list) on every
  write would need an arbitrary "which one is primary" rule for no benefit
  once nothing reads the column anymore, so it's simplest to freeze it as a
  one-time migration source. `db.migrate_legacy_contact_phone_email` copies
  a still-legacy value into the new table as a single "Other"-typed row,
  gated on "zero existing child rows for this contact" so it's idempotent
  and never overwrites real typed data a user already entered — runs
  automatically in `init_schema`, same place every other migration in this
  file lives. vCard round-trips as multiple TEL/EMAIL lines with a `TYPE=`
  param (`vobject`'s `card.add("tel")`/`.type_param`, read back via
  `tel_list`/`email_list` — the plural API, confirmed via a live vobject
  round-trip that `card.tel`/`card.email` only ever surface the first
  line); "Other" deliberately gets no `TYPE=` param at all since vCard has
  no standard token for it, in either direction. Router: `create_contact`/
  `update_contact` swapped their flat `phone`/`email` Form fields for
  parallel `phone_type[]`/`phone_value[]` (`email_type[]`/`email_value[]`)
  arrays (`list[str] = Form([])`, the same shape `tags_labels` already
  uses) — chosen over `_task_work_allocations.html`'s own-POST-endpoints-
  per-row pattern because a phone/email list is small and edited as a
  whole on the form's one existing Save button, not a separate persistent
  sub-resource like a work session. Rows are added/removed purely client-
  side (new `static/contact_phone_email_rows.js`, clones a `<template>`
  row, same `wireContent()` re-init idiom as `label_role_picker.js`) since
  nothing is written until Save either way; the type picker is a plain
  `<select>` (matching `habit_form.html`'s Project picker/`label_edit_
  modal.html`'s Parent picker for "one of a short fixed list", not the
  segmented `.seg-btn` control reserved for 2-3-way toggles). Detail page
  lists every phone/email with its type label and a tel:/mailto: link
  (repeated per row); the contacts-list row subtitle and the dashboard
  Contact List widget both stay concise, showing only the first
  (lowest-position) entry of each — no new "primary" flag, "first" is
  simply creation/submission order. `db.list_contacts`'s `q` search and the
  global `db._search_contacts` now also match the new child tables (the
  dead legacy columns are still searched too — harmless redundancy, and
  correct since the migration always runs before any query executes).
  Also updated: `routers/export.py`'s contacts.csv (reads the first phone/
  email instead of the dead columns) and `routers/quick_capture.py`'s `!c`
  contact capture (stores its single parsed phone/email as one "Other"-
  typed entry instead of writing the dead columns). See
  `features/contacts.md`. 40 new tests
  (`test_contacts_field_parity_phone_email.py`), plus 7 existing contact-
  route call sites across `test_phase5_contacts.py`/
  `test_phase1_universal_pool.py`/`test_modal_input_phaseB_chip_
  multiselect.py`/`test_contacts_field_parity_title.py` updated for the new
  `phone_type`/`phone_value`/`email_type`/`email_value` params, plus
  `test_quick_capture.py`/`test_row_translators.py` updated off the now-
  dead flat `phone`/`email` row keys (caught by the full suite, not this
  slice's own new tests), full suite 1422 passed. **Next in this build
  order:** Website (multi-value), then Birthday, Address, Social network —
  see `open.md`'s Contacts field parity section.

- **Designed:** side work — **Modal window uniformization, audit + rules**
  (docs only, no code), complete (2026-08-15), direct user request to jump
  ahead of Project check-in in the 2026-08-15 reprioritized queue and start
  this now. Read every modal template in the app
  (`grep -l "modal-header\|modal-body" src/templates/*.html`, 15 real modal
  fragments) against `_modal_footer.html`'s existing convention, per this
  file's own standing "audit before assuming a from-scratch build" habit.
  Found: three different footer implementations in use (the shared
  `_modal_footer.html` partial — core three entities only; hand-rolled
  `.modal-footer` markup with small pointless differences — habit_form/
  habit_task_form/label_edit_modal/label_merge_modal/note_form/quick_add/
  _modal_widget_customize; no footer at all, Save embedded in the body form
  — `_widget_edit_modal`/`banner_editor`); a real safety bug
  (`note_form.html`'s Delete has neither confirm-sheet nor undo — the only
  unconfirmed delete action in the app); an inconsistent icon-prefixed `<h1>`
  on 2 of 12 utility-modal titles; and one real sizing bug
  (`_modal_widget_customize`'s two-pane widget-builder grid never gets
  `data-modal-size="wide"` on its trigger links, unlike the visually
  identical `_widget_edit_modal`, so it squeezes into the default width).
  Wrote the "real uniform modal windows" rules (footer always through
  `_modal_footer.html`, delete confirmation never optional, plain-`<h1>`
  titles reserved for utility modals vs. the rich identity header for
  entity detail views, two allowed body shapes plus a documented custom
  exception, two named dialog sizes) and an 8-slice (A-H) implementation
  breakdown, ordered safety-fix-first. See `plans/open.md`'s Modal window
  uniformization section for the full audit + rules + slice list.
  **Deliberately no code changed this session** — slices A-C are small and
  independent, but slices D-H should still wait for Contacts field parity
  (4 of 6 sub-slices open) and Project check-in to finish touching the
  entity/widget modals first, per the section's own updated note.

- **Shipped:** side work — **Modal window uniformization, slices A-C**,
  complete (2026-08-15), direct follow-up to the same-day audit + rules
  pass above ("start work uniforming their look"). Three small,
  independent slices from `plans/open.md`'s 8-slice (A-H) breakdown:
  - **A+B — hand-rolled footers migrated onto `_modal_footer.html`**:
    `habit_form`, `habit_task_form`, `label_edit_modal`,
    `label_merge_modal`, `note_form`, `quick_add` all render their footer
    through the shared partial now, matching the core three entities
    (task/event/contact). Folded slice A's safety fix into the same
    change: `note_form.html`'s Delete had neither `data-confirm-sheet` nor
    `data-delete-undo` before this — the only unconfirmed destructive
    action anywhere in the app — and now goes through the partial's
    `confirm` mode like every other migrated modal's Delete.
    `_modal_footer.html` gained one small, backward-compatible extension:
    an optional `footer_primary_id` (`quick_add.html`'s tab switch
    retargets the Save button's `form` attribute via
    `getElementById("quick-add-save")`, `static/quick_add.js` — the
    partial didn't expose a stable id for that before).
  - **C — "New widget" triggers sized to match their content**:
    `dashboard.html`/`label_detail.html`'s "New widget" links now carry
    `data-modal-size="wide"`, matching `_widget_edit_modal.html`'s own
    trigger — both open the identical `.widget-builder` two-pane grid, but
    only one used to get the wide dialog.
  Slices D-H (the remaining footer-less/icon-prefixed utility modals —
  `_modal_widget_customize`, `_widget_edit_modal`, `banner_editor`) are
  deliberately deferred per `open.md`'s own note: they touch modals
  Contacts field parity (4 of 6 sub-slices open) and Project check-in
  haven't finished adding fields to yet. See `plans/open.md`'s Modal
  window uniformization section. 9 new tests
  (`test_modal_uniformization.py`), full suite 1431 passed.

- **Shipped:** **Contacts field parity slice 3 of 6 — Website**, complete
  (2026-08-15) — multi-value, Home/Work/Other type vocabulary (same as
  email/address, green-lit alongside the other Contacts field parity
  decisions), new `contact_websites` table (`db.py`, same owned-child-row
  shape as `contact_phones`/`contact_emails` — `contact_uid`, `type`,
  `position`, no FOREIGN KEY — but the value column is named `url`, not
  `value`, matching vCard's own URL property name). Unlike Phone/Email,
  there was never a pre-existing single-value website column anywhere in
  this app (confirmed by grepping `db.py`/`vcard_rows.py`/
  `contact_form.html`/`contact_detail.html` before writing any code), so
  no auto-migration was needed for this slice. vCard round-trips as
  multiple `URL` lines with the same `TYPE=` convention Phone/Email use
  ("Other" omits the param) — vCard's URL property isn't one of RFC
  2426/6350's typed multi-instance properties the way TEL/EMAIL are, but
  vobject supports repeated `card.add("url")` calls and a `card.url_list`
  read-back identically, confirmed directly against vobject with a live
  Python snippet before writing `vcard_rows.py`, not assumed. The
  create/edit form submits every website row together as parallel
  `website_type[]`/`website_url[]` form arrays, reusing
  `static/contact_phone_email_rows.js`'s existing add/remove-row wiring
  verbatim — it was already written generically enough
  (`data-repeatable-rows-scope`/`-add`/`-template`) for a third field
  group, no JS changes needed. The detail page lists every website with
  its type and an external link (`target="_blank" rel="noopener"`,
  matching event `meeting_url`'s own convention in `event_detail.html`).
  Left off the contacts-list row subtitle and dashboard Contact List
  widget — org/title/phone/email stay the more useful compact-row fields,
  per the slice's own scoping note. Search (`db.list_contacts`/
  `db._search_contacts`) matches website URLs too. See
  `features/contacts.md`. 26 new tests
  (`test_contacts_field_parity_website.py`); updated 7 existing
  contact-route call sites (`test_contacts_field_parity_phone_email.py`,
  `test_contacts_field_parity_title.py`, `test_phase5_contacts.py`,
  `test_phase1_universal_pool.py`,
  `test_modal_input_phaseB_chip_multiselect.py`) that call
  `contacts_router.create_contact`/`update_contact` directly, off the new
  required `website_type`/`website_url` form-array params — same "wire up
  the new arrays at every existing call site" step Phone/Email's own
  slice needed. Full suite 1457 passed. **Next in this build order:
  Birthday** (full or year-less date, 4 of 6).
- **Shipped:** **Contacts field parity slice 4 of 6 — Birthday**, complete
  (2026-08-16) — single-value (unlike Phone/Email/Website above — a
  contact has at most one birthday), so a plain `contacts.birthday`
  column (`_ensure_column`), not a child table. Stores vCard's own BDAY
  text verbatim: a full `YYYY-MM-DD` date, or a year-less `--MM-DD` date
  (green-lit alongside the other Contacts field parity decisions,
  2026-08-15). New `db.parse_contact_birthday` validates a create/edit
  form's raw text against both shapes using real calendar-date rules
  (`datetime.strptime`, not just a regex — rejects e.g. `1990-02-30`; a
  year-less date is checked against a dummy leap year, 2000, so `--02-29`
  validates) — `routers/contacts.py`'s one call site before
  `db.upsert_contact` ever runs, raising a 400 on anything else so a
  rejected save never partially writes (same convention
  single-project-per-task's `MultipleProjectLabelsError` handling uses).
  New `db.format_contact_birthday` is the display side ("May 17, 1990" /
  "May 17"), falling back to the raw stored value unchanged for a shape
  this app didn't write itself. vCard round-trips through one BDAY line —
  confirmed directly against vobject before writing `vcard_rows.py` that a
  plain string `.value` (not a `date` object) round-trips both shapes
  byte-for-byte on both write and read, so no date-parsing is needed
  anywhere in this app. The create/edit form uses a plain text input
  (`contact_form.html`, new `.field-hint` CSS shared with any future
  plain-form hint text), not a native `<input type="date">`, since a
  year-less birthday has no HTML date-input equivalent — `pattern` is a
  client-side hint only, the router's `_parse_birthday_field` is the real
  validation. The detail page renders it through a new `fmt_birthday`
  Jinja filter (`deps.py`). Deliberately not searched
  (`db._search_contacts`/`list_contacts`) — same precedent as Address, the
  other single-value field, which isn't searched either. See
  `features/contacts.md`. 35 new tests
  (`test_contacts_field_parity_birthday.py`); updated 20 existing
  contact-route call sites across 6 test files
  (`test_contacts_field_parity_phone_email.py`,
  `test_contacts_field_parity_title.py`,
  `test_contacts_field_parity_website.py`,
  `test_modal_input_phaseB_chip_multiselect.py`,
  `test_phase1_universal_pool.py`, `test_phase5_contacts.py`) that call
  `contacts_router.create_contact`/`update_contact` directly, off the new
  required `birthday` form param — same "wire up the new field at every
  existing call site" step Website's own slice needed. Full suite 1492
  passed. **Next in this build order: Address** (structured multi-value,
  full vCard ADR, 5 of 6).
- **Shipped:** side work — **Birthdays as generated Calendar events + a
  real `.checklist-delete` style**, complete (2026-08-16), direct feedback
  on the Birthday slice above. Two independent pieces:
  - A contact with a Birthday now shows up on the Calendar itself as a
    real all-day event, recurring `FREQ=YEARLY`, tagged with the
    "Birthday" label — not a separate widget. New `db.sync_contact_
    birthday_event(conn, contact_uid, full_name, birthday)`, called from
    `upsert_contact` on every save and from `delete_contact`, owns exactly
    one such event per contact at the deterministic uid
    `f"birthday::{contact_uid}"` — found-and-replaced idempotently on
    every save rather than tracked through a new relation table (same
    "derive the id instead of storing a relation" shape
    `event_occurrence_overrides`' `master_uid::occurrence_date` composite
    key already uses). A year-less `--MM-DD` birthday has no real year to
    anchor `DTSTART` on, so it uses a fixed placeholder year (1900) far
    enough in the past that `FREQ=YEARLY` always has a "this year"
    occurrence — RRULE recurrence only ever generates forward from
    DTSTART, which is also exactly correct for a *full* birthday date
    (DTSTART = the real birth year, no occurrence before someone was
    born). Clearing a birthday deletes the generated event; deleting the
    contact does too. Verified end-to-end through the real
    `recurrence_expand.expand_events` pipeline the Calendar page itself
    uses (not just that the row exists) — both a full-date and a
    year-less birthday actually expand to one occurrence in the current
    year's window. See `features/calendar.md`'s new "Generated Birthday
    events" note and `features/contacts.md`'s Birthday entry.
  - `.checklist-delete` (the icon-only remove button used by checklist
    rows, the Relations card's unlink action, and Work sessions/Phone/
    Email/Website row removal) was previously unstyled beyond
    `margin-left:auto` — it rendered as a bare native `<button>` with
    default browser chrome. Now styled with the same quiet-by-default,
    red-on-hover/focus treatment `.detail-delete-link` already uses for
    the footer's demoted Delete action (`color:var(--fg-tertiary)` ->
    `var(--danger)` + `var(--tag-red-bg)` on hover/focus), just sized for
    an inline row instead of a footer link.
  11 new tests extending `test_contacts_field_parity_birthday.py`
  (`TestBirthdayCalendarEvent`, 46 total in that file), full suite 1503
  passed. No CSS-only test coverage for `.checklist-delete` (this app has
  no visual-regression harness) — verified by reading the rendered rule
  against `.detail-delete-link`'s own precedent.

- **Shipped:** `1.9` slice — **Async CRUD: task create/edit/complete/delete
  without a page reload**, complete (2026-08-16) — progressive-enhancement
  async layer over the existing plain-form flows, per `features/async-crud.md`.
  Every mutation endpoint keeps its `303 Redirect` for a non-JS client; with
  the fetch header (`X-Requested-With: fetch`) it returns JSON instead
  (`201 {"ok": true, "uid": …}` on create, `200 {"ok": true}` on the rest) —
  detected via `x_requested_with: str | None = Header(default=None)` (a
  `Request | None` param breaks FastAPI with "Invalid args for response
  field"), shared by `routers/tasks.py`'s `_wants_json`/`_respond`.
  - New `static/async_crud.js` (loaded globally in `base.html` after
    `modal.js`): `window.ccApi.post` (the only `fetch` path every mutating
    form goes through, so 1.8's future outbox interception has one hook —
    `_send`), `window.ccApi.refreshRegion`, a generic `data-cc-complete`
    submit handler (posts, then dispatches the event; it does *not* refresh
    — the owner does), and the `cc-entity-changed` event bus for
    cross-surface sync.
  - Tasks page: new `GET /tasks/regions?region=table` fragment endpoint
    (`routers/tasks.py::tasks_regions`, unknown region -> 400 JSON) renders
    the shared `_tasks_body.html` (extracted from `tasks_list.html`, which
    now just includes it — the partial self-imports `task_row` and defines
    `sort_link` so it renders standalone). It accepts the same query params
    as `list_tasks`; the client forwards the page's own `location.search`
    so filters/sort/page carry over. `tasks_table.js` was refactored to
    document-level delegation (region swaps replace `#task-table`), and
    listens for `cc-entity-changed` to refresh `#tasks-body` (reload
    fallback on failure); inline pill/date edits stay optimistic with no
    region refresh, by design. Bulk status/tag/delete dispatch the event
    instead of reloading; bulk list-select stays a reload.
  - Modals/other JS: `modal.js` sends the fetch header and, on a
    non-keep-open success of a `data-cc-change` form (action from
    `data-cc-action`), dispatches `cc-entity-changed` instead of
    reloading; `task_form.html` uses `data-cc-change="task"` +
    `data-cc-action`, `task_detail.html` opts its footer delete into the
    same via `_modal_footer.html`'s new `footer_delete_cc_change`.
    `app.js`'s delete-with-undo and list-row timer paths do the same when
    the form carries `data-cc-change`; `command_palette.js`'s task
    complete/delete send the header + dispatch (notes/events unchanged).
  - Dashboard: new `GET /dashboard/widgets/{uid}` (`routers/dashboard.py::
    widget_card_region`, 404 on unknown uid) renders the single-card
    `_widget_card.html` (widget markup extracted into the shared
    `widget_inner` macro in new `_widget_inner.html`); cards carry
    `data-widget-uses="tasks"` and the dashboard listener refreshes
    `.widget-card[data-widget-uses*="tasks"]` on `cc-entity-changed` but
    skips while `#dashboard-grid.is-editing` (the fragment renders
    `edit_mode=False` and would drop drag chrome). `_widget_agenda.html`'s
    complete forms got `data-cc-complete`. Stack children have no
    `#widget-<uid>` container so `refreshRegion` no-ops there (documented
    scope cut).
  17 new tests (`test_async_crud.py`): region-fragment parity with the full
  page (rows, filters/pagination, pager, empty state, unknown region 400),
  dual-mode mutations (JSON 201/200 with header, 303 without, recurring
  completion history, two-project 400), widget card region (marker +
  content + 404), detail delete-form opt-in. Full suite 1524 passed.
  *Note:* the working tree also still carries the pre-existing uncommitted
  Modal window uniformization slices D–H (modal-uniformization audit +
  rules were committed as slices A–C in `cc31141`); two small fixes were
  made to that uncommitted work to get the suite green (`_widget_edit_
  modal.html`'s Jinja comment ending `-->` instead of `#}`; a too-strict
  assertion in `test_modal_uniformization.py`).
- **Shipped:** side work — **Modal window uniformization, slices D-H (all
  slices now shipped)**, complete (2026-08-15), continuing straight on
  from slices A-C (`cc31141`) once the concurrent Async CRUD work above
  had committed and the tree was green again (session paused mid-slice
  waiting on that, per its own direct instruction — see this file's git
  log for the gap). Four small slices closing out the 8-slice (A-H)
  breakdown from `plans/open.md`'s former Modal window uniformization
  section (now removed — every slice shipped, folded into
  `features/design-system.md`'s new "Modal windows" section instead, per
  this repo's "ships -> describe the outcome, remove the section"
  convention):
  - **D** — `_modal_widget_customize.html`'s "Add widget" onto
    `_modal_footer.html` in a new primary-only mode (no back link at all,
    the dialog's own X still closes it, preserving the 2026-08-07
    "one button" decision) — `_modal_footer.html` gained a second small
    extension, `footer_back_url` can now be omitted entirely.
  - **E** — `_widget_edit_modal.html` gets a Back/Done-only footer.
    Checked `static/dashboard_widget_preview.js` directly before touching
    anything (per this file's own "verify, don't guess" habit): the body's
    inline "Save filters" button isn't vestigial, it's a real
    progressive-enhancement fallback JS hides once autosave takes over and
    un-hides again on failure, so it stays in the body untouched — the
    partial gained a third small extension, `footer_primary_label` can now
    be omitted for a footer with no primary button at all.
  - **F** — `banner_editor.html` gets a Back/Done-only footer using the
    real `page_url` (this template also renders standalone for a no-JS
    visit, so the back link needs a real navigable target, not `#`).
  - **G** — dropped the inconsistent icon prefix from `banner_editor`'s
    and `_widget_edit_modal`'s `<h1>` to match every other utility modal.
  - **H** — re-grepped all 15 modal fragments: every one now includes
    `_modal_footer.html`, no leftover hand-rolled footer markup anywhere.
    Added a standing regression test (`TestFullAppModalSweep`) that greps
    the same 15 files for the include, so a future modal skipping the
    partial fails CI instead of waiting for another manual audit.
  4 new tests extending `test_modal_uniformization.py` (13 total), full
  suite 1524 passed.
- **Shipped:** side work — **Contacts field parity slice 5 of 6, Address
  (structured multi-value, full vCard ADR)**, complete (2026-08-16) — the
  old `contacts.address` free-text column is now `contact_addresses`, a
  full structured, multi-value vCard ADR (PO Box, Extended, Street, City,
  Region, Postal code, Country), each entry typed Home/Work/Other (same
  vocabulary as email/website). Same owned-child-row shape as
  `contact_phones`/`contact_emails`/`contact_websites`
  (`db.list_contact_addresses`/`set_contact_addresses`), just seven value
  columns instead of one — a row is dropped on save only when every one
  of the seven fields is blank, unlike the sibling tables' single-value
  blank check. The old flat value auto-migrates once, idempotently, into
  a single "Other"-typed entry (the whole legacy string placed in
  `street`, every other field left blank —
  `db.migrate_legacy_contact_address`, same shape as
  `migrate_legacy_contact_phone_email`). vCard round-trips as multiple
  `ADR` lines with `TYPE=` (Other omits it) via vobject's `card.add
  ("adr")`/`adr_list` — ADR is one of RFC 2426/6350's own typed multi-
  instance properties (unlike Website's URL workaround), confirmed
  directly against vobject before writing `vcard_rows.py`. The create/
  edit form renders each address as its own card (new
  `.contact-address-row`/`.contact-address-fields` CSS, a 2-column field
  grid) rather than the single-line rows phone/email/website use — more
  fields per entry than a one-line layout could hold; still reuses
  `static/contact_phone_email_rows.js`'s generic add/remove-row wiring
  verbatim. The detail page renders each entry through a new
  `fmt_address` Jinja filter (`deps.py` -> `db.format_contact_address`),
  vCard's own multi-line layout (PO Box/Extended/Street each own line,
  then "City, Region PostalCode", then Country). Not searched, same
  precedent Birthday established. See `features/contacts.md`. 37 new
  tests (`test_contacts_field_parity_address.py`); ~28 existing call
  sites across 8 test files updated for the removed bare `address` form
  param (superseded by eight `address_*[]` arrays), full suite 1560
  passed.
- **Shipped:** side work — **Contacts field parity slice 6 of 6, Social
  network (`X-SOCIALPROFILE`)**, complete (2026-08-16) — closes out the
  6-slice Contacts field parity effort (`plans/open.md`, Title -> Phone/
  Email -> Website -> Birthday -> Address -> Social network). Multi-
  value, each entry tagged with a network name (`db.CONTACT_SOCIAL_
  TYPES` — Twitter/Facebook/Instagram/LinkedIn/Mastodon/GitHub/Other),
  deliberately not the Home/Work/Other vocabulary every other typed
  contact field uses, since "which network" is the meaningful
  distinction here, not "which location/context." New
  `contact_social_profiles` table, same owned-child-row shape as
  `contact_phones`/`contact_emails`/`contact_websites` (single `value`
  column, `db.list_contact_social_profiles`/`set_contact_social_
  profiles`). No pre-existing single-value column ever existed, so no
  auto-migration was needed (same situation as Website, confirmed by
  grep first). vCard round-trips as multiple `X-SOCIALPROFILE` lines
  with `TYPE=` naming the network (Other omits it) — an X- extension
  property, not core RFC 2426/6350, but vobject treats it identically to
  a typed core property (repeatable `card.add`, plural `_list` read-
  back), confirmed directly against vobject before writing
  `vcard_rows.py`. Create/edit form uses the same one-line multi-row
  shape as Phone/Email/Website (`social_type[]`/`social_value[]`,
  `static/contact_phone_email_rows.js` reused verbatim). The detail page
  renders a URL-shaped value (`http://`/`https://`) as an external link,
  matching website's own convention; a bare handle/username renders as
  plain text, since X-SOCIALPROFILE doesn't guarantee either shape. See
  `features/contacts.md`. 25 new tests
  (`test_contacts_field_parity_social.py`), full suite 1586 passed.
  **Contacts field parity with Nextcloud Contacts is now fully shipped**
  (`plans/open.md`'s section closed out, `plans/roadmap.md`'s 1.1 side-
  work row marked shipped).
  *Note on session discipline:* both slices above were built and
  committed together in this one session, at the user's explicit
  request (normally one slice per session, per this file's own "How to
  run a session" section below) — Address and Social network touch the
  same handful of files (`db.py`, `vcard_rows.py`,
  `routers/contacts.py`, `contact_form.html`/`contact_detail.html`) in
  ways that were simplest to write and verify together as one pass, even
  though their docs/tests/STATE.md entries are still kept fully separate
  above.
- **Versioned:** `1.9` now shipped as `1.9.0` (2026-08-16) — `pyproject.toml`
  bumped, catching another stale-versioning gap: it had stayed at `1.8.0`
  since 1.9's Pagination slice shipped (2026-08-15) and the bump was never
  committed, the same gap 1.8's own bump had already caught for 1.4-1.7.
  No code changes — the 1.9 features (Tasks table pagination) shipped in
  the entries above; this commit only versions them. Full suite still 1586
  passed.
- **Shipped:** `1.9` follow-up slice — **Async CRUD, expanded to the other
  daily surfaces** (2026-08-16), the "wire the change event into the
  Calendar/Board/Timeline/Habits and the remaining modal forms" follow-up
  from the Async CRUD slice above, per `features/async-crud.md` §5/§7.
  Session scope (user-chosen): core daily surfaces + the two stale-region
  gaps; Settings/admin/published-lists/import stay reload-based.
  - **Mechanism generalized**: `static/async_crud.js`'s change dispatch is
    now `ccApi.dispatchChange({type, action, uid})` with a **claim
    protocol** — the event carries `detail.claimed = false` and each
    surface listener sets it `true` only when it actually owns a region on
    the current page; `dispatchChange` returns `claimed` and `modal.js` /
    `app.js` fall back to a reload when nothing claims it (backward
    compatible). `routers/deps.py` gained the shared `wants_json()` /
    `respond()` helpers (`tasks.py` refactored onto them). Design decision
    recorded: **no generic plain-page `data-cc-change` submit handler** in
    `async_crud.js` — it would strand standalone form pages (fetch + reload
    instead of following the 303 redirect); plain-page forms are handled by
    surface-specific listeners with `e.defaultPrevented` /
    `#modal-overlay` guards.
  - **Contacts**: `GET /contacts/regions?region=list` + shared
    `_contacts_list_context` (matches the exact `list_contacts` filter/tag
    params), `_contacts_body.html` partial, `create_contact` (201+uid) /
    `update_contact` / `delete_contact` dual-mode, `data-cc-change="contact"`
    on the form + footer delete, new `contacts_list.js` listener. 63 tests.
  - **Notes**: `GET /notes/regions?region=list` + `_notes_body.html`,
    dual-mode create/update/delete (404 -> JSON when fetch), `data-cc-change
    = "note"` + confirm-mode footer delete opt-in (new
    `footer_delete_cc_change` support in `_modal_footer.html`'s confirm
    branch), new `notes_list.js` listener.
  - **Habits**: `GET /habits/regions` (`region=list` -> `_habits_body.html`,
    `region=detail&uid` -> `_habit_detail_body.html`, unknown -> 400),
    dual-mode create (201+uid)/edit/archive/unarchive/delete +
    `toggle_entry`/`add_entry` (referer redirect default), `data-cc-change
    ="habit"` on the form + delete + archive/unarchive + backfill, new
    `habits.js` listener claiming whichever habit region is present and
    handling the heatmap cell / backfill / archive forms async. 71 tests.
  - **Events**: `create_event` (201+uid) / `update_event` / `delete_event`
    / `cancel|move|restore_occurrence` dual-mode (via `respond`),
    `data-cc-change="event"` on the form + footer delete + the occurrence
    actions (modal.js's per-form handler dispatches them inside the modal).
    **Month view** is the wired event/task surface: `_calendar_month_grid
    .html` partial + `GET /calendar/regions?region=month` (shared
    `_month_view_context`), new `async_calendar.js` listener that refreshes
    `#month-grid` and re-inits the drag bindings (`calendar_month.js` /
    `calendar_month_drag.js` refactored to expose re-invocable `init()`s);
    the month drag-to-move now dispatches the change event instead of
    reloading. Week/Day/Timetable grids carry per-block drag bindings and
    stay on the reload fallback for now (documented follow-up).
  - **Labels**: `GET /labels/regions?region=list` + shared
    `_labels_context`, `_labels_body.html` partial, `data-cc-change="label"`
    on the edit + merge modals, new `labels_manage.js` listener
    (`label_search.js` refactored to an exposed `init()` so the client-side
    search re-binds after a region swap).
  - **Opt-ins (reload fallback keeps them safe)**: `data-cc-change="banner"`
    on the banner upload/remove forms; `data-cc-change="task"` on
    `habit_task_form.html` (create) and on the tasks list-row delete
    (`_task_row.html`) — closing the two stale-region gaps from the first
    slice (list-row delete + command-palette quick capture now dispatch
    `cc-entity-changed`).
  - **Deliberately deferred follow-ups** (documented, not done): the
    Week/Day/Timetable grid region (needs calendar.js + project_calendar.js
    re-init, the merged grid's per-block bindings), the Timeline grid
    region (timeline.js already POSTs JSON but `reload()`s for correctness),
    a Board column region, and async work-allocation create/move/delete.
  - 13 new tests across the surface suites (contacts 63, notes,
    habits 71, calendar 141, full suite **1586 passed**).
- **Shipped:** `1.9` follow-up slice — **Async CRUD: the Week grid region +
  async work-allocation create/move/delete**, complete (2026-08-16) — the
  "week-grid region + work allocations" deferred item from the expansion
  slice above (reported directly against the merged Week view: "in the
  calendar week view, moving task timeblocks refreshes the page"). The
  planning grid's block-level create/move/delete now goes through
  `static/project_calendar.js`'s new `postAction` (a FormData body posted
  via `ccApi.post`, `change.type = "task"`) instead of `submitForm` (a
  hidden form + real submit -> 303 -> full reload); the three
  `/calendar/week/allocations[...]` endpoints are dual-mode (`_week_respond`,
  same `respond` helper as the rest of async-CRUD). The block's ✕-button
  delete form is intercepted the same way, so the whole grid is reload-free.
  `ccApi.post` now accepts a `FormData` instance directly (the drag paths
  build their payload in JS, no `<form>` in the DOM) alongside `<form>`.
  The week region is `GET /calendar/regions?region=week&date_=...` rendering
  a new `_calendar_week_grid.html` partial — the `.project-calendar-layout`
  wrapped as `#week-grid` (with `data-date`/`data-label`), extracted from
  `calendar_week.html` and shared as the single source of truth, driven by
  `_week_view_context` factored out of `week_view`. `async_calendar.js` now
  handles both regions (month `#month-grid`, week `#week-grid`) and re-runs
  the swapped-in grid's bindings: `calendar.js`/`project_calendar.js`/
  `unscheduled_panel_toggle.js` all expose re-invocable `init()`s
  (`window.CCWeekGrid`/`CCProjectCalendar`/`CCUnscheduledPanel`; the scroll
  container and all per-element selectors are re-queried per init, and
  project_calendar.js binds the ✕-delete forms there too). The Week/Day/
  Timetable reload-fallback note from the expansion slice is now only the
  Day grid + the standalone `/week`/Timetable pages, which keep reload
  behavior. 5 new tests (`TestWeekGridAsyncCrud`), full suite **1590
  passed**.
- **Removed:** side work — **Week/Day grid no longer auto-scrolls off
  12 AM**, complete (2026-08-16), direct request ("remove the action that
  moves the calendar week and day view from anywhere besides 12 AM. No
  moving despide sleep time or whatever"). The "never open scrolled to a
  Sleep hour" initial-scroll behavior (side work, 2026-08-15) is gone:
  `static/time_blocks.js`'s whole "Initial scroll" section deleted (the
  `clearMin`/`Math.max` loop over visible day columns, the
  `.time-grid-wrap` scrollTop write). The Week and Day grids now always
  open at the top (12 AM) regardless of any configured Sleep block
  covering midnight. Everything else in that file is untouched —
  `findOverlap`/`warnIfOverlapping` and the `cc-time-blocks` payload still
  drive the overlap warning toast exactly as before (Sleep Time / Leisure
  Time guidance stays purely advisory, never a scroll).
  `features/calendar.md`'s Sleep/Leisure section's "Initial scroll" note
  rewritten to say the grid always opens at 12 AM;
  `TestSleepAwareInitialScroll` (4 structural JS-source checks) removed
  from `test_settings_time_blocks.py`. Full suite 1586 passed.
- **Shipped:** side work — **Toast/snackbar rework**, complete (2026-08-16)
  — direct feedback asks on `ccToast` (static/toast.js): "don't show
  duplicate toasts (small time barrier)", "more appealing: icon + clear
  header + short body", "hovering must not make them disappear; leaving
  makes them disappear after a few seconds", "consistent look", and
  "actionable (revert/confirm)". Each toast is now an elevated card -- a
  tinted status-icon chip (`.toast-icon`), a bold title header
  (`.toast-title`), an optional short body (`.toast-body`), an optional
  accent-colored action button (`.toast-action`), and a quiet close ✕.
  Chip icon + default title derive from `variant`
  (`default` → check-circle/"Done", `error` → alert-circle/"Something went
  wrong", `warning` → alert-triangle/"Heads up"), colored via the shared
  `--tag-green/-red/-orange` pairs; the four glyphs are new
  `_icons_sprite.html` symbols. Duplicate suppression: the same
  variant+title+message shown again within `BARRIER_MS` (4s) is dropped,
  so a burst of identical save errors collapses to one toast. Hover pauses
  the auto-dismiss countdown; leaving restarts it capped at a short grace
  (`HOVER_GRACE_MS`, 2.5s). A thin `.toast-progress` bar along the toast's
  bottom edge drains 100% → 0% in lockstep with that countdown (a rAF loop,
  so "how long until this goes away" is always visible, and it freezes with
  the countdown while hovered). Success/warning call sites now pass an explicit
  `title` + short `message` (app.js's archive/delete undo,
  tasks_table.js's bulk ops, command_palette.js's created/done/deleted/
  label-added, and time_blocks.js's overlap warning whose old "Heads up: "
  message prefix became the title); the pure `variant: "error"` call sites
  are untouched and pick up the default error title for free. New
  structural JS-source checks (`test_toast_rework.py`, same style as
  `test_pwa_shell.py`), full suite **1593 passed**.

- **Shipped:** side work — **Easy deployment: systemd + Docker Compose, with
  install/update scripts and docs**, complete (2026-08-16) — a deploy slice,
  not a feature slice. Two one-command installers under `deploy/` run the app
  on a real server: `deploy/systemd/` (a native systemd service from a clone
  of the repo at `/opt/curodav`, app data in `/var/lib/curodav`, config in
  `/etc/curodav/curodav.env`) and `deploy/docker/` (a `python:3.12-slim` +
  uv single image that runs both the app and, via the compose `sync` profile,
  an optional Radicale companion; named volumes for all data). Both
  installers are idempotent, never overwrite an existing env file, and take a
  `--with-radicale` flag that generates sync credentials; both updaters pull
  `main`, re-sync/rebuild, and restart. Docs: `deploy/README.md` (both paths,
  config, `CC_RADICALE_URL` must end with the sync user's principal path,
  update/uninstall, the no-auth/trusted-network warning), plus root
  `README.md` and `webapp/README.md` deployment sections (and the stale
  "current version is 1.0" line finally fixed to 1.9.0; the webapp config
  table gained `CC_BACKUP_DIR`). The Dockerfile syncs from the `webapp/`
  member (`cd webapp && uv sync --frozen --no-dev --no-install-project`),
  matching `run.sh`'s own invocation — syncing from the workspace root
  installs nothing (root project has no deps), the original bug this
  production `uv sync` replaces.
- **Fixed:** side work — **the app now boots when Radicale is unreachable**,
  complete (2026-08-16), found by the deploy work above: `CalDavBridge`'s
  constructor connects to Radicale eagerly (DAVClient principal + default
  collection lookups), and `main.py`'s lifespan built it *outside* the
  try/except that already isolated `sync.full_refresh` — so the container
  run crashed with `ConnectionRefusedError -> "Application startup failed.
  Exiting."` whenever no Radicale server was reachable, contradicting the
  "runs with no external services" story. The bridge construction is now
  wrapped (`main.py`): on failure it sets `app.state.bridge = None`, logs
  `Radicale unreachable at startup; running without the sync bridge`, and the
  app keeps serving (a restart re-attempts the connection). The one consumer
  that can't degrade to `None`, `routers/published_lists.py`, gained a
  `_require_bridge` guard on all four mutating routes (clean 503 instead of
  an AttributeError). Since the Phase-1 label-space rework, tasks/events/
  contacts writes are plain SQL to the local SQLite store — no bridge in
  those paths — so a Radicale outage only costs background external-sync and
  Published Lists, never the app's own CRUD. Also fixed the runtime-import
  bug the container run exposed first: `caldav_bridge.py` does `import httpx`
  but httpx was only in the dev dependency group, so the pinned production
  `uv sync --no-dev` image failed at import; httpx moved into `dependencies`
  in `webapp/pyproject.toml` (uv.lock regenerated). Verified end-to-end:
  image builds, the app container boots standalone (HTTP 200, data survives
  restart in the named volume), and the compose `sync` profile's app+Radicale
  stack works together (collections auto-created under `/curodav/`).
  Full suite 1593 passed (unchanged — no test files touched; the lifespan
  fix is on a code path this suite doesn't exercise, router-function-call
  convention).
- **Shipped:** side work — **single-user authentication**, complete
  (2026-08-16), direct request ("add authentification for one user only"),
  design choice green-lit via AskUserQuestion: credentials via env vars,
  auth enforced **only when configured**. The app still ships with no login
  at all (its long-standing behavior, see deploy/README.md's old security
  note); set both `CC_AUTH_USERNAME` and `CC_AUTH_PASSWORD` and every
  request except `/login` and `/static` requires a signed session cookie.
  - **`src/auth.py`** (new, stdlib-only — `hmac`/`hashlib`/`secrets`/
    `base64`, no new runtime dependency and no schema change): `auth_enabled`
    (both creds set, else the middleware is a no-op), `verify_credentials`
    (constant-time on both fields), a **stateless signed session cookie**
    (`base64url(json({"sub","exp"})) + HMAC-SHA256`, `HttpOnly` +
    `SameSite=Lax` + 30-day max-age) with `make_session_token`/
    `read_session_token`, the signing secret from `CC_AUTH_SECRET` or
    auto-generated-and-persisted in `app_meta` (`session_secret`), and the
    gate itself, `AuthMiddleware` — pure-ASGI, reads settings off
    `scope["app"].state.settings` (set by the lifespan), 302-to-`/login?
    next=<path>` for pages and **401 JSON** for anything that wants JSON
    (`/api/*` paths, `X-Requested-With: fetch`, `Accept: application/json`)
    so fetch-driven surfaces never try to parse the login page. A
    middleware (not a per-router dependency) because it's the only layer
    that provably covers routes registered in the future too.
  - **`routers/auth.py`** (new): `GET /login` (minimal standalone
    `login.html`, deliberately NOT extending base.html — no app chrome on
    the sign-in screen; redirects away when auth is disabled or the visitor
    is already authenticated), `POST /login` (generic 401 + error re-render
    on wrong creds, no username-vs-password distinguisher; on success sets
    the cookie and redirects to the `_safe_next`-validated `next` or `/`),
    `POST /logout` (clears the cookie). `_safe_next` mirrors
    routers/tasks.py's own open-redirect guard.
  - **`config.py`**: `auth_username`/`auth_password`/`auth_session_secret`
    on `Settings`, defaulted `None` (no existing construction breaks),
    from `CC_AUTH_USERNAME`/`CC_AUTH_PASSWORD`/`CC_AUTH_SECRET`.
  - **Deploy/docs**: `deploy/*/curodav.env.example` gained commented
    `CC_AUTH_*` lines; `deploy/README.md`'s "no auth" security note
    rewritten ("applies until you set CC_AUTH_*") + config-table rows;
    `webapp/README.md` config table + Known gaps updated; new
    `features/auth.md` outcome doc + `features/README.md` tour/table rows.
    `/sw.js` kept public (a service worker can't update while signed out
    otherwise, and its precache list holds no private data).
  38 new tests (`test_auth.py` — config env parsing, every pure function
  incl. tampered/wrong-secret/expired tokens, the middleware over a real
  minimal FastAPI app via TestClient with a fixed test secret, and the
  login/logout routes via the suite's direct-call convention), full suite
  **1631 passed** (was 1593, +38), plus an end-to-end smoke of the real
  app under `CC_AUTH_*` env (signed-out 302, API 401, form render, bad/
  good login, cookie round-trip, signed-in 200) and of the no-auth default.
- **Fixed:** auth follow-up (2026-08-16) — **Settings > Purge all now
  forces a re-login.** The session signing secret lives in `app_meta`, so
  a purge (which wipes that table) left the auto-generated secret deleted
  while the in-process memoized one (`app.state._cc_auth_secret`) kept
  existing cookies valid until the next restart — a reset and the auth
  reset were out of sync. `routers/settings.py::purge_all` now drops the
  memoized secret and clears the session cookie (the wipe itself already
  happened), so the very next request re-mints a fresh secret and the old
  cookie no longer verifies: signed-out again, straight back to `/login`.
  With a stable `CC_AUTH_SECRET` configured the DB secret isn't involved,
  but clearing the cookie forces the same re-login. Two new tests (the
  route: drops cache + clears cookie + wipes app_meta; and a middleware
  integration: auto-generated secret survives a valid pre-purge cookie,
  purge drops it, the same cookie 302s to login) — full suite
  **1633 passed**.
- **Shipped:** side work — **sync announcements + delete confirmations use
  the bottom-right toast style**, complete (2026-08-16), direct request
  ("Sync announcements and status should have the bottom right announcement
  like style like for warnings, errors confirmation messages etc. Also All
  delete confirmations should be displayed there"). Both the sync status
  indicator and every "are you sure?" delete confirmation now render in the
  same bottom-right toast stack as warnings/errors/undo messages, so they
  read as part of the app's normal notification language instead of
  separate chrome:
  - **`static/toast.js`** — `ccToast` gained a `persistent` mode (state
    indicators, not event announcements): no auto-dismiss countdown (and so
    no progress bar / hover-pause), the dedupe barrier is skipped (a state
    that genuinely re-appears must re-show), and the returned handle gains
    `set(newOpts)` (update title/message/variant/icon in place) +
    `isAlive()`. Toasts can now carry an `actions` array (`.toast-actions`
    row of buttons, each label/className/onAction) alongside the existing
    single `actionLabel`/`onAction`. `ccConfirmSheet` was rewritten from a
    button-anchored popover (`.confirm-sheet`, deleted) into a persistent
    error-variant toast in the stack — `title: "Please confirm"`, `variant:
    "error"`, `className: "toast-confirm"`, Cancel + confirmLabel buttons,
    Escape/✕ cancels, one at a time. The `anchor` param is kept for API
    compatibility with every existing caller but no longer positions
    anything. (A Node smoke run caught a real bug here that the structural
    tests couldn't: the confirm button wired `onAction` instead of
    `onConfirm`, a ReferenceError that would have crashed every delete
    confirmation the moment it opened — fixed, plus a regression assertion.)
  - **`static/offline_status.js`** — the sync status is no longer a
    top-right `.sync-status-pill` (deleted): `offline` / `pending` /
    `synchronizing` now render as persistent toasts in the stack, updated
    in place via `set()` as the state changes, dismissible via ✕; "Synced"
    is transient — a brief toast only on a real non-synced -> synced
    transition (a page load that was already synced stays quiet, per §8's
    "successful background sync stays unobtrusive"). `synchronizing` with
    `pendingCount > 0` keeps showing the pending message so a retry loop
    doesn't flicker.
  - **`static/style.css`** — new `.toast-actions` / `.toast-confirm` styles
    (right-aligned action row; Cancel is a bordered ghost, the confirm
    button is filled `--danger` with dark-theme hover); `.confirm-sheet`
    and `.sync-status-pill` blocks removed.
  - **`static/sw.js`** — shell cache bumped `cc-shell-v7` -> `v8` so no
    precached copy of the reworked assets lingers.
  Docs updated (`features/offline-sync.md`, `features/design-system.md`);
  `test_pwa_shell.py`'s cache-name test updated; 6 new tests in
  `test_toast_rework.py` (persistent mode, confirm toast anatomy incl. the
  `onConfirm` wiring, sync-status toast titles, pill CSS gone) — full suite
  **1639 passed**, plus a Node smoke run (22 checks) over toast.js with a
  minimal DOM stub exercising persistent/set/isAlive/dedupe-bypass and the
  confirm action/Escape paths.
- **Shipped:** side work — **Widget bodies: one shared component library**,
  complete (2026-08-17), direct request ("make all design visual widgets
  uniform... create a coherent widget library... reused, not reinvented"),
  following `UI_CONSISTENCY_GUIDE.md` (the audited every `_widget_*.html`
  partial found the same five patterns — link-list rows, status pills, stat
  blocks, filled cards, empty states — hand-rolled slightly differently per
  file). New `src/templates/_widget_items.html`: `widget_link_row(url,
  title, leading=..., leading_class=..., right=...)` (supports a
  `{% call %}` right cell), `widget_pill(text, color, icon_name=...)`,
  `stat_block(number, label, ...)`, `filled_card(name, href, color, ...)`,
  `widget_empty(message, inset=...)`, `widget_section_label`,
  `relative_due(days)`, `widget_complete_button(uid)`. All 13 visual
  widgets (agenda incl. every view, at_a_glance, streak, next_deadline,
  important_urgent, scheduled_work_today, organize_today, quick_links,
  spaces_projects, habit_checkin, contact_list, weekly_schedule) plus the
  four builder/preview fragments' empty states refactored onto it. The
  audit surfaced and the pass fixed three real inconsistencies: (1) a bare
  `.cell-tag` with no color class in `_widget_important_urgent.html`
  rendered as a transparent pill → `widget_pill` always emits
  `.pill-static.pill-{color}`; (2) the `.pill-*` CSS family only covered 7
  of the 16 identity colors, so a `pink`/`teal`/... pill rendered
  uncolored → completed the family (9 new classes, same
  `--tag-{color}-bg`/`fg` tokens as `.tag-*`, UI guide §6); (3) three
  arbitrary fixed-width time cells (60/100/150px) where
  `white-space:nowrap` was the actual wrap-fix → `.widget-row-time`
  class, no fixed widths anywhere. Also fixed a Jinja gotcha the live
  render check caught: macro params are auto-escaped, so the builder
  empty-states' `&hellip;` entity rendered as literal `&amp;hellip;` →
  literal `…` characters. Two bodies deliberately stay off the library and
  are documented as such at the top of their files: `_widget_mini_month_
  calendar` (custom grid) and the Spaces & Projects list style (`.cell-tag.
  cal-*` is a label-identity swatch, not a status pill). Structural sweep
  tests (`tests/test_widget_library.py`, same grep-the-templates style as
  the modal-uniformization sweep): every visual widget imports the library,
  none hand-roll an empty-state/section-label/status-pill/fixed-width cell,
  and the pill palette stays complete; the old
  `TestUpcomingEventsDoubleLineFix` updated to assert the shared
  `.widget-row-time` class instead of the removed inline `width:150px`.
  Verified with a live-render script (a real seeded DB through the actual
  router functions: full dashboard with one widget of every type + every
  source preview + customize page), not just structural checks. Full suite
  **1645 passed**.
- **Shipped:** side work — **Settings templates uniformization** (both
  halves), complete (2026-08-17), direct request ("make the Settings pages
  uniform... the CSS is fine") per `SETTINGS_UI_GUIDE.md`, landed as two
  commits:
  1. **Holidays + Sleep & Leisure Time onto the Labels grouped-list + modal
     pattern** (`34b7435`): the two Tasks-table-style grids are now
     `.label-list` grouped lists (`settings_holidays.html`, each row a title
     + "calendar · from → to" hint; `settings_time_blocks.html`, Sleep and
     Leisure sections), with Edit buttons opening the same
     modal-in-`#modal-target` shape as Labels (`holiday_edit_modal.html` /
     `time_block_edit_modal.html`, delete in the footer's confirm mode) and
     "+ Add" toolbar buttons. Router: `_HOLIDAY_UPDATABLE_FIELDS`/
     `_TIME_BLOCK_UPDATABLE_FIELDS` and the per-field `update-field`
     endpoints removed in favor of `new_*_modal`/`edit_*_modal` GETs and
     `update_holiday`/`update_time_block` POSTs (`{uid}/update`); the
     time-block one deliberately ignores any `kind` the form submits (kind
     is fixed per table) and drops `end_time <= start_time` edits as
     malformed. `static/settings_holidays.js`/`settings_time_blocks.js`
     deleted — the pattern needs no JS. See `features/settings.md`'s
     Holidays and Sleep & Leisure Time entries. 9 files, full suite 1654
     passed.
  2. **Advanced + Data health + Sync conflicts merged into one "Data &
     Maintenance" page** (`47a0f54`): hub is now 7 categories, the three
     pages (plus `/export`) folded into `GET /settings/data-maintenance`
     (`settings_data_maintenance.html`) with the old URLs kept as 303
     redirects and every POST action endpoint redirecting back to it.
     Section order per the guide: (1) **Needs attention** — a warning-tone
     card (M3 `--tag-red-*` tokens, the one deliberately non-neutral block
     in Settings) rendering only when something is wrong: unresolved sync
     conflicts (Restore/Dismiss), a failed integrity check, or an
     unverified latest backup; its "visible" half is a `pill-static
     pill-red` conflict-count badge on the hub row in `settings_index.html`
     (`conflict_count`, only when > 0); (2) **Health status** as colored
     chips rather than plain text rows; (3) **Maintenance & upkeep** —
     Backup now (`btn primary`) / Verify / Check integrity / Repair /
     Reset layout (`btn ghost`) plus sync-retention and task-auto-archive
     selects; (4) **Export & import** (from Advanced); (5) **Danger zone**
     last and visually separated (purge completed / purge all); (6)
     **Backups & storage** (stats + backups table) last. Test surface
     updated across `test_phase8_settings_hub.py` (7-category hub, badge
     tests, export-inlined, purge redirects), `test_data_health.py`,
     `test_offline_sync.py`, `test_display_prefs_settings.py`,
     `test_phase10_export.py`, `test_dashboard_usability_rework.py`,
     `test_pwa_shell.py`, `test_auth.py`; the merged page reads
     `request.app.state.settings.{db_path,backup_dir,radicale_base_url}` so
     the direct-call tests build fuller fake apps. `SETTINGS_UI_GUIDE.md`'s
     reorg section marked shipped; `features/settings.md` rewritten to the
     7-category current state. 16 files, full suite **1659 passed**.
- **Shipped:** side work — **Settings Appearance page restructure + three
  template bugs**, complete (2026-08-17) — the appearance page was the last
  Settings template still using the old half-width two-column
  `.field-split` layout while General/Labels already used the single-card
  `.settings-field-row` stack; `settings_appearance.html` now matches
  General (Theme stays a non-form `<div>` rather than a `<form>`, the same
  exception General's profile-picture row established — the segmented
  control's buttons already post via `app.js`'s `window.CCTheme`). Three
  real bugs fixed along the way: (1) the edit modals for Holidays and Sleep
  & Leisure Time each rendered a **duplicate `<label>`** (their own + the
  one `_widget_list_multiselect.html` renders for its `ms_label` input), so
  clicking "Calendar"/"Days" opened the picker twice — removed the modals'
  own labels; (2) Settings > Purge all was missing `time_blocks` from
  `db.purge_all_data`'s table list, so a "purge all" left the Sleep/Leisure
  blocks behind; (3) the Sleep & Leisure rows listed full day names
  ("Monday Tuesday Friday") — new `_time_block_days_label` in
  `routers/settings.py` renders "All week" (7 days), "All work week"
  (Mon-Fri), else compact abbreviations ("Mon Tue Fri"), same shape as the
  Holidays "calendar · from → to" hint. Full suite **1662 passed**.
- **Shipped:** side work — **shared date+time range picker**, complete
  (2026-08-17), direct feedback ("create a way to add dates, and hours,
  more easily ... keyboard and mouse friendly, something for easy hour
  select"). New `templates/_datetime_picker.html` macro +
  `static/datetime_picker.js`: one popover with a month calendar (Monday-
  first, matching the app's own mini-cal) for the date and a clickable
  24-row hour grid for the start/end range ("like the Week grid"), used by
  all three call sites — the calendar event form's Start/End
  (`_event_form_fields.html`, still wrapped in `.event-start-end-field` so
  All-day hides it), the time-block edit modal's Hours (`time` mode, no
  date), and each Work-sessions-card session's when (`range` + `submit`
  mode, posting to a new `POST /tasks/{uid}/work-allocations/{event_uid}/
  set-times` endpoint wrapping the existing `db.set_work_allocation_times`
  — a session can be dated right from the card now, not only by drag). The
  picker's two hidden inputs keep the exact `start_at`/`end_at` name/value
  contract the native inputs had, so no server parsing changed anywhere.
  Hour selection is whole-hour granularity with the original minutes
  preserved when the same hour is re-saved (`origStart`/`origEnd`); the
  panel portals to `#multiselect-portal` like `.multiselect` so a modal
  never clips it, and supports pointer drag, click-click, Arrow-key + Enter
  navigation, and Escape/outside-click close. The 12h/24h display
  preference flows through as `data-dtp-12h` (via `time_format(request)`,
  which is why the macros all import `with context`) and the label is
  rendered client-side. Loaded globally in `base.html` (the event form and
  both modals are innerHTML-injected, so `datetime_picker.js` self-
  initializes via the same MutationObserver convention as
  `reminders_picker.js`). Tests: 3 new set-times endpoint tests +
  event-form-picker render test; the Work-sessions card + display-prefs
  tests rewritten off the old server-rendered `session-when` text. Full
  suite **1666 passed**.
- **Shipped:** follow-up (2026-08-17) — the picker gained a **date-only
  mode** (`data-dtp-mode="date"`: a single `YYYY-MM-DD` hidden input, plus
  a `required` param so the browser still blocks an empty submit the way
  the native input it replaces did), wired into the Holiday modal's From/To
  fields — those were native `<input type="date">`s whose browser-drawn
  popup (its clickable month/year header + Clear button) can't be themed
  by the app's CSS, the root of the "the month/year selector and the clear
  are unthemed" feedback; the themed picker replaces it everywhere now.
  **Rolled out to every remaining native date/datetime input in the app**
  (same day): task form Due/Start date, project Start/End date (label
  modal), habit check-in entry date (with `data-dtp-max="today"` so future
  days stay disabled like the old `max` attribute), the calendar "Move
  this occurrence" start/end (now the range picker), and the Tasks table's
  inline due-date cell — the picker fires a `change` on its start hidden
  input on Apply/Clear, so tasks_table.js's existing `input.inline-date`
  single-field update keeps working with zero wiring changes. Only the PWA
  offline shell (`offline_shell.js`) keeps a native date input, by design
  (a static fallback that can't depend on the app JS). Full suite
  **1667 passed**.
- **Fixed:** side work — **"Synced — All changes are up to date" toast only
  fires after a real sync**, complete (2026-08-17), direct feedback ("the
  'Synced All changes are up to date.' notification from bottom right should
  only appear after a real sync, not with a local machine that is
  continuously been connected to the server"). Root cause:
  `static/offline_status.js`'s "Synced" confirmation was gated on a
  `wasNonSynced` flag that flipped true the moment any status event left the
  `synced` state — and a routine page load on an up-to-date,
  continuously-connected machine always does leave it briefly (the `load`
  event triggers `requestSync` → a push/pull round → `synchronizing` → back
  to `synced`), so every page visit announced "Synced" even though nothing
  was pushed and nothing new was pulled. The gate is now the sync engine's
  own `didWork` fact instead: `offline_sync_client.js` sets a per-round
  `didWork` flag only when a round actually moved data — `pushOnce` when the
  outbox is non-empty (real local changes sent), `pullOnce` when the server
  returned a non-empty `changes` list (something new received) — reset at
  the start of each `syncNow` round and surfaced through `getStatus()`'s
  detail. `offline_status.js` shows the transient "Synced" toast only when
  `detail.didWork` is true; the `wasNonSynced` flag is gone. A page-load
  health check with an empty outbox and nothing new server-side stays
  silent, while a genuine offline→online flush of queued changes, or a pull
  that actually receives new data, still announces itself. See
  `features/offline-sync.md`. Test updates: `test_toast_rework.py`'s
  `TestSyncStatusToasts` re-gated on `didWork` (asserting `wasNonSynced` is
  gone), one new structural test
  (`test_offline_sync_client_tracks_whether_a_round_moved_data`) in
  `test_pwa_shell.py`. Full suite 1668 passed.
  **Same-session follow-up:** even the brief "Syncing…" persistent toast
  still flashed on every routine page load -- `syncNow` emitted the
  "synchronizing" status at the *start* of every round, so an up-to-date,
  continuously-connected machine showed "Syncing…" for the duration of its
  no-op push/pull round before settling back to "synced". The round-start
  emission is now gated on a non-empty outbox
  (`syncNow`: `if ((await CCOfflineDB.getOutboxCount()) > 0) await
  emitStatus()`), so a pull-only/no-op round announces nothing at all and
  only the round's outcome ("Synced" when `didWork`, or silence) is
  surfaced; a real flush still flips the toast to "Changes pending" the
  moment the round starts. The bare "Syncing…" `configFor` branch in
`offline_status.js` is effectively unreachable now and kept only as a
   defensive fallback. One more structural test
   (`test_sync_now_announces_round_start_only_with_real_push_work` in
   `test_pwa_shell.py`). Full suite 1669 passed.
   **Same-session follow-up:** direct feedback the next day ("when the
   server is ofline, the sync, synced notification still appear") did not
   reproduce against the current code. A Node smoke run (`/tmp/opencode/
   smoke.js`) loading the real `offline_db.js`/`offline_sync_client.js`/
   `offline_status.js` from disk under `fake-indexeddb` with a stub
   `fetch` that rejects (server unreachable) confirmed: server down + empty
   outbox → zero toasts, status stays `synced` with `didWork:false`;
   server down + queued op → only the persistent "Changes pending" toast,
   never "Synced" (status ends `pending`, and the "Synced" toast needs
   `status === "synced" && didWork === true`, which requires a successful
   push/pull). The reported behavior exactly matches the *pre-fix* code
   (page load on a dead server flashed "Syncing…" then "Synced"), i.e. the
   browser was still running a cached copy of the old scripts. Bumped
   `sw.js`'s `CACHE_NAME` to `cc-shell-v9` per the file's own convention
   so an installed PWA re-precaches the reworked `offline_sync_client.js`/
   `offline_status.js` and never serves the stale "announces on dead server"
   versions again; `test_pwa_shell.py`'s cache-name test bumped to v9. Full
   suite 1669 passed.
   **Second same-session follow-up:** "the syncing still shows onn normal
   app" did not reproduce against the current code either -- the bare
   "Syncing…" branch in `offline_status.js`'s `configFor` is unreachable
   dead code (it needs `synchronizing` with an empty outbox, and the
   round-start emission is gated on a non-empty one), so the report again
   matches a stale cached copy of the pre-fix scripts. Implemented the
   user's proposed mechanism anyway -- "a hash attached to the database,
   on the server, compared against the locally saved hash to decide
   whether a sync is needed" -- as a monotonic **server data version**
   rather than a literal whole-DB hash (a whole-DB hash would also move on
   ordinary server-rendered app edits that never enter `field_versions`,
   sending every device into a pull that returns nothing new, forever;
   the counter moves exactly when a sync write actually lands, so "did the
   version change" always matches "would a pull return something").
   Server: `db.get_sync_data_version`/`bump_sync_data_version`
   (app_meta-backed, no schema change), bumped in `offline_sync.apply_
   batch` only for *new* ops whose result actually applied (never for a
   replayed op_id, §5) and by `purge_expired` when GC physically removes
   anything; new `GET /api/sync/state` endpoint (routers/sync_api.py)
   plus `version` in every pull response (computed after the lazy GC so
   the pulling device saves post-purge state). Client: `offline_db.js`
   gains `getServerVersion`/`setServerVersion` meta rows; `offline_sync_
   client.js`'s `syncNow` now checks `nothingToDo()` on the empty-outbox
   branch -- a `GET /api/sync/state` whose version matches the saved one
   skips the round outright (no pull, no status event, no toast), while a
   failed/unreachable state check falls through to the normal round so the
   usual failure/retry path still applies; the version is saved only after
   a *successful pull*, never after a push alone (a successful push with a
   failed pull leaves changes unpulled). Node smoke (scenarios A-F)
   confirmed: version match -> only the state GET, zero toasts; version
   bump -> real round, "Synced" when changes arrive; server down -> silent
    as before. 7 new server tests (`test_offline_sync.py`'s
    `TestDataVersion`) + 2 structural JS checks (`test_pwa_shell.py`).
    Full suite 1678 passed.
- **Fixed:** side work — **a round with a non-empty outbox actually syncs
  its data again**, complete (2026-08-18) — found while smoke-testing the
  `inFlight`-reset hardening. The previous `syncNow` restructure wrapped the
  round body in `try/finally` to guarantee `inFlight` is reset even when a
  round throws, but parked the `pushOnce()`/`pullOnce()` exchange in an
  `else` of the round-start-emission branch — so a round with real push work
  queued (a non-empty outbox) took the emission branch and **never ran
  push/pull**, returned `undefined` (falsy), and `attempt()` retried it
  forever: infinite "Syncing…"/"Changes pending" with data never leaving the
  device. Exactly the signature of the user's "Syncthing is now showing
  infinitelly" report — this would have shipped the real thing if left
  alone. The push/pull exchange now runs via an independent
  `if (ok === undefined)` guard (deliberately NOT an `else`), so all three
  round shapes work: outbox non-empty → announce start + actually push/pull;
  outbox empty + version mismatch → silent push/pull; outbox empty + version
  match → skip outright. Node smoke (`/tmp/opencode/smoke.js`) re-verified
  all six scenarios; the smoke harness itself was also made faithful — it
  re-evals the sync client per scenario (fresh module state, like a fresh
  page load), which leaked the previous scenario's `setTimeout` retry timer
  into the next one and produced phantom extra rounds; the harness now
  tracks `setTimeout`/`clearTimeout` and cancels all pending timers at the
  start of each scenario. Full suite 1678 passed.
- **Shipped:** side work — **the in-progress sync toast is deferred by a
  grace period**, complete (2026-08-18), direct feedback ("Syncing shows for
  some pages, for a brief second... rework the syncing one specifically, to
  add a delay for the frontend showing. So for bigger syncing it shows, but
  for small ones it doesn't. And for none or very smalls the frontend doesn't
  get a notification"). `static/offline_status.js` (the renderer, the
  "frontend showing") now defers the *first* appearance of the persistent
  synchronizing/pending toast by `SYNC_SHOW_DELAY_MS` (1500ms): a small sync
  round -- a handful of queued ops against a reachable server, resolved in a
  few hundred ms -- never flashes "Syncing…"/"Changes pending" at all, while a
  state still current once the grace has elapsed (a genuinely slow/big round,
  or a round that fails and settles back to pending) still surfaces its
  persistent toast. The deferral covers **both** triggers of a first
  appearance, not just the round-start emission: the `DOMContentLoaded`
  initial render of a non-empty outbox (status `pending` before any round
  runs) is deferred too, otherwise a page load with a queued op would still
  flash "Changes pending" before its fast flush resolves it -- caught by the
  smoke harness's new timed snapshots. Every new status event cancels a
  pending grace timer, so a fast round's deferred toast can never surface
  after its outcome; `offline` ("You're offline") surfaces immediately, never
  deferred (the network state is worth knowing right away), and an
  already-visible persistent state (a genuinely stuck/failing retry loop)
  keeps updating in place via `set()` with no flicker. The engine
  (`offline_sync_client.js`) is untouched -- status events stay honest and
  immediate; only the renderer delays what it shows. "Synced" is unchanged:
  still gated on `didWork`, so a small-but-real sync (e.g. one op flushed
  fast) still gets its brief confirmation -- only the in-progress toast is
  suppressed by the grace (if the user wants even that silenced for tiny
  syncs, that's a follow-up decision, flagged here). `sw.js` cache bumped
  `cc-shell-v9` -> `v10` so an installed PWA re-precaches the reworked
  renderer. Node smoke (`/tmp/opencode/smoke.js`) extended from 6 to 8
  scenarios, two purpose-built for the grace: G (push+pull each delayed 2.5s)
  confirms a slow round shows "Changes pending" only after the delay (no
  toast at the 900ms snapshot, toast present once the grace has elapsed, then
  "Synced"); H (a fast successful flush) confirms no in-progress toast ever
  appears, only the "Synced" outcome; the harness's push mock now also
  acknowledges the sent ops like the real server's idempotency ledger, so a
  successful round actually drains the outbox. 2 new structural tests
   (`test_pwa_shell.py`'s `TestSyncEngine::test_offline_status_defers_the_
   in_progress_toast_behind_a_grace` and `test_toast_rework.py`'s
   `TestSyncStatusToasts::test_in_progress_toast_is_deferred_behind_a_grace_
   period`), cache-name pin bumped to v10. Full suite **1680 passed**.
- **Fixed:** side work — **the app's offline experience actually works**
   (the server writes its own UI edits into the sync mirror, and /offline's
   own scripts load offline), complete (2026-08-18) — reported directly
   ("every page offline shows the /offline empty state — Nothing to load
   right now — instead of local data"). Reproduced live against the real
   app (headless Chromium, wipe IndexedDB/caches/SW, online visit, go
   offline) and found **two independent root causes**:
   - **Root cause 1 (data): the server's own UI writes never entered
     `field_versions`** — the only source a device's pull reads. Every
     task/event/contact created or edited through the rendered app
     (`db.upsert_*`/`delete_*`) bypassed the sync layer entirely, so a
     fresh device's first pull returned an empty delta and its local mirror
     stayed empty. Fixed by making **the server itself a sync participant**:
     `db.ENTITY_TABLES`/`ENTITY_SYNC_FIELDS` (the sync-whitelist
     centralized in one place; dead `importance`/`urgency` task columns
     dropped from it), `db.SERVER_DEVICE_ID = "server"`, an app_meta-backed
     monotonic `server_hlc_clock`
     (`get_server_hlc_clock`/`mint_server_hlc`/`merge_server_hlc`),
     `record_server_sync_write` (diffs the whitelist columns before/after a
     write and records **only changed fields**, so a device's newer HLC on
     an untouched field is never clobbered) and `record_server_delete`
     (records a `deleted_at` tombstone in `field_versions`). `upsert_task`/
     `upsert_event`/`upsert_contact` and `delete_task`/`delete_event`/
     `delete_contact` now take `record_server_write: bool = True`; the GC's
     `_purge_expired_tombstones` passes `False` so mechanical purge doesn't
     re-record the tombstone it's deleting. `offline_sync.py` merges the
     server clock forward on every applied op (`apply_op` → `db.merge_
     server_hlc`), so a server edit causally after a device's offline edit
     genuinely outranks it per §3; `_current_field_value` special-cases a
     missing row's `deleted_at` (synthesizes a truthy value from the field
     HLC) so the server's hard delete propagates to devices' mirrors. A
     **one-time backfill** (`db.backfill_server_sync_writes`, app_meta
     marker `sync_server_writes_backfilled`, called at the end of
     `init_schema`) writes `field_versions` entries for every pre-fix row
     via `INSERT OR IGNORE` (never overwrites a device-synced HLC,
     idempotent, bumps the data version only when rows were actually
     inserted — keeps `test_version_starts_at_zero` green), so databases
     with data written before this fix sync that data too.
   - **Root cause 2 (assets): the SW could not serve /offline's own
     scripts.** Pages request every static asset with a cache-busting
     `?v=` URL, and `caches.match` never matches that against the
     precache's un-versioned entries — the precache only actually served
     assets the runtime path had ALSO cached under their versioned URL
     during a controlled online visit. Scripts only `/offline` loads
     (`offline_shell.js`/`offline_write.js`/`offline_status.js`) are never
     requested by a normal page visit, so they were never runtime-cached,
     and a device's first offline visit failed to load them entirely
     (`net::ERR_FAILED`), leaving the static "Nothing to load right now"
     empty state visible no matter how populated the mirror was. Fixed in
     `sw.js`'s static handler: try the versioned-exact match first, then
     fall back to `caches.match(request, { ignoreSearch: true })` before
     hitting the network — the precache becomes genuinely reachable. One
     accepted staleness (documented in the handler): between a file
     changing and the SW itself updating, an offline device may get the
     old precached copy; the `?v=` query still governs the online path,
     where the fresh file loads and is runtime-cached under its new
     versioned URL. `CACHE_NAME` bumped to `cc-shell-v11` (pinned in
     `test_pwa_shell.py`) so installed PWAs re-precache with the new
     handler.
   Verified live (headless Chromium, `/tmp/opencode/offline_test2.js`):
   wipe IndexedDB + caches + SW, visit online (mirror populates 4 tasks +
   2 events from the pull, SW controlling), block network for both the page
   and the service-worker target, navigate to `/offline` → renders "Tasks
   (4)"/"Events (2)" with real titles and "Last synced" timestamp, no
   "Nothing to load right now". 7 new server tests
   (`test_offline_sync.py`'s `TestServerWritesEnterFieldVersions` (5) and
   `TestServerWritesBackfill` (2); the §7b two-device conflict tests are
   preserved by seeding their pre-sync rows via `record_server_write=
   False` — server-vs-device participation is pinned separately). Full
   suite **1688 passed**. This also closes out the uncommitted state from
   the previous session (the sync-toast grace-period slice) — committed
   together below.
- **Shipped:** side work — **the /offline toolbar rework: "Quick add +
  Upcoming"**, complete (2026-08-18) — the offline page's toolbar is now
  two tabs (offline.html + offline_shell.js): **Upcoming** (the existing
  mirror-read list, now split into Tasks / Upcoming events / Timetabled
  events sections, agenda-style like the dashboard's Agenda widget —
  a leading date+clock cell per row) and **Quick add** (a single-field
  capture input, `!t` task / `!e` event / `!c` contact, parsed entirely
  client-side by new `static/offline_quick_capture.js` — a faithful JS
  port of `src/quick_capture.py`'s grammar, cross-checked against it —
  and created through `offline_write.js`'s new `createEvent`/
  `createContact`, built by a shared `createEntity` helper alongside the
  existing `createTask`). The "Timetabled events" section needed a way to
  tell a work-allocation session from an ordinary event in the local
  mirror, and the sync protocol only delivers through `field_versions`,
  so the server now records the flag as its own sync field: the value
  isn't an `events` column (it lives in `event_task_relations.
  is_work_allocation`), so `db.record_work_allocation_flag` writes the
  field_versions HLC entry, `create_work_allocation` calls it, a second
  one-time backfill (`db.backfill_work_allocation_flags`, own app_meta
  marker — the main `sync_server_writes_backfilled` marker covers entity
  columns only, which is why it needs a separate pass) fills in
  pre-existing sessions, and `offline_sync._current_field_value` derives
  the delivered value back from the relation table (a device push that
  tries to set it is rejected as an unknown field — the flag is
  server-derived). Honest-by-design scope, reported in the quick-add
  result line rather than silently dropped: labels can't be applied
  offline (they never flow through the field-HLC path), a task's
  scheduled time blocks can't be created offline (a work allocation needs
  the server-side relation a device op can't express), and a contact's
  phone/email are dropped (they live in `contact_phones`/`contact_emails`
  child tables outside the sync protocol; the dead `contacts.phone`/
  `email` columns are never written). The old inline add-task form is
  gone — Quick add replaces it. `CACHE_NAME` bumped to `cc-shell-v12`
  (new script precached). 6 new server tests (`test_offline_sync.py`'s
  `TestWorkAllocationSyncFlag`: flag pull on create, regular event has no
  flag, undated sessions still flagged, backfill only for `=1` relations,
  backfill idempotence + never-clobbers-device-HLC, device push rejected)
  and 9 new client tests (`test_pwa_shell.py`'s `TestOfflineToolbar`).
  Full suite **1703 passed**.

## Breadcrumbs for 1.4's two still-deferred items

1.4's main line (work allocations + both project views) is fully shipped.
Two small pieces were deliberately deferred throughout 1.4 (per
`open-priority.md`'s own "still open" notes) and don't block 1.5 — pick
either up as its own small, self-contained slice whenever convenient,
not as part of a 1.5 slice:

- **`_project_card`'s `progress`** (`routers/projects.py`) — still
  completed/total *task count* (1.3's interim proxy). `db.task_work_hours`
  exists per-task (1.4 slice 1) and is now reachable for a real project's
  tasks via the Week Calendar view (slice 3) — swap `progress` to
  aggregate `task_work_hours` across a project's tasks, per
  `open-priority.md`'s "Project progress is based on work, not merely task
  count" rule.
- **Hiding a completed task's future allocations** — `open-priority.md` §
  Work allocations: "future allocations are hidden from the active
  calendar" once a task completes, without deleting them. Not implemented
  anywhere yet — needs a filter applied in `routers/projects.py::
  project_calendar` (and any future calendar view that renders work
  allocations), keyed off `db.work_allocation_task_uid` + the linked
  task's `status`.

## How to run a session (slice discipline)

1. Read this file. That's the whole session-start cost.
2. Pick **one** slice — one roadmap bullet, sized to ship standalone (the
   roadmap docs already size sections this way; if a section still feels big,
   split it into a smaller committable piece rather than attempting it whole).
3. Before writing code, open only the specific section of `open-priority.md`
   or `open.md` the slice belongs to (use grep/section headers, not a full
   read) — the docs are long because they cover nine releases, not because one
   slice needs all of it.
4. Implement, then run the affected test file(s) directly
   (`pytest tests/test_x.py -q`), not the full suite, while iterating.
5. Before calling the slice done: run the full suite once
   (`cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q`), commit
   with a message following the existing `Released X.Y — ...` / descriptive
   style, bump `pyproject.toml` version if the slice completes a release.
6. Update the "Right now" section above with the new position. Update
   `roadmap.md`'s table row and the relevant doc section (strike through /
   mark resolved, matching how `1.1`/`1.2` were closed out) in the same
   commit. Remove the finished section from `open-priority.md`/`open.md` and
   summarize the shipped outcome in `features/`, per each doc's own "How open
   work gets tracked" footer.
7. Stop. Don't chain multiple slices in one session unless they're trivially
   small (a doc-only correction, a one-line fix) — bigger sessions cost more
   tokens per slice and make the commit history harder to audit, not easier.

## Cheap verification, every session

```bash
git status --short                                    # catch uncommitted WIP from a prior session
cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q   # full suite, ~11s, 921+ tests
```

Run both before assuming a clean starting point — WIP has been left
uncommitted before (1.2 sat complete-and-passing but uncommitted until a
session checked `git status`).

## Where the detail actually lives (read on demand, not up front)

| Need | File | Read |
|---|---|---|
| Full release order / dependencies | `plans/roadmap.md` | the one table + the current release's subsection only |
| Rework spec (projects, schedule, views, sync) | `plans/open-priority.md` | the one `##` section for the current slice |
| App-local/low-priority spec | `plans/open.md` | the one `##` section for the current slice |
| Data model / layering rules | `features/architecture.md` | before touching schema or a new entity type |
| What's shipped, for cross-reference | `features/README.md` + linked docs | only if the slice touches an existing surface |
| Why something was cut, versioning history | `plans/abandoned.md` | rarely — only if reopening a past decision |

## Notes for future sessions

- Test env: `.venv/bin/python` at repo root, run from `webapp/` with
  `PYTHONPATH=src`. The system `python3` (3.14) is not the project venv.
- Git identity in this repo: `istorie.petru <126282015+istorie-petru@users.noreply.github.com>`.
- Commit message convention: `Released X.Y — <summary>` for a release-closing
  commit (see `git log`); plain descriptive messages for side-work-only or
  partial slices that don't close a release.

- **Shipped:** side work — **Data & Maintenance page redesign**, complete
  (2026-08-26), direct request ("redesign the HTML/CSS for a data maintenance
  settings page... eliminate redundancy, improve hierarchy, minimize clutter")
  with one hard constraint: the three System Status cards stay visually
  identical (they do — byte-for-byte). Everything below them is now four
  sections in priority order:
  - **Maintenance & cleanup** — every row an inline control: auto-archive
    (`After 1 week / After 1 month / Never`) and sync retention (`Keep 30 /
    Keep 90 / Keep forever`, where "forever" is literally what retention 0
    already meant — GC disabled) autosubmitting selects, both relabeled
    without changing stored values; a legacy value from before the relabel
    renders as an honest `"14 days (current)"` extra option
    (`_choices_with_stored_value`) instead of silently displaying the first
    preset while storing something else. "Purge completed tasks" moved here
    from the Danger zone as routine housekeeping — soft grey button carrying
    its live count ("(0 right now)"). Reset Home stays.
  - **Full backup & restore** — the former hero + Backups & storage stats +
    per-backup table collapsed into ONE card, now the only place on the page
    naming a backup's timestamp, size, or filename: facts row (last backup
    through the new `fmt_dt` Jinja filter — "Aug 25, 2026, 8:57 PM", local
    zone, 12h/24h-preference aware — plus size), blue Download button,
    full-bleed divider, then restore area (filename + green `Verified ✓`
    badge, Verify integrity / Restore this backup inline buttons, a subtle
    "+ Upload a different .json file to restore" link whose submit button
    appears only once a file is chosen — no-JS fallback keeps it visible),
    helper text last. `id="backups-section"` moved onto the hero so the
    status cards' "View backups" menu item still scrolls somewhere real.
  - **Export & import** — tabbed structure and both dropdowns kept; each Data
    option carries a server-rendered `data-dm-preview` phrase composed into
    the live "*Includes: N Events, N Tasks, N Contacts*" line under Format.
    The drop zone now also accepts .csv: `routers/export.py::_import_csv_text`
    recognizes ONLY this app's own three CSV export header rows (case-
    insensitive) and round-trips them — tasks (title/status/due/labels),
    events (+start/end/all-day/location/meeting URL), contacts (+org/address,
    first phone/email landing in the real child tables the flat columns feed);
    uid-less rows skipped, merge-off skips existing uids, any other CSV
    rejected rather than half-imported. Client detection mirrors the same
    sniffing for its "Detected: ..." preview.
  - **Danger zone** — one action left, red-tinted like `.status-card.error`,
    gated twice: the red "Permanently Delete Everything" button ships
    `disabled` straight from the server and `data_maintenance.js` arms it
    only while the input reads exactly `DELETE ALL`; the confirm sheet
    remains as the second lock.
  New CSS replaces the old dm-* block (hero top/divider/badges/upload-alt/
  danger styles, generous whitespace on shared tokens). Tests:
  `test_phase10_export.py`'s TestAutoImport gained five CSV cases;
  `test_data_health.py` gained TestDataMaintenanceRedesign2026_08_26 (order,
  gate markup, human-readable facts-only-in-hero, verified badge, relabeled
  options, legacy-value visibility) + TestDataMaintenanceScriptGate;
  `test_display_prefs_settings.py` gained TestFmtDtFilter. Full suite
  **1735 passed**. Committed deliberately alongside — but separate from —
  the still-uncommitted offline-mode WIP this file's tail documents; only
  this feature stream's files are in the commit.

- **Shipped:** side work — **Data & Maintenance second pass: no backup
  section, no danger section**, complete (2026-08-26), immediate follow-up
  on the redesign above ("Full backup & restore should be integrated into
  the Backup inside System Status - in the hamburger menu. Also the Danger
  Zone should be deleted because Reset Database should do the same thing
  (check then delete)"). Two structural moves:
  - **The Full Backup & Restore card is gone entirely.** Its actions are
    menu items on the Backup status card itself now: Backup now / Download
    full backup (/export/data.json) / Verify integrity / Restore this
    backup (both posting the latest backup's filename, restore keeping its
    safety-snapshot confirm sheet), plus "Restore a file…" scrolling to the
    unified Export & import drop zone (which already auto-detects a
    data.json). The card's own meta line is the page's single mention of a
    last-backup timestamp ("Last backup: Aug 25, 2026, 8:57 PM · 7.0 kB",
    through fmt_dt) and verification state; "No backups yet -- 'Backup
    now' saves one on the server." when there's nothing yet; the backup
    filename never renders as visible text at all (only hidden inputs).
    The dead "View backups" item is gone with the table it scrolled to.
  - **The Danger zone section is gone too.** The Database card's existing
    "Reset database (purge all)" item is now the one purge path: it opens
    a new confirmation dialog (`GET /settings/purge-confirm`,
    `templates/purge_modal.html`, standard `_modal_footer` Cancel footer)
    carrying the typed-DELETE-ALL check the section used to have — the
    red button ships disabled from the server and
    `static/data_maintenance.js` arms it only on the exact phrase, bound
    by document-level delegation since the dialog injects after load.
    Check first, then delete; POST target unchanged
    (`/settings/purge-all`). Purge-completed stays a grey count button in
    Maintenance & cleanup.
  CSS: every hero/badge/restore/upload style removed; the .dm-danger-*
  phrase-gate styles remain for the dialog. Tests updated to the new
  shape (phase8's purge assertions split page-vs-modal;
  TestDataMaintenanceRedesign2026_08_26 rewritten around card-menu/meta
  facts; ScriptGate reads both templates), full suite **1737 passed**.

- **Shipped:** side work — **Data & Maintenance third pass: export/import
  folded into the Sync card as dialogs**, complete (2026-08-26), immediate
  follow-up on the second pass ("Export and Import should be incorporated
  into the sync box... entries in the three dots menu... direct to modal
  windows"). The standalone Export & import card is gone from the page
  entirely:
  - The Sync status card's menu gains a first section with **Export
    data…** and **Import data…**, each opening its own dialog (new GET
    /export/modal + GET /export/import-modal in routers/export.py,
    export_modal.html / import_modal.html, both standard #modal-target +
    _modal_footer Cancel footers). Export = the same two-dropdown
    data-dm-preview GET form posting /export/download, marked
    `data-modal-get` so modal.js's POST interceptor stands down and the
    submit navigates to the attachment natively (openModal's own fetch of
    the file finds no #modal-target and falls back to exactly that
    navigation). Import = the same content-sniffing drop zone (.ics/.vcf/
    .csv/.json) posting /export/import/auto; success closes the dialog and
    reloads the page like every other modal form. The Backup card's
    "Restore a file…" item now opens the Import dialog too (it was a
    scroll-to before; the section it scrolled to no longer exists).
  - static/data_maintenance.js rewired from load-time binding to fully
    document-level delegation (change/input/dragenter/dragover/dragleave/
    drop), since all three dialogs' markup injects after the script runs —
    the same no-wireContent-hook precedent modal.js documents for the
    command palette's delegated listeners. CSS: pane-switching/:has() rules
    removed; dropdown-field/preview/dropzone styles remain for the dialogs.
  Tests: phase8's inlined-export assertions rewritten around the two menu
  triggers + dialog renders; ScriptGate reads all three dialog templates
  and pins the delegation-only wiring. Full suite **1739 passed**.

- **Fixed:** side work — **status-card menus close on any action; menu
  items non-bold**, complete (2026-08-26), direct feedback on the third
  pass ("the three dots menu should close after any action... also the
  entries should not be bold"). app.js's action menu already closed on
  form submits but not on plain anchor items, so Export…/Import…/Restore a
  file…/Reset database left the open panel stranded behind the modal
  overlay -- a single delegated `panel.addEventListener("click", () =>
  closeMenu())` now closes it for every entry (the activated item still
  completes: closing only re-homes the panel). `.action-menu-item` pins
  `font-weight:400` so entries can never inherit a heavier weight.
  One structural test added (TestDataMaintenanceScriptGate); full suite
  **1740 passed**.

## Bug fixes (2026-08-19 session)
- Fixed modal centering: removed conflicting CSS that redefined global `.modal`/`.modal-overlay`/`.modal-header`/`.modal-footer` classes (offline mode's quick-add modal CSS was overriding the app's real dialog chrome)
- Datetime picker: date mode now auto-commits on day selection (like native `<input type="date">`)
- Datetime picker: time/range mode now auto-commits when both start and end hours are selected
- "Move this occurrence" form: added `submit=true` to datetime picker so Apply submits the form
- Added generic async handler for page forms with `data-cc-change` (not in modals) in `async_crud.js` — progressive enhancement, falls back to reload

## Bug fixes (2026-08-28 session) — breakage from the uncommitted-workflow
"Reworked settings" commits (14971d3, 2c896d1)
Two commits landed changes to labels/spaces routing and settings pages
outside the normal one-slice-per-session discipline (no STATE.md update,
several call sites left stale). Direct user report: `/labels/Debate` and
`/labels/Debate?edit=1` 404ing, `POST /dashboard/widgets` redirecting
somewhere broken, Settings > General template broken, Labels modal design
off. Root causes and fixes:
- `routers/labels.py`'s router prefix moved from `/labels` to
  `/settings/labels` but ~6 other call sites (breadcrumb-adjacent dashboard
  tiles, search results, the widget-mutation `_return_url` helper,
  `banners.py`'s redirect fallback) still built the old `/labels/{name}`
  URL — every one of those now 404s. Fixed every live call site (dead
  templates `label_edit_modal.html`/`_labels_body.html`/
  `label_merge_modal.html`/`_breadcrumb.html`, already unreferenced,
  left alone). `routers/dashboard.py::_return_url` also gained an optional
  `conn` param so a widget-mutating redirect can check `generate_space`
  and point straight at `/spaces/{name}` for a real Space instead of
  bouncing through `/settings/labels/{name}`'s own 301 (which was also
  fixed to preserve `?edit=1` across that redirect). `static/
  dashboard_widget_preview.js`'s "Done" button flush-before-navigate
  selector matched on the old href pattern — switched to matching by
  class (`a.btn.primary`) instead, so it can't silently stop working the
  next time this URL shape changes.
- `templates/settings_general.html`'s new "Calendar views" multiselect
  used `{% include "..." with ms_name=... %}` — not valid Jinja2 (this
  app's own convention is `{% set ms_name = ... %}` before a bare
  `{% include %}`, see every other `_widget_list_multiselect.html`
  caller) — a straight `TemplateSyntaxError` on every page load, which is
  why General looked "broken." Fixed to the established `{% set %}`
  pattern.
- `static/style.css`'s new Labels-table styling added `tbody
  td{padding:6px 8px}` as a **global** rule (no `#labels-table` scope),
  silently shrinking row padding on every other plain table in the app
  (Holidays, Time blocks, ...) as a side effect. Reverted the global rule
  to its original `10px 8px`, moved the tighter 6px spacing onto
  `#labels-table tbody td` specifically. The label form modal's own
  markup (`label_form_modal.html`) was otherwise verified structurally
  sound (rendered server-side and inspected directly — matches
  `habit_form.html`'s established color/icon-swatch-picker + Advanced
  `<details>` pattern byte-for-byte in shape); no headless browser was
  available in this sandbox to confirm the visual result pixel-for-pixel,
  so if the modal still looks off after this fix, that's the next thing
  to report back with specifics (which field, what it looks like).
- Updated 5 stale test assertions (`test_dashboard_router.py`,
  `test_dashboard_usability_rework.py`, `test_search_api.py`) that were
  still asserting the pre-rework `/labels/{name}` redirect target; added
  one new test (`TestSpaceWidgets::
  test_add_widget_redirects_straight_to_spaces_for_a_real_space`) covering
  the new direct-to-`/spaces` redirect path. Full suite **1741 passed**.

Deliberately NOT done this session (out of scope for "fix active
breakage," belongs to the redesign queue below): `/projects/{name}` is
still deliberately retired (redirects to `/tasks?label=...`, see
`routers/projects.py`'s own docstring, a 2026-08-15 decision) — reviving
it as a 2:1 kanban+agenda page is new feature work, not a bug fix.

## Major rework session (2026-08-28) — items 2+3+4 of the queue below,
bundled into one session with explicit user approval

Direct user request to bundle three normally-separate "one slice per
session" queue items into a single session, since they're interdependent
(the habits merge and the grouping rework both touch the same table) —
a deliberate, user-approved exception to this file's usual one-slice
discipline, not an oversight.

- **Item 2, "Merge Habits into the Tasks table"**: the standalone Habits
  feature (`routers/habits.py`, `habits`/`habit_entries` tables) is
  presentation-merged into the Tasks Table view as its own "Habits"
  group, alongside habit-*labeled tasks* (the pre-existing "Tasks >
  Habits" mechanism, task_habit_settings/target_per_day/
  task_completions) — both normalize into one shared row shape
  (`routers/tasks.py::_habit_group_items`, new `templates/_habit_row.
  html`) since they're conceptually the same thing (a habit) tracked two
  different ways in this codebase's history. The row repurposes the
  Status column for the check-in control itself (checkbox/stepper, same
  as the Dashboard's existing habit check-in widget) and Scheduled for a
  streak readout, since Due/Scheduled-as-hours don't apply to a habit.
  `GET /habits` (the standalone list page) and `GET /tasks/habits` (the
  old dedicated view) both retire to `RedirectResponse(url="/tasks")`,
  same "any bookmark still lands somewhere real" precedent `/projects`'s
  own retirement set; every habit *mutation* endpoint
  (create/edit/archive/unarchive/delete/entries/toggle in
  `routers/habits.py`, completion endpoints in `routers/tasks.py`) is
  completely unchanged — this was presentation-only, not a data-model
  change. `habits_list.html`/`_habits_body.html`/`tasks_habits.html`/
  `static/task_habit_checkin.js` deleted (dead once their one page each
  was gone); `habit_detail.html` (`/habits/{uid}`) survives as the
  Habits group row's detail link.
- **Item 3, "Tasks table rework"**: filtering reduced to Date only —
  Status/Importance/Urgency/label filter dropdowns and the group-by
  toggle are gone from `_tasks_toolbar.html`
  (`_apply_status_filter`/`_apply_importance_filter`/
  `_apply_urgency_filter`/`_apply_label_filter`/`_active_filter_count`
  deleted from `routers/tasks.py`; `IMPORTANCE_LABELS`/`COLORS`/
  `URGENCY_LABELS`/`COLORS` stay, since `task_detail.html`'s read-only
  meta row still uses them — a Table-page-only cut, not a full retirement
  of the axes, confirmed against `src/derived_state.py`'s other callers
  first). Grouping is unconditional now (`routers/tasks.py::
  _build_task_groups`): Project (one group per project label,
  alphabetical) → Habits → Unassigned → Completed, in that fixed order;
  every group but Completed is due-date ascending
  (`_due_at_key`, the one sort key left — column-header sort links and
  `sort`/`dir` are gone too), Completed is most-recent-first by
  `updated_at` and pulls every completed task out of its project's own
  group (the only way "completed always last" can hold across every
  project at once). Sorting/grouping being unconditional retired
  pagination as a direct consequence — the 1.9 pagination slice already
  special-cased "grouped mode shows everything, don't paginate it," which
  is now simply the whole page's behavior (`_tasks_pager.html` deleted).
  A "+" add-row closes every group but Completed (styled as a normal
  table row, `.task-add-row`), reusing the existing task-creation
  modal/endpoint per group (`?project=<name>`/`?habit=1`/plain, same
  `/tasks/new` flow the toolbar's own "+ New" button already used) rather
  than a new inline creator.
- **Item 4, "Tasks page: table view only"**: Kanban (`/tasks/board`) and
  Timeline (`/tasks/timeline`) both retire to redirects
  (`board_view_redirect` in `routers/tasks.py`;
  `routers/timeline.py` rewritten to a two-route redirect stub, same
  precedent as `/projects`'s own retirement — `timeline_layout.py`/
  `static/timeline.js` stay on disk, unimported by anything live).
  `tasks_board.html`/`tasks_timeline.html` deleted; `_tasks_toolbar.html`
  no longer has a view switcher at all (Table is the only view left, so
  there's nothing to switch between).
- Fallout fixed in the same session: `/tasks?label=...`/`?group_by=
  project` links that used to pre-filter/pre-group the Tasks page
  (`routers/projects.py`'s three redirects, `dashboard.py`'s project
  quick-links tile, `_widget_spaces_projects.html`'s project preview
  rows, `_widget_at_a_glance.html`'s overdue/important/urgent stat
  links) all repointed at the plain `/tasks` — grouping is automatic now,
  so a project already surfaces as its own group without a filter query
  param to ask for it.
- Tests: `test_tasks_grouping.py`/`test_tasks_habits_view.py` rewritten
  for the new `groups`/`habit_items` context shape; `test_timeline_
  router.py` rewritten to two redirect tests; `test_tasks_pagination.py`
  deleted (pagination retired); `test_tasks_view_rework.py`/
  `test_phase9b_toolbar_filters.py`/`test_phase1_derived_states.py`/
  `test_async_crud.py`/`test_project_stack.py`/`test_task_scheduled_
  column.py`/`test_dashboard_usability_rework.py`/`test_phase8_settings_
  hub.py` trimmed of assertions against removed filters/views/context
  keys. Full suite **1683 passed** (down from 1741 pre-session — net
  fewer tests than before since several whole test classes exercised code
  that's now gone, not a coverage regression on anything still live).

## Shipped — Calendar split + Contacts cleanup (2026-08-28), items 3+4 of the
queue below, bundled into one session with explicit user approval

Direct user request to do both queue items in one go.

- **Calendar split into two pages**: 4-Week and Week are standalone tabbar
  destinations now (`base.html`, `icon-grid`/`icon-clock`, `data-tab=
  "calendar_fourweek"`/`"calendar_week"`) instead of two of the four tabs in
  the shared Month/4-Week/Week/Day segmented subnav
  (`routers/calendar.py::four_week_view`/`_week_view_context` now set
  `active_tab` to those two new values so the tabbar highlights correctly).
  `calendar_fourweek.html`/`calendar_week.html` dropped the subnav entirely
  (no more cross-links to Month/Day/each other); `calendar_month.html`/
  `calendar_day.html`'s own subnav is Month|Day only now, each hardcoding
  its own tab as active rather than the pre-existing (and, on inspection,
  already-buggy — Day's tab was never marked active by default) "active
  when the others are disabled" conditional logic. Settings > General's
  "Calendar views" toggle (2026-08-28, same day, from the "major rework"
  session) is trimmed to Month/Day only — `deps.py::_calendar_views`/
  `routers/settings.py::set_calendar_views` both narrowed their valid set
  from `{month, fourweek, week, day}` to `{month, day}` and their default
  from `"month,fourweek,week,day"` to `"month,day"`; an install with an old
  stored value carrying the two retired tokens just has them filtered out
  harmlessly, no migration needed. See `features/calendar.md`.
- **Contacts page cleanup**: `contacts_list.html` was wrapping `.card` around
  `_contacts_body.html`, which itself opened a second, nested `.card` inside
  its own `#contacts-body` root — collapsed to one: `_contacts_body.html`'s
  root div now carries `id="contacts-body" class="card"` directly and the
  redundant inner `.card` is gone; `contacts_list.html` just includes the
  partial with no wrapper of its own. `#contacts-body` has to stay the
  fragment's own root either way — `static/async_crud.js::refreshRegion`
  does `current.replaceWith(fragment)` after a contact mutation, matching by
  that id — so the fix was removing the *duplicate* card, not the id itself.
  See `features/contacts.md`.
- Tests: `test_calendar_fourweek.py`'s `TestFourWeekViewTemplate` rewritten
  (subnav-cross-link assertions replaced with "no `.calendar-subnav` on the
  4-Week/Week pages at all" + "tabbar carries the two new `data-tab`
  entries" + "Month/Day's own subnav is Month|Day only", isolating just the
  `.calendar-subnav` segment before asserting, since the tabbar itself now
  also contains the literal text "4-Week"/"Week"). No contacts test asserted
  the old nested-card markup, so nothing there needed updating. Full suite
  1685 passed (up from 1683 — 2 net-new tests replacing 3 retired ones plus
  a few new assertions folded into existing tests).

## Shipped — Calendar split follow-up: Calendar tab = 4-Week, Day nav-disabled
(2026-08-28), same-day direct feedback on the entry above

Feedback after the first pass: "the day view should also be disabled. also
in the month view it should be the 4 week view, not actually the month
view. and in the sidebar it should be actually the WEEK view." Clarified via
AskUserQuestion (Day: remove from nav, keep the route reachable by direct
link; Calendar tab: repoint at 4-Week, retiring the just-added separate
"4-Week" tab as now-redundant; Week tab: no bug, just confirming it stays a
second, separate destination) before changing anything.

- **"Calendar" tabbar entry now opens 4-Week, not Month.** `base.html`'s
  Calendar link points straight at `/calendar/fourweek` (`data-tab=
  "calendar"`); the separate "4-Week" tab added earlier the same day is
  gone (redundant with Calendar now). New `routers/calendar.py::
  calendar_root_redirect` takes over the bare `GET /calendar` route
  (302 -> `/calendar/fourweek`, preserving `?label=`) — the same URL every
  event-mutation redirect (`create_event`/`update_event`/`delete_event`/
  `cancel_occurrence`) and `event_detail.html`'s "Back to calendar" link
  already target, so those all resolve one hop further to 4-Week now with
  no call-site changes needed. `four_week_view`'s own `active_tab` changed
  from `"calendar_fourweek"` to `"calendar"` so the tabbar highlights
  correctly. Month itself (`month_view`, `calendar_month.html`,
  `_calendar_month_grid.html`, `_month_view_context`) is deliberately left
  in place, just un-routed — `_month_day_cells`/`_bucket_month_items`
  underneath it are shared with the 4-Week grid, and the function is still
  exercised directly by `test_calendar_month_bars.py` and several other
  test files (this app's router-function-call test convention), so keeping
  it importable costs nothing. Settings > General's "Calendar views"
  toggle is left as-is too — it's now vestigial (only reachable code path
  left is the un-routed Month page), a known follow-up if anyone notices,
  not cleaned up this session to keep the diff to the actual nav change.
- **Day is nav-disabled**, not deleted: `calendar_day.html` dropped its own
  Month|Day subnav entirely (Month has no route to link to anymore anyway)
  in favor of a plain "back to Calendar" icon-link to `/calendar/fourweek`,
  matching `event_detail.html`'s existing back-link pattern. `GET
  /calendar/day/{day}` itself is untouched and still reachable by direct
  link — 4-Week's own day-number and "+N more" overflow links
  (`calendar_fourweek.html`) still point there, so drilling into a specific
  day still works, there's just no persistent nav entry for it anymore.
- Tests: `test_calendar_fourweek.py`'s `TestFourWeekViewTemplate` updated —
  the old "4-Week tab exists" assertions replaced with "Calendar/Week tabs
  exist, no separate 4-Week/Day tab," a new pair of tests on
  `calendar_root_redirect` (redirects to `/calendar/fourweek`, preserves
  `label`), and the Day subnav test rewritten to assert no `.calendar-subnav`
  plus the back-to-Calendar link. `test_month_view_subnav_is_month_day_only`
  (month_view's own internal subnav) left as-is since that page/test are
  intentionally unchanged. Full suite 1687 passed.

## Next session queue — major rework requested 2026-08-28 (items 2/3/4 of the
original numbering done in the "Major rework session" entry above; items 3/4
of the renumbered list below done in the "Calendar split + Contacts cleanup"
entry directly below; renumbered again to close the gap)

Direct user request, much larger than one slice — broken into the pieces
below, **one per session** per this file's own discipline. Pick the next
one in rough dependency order (sync model design first, since it's
docs-only and everything else is independent of it):

1. **Design doc: fixed-IP DB sync, transport swap only** — the PWA/
   IndexedDB/service-worker offline model (all of 1.8) is being scrapped
   as unreliable. Replacement: the app links to a database at a fixed
   IP/hostname (e.g. `192.168.1.111:8080` or `app.site.com`) from
   Settings, and syncs against it directly — no browser-side mirror, no
   offline-first editing model. Per direct answer when asked: **keep**
   the existing per-field HLC/LWW conflict logic (`field_versions`,
   `sync_devices`, `sync_conflicts`, `src/offline_sync.py`'s `apply_op`/
   `apply_batch`) — only the transport changes (direct device-to-server
   over LAN/HTTP instead of through a service worker's local IndexedDB
   mirror), and the server is explicitly the priority/authoritative side
   on conflict. Write this as its own docs-only slice in
   `open-priority.md` (same precedent as 1.8's original sync model
   write-up) before touching code; then a real implementation breakdown.
   Everything under `static/offline_*.js`, `static/sw.js`, `templates/
   offline.html`, `routers/pwa.py` needs an explicit keep/replace/delete
   decision as part of that doc.
2. **Project page: 2:1 layout** — left column (2 parts) a Kanban of the
   project's tasks, right column (1 part) an agenda of the project's
   events. Revives `/projects/{name}` (currently a redirect, see the Bug
   fixes section above) as a real page again — reconcile with the
   2026-08-15 "retire /projects" decision record in `plans/open.md`
   before building.
3. **Settings tables (Labels, Holidays, Time blocks) restyled as exact
   replicas of the Tasks table view** — same row markup/spacing/column
   conventions (see the `tbody td` padding-leak fix above, which was a
   warning sign that these tables have been drifting from the Tasks
   table's own styling), including the same per-group "+" add-row the
   2026-08-28 major rework session added to the Tasks table (see that
   session's entry above).

## Bug fix (2026-08-28 follow-up) — editing a habit force-reloaded the page

Direct user report: "editing habits force a page refresh. it should not.
save smarter." Root cause: the same-day "major rework" session (see above)
retired `/habits` as a standalone list page — habit rows now render inside
the Tasks table's own "Habits" group (`_tasks_body.html`'s `grp.kind ==
'habits'` block), with the Tasks page's `#tasks-body` region as their real
home. But `habit_form.html`'s edit/create form still dispatches
`data-cc-change="habit"` on save (unchanged, still correct for `/habits/
{uid}`'s own standalone detail page), and nothing on the Tasks page ever
claimed a `"habit"`-typed `cc-entity-changed` event — `static/
tasks_table.js`'s one listener only checked `detail.type === "task"`.
`window.ccApi.dispatchChange` came back unclaimed every time, so
`modal.js`'s generic form handler fell back to its unclaimed-change branch,
a full `window.location.reload()`.

Fix: `tasks_table.js`'s listener now claims `"habit"` alongside `"task"` —
both types refresh the exact same `#tasks-body` region
(`/tasks/regions?region=table`, already includes the Habits group
regardless of which type triggered it), so a habit edit now re-renders in
place exactly like a task edit does, no full reload. One-line-condition
fix in `static/tasks_table.js`; no server/template changes needed. Full
suite still 1687 passed (JS-only change, not exercised by the Python test
suite — `habits.js`'s own listener and its `/habits/{uid}` coverage in
`test_habits_router.py` are untouched and still pass).

## Bug fix (2026-08-28 second follow-up) — habit check-ins (checkbox/"+1")
also force-reloaded, and the underlying endpoints never supported async at
all

Direct user report: a server log line, `POST /tasks/{uid}/completions
HTTP/1.1" 303 See Other` — a real browser navigation, not a background
fetch. Same root cause family as the habit-edit fix just above (the
2026-08-28 "major rework" session merged habits into the Tasks table
without finishing the async wiring for every surface it touched), but a
second, independent gap:
- `_habit_row.html`'s three check-in forms (the plain-habit checkbox
  `habit-checkin-toggle`, and the quantity-habit `habit-checkin-plus`
  "+1"/`habit-checkin-reset` pair) had **no `data-cc-change` attribute at
  all** — only the row's own Delete form did. `static/async_crud.js`'s
  global "forms with `data-cc-change`" submit listener (loaded in
  `base.html`, the mechanism every other async mutation on this page relies
  on) had nothing to match, so these three forms fell straight through to
  a plain, unenhanced native `<form>` submit on every click.
- Independently, the two server routes those forms post to
  (`routers/tasks.py`'s `toggle_task_completion` /
  `set_task_completion`) never implemented the dual-mode
  redirect-vs-JSON convention (`deps.respond`, `X-Requested-With: fetch`)
  every other mutation endpoint in this router already follows — they
  always returned a 303, full stop. Adding `data-cc-change` alone would
  not have been enough; even a fetch-based submit would have silently
  "succeeded" by following the redirect rather than getting a real JSON
  ack.
Fixed both: `toggle_task_completion`/`set_task_completion` now take
`x_requested_with` and return `respond(x_requested_with, ...)` like
`complete_task`/`delete_task`/etc. already do (habits.py's equivalent
`/habits/{uid}/entries...` routes, used by the Habits group's *entity*-kind
rows, already supported this — only the *task*-kind routes were missing
it). `_habit_row.html`'s three forms now carry `data-cc-change="task"` (or
`"habit"` for an entity-kind row, `{% set cc_change %}` on `item.kind`) +
`data-cc-action="checkin"`. 7 new tests in `test_tasks_habits_view.py`
(`TestSetTaskCompletion`/`TestToggleTaskCompletion`'s new fetch-header
cases, `TestHabitRowAsyncSubmit`'s rendered-template assertions), full
suite 1694 passed.

## Side work (2026-08-28) — Habits group: direct number input + streak text

Direct user request against the Habits group's row in the Tasks table:
"their status is a simple increment and delete buttons, not enough, it
should be a direct number input... the due date for habits should display
a text with the streak, custom and that can be playful (depending on the
settings)."

- **Check-in control**: `_habit_row.html`'s checkbox/"+1"/reset trio is
  replaced by one plain `<input type="number" min="0" max="999999"
  step="1">` per row (both a target=1 habit and a quantity habit alike),
  auto-submitting on `onchange` through the same `.habit-checkin-value`
  form + `data-cc-change`/async_crud.js path the old controls used. No new
  endpoint needed -- `plus_url` (`routers/tasks.py::set_task_completion` /
  `routers/habits.py::add_entry`) already accepted an arbitrary `value`,
  only the old "+1" button ever called it with one; `toggle_url` and the
  reset form are unused by this row now (still live for the Dashboard's
  own check-in widget, `_widget_habit_checkin.html`/`static/
  habit_checkin.js`, an untouched separate surface). "Reasonable integer
  limit to save on memory": the input's own `max="999999"` is advisory
  only, so both `set_task_completion` and `add_entry` clamp server-side
  too (`_MAX_HABIT_VALUE` in `routers/tasks.py`, a literal `999999` in
  `routers/habits.py` -- kept as a duplicated constant rather than a
  cross-router import).
- **Streak text**: new `habit_heatmap.streak_text(days, playful)` --
  standard mode is a plain `"{n} day streak"`; playful mode escalates
  through `"This week has been full"` (7-13 days), `"{n} weeks strong"`
  (14-29), `"Consistent for {n} months"` (30+), matching the concrete
  examples from the request. Wired as a new Settings > General toggle,
  "Habit streak terminology" (`deps.py`'s `HABIT_STREAK_TERMINOLOGY_KEY`,
  `habit_streak_terminology()`/`habit_streak_text()` Jinja globals; `POST
  /settings/habit-streak-terminology`), same presentation-layer-only
  app_meta pattern as 1.6's `recurrence_terminology` (default
  `"standard"`). `_habit_row.html`'s Due column (previously a blank em
  dash) now renders `habit_streak_text(request, item.current_streak)`;
  Scheduled takes over the blank em dash Due used to show, since
  "scheduled hours" doesn't apply to a habit any more than a due date
  does.
- New CSS: `.habit-checkin-value`/`.habit-checkin-input`/
  `.habit-checkin-target` (`static/style.css`) -- the number input is
  deliberately narrower than a `.stepper-input` and keeps its native
  spinner (no flanking -/+ buttons here to duplicate it).
- Tests: `TestHabitRowAsyncSubmit` (`test_tasks_habits_view.py`) rewritten
  off the retired checkbox/plus/reset assertions to the one number-input
  form, plus two new streak-text tests (standard default, playful via a
  `_request_with_app` fake-ASGI-app Request -- same pattern
  `test_recurrence_terminology.py` established, needed because
  `deps._cached_app_meta` reads `request.app.state.settings.db_path` and
  a bare `Request({...})` has no `.app` at all). Full suite 1696 passed.

## Side work (2026-08-28, same-day follow-up) — Notion-style click-to-edit,
starting with the habit check-in counter

Direct feedback on the number input above: "how in notion we see a table
with just text and colored pills, but once you click two times on an
element it becomes editable in a non-discrete way? Yes, I want this,
starting with the counter in the status column for habits."

- New generic contract, `data-inline-edit` (`static/inline_edit.js`, ~100
  lines, loaded globally in `base.html` right after `async_crud.js`, which
  it reuses): any element carrying it renders as bare text -- no input
  border/background, just a subtle hover background and a dashed
  underline on keyboard focus -- until double-clicked (or Enter/Space
  while focused, for keyboard users). At that point its text is swapped
  for a real `<input type="number">` in place, focused and pre-selected;
  Enter or blur commits (clamped to `data-min`/`data-max`), Escape
  reverts. Committing writes the new value into the nearest `<form>`'s
  hidden `name="{data-field}"` input and calls `form.requestSubmit()` --
  picked up by async_crud.js's existing `[data-cc-change]` submit
  listener exactly like any other form on the page, so this adds no new
  network path. Deliberately generic (not habit-specific) -- the Habits
  group's check-in counter is its first user, per the request, not
  intended to be its only one.
- `_habit_row.html`'s check-in cell: the always-visible number input
  (this same day, entry above) is now a `data-inline-edit` span holding
  just the digit(s), plus a hidden `name="value"` input carrying the real
  value (`item.today_value`) the form submits. `plus_url`/the server-side
  clamp are completely unchanged -- this was presentation-only, same as
  every other step in this same-day thread.
- New CSS: `.inline-edit-cell`/`.inline-edit-input` (`static/style.css`),
  generic (not `.habit-*`-prefixed) for the same reuse reason;
  `.habit-checkin-input` (the old always-visible input's own rule) is
  gone, replaced by these.
- Tests: `TestHabitRowAsyncSubmit`'s two check-in-cell tests updated to
  assert the `data-inline-edit`/hidden-input markup instead of a visible
  `<input type="number">` (renamed to `test_plain_habit_task_has_data_cc_
  change_task`/`test_quantity_habit_shows_target_and_today_value`) --
  double-click-to-edit itself is a client-side interaction with no
  Python-side behavior to unit test beyond "the right markup and data
  attributes are present," same level this app's other JS-behavior tests
  (e.g. the ScriptGate-style ones) already operate at. Full suite 1696
  passed (net zero -- no tests added or removed, two rewritten in place).

## Side work (2026-08-28, immediate CSS follow-up) — inline-edit cell:
much less visible at rest

Direct feedback on the pass directly above: "I don't want in this case
specifically to have the bulky cell like with different background and
counter. Much simpler, much less visible besides the obvious line that
shows editing." The first pass's `.inline-edit-cell` had padding, a
border-radius and a hover background -- a visible little pill/box even
though nothing was being edited yet, exactly the "bulky" look reported.

- `.inline-edit-cell` (resting state) now has **no box at all** -- no
  padding, no border-radius, no hover background, so it reads as the
  exact same plain text as every other cell around it. The only hint it's
  interactive is a light dotted underline, always on rather than
  hover-only (so a mouse user gets the same affordance a keyboard user's
  `:focus` state already implied) -- that's "the obvious line."
- `.inline-edit-input` (the real input, mid-edit) dropped its bordered
  box too (`all:unset` + only `border-bottom` left) -- a solid underline
  replacing the resting dotted one is now the *only* visual difference
  between "displaying" and "editing," rather than a bordered/backgrounded
  field on top of the underline.
- Presentation-only, `static/style.css` only -- no markup, router, or test
  changes (nothing asserts CSS specifics). Full suite still 1696 passed.

## Side work (2026-08-29) — Habits UI rework: row columns, dedicated
edit/view modals, non-interactive heatmaps, habit work sessions

Direct feedback, five parts:

1. **Habits row (`_habit_row.html`)**: dropped the `repeat` icon next to
   the streak, and swapped the Due/Scheduled columns back the other way
   from the 2026-08-28 side work above -- Scheduled now shows the streak
   (plain text, `habit_streak_text()`), Due shows the habit's cadence.
2. **Human recurrence label, not raw RRULE**: `habit_heatmap.py` gained
   `recurrence_frequency(rrule)`/`recurrence_label(rrule)` ("Daily"/
   "Weekly"/"Monthly"/"Yearly"/"Custom" -- an INTERVAL/BYDAY/COUNT/UNTIL
   qualifier beyond the bare FREQ still resolves to its FREQ bucket).
   Exposed as a jinja global (`recurrence_label`, deps.py) and used by
   `_habit_group_items` (a habit-labeled task reads its own `recurrence`
   column; a standalone Habit entity has no recurrence field at all --
   implicitly "Daily", same as `habit_task_form.html`'s create default).
3. **Dedicated habit-task edit/view modals**: a habit-labeled task used
   to reuse the generic `task_form.html`/`task_detail.html` for edit/view
   (label dropdown, status dropdown, due date, start date, no heatmap at
   all) -- direct feedback that none of those belong on a habit. New
   `routers/tasks.py::_is_habit_task(conn, task)` routes `GET /tasks/
   {uid}/edit` to `habit_task_form.html` (now handles edit as well as
   create -- title/description/recurrence/target_per_day plus a Work
   sessions card, reusing `_task_work_allocations.html` unchanged) and
   `GET /tasks/{uid}` to the new `habit_task_detail.html` (recurrence
   label, streak, a non-interactive heatmap built from the same
   `completion_weeks`/`_completion_heatmap_weeks` task_detail.html already
   computed but never rendered, and the same Work sessions card). A plain
   task (no habit label) is completely unaffected -- both routes still
   fall through to the generic templates.
4. **Non-interactive heatmap**: `_habit_heatmap.html`'s `heatmap()` macro
   gained `interactive=false` -- renders a plain `<span>` per day instead
   of a `<form>`/`<button>` toggle, no click target at all. Used by the
   new `habit_task_detail.html` above and, for the standalone Habit
   entity's own view (`_habit_detail_body.html`), same feedback ("a
   heatmap graph should be able to be visible... not interactable").
   `habit_form.html` (the entity's edit modal) also dropped its Labels
   chip multiselect -- unlike a habit task's due/start/status (which
   `update_task` simply leaves alone when unsent), `edit_habit`'s `tags`
   argument is NOT additive, so the field is now hidden inputs that
   re-submit the existing tags unchanged (preserved, no longer editable
   from this modal) rather than just deleted outright.
5. **Habit work sessions, persistent per period**: a habit-tracked task
   is deliberately excluded from `db.list_tasks`' default query (lives
   only on Tasks > Habits), so it never reached the Week view's
   Unscheduled work panel at all before this. `routers/calendar.py::
   week_view` now also fetches `db.list_habit_tasks` directly and applies
   a different visibility rule via the new `db.habit_work_sessions_status
   (conn, task_uid, recurrence, period_start, period_end)`: a daily habit
   needs 7 dated sessions in the displayed week, weekly/monthly/anything
   else just needs 1 (monthly's period is that week's calendar month, not
   the week itself) -- "a daily habit remains persistent and disappears
   from the unscheduled work only when the current week has all been
   taken care of; for a weekly task it's enough to add only one, and
   monthly the same." An undated placeholder session (the panel's own "+"
   button) counts toward the requirement same as a dated one, same "+"/"−"
   affordance as any other task (`_unscheduled_task_item.html` branches on
   a new `item.is_habit` to show "sessions still needed this period"
   instead of "sessions still needing placement"). A plain (non-habit)
   recurring task is untouched -- still the original "every session has a
   date" rule.

32 new tests (`test_habit_ui_rework.py`), full suite 1728 passed.

## Side work (2026-08-29) — inline-edit input: hide the native number
spinner arrows

Direct follow-up on the Habits-group check-in cell's click-to-edit
control (`.inline-edit-cell`/`.inline-edit-input`, `static/inline_edit.js`)
once it was confirmed actually working live: the real `<input
type="number">` that appears mid-edit still showed the browser's native
up/down spinner buttons, a small bordered-looking control that undercuts
the "no chrome, just text + an underline" look the last two passes on
this element were about. `.inline-edit-input` now sets `-moz-appearance:
textfield` (Firefox) and hides `::-webkit-outer-spin-button`/
`::-webkit-inner-spin-button` (Chrome/Safari/Edge) -- the field is still a
real `<input type="number">` (keyboard up/down arrows and scroll-wheel
adjustment still work), just without the visible spinner widget.
Presentation-only, `static/style.css` only. Full suite still 1728 passed
(no test asserts CSS specifics, same as the passes before it).

## Side work (2026-08-29, immediate follow-up) — inline-edit input: no
border, background matches the row

Direct feedback: "for this input have the same background as the rows and
no border." `.inline-edit-input` (the real `<input>` shown mid-edit) drops
its `border-bottom` entirely and switches from a hardcoded surface color
to `background:transparent` -- transparent rather than a specific
`--surface-container-*` variable so it always matches whatever's actually
behind it (a row's hover state, light/dark theme) instead of risking a
mismatch against either. There is now no visual boundary at all between
"displaying" and "editing" beyond the text becoming an editable field --
as close to invisible chrome as an `<input>` can get, in line with every
prior pass on this control trending the same direction. Presentation-only,
`static/style.css` only. Full suite still 1728 passed.

## Bug fix (2026-08-29, immediate follow-up) — the "no border, background
matches the row" pass directly above hadn't actually done anything

Direct report: "i don't think it worked." Verified live (seeded a habit
task, ran the real app, curled the served `/static/style.css`) rather than
re-guessing at CSS blind a third time -- found a real bug, not a
perception issue. `.inline-edit-input` collided with an unrelated, dead
rule higher up the same file (a 2026-08-02 "inline-editable text"
convention for project/Space/list names, its own comment gone, no live
consumer left anywhere in a template or script): `.inline-edit-input:
focus{background:var(--control-bg)}`. A `:focus` pseudo-class beats a
plain class on specificity regardless of source order, and this input is
focused essentially the entire time it's ever visible (`inline_edit.js`
calls `.focus()` right after creating it) -- so that dead rule was
silently repainting a background on it no matter what the real rule said.
Removed the dead rule outright (it had nothing left to style) rather than
just out-specificity'ing it. Also hardened `.inline-edit-input` itself
while in there: `-webkit-appearance:none`/`appearance:none` added
defensively (`all:unset` alone doesn't reliably strip a number input's
native platform chrome in every browser -- the standard, separate fix).
Presentation-only, `static/style.css` only -- confirmed via a live curl of
the served CSS that the collision is gone and only one `.inline-edit-
input` rule remains. Full suite still 1728 passed.

## Bug fix (2026-08-29, immediate follow-up) — the real root cause: the
PWA service worker had been serving a stale style.css all session

Direct report, after the dead-CSS-rule fix above still didn't visibly
change anything: "it did not work. i guess it's fine." Worth chasing
down properly rather than accepting it, since every fix up to this point
had verified correct on the live server (curl bypasses a service worker
entirely, which is exactly why server-side verification kept looking
right while the browser didn't change).

Root cause: `static/sw.js` (the PWA app-shell service worker,
`pwa.js`-registered globally on every page load, 1.8 slice 3) precaches
`/static/style.css` under `CACHE_NAME` ("cc-shell-v14" -- last bumped
2026-08-26, for an unrelated redesign, and not touched since). Its fetch
handler tries an exact versioned-URL (`?v=<mtime>`) match first, but
falls back to `caches.match(request, {ignoreSearch:true})` against that
precache's un-versioned entry the moment the exact match misses (v11,
2026-08-18, added on purpose so /offline's scripts load on a device's
first-ever offline visit) -- and for a file that's never been re-fetched
under a brand-new `?v=` during a runtime-cached online visit, that's
*every* request. So every single CSS edit this session (five rounds:
number-input replacing the checkbox trio, the box-removal pass, the
spinner-arrow hide, the border/background pass, the dead-rule fix) kept
being served the SAME install-time style.css out of the service worker
cache, completely independent of what the server actually returned or
how correct the source file was.

Fix: bumped `CACHE_NAME` to `"cc-shell-v15"` -- the only thing that
forces a fresh precache; `activate`'s existing cleanup (deletes any
`cc-shell-*` cache except the current one) then evicts the stale v14
cache entirely. `sw.js`'s own version-history comment updated with the
lesson: a `static/style.css`-only change has to bump `CACHE_NAME` too
now, not just a JS rewrite, given the ignoreSearch fallback means a
precached CSS file never naturally goes stale on its own. Test:
`test_pwa_shell.py`'s `TestServiceWorkerCacheVersioning`-equivalent
assertion updated from `"cc-shell-v14"` to `"cc-shell-v15"`. Full suite
1728 passed. **This should be the actual fix for every CSS-not-showing-
up report from this entire session** -- a hard refresh (or reopening the
tab after the new service worker activates) should finally show all of
today's habit check-in cell changes at once.

## Bug fix (2026-08-29, immediate follow-up) — the underline itself was
the leftover "border"

Direct report after the service-worker fix above: "the border is still
there." Real bug, not another stale-cache echo (confirmed the new SW had
actually taken over first). `.inline-edit-input`'s own border/background
were already gone (the two passes above), but `.inline-edit-cell` (the
outer `<span>`) keeps its resting-state dotted `text-decoration` the
entire time -- `inline_edit.js`'s `enterEditMode` only swaps the span's
*content* (text -> a real `<input>` child via `appendChild`), it never
leaves the span itself, so that dotted underline kept drawing underneath
the input while editing (browsers propagate an ancestor's text-decoration
line across descendant inline content, including form controls) -- which
is what was actually being reported as a leftover border. Fix: `.inline-
edit-cell[data-editing]{text-decoration:none}` -- `[data-editing]` is the
same attribute `enterEditMode` already sets on the cell the moment edit
mode starts, so no JS change was needed, just this one rule. Bumped
`CACHE_NAME` to `"cc-shell-v16"` (per the v15 lesson two entries up: a
`static/style.css`-only edit needs this too, now proven not just
written down) and updated the matching pinned test assertion. Full suite
1728 passed.

## Bug fix (2026-08-29, immediate follow-up) — habit-task heatmap's empty
space in its detail modal

Direct report: "for habits, the heatmap graph should not have empty
space. Prefer to show more months, empty cells, but not empty space."
Confirmed by inspecting `static/style.css`: the heatmap's cells are a
fixed 11px (+3px gap), and `routers/tasks.py::_completion_heatmap_weeks`
(the habit-tracked-task detail modal's heatmap, `habit_task_detail.html`)
defaulted to 12 weeks — 168px wide — inside a `.detail-card` that renders
at roughly 616-660px in the 700px modal (`.modal` width minus
`.modal-body`/`.detail-card` padding), leaving a ~450px blank gap to the
right. The standalone habit detail modal (`_habit_detail_body.html`,
`routers/habits.py`) already used a wider `DETAIL_WEEKS = 53` ("a bit
over a year," matching GitHub's contribution-graph convention) and
doesn't show the same gap.

Fix: moved `DETAIL_WEEKS` into the shared `habit_heatmap.py` module (both
routers already depend on it, so this isn't a new coupling) and pointed
`_completion_heatmap_weeks`'s default at it instead of the literal `12` —
`routers/habits.py` re-exports the name unchanged so its own call sites
and tests are untouched. The extra weeks beyond "today" still render as
blank *cells within the grid* (`level -1`, non-interactive) rather than
literal empty space around it — same mechanism the standalone habit
heatmap already relies on, just applied consistently to the task-tracked
variant too. No CSS/JS touched, so no service-worker cache bump needed.
Full suite 1728 passed.

## Bug fix (2026-08-29, immediate follow-up) — widened heatmap left no
visible scrollbar, and scrolled to the wrong end by default

Direct report on the widening fix above: "better. but no scrollbar. and
the actual entries are a priority." Two real problems, not one:
`.heatmap{overflow-x:auto}` does make the grid scrollable once it's wider
than its card, but (1) plain `auto` leaves the scrollbar's *appearance* to
the OS/browser default, which on several platforms (macOS's "when
scrolling" trackpad setting, most mobile browsers) is a transient overlay
invisible until actively mid-scroll -- no visible affordance that there
was more to see; and (2) a freshly rendered scroll container starts
pinned to its left edge, i.e. the *oldest* end of the grid, while
`heatmap_weeks`/`heatmap_range` always end the grid on `today` -- so the
most relevant cells (today, and whatever real entries sit near it) were
exactly the ones scrolled out of view by default, behind an invisible
scrollbar.

Fix, two parts:
- `style.css`'s `.heatmap` now sets `scrollbar-width:thin` (Firefox) plus
  `::-webkit-scrollbar`/`-track`/`-thumb` rules (Chrome/Safari/Edge) for a
  slim but always-present, always-visible track/thumb instead of relying
  on the OS default.
- New `static/heatmap_scroll.js` (`window.CCHeatmapScroll.init(root)`,
  same re-init-after-inject convention as `avatar_cropper.js`/
  `contact_phone_email_rows.js`) sets `el.scrollLeft = el.scrollWidth` on
  every `.heatmap` in `root`. Wired to `DOMContentLoaded` (full-page
  loads), the existing `cc-region-swapped` event `async_crud.js`'s
  `refreshRegion` already dispatches (the standalone habit modal's
  `#habit-detail-body` refresh), and `modal.js`'s `wireContent()` (both a
  modal's first open and the view<->edit swap-in-place) -- the same three
  places every other per-fragment behavior in this app already re-inits
  from. Loaded globally in `base.html` (not shell-critical, so not added
  to `sw.js`'s `SHELL_ASSETS`, same category as `inline_edit.js`/
  `async_crud.js`). Scrolling left still reaches the older history; this
  only changes where an untouched heatmap starts.

Bumped `CACHE_NAME` to `"cc-shell-v17"` (`style.css` changed again, per
the v15/v16 lesson) and updated the matching pinned test assertion. Full
suite 1728 passed.

## Bug fix (2026-08-29, immediate follow-up) — stopped chasing the
scrollbar, removed the possibility of one instead

Direct feedback on the v17 fix above: "I just never want for a
[scroll]bar to ever be needed there. Only have what is necessary." Right
call -- v17 made an already-present overflow visible and better-
positioned, but a fixed-cell-size grid wider than its container will
always overflow *something* eventually (a longer DETAIL_WEEKS, a narrower
window, a different modal). The actual fix is to remove the overflow
case entirely rather than manage it. `.heatmap-wide` (style.css, added
2026-08-08 for the exact same "cover all the width, no scrollbar" reason,
already used by Tasks > Habits' cards) stretches each week column's cells
to fill the available width instead of rendering them at a fixed 11px --
so the grid's rendered width always exactly equals its container's,
regardless of DETAIL_WEEKS or container size. Passed `extra_class=
'heatmap-wide'` into both detail heatmaps (`_habit_detail_body.html`,
`habit_task_detail.html`) that v16/v17 touched.

With that in place there's nothing left to scroll, so v17's whole
apparatus came back out: reverted `.heatmap`'s scrollbar-visibility CSS,
deleted `static/heatmap_scroll.js`, and removed its `<script>` tag
(`base.html`) and its `wireContent()` hook (`modal.js`). Bumped
`CACHE_NAME` to `"cc-shell-v18"` (style.css changed again) and updated
the pinned test assertion. Full suite 1728 passed.

## Next session queue — direct request 2026-08-29 (new backlog, not yet
started)

Direct user request, dumped as a raw list — broken into pieces below per
this file's one-slice-per-session discipline. Not ordered by priority;
pick whichever is smallest/cleanest next. Some overlap with items already
queued elsewhere (noted inline).

**Direct steer, 2026-08-29 (later the same day), reorders item 12 below to
the front of this queue — security is a first priority:** auth
(`features/auth.md`) should be **on by default**, not opt-in via
`CC_AUTH_USERNAME`/`CC_AUTH_PASSWORD`. Today's behavior — fully open
unless both env vars are set — was flagged as a live bug ("auth right now
is not working correctly" / "not enforcing, bypassable") before tracing
it to this by-design default; the correction is to change the default
itself, not just document it.

**Shipped 2026-08-29 (same day, follow-up)** — design finalized then built
in the same session:
- First-run setup is a forced **web setup page** (`GET/POST /setup`,
  `routers/auth.py`), not a generated password: the operator picks their
  own username/password (8+ chars, confirmed) on first visit. Credentials
  are persisted hashed (PBKDF2-HMAC-SHA256, 260k iterations,
  `auth.hash_password`) in `app_meta` (`auth_username`/
  `auth_password_hash`), not env vars — matches the existing
  auto-generated-session-secret precedent (`AUTH_SECRET_KEY`) of "persist
  in app_meta, not disk config." `auth.verify_credentials`/`auth_enabled`
  now check this persisted account as a fallback to the env pair.
- Local dev **keeps today's opt-out** (open unless `CC_AUTH_USERNAME`/
  `CC_AUTH_PASSWORD` are both set) — the default only flips for real
  deploys. Distinguished by a new `CC_DEPLOY_MODE` setting (`config.py`,
  default `"local"`, read from `CC_DEPLOY_MODE`); `deploy/systemd/
  curodav.service` and `deploy/docker/Dockerfile` both set
  `CC_DEPLOY_MODE=production` so only those two deploy paths force
  first-run setup (`auth.setup_required`, enforced by `AuthMiddleware`,
  which caches "already configured" on `app.state` — reset by Settings >
  Purge all, `routers/settings.py::purge_all`). Local dev, and anyone
  running the app manually without that var, is unaffected — confirmed by
  a live smoke test (fresh install → forced `/setup` → account creation →
  logged in; a second, uncookied client still hits `/login`; `/setup`
  itself 302s away once configured).
- Still single-user, per `features/auth.md` § Out of scope — unchanged.
- Bundled in the same slice per direct request, both pulled forward from
  item 12 below: **CSRF protection** (`auth.CSRFMiddleware` — Origin/
  Referer verification for state-changing requests carrying the session
  cookie, only enforced when auth is enabled; no per-form tokens, no
  template changes, confirmed live against `/tasks`) and **login rate
  limiting** (`auth.login_rate_limited`/`record_failed_login` — in-memory
  per-IP sliding window, 5 attempts / 15 minutes, wired into
  `routers/auth.py::login_submit` as a 429).
- 99 new/updated tests across `test_auth.py`; full suite 1780 passed.
  Docs: `features/auth.md` rewritten (deploy-mode default, /setup, CSRF,
  rate limiting), `deploy/README.md` + both `curodav.env.example` files
  updated for the new default posture.

1. **Bulk actions on tables** — every table/table-like surface in the app
   (Tasks first, since it's the precedent; then Habits, Contacts, Labels,
   Holidays, Time blocks, etc. wherever a table exists), not just Tasks'
   existing bulk bar.
2. **Undo history (Ctrl+Z), 15-30 actions deep** — a real undo stack across
   the app, not the current per-row "delete with undo" toast pattern
   (`_task_row.html` et al.) — this is a bigger, general mechanism sitting
   on top of/replacing that.
3. **Recurrence affected by holiday calendars, for both tasks and habits**
   — the named holiday calendars already exist for events/scheduling
   (`open-priority.md`'s shipped Schedule & recurrence rework); extend the
   same non-working-day policy to task and habit recurrence.
4. **Fully disable Relations as a feature** — not the work-allocations
   half of `event_task_relations` (keep that), the separate task↔event
   Relations *card*/picker described in `features/tasks.md` § "Relations
   (task ↔ event)". Already has a presentation-layer toggle
   (`deps.py::show_relations_card()`, default on) — this asks to go
   further: fully disable/remove the feature, not just hide the card.
5. **Remove the "Configurable views" Calendar setting** — see `open.md` §
   Configurable views; its Calendar half (Month/4-Week/Day toggles) is
   still live and should come out. (The Tasks half was already superseded
   2026-08-28 — see that section.)
6. **Label modal window** — better visual picker for Space / Project /
   None (currently unclear which is selected); fix a font-size mismatch
   between `.usage-badge` and the table it sits in.
7. **Holidays and Time blocks settings tables not on latest CSS** —
   already queued above ("Settings tables (Labels, Holidays, Time blocks)
   restyled as exact replicas of the Tasks table view") — this is a
   direct re-confirmation that item is still open.
8. **Cleaner modal for creating/editing a published list** — bring it in
   line with the rest of the app's modal styling (post-modal-
   uniformization pass, `features/design-system.md` § Modal windows).
9. **Tasks table view, several changes bundled together:**
   - Labels and Status columns become always-clickable checkbox dropdown
     menus (not click-to-open-then-pick).
   - Title column: double-click to edit inline (same inline-edit
     convention as this session's habit work, `inline_edit.js`).
   - Rename the "Due" column to "Date".
   - Date-picker dropdown: remove the Apply button entirely; Clear button
     loses its text label, becomes icon-only (near an arrow, but with
     visible separation, not crowded against it).
10. **Rename "Week" to "Planner" in the sidebar** — label change only,
    confirm it doesn't collide with a different Planner concept elsewhere.
11. **Mobile responsiveness audit** — pass over the app's existing
    surfaces on small viewports; scope (which pages, phone vs. tablet) to
    be defined when this is picked up.
12. **Production-readiness / infra cluster** — grouped because they're
    likely to share a session or two, not because they're one slice.
    **Correction to this file's earlier note:** auth already exists —
    single-user login shipped 2026-08-16, see `features/auth.md` +
    `webapp/src/auth.py::AuthMiddleware` (optional, on when both
    `CC_AUTH_USERNAME`/`CC_AUTH_PASSWORD` are set; signed `HttpOnly`/
    `SameSite=Lax` session cookie gating every route). Nothing here needs
    "build auth first" — these are gaps on top of what's already shipped:
    - Gzip compression + database indexes (performance).
    - Alembic migrations (schema upgrades — currently no migration
      framework; check `features/architecture.md` before starting).
    - Security headers (CSP, HSTS).
    - ~~CSRF protection~~ — **shipped 2026-08-29**, see the entry below;
      `src/auth.py::CSRFMiddleware`, Origin/Referer verification, no
      per-form tokens.
    - HTTPS redirect / `Secure` cookie flag — explicitly out of scope
      today (`features/auth.md` § Out of scope: threat model assumes a
      trusted network or TLS-terminating reverse proxy); only relevant
      once/if the app is exposed beyond LAN — see the DAVx5 item in
      `open.md`, same "needs a domain/server" precondition.
    - Session timeout — today's cookie is a flat 30-day expiry from
      login, not an idle/activity timeout; "session timeout" likely means
      adding the latter.
    - ~~Login attempt rate limiting / lockout~~ — **shipped 2026-08-29**,
      see the entry below; `src/auth.py::login_rate_limited`, in-memory
      per-IP sliding window.

## Follow-up (2026-08-29, same day) — bigger heatmap cells

Direct request: "could you make the cells a bit bigger." With both
detail heatmaps now on `heatmap-wide` (previous entry), cell size is
`container width / DETAIL_WEEKS` -- there's no fixed-px cell size left to
bump directly, so the lever is `habit_heatmap.DETAIL_WEEKS` itself: fewer
columns dividing the same container width renders each one bigger.
Dropped it from 53 (~1 year) to 32 (~7.5 months) -- a real size increase
(roughly 1.6x wider per cell) while still showing well over half a year
of history. No CSS/JS touched, pure Python constant, so no
service-worker cache bump needed. Full suite 1728 passed.
