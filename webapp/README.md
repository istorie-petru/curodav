# Command Center Web

Mobile/remote client: calendar, tasks, contacts, and a recurring class
schedule, full CRUD, synced against a self-hosted Radicale (CalDAV/CardDAV)
server.

**Update 2026-07-31:** Tasks gained a Kanban board, subtasks, and
checklists at explicit user request -- this reverses the "no project/
board/tag-graph features by design" line that used to be here. The
tag-graph/links/general-board *object* system (desktop's arbitrary
cross-type linking) is still out of scope. What shipped instead, all built
to fit this app's plain CalDAV/CardDAV data model rather than desktop's
file-based object graph:

- **Kanban board** (`/tasks/board`) -- columns are just `tasks.status`
  grouped and rendered differently; no new table, no new CalDAV property.
- **Subtasks** -- `tasks.parent_uid` already existed and already
  round-tripped through `RELATED-TO;RELTYPE=PARENT` (ical_rows.py); this
  just added UI (a parent's detail page lists and quick-adds children).
  Unlike desktop, deleting a parent cascades to its subtasks, since this
  app's only path to a subtask is through its parent's detail page (see
  `routers/tasks.py::delete_task`).
- **Checklists** -- the one genuinely new, local-only table
  (`task_checklist_items` in `db.py`), following the same precedent as
  `schedule_classes`: there's no standard iCalendar property for a task's
  own checklist, so this app's SQLite is the authoritative store for it,
  same as it already was for Schedule. A checklist made here won't appear
  if the same task is opened from another CalDAV client.

**Update 2026-08-01, Phase 1 of the projects/tags rework (data layer
only, no UI/routers yet):** added `tags`, `tag_groups`, `projects`, and
`project_groups` tables to `db.py`, plus a `project_uid` column on
`task_lists`/`calendars`/`addressbooks`/`schedule_classes`. All local-only,
same precedent as checklists/schedule above -- there's no CalDAV/CardDAV
concept for either a project or a tag's color/group. Tag *assignment*
itself is not new and is not local-only: tasks/events/contacts already had
a `tags_json` column that round-trips through iCalendar/vCard `CATEGORIES`
to Radicale and any other client; the new `tags` table is a color/group
registry on top of that existing, already-synced data, not a replacement
for it. A project doesn't own objects directly -- no new graph/link table
was added (this file explicitly avoided that before, for tasks/events/
contacts, and the same reasoning applies) -- instead a whole task list,
calendar, address book, or schedule class points at a project via its own
`project_uid`, which is how "link a whole list to a project" is meant to
work per the feature request. See `db.py`'s table comments and
`tests/test_projects_tags_db.py` for the full behavior, including why
`upsert_task_list`/`upsert_calendar`/`upsert_addressbook` COALESCE
`project_uid` instead of overwriting it (an ordinary rename/recolor must
not silently unlink a list from its project) and why archiving a project
doesn't cascade a write to the lists under it (retirement is derived at
query time via `project_is_archived`, so unarchiving needs no cascade
either). Routers, Settings UI, and the project detail page are not built
yet -- next phase.

**Update 2026-08-01, Phase 2 of the projects/tags rework: global
recommendable tags, live end-to-end.** `routers/tags.py` (`/tags`) --
create/rename/recolor/group/merge/delete a tag, plus tag groups, all in
one modal-friendly manage page (`tags_manage.html`), same pattern as
`task_lists_manage.html`/`addressbooks_manage.html`. The part that
actually mattered: tag *assignment* is real, already-synced data
(tasks/events/contacts' `tags_json`, round-tripped through iCalendar/
vCard `CATEGORIES`), so rename/merge/delete can't just touch this app's
SQLite cache -- `_rewrite_tag_everywhere()` finds every affected task/
event/contact, rewrites its tags, and pushes the change back through
`CalDavBridge.save_task_row`/`save_event_row`/`save_contact_row` *before*
updating the local cache. Verified against a live local Radicale
instance, not just the fake-bridge unit tests in
`tests/test_tags_router.py` -- create a task with new tags, confirm they
auto-register (see below), rename one, confirm the task's real `tags_json`
changed; delete one, confirm it's stripped from every object that had it
and the registry row is gone.

A tag typed on any task/event/contact form now also **auto-registers**
(`db.ensure_tags_registered`, called right after every create/update
save) with a default gray color -- otherwise a tag you'd just used
wouldn't show up on the manage page until someone separately added it
there by hand, which would have made the empty-state copy ("tags are
created automatically the first time you type one") a lie. This also
required deciding a naming collision: renaming a tag to a name another
tag already has now merges into that tag instead of raising a
unique-constraint error the user can't act on from a plain HTML form.

**Recommend-as-you-type** on the Tags field of `task_form.html`/
`event_form.html`/`contact_form.html`: a plain HTML `<datalist>` was
tried first and rejected -- selecting a suggestion replaces an entire
`<input>`'s value, which breaks a comma-separated multi-tag field the
moment you pick a suggestion for tag 2 (it wipes tag 1). Built
`static/tag_input.js` instead: progressive enhancement that suggests only
the current comma-separated fragment being typed, keeps the underlying
input's name/value shape completely unchanged (still plain
comma-separated text, so no router parsing changed), and degrades to an
ordinary text input with the native datalist popup if JS is off. Loaded
once in `base.html` (not per-form `extra_scripts`) and wired via a
`MutationObserver`, because every form here can arrive already-rendered
via `modal.js`'s `body.innerHTML = ...`, which never executes `<script>`
tags embedded in that HTML.

**Update 2026-08-01, Phase 3 of the projects/tags rework: projects as a
first-class, customizable nav destination.** `routers/projects.py`
(`/projects`) -- unlike Tags (a small manage-modal reached from other
pages), Projects got its own top-level nav tab, since a project is meant
to be a destination you go *to*, not a utility you edit in passing.

- **Manage page** (`/projects`) -- create/rename/recolor/icon/group/
  merge/archive/delete, same flat-row-list pattern as `tags_manage.html`.
- **Detail page** (`/projects/{uid}`) -- centralizes every task/event/
  contact/class belonging to a list linked to this project (via Phase 1's
  `project_uid` columns), plus a derived, never-stored progress bar
  (`done / total` over the project's own tasks) -- same "always computed"
  principle desktop's project view documents. Linking an *existing* list
  to a project (the dropdown on task-list/calendar/address-book/schedule-
  class management) is deliberately **not** built yet -- that's Phase 4.
  Until then the detail page's sections just show their empty state; the
  aggregation logic itself (`_project_scope`) is fully built and tested
  against Phase 1's `set_*_project` setters directly.
- **Customization**: color (reusing the same 8-color palette calendars/
  task-lists/address-books already use), a free-text icon field (emoji or
  short glyph), and a cover image -- same base64-in-SQLite approach as
  contact photos (`routers/contacts.py`'s `_read_photo`), minus the vCard
  round-trip since a project isn't synced at all. Validated against the
  same content-type allowlist/size-cap reasoning (`_read_cover_image`):
  this app has no auth, so an unauthenticated upload gets checked against
  what it actually is, not what it claims to be.
- Archiving is unchanged from Phase 1's design (retire, don't delete;
  no cascade write, since a linked list's "is my project archived"
  question is answered live via `project_is_archived` at query time) --
  this phase just gives it a UI (Active/Archived sections on the manage
  page, an Unarchive button).

Verified against a live local Radicale instance end-to-end (not just the
unit tests in `tests/test_projects_router.py`, which need no bridge at
all since projects are entirely local): created a project, linked the
default task list to it via the Phase 1 setter, created a real task
through the actual form, and confirmed it appeared correctly aggregated
on the project's detail page.

**Update 2026-08-01, Phase 4 of the projects/tags rework: linking
existing lists to a project.** The gap Phase 3 deliberately left open --
every list-management page (`task_lists_manage.html`, `calendars_list.html`,
`addressbooks_manage.html`) and the schedule class form
(`schedule_class_form.html`) now has a Project dropdown, wired to Phase
1's `set_*_project` setters via each router's create/edit endpoint. The
dropdown only renders when at least one project exists (`{% if projects
%}`) -- an empty `<select>` isn't just visual clutter, it'd also mean the
edit form always submits `project_uid=""`, and every edit route treats
that as an explicit "unassign," not "field wasn't shown." Regression-
tested for the specific failure mode this setup avoids: renaming/
recoloring a list that's already linked to a project, through the real
router endpoint, must not silently unlink it (`tests/test_project_linking.py`,
`TestTaskListLinking::test_rename_via_router_preserves_link` and
siblings) -- this is exactly the "ordinary edit clobbers a field the
caller didn't mean to touch" bug class Phase 1's COALESCE design was
built to prevent.

**"University courses become projects, with a dropdown"** -- built as
specified: a Schedule class links to a project via the same `project_uid`
mechanism as any other list (`set_schedule_class_project`), not by a
course literally turning into a `projects` row. `create_class`/
`update_class` (`routers/schedule.py`) both take the new `project_uid`
form field and apply it as a separate call after `upsert_schedule_class`,
mirroring the same "upsert never touches project_uid, only the explicit
setter does" pattern used everywhere else -- confirmed via
`TestScheduleClassLinking::test_class_appears_in_project_scope_once_linked`
that a linked course actually surfaces on the project's detail page's
Courses section (built in Phase 3, unreachable until this phase).

Verified live end-to-end again: rendered every affected manage page with
zero projects (dropdown correctly absent) and with one present (dropdown
correctly shown and listing it), then linked the default task list to a
real project through the actual HTTP form (not a direct function call)
and confirmed the project detail page picked it up.

**Update 2026-08-01, Phase 5: grouping/archiving audit + a real gap
closed.** Tag groups (Phase 2) and project groups (Phase 3) already had
full CRUD; what was missing was actually *using* group membership in the
manage pages' display -- both listed items in one flat alphabetical list
regardless of group. `tags_manage.html`/`projects_manage.html` now render
grouped section headers (Jinja `groupby` over a `group_name` the router
attaches to each row), with ungrouped items clustered at the end via a
`"~ Ungrouped"` sentinel that sorts after any real group name. Archiving
needed no further work -- Phase 3 already built the full retire/restore
UI for projects; there's nothing to archive for a tag (a tag with zero
usage just... has zero usage, no separate archived state was ever
requested or would mean anything different).

**Update 2026-08-01, Phase 6: habit tracking.** New, self-contained
feature -- its own nav tab (`/habits`), `routers/habits.py`, and two new
local-only tables (`habits`, `habit_entries`; see db.py's table comments).
No CalDAV/CardDAV involvement at all, same bucket as projects/tags/
checklists.

- **Heatmap** (`_habit_heatmap.html`, shared by the list and detail
  pages) -- a GitHub-style calendar grid, server-rendered as plain HTML
  (a flex grid of week-columns, each a stack of 7 day cells), not canvas
  or a JS charting library. Every non-future day is its own tiny `<form>`
  posting to `/habits/{uid}/entries/{date}/toggle` -- clicking a day is
  one no-JS request. Color intensity (`_heatmap_weeks`, 5 levels) scales
  against the habit's `target_per_day`, but hitting the target isn't
  required for a day to "count" -- see streaks below.
- **Easy input** -- click any past or present day to toggle it on/off.
  `toggle_habit_entry` (db.py) removes the row entirely when toggling
  off, not just zeroing it, so a cleared day goes back to genuine
  "no data," not a visually-empty-but-still-present entry.
- **Backfill ("add past data")**, explicitly requested -- a dedicated
  form on the detail page (date + exact value + optional note),
  independent of the heatmap's 0/1 toggle. `POST /habits/{uid}/entries`
  upserts the one row for that date (`UNIQUE(habit_uid, date)`), so
  correcting an already-logged day and backfilling a new one are the same
  code path, and a value of 0 deletes the entry rather than leaving a
  meaningless zero-row behind.
- **Streaks** (`_streaks`) -- current and longest, counting any day with
  a logged value > 0 as done (the daily target only colors the heatmap,
  it isn't a pass/fail gate -- reading 8/10 pages shouldn't zero your
  streak). Current streak tolerates *today* not being logged yet without
  breaking, but a fully skipped calendar day does break it.
- **Customization + linking**, consistent with projects/tags: color, an
  emoji/glyph icon, tags (auto-registered on save, same as tasks/events/
  contacts/`ensure_tags_registered`), and an optional project link (e.g.
  a "Study 1h/day" habit under a University project) via the same
  `project_uid` pattern as every other list in this app.
- **Archive, don't delete on the list view** -- same convention as
  projects; a genuine delete (habit + its full entry history) is a
  separate, explicit, confirmed action, since a habit's history has no
  meaning independent of the habit the way a task list's tasks do.

Verified live end-to-end: created a habit through the real form, rendered
both the list (mini heatmap) and detail (full heatmap) pages, toggled
today on and off through the actual endpoint, backfilled a date 45 days
in the past with an exact value and a note through the real form,
confirmed its tag auto-registered, archived it (disappears from the
active list), then deleted it and confirmed cleanup.

**Update 2026-08-01, Phase 7: custom databases with formulas
(Notion-like).** New nav tab (`/databases`), `routers/databases.py`, and
a small purpose-built formula language (`formula_engine.py`). Local-only,
same bucket as everything else in this section -- no CalDAV/CardDAV
concept for a user-defined table.

- **Schema**: two tables, not three -- `databases` + `database_columns`
  define the table and its column types/formulas; `database_rows` stores
  each row's non-formula values as one JSON blob (`values_json`,
  column_uid -> raw value) rather than a normalized cells table. A
  formula column's value is **never stored**, computed fresh on every
  read -- same "derived, never stored" rule this app already applies to
  task progress and project progress.
- **Column types**: text, number, date, select (fixed choice list),
  checkbox, formula.
- **Formula language** (`formula_engine.py`) -- deliberately scoped, not
  a general expression language: arithmetic (`+ - * /`, parens, unary
  minus), column references (`grade` or `[Column With Spaces]`), and a
  fixed function set: `SUM`, `AVG`, `MIN`, `MAX`, `COUNT`, `WEIGHTAVG`.
  No `IF`/comparisons/booleans/user-defined functions -- if a real need
  for those shows up later that's a deliberate grammar extension, not
  something guessed at up front. Two evaluation contexts share the same
  grammar: a **row formula** (e.g. `grade * weight`) resolves bare
  identifiers against that row's own values; a **summary formula** (one
  optional footer value per column, e.g. `WEIGHTAVG(grade, weight)` or
  `AVG(grade)`) has no single row, so only aggregate functions are valid
  there. Every failure mode (unknown column, division by zero, empty
  aggregate, malformed syntax) returns `(None, error_message)` rather
  than raising, rendered as a `#ERROR` chip with the reason in its title
  attribute -- one bad formula can't take the whole page down. 33 unit
  tests (`tests/test_formula_engine.py`), including the specific driving
  case (weighted grade averages) checked against a manually-computed
  expected value.
- **The grid** (`database_detail.html`) -- server-rendered HTML, no JS:
  every editable cell is its own tiny form that submits on change (same
  no-JS convention as the habit heatmap's day toggles and every other
  inline-edit surface in this app), type-appropriate input per column
  (checkbox/select/date/number/text). A column-management panel below
  the grid handles add/edit/delete/reorder (swap-with-neighbor, same
  primitive idea as a fractional position key elsewhere in this app).
- **Customization + linking**, consistent with every other Phase
  1-7 entity: color, icon, tags (auto-registered), optional project link
  -- e.g. "Databases 101 Grades" living under a University project
  alongside its task list and schedule class.
- Archive (hide, keep data) vs. delete (drops the database, its columns,
  and its rows) -- same convention as projects/habits.

Verified live end-to-end against the actual grade-tracking scenario the
feature request named: created a database, added `grade`/`weight` number
columns plus a `Weighted` formula column (`grade * weight`) and a
`WEIGHTAVG(grade, weight)` summary formula on the grade column, added
three rows through the real forms (Midterm 85/30, Final 90/50, Homework
70/20), and confirmed both the per-row formula (2550 for Midterm) and the
weighted-average summary (84.5) rendered correctly on the actual page --
not just asserted against the engine in isolation.

**Update 2026-08-01, Phase 8: a customizable, extensible, widget-based
dashboard.** `/` was a placeholder ("Nothing here yet") until now --
genuinely new, not a rework. `routers/dashboard.py`, `dashboard_widgets`
table (local-only, per-device layout, same bucket as everything else in
this section).

- **Widget registry** (`WIDGET_TYPES`) -- "extensible" isn't just an
  adjective here: a widget type is a dict entry (label, partial template,
  render function, which of tasks/events it reads) plus a render function
  that returns a plain dict. Adding a new widget type later means adding
  one registry entry, not touching add/edit/reorder/delete or any
  existing widget. Proved this isn't just three hardcoded branches by
  shipping a fourth, unrequested type (`overdue_tasks`) through the exact
  same mechanism as the three named in the request.
- **Three widget types built as specified**: Today's Agenda (overdue +
  due-today tasks, today's events), Weekly Overview (next 7 days,
  grouped by day in a 7-column grid), Upcoming Events (next N events
  chronologically, N itself configurable). All four types share one
  filter vocabulary -- project, tags (any-match), specific task lists,
  specific calendars -- applied uniformly by `_passes_filters`, which
  resolves a task/event's project through the list/calendar it belongs
  to (there's no per-task project field; a task's project is always
  inherited from its list, same as the project detail page's aggregation
  in Phase 3).
- **Customizable**: every widget has a "Filters" panel (title override +
  the four filters) and move-up/move-down/remove controls, right on the
  dashboard, no separate settings page. Add-widget form at the bottom
  covers every registered type generically -- it doesn't need updating
  when a new widget type is added, since it iterates `WIDGET_TYPES`.
- **Starts populated, not blank** -- a fresh install seeds three
  unfiltered default widgets (Today's Agenda / Weekly Overview / Upcoming
  Events) the first time `/` loads, same "ensure_default_*, no-op once
  anything exists" convention as `ensure_default_calendar`/
  `ensure_default_task_list`/`ensure_default_addressbook`. "Customizable"
  means reshaping it from a working default, not starting from nothing.
- All-JS-free, consistent with the rest of this app: every widget's own
  interactive elements (mark task done, move/delete a widget) are plain
  forms; the "Filters" and "Add widget" panels are native `<details>`
  disclosure elements.

Verified live end-to-end: confirmed the three seeded default widgets
render on a fresh dashboard, created a real project + task list + task
due today through the actual forms and confirmed it appeared in the
unfiltered Today's Agenda widget, added a second Today's Agenda widget
filtered to a *different* project through the real form and confirmed
the task correctly does NOT appear in that one, and reordered a widget
via the real move endpoint.

(Correction: this rework is 11 phases total, not 8 as an earlier note
here claimed -- task-view rework, calendar quick-create, and a Timeline
view port were always phases 9-11, just planned before habits/databases/
dashboard existed and renumbered when those were inserted. See below.)

**Update 2026-08-01, Phase 9: task view rework.** Three independent
changes to `routers/tasks.py`/`tasks_list.html`, all about how the Table
view filters and displays tasks -- no schema changes, nothing new to
sync, just query/render logic.

- **Completed tasks stay visible, not hidden.** Previously the default
  view (`all_open`) excluded done/archived tasks outright. Now every
  view -- including the new default -- keeps them, but visually
  separates them: `list_tasks` splits the filtered set into `open_tasks`
  and `completed_tasks`, and the template renders them as two `<tbody>`
  groups with a "Completed (N)" divider row between them (only shown when
  both groups are non-empty -- a single-status filter like
  `status_filter=done` has nothing to separate from). Completed rows are
  additionally dimmed and strikethrough (`.task-row-completed`) so the
  separation reads at a glance, not just via table position.
- **Priority/status/date are three independent filters, not one preset
  list.** The old `filter` param (`all_open` / `today` / `overdue` /
  `high_priority` / `waiting` / `done` / `archived` / `all`) was a fixed
  set of preset *combinations* -- there was no way to ask for "this
  week's high-priority waiting tasks" without a new preset. Replaced with
  `date_filter` (all/today/this_week/overdue), `status_filter` (all +
  every real status), and `priority_filter` (all/1-4), each its own
  `<select>`, ANDed together in `list_tasks`. `this_week` is genuinely
  new -- the old preset list never had a week view at all, only
  today/overdue.
- **Task start date is always today.** Not a form field on task
  *creation* at all anymore (`create_task` dropped the `start_at`
  parameter entirely and hardcodes `date.today().isoformat()` server-side
  regardless of what's posted) -- `task_form.html`'s Start date input
  only appears once a task already exists, for pushing it out later. A
  brand-new task simply starts today; that's not a choice to make at
  creation time.

Verified live end-to-end: created a task with a deliberately wrong
`start_at` in the POST body and confirmed the server ignored it and used
today's date anyway; marked it done and confirmed it stayed visible (with
the divider) in the default view, the Today view, and the This-week view;
confirmed a `this_week` + `status=active` combination correctly excludes
it while `this_week` + `status=done` includes it; confirmed the new-task
form has no Start date field at all while the edit form still does.

**Update 2026-08-01, Phase 10: click-and-hold drag-to-create in the
month view.** The one calendar view with zero create-by-dragging
interaction until now -- Week/Day already had it
(`.calendar-create-col` in `static/calendar.js`), Schedule has its own
equivalent (`schedule_grid.js`), but Month only ever offered a static day
list you had to click through to `/calendar/day/{date}` to add anything.

- **`static/calendar_month.js`** -- new file, since Month has no time
  axis at all (a "drag" here spans whole *days*, not hours): press down
  on empty space in a day cell, drag across other day cells in either
  direction, release to open the New Event form prefilled as an all-day
  event spanning the pressed-to-released date range. A press-and-release
  on the same cell with no movement is treated as a same-day quick-add
  rather than requiring a deliberate drag for the common "just add
  something today" case. Same "only start when the event target is the
  bare cell, not a child link" rule `.calendar-create-col`'s handler
  already uses, so the day-number link and existing event/task chips
  inside a cell keep working normally.
- **`GET /events/new?date=X&end_date=Y`** (`routers/calendar.py`) -- new
  prefill path, all-day, spanning midnight-to-midnight
  (`{date}T00:00` .. `{end_date}T23:59`), auto-checking the existing "All
  day" checkbox. Deliberately separate from the pre-existing `start_time`/
  `end_time` prefill path (Week/Day's same-day, specific-time drag) --
  that one still takes priority when present and is unaffected by this
  change, verified with a regression test.

Verified live end-to-end: confirmed the month page actually serves the
new script and has `data-date`-tagged day cells, hit the new prefill
endpoint directly and confirmed the all-day checkbox renders checked with
the correct date range, created a real 3-day all-day event through the
actual form and confirmed it stored as `all_day=True` spanning the right
dates and rendered on the month grid across that span, and confirmed the
older Week/Day drag-to-create prefill path still works exactly as before.

**Update 2026-08-01, Phase 11: Timeline (Gantt) view, ported from
desktop.** The last item in the original 11-phase plan. Read desktop's
actual source (`desktop/src/features/tasks/timeline_view.py`'s
`TimelineCanvas`, `desktop/src/core/utils/interval_packing.py`) rather
than working from the prose description alone, per the explicit
instruction to implement this verbatim, not incompletely. New nav
segment (`/tasks/timeline`, alongside Table/Board), `timeline_layout.py`
(the ported algorithms), `routers/timeline.py`, `static/timeline.js`,
`tasks_timeline.html`.

- **`timeline_layout.py::pack_intervals`** -- a byte-for-byte port of
  desktop's `interval_packing.py::pack_intervals` (same overlap-cluster
  sweep, same greedy lowest-free-lane assignment, same `preferred`-lane
  stability behavior). 30 tests, including the specific regression
  desktop's own docstring documents (an item with zero real conflicts
  must not bounce to a new lane purely from sort-order changes when its
  previous lane is still free).
- **`assign_swimlanes`** -- ported from `_assign_swimlanes`: bin-packs
  each group's tasks into the minimum rows so none of that group's own
  tasks visually overlap, stacks groups vertically so different groups
  never share a row, and lets a task's explicit manual placement
  (`timeline_lane`) win over the computed layout, unclamped -- "deliberately
  leaving gaps for visual grouping" is the point, same as desktop.
  **One forced adaptation, not a design choice**: desktop groups by
  `parent_id` (a task's direct project, in its object graph). This app
  has no such field -- a task belongs to a task list, and a list
  optionally belongs to a project (Phase 3/4). Swimlanes here group by
  **task list**, not project directly; a list linked to a project is
  exactly the "whole list belongs to a project" mechanism the rest of
  this rework already established, so this is the faithful equivalent,
  not a reduction.
- **Calendar-aligned window** (`month_bounds`/`compute_range`) -- verbatim
  port of `_month_bounds`/`_compute_range`: previous/current/next
  calendar month (three months), extended to cover any task outside it.
  Desktop's Day/Month zoom were both tried and removed at various points
  in its history, leaving one zoom level ("Week zoom," day-granularity
  bars); this port has exactly that one level too, for the same reason
  -- there's nothing left to toggle.
- **Bar geometry, header, gutter** -- exclusive one-past-due-date bar
  width, every day gridlined and labeled, a two-row header ("Week NN"
  spanning that week's width + a bare day number per day, the exact
  layout desktop settled on after two documented header-overlap bugs),
  and a gutter column showing each list's name on its block's first row
  and "Row N" (or a custom override) below it.
- **Drag interactions** (`static/timeline.js`) -- move (day-snapped,
  live, not just on release), resize either edge (day-snapped, with the
  narrow-bar midpoint hit-test split and the single-day/no-start-date
  start_at-freeze-on-drag-begin fix, both ported verbatim from desktop's
  documented bug history, not just the current behavior), a vertical drag
  to manually pick a row within the task's own list (computed the same
  way desktop's `mouseReleaseEvent` does -- original local lane + row
  delta, clamped -- never by hit-testing whatever's visually under the
  cursor), click-and-drag on empty grid space to create a task spanning
  that exact date range and row, double-click a gutter label (including
  a list's own row 0) to rename it, and a draggable gutter/grid boundary
  (persisted per-device via localStorage, a pure display preference).
- **One deliberate, documented scope reduction**: no custom right-click
  context menu (status-set/duplicate/delete). A single click opens a task
  via this app's existing `data-modal` convention (every other object
  card in this app already opens on single click, not double-click the
  way desktop's Qt canvas requires) -- covers the primary navigation
  need the context menu's "Open" action served; the menu's other actions
  are already reachable from the task's own detail view.

Verified live end-to-end -- and this phase caught a real bug the hard
way: `/tasks/timeline` initially 404'd into `task_detail.html`'s "not
found" page, because `tasks.router`'s catch-all `GET /tasks/{uid}` was
registered first and silently matched `uid="timeline"` before
`timeline.router`'s own literal route ever got a chance. Fixed by
registering `timeline.router` before `tasks.router` in `main.py`, with a
comment explaining why the order is load-bearing. After that fix:
confirmed a real task renders as a bar, moved it via the reschedule
endpoint, resized it, manually placed it in a specific row, click-created
a brand-new task spanning an exact date range and row, renamed a gutter
row and confirmed the custom label rendered, and confirmed an unrelated
ordinary task edit (through the normal edit form) does not clobber the
manual row placement -- plus confirmed `/tasks`, `/tasks/board`, and
`/tasks/{uid}` all still work correctly after the routing fix.

This completes all 11 phases of the projects/tags rework.

## Quick start

```bash
# from webapp/
./run.sh
# -> http://127.0.0.1:8000
```

That's the one-command path: it runs `uv sync`, starts the dev Radicale
instance, then the web app, and stops Radicale on Ctrl+C. A throwaway dev
Radicale config lives in `.dev/radicale/` -- do not reuse its plaintext
htpasswd auth for anything beyond localhost (see "Deploying for real"
below).

To run the two pieces in separate terminals instead (e.g. for iterating on
one without restarting the other):

```bash
# terminal 1: Radicale
uv run python -m radicale --config .dev/radicale/config \
  --storage-filesystem_folder=.dev/radicale/collections \
  --auth-htpasswd_filename=.dev/radicale/users

# terminal 2: the web app
export CC_RADICALE_URL="http://127.0.0.1:5232/devuser/"
export CC_RADICALE_USER="devuser"
export CC_RADICALE_PASSWORD="devpass"
uv run python -m src.main
```

## Architecture

Radicale is the source of truth. This app's SQLite database is a
disposable, rebuildable cache (same relationship the desktop app's SQLite
cache has to its file tree) -- reads hit the cache, writes go to Radicale
first and then update the cache. A background thread does a full-refresh
pull from Radicale periodically, to pick up changes made by *other*
clients (desktop's sync bridge, a phone's native Calendar/Contacts app).

```
Browser -- HTML forms --> FastAPI --> SQLite cache (reads)
                              |
                              +--> CalDavBridge --> Radicale
                                   (writes, + periodic background pull)
```

`caldav_bridge.py` uses the `caldav` library for events/tasks (VEVENT/
VTODO). It hand-rolls the CardDAV side (contacts) with `httpx` -- the
`caldav` PyPI package doesn't implement CardDAV at all, confirmed by
inspecting its API before writing this.

## Schedule

A repeating class list -- day/time, odd/even ISO-week parity, semester
start/end, holiday exception ranges -- for the "repeats endlessly between
dates, excepting certain dates" pattern (university/school timetables).
Same odd/even-week convention as the reference Uni Schedule app this was
modeled on.

`schedule_classes`/`schedule_holidays`/`schedule_settings` (db.py) are
**local-only** -- there's no standard CalDAV object type for "a recurring
class with parity and credits," so this app's SQLite is the authoritative
structured store, edited under the Schedule tab (Classes / Holidays /
Settings). Each class is additionally mirrored **one-way** into a plain
VEVENT (RRULE + computed EXDATE for holiday exceptions) through the normal
event bridge, so it shows up in the Calendar tab and any other CalDAV
client (including your phone). That mirrored event is a courtesy export --
editing it elsewhere doesn't flow back into the class's structured fields;
edit the class itself for that. Professor/room/credits/type/acronym have
no standard iCalendar slot, so they're folded into the mirrored event's
`DESCRIPTION` (room also maps to the standard `LOCATION` field).

Classes only generate calendar occurrences once both semester dates are
set under Schedule -> Settings; changing settings or holidays regenerates
every class's mirrored event.

## Calendar

Month / Week / Day / Agenda, switchable via the sub-nav under the Calendar
tab -- feature parity with desktop's Calendar module (`features/calendar.md`):

- **Week/Day** are real hour-by-hour time grids (`grid_layout.py`), not
  lists -- overlapping events split into side-by-side lanes (same
  greedy-packing idea as desktop's `_pack_overlaps`), all-day events sit in
  a strip above the grid.
- **Drag-to-move and drag-to-resize** directly on the Week/Day grid
  (`static/calendar.js`), snapping to 15-minute increments live during the
  drag, saved via `POST /events/{uid}/reschedule` on release. A short drag
  (a few px) is treated as a click and opens the edit form instead.
- **Recurrence is expanded in every view**, not just shown on the anchor
  date -- `recurrence_expand.py` uses the `recurring_ical_events` library
  (already a transitive dependency of `caldav`) rather than hand-rolling
  RFC 5545 expansion.
- **Multi-calendar**: named, color-coded calendars, each a real separate
  CalDAV collection (`routers/calendars.py`, `/calendars` to manage).
  Visibility per calendar is a cookie (per-device, not synced -- same idea
  as desktop's per-device calendar visibility toggle), filtering server-side
  before any view renders.

## Configuration (env vars)

| Var | Default | Purpose |
|---|---|---|
| `CC_RADICALE_URL` | `http://127.0.0.1:5232/devuser/` | Radicale principal URL |
| `CC_RADICALE_USER` | `devuser` | Radicale username |
| `CC_RADICALE_PASSWORD` | `devpass` | Radicale password |
| `CC_CALENDAR_COLLECTION` | `calendar` | Events collection name |
| `CC_TASKS_COLLECTION` | `tasks` | Tasks (VTODO) collection name |
| `CC_CONTACTS_COLLECTION` | `contacts` | Addressbook collection name |
| `CC_DB_PATH` | `~/.command_center_web/cache.sqlite` | SQLite cache path |
| `CC_SYNC_INTERVAL` | `60` | Background pull interval, seconds |

## Known gaps

- **No auth on this app itself.** Assumes it's reachable only over a
  trusted network (e.g. Tailscale), matching the earlier decision to avoid
  public exposure. Add auth before that assumption changes.
- **Full-refresh sync, not delta sync.** Every background poll re-lists
  everything from Radicale. Fine at personal-scale item counts; CalDAV's
  `sync-collection` REPORT (true delta sync) is a reasonable upgrade if
  this ever becomes slow.
- **Schedule's weekly grid is a static table, not drag/resize.** The
  reference app it's modeled on lets you drag-create and drag-resize
  classes directly on the grid; this one shows the same layout but you
  add/edit through the form. Click a class in the grid to edit it.
- **No PWA manifest/service worker yet.** Works fine as a mobile browser
  page; isn't installable to a home screen or usable offline yet.

## Deploying for real

Not covered yet: running Radicale with real (non-plaintext) auth, putting
both Radicale and this app behind Tailscale, and pointing desktop's
CalDAV/CardDAV bridge daemon (see `../desktop/src/core/caldav/`) at the
same Radicale instance so desktop and this app share one dataset. That's
the next piece of work, not this one.
