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
- **Next slice:** nothing queued yet toward `1.9` — the next session should
  open `plans/roadmap.md`'s `1.9 — Deployment & polish` subsection to scope
  the first real slice there (DAVx5 mobile hosting is pure infra, blocked
  on an external domain + server, so likely not the first thing to pick
  up). In the meantime, any of these smaller, self-contained side-work
  items are fair game for a session that wants a break from that: `open.md`'s
  Command palette actions follow-up (1.2 side work), 1.4's optional Project
  check-in, 1.6's optional "Configurable views + optional Schedule module",
  and 1.8's own Pagination/collapsible-sections side work (Phase B of
  webapp usability, `roadmap.md`'s 1.8 row).

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
