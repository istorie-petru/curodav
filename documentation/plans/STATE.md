# State

Single source of truth for "where are we right now." Read this file — and
only this file — at the start of a session working toward 2.0. Don't re-read
`roadmap.md` / `open-priority.md` / `open.md` in full; they're expanded specs
for reference, not session-start context. Update this file at the end of every
session, right before the final commit of that session.

Trimmed 2026-09-03: "Right now" had grown to ~4,400 lines of accumulated
session-by-session history instead of a current-position summary. Entries
older than the day of the trim were deleted outright (direct request, not
archived elsewhere) — full detail for anything cut is still recoverable via
`git log -p -- documentation/plans/STATE.md` (or `plans/STATE.md` in commits
before the docs move) if a past decision needs re-litigating. Keep "Right
now" short going forward: this file's whole value is being cheap to read at
session start.

## Right now

- **Shipped:** 2026-09-12 -- next item off `audit-fixes-2.1.md` in doc
  order: "Hollydays should add support for only day hollydays, withot the
  year. For example religious national holydays that are the same each
  time each year." A year-agnostic holiday is now stored as `--MM-DD`
  (`db.is_year_agnostic_holiday_date`/`db.parse_holiday_date`) -- the same
  vCard-derived convention Contacts' year-less Birthday field already used
  (`parse_contact_birthday`), reused rather than adding a schema column:
  `schedule_holidays.date_from`/`date_to` stay plain TEXT holding an
  alternate string shape. `holiday_edit_modal.html` gained a "Repeats every
  year" checkbox (`year_agnostic`); the shared date picker itself needed no
  change -- Start/End still pick a real calendar date so month+day are easy
  to click, the checkbox alone decides whether `create_holiday`/
  `update_holiday` (routers/settings.py) keep or discard the year via
  `db.parse_holiday_date`. Editing an existing year-agnostic holiday feeds
  the picker a placeholder-year stand-in (`db.holiday_date_picker_value`,
  year 2000, leap-safe) purely so it has a real date to highlight --
  nothing about that placeholder year is what gets saved back, the
  checkbox is. `recurrence_expand.is_excluded_by_policy` is the one place
  the actual "is this holiday" matching logic lives (both
  `expand_events`/Calendar's Month/Week/4-Week/Day/Dashboard-agenda and
  `habit_heatmap.excluded_dates_in_range`/streaks route through it, so
  neither needed any change of their own) -- it now compares `(month,
  day)` instead of the full date whenever a holiday row is year-agnostic,
  including a range that wraps the year boundary (e.g. a Dec 30 -> Jan 2
  New Year break). `settings_holidays.html`'s Date Range column uses a new
  `holiday_date` Jinja filter (deps.py) instead of the plain `relative_date`
  one, since `relative_date`'s `date.fromisoformat` can't parse `--MM-DD`
  (it would otherwise silently degrade to printing the raw stored string) --
  `holiday_date` delegates to `relative_date` for an ordinary full-date
  holiday and to `db.format_holiday_date` ("25 Dec", no year) for a
  year-agnostic one.

  **Tests**: `test_holiday_calendars.py` gained
  `TestYearAgnosticHolidayDates` (the db.py helpers: parse/format/
  round-trip, Feb 29 leap-year allowance, rejecting a yearless value when
  the checkbox isn't set). `test_recurrence_expand.py` gained
  `TestYearAgnosticHolidayPolicy` (single-day match across years, a
  within-month range, a year-boundary-wrapping range, and an end-to-end
  `expand_events` case). `test_settings_holidays.py` gained
  `TestHolidayEditModalYearAgnostic` (checkbox state on new vs. year-
  agnostic vs. ordinary edit) plus create/update/list coverage (yearless
  storage, invalid-date 400, re-saving a year-agnostic holiday unchanged
  stays yearless, list row shows "25 Dec" not the raw `--12-25`). Existing
  create_holiday/update_holiday direct-call tests needed an explicit
  `year_agnostic=""` added (same reason `exclude_saturday`/
  `exclude_sunday` tests always pass every Form field explicitly --
  FastAPI's `Form(...)` default sentinel is truthy when a router is called
  directly in a test rather than through real request parsing, so omitting
  a boolean-ish Form field in a direct call doesn't behave like an
  unchecked checkbox the way it does over real HTTP). Full suite run in 4
  file-list batches (still one call per batch -- this sandbox can't finish
  an un-split run inside the tool's 45s call limit): **2180 passed, 0
  failed** -- no flaky time-of-day-boundary failures this run.

  Next slice: whatever's next in `audit-fixes-2.1.md` doc order after
  this -- "Holiday bug, for some reason the user is not allowed to add
  more holidays to the same calendar, and it defaults to Default
  calendar."

- **Shipped:** 2026-09-11 -- next item off `audit-fixes-2.1.md` in doc
  order: "While adding a hollday, in the specific modal window, after
  setting either the start and end date, the other one should be
  automatically set the same. After the initial set both can be changed
  without any sync between them." `holiday_edit_modal.html`'s Start/End
  are two independent `_datetime_picker.html` date-mode instances with no
  awareness of each other -- new `static/holiday_date_sync.js` listens
  for the `change` event each already fires on pick (datetime_picker.js's
  existing commitChange()) and, only when the *other* field is still
  empty, fills it with the same date. `datetime_picker.js` gained a small
  `dtpSetDate(key)` hook on each date-mode `.dtp` container's element (set
  in `enhance()`, mirrors a real pick's hidden-input+trigger-label update
  without dispatching another `change` -- no risk of the two listeners
  looping) so the sync script can fill the *other* picker's own instance,
  not just its raw hidden input. Wired into `base.html` (global `<script
  defer>`, same as `event_format_toggle.js`) and `modal.js`'s
  `wireContent()` (`CCHolidayDateSync.init(body)`) -- holiday_edit_modal
  is modal-only, so no extra_scripts block, same reasoning as every other
  modal-injected field-linking script. Not added to `sw.js`'s
  SHELL_ASSETS (following `label_role_picker.js`/`label_form_picker.js`'s
  precedent, not `event_format_toggle.js`'s -- this codebase is
  inconsistent about which globally-loaded small feature scripts get
  precached, per v97/v98's own admission; datetime_picker.js's change
  also needs no bump, same "page-specific, not itself a SHELL_ASSETS
  entry" reasoning as its v49 entry).

  **Tests**: new `test_holiday_date_sync.py` -- markup sanity (both date
  fields render in one `#holiday-form`, `data-dtp-mode="date"`), the new
  script's existence/API surface, the empty-field gate that keeps "both
  can be changed without sync" true once both are set, and that
  `base.html`/`modal.js` load/reinit it. Full suite run in 4 sequential
  batches (still one call per batch -- this sandbox can't finish an
  un-split run inside the tool's 45s call limit): **2157 passed, 0
  failed** -- the 4 time-of-day-boundary failures noted in the last few
  sessions didn't reproduce this time (wall-clock dependent, not
  something this slice touched).

  Next slice: whatever's next in `audit-fixes-2.1.md` doc order after
  this -- "Hollydays should add support for only day hollydays, withot
  the year" (year-agnostic recurring holidays, e.g. fixed-date religious
  holidays).

- **Shipped:** 2026-09-11 -- next item off `audit-fixes-2.1.md` in doc
  order: "For the settings, the page-header-narrow-back, it should be on
  the left most, not right most." The crumbs-driven back arrow
  (`_page_header_narrow.html`'s `page_header_narrow()` macro) was sitting
  inside `.page-header-narrow-actions`, the header's right-aligned slot
  (after the spacer) -- moved it to the header's actual first child,
  before the icon+title, so it's leftmost regardless of whether a page
  also has real actions-slot content. `.page-header-narrow-actions`
  itself (Calendar's prev/next/subnav, etc.) is untouched, still
  right-aligned, and now only renders when a page passes a `{% call %}`
  block -- the old `(crumbs is defined and crumbs) or caller` condition
  guarding it is just `caller` now, since crumbs no longer render inside
  it. `style.css` gained a small `.page-header-narrow-back` rule
  (z-index:1 like the other header children, plus the has-banner
  frosted-chip treatment `.icon-btn`s in the old actions slot had) --
  none of Settings' existing pages needed a template change, only the
  shared macro/CSS.

  **Tests**: `test_page_header_narrow.py` gained
  `TestNarrowHeaderBackPosition` (two tests: back arrow renders before
  `.page-header-narrow-icon`/`-title`, and renders even when a page has
  no `.page-header-narrow-actions` at all -- proving it's no longer
  actions-slot-dependent). Full suite run in 4 sequential batches (this
  sandbox couldn't complete a single un-split run within the tool's 45s
  call limit today -- unrelated to this change): **2146 passed**, same 4
  pre-existing time-of-day-boundary failures as prior sessions
  (`test_dashboard_router.py`'s `TestAgendaWidgetAllUpcoming` +
  `test_project_detail.py`'s 3 agenda/deadline "due today" tests),
  unchanged and not touched by this slice.

  Next slice: whatever's next in `audit-fixes-2.1.md` doc order after
  this -- the holiday start/end-date auto-sync item ("While adding a
  hollday... after setting either the start and end date, the other one
  should be automatically set the same").

- **Shipped:** 2026-09-11 -- same session, direct "continue": the deferred
  second half of the previous slice's doc line -- "The Restart app should
  also be moved to the Data & Maintenance and should be able to be called
  after editing important enviroment data for the app, appearing in the
  form of a toast." Moved the "Restart app" card from Settings > Your
  Profile into Data & Maintenance's "Maintenance & cleanup" card (first
  row, `settings_data_maintenance.html`) -- same `/settings/restart`
  route, same `data-confirm-sheet`, same `restart_available` gate (now
  built in `settings_data_maintenance`'s own context instead of
  `settings_your_profile`'s).

  The "appearing in the form of a toast" half: Data & Maintenance already
  had a note-query-param-becomes-a-floating-toast mechanism
  (`data_maintenance.js`, see that page's own header comment) that Your
  Profile never had -- rather than build a second toast pipeline, made the
  routes that actually NEED a restart redirect to Data & Maintenance
  instead of back to Your Profile, so the existing mechanism does the
  work: `account_settings` now redirects to `/settings/data-maintenance`
  whenever the save is env-managed (always needs a restart) OR a new
  password/Radicale URL was saved to app_meta (`restart_relevant`, a new
  local in that function) -- a username-only app_meta change still stays
  on Your Profile since the session is re-minted immediately and nothing
  needs restarting. `restart_app` itself (both its success and
  no-op-outside-production error path) now also redirects to
  `/settings/data-maintenance` instead of `/settings/your-profile`.

  **Tests**: `test_settings_login_password.py` gained three new
  `TestAccountSettingsAppMetaPath` tests covering the `restart_relevant`
  branch (username-only stays on Your Profile; new password or Radicale
  URL alone both redirect to Data & Maintenance), one new assertion on the
  existing env-path test (env saves always redirect to Data &
  Maintenance), and `TestRestartApp`'s two existing tests gained a
  redirect-target assertion. `test_data_health.py` gained
  `test_restart_app_present_only_in_production`/
  `test_restart_app_shown_in_production` on
  `TestDataMaintenanceRedesign2026_08_26`. `test_phase8_settings_hub.py`'s
  `TestSettingsYourProfile` gained `test_no_longer_has_restart_app`. Full
  suite run in the same 4-parallel-batch pattern: **2144 passed**, same 4
  pre-existing time-of-day-boundary failures as the last two sessions
  (unchanged, not re-verified against HEAD again -- nothing this slice
  touched plausibly affects an "earlier today" date/time boundary check).

  This closes out both halves of the "move password/username/Radicale/
  Restart app off General" doc paragraph -- next slice starts fresh on
  whatever's next in `audit-fixes-2.1.md` doc order (the
  page-header-narrow-back alignment item, unless something above it was
  missed).

- **Shipped:** 2026-09-11 -- next item off `audit-fixes-2.1.md` in doc
  order (first half only -- see note at the end): "I would like to move
  the password, username, radicale url etc, settings from general to a new
  page named Your Profile. It should include the Profile Picture and
  Nickname (current Your Name, used in greeting)." New hub category/page,
  `/settings/your-profile` (`settings_your_profile.html`, icon
  `user-check`, between General and Appearance in `HUB_CATEGORIES`) --
  holds the Profile picture upload/remove forms, the nickname field
  (relabeled from "Your name" to "Nickname" per the direct request's own
  wording, same `/settings/display-name` route/behavior), and the Account
  card (username/current+new password/Radicale URL, `/settings/account`)
  moved verbatim from `settings_general.html`. Restart app came along too
  (not left orphaned on General with no Account card to apply) -- the
  actual "move Restart app to Data & Maintenance, trigger it as a toast
  after an env-data edit" half of the same doc line is intentionally
  deferred to a follow-up slice (see below), since bundling both would
  have made this one slice cover two unrelated relocations landing in two
  different places.

  General (`settings_general.html`) now holds only the format/display
  preferences that aren't about who the user IS (week start, 4-week
  position, recurrence/habit terminology, time format, hide-sleep-hours).
  Every route these moved fields post to is unchanged (same URLs, same
  handler functions in `routers/settings.py`) -- only the GET page they
  live on and the redirect target on save moved: `account_settings`,
  `restart_app`, `set_display_name`, `set_profile_photo`, and
  `remove_profile_photo` now all redirect to `/settings/your-profile`
  instead of `/settings/general`. `settings_data_maintenance.html`'s
  read-only Radicale card, which used to point at "Settings > General" for
  the actual connection fields, now points at "Settings > Your Profile."

  **Tests**: updated in place rather than duplicated --
  `test_phase8_settings_hub.py`'s old `TestSettingsGeneral` display-name/
  account assertions split into a trimmed `TestSettingsGeneral` (asserts
  those fields are now ABSENT from General) plus a new
  `TestSettingsYourProfile` class covering the same ground against the new
  page; its `test_set_display_name_route_redirects_to_general` became
  `test_set_display_name_route_redirects_to_your_profile` (redirect target
  updated). `test_dashboard_usability_rework.py`'s
  `test_settings_general_passes_display_name` renamed/repointed to
  `test_settings_your_profile_passes_display_name`.
  `test_settings_radicale.py`'s href assertion updated to
  `/settings/your-profile`. Full suite run in the same 4-parallel-batch
  pattern as last session (single bash call, background `&`/`wait`):
  **2138 passed**, same 4 pre-existing time-of-day-boundary failures as
  last session (confirmed unrelated then, unchanged now -- not re-verified
  against HEAD again since nothing this slice touched could plausibly
  affect them).

  **Next slice** (per `audit-fixes-2.1.md`, doc order -- second half of
  the same paragraph, deferred from this session): move "Restart app" from
  Settings > Your Profile into Data & Maintenance, and make it triggerable
  as a toast after editing "important environment data" (the Account
  card's env-file path is the obvious trigger -- `account_settings`
  already returns a note telling the user to click Restart when
  `env_managed`; check whether that note itself should become the toast
  trigger, or whether Data & Maintenance needs its own always-visible
  Restart control regardless of what page any given env-data edit happened
  on).

- **Shipped:** 2026-09-11 -- next item off `audit-fixes-2.1.md` in doc
  order -- "the Purge Completed Tasks should sit in the context menu of
  Database (as purge completed). The reset home layout button should be
  removed, because in edit mode an exact button already exists."
  settings_data_maintenance.html's Database status-card menu (the
  `.action-menu` three-dot pattern shared by all three status cards) gained
  a third item in its first (routine, non-danger) section: "Purge completed
  (N)", the same `POST /settings/purge-completed` form and
  `data-confirm-sheet` the old inline row used, just moved and relabeled --
  grouped with Check integrity/Compact & reindex rather than the danger
  section "Reset database (purge all)" lives in, since it's routine
  housekeeping, not a catastrophe (same reasoning the 2026-08-26 redesign
  used when it first placed this button). The "Reset Home to default
  layout" row (posting to `/dashboard/reset`) was deleted outright, no
  replacement -- confirmed first that Home's edit-mode "Reset layout"
  button (`dashboard.html`) already posts to the exact same route with the
  same `data-confirm-sheet` mechanism, just different wording, so the
  Settings row was a verbatim duplicate control, not a second surface worth
  keeping. Both rows removed from the Maintenance & cleanup card, which now
  holds only the two autosubmit lifecycle selects (auto-archive, sync
  cleanup retention). No backend/route changes -- `/settings/purge-completed`
  and `/dashboard/reset` are unchanged, only the markup calling them moved.

  **Tests**: updated the three existing tests that asserted on the old
  markup rather than adding new ones (the moved button's behavior is
  already covered by `test_data_health.py`'s purge-completed tests and
  `test_dashboard_usability_rework.py`'s `TestHomeResetButton`/
  `TestLabelPageResetButton`, which test the route/behavior, not this
  page's now-removed duplicate): `test_phase8_settings_hub.py`'s
  `TestSettingsAdvanced` (renamed/rewrote the reset-button test to assert
  absence instead of presence), `test_data_health.py`'s
  `test_purge_completed_is_housekeeping_and_danger_zone_is_gone` (label
  text changed from "Purge completed tasks (N right now)" to "Purge
  completed (N)"), and `test_dashboard_usability_rework.py`'s
  `TestSettingsResetButton` (inverted to assert the route is gone from this
  page). Full suite run in 4 parallel batches (single bash call, background
  `&`/`wait` -- this environment's timeout otherwise kills a ~20s+ single
  run): **2136 passed**, plus 4 pre-existing failures confirmed unrelated
  by reproducing them on the unmodified HEAD commit via `git stash`
  (`TestAgendaWidgetAllUpcoming::test_todays_earlier_events_still_count_as_upcoming`
  and three siblings in `test_project_detail.py` -- all "today's earlier
  event/task still counts as upcoming" tests, time-of-day-sensitive
  boundary checks, not something this slice touched).

  **Next slice** (per `audit-fixes-2.1.md`, doc order): move the password,
  username, Radicale URL, etc. settings from General to a new "Your
  Profile" page (including Profile Picture and Nickname/"Your Name"), and
  move "Restart app" to Data & Maintenance as a post-edit toast trigger.

- **Shipped:** 2026-09-10 -- same session, direct "continue": next item off
  `audit-fixes-2.1.md` in doc order -- "The Kanban board columns should
  try to not add a horizontal scrollbar. It should first try to have them
  all in one row, then two rows, and only last the 4 rows for the 4
  columns. Keep in mind to calculate depending on the sidebar width." The
  old layout (style.css) was binary: columns shrink to fill one row down
  to a 240px floor, then a single `@media (max-width:1123px)` breakpoint
  jumped straight to 4 full-width stacked rows -- no 2-row middle step,
  and worse, keyed off the VIEWPORT, which can't see the sidebar's own
  expanded/collapsed state (`html[data-sidebar-expanded]`, toggled
  independently) -- a maximized window reads as the same "viewport width"
  whether the sidebar is eating ~240px of real content space or not,
  exactly the blind spot the direct request called out.
  Fixed with CSS container queries instead of viewport media queries:
  project_detail.html's Kanban board is now wrapped in a plain
  `.kanban-board-wrap` div (`container-type:inline-size; container-
  name:kanban`), and style.css's breakpoints became `@container kanban
  (max-width:...)` keyed off THAT wrapper's own rendered width -- sidebar-
  aware for free, since the wrapper's actual box already reflects
  whatever space the sidebar left it, regardless of viewport size. Two
  explicit tiers (not a continuous `auto-fit` grid reflow, which could
  land on an uneven "3 then 1" split with exactly 4 columns and wouldn't
  match "first one row, then two rows" at all): >=996px (4 * the 240px
  floor + 3 * the 12px gap) keeps the original unchanged single-row
  shrink-to-fit; 492-995px (2 * the floor + 1 gap) wraps to 2 columns per
  row via `flex-wrap:wrap` + a `calc(50% - gap/2)` basis (the two widths
  plus their one gap sum to exactly 100%, so it naturally breaks after
  every 2nd column with no `:nth-child` rule needed); below 492px, same
  full 4-row stack the old breakpoint used.
  **Also caught while touching style.css** (same lesson as the v97 sw.js
  bump's own comment, apparently still not a reliable habit): the
  PREVIOUS TWO slices this session (pill-click-opens-modal -- no style.css
  change, so no bump needed there; and the Contacts custom-dropdown swap)
  both should have bumped `sw.js`'s `CACHE_NAME` per style.css's own
  SHELL_ASSETS membership, and the Contacts one didn't. Bundled that missed
  bump with this slice's own into one `cc-shell-v97` -> `cc-shell-v98`
  jump -- see sw.js's own comment for the full breakdown.

  **Tests**: new `TestKanbanResponsiveColumns` in test_project_detail.py
  (8 tests, no browser harness, same structural-source-check convention as
  `TestKanbanDragAndDrop` in the same file) -- wrapper div present and
  actually contains the board, `container-type` declared, old `@media`
  rule confirmed gone, both `@container` breakpoints present, wide/middle/
  narrow tier rules each confirmed, and a sanity check that
  tasks_board.js's own selectors still match the rendered markup through
  the new wrapper (drag-and-drop unaffected). `test_pwa_shell.py`'s
  hardcoded `CACHE_NAME` assertion updated to v98. Full suite re-verified
  in the usual 6 batches -- **2140 passed, 0 failed** (2132 + 8 new).

  **Next slice** (per `audit-fixes-2.1.md`, doc order): the Data &
  Maintenance settings reorg -- move "Purge Completed Tasks" into
  Database's own context menu (as "Purge completed"), and remove the
  Reset-home-layout button (edit mode already has an equivalent button).

- **Shipped:** 2026-09-10 -- same session, direct "continue": next item off
  `audit-fixes-2.1.md` in doc order -- "Contacts edit modal window doesn't
  use the custom drop down menus." contact_form.html's five Phone/Email/
  Website/Address/Social "type" pickers (Home/Work/Other etc,
  db.CONTACT_*_TYPES) were the one form control left in the app still
  opening the browser's own native `<select>` chrome instead of the app's
  `.multiselect` checkbox/radio dropdown (_widget_list_multiselect.html,
  _task_row.html's status/labels pickers).
  Couldn't just drop in a per-row `{% include "_widget_list_multiselect.html" %}`:
  that partial submits its radios under one shared `name="{{ ms_name }}"`,
  but each of these fields is a REPEATABLE row group (a contact can have
  several phones/emails/etc, static/contact_phone_email_rows.js's
  add/remove rows) that all need to submit under the SAME field name
  (`phone_type`, parallel to `phone_value[]`, routers/contacts.py's
  `_phone_email_list` zips them back together by position) -- but native
  `<input type="radio">` mutual exclusion is scoped by (name, form owner),
  so sharing that name across rows would make every row ONE radio group
  (picking "Work" on row 2 would silently uncheck "Home" on row 1).
  New `_contact_type_picker.html` macro (`contact_type_picker()`) instead:
  each row's radios get a row-scoped unique name (`{{ field }}__{{
  row_key }}`, `row_key` = that row's `loop.index`, or a placeholder for
  the `<template>` "Add" clones) purely for the browser's own grouping,
  plus a `data-proxy-target` pointing at a hidden `<input type="hidden"
  name="{{ field }}">` that carries the REAL submitted value --
  contact_phone_email_rows.js's new delegated `change` listener keeps that
  hidden input in sync with whichever radio is checked, looked up by `id`
  (not `.closest(".contact-multi-row")`) since static/app.js's shared
  multiselect portal moves an OPEN `.multiselect-panel` -- radios included
  -- out to `#multiselect-portal`, outside the row, while a pick is being
  made. The same script's "Add" handler also rewrites a freshly-cloned
  row's placeholder name/id to something newly unique (a page-lifetime
  counter -- two clicks of "Add phone" must not produce two rows sharing
  one group either). Wire format is completely unchanged server-side --
  same field names, same value strings, same DOM order -- so
  routers/contacts.py needed no changes at all. style.css's per-row width
  overrides (`.field-wide .contact-multi-row select{width:110px}`,
  `.contact-address-row select{width:140px}`) retargeted from `select` to
  `.contact-type-select` (the new wrapper's own class).

  **Tests**: new `TestTypePickerIsCustomDropdown` class in all four of
  test_contacts_field_parity_{phone_email,website,address,social}.py (21
  tests total) -- native `<select>` gone, `.multiselect`/`data-ms-
  mode="single"` markup present, radios never carry the real field name
  directly, two rows in the same group get distinct radio-group/proxy ids,
  the hidden proxy still posts under the original field name. Every
  pre-existing contacts test kept passing unchanged through this swap
  (written against the wire contract, not the markup, so the `<select>` ->
  custom-dropdown swap was invisible to them). Full suite re-verified in
  the usual 6 batches -- **2132 passed, 0 failed** (2111 + 21 new).

  **Next slice** (per `audit-fixes-2.1.md`, doc order): "The Kanban board
  columns should try to not add a horizontal scrollbar. It should first
  try to have them all in one row, then two rows, and only last the 4 rows
  for the 4 columns" -- confirmed still open (style.css's `.kanban-board`
  is currently a binary layout: one shrinking row down to a 240px column
  floor, or -- past a single `max-width:1123px` breakpoint -- straight to
  4 full-width stacked rows, no intermediate 2-row/2-column step).

- **Shipped:** 2026-09-10 -- same session, direct "continue": next item off
  `audit-fixes-2.1.md` in doc order -- "In the unscheduled work, for any
  pill inside it, the user could click it and open the task view modal
  window." This directly conflicted with the SAME session's own earlier
  Planner-rework slice (doc order, further down this file), which made a
  plain click on that same pill add one more undated work session instead
  -- a single click gesture can't do both. Flagged this to the user before
  touching code (AskUserQuestion) rather than guessing; picked "click opens
  the modal; drop click-to-add entirely -- add a session from the modal's
  Work sessions card instead" (confirmed that card already has a working
  "+" button posting to the same `/tasks/{uid}/work-allocations` endpoint,
  so nothing there needed building).
  Implementation: `static/project_calendar.js`'s `setupUnscheduledItem`
  `end()` -- the no-drag click branch's `postAction(".../work-allocations",
  ...)` call replaced with the same `taskUrlBase`/`window.CCModal.open(url,
  item)` (falling back to `window.location.href`) convention interaction 4
  already uses for a placed `.work-allocation` block's click-to-open;
  `cfg.taskUrlBase` was already being set by `calendar_week.html` (the only
  template that sets `window.PROJECT_CALENDAR` -- `_unscheduled_task_item.html`
  is only ever rendered there via `_calendar_week_grid.html`) so no new
  config plumbing was needed. Updated the stale click-to-add comments in
  `project_calendar.js` (both its file-header interaction-1b note and
  `end()`'s own) and `_unscheduled_task_item.html`'s macro-doc comment to
  describe the superseding and why.

  **Tests**: `test_calendar_week_scheduling.py` -- `TestClickToAddSessionIsAsync`
  replaced with `TestClickOpensTaskModal` (4 tests: no-drag click branch
  uses `cfg.taskUrlBase`/`item.dataset.taskUid`/`window.CCModal`/
  `CCModal.open(url, item)`, the old click-to-add POST is gone from that
  branch, the dead stepper pointerdown carve-out stays gone, and the
  no-CCModal navigation fallback is present); `TestUnscheduledPanelStepper`'s
  docstring updated to point at the new class. Full suite re-verified in
  the usual 6 batches -- **2111 passed, 0 failed** (2110 - 3 old + 4 new).

  **Next slice** (per `audit-fixes-2.1.md`, doc order): "Contacts edit
  modal window doesn't use the custom drop down menus" -- confirmed still
  open (contact_form.html's type pickers are all plain native `<select>`s;
  only its Labels field uses the app's custom multiselect component).

- **Shipped:** 2026-09-10 -- same session, direct "continue": next item off
  `audit-fixes-2.1.md` -- "In the projects page, I would like the agenda
  card to also include tasks due date in that list, like other widgets in
  the normal dashboard." The Project page's card (previously "Upcoming
  events", `routers/projects.py::project_detail`) only ever queried
  events; renamed to "Agenda" and merged in every open, due-dated task
  tagged with the project's label into the SAME chronologically-sorted
  list (not a separate section) -- the request said "that list," singular.
  Checked first whether the normal Dashboard's own Agenda widget
  (`dashboard.py::_render_agenda`) had a reusable merged-list helper to
  call instead of writing new logic -- it doesn't: that widget actually
  keeps tasks/events as two SEPARATE lists/sections internally, so "like
  other widgets in the normal dashboard" is matched here via the same
  `relative_date` formatting/row-macro conventions, not a literal shared
  merge function (none exists to share).
  Implementation: `tasks` (already computed for the Kanban board, already
  excludes archived) filtered to not-done + has due_at + due_at >= today,
  each turned into an event-shaped dict with `kind: "task"`; combined with
  the existing events/deadline list, sorted by one `start_at` key, capped
  at 8 same as before. Context key renamed `events` -> `agenda_items`
  (there's no single-list precedent to preserve `events`'s old meaning
  under, and "an agenda_items list that sometimes contains tasks" is more
  honest than overloading `events`). Template gained a third row branch
  (`item.kind == 'task'`) alongside the existing plain-event/`is_deadline`
  branches.
  **Also fixed while touching this filter** (caught mid-implementation,
  not itself in the audit doc): the events filter compared the FULL
  `now_iso` timestamp (wall-clock precision) against `start_at` -- the
  exact bug `dashboard.py`'s own Agenda widget fixed 2026-09-03 (today's
  earlier events silently dropped). Switched to the same date-level
  `>= today_iso` comparison dashboard.py already uses, for consistency
  and correctness.

  **Tests**: `test_project_detail.py`'s `TestUpcomingEventsCard` ->
  `TestAgendaCard` (context-key rename throughout, +1 new test for the
  wall-clock fix), `TestProjectDeadlineAsEvent` updated for the same
  rename, new `TestAgendaCardIncludesTasks` (9 tests: inclusion, no-due-
  date/past-due/done/other-project exclusion, today-still-counts,
  combined sort order, shared 8-item cap, task-row link markup). Full
  suite re-verified in the usual 6 batches -- **2110 passed, 0 failed**
  (2100 + 10 new).

  **Next slice** (per `audit-fixes-2.1.md`, doc order): the Data &
  Maintenance settings reorg (move "Purge Completed Tasks" into
  Database's context menu, drop the redundant Reset-home-layout button),
  or the "Your Profile" settings page split (move password/username/
  Radicale URL/profile picture/nickname off General into a new page).

- **Shipped:** 2026-09-10 -- same session, direct "continue": next item off
  `audit-fixes-2.1.md` -- "The kanban board for tasks doesn't allow for
  tasks to be drag and dropped." Diagnosis: `static/tasks_board.js` (a
  fully-implemented Pointer-Events drag-and-drop, not native HTML5 DnD --
  see its own header comment for why) already existed and already matched
  `project_detail.html`'s Kanban board markup exactly (`#kanban-board`,
  `.kanban-column[data-status]`, `.kanban-cards[data-status]`,
  `.kanban-card[data-uid]`) and posts to the same `/tasks/{uid}/
  update-field` endpoint the old per-card status dropdown used before its
  2026-09-02 removal -- it was simply never `<script>`-included on this
  page. It's a leftover from `templates/tasks_board.html`, a standalone
  global Kanban page deleted in the 2026-08-28 rework; project_detail.html
  later rebuilt its own Kanban board (2026-08-30) reusing the same
  `.kanban-*` CSS by name but never re-attached the matching JS. style.css's
  `.kanban-card.dragging`/`.kanban-cards.drop-hover` rules were likewise
  already sitting there unused. Fix: added
  `{% block extra_scripts %}<script defer src="{{ static_url('tasks_board.js') }}"></script>{% endblock %}`
  to `project_detail.html` -- no markup or JS changes needed. Confirmed
  this doesn't conflict with the 2026-09-02 "no inline editing" decision
  (that removed the per-card native `<select>` dropdown specifically,
  per direct request; today's request is a separate, later, direct ask
  for drag-and-drop). Updated the stale "out of scope" comment blocks in
  `project_detail.html`, `tasks_board.js`, and `style.css` that all
  referenced the deleted `tasks_board.html`/the old "still open" note.
  `tasks_board.js` is NOT added to `sw.js`'s `SHELL_ASSETS` (page-specific,
  same as `project_calendar.js`/`tasks_table.js`) -- no cache-version bump
  needed for this slice, unlike the Planner slice below.

  **Tests**: 3 new in `test_project_detail.py`'s new
  `TestKanbanDragAndDrop` -- confirms the script tag renders, confirms the
  script's own selectors (`getElementById("kanban-board")`,
  `.closest(".kanban-cards")`, `.kanban-card` query) actually match
  strings present in the rendered board markup (not just "the script is
  included," but "the script's selectors have something real to bind to"),
  and confirms the drag-drop path posts to `/tasks/{uid}/update-field`
  with the exact `{field: "status", value: ...}` shape that endpoint
  expects. No browser harness in this suite, same structural-source-check
  convention `test_calendar_week_scheduling.py`'s `TestGridDragConflictFix`
  already established. Full suite re-verified in the usual 6 batches --
  **2100 passed, 0 failed** (2097 + 3 new).

  **Next slice** (per `audit-fixes-2.1.md`, doc order): the Projects page
  agenda card's missing task due dates, or the Data & Maintenance settings
  reorg (move Purge Completed Tasks into Database's context menu, remove
  the redundant Reset home layout button).

- **Shipped:** 2026-09-10 -- same session, direct "continue": the Planner
  page's "Unscheduled work" panel rework, `audit-fixes-2.1.md`'s largest
  item -- "tasks with 0 work sessions should not appear... remove the
  minus and plus for these pills and allow for the task title to show a
  bit more, a bit of space and then at the end the number of sessions
  needed to allocate... replaced by the already in place drag and drop...
  click on it, add one more unscheduled session... drag and drop the other
  one wherever the user wants." Three changes:
  1. **0-session filter bug** (`routers/calendar.py`'s `_week_view_context`,
     the unscheduled_tasks loop): the old `info["count"] and not
     info["undated_count"]` check only ever dropped a task once it had
     >=1 session and all were dated -- it never treated "0 sessions total"
     as a reason to hide, so a brand-new task with no sessions at all
     showed up with a bare "0" pill. Both cases collapse to one check,
     `if not info["undated_count"]: continue` (a 0-session task's
     `undated_count` is also 0) -- `db.work_allocation_panel_info`'s
     docstring updated to match.
  2. **Stepper removed** (`_unscheduled_task_item.html`): both `<form>`s
     (+/- posting to /tasks/{uid}/work-allocations and .../remove-latest)
     deleted from both the plain-task and habit branches; the row is a
     plain `<div>` again (title given more room via style.css's
     `.unscheduled-task-item` max-width 190px -> 240px, `.unscheduled-count`
     now `margin-left:auto` at the end of the row instead of sandwiched
     between two icon buttons).
  3. **Click-to-add replaces "+"** (`project_calendar.js`): the drag
     source's own pointerdown/pointerup handling now treats a plain
     release with no drag (`!wasDrag`, previously a silent no-op) as "add
     one more undated session" -- posts the same
     `/tasks/{uid}/work-allocations` endpoint the old "+" button used, via
     the same async `postAction`/ccApi path every other action on this row
     already takes. The stepper's pointerdown carve-out
     (`e.target.closest(".unscheduled-stepper")`) is dead and removed.
     There is no in-panel "−" anymore -- the task modal's own Work
     sessions card still owns deleting a session outright; drag-a-placed-
     session-back-onto-the-panel-to-unschedule (interaction 3) is
     unaffected.

  **Also caught mid-slice:** `static/avatar_cropper.js` IS in `sw.js`'s
  `SHELL_ASSETS` precache list -- the earlier same-session fix to that
  file (backdrop-click no longer discards an in-progress crop) skipped the
  required `CACHE_NAME` bump. Bundled the retroactive bump for that with
  this slice's own (style.css changed, which always requires one
  regardless of SHELL_ASSETS membership, per the file's own v88 note) into
  one `cc-shell-v96` -> `cc-shell-v97` bump -- see sw.js's own comment.
  **Lesson for future JS/CSS slices in this repo: check `SHELL_ASSETS`
  membership and check style.css diffs BEFORE calling a slice done, not
  after the fact.**

  **Tests**: `test_calendar_week_scheduling.py` -- flipped
  `test_open_task_with_no_allocation_is_unscheduled` (renamed
  `..._is_not_unscheduled`, asserts absence now), gave
  `test_unscheduled_task_shows_its_project_pill` an undated session so it
  still qualifies for the panel, rewrote `TestUnscheduledPanelStepper`'s
  button-specific tests into stepper-is-gone assertions, replaced
  `TestUnscheduledPanelStepperIsAsync` with `TestClickToAddSessionIsAsync`
  (structural source-checks against project_calendar.js, same no-browser-
  harness convention as `TestGridDragConflictFix` in the same file).
  `test_pwa_shell.py`'s hardcoded `CACHE_NAME` assertion updated to v97.
  Full suite re-verified in the usual 6 batches -- **2097 passed, 0
  failed** (net test count unchanged: -1 stepper test, +1 click-to-add
  test).

  **Next slice** (per `audit-fixes-2.1.md`, doc order): the Kanban board's
  drag-and-drop (currently not working at all for moving tasks between
  columns), or the Projects page agenda card's missing task due dates.

- **Shipped:** 2026-09-10 -- same session, direct "continue": next item off
  `audit-fixes-2.1.md` in doc order -- "When inline changing labels in
  Tasks page, the pills revert to a blue no icon pill, even if they
  normally have color and icon. A refresh fixes this." Root cause:
  `static/tasks_table.js`'s `change` listener for `input.task-label-
  checkbox` rebuilt the trigger's `.cell-tags` HTML client-side after every
  toggle, hand-constructing `<span class="cell-tag tag-blue">Name</span>`
  per checked label -- it had no access to that label's real configured
  color/icon (that lookup, `label_color()`/`label_icon()`, is server-side
  only, in `_label_pill.html`'s `label_pill()` macro), so every edited pill
  collapsed to plain blue with no icon until the next full page load
  re-rendered it through the real macro. Fixed by cloning the pill markup
  instead of reconstructing it: each checkbox's own `<label class=
  "multiselect-option">` already has the real, server-rendered pill
  sitting right next to it (`_task_row.html`'s dropdown-option list also
  calls `label_pill(name)`) -- `cb.parentElement.querySelector(".cell-tag")
  .outerHTML` reuses that exact markup, with the old hand-built-blue-span
  kept only as a defensive fallback if the pill element somehow isn't
  found.

  **Tests**: 2 new structural source-checks in
  `test_tasks_table_labels_status_title.py`'s new
  `TestInlineLabelEditKeepsRealPillColorAndIcon` (same "no JS harness in
  this suite, assert against the actual JS source" style the file's
  existing `TestStatusLabelChangeListenerNotAncestorScoped` class already
  uses) -- one confirms the old hardcoded-blue-span construction is gone,
  one confirms the new clone-the-real-pill approach is present. Full suite
  re-verified in the usual 6 batches -- **2097 passed, 0 failed**.

  **Next slice** (per `audit-fixes-2.1.md`, doc order): the Planner page's
  unscheduled-work-card rework -- hide 0-session tasks, drop the +/-
  steppers in favor of drag-and-drop reallocation. Doc order covered so
  far this session: vCard import crash, banner/avatar crop-editor
  outside-click, this Tasks-label-pill entry -- next up is the doc's
  Planner item, the largest/most involved item in the list so far.

- **Shipped:** 2026-09-10 -- same session as the vCard-import-crash entry
  below, direct "continue": next item off `audit-fixes-2.1.md`'s own list
  (picked in doc order, since the doc has no priority marking) -- "The
  banner upload modal window doesn't work. The image crop/rotate, on
  external mouse click always exists, even if the user is trying to crop
  the image (remove the if click outside then exit for it)." Root cause:
  `static/avatar_cropper.js`'s crop/rotate overlay (shared by every image
  upload in the app -- contact photos, the profile-picture row, and
  Home/label/page-header banners, not banner-specific despite the report's
  wording) had a backdrop-click listener (`overlay.addEventListener("click",
  ...)`, was lines 353-355) that called `closeEditor(true)` -- discarding
  the in-progress crop/rotate -- on *any* click landing on the backdrop,
  including a pointer that only briefly leaves the crop stage during a
  fast drag on a resize handle or the box itself. No dirty-state check, no
  confirmation. Removed the listener entirely; the explicit Close (X) and
  Cancel buttons are the only exits now. Checked first whether this
  codebase has an existing "suppress outside-click-close" convention to
  reuse (a `data-no-outside-close`-style flag) -- it doesn't; every other
  outside-click-to-close spot (`modal.js`'s own backdrop click, the color/
  icon popover, `datetime_picker.js`, `reminders_picker.js`) is its own
  bespoke listener with no shared opt-out, so outright removal (not a new
  flag) is the consistent fix here.

  **Tests**: none added -- this repo has no JS test runner/framework
  (checked: no `package.json` test setup, no `.test.js` files anywhere),
  same "no live browser in this sandbox" gap noted in the 2.0 session's
  entry below. Python suite unaffected (no `.py` changed this slice) --
  re-ran `test_banners.py` (the file covering this editor's wiring,
  `TestBannerUploadUsesCropEditor`) as a sanity check anyway: 55 passed.

  **Next slice** (per `audit-fixes-2.1.md`, doc order): the inline-labels-
  revert-to-blue-pill bug on the Tasks page, or the Radicale-unreachable
  startup traceback (still unconfirmed whether that's a real bug or just
  noisy logging -- app already degrades gracefully per the log's own
  "running without the sync bridge" line).

- **Shipped:** 2026-09-10 -- direct request, new session: user dropped a new
  `documentation/plans/audit-fixes-2.1.md` (a plain-text bug list -- ~14 UI/
  UX items -- plus two production `journalctl`/traceback logs) and said "the
  app has some bugs." Asked which item to start on (AskUserQuestion, since
  the doc has no priority order of its own); picked the vCard-import crash:
  `POST /export/import/auto` 500'd (`AttributeError: uid`) importing a vCard
  with no UID property at all -- confirmed real, not hypothetical, since the
  pasted traceback's sample card (a Nextcloud "Administrator" export) is
  exactly this shape, and UID is spec-mandatory but plenty of real-world
  exporters omit it anyway. Root cause: `vcard_rows.vcard_to_contact_row`
  did `str(card.uid.value)` unconditionally -- vobject's `__getattr__`
  raises `AttributeError` for an absent property, no `getattr(..., None)`-
  friendly accessor exists. Fixed by falling back to `str(uuid.uuid4())`
  when `card.uid` is absent or its `.value` is falsy (a `UID:` line with
  nothing after the colon is a separate but same-shaped case) -- same
  "always assign a fresh identity" convention as every other uid-on-
  creation callsite in this app (`routers/contacts.py`, `routers/tasks.py`,
  etc., all `str(uuid.uuid4())`). A uid-less card now imports as a new
  contact instead of failing the whole import.

  **Tests**: 3 new -- `test_row_translators.py`'s
  `TestContactRow::test_missing_uid_gets_generated_not_crash` (UID property
  absent) and `::test_blank_uid_value_gets_generated_not_stored_literally`
  (UID property present, empty value -- a distinct code path,
  `hasattr`-true but falsy `.value`), plus an endpoint-level regression in
  `test_phase10_export.py`'s
  `TestExportAndImport::test_import_contact_with_no_uid_does_not_500` using
  the same card shape as the reported traceback. Full suite re-verified in
  6 batches of ~15 files each (this sandbox's 45s-per-command limit still
  applies, same workaround as the 2.0 session) -- **2095 passed, 0
  failed**. The single pre-existing failure noted in the 2.0 entry below
  (`test_dashboard_router.py::TestAgendaWidgetAllUpcoming::
  test_todays_earlier_events_stil...`) is no longer present -- not
  investigated further this session (out of scope for this slice), but
  worth noting it's gone rather than silently carrying forward a stale
  "known failure" caveat.

  **Next slice** (per `audit-fixes-2.1.md`, no priority order of its own --
  pick next): the other crash log in the doc (Radicale-unreachable-at-
  startup traceback -- likely just noisy logging, app already degrades
  gracefully per the log's own "running without the sync bridge" line, so
  worth confirming that before treating it as a real bug), or any of the
  ~14 plain-text UI items (banner upload modal crop/rotate exiting on
  outside click is first in the doc's own order). `audit-fixes-2.1.md`
  itself is untouched -- unlike `audit-fixes-2.0.md` this doc has no
  checkbox/strikethrough convention yet; worth deciding one before the
  list grows, so the same "audit before declaring done" mistake caught in
  the 2.0 session doesn't recur.

- **Released 2.0** -- 2026-09-09, direct request, new session: "push this to
  2.0." Before pushing, audited `audit-fixes-2.0.md` (the roadmap's own
  stated gate) rather than taking "nothing left to do" at face value --
  found items 7/8/13/14 had actually already shipped in code (7: dead
  templates/db functions gone; 8: settings-heading consistency reached via
  a different route than sketched, the per-page `section-label` removed
  app-wide 2026-09-08 instead of these two pages conforming to it; 13/14:
  `_row_action_buttons.html`/`_empty_state_row.html` macros exist and are
  imported everywhere the item specified) but the doc itself was never
  struck through -- fixed the bookkeeping to match reality. Item 15 (stale
  roadmap claim) was only half-fixed: `roadmap.md`'s 1.9 detail section
  already had the correct "superseded 2026-08-28" note, but the Release
  map table's `1.8`/`1.9` rows still claimed a bare "shipped" -- fixed to
  match. All 15 audit items now genuinely shipped; the FullCalendar-parity
  calendar queue (`open.md`) was already fully shipped per its own slice
  6 entry. Version bumped to **2.0.0** in both `pyproject.toml` files and
  `README.md`; `roadmap.md`'s Release map `2.0` row marked shipped.

  **README.md rewrite** (direct request, "in depth enough for normal
  people to install it" -- it wasn't): added an "Is this for you?" framing
  section; split "Getting started" into a clearly-labeled throwaway
  local-eval path vs. a real always-on server install, spelling out
  prerequisites (Debian 12, SSH, root) and what happens immediately after
  `curodav-ctl install` (the app is reachable at `http://<ip>:8000` and
  lands on a one-time `/setup` page to pick a login in-browser -- this
  wasn't mentioned anywhere before, the old README implied env-var editing
  was the only path). New "Security note" section (Tailscale vs. public
  domain+TLS, don't bare-expose port 8000), "Connecting your phone"
  section (DAVx5/iOS, pointing at `deploy/README.md`'s existing Cloudflare
  Tunnel walkthrough rather than duplicating it), and "Troubleshooting"
  (service status/logs, failed-update rollback, forgotten-password
  recovery via direct `app_meta` deletion -- verified against
  `auth.py`/`settings.py::purge_all` and `curodav-ctl`'s actual
  `CC_DB_PATH` before writing the exact SQL, since `purge_all_data` wipes
  *all* data, not just the login, so pointing there would have been wrong
  advice). All jargon (systemd, LXC, symlink swap) now defined inline on
  first use rather than assumed.

  **Tests**: no code changed, so no new tests -- full suite re-verified
  (92 files, run in 6 foreground batches of ~15 files each rather than one
  `pytest` invocation, which timed out in this sandbox's 45s-per-command
  limit; a background/detached run was also tried and discarded --
  processes and `/tmp` don't survive between tool calls here, unlike a
  normal shell session) -- 2091 passed, 1 failed (same pre-existing
  `test_dashboard_router.py::TestAgendaWidgetAllUpcoming::
  test_todays_earlier_events_still_count_as_upcoming` date-relative flake
  every recent entry in this file already notes), 2092 collected. Matches
  the prior session's baseline exactly.

  **Manual verification**: none beyond reading the actual template/db
  files for items 7/13/14 (confirmed dead code gone, macros exist and are
  imported) and the actual `_row_action_buttons.html`/`_empty_state_row.
  html` header comments (both already say "audit-fixes-2.0.md item N" and
  a 2026-09-07 date, confirming they were real shipped work, just
  undocumented in the tracking doc) -- no live browser in this sandbox,
  same recurring gap.

  **Next slice:** none mandated -- 2.0 is shipped. Future sessions can
  drop back to normal minor-release-style work; there's no more "gate"
  doc to read before starting.

- **Shipped:** 2026-09-09 -- direct request, new session: "a setting in
  general so if checked (normally isn't), the time tagged as sleep time is
  just removed as cells from the planner calendar view." Three clarifying
  questions asked and answered up front (AskUserQuestion), since the
  literal ask turned out to require rewriting the Week grid's pixel math
  (server AND both drag-interaction JS files) to stay correct, not just a
  CSS tweak: (1) Sleep can be configured with different start/end per
  weekday (Settings > Sleep & Leisure Time) -- if the configured windows
  disagree, **require one uniform window** rather than guessing which one
  to collapse; (2) hidden hours are **fully removed** (no drag reachability
  into them), not just zero-height-but-still-a-drop-target; (3) **Week
  (Planner) only** -- Day view keeps all 24 hours regardless of this
  setting.

  **New Settings > General toggle**: "Hide sleep hours in Planner", off by
  default (`deps.HIDE_SLEEP_HOURS_KEY = "planner_hide_sleep_hours"`,
  `routers/settings.py::set_hide_sleep_hours`, same On/Off segmented
  autosubmit pattern as Edit mode/Show label icons).

  **`grid_layout.py`**: new `collapse_minutes(minute, (skip_start,
  skip_end))` -- the actual "remove these hours" transform (before <=
  skip_start unchanged, at/after skip_end shifts up by the window's width,
  inside the window clamps to skip_start) -- plus `grid_height_px(collapse)`
  and `visible_hours(collapse)` (the hour-gutter's own `{hour, top_px}`
  list, dropping any hour whose boundary falls inside the window).
  `position_event`/`layout_day` both gained an optional `collapse` param,
  mapping an event's real start/end through `collapse_minutes` before the
  existing pixel math -- Day view's own unchanged call sites just never
  pass one.

  **`routers/calendar.py`**: new `_sleep_collapse_window(blocks)` -- None
  unless every Sleep-kind time_blocks row shares the exact same start/end
  (the "require one uniform window" decision); `_week_view_context` computes
  it once (only when the setting is on) and threads it through
  `grid_layout.layout_day`/a reworked `_time_block_overlays_for_day`
  (a Sleep-kind overlay is dropped entirely when collapsing -- those hours
  don't exist any more -- a Leisure-kind one still renders, repositioned).
  New context keys: `grid_height_px` (the collapsed column's total height)
  and `sleep_collapse_json` (`{active, skip_start, skip_end}` for the
  client). `_day_view_context` untouched.

  **Templates**: `settings_general.html` gained the new row.
  `_calendar_week_grid.html`'s hour gutter now reads `{hour, top_px}` pairs
  instead of computing `h * px_per_hour` itself, and `.time-grid-body` gets
  an explicit `data-style="height:..."` override (dynamic_styles.js's CSSOM
  convention, CSP-safe) instead of relying on the shared
  `height:calc(25 * var(--hr-h))` default. `calendar_week.html` renders a
  new `#cc-sleep-collapse` JSON tag + loads the new `static/sleep_collapse.
  js` before calendar.js/project_calendar.js.

  **New `static/sleep_collapse.js`**: reads that JSON once, exposes
  `window.CCSleepCollapse = {active, dayHeightPx(pxPerHour), toReal(min)}`
  -- `toReal` is the exact client-side inverse of `collapse_minutes`,
  needed because a drag create/move/resize's pixel position is already in
  COLLAPSED space (there's no DOM height for the hidden hours at all); without
  converting back to the real clock time before saving, anything dragged
  below a collapsed window would save shifted earlier by the window's
  width. `calendar.js`/`project_calendar.js` (both previously hardcoded
  `DAY_HEIGHT_PX = 24 * PX_PER_HOUR` and read pixel positions straight into
  saved minutes) now read `DAY_HEIGHT_PX` from `CCSleepCollapse.
  dayHeightPx` and wrap every final real-minute conversion in `toRealMin`
  (falls back to identity/`24 * PX_PER_HOUR` when the global is absent,
  i.e. every page except Week). `time_blocks.js`'s own overlap-warning
  check needed no change -- it already operated on real minutes, which is
  exactly what it now keeps receiving.

  **Tests**: `test_grid_layout.py` gained a `TestSleepHourCollapse` class
  (collapse_minutes/grid_height_px/visible_hours + layout_day with a
  collapse window, 12 new tests). New `test_calendar_planner_sleep_
  collapse.py` (17 tests): setting defaults off and round-trips; Week view
  renders all 24 hours when off OR when configured Sleep blocks disagree;
  collapses correctly when on and uniform (hour count, sleep overlay
  gone, leisure overlay repositioned, event after the window shifted,
  grid_height_px shrunk, sleep_collapse_json payload); Day view unaffected
  regardless of the setting. Full suite (2092 tests): 619 + 609 + 507 + 357
  = 2092 collected, 2091 passed, 1 pre-existing unrelated failure
  (`test_dashboard_router.py::TestAgendaWidgetAllUpcoming::test_todays_
  earlier_events_still_count_as_upcoming`, a date-relative flake confirmed
  pre-existing via `git stash` before this session touched anything;
  4-chunk run).

  **Manual verification**: none beyond the pytest suite + direct router/
  grid_layout calls above -- no live browser in this sandbox to actually
  drag-create/move/resize an event across a collapsed window and confirm
  the saved time on screen. The math is covered by tests on both sides
  (server `collapse_minutes` and its client inverse `toReal`), but an
  actual pointer-drag round trip through calendar.js/project_calendar.js is
  unverified beyond code review.

  **Next slice:** none mandated -- direct request, fully shipped. Worth
  live-verifying the drag-create/move/resize interactions in a real
  browser next time Planner is touched, given the "no browser in this
  sandbox" gap above.

- **Shipped:** 2026-09-08 -- direct request, new session: "add the
  ability to change radicale environment variables in the app, and have
  a button actually restarting the app so it applies. also I would like
  to merge the concept of radicale username to the app username, and
  merge the app password with the radicale password." Two clarifying
  questions asked and answered up front (AskUserQuestion): restart
  mechanism = self-exit + systemd `Restart=always` (not a sudo/systemctl
  grant), and credential merge = "UI-level merge only, stores stay
  separate" (not a privileged helper writing Radicale's own htpasswd --
  that file, owned by a separate `radicale` system user, stays entirely
  out of reach, unchanged).

  **New: `webapp/src/env_file.py`** -- stdlib-only read/write for the
  systemd `EnvironmentFile` (`/srv/curodav/shared/.env`). `read_env_file`
  (live vars only, ignores commented-out template lines);
  `update_env_file` (replaces a live `KEY=` line, or uncomments+fills a
  `#KEY=` template line, or appends a new one; always double-quotes with
  `\"`/`\\` escaped; atomic temp-file-then-`os.replace`, original file
  mode preserved). `config.Settings` gained `env_file_path` (from
  `CC_ENV_FILE`, a new env var `scripts/curodav-ctl`'s generated unit now
  sets to the same path as its own `EnvironmentFile=` -- the file's
  *contents* land in the process env either way, but nothing before this
  told the process where that file itself lives).

  **`scripts/curodav-ctl`**: `write_env_template`'s `chmod 0640` ->
  `0660` (group-writable -- the app, running as the `curodav` group
  owner, now needs to write its own config, not just read it).
  `write_unit`'s `Restart=on-failure` -> `Restart=always` (a clean
  `exit(0)` now gets relaunched too, not just a crash) plus the new
  `Environment=CC_ENV_FILE=...` line.

  **`routers/settings.py`**: three old routes --
  `change_login_password`/`change_radicale_password` (Settings > General)
  and `settings_radicale` (Data & Maintenance's plain URL/username/
  password form) -- replaced by one `POST /settings/account`
  (`account_settings`). One username/password now governs both the app's
  login and its stored Radicale credential; a Radicale Server URL field
  sits alongside. Storage backend: if either half was already
  env-configured (`CC_AUTH_USERNAME`/`PASSWORD` or `CC_RADICALE_URL`) AND
  `CC_ENV_FILE` is known, the whole account is written to the env file
  from then on (converting the other half over too, if it wasn't already
  -- deliberate, "one identity" was the point); env-configured with no
  `CC_ENV_FILE` known still refuses to edit (same "edit curodav.env
  yourself" fallback as before); neither env-configured persists to
  app_meta, same as the three old routes did. Any existing account
  requires `current_password` to verify before ANY change (username,
  password, or just the URL) -- broader than the old routes' "only a
  password change needs verification," since this form now controls the
  sync credential too. The Radicale password key is only ever written
  when a real `new_password` is supplied -- never silently persists
  `settings.radicale_password`'s "devpass" dev-default as if it were a
  chosen credential.

  New `POST /settings/restart` (`restart_app`): gated on `deploy_mode ==
  "production"` (the one existing signal for "systemd-managed, something
  is watching to relaunch me"); schedules `os._exit(0)` on a
  `threading.Timer` half a second out (long enough for the redirect to
  reach the socket first) rather than exiting inline.

  **`routers/auth.py` / `setup.html`**: `/setup`'s "connect to Radicale"
  section dropped its separate username/password fields -- URL only now;
  `_save_radicale_fields` reuses the account's own just-chosen
  username/password as the Radicale credential.

  **Templates**: `settings_general.html`'s two old cards ("Login &
  security" + Radicale password) replaced by one "Account" card
  (username, current/new/confirm password, Radicale URL) plus a
  "Restart app" card/button, the latter hidden entirely (not shown
  disabled) outside `deploy_mode == "production"`.
  `settings_data_maintenance.html`'s "CalDAV / Radicale sync" card is
  read-only display now (current URL + a link to Settings > General) --
  no form of its own, credentials live in the merged Account card.

  **Tests**: `test_settings_login_password.py` rewritten for
  `account_settings`/`restart_app` (env-file path, app_meta path,
  verification-required-for-any-change, restart gating via a fake
  `threading.Timer` so the test process doesn't get killed by the real
  one). `test_settings_radicale.py` rewritten for the now-read-only
  Data & Maintenance card. New `test_env_file.py` (13 tests: live-line
  replace, template uncomment+fill, append, quote/escape round-trip,
  mode preservation, missing-file/missing-dir failure surfaces as a real
  exception). `test_auth.py`'s `/setup` Radicale tests updated for the
  dropped fields. Full suite (now 2071 tests, up from 2058): 898 + 672 +
  501 = 2071 passed, 0 failed (6-chunk run).

  **Manual verification**: `bash -n scripts/curodav-ctl` (syntax only --
  no real systemd/root environment in this sandbox to actually exercise
  install/restart); direct `env_file.update_env_file`/`read_env_file`
  round-trip against a real temp file (quoting, mode, template-line
  uncommenting all confirmed by hand before the pytest suite existed);
  direct `settings_general`/`settings_data_maintenance` router calls
  rendering real Jinja output across local/production/env-configured-
  without-CC_ENV_FILE states, confirming the right form/button
  presence in each. No live browser, no real systemd unit, no real
  Radicale htpasswd anywhere in this sandbox -- the restart button's
  actual "process exits, systemd relaunches it with new env" behavior is
  unverified beyond code review + the mocked-Timer test.

- **Shipped:** 2026-09-08 -- direct follow-up, same session as the four
  entries below: "also remove the 'No account needed.' label."
  published_lists.html only -- the public-link Link-column hint added
  two entries below ("Anyone with this link can view it, no account
  needed." -> "No account needed.") is deleted outright, same treatment
  every other settings-hint on this page has gotten this session; no
  replacement copy, the public-link row is now just the truncated URL +
  copy button, nothing underneath. Full suite re-run in 6 chunks:
  898+662+498 = 2058 passed, 0 failed.

- **Shipped:** 2026-09-08 -- direct follow-up, same session as the three
  entries below: "also rename the Private Radicale and Public Link to
  Private and Public. Also when no Filter just say All items."
  published_lists.html/published_list_create_modal.html only:
  - "Private Radicale" (the Sharing field's option label, added the
    entry two below) reverted to plain "Private" -- in the Sharing
    single-select's own panel, table pill text, and the test asserting
    the rendered summary (`test_entity_type_and_visibility_render_as_
    single_mode_multiselects`, updated to match). "Public" was already
    unchanged from the earlier rename, nothing to touch there.
  - The Filter column's empty state "All items (no filter)" -> "All
    items" -- the parenthetical was redundant once you're looking at an
    empty Filter cell in a table row that already has its own column
    header saying "Filter".
  - Full suite re-run in 6 chunks: 898+662+498 = 2058 passed, 0 failed.

- **Shipped:** 2026-09-08 -- direct follow-up, same session as the two
  entries below: "in the table, could you remove the 'Private -- needs
  your Radicale/CalDAV account.' text. Also trim all text from that
  table so that it, in most cases, doesn't overflow to another row."
  published_lists.html only:
  - The private-collection Link-column hint ("Private -- needs your
    Radicale/CalDAV account.") is deleted outright, same treatment the
    two Visibility hints already got in the entry below -- no
    replacement copy.
  - The public-collection Link-column hint shortened "Anyone with this
    link can view it, no account needed." -> "No account needed."
  - The archived/paused Link-column fallback shortened "Paused -- not
    synced or shared" -> "Not synced or shared" -- the leading "Paused"
    was dropped as redundant, the Sharing column's own pill (right next
    to it) already says "Paused".
  - Nothing else in the table needed trimming -- Name/Type/Filter/Sharing
    cells are all either short fixed vocabulary or already truncated
    (`.truncated-url`'s existing 45-char ellipsis, `white-space:nowrap`)
    and the table sits in `.table-scroll` (horizontal scroll on overflow,
    section 6 rule), so nothing here was wrapping to a second line
    within its own cell before this either -- confirmed by reading the
    template, not a browser check (no live browser reachable in this
    sandbox, same recurring gap this file's other entries note).
  - Full suite re-run in 6 chunks: 898+662+498 = 2058 passed, 0 failed.

- **Shipped:** 2026-09-08 -- direct follow-up, same session as the table-
  rework entry right below: "also remove 'Matches any checked label.
  Leave blank for everything.' and 'Private syncs to your Radicale
  account.'. Rename the Visibility to better match the options: Private
  should become Private Radicale and Public should become Public; and
  the Visibility should become Linkage (or other more normal or
  intuitive names)." All in published_list_create_modal.html/
  published_lists.html:
  - Both remaining settings-hints deleted outright, no replacement copy.
  - Visibility field/label renamed "Sharing" (picked over the user's own
    suggestion "Linkage" as the more ordinary word for what it controls)
    -- `ms_label`/`data-ms-label` and the table's own column header both
    changed; the submitted form field name (`name="visibility"`) and the
    `visibility` DB column/route params are untouched, this is a display
    rename only.
  - Option copy: "Private" -> "Private Radicale", "Public (shareable
    link)" -> "Public" -- both fields now name themselves without
    leaning on the hint that used to sit underneath (now deleted). Table
    pill text (published_lists.html) updated to match ("Private" ->
    "Private Radicale"). "Paused" (archived, edit-mode only) unchanged.
  - `TestCreateModalDropdownsAreCustomStyled::test_entity_type_and_
    visibility_render_as_single_mode_multiselects` updated for the new
    `data-ms-label="sharing"` and `<span class="ms-summary">Private
    Radicale</span>` strings -- a real behavior change, not test rot.
  - Full suite re-run in 6 chunks: 403+495+662+498 = 2058 passed, 0
    failed (same total as the table-rework entry below).

- **Shipped:** 2026-09-08 -- direct request, new session: "rework the
  [Published Lists] table in the spirit of any other table in the app.
  Also it should have an edit button. No inline editing. In the modal
  window for creating or editing a published list, choosing a label
  should be a checkbox drop down menu, and please delete any settings
  hint that are unnecessary." Four changes, all in the Published Lists
  feature (webapp/src/templates/published_lists.html, published_list_
  create_modal.html, routers/published_lists.py, static/published_lists.js,
  static/style.css):

  1. **Table rework.** The page's own hand-rolled `.lists-table-container`/
     `.lists-table` chrome (flat border, tinted thead, roomier padding, a
     bespoke mobile stacked-row `@media` block) predated the `.card.
     table-scroll` + plain `<table>` convention the rest of the app
     settled on (_tasks_body.html, settings_holidays.html, settings_data_
     maintenance.html's conflicts table) -- swapped onto that convention;
     style.css's generic `table`/`thead th`/`tbody td` rules (section 6)
     now supply the chrome, and the old `.lists-table*` CSS block
     (~190 lines, mobile stack included) and the now-dead `#create-list-
     form .field-toggle*` rules (labels moved off that markup, see #3
     below) are deleted rather than left dead.
  2. **No inline editing.** Visibility's auto-submitting `<select>` (a
     live write on every change, no confirmation -- the one inline-edit
     control this table had) is gone, replaced by a plain read-only
     `.pill-static` badge. Every editable field (Name, Visibility, Labels)
     now lives behind a new per-row Edit icon-btn (`.action-buttons`, same
     shape `_row_action_buttons.html` callers use elsewhere, hand-rolled
     here rather than that shared macro so the Delete button could keep
     its domain-specific "Unpublish" wording) that opens `GET /published-
     lists/{id}/edit` -- new route, backed by a new `POST /published-
     lists/{id}/update` that reuses `_unique_collection_path`/
     `_try_teardown`/`_try_materialize` (rename-safe, best-effort on
     Radicale, skips Radicale side effects entirely for an already-
     archived List) and delegates the actual visibility transition to the
     existing, already-tested `set_visibility` function rather than
     duplicating its token/teardown/rematerialize logic. Type is NOT
     editable post-creation (shown as a read-only `.cell-tag` pill in the
     edit modal instead) -- changing entity_type after a List has
     materialized would orphan its Radicale collection; out of scope here.
     Visibility's edit-mode picker gains a third option ("Paused" =
     archived) since that state is no longer reachable from the table.
  3. **Labels filter -> checkbox dropdown.** The hand-rolled `.field-
     toggle-group` of always-visible plain checkboxes is now `_widget_
     list_multiselect.html`'s `ms_mode="filter"` (not `"select"` --
     filter mode's "empty = All" reading matches this field's own "leave
     blank for everything" semantics; select mode's "empty = no labels,
     never collapses to All" is for a record's actual tag set, wrong
     here) with `ms_pill=true`, same colored/iconed pills every other
     Labels picker in the app renders. One template now serves both
     create and edit (`editing` in context switches the header/action/
     button copy and pre-fills Name/Visibility/Labels); form id is
     `create-list-form` or `edit-list-form` depending, so static/
     published_lists.js's validation now looks up whichever is present
     instead of a single hardcoded id (the old `#label-checkboxes`
     checkbox-count logic was dead weight -- never actually gated
     anything, see that file's own comment -- and is gone, not ported).
  4. **Settings-hint cleanup.** Visibility's hint dropped its "Public also
     adds a shareable link" clause (redundant -- the option itself is
     already labeled "Public (shareable link)"). The trailing "Change
     visibility or archive anytime from the list below" hint is deleted
     outright, not shortened -- it described the now-removed inline
     `<select>`; there's nothing "below" to point at any more, the Edit
     button doesn't need a hint to explain itself. The labels-filter
     "matches any checked label" hint and the no-labels-yet empty-state
     copy both stay -- real, non-obvious information nothing else on the
     page says.

  **Tests:** full suite re-run in 6 chunks (file-list split, largest
  suite yet at 2058 tests total across 90 files) -- 403 + 495 + 286 + 376
  + 275 + 223 = 2058 passed, 0 failed. No new test file added this
  session (existing `TestPublishedListsRouterCrud`'s "Edit not supported
  in new simplified API" comment is now stale -- edit_list_modal/
  update_list exist -- but no test asserts the old absence either, so
  nothing broke; a follow-up session should add explicit edit-route
  coverage rather than relying on the manual round-trip reasoning above).

  **No live browser reachable in this sandbox** -- same recurring gap
  every entry in this file already notes; verified via template-syntax-
  clean Jinja renders (a stray literal `{{ }}` in this template's own
  header comment briefly broke `TemplateSyntaxError` until caught by the
  first test run) and the full test suite, not an actual click-through.

- **Noted, not shipped:** 2026-09-08 -- direct request, same session as
  the `deploy/`/Cloudflare Tunnel entries below: the user wants "something
  like this, or at least a good or easy way to deploy all." Right now
  `scripts/curodav-ctl` (deploys the webapp) and `deploy/`'s three scripts
  (`firewall.sh`, `cloudflared/install-cloudflared.sh`, `radicale/install-
  radicale.sh`) are entirely separate tool chains -- none of them call or
  even reference each other. A fresh server needs all four run by hand, in
  order, plus a manual copy-paste of the Radicale credentials `install-
  radicale.sh` prints into `curodav-ctl`'s own `/srv/curodav/shared/.env`
  before restarting it. Logged as an explicit open request in `open.md`'s
  "Webapp usability + DAVx5 mobile hosting" section (a single orchestrator
  -- `deploy/bootstrap.sh` or a new `curodav-ctl` subcommand -- that runs
  every step and wires the credentials through automatically) so it isn't
  lost; not scoped or built this session. Next session picking this up
  should read that note before starting.

- **Shipped:** 2026-09-08 -- direct follow-up, same session/modal as the
  entry right below: "in the Create a published list the drop down menu
  are not our own design, they are defaults. also make way short the
  settings-hint."

  **Root cause (dropdowns):** Type and Visibility were plain `<select>`s.
  style.css's site-wide `select{}` rule only reskins the CLOSED box
  (custom chevron, border-radius, padding) -- a native select's OPEN
  dropdown list is drawn by the OS/browser, unstyleable by any CSS on the
  page. This is the exact reason `task_form.html`'s Status/Priority/
  Recurrence and the widget builder's View/Range already moved off
  `<select>` onto `_widget_list_multiselect.html`'s `ms_mode="single"`
  variant (see that partial's own header comment) -- confirmed via a
  subagent that this modal's markup was otherwise a correct, unremarkable
  instance of the plain-`<select>` convention used elsewhere (habit_form/
  contact_form's short-list pickers); the fix wasn't missing CSS/markup on
  this file, it was the field never having been moved onto the
  already-established richer component the way Status/Priority/View/
  Range were.

  **Fix, `published_list_create_modal.html` only:** both fields now
  `{% include "_widget_list_multiselect.html" %}` with `ms_mode="single"`,
  `ms_wide=false` (same half-width slot the two `<select>`s occupied
  side by side), `ms_form_id="create-list-form"`. `entity_type` defaults
  to `entity_types[0]` (same default a `<select>` with no `selected`
  option would pick -- no behavior change). Visibility's items are now
  short labels ("Private" / "Public (shareable link)") instead of full
  sentences baked into `<option>` text, since a dropdown *option* can't
  carry a secondary description the way a `.settings-hint` paragraph can.
  Backend needed no change -- the radios still submit as `name="entity_
  type"`/`name="visibility"`, same field names `create_list()`'s
  `Form(...)` params already read.

  **Shortened every `.settings-hint` in this modal** (second half of the
  same direct request): the two long Visibility sentences collapsed into
  one hint below both fields ("Private syncs to your Radicale account;
  Public also adds a shareable link."); the labels-filter hint went from
  two sentences to one ("Matches any checked label. Leave blank for
  everything."); the no-labels-yet hint and the bottom "change visibility/
  archive" hint were each trimmed similarly. `.settings-hint` itself has
  no CSS length/width constraint (confirmed by research) -- this was a
  copy edit, not a layout fix.

  **Tests:** new `TestCreateModalDropdownsAreCustomStyled` (2 tests) --
  asserts no literal `<select` tag anywhere in the rendered body (comment
  stripped first, since the fix's own header comment names the old
  element in prose) and that both fields render as `data-ms-mode="single"`
  multiselects with the expected default-selected summary text ("Tasks"/
  "Private"). Full suite re-run in the same 3-chunk pattern as recent
  entries: 976 + 622 + 455 = 2053 passed, 0 failed (2051 + 2 net new). No
  `sw.js` bump -- template + test only, no static JS/CSS touched.

  **No live browser reachable in this sandbox** -- same recurring gap
  every entry in this file already notes. Verified via a direct
  `new_list_modal()` router call (real Jinja output, confirms the radios/
  panel markup and default summaries) and the full test suite, not an
  actual click-to-open-the-panel check.

- **Shipped:** 2026-09-08 -- direct request, same session as the
  `deploy/`/Cloudflare Tunnel entries below: "make published lists more
  permissive and easier to set up even if no labels present." Two real
  blockers, both removed:

  1. **The create modal hard-blocked with zero labels in the account.**
     `published_list_create_modal.html` used to render an empty-state
     ("go create a label first") instead of the form entirely when
     `all_labels` was empty -- an account with no labels yet could never
     create a List at all. The form now always renders; the label section
     is explicitly framed as optional ("Filter by labels (optional)"),
     and when there are no labels yet it shows an inline note ("this list
     will include everything of the selected type") plus a `Create a
     label` link (`/settings/labels/new`, modal) instead of blocking.
  2. **An unfiltered List materialized as permanently empty.**
     `evaluate_label_filter`'s "neither `all` nor `any` given" case used
     to return `[]` outright (documented reasoning: "a List with zero
     criteria publishing the entire pool would be a surprising default").
     Flipped per this direct request: it now returns everything of that
     `entity_type` (`_ALL_OBJECT_IDS` dispatch to `db.list_tasks`/
     `list_events`/`list_contacts` -- `task` deliberately goes through
     `list_tasks`'s own `include_habit_tasks=False` default rather than a
     raw table scan, so an unfiltered List stays consistent with the
     app's existing habit-task exclusion elsewhere). `none` still
     subtracts from that base, so "everything except labelled X" stays
     expressible with zero positive criteria. This is what actually makes
     fix 1 useful -- without it, the newly-unblocked form would still
     produce a List that stays empty forever.

  **Copy updates to match:** `published_lists.html`'s table now shows
  "All items (no filter)" instead of "No labels selected" for an
  unfiltered List's Filter column (the old wording read as a
  misconfiguration, not a deliberate choice); its empty-state text
  dropped "a filtered subset" in favor of "optionally filtered by label."

  **Tests:** `test_no_positive_criteria_matches_nothing` in
  `test_phase6_published_lists.py` renamed/rewritten to
  `test_no_positive_criteria_matches_everything` (its own docstring
  explains the flip); new `TestNoLabelsPresent` (2 tests) -- the create
  form renders (no "No labels available" text) against a conn with zero
  labels, and `create_list(..., labels=[], ...)` against that same conn
  materializes every task, not zero. No other test in the suite asserted
  the old "empty filter = nothing" behavior (confirmed by grep for
  `label_filter`/`evaluate_label_filter` across `webapp/`) -- every other
  materialize/visibility test uses an explicit non-empty filter. No
  `sw.js` bump -- only templates + Python changed this slice, no static
  JS/CSS. Full suite re-run in the same 3-chunk pattern as recent
  entries: 976 + 620 + 455 = 2051 passed, 0 failed (2049 + 2 net new).

  **No live browser reachable in this sandbox** -- same recurring gap
  every entry in this file already notes. Verified via direct router
  calls (real Jinja output, confirms the form renders and the "No labels
  available" text is gone) and the full test suite, not click-through.

- **Shipped:** 2026-09-08 -- direct follow-up, same session as the
  `deploy/` scaffolding entry right below: "we are going online via
  cloudflare tunnels." Swapped the whole reverse-proxy layer from
  Caddy + Let's Encrypt to a Cloudflare Tunnel -- this is a real
  simplification, not just a substitution: a tunnel is fully outbound
  (cloudflared connects OUT to Cloudflare's edge), so there's no inbound
  port to open, no cert to issue/renew, and no local reverse-proxy process
  needed on the host at all. `Caddyfile.template`/`install-caddy.sh`
  deleted outright, replaced by `deploy/cloudflared/` (`config.yml.
  template`, `cloudflared.service`, `install-cloudflared.sh`).

  **`install-cloudflared.sh`:** installs `cloudflared` from Cloudflare's
  own apt repo; runs `cloudflared tunnel login` (interactive -- prints a
  URL, blocks until the operator authorizes it in a browser) only if
  `/root/.cloudflared/cert.pem` doesn't already exist; finds-or-creates a
  named tunnel (`cloudflared tunnel list -o json` piped through a small
  `python3 -c` filter for the non-deleted entry matching `TUNNEL_NAME` --
  verified standalone against a fake JSON list with both a live and a
  `deleted_at`-set entry sharing the same name, confirmed it picks the
  live one); routes DNS for both `DOMAIN_APP`/`DOMAIN_DAV` at the tunnel
  (`cloudflared tunnel route dns`, Cloudflare's own CNAME automation --
  unlike the Caddy version, the user never manually creates an A/AAAA
  record); copies the tunnel's credentials JSON + rendered `config.yml`
  into `/etc/cloudflared`, owned by a new dedicated `cloudflared` system
  user (no special privileges needed -- the process only ever makes
  outbound connections, never binds a listening socket); installs +
  starts `cloudflared.service`.

  **`firewall.sh`** simplified to ssh-only (was ssh+80+443) -- 80/443
  aren't needed anywhere in this design anymore. The explicit
  `ufw deny 8000/5232` defense-in-depth lines are unchanged (still true
  that `curodav.service` binds `0.0.0.0:8000`, not loopback).
  `radicale/*` (config/service/install script) is entirely unaffected by
  this swap -- Radicale still binds loopback and gets bcrypt auth exactly
  as before; only what fronts it publicly changed.

  **`deploy/README.md`** rewritten around the tunnel flow: prerequisite is
  now "domain onboarded to Cloudflare" (nameservers pointed there) rather
  than "DNS A/AAAA records pointing at this server's IP"; added a
  troubleshooting note (unverified) that Cloudflare's Bot Fight Mode/WAF
  can occasionally flag DAVx5's `PROPFIND`/`REPORT` requests on the DAV
  subdomain, with the fix being a WAF skip rule scoped to `DOMAIN_DAV` --
  flagged explicitly as unverified since there's no live tunnel to test
  against from this sandbox.

  **Verified:** `bash -n` on all three scripts; the tunnel-lookup Python
  filter tested standalone (see above) against a crafted two-entry JSON
  list. **Not verified, same as the entry below:** no live Cloudflare
  account/tunnel/domain to actually run this against from this sandbox --
  `cloudflared tunnel login`'s interactive browser-auth step in particular
  has never been exercised for real. `open.md`'s DAVx5 section updated to
  describe the Caddy->tunnel swap. No app code touched; full suite not
  re-run for this entry specifically (nothing in `webapp/` changed since
  the prior entry's own full run).

- **Shipped:** 2026-09-08 -- scaffolded `deploy/` (repo root, new
  directory) for `open.md`'s "DAVx5 mobile access (Phase C)": direct
  request, "the app is going to run on a machine reachable from the public
  internet" (answered via AskUserQuestion: no domain yet, subdomain split
  -- app on one subdomain, DAV on another -- and same host `curodav-ctl`
  already manages). Pure infra, no `webapp/` app code touched -- confirmed
  by running the existing full suite unchanged after this slice (see
  below), nothing here is Python/template/JS that pytest would exercise.

  **Layout, all under new `deploy/`:** `deploy.env.example` (copy to
  `deploy.env`, gitignored, holds `DOMAIN_APP`/`DOMAIN_DAV`/`LE_EMAIL`/
  `RADICALE_USER`) + `firewall.sh` (ufw: only 22/80/443 open externally --
  explicitly denies 8000/5232 too, defense in depth, since `curodav.
  service`'s own `ExecStart` binds `0.0.0.0:8000` not loopback) +
  `Caddyfile.template`/`install-caddy.sh` (installs Caddy from its official
  apt repo, sed-renders the template, automatic Let's Encrypt TLS for both
  domains) + `radicale/config.template` + `radicale/radicale.service` +
  `radicale/install-radicale.sh` (dedicated `radicale` system user/venv/
  service -- independent of `curodav`'s own release lifecycle, since
  Radicale is a dev-only pip dependency in `webapp/pyproject.toml`,
  excluded from `uv sync --no-dev`; interactively prompts for a password,
  bcrypt-hashes it into `/srv/radicale/users` via the same venv's own
  `bcrypt` package, never writes the plaintext anywhere). `deploy/README.md`
  ties it together: prerequisites (DNS must already resolve before
  `install-caddy.sh`, ACME needs it), exact run order, the exact
  `CC_RADICALE_URL/USER/PASSWORD` lines to add to `/srv/curodav/shared/.env`
  afterward (the app keeps talking to Radicale over loopback directly, same
  as today -- only DAVx5 goes through the new public `DOMAIN_DAV`), DAVx5's
  own account fields, an end-to-end verification checklist, and a
  `--reset-password` rotation path.

  **Design choices worth remembering:** DAV gets its own subdomain, not a
  path under the app's domain -- Radicale's `/‹user›/‹collection›/` URL
  shape would otherwise collide with the webapp's own routes if they
  shared one hostname (this was an explicit answered question, not
  assumed). Radicale's own `hosts=127.0.0.1:5232` plus `firewall.sh`'s
  explicit deny is two independent layers keeping it off the public
  internet directly -- only Caddy's reverse proxy is ever allowed through.

  **Verified:** `bash -n` on all three new scripts (syntax only, no
  `shellcheck` available in this sandbox); the bcrypt-hashing snippet
  `install-radicale.sh` runs was extracted and run standalone against a
  test string, confirmed it produces a real `$2b$...` hash. No `caddy`
  binary available in this sandbox to `caddy validate` the Caddyfile
  template -- syntax follows Caddy's documented reverse_proxy/header/
  request_body directive shapes but has not been validated by the real
  binary. **Nothing in this slice has been run against a live public
  server** -- no domain exists yet (direct answer to the clarifying
  question), so this is unexecuted scaffolding, not a confirmed-working
  deployment. `open.md`'s own DAVx5 section updated to note the
  scaffolding exists but is still blocked on a real domain/server.

  **Next step, not this session's to take:** once the user has a domain
  and DNS pointing at the server, walk `deploy/README.md`'s setup order
  for real and fix whatever the live run surfaces that couldn't be caught
  by static review alone (same "verified structurally, never run for
  real" caveat every entry in this file already carries for the app side).

- **Shipped:** 2026-09-08 -- direct bug report, same day as the header
  cleanup entry right below: "published list doesn't work to create even
  if labels exists. though this should not be a condition."

  **Root cause:** `published_lists.js`'s `checkValidity()` disabled the
  "Publish List" button unless BOTH a name was typed AND at least one
  label checkbox was ticked -- a client-side rule the server never
  actually enforced. `routers/published_lists.py`'s `create_list()` has
  `labels: list[str] = Form([])` (defaults to empty), and both
  `_filter_from_form()` and `src/published_lists.py`'s
  `evaluate_label_filter()` handle an empty filter without error --
  already covered by `test_phase6_published_lists.py`'s
  `test_create_slugifies_name_and_dedupes_collection_path`, which calls
  `create_list(..., labels=[], ...)` directly and asserts success. So the
  report's exact framing was right: labels existed in the account (the
  form wasn't in the "no labels" empty-state branch), but the submit
  button silently never enabled unless the user happened to tick a
  checkbox -- no error shown anywhere, since this was a disabled-button UI
  gate, not a validation message.

  **Fix, `published_lists.js` only:** `checkValidity()` now gates purely
  on `hasName` -- matches the server's real requirement (`name: str =
  Form(...)`, no default, so an empty name is a genuine 422). Stale
  comment in `published_list_create_modal.html` (documented the old
  "name + label" gate as intentional) corrected to match.

  **Also investigated, not a bug -- DAVx5/Radicale exposure:** the
  roadmap (`open.md`/`roadmap.md`) already scopes this as infra-blocked,
  not app code: `config.py` defaults to a localhost-only dev Radicale
  with plaintext dev creds (`.dev/radicale/config`'s own comment: "NOT for
  real deployment... never for anything reachable off localhost"), and no
  `deploy/` directory (Caddyfile, firewall rules, production Radicale
  config) exists yet. A private published list already materializes fine
  into the local dev Radicale; making DAVx5 on a real phone sync against
  it needs a real domain + server + TLS + production Radicale auth, none
  of which this repo can provide on its own. Explained to the user rather
  than attempted -- no infra decision made yet.

  **Tests:** new `test_published_lists_create_button.py`
  (`TestCreateButtonNotGatedOnLabels`, 2 tests) -- same "no JS unit-test
  harness for `static/*.js` in this repo" gap every prior JS-only slice's
  own entry notes, covered via `node --check` (syntax) plus a source grep
  pinning that `hasLabel` is gone from the file, not just shadowed. No
  `sw.js` bump needed -- `published_lists.js` isn't in `SHELL_ASSETS`
  (not shell-critical, same category `heatmap_scroll.js` used to be per
  an earlier entry in this file) and `static_url()`'s own mtime-based
  cache-busting query string means a normal reload always fetches the new
  copy regardless of the service worker's precache. Full suite re-run in
  the same 6-chunk pattern as the entry below: 413 + 563 + 290 + 328 + 260
  + 195 = 2049 passed, 0 failed (2047 + 2 net new).

  **No live browser reachable in this sandbox** -- same recurring gap
  every entry in this file already notes. The fix was verified by
  re-reading the server's own actual requirements (not a guess) and a
  direct source-grep test, but the real "type a name, no labels ticked,
  does the button actually enable and does submitting actually create the
  list" click-through has not been seen rendered.

- **Shipped:** 2026-09-08 -- direct pre-release cleanup on the Published
  Lists page (`/published-lists`): "we also need to fix the published list
  before release. move the new list button to the header, while not having
  too big of height. also remove the page-description."

  **`published_lists.html`:** the "New List" `<a class="btn primary"
  data-modal>` -- previously its own `.lists-toolbar` row below the header
  -- now renders inside `page_header_narrow`'s `{% call %}` actions slot
  (same pattern Tasks/Calendar already use), alongside the existing
  `crumbs`-driven "Back to Settings" icon-btn. The `<p class="page-
  description">` (the "Share a live, read-only snapshot..." blurb) is
  deleted outright, per direct request.

  **`style.css`:** added a scoped `.page-header-narrow-actions .btn.primary
  {height:30px; padding:0 var(--space-4);}` -- a default `.btn.primary`'s
  own padding (`--space-2` top/bottom) runs taller than the header's fixed
  48px box actually has room for (30px content budget: 48 - 16 padding - 2
  border, same math `.filter-dropdown-trigger`'s own comment already
  derived), so it's pinned to a fixed height here rather than left to
  overflow:hidden to silently clip it -- this is the "not too big of a
  height" half of the request. Also deleted `.page-description` (now
  unused, confirmed by grep) and two further dead rules in this page's own
  CSS block, `.page-header`/`.page-header h1` -- leftover from before this
  page adopted the shared `.page-header-narrow` partial, never referenced
  by any template (confirmed by grep) and easy to confuse with the real
  `.page-header-narrow` class name.

  **Verified rendered** (not just reasoned about): a direct `list_index()`
  router call, real Jinja output -- confirms the button and the back-arrow
  both land inside `.page-header-narrow-actions`, and that `page-
  description`/`lists-toolbar` no longer appear anywhere in the output.

  **Tests:** no dedicated test previously asserted the old `.lists-
  toolbar`/`.page-description` markup or the button's exact location
  (confirmed by grep across `webapp/tests`), so nothing needed updating
  beyond the routine `sw.js` bump. `CACHE_NAME` `v95` -> `v96`; `test_pwa_
  shell.py`'s pin updated. Full suite re-run in 6 chunks of ~15 files each:
  413 + 563 + 290 + 356 + 237 + 188 = 2047 passed, 0 failed (same total, no
  tests added/removed here).

  **No live browser reachable in this sandbox** -- same recurring gap
  every entry in this file already notes. The 30px fixed-height button was
  verified by the same padding/border arithmetic `.filter-dropdown-
  trigger`'s own comment already established for this exact header (not a
  fresh guess), but the actual on-screen fit (does it look centered/not
  clipped next to the back-arrow) has not been seen rendered.

- **Shipped:** 2026-09-08 -- fourth direct follow-up, same session as the
  three entries below: "I would like to have it have the min height a bit
  bigger." `#unscheduled-panel-body`'s fixed height was 26px -- computed as
  the exact content height of one row with no slack at all, which read as
  cramped/clipped. Bumped to 36px, still a fixed (not max-/min-) height, so
  the no-reflow-on-drag fix two entries below is unaffected either way.

  **Tests:** `TestUnscheduledPanelFixedHeight`'s test updated for the new
  36px value. `sw.js` `CACHE_NAME` bumped `v94` -> `v95`; `test_pwa_shell.
  py`'s pin updated. Full suite re-run in 3 chunks: 976 + 646 + 425 = 2047
  passed, 0 failed (same total, one assertion changed).

  **No live browser reachable in this sandbox** -- same recurring caveat.
  This is now the fourth same-day round on this one small panel (hard-
  reload fix, height, toggle side, hidden scrollbar, now height again)
  without ever seeing it rendered -- strongly worth a real look at this
  specific panel first if a browser becomes reachable next session, rather
  than continuing to iterate blind on exact pixel values.

- **Shipped:** 2026-09-08 -- third direct follow-up, same session as the two
  entries below: "in the unscheduled work card it shouldn't have a
  sidebar." Root cause: shrinking `#unscheduled-panel-body` to a fixed
  one-row height (the entry right below) means it now hits its own
  `overflow-y:auto` scrollbar far more readily than the previous 3-row
  version did -- the browser's default scrollbar track was reading as an
  unwanted vertical strip stuck to this small card's right edge (hence
  "sidebar"). Fixed by hiding the track -- `scrollbar-width:none` +
  `#unscheduled-panel-body::-webkit-scrollbar{display:none;}` -- the exact
  same pattern `.tabbar` (this app's other overflow-y:auto-but-no-visible-
  track element) already uses elsewhere in style.css. The row still
  scrolls (wheel/touch/drag auto-scroll), just with no visible track.

  **Tests:** `TestUnscheduledPanelFixedHeight`'s test updated to assert
  both new rules. `sw.js` `CACHE_NAME` bumped `v93` -> `v94`; `test_pwa_
  shell.py`'s pin updated. Full suite re-run in 3 chunks: 976 + 646 + 425 =
  2047 passed, 0 failed (same total as the entry below -- one test's
  assertion got stricter, no test added/removed).

  **No live browser reachable in this sandbox** -- same recurring caveat.
  This is now the third same-day round on this one card (hard-reload fix,
  then height, then toggle side, then this) without ever seeing it
  rendered -- worth prioritizing a real look at this specific panel first
  if a browser becomes reachable next session.

- **Shipped:** 2026-09-08 -- direct follow-up, same day/session as the entry
  right below ("acceptable, however..."): two more Planner "Unscheduled
  work" panel reports against that fix.

  1. **"The Unscheduled work div got bigger."** The prior fix's `#
     unscheduled-panel-body{height:84px}` (~3 rows, sized generously so
     more items wouldn't scroll right away) read as a size regression for
     the common one-or-two-item case, where the box now always reserved
     3 rows of mostly-empty space. Shrunk to `height:26px` -- exactly one
     row (the tallest child in a row is `.unscheduled-step-btn` at 16px,
     plus the item's own 3px/3px padding and 1px/1px border) -- matching
     the panel's own everyday pre-fix size. Still a FIXED (not max-)
     height, so the reflow-on-drag fix itself is unaffected; a list past
     one row now reaches its own internal scrollbar sooner than before,
     which is the accepted trade.
  2. **"When hiding the unscheduled work card, the sidebar icon goes from
     right to left. It should remain on the right."** Root cause: `.
     unscheduled-panel-head{justify-content:space-between}` positions its
     two children (h2 title + toggle button) relative to each other --
     collapsing hides the h2 (`display:none`), leaving the toggle as the
     row's ONLY flex item, and `space-between` puts a lone item at
     flex-start (left) instead of flex-end. Fixed with `#unscheduled-
     panel-toggle{margin-left:auto}`, pinning it to the row's own right
     edge regardless of whether the h2 is present in layout.

  **Tests:** `test_calendar_week_scheduling.py`'s `TestUnscheduledPanel
  FixedHeight` test updated for the new 26px value; new `TestUnscheduled
  PanelToggleStaysOnTheRight` (1 test) locks in the `margin-left:auto`
  rule. `sw.js` `CACHE_NAME` bumped `v92` -> `v93`; `test_pwa_shell.py`'s
  pin updated. Full suite re-run in 3 chunks across all 88 non-live test
  files: 976 + 646 + 425 = 2047 passed, 0 failed.

  **No live browser reachable in this sandbox** (same recurring gap this
  file already notes) -- both fixes verified by source/CSS reasoning and
  the test suite, not seen rendered. Worth confirming on-screen next
  session if a browser becomes reachable, same note as the entry below.

- **Shipped:** 2026-09-08 -- direct report against the Planner (`/calendar/
  week`) page, two bundled fixes, both scoped to the "Unscheduled work"
  panel specifically (not the grid itself):

  1. **"Incrementing work sessions for any unscheduled work should not hard
     refresh the page."** `_unscheduled_task_item.html`'s "+"/"-" stepper
     forms (both the plain-task and habit branches, 4 forms total) were
     plain `<form method="post">`s with no `data-cc-change` attribute --
     every other mutation on this page (drag-create, drag-move,
     unschedule-by-drop) already goes through `ccApi`/`cc-entity-changed`
     and a targeted `#week-grid` region refresh, but these four never got
     that treatment, so a click fell through to a real browser submit and
     its endpoint's unconditional 303 redirect (`routers/tasks.py`'s
     `add_work_allocation`/`remove_latest_work_allocation` don't branch on
     the fetch header at all). Fix: added `data-cc-change="task"` +
     `data-cc-action="create"`/`"remove"` to all four forms -- async-crud.
     js's existing generic `[data-cc-change]` submit handler (the same one
     `task_form.html`/`event_form.html`/etc. already use) now intercepts
     them, and async_calendar.js's already-wired `cc-entity-changed`
     listener for `/calendar/week` claims the change and refreshes just the
     region. No backend change needed -- confirmed live (a direct
     `week_view()` router call rendering real Jinja output, not just the
     unit tests) that both forms carry the new attributes in actual served
     HTML.
  2. **"Dragging and dropping from unscheduled work to the planner, and
     vice versa, should not move the scrollbar page."** Root cause: `.
     project-calendar-unscheduled` (the aside) is `flex:none`, so its own
     outer height was purely a function of how many `.unscheduled-task-
     item` chips it had to wrap (the 2026-09-02 "grow tall, more rows"
     redesign). Scheduling a task (drag onto the grid) or unscheduling one
     (drag onto the panel) changes that item count by exactly one, so the
     aside got one row taller/shorter on every such drop -- reflowing `.
     project-calendar-grid` below it in the same flex column. This is
     separate from (and not fixed by) the 2026-09-09 slice-5 scroll-restore
     work, which only preserves `.time-grid-wrap`'s own `scrollTop` -- that
     value genuinely never changed here, the whole grid card just
     physically moved on screen, which reads as a scrollbar jump even
     though no real scroll position did. Explains why the report scoped
     this to unscheduled<->planner drags specifically: a plain block move/
     resize never touches the panel's item count, so it never reflows
     anything. Fix, `style.css` only: `#unscheduled-panel-body` (the list
     wrapper, not the always-visible header above it) now has a fixed
     `height:84px` (not `max-height`, which would still shrink/grow with
     content and reintroduce the same reflow) + its own `overflow-y:auto`
     -- about 3 rows, so the aside's footprint can no longer change with
     item count; a longer list scrolls inside this fixed box instead of
     growing it. Trades a little empty space at very low item counts for a
     grid that can't move under an active drag.

  **Tests:** `test_calendar_week_scheduling.py` gained `TestUnscheduled
  PanelStepperIsAsync` (2 tests: plain-task and habit-branch forms both
  carry the new attributes) and `TestUnscheduledPanelFixedHeight` (1 test:
  the fixed-height rule is present and no competing `max-height` rule
  exists). `sw.js` `CACHE_NAME` bumped `v91` -> `v92`; `test_pwa_shell.py`'s
  pin updated. Full suite re-run in 3 chunks across all 88 non-live test
  files (`test_caldav_bridge_live.py` excluded as always): 975 + 646 + 425
  = 2046 passed, 0 failed.

  **No live browser reachable in this sandbox** (same recurring gap prior
  entries in this file note) -- the stepper's async wiring was verified
  against real server-rendered HTML (a direct `week_view()` call, not just
  assertions), and the fixed-height CSS reasoning was verified by computing
  the panel's own per-row pixel math from its existing rules, but neither
  fix's actual on-screen *feel* (does a schedule/unschedule drop now truly
  never nudge the grid, does the region refresh after a stepper click look
  instant/non-jarring) has been seen rendered or clicked through. Worth
  being the first thing confirmed next session if a browser becomes
  reachable.

- **Shipped:** 2026-09-08 -- direct follow-up, same day as round 3 above:
  "fix the drag and drop for tasks and events... it doesn't show the drag
  and drop shadow like in all day events." Plain event/task chips (Month/
  4-Week, `setupItem` in `calendar_month_drag.js`) never got a pointer-
  follow drag ghost the way `.month-bar`s already do (`setupBar`) -- a chip
  just sat lifted in place (`.dragging`'s ring outline, 2026-09-03) with
  nothing actually tracking the cursor.

  **Fix:** `setupItem` now spawns a `.month-item-ghost` on drag start --
  a deep `cloneNode(true)` of the chip itself (its markup varies by kind:
  color-dot + optional time + title, so cloning wholesale sidesteps
  special-casing that setupBar's manual ghost reconstruction needed),
  `position:fixed`, follows the pointer (offset by the original grab
  point, same math as the bar ghost), removed on drop. The source chip now
  fades (`opacity:.3`) instead of the ring-outline "lifted" treatment --
  the ghost carries the "picked up" signal now, so keeping both would be
  redundant, matching `.month-bar.dragging`'s own "source fades, ghost is
  what's visible" split.

  **Verified live** (not just reasoned about, per round 3's own process
  note above): dispatched synthetic pointerdown/pointermove against a real
  chip in the running instance -- ghost appeared, tracked the pointer,
  origin chip faded; pointerup landed the reschedule on the exact date
  released over, and the ghost was removed from the DOM afterward.

  **Tests:** new `TestItemDragGhostStructural` in `test_calendar_month_
  bars.py` -- `node --check` plus source/CSS greps for the clone/ghost/
  fade wiring, same pattern every prior JS-only calendar slice's own test
  file uses. `sw.js` `CACHE_NAME` bumped `v90` -> `v91`; `test_pwa_shell.
  py`'s pin updated. Full suite re-run across all 88 non-live test files in
  4 batches -- all green, 0 failures.

  **Next slice:** none mandated -- direct request, fully shipped and
  verified live.

- **Shipped:** 2026-09-08 -- same-day bug fix, round 3, the ACTUAL root
  cause, found by connecting a live browser to this sandbox after round 2
  (further below) was reported still broken. Rounds 1 and 2 both reasoned
  from the code alone and both fixed real-but-secondary issues in
  `calendar_month_drag.js` (kept, not reverted) -- neither was the actual
  cause of "resize down doesn't work" / "resize needs N+1" / "drops into
  the wrong cell."

  **Root cause:** `.month-day-cell:nth-child(N){grid-column:N;}` (style.css)
  counts each day cell's position among ALL of `.month-week-grid`'s
  children. `.month-week-bars` (`_calendar_month_grid.html`/
  `_calendar_fourweek_grid.html`) is rendered as a PRECEDING sibling of the
  day cells, but only `{% if week.bars %}` -- i.e. only in a week row that
  actually has a bar-worthy event. In exactly those rows, every
  `.month-day-cell` after it lands one `nth-child` index later than its own
  weekday: Monday's cell silently gets `grid-column:2` (Tuesday's slot),
  Tuesday's gets `grid-column:3`, and so on, with Sunday's cell falling off
  the explicit 1-7 rule set entirely and auto-placing back into column 1.

  Confirmed live, in a running instance, by dumping the actual DOM: a week
  row with a bar had its 7 `.month-day-cell`s in date order but
  `getBoundingClientRect().left` shifted one column right of where their
  own `data-date` said they should be, while the bar itself (laid out
  independently via `_week_bars`' own `col_start`/`col_span` math) sat at
  its own correct position -- so the bar and the day cells under it
  disagreed about which date lived where. Every `cellAtPoint` hit-test
  during a drag reads a cell's `data-date` directly, so this wasn't a
  hit-testing bug at all: a user dragging to what looked like the right day
  was, in any week containing a bar, always landing on a cell one column
  over from what they saw. This explains "wrong cell" outright, and
  "resize needs N+1" as a direct consequence (the visual target and its
  true date disagreed by exactly one column).

  **Fix, `style.css` only** (no template change -- both grid partials
  share this one rule block): `.month-day-cell:nth-child(N){...}` ->
  `.month-day-cell:nth-child(N of .month-day-cell){...}` for N in 1-7 --
  the CSS Selectors 4 "of <selector>" filter on `:nth-child`, which counts
  only among siblings matching `.month-day-cell`, so `.month-week-bars`
  (never itself a `.month-day-cell`) can no longer perturb the count.
  Verified live: reproduced the shifted-column DOM, confirmed the fix
  restores correct alignment, then re-ran an actual resize-grow drag
  (landed exactly on the day dropped on, no overshoot) and an actual chip
  move drag (same) against the running server -- not just reasoned about,
  actually clicked through this time.

  **Tests:** new `TestDragRound3DayCellColumnAlignment` in
  `test_calendar_month_bars.py` -- greps style.css for the `of
  .month-day-cell`-scoped rules (and asserts the old unscoped form is
  gone, since a leftover at equal specificity would be a cascade-order
  footgun) plus a precondition test locking in that `.month-week-bars`
  is still a preceding, conditional sibling in both templates (if that
  ever changes, this fix's own reasoning needs revisiting, not silent
  invalidation). `sw.js` `CACHE_NAME` bumped `v89` -> `v90`; `test_pwa_
  shell.py`'s pin updated. Full suite re-run across all 88 non-live test
  files (`test_caldav_bridge_live.py` excluded as always) in 5 batches --
  all green, 0 failures.

  **Process note, worth keeping:** two rounds of "read the code, form a
  hypothesis, ship it" both missed this because the bug wasn't in the file
  either round was looking at -- it was one CSS rule, several hundred
  lines away from the drag JS, that only manifests in weeks containing a
  bar. Connecting a live browser (once one became reachable) and actually
  dumping DOM rects took a few minutes and found it immediately. If a
  future calendar-drag report doesn't yield an obvious cause on first read,
  get a live browser in before iterating on hypotheses a second time.

- **Shipped:** 2026-09-08 -- same-day bug fix, round 2, direct live-browser
  report against the round-1 fix further below (2026-09-08 "same-day bug
  fix" entry): Month/4-Week bar resize was *still* unreliable after that
  fix ("resize down is buggy, most of the times it doesn't work" / "resize
  more sometimes needs to do N+1 to do N"), and a related complaint not
  previously reported: drag-to-move landing in the wrong cell -- for plain
  event/task chips too, not just bars.

  **No live browser reachable in this sandbox (same recurring gap every
  entry in this file notes), so this is a second round of reasoning from
  the code rather than a confirmed repro** -- flagged here explicitly
  rather than claiming certainty the round-1 report's own preceding entry
  didn't have either. Re-audited `calendar_month_drag.js` end to end and
  compared against how FullCalendar's own interaction plugin does hit-
  testing (coordinate-to-date math on every pointermove, no DOM traversal)
  -- confirmed the round-1 `cellAtPoint` geometry rewrite is the right
  architecture, so this pass didn't touch it again. Found three concrete,
  defensible defects instead:

  1. `.month-bar-resize-handle` was `width:8px` on a 16px-tall bar -- an
     8x16px pointer target, under normal touch/pointer-target sizing
     guidance. Missing it doesn't error: `setupBar`'s pointerdown mode
     detection (`e.target === handleLeft`) silently falls through to
     `mode:"move"` instead, so a missed resize-grab becomes a whole-bar
     move that, dropped back near the origin cell, is a silent 0-delta
     no-op -- indistinguishable from "nothing happened." This is the
     best-supported explanation for "resize down mostly doesn't work."
  2. Both resize guards (crossing the event's own other edge) were a bare
     `return` -- a correctly-detected, correctly-rejected resize gave zero
     feedback, same "looks broken" shape.
  3. `.month-day-cell.drop-hover` was a faint background tint only, no
     visible boundary -- best (unconfirmed) hypothesis for "grow needs
     N+1": the exact target-cell edge wasn't obvious enough to trust
     without a hard line, framed here as a hypothesis rather than a
     finding since it couldn't be verified against a real repro either.

  **Fixes, `calendar_month_drag.js` + `style.css`:** resize handles gained
  an invisible `::before` enlarging the actual hit box (top/bottom -2px,
  left/right -8px) without changing the handle's own thin visual line --
  pointer events on generated content still dispatch to the host element,
  so `e.target === handleLeft` still holds. Both resize guards now call
  `window.ccToast(...)` instead of silently returning. `.month-day-cell.
  drop-hover` gained `box-shadow:inset 0 0 0 2px var(--accent-neutral)`
  (same "solid fill + accent ring" vocabulary `.is-selecting` already
  uses) alongside its existing background tint. `setupItem`/`setupBar`'s
  `begin()` both now call `el.setPointerCapture(e.pointerId)` (try/caught,
  non-critical) -- defensive belt-and-suspenders matching FullCalendar's
  own `PointerDragging`, not the primary fix for anything reported since
  the move/end listeners were already on `document`. All four changes are
  shared by `setupItem` (plain event/task chips) and `setupBar` (bars) --
  both call the same `cellAtPoint`/use the same `.drop-hover` class, so
  the chip-drag "wrong cell" complaint is covered by the same fixes
  without a separate code path.

  **Tests:** new `TestDragResizeRound2Structural` in
  `test_calendar_month_bars.py` -- same "no JS unit-test harness for
  `static/*.js` in this repo" gap every prior JS-only calendar slice's own
  entry notes, so covered via `node --check` (syntax) plus source/CSS
  greps pinning the pointer-capture calls, the two toast calls, the
  widened resize-handle pseudo-element, and the strengthened drop-hover
  ring. `sw.js` `CACHE_NAME` bumped `v88` -> `v89`; `test_pwa_shell.py`'s
  pin updated. Full suite re-run across all 88 non-live test files (`test_
  caldav_bridge_live.py` excluded as always) in 7 batches (background
  processes don't survive across tool calls in this sandbox, same
  constraint every entry in this file already notes) -- all green, 0
  failures.

  **Next slice:** none mandated -- direct bug report, addressed as best as
  static reasoning allows. This is the SECOND round of "fixed, but never
  confirmed against a real repro" for this exact feature -- if it's
  reported broken a third time, stop reasoning from the code alone and
  either get a live browser into this sandbox or ask the user to open dev
  tools and report the actual `cellAtPoint`/mode values during a failing
  drag, rather than repeating the same "read the code, form a hypothesis,
  ship it" cycle a third time.

- **Shipped:** 2026-09-09 -- FullCalendar-parity interactions, slice 6 of
  6 (final slice of the arc; see `plans/open.md` § "Calendar:
  FullCalendar-parity interactions"): live month/week label + AJAX
  prev/next navigation for 4-Week and Week, replacing the old full-page-
  reload `<a href>` links. Month is deliberately NOT covered -- confirmed
  before writing any code that `month_view` has had no route decorator
  since `calendar_root_redirect` was added (bare `/calendar` always
  redirects to `/calendar/fourweek`), so there's no reachable page left to
  wire AJAX nav onto; `_calendar_month_grid.html`/`_month_view_context`
  are untouched.

  **Open decision, settled via AskUserQuestion (direct answer) before
  building:** Week's visible label is a date range ("Sep 07 - Sep 13,
  2026"), matching FullCalendar's own default over an ISO week number.
  4-Week's label follows the same date-range convention -- its own
  sr-only `<h1>` used to be a static "4-Week View" string with no date
  info at all, so this also fixes that gap, not just adds nav.

  **Backend (`routers/calendar.py`):** both `_four_week_view_context` and
  `_week_view_context` now compute a `label_text` string once (`"%b %d"`
  .. `"%b %d, %Y"`, en dash) and return it -- the same value now drives
  the sr-only `<h1>` (previously computed inline in the template,
  hand-duplicated), the new visible `#cal-nav-label` span, and the async
  region fragment's own `data-label-text`, so the three can never drift
  apart. `_calendar_fourweek_grid.html`/`_calendar_week_grid.html`'s root
  elements also gained `data-prev`/`data-next` (the existing
  `prev_start`/`next_start`/`prev_week`/`next_week` values) alongside
  their existing `data-date`/`data-label` -- everything a prev/next click
  needs to know for its *next* click is already on the freshly-swapped
  node, no second round-trip required.

  **Templates:** each page's prev/next `<a class="icon-btn">` gained a
  `cal-nav-prev`/`cal-nav-next` class (href unchanged -- still the real,
  bookmarkable full-page URL, and the no-JS/failure fallback); a new
  `<span class="cal-nav-label" id="cal-nav-label" aria-live="polite">`
  sits between them.

  **`async_calendar.js`:** new shared `bindCalNav(gridId, pageBase,
  refreshFn)`, called once each for the 4-Week and Week blocks (not
  Month). Intercepts a prev/next click, calls the region's existing
  `refresh*` function (now parameterized with an optional `dateVal`
  override -- defaults to the region's own current `data-date`, unchanged
  behavior for the pre-existing mutation-refresh call site) instead of
  following the link, then reads the freshly-swapped node's
  `data-label-text`/`data-prev`/`data-next` to update the visible label,
  `document.title`, and both links' hrefs for the next click.
  `history.pushState` keeps the URL bar/bookmarks in sync; a `popstate`
  listener makes the browser's own Back/Forward buttons re-run the same
  fetch-and-swap (reading `date_` back off `window.location.search`)
  instead of just changing the address bar with nothing reacting on
  screen. A failed nav falls back to a real `window.location.href`
  navigation, same "converge to server truth" pattern every other refresh
  failure in this file already uses. Week's existing scroll-position
  capture/restore (slice 5) is kept for a nav call too, not just a
  mutation refresh -- carrying the same time-of-day scroll position over
  when paging to a different week.

  **`style.css`:** new `.cal-nav-label` (600-weight, `--text-body`,
  `--fg-secondary`, ellipsis-truncated at 180px so a long range can't push
  the arrows/filter out of the header's fixed 48px strip) plus a
  `.page-header-narrow.has-banner` override matching the existing
  banner-mode treatment other actions-slot controls already have.

  **Bug caught before it shipped:** the first draft of both templates'
  own header comments referenced "the sr-only `<h1>`" in prose -- since
  Jinja doesn't strip HTML comments, that literal `<h1>` substring showed
  up in the rendered page and broke `test_page_header_narrow.py`'s
  "exactly one real `<h1>` per folded page" test (found by running that
  file, not by inspection -- worth remembering: never write a literal
  `<h1>`/`<h2>`/etc. tag name inside an HTML comment in these templates).
  Reworded to "the sr-only heading" in both files; re-verified 1 match
  each.

  **Tests:** new `test_calendar_nav_labels.py` -- `label_text` shape and
  that it moves with the window/anchor, the sr-only-`<h1>`-and-visible-
  label-share-the-same-text invariant, the new `cal-nav-*` classes, the
  region fragment's new data attributes, and (same "no JS unit-test
  harness for `static/*.js` in this repo" gap every prior JS-only calendar
  slice's own entry notes) `node --check` plus source greps pinning
  `bindCalNav`'s click-interception/pushState/popstate/dataset-driven-
  update/failure-fallback behavior and that Month's own block never calls
  it. A `TestMonthUntouched` class locks in the scoping decision above
  (no `label_text`/`data-prev`/`data-next` anywhere near Month's context
  or grid partial).

  `sw.js` `CACHE_NAME` bumped `v87` -> `v88`; `test_pwa_shell.py`'s pin
  updated. Full suite re-run in 10 sequential chunks (background
  processes don't survive across tool calls in this sandbox, same
  constraint every entry in this file already notes; `test_caldav_bridge_
  live.py` excluded as always): 301 + 220 + 338 + 211 + 181 + 218 + 196 +
  144 + 120 + 103 = 2032 passed, 0 failed (2012 + 20 net new).

  **Next slice:** none mandated -- this was the final slice of the
  "FullCalendar-parity interactions" arc (plans/open.md), now fully
  shipped end to end. No live-browser check yet either (same recurring
  gap every entry in this file already notes) -- this slice's AJAX
  nav/pushState/popstate wiring was verified structurally (JS reasoned
  about directly, rendered HTML inspected via direct router calls, full
  test suite green) but the actual click-through feel -- especially
  Back/Forward behavior and whether the label visibly flickers during the
  fetch -- has never been seen rendered. Worth being the first thing
  checked next session if a browser becomes reachable, given this arc's
  six slices have all shipped "structurally verified, never rendered."

- **Shipped:** 2026-09-09 -- FullCalendar-parity interactions, slice 5 of
  6 (see `plans/open.md` § "Calendar: FullCalendar-parity interactions"):
  Week view no longer resets scroll position on an async region refresh.

  **Root cause, confirmed exactly as open.md's own scoping note
  predicted:** `async_crud.js`'s `refreshRegion()` does `current.replaceWith
  (fragment)`, a wholesale swap of `#week-grid`. `.time-grid-wrap` (the
  actual `overflow-y:auto` scroll container, style.css) is a child of that
  swapped element, so the freshly-parsed fragment always started at
  `scrollTop: 0`, discarding whatever position the user had scrolled to
  before a create/move/etc. triggered a refresh.

  **Fix, entirely in `async_calendar.js`'s `refreshWeek()`:** before
  calling `ccApi.refreshRegion`, reads `.time-grid-wrap`'s current
  `scrollTop` off the still-attached `weekEl`. After the swap resolves,
  re-queries `#week-grid` (reassigning the outer `weekEl` -- previously
  this function was the one region-refresh closure in the file that
  *didn't* do this, unlike `refreshMonth`/`refreshFourweek`/`refreshDay`;
  brought in line with them as part of this fix, since the restore needs a
  reference to the newly-attached node anyway) and writes the captured
  value onto the fresh node's own `.time-grid-wrap`. Both the capture and
  the restore are null-guarded (no scroller found, or no scroll to
  restore) rather than assuming the element always exists. Scoped to Week
  only, per open.md's own slice split (Day has its own `.time-grid-wrap`
  but wasn't part of this slice's acceptance line -- not touched).

  **Tests:** new `test_calendar_week_scroll_restore.py`
  (`TestWeekScrollRestoreStructural`, 4 tests) -- same "no JS unit-test
  harness for `static/*.js` in this repo" gap every prior JS-only calendar
  slice's own entry notes, so covered via `node --check` (syntax) plus
  source greps pinning the specific capture/restore lines (including the
  null-guard conditions) so a future refactor can't silently drop the fix.
  No backend change, so no Python-side behavior to test beyond that.

  `sw.js` `CACHE_NAME` bumped `v86` -> `v87`; `test_pwa_shell.py`'s pin
  updated. Full suite re-run in 4 chunks of ~20-22 files each (background
  processes don't survive across tool calls in this sandbox, same
  constraint every entry in this file already notes; `test_caldav_bridge_
  live.py` excluded as always): 569 + 572 + 473 + 398 = 2012 passed, 0
  failed (2008 + 4 net new).

  **Next slice:** open.md slice 6 (final slice of this arc) -- live
  month/week label + AJAX prev/next navigation across Month, 4-Week, and
  Week, replacing today's full-page-reload `<a href>` links. Has its own
  open decision to settle first: for Week's visible label, an actual ISO
  week number ("Week 37") or a date range ("Sep 7 - 13")? FullCalendar
  itself defaults to a date range -- confirm via AskUserQuestion before
  building. No live-browser check yet either (same recurring gap every
  entry in this file already notes) -- this slice's scroll-preservation
  fix was verified structurally (JS reasoned about directly, full test
  suite green) but the actual "does the grid visibly stay put after a
  drag" feel has never been seen rendered.

- **Shipped:** 2026-09-09 -- FullCalendar-parity interactions, slice 4 of
  6 (see `plans/open.md` § "Calendar: FullCalendar-parity interactions"):
  Week view drag between the "All day" row and the timed grid, both
  directions -- FullCalendar's `allDayMaintainDuration` equivalent. Until
  now `calendar_week_allday_drag.js` only moved all-day items between days
  in the same row, and `calendar.js`'s timed-event drag stayed within the
  time grid; neither crossed the boundary, by design (the all-day script's
  own header comment said so).

  **Backend (`routers/calendar.py`), the one piece both directions share:**
  `POST /events/{uid}/reschedule` gained an optional `all_day` field --
  every earlier caller (this same endpoint, plus Month/4-Week's bar drag)
  only ever reschedules within one row/grid, so it never needed to flip the
  flag; omitting the field leaves the existing value untouched (`row =
  dict(existing)` already carries it forward). No new endpoint, per
  open.md's own scoping note.

  **`calendar_week_allday_drag.js` (all-day row -> timed grid):** `setupItem`
  now checks `.time-col` as a second valid drop-target type alongside
  `.allday-col` (`dropTargetAtPoint`, replacing the old allday-only
  `colAtPoint`). Only events are eligible -- a task chip (`data-due`) has no
  time-of-day due-date concept in this app, so a task dropped on the timed
  grid is a no-op, same as dropping on its own origin column already was.
  Dropping an event picks a start time from the drop's Y position within
  the target column (same PX_PER_HOUR/15-minute-snap model `calendar.js`
  already uses), preserves the event's own original duration when it has a
  real one (`data-start`/`data-end` diff, default 60 minutes otherwise),
  and sends `all_day: false`.

  **`calendar.js` (timed grid -> all-day row):** `setupEvent`'s move-mode
  `move()` now checks `.allday-col` hover FIRST, before its existing
  top/column tracking -- while hovering the all-day row it skips that
  tracking entirely (the element's on-screen top/height just stay wherever
  they last were) rather than trying to reparent an absolutely-positioned
  `.time-event` into the all-day row's normal-flow DOM mid-drag; a
  successful drop's full `#week-grid` region refresh re-renders it correctly
  server-side anyway, same "let the server re-render" reasoning every other
  lane/layout-affecting calendar drag in this app already follows. On drop,
  sends `all_day: true` with a time-stripped `start_at` (`${day}T00:00:00`)
  and `end_at: null`. Guarded to never fire mid-resize (`wasResize` check --
  crossing rows during a resize makes no sense). Day view's own `.allday-col`
  has no `data-date` (only one column exists there, no per-column date to
  disambiguate) -- falls back to the drag's own start column's date, so the
  same code incidentally also works on Day (calendar.js is loaded there
  too), a bonus not required by this slice's Week-only acceptance line.

  Both directions reuse the CSS this app already had --
  `.allday-col.drop-hover`/`.time-col.drop-hover` (style.css) predate this
  slice, no new rules needed.

  **Tests:** new `test_calendar_week_allday_boundary_drag.py`.
  `TestRescheduleEndpointAllDayField` (4 tests, direct router calls with a
  crafted `Request`/`receive`, same pattern `test_quick_capture.py` already
  uses for async JSON endpoints) locks in the new `all_day` field's
  omit/true/false behavior and the existing 404 path. No JS unit-test
  harness for `static/*.js` in this repo (same recurring gap every prior
  JS-only calendar slice's own entry notes) -- `TestDragScriptsStructural`
  (7 tests) covers both changed files via `node --check` (syntax) plus
  source greps pinning the specific new branches (`dropAllDayCol`,
  `wasResize` guard, `endDropOnTimedGrid`, the task no-op guard) so a future
  refactor can't silently drop one side of the merge unnoticed.

  `sw.js` `CACHE_NAME` bumped `v85` -> `v86`; `test_pwa_shell.py`'s pin
  updated. Full suite re-run in 9 sequential chunks (background processes
  don't survive across tool calls in this sandbox, same constraint every
  entry in this file already notes; `test_caldav_bridge_live.py` excluded as
  always): 313 + 391 + 273 + 163 + 266 + 226 + 153 + 123 + 100 = 2008
  passed, 0 failed (1997 + 11 net new).

  **Next slice:** open.md slice 5 -- Week view: stop resetting scroll
  position on add/move (`async_calendar.js`'s `refreshWeek()` needs to
  capture/restore `.time-grid-wrap`'s `scrollTop` around the region swap).
  Small and self-contained per open.md's own note ("could ride along with
  slice 4 if convenient" -- deliberately not bundled in here, kept as its
  own slice/commit instead). No live-browser check yet either (same
  recurring gap every entry in this file already notes) -- this slice's
  cross-boundary drag/drop was verified structurally (JS reasoned about
  directly, the shared endpoint's new field covered by direct router-call
  tests, full test suite green) but the actual pointer-drag feel, especially
  the "hover the sticky all-day header while the timed grid below it is
  mid-scroll" case, has never been seen rendered.

- **Shipped:** 2026-09-09 -- FullCalendar-parity interactions, slice 3 of
  6 (see `plans/open.md` § "Calendar: FullCalendar-parity interactions"):
  Month/4-Week's "+N more" overflow no longer navigates to Day view --
  clicking it opens an info toast listing the day's hidden events/tasks as
  click-through buttons, each opening that item's own edit modal directly.

  **Open decision settled first, via AskUserQuestion (direct answer):**
  build the list on `ccToast`'s `actions` array (keeps click-through),
  not a plain-text toast -- accepting the noted risk that `.toast-actions`
  was built for a 1-2 button Cancel/Confirm pair, not 3-6 stacked items,
  and would need its own styling.

  **Backend (`routers/calendar.py`):** `_month_day_cells` now also returns
  `overflow` -- the same-shaped tail of `rows` past `MONTH_MAX_VISIBLE_
  ITEMS` (previously only `overflow_count`, an int, existed). Same
  kind/event/task dicts as `rows`, same order -- `rows + overflow`
  reconstructs every event/task on the day with nothing dropped or
  duplicated.

  **Templates** (`_calendar_month_grid.html`/`_calendar_fourweek_grid.html`,
  same "one script serves either grid" pattern every slice in this arc
  follows): the "+N more" `<a href="/calendar/day/...">` is now a plain
  `<button class="month-more-link">`, with a sibling, inert `<template
  class="month-overflow-data">` listing each overflow item as an `<a
  data-modal href="...">title</a>` -- built with the exact same href logic
  the visible `day.rows` loop above it already uses (event vs. task URL,
  recurrence `occurrence_date` query param), so the two can never drift
  apart the way a second hand-written URL-builder would.

  **New `calendar_month_overflow.js`:** a single document-level delegated
  click listener on `.month-more-link` (same reasoning modal.js's own
  `[data-modal]` delegation comment gives) reads the sibling `<template>`'s
  anchors and fires `window.ccToast({ actions: [...] })`, one action per
  item, each calling `window.CCModal.open(href)`. No init()/rebind call
  needed after `async_calendar.js`'s region-refresh DOM swaps -- unlike
  `calendar_month_drag.js`'s `CCMonthGridDrag.init()`, this listener holds
  no element references between clicks. Wired in via a new `<script defer>`
  tag in both `calendar_month.html` and `calendar_fourweek.html`'s
  `extra_scripts` block (not added to `sw.js`'s `SHELL_ASSETS` precache
  list -- confirmed `calendar_month.js`/`calendar_month_drag.js` aren't
  there either; this repo's precache list is core shell assets only, not
  every page-specific script).

  **`style.css`:** new `.toast-overflow` variant -- `.toast-actions`
  stacks full-width instead of the default flex-end pair, each row
  left-aligned and ellipsis-truncated (same overflow feel `.month-item-
  title` already has in the grid itself) rather than wrapping, capped at
  `max-height:220px` with its own scroll for a day with many hidden items.

  **Tests:** new `TestOverflowItems` class in `test_calendar_month_bars.py`
  (2 tests) locks in `overflow`'s shape/order and that it's `[]` (not
  missing) when there's nothing to show. No JS unit-test harness for
  `static/*.js` in this repo (same recurring gap every JS-only change in
  this file notes) -- verified via `node --check` on the new file and a
  direct Jinja render of `_calendar_month_grid.html` with a fake overflow
  day dict (same ad hoc verification slice 1 used), confirming the
  `<template>` and its `data-modal` anchors actually appear in the
  rendered HTML with the right hrefs/titles.

  `sw.js` `CACHE_NAME` bumped `v84` -> `v85`; `test_pwa_shell.py`'s pin
  updated. Full suite re-run in the same 10-chunk pattern as the entry
  below: 313 + 215 + 296 + 220 + 113 + 245 + 219 + 119 + 127 + 130 = 1997
  passed, 0 failed (1995 + 2 net new).

  **Next slice:** open.md slice 4 -- Week view drag between the "All day"
  row and the timed grid, both directions. No live-browser check yet
  either (same recurring gap every entry in this file already notes) --
  this slice's toast/click-through wiring was verified structurally (JS
  reasoned about directly, a real Jinja render inspected, full test suite
  green) but never seen rendered or clicked.

- **Shipped:** 2026-09-08 -- same-day bug fix, direct report against the
  slice 2 entry below: bar resize was unreliable in a live browser --
  shrinking (dragging an edge inward) "most of the time doesn't work",
  growing (dragging an edge outward) "sometimes needs N+1 to do N" (drag
  one extra day further than the desired result requires).

  **Root cause:** `cellAtPoint` (`calendar_month_drag.js`, shared by both
  `setupItem` and the new `setupBar`) used `document.elementsFromPoint(x,
  y)` -- the full hit-test stack at that pixel, topmost first -- and
  walked it for the first element with a `.month-day-cell` ancestor. A bar
  being resized never actually changes its own on-screen box (only its
  separate ghost clone does, see slice 2's own entry below), so the
  pointer spends most of a shrink drag -- and the tail end of a grow drag
  -- hovering a point still geometrically covered by the ORIGINAL,
  un-resized bar. Which element that stack reported first for a given
  pixel then depended on the browser's own pointer-events/stacking
  resolution rather than anything this code controlled directly --
  unreliable enough in practice to explain both the "shrink mostly
  fails" and "grow is off by one" shapes of the report.

  **Fix:** `cellAtPoint` no longer touches DOM hit-testing at all --
  it's now a plain rectangle-containment scan over `cells` (every
  `.month-day-cell` on the grid, already collected in `init()`), checking
  each cell's own `getBoundingClientRect()` directly against the pointer's
  (x, y). This answers "which calendar day is the pointer over" as a pure
  geometry question, with no dependency on what any absolutely-positioned
  bar/ghost/handle happens to be drawn on top of that same pixel. Same
  function, same call sites (`setupItem`'s move logic included) -- no
  behavior change intended for plain chip dragging, which this bug never
  actually affected (a chip is a normal-flow descendant of its cell, so
  its own hit-test stack always had the cell as an unambiguous ancestor
  either way).

  `sw.js` `CACHE_NAME` bumped `v83` -> `v84`; `test_pwa_shell.py`'s pin
  updated. No new tests -- same "no JS unit-test harness for `static/*.js`
  in this repo" gap slice 2's own entry already notes; verified via `node
  --check` (syntax) and re-running the full suite for regressions (nothing
  Python-side changed). Full suite re-run in the same 10-chunk pattern as
  the entry below: 311 + 215 + 296 + 220 + 113 + 245 + 219 + 119 + 127 +
  130 = 1995 passed, 0 failed -- same total, no tests added/removed.

  **Next slice:** unchanged from the entry below -- open.md slice 3.
  Still no live-browser check available in this sandbox; this fix is
  reasoned from the code and the user's own description of the symptom,
  not confirmed against a real repro. Worth a direct follow-up ("does it
  feel right now?") before treating this as fully closed.

- **Shipped:** 2026-09-08 -- FullCalendar-parity interactions, slice 2 of
  6 (see `plans/open.md` § "Calendar: FullCalendar-parity interactions"):
  drag-move + edge-resize for Month/4-Week's spanning bars (slice 1's new
  `.month-bar` elements), plus the pointer-follow drag ghost, fixing the
  known temporary regression slice 1's own entry (below) flagged: whole-day
  drag-to-move on an all-day bar had stopped working because
  `calendar_month_drag.js`'s selector only ever matched the old
  `.month-event-item[data-uid]` chip markup, not the new `.month-bar`.

  **Backend (`routers/calendar.py`):** `_week_bars` now also returns
  `is_start`/`is_end` per bar segment -- whether that segment's left/right
  edge is the event's own real start/end, vs. a clip introduced by the
  week row's own bounds (a multi-week event gets one independently
  lane-assigned bar per week row it touches, per slice 1). Only a `True`
  edge should ever offer a resize handle; dragging a mid-event
  continuation segment's clipped edge back would silently rewrite a date
  that was never a real boundary.

  **Templates** (`_calendar_month_grid.html`/`_calendar_fourweek_grid.html`,
  identical change to both, same "one script serves either grid" pattern
  slice 1 established): each bar's title now sits in a `.month-bar-label`
  child span, flanked by `.month-bar-resize-handle.month-bar-resize-left`/
  `-right` -- rendered only when `bar.is_start`/`bar.is_end` (and never for
  a recurring event, same exclusion the whole-bar drag already has, for
  the same reason: a recurring master's own `start_at`/`end_at` covers the
  whole series, not one occurrence).

  **`calendar_month_drag.js`:** `cellAtPoint` rewritten to use
  `elementsFromPoint` instead of `elementFromPoint` -- a `.month-bar` is an
  absolutely-positioned SIBLING of the day cells (a separate stacked
  layer), not their DOM descendant the way a plain chip is, so the old
  `elementFromPoint(...).closest(".month-day-cell")` could never find the
  cell underneath a bar; the full hit-test stack can. Works identically
  for existing chips too (no behavior change there). New `setupBar`
  (mirrors `setupItem`'s click-vs-drag threshold and event-shift math,
  factored `postReschedule` shared across its three call sites) handles:
  move (grab the bar body, shifts `start_at`/`end_at` by the same
  whole-day delta `setupItem` already computes for chips), resize-left/
  resize-right (grab a handle, changes just that one date, guarded against
  crossing the event's own other end). A floating `.month-bar-ghost` clone
  (an exact visual copy of the bar, `position:fixed`+`pointer-events:none`
  so it doesn't defeat the `elementsFromPoint` hit-test) is spawned at
  drag-start and removed on drop -- for a move it tracks the pointer
  directly (offset by the original grab point); for a resize it stays
  pinned to the bar's own row and only the dragged edge follows the day
  cell currently under the pointer, snapped to that cell's own on-screen
  edge (same "snap to the grid, not the raw cursor" feel Week/Day's
  `.te-resize-handle` already has, one day instead of 15 minutes). The
  real bar fades to `opacity:.25` while its ghost is what's actually
  visible moving -- unlike Week/Day's `.time-event`, a bar can't move
  itself (it's positioned by `.month-week-bars`' percentage-based column
  math, not the pointer), so leaving it at full opacity in its original
  spot while a ghost renders elsewhere would look like two bars at once.

  **`style.css`:** `.month-bar-label` (block wrapper, same ellipsis
  truncation the anchor already had), `.month-bar-resize-handle`/`-left`/
  `-right` (8px edge grab zones, `cursor:ew-resize`, subtle hover tint),
  `.month-bar.dragging{opacity:.25}`, `.month-bar-ghost` (`position:fixed`,
  `pointer-events:none`, `z-index:50`, drop shadow) -- all bounded classes,
  no inline `style=`, same CSP constraint every other per-item value in
  this grid already follows.

  **Tests:** new `TestBarStartEndFlags` class in `test_calendar_month_bars.py`
  (3 tests) locks in `is_start`/`is_end` for a single-day bar, a bar fully
  inside one week, and the two segments of a week-boundary-spanning event
  (first segment: real start, clipped end; second: clipped start, real
  end). No JS unit-test harness for `static/*.js` in this repo (same gap
  every prior JS-only change in this file notes) -- verified via `node
  --check` on the changed file (syntax) and a direct Jinja render of
  `_calendar_month_grid.html` with a fake bar dict, confirming both handle
  spans and the label span actually appear in the rendered HTML. `sw.js`
  `CACHE_NAME` bumped `v82` -> `v83`; `test_pwa_shell.py`'s pin updated.

  Full suite re-run in 10 sequential chunks (background processes don't
  survive across tool calls in this sandbox, same constraint every entry
  in this file already notes; `test_caldav_bridge_live.py` excluded as
  always): 311 + 215 + 296 + 220 + 113 + 245 + 219 + 119 + 127 + 130 =
  1995 passed, 0 failed (1992 + 3 net new).

  **Next slice:** open.md slice 3 -- "+N more" overflow -> info toast
  instead of a Day-view link. Has its own open decision to settle first
  (plain `ccToast` text vs. its `actions` array for click-through, see
  open.md's own note) before writing code. No live-browser check yet
  either (same recurring gap every entry in this file already notes) --
  this slice's drag/resize/ghost interactions were verified structurally
  (JS reasoned about directly, a real Jinja render inspected, full test
  suite green) but the actual pointer-drag feel has never been seen
  rendered.

- **Shipped:** 2026-09-08 -- FullCalendar-parity interactions, slice 1 of
  6 (see `plans/open.md` § "Calendar: FullCalendar-parity interactions"
  for the full scoping of all six): backend lane-packing + spanning-bar
  rendering for Month + 4-Week, no drag/resize yet (that's slice 2).

  **Reverses `_is_bar_worthy`'s 2026-08-08 "flat per-day list" design for
  all-day events only.** `_bucket_month_items` (routers/calendar.py) no
  longer buckets all-day events per date -- it returns the raw bar-worthy
  event list, which a new `_week_bars` lane-packs into one continuous bar
  per week row an event touches (clipped to that week's 7-day bounds, a
  separate independently-lane-assigned bar per week row for an event that
  spans a week boundary). Standard interval-graph greedy lane assignment:
  events sorted by (clipped start day, longest-span-first, title
  tiebreak), each placed in the first lane whose last bar ends before this
  one starts, no fit opens a new lane. `_month_day_cells` dropped the
  `all_day_by_date`/`kind:"all_day"` row entirely -- its flat per-day list
  (`day["rows"]`, capped at `MONTH_MAX_VISIBLE_ITEMS`) is now timed
  events + tasks only; bars aren't subject to that cap or counted in
  `overflow_count`. Timed *multi-day* events are unaffected -- still
  repeat as a per-day text row, only `all_day` earns a bar (unchanged
  `_is_bar_worthy` rule). `_month_grid`/`_four_week_grid` each week dict
  now carries `bars` (list) and `lane_count` (int, capped at
  `MONTH_MAX_BAR_LANES=8`) alongside `days`.

  **Templates:** `_calendar_month_grid.html`/`_calendar_fourweek_grid.html`
  each gained a `.month-week-bars` layer (absolutely positioned, one per
  week row, rendered before that week's day cells) with one `<a
  class="month-bar ...">` per bar; every day cell's `.month-day-bottom`
  gained a `month-bars-offset-{{ week.lane_count }}` class reserving the
  matching empty space at its top so the bar layer (a grid sibling, not a
  child of any one day cell) can never visually overlap the timed-event/
  task rows below it -- the specific failure mode the 2026-08-08 rework's
  own comment warned a layered design must not reintroduce; this
  reintroduces layering for all-day events only, with the offset class as
  the fix. `style.css`: `.month-bar-col-1..7`/`.month-bar-span-1..7`/
  `.month-bar-lane-0..7`/`.month-bars-offset-0..8` are bounded static
  classes (no inline `style=`, consistent with `.month-day-cell`'s own
  nth-child convention -- CSP has no `'unsafe-inline'` on style-src,
  audit-fixes-2.0.md item 11) driven by `_week_bars`'/`_month_grid`'s
  Python-side column/lane/offset math.

  **Known, temporary regression, documented in `calendar_month_drag.js`'s
  own header comment:** whole-day drag-to-move on an all-day event no
  longer works -- it previously matched `.month-event-item[data-uid]`,
  but a bar is `.month-bar`, a different class this script's selector
  doesn't reach. Single-day timed events and due-date task chips are
  unaffected. Slice 2 ("Drag-move + edge-resize for bars, plus the
  pointer-follow drag ghost") retargets this same delta-shift logic at
  `.month-bar` elements -- deliberately not fixed in this slice, per
  open.md's own slice split.

  **Tests:** `test_calendar_month_bars.py` substantially rewritten (the
  old file's whole premise -- asserting the *absence* of bars -- is
  exactly what this slice reverses); new `TestBars` class covers
  single/multi-day bars, week-boundary wrapping (two independent bars,
  each clipped to its own week), non-overlapping bars sharing lane 0,
  overlapping bars getting different lanes, longest-bar-wins-lane-0
  tiebreak, and lane reuse after a bar ends. `test_calendar_fourweek.py`'s
  two bar-dependent tests rewritten to assert a bar instead of a repeated
  row. No other test file depended on the old `kind:"all_day"`/
  `.month-all-day` shape (confirmed by grep before editing) -- Week's own
  `test_calendar_allday_strip.py` is untouched, out of scope (Week isn't
  part of this slice).

  `sw.js` `CACHE_NAME` bumped `v81` -> `v82` (style.css,
  calendar_month_drag.js, both grid partials changed); `test_pwa_shell.py`
  pin updated. Full suite re-run in 4 sequential chunks (background
  processes don't survive across tool calls in this sandbox, same
  constraint every entry in this file already notes, `test_caldav_bridge_
  live.py` excluded as always): 819 + 488 + 391 + 294 = 1992 passed, 0
  failed -- same total as before this slice (net: old file's ~20 tests
  replaced by ~30 new ones in test_calendar_month_bars.py, a few rewritten
  in test_calendar_fourweek.py, no other file's count changed).

  **Next slice:** open.md slice 2 -- drag-move + edge-resize for bars
  (retargeting `calendar_month_drag.js`'s delta-shift logic at
  `.month-bar`, fixing the regression noted above as part of the same
  work) plus the pointer-following drag ghost (new, for both move and
  resize). Slice 3 ("+N more" overflow -> info toast) has its own open
  decision to settle first (plain `ccToast` text vs. `actions` array for
  click-through) -- see open.md. No live-browser check yet either (same
  recurring gap every entry in this file already notes) -- this whole
  slice was verified structurally (rendered HTML/CSS reasoned about
  directly, full test suite green), never rendered.

- **Shipped:** 2026-09-09 -- sixth same-day follow-up, direct request:
  "let's just remove offline mode. please. purge it." After two rounds of
  UI fixes against direct screenshot reports (the two entries below), the
  whole client-side Offline Mode feature was deleted outright rather than
  continuing to polish it. Scoped first via AskUserQuestion: client-side
  only (the `/offline` page, its Quick Add builder, the local IndexedDB
  mirror/write/sync scripts, the service worker's offline navigation
  fallback) -- the server-side sync engine (`src/offline_sync.py`,
  `routers/sync_api.py`, the HLC/conflict-resolution logic, its DB tables)
  and the Sync card + cleanup controls on Settings > Data & Maintenance
  were explicitly kept out of scope, since none of it depends on the
  client page/files existing.

  **Deleted outright:** `templates/offline.html`, `templates/
  _offline_quick_add.html`, and all six `static/offline_*.js` files
  (`offline_shell.js`, `offline_db.js`, `offline_sync_client.js`,
  `offline_write.js`, `offline_status.js`, `offline_quick_capture.js`).
  `routers/pwa.py`'s `GET /offline` handler removed (module docstring
  rewritten -- `/sw.js`/`/favicon.ico` untouched). `base.html`'s three
  already-dead-commented-out `<script>` tags for the three globally-loaded
  offline scripts removed (dead cleanup, not a behavior change -- they were
  inert since the 2026-09-07 performance pass). `sw.js`: `/offline` and
  the six `offline_*.js` entries dropped from `SHELL_ASSETS`; the navigate
  handler's `caches.match("/offline")` fallback on a failed fetch removed
  (a failed navigation now just fails, same as with no service worker
  installed -- this whole mechanism has been inert anyway since `pwa.js`'s
  registration call is itself commented out in `base.html`); `CACHE_NAME`
  bumped `v80` -> `v81`.

  **Discovered mid-purge, outside the original scope but a direct
  consequence of it:** Settings > Data & Maintenance's Sync card had a
  "Force sync" button (`data-action="force-sync"`) that only worked by
  calling `window.CCOfflineSync.syncNow()` -- defined by the now-deleted
  `offline_sync_client.js`. It already had a defensive `if
  (!window.CCOfflineSync)` guard (no crash, just an error toast), but
  there's no such thing as forcing a client push/pull round with no client
  engine to run it from -- removed the button (`settings_data_maintenance.
  html`) and its dead wiring (`data_maintenance.js`'s `forceSyncFromServer`
  + delegated click listener) rather than leave a control that could only
  ever show "Sync engine not available." Everything else on that page
  (the Sync card itself, its status/meta text, "Clean up now"/sync-gc,
  export/import) is untouched, per the agreed scope.

  **Tests:** `test_pwa_shell.py` rewritten -- removed `TestOfflineShell`,
  `TestLocalReadPath`, `TestLocalWritePath`, `TestOfflineToolbar`, and the
  client-side halves of `TestSyncEngine`/`TestTombstoneGc` outright; the
  three tests in those last two classes that were actually server-side
  (`test_data_health_sync_summary_reflects_real_sync_devices`,
  `test_settings_data_maintenance_page_shows_sync_cleanup_controls`,
  `test_scripts_data_health_cli_has_a_sync_gc_subcommand`) relocated to
  `test_data_health.py` (`TestHealthSummary`, `TestSettingsDataMaintenance
  Page`, and a new `TestDataHealthCli`) since they never depended on any
  deleted file. Added a new `TestOfflineModeFullyRemoved` class asserting
  the files/route are actually gone from disk, not just disconnected, and
  revived the long-`DISABLED`-commented `TestRouterWiring` as a real test
  (routes `/sw.js`/`/favicon.ico` present, `/offline` absent) instead of
  dead commented-out code. `test_toast_rework.py`'s `TestSyncStatusToasts`
  (tested `offline_status.js`'s rendering) removed. Net test count: 2023 ->
  1985 (-38: -41 deleted across both files, +3 relocated to
  `test_data_health.py`, +4 new in `TestOfflineModeFullyRemoved` --
  arithmetic doesn't need to net to zero here, unlike a pure refactor,
  since real functionality was deleted, not just moved). Full suite
  re-run in the same 8-chunk pattern as the two entries below: 301 + 392 +
  274 + 163 + 260 + 228 + 160 + 207 = 1985 passed, 0 failed.

  **Next slice:** none mandated -- direct request, fully shipped. No
  offline-related "next slice" carries forward from the two entries below
  anymore (the deferred "real offline read surface" they mention is moot
  now that the feature is gone entirely). Still worth a real live-browser
  check that nothing else silently depended on `window.CCOffline*`
  globals beyond the one "Force sync" case already found and fixed here --
  this was found by grep, not by clicking through the app in a browser
  (still unreachable in this sandbox).

- **Shipped:** 2026-09-09 -- fifth same-day follow-up, direct report against
  a second screenshot of the just-collapsed Offline Mode page: still didn't
  match the rest of the app, six concrete complaints. Fixed all six:

  1. **Told the user it's offline twice** ("Offline Mode" title + a separate
     `.offline-indicator` badge beside it, same fact). Badge removed
     outright (`.offline-indicator` CSS deleted too, confirmed unused
     elsewhere via grep); its message merged into the one hint line below
     the header, which is now the page's only "you're offline" statement
     (`TestOfflineToolbar::test_offline_page_says_youre_offline_exactly_
     once` locks this in against the *rendered* body, not raw template
     source, since the source's own header comment mentions the old class
     name in prose).
  2. **Two competing headings** ("Offline Mode" then a bold "+ Quick Add"
     right below it). The Quick Add card's title now uses `.widget-header`'s
     existing "quiet card-header label" convention (15px, weight 600,
     hairline border-bottom) instead of `text-title2` -- same fix the
     2026-08-30 widget-header design pass already applied everywhere else,
     just never carried over to this page.
  3. **"The rest should be card widgets too."** `_offline_quick_add.html`'s
     builder now renders inside a real `.card` (`class="card offline-
     quick-add-builder"`) instead of a bespoke lookalike box with its own
     background/border/radius -- same surface every dashboard widget and
     Settings status-card already uses.
  4. **Buttons not "appearing correctly like on modal windows."** Root
     cause: the footer was missing the `<span class="spacer">` every real
     `_modal_footer.html` puts between its back/cancel and primary buttons
     to split them left/right -- Cancel and Add were reading as stuck
     together on the left. Added the spacer; `.modal-footer .spacer{flex:1}`
     already existed and just had nothing using it here.
  5. **"The labels dropdown doesn't work."** Root-caused, not just
     restyled: a Labels selection in this builder never actually applied to
     the created entity (label ops don't flow through the offline field-HLC
     write path at all) -- the old code only admitted this *after* submit,
     via an "(labels can't be added offline)" footnote. A control whose
     selection silently does nothing is a real bug, not a look-and-feel
     one. Removed the Labels field from both the task and event fieldsets
     entirely (`offline_shell.js` no longer fetches `getAllTasks`/
     `getAllEvents` either, since that was the only reason it read them);
     left the task/event/contact/note forms otherwise unchanged. Also fixed
     while in the same markup: `<fieldset>`'s default browser border/
     padding (never reset before) was drawing an unrelated second box
     around the Title/Due Date group inside the already-bordered card --
     `.offline-entity-fields{border:none; padding:0; margin:0;}` now.
  6. **"No scrollbar - flex."** `offline.html` adopted `main-shell`/
     `main-shell-body` -- the same "fits the viewport, scrolls internally"
     shell Tasks/Contacts/Notes/Dashboard already use (2026-09-07 pass)
     -- instead of relying on whole-page scroll, which this page had never
     opted into.

  `sw.js` `CACHE_NAME` bumped `v79` -> `v80` (`offline.html`, `_offline_
  quick_add.html`, `offline_shell.js`, `style.css` all changed again).
  `test_pwa_shell.py` gained 4 tests locking in items 1/2/4/5/6 above
  (`test_offline_page_says_youre_offline_exactly_once`,
  `test_offline_page_uses_the_shared_flex_shell`,
  `test_offline_quick_add_footer_splits_buttons_like_a_real_modal`,
  `test_offline_quick_add_has_no_labels_field`), plus two existing tests
  updated for the removed `getAllTasks`/`getAllEvents` reads and the new
  `.card`/`.widget-header` markup. Net test count 2019 -> 2023 (+4). Full
  suite re-run in the same 8-chunk pattern as the entry below: 301 + 392 +
  271 + 163 + 260 + 266 + 160 + 210 = 2023 passed.

  **Next slice:** same as the entry below's -- a real offline *read*
  surface, still deliberately not started. No live-browser check yet
  either; this is now two rounds of direct UI complaints against
  screenshots that were only fixed by reasoning about markup/CSS, never
  seen rendered -- worth being the first thing done next session if Chrome
  or a sandbox browser becomes reachable.

- **Shipped:** 2026-09-09 -- fourth same-day follow-up, direct request
  (with a screenshot): the Offline Mode page's UI was "wrong," specifically
  called out as the reason offline support had been effectively shelved
  (its four scripts have sat dead-commented-out since the 2026-09-07
  performance pass, per that entry's own note). Scoped down first via
  AskUserQuestion: fix the Quick Add UI only, dropping the rest of the page
  rather than trying to fix the whole five-tab surface at once.

  **Collapsed `offline.html` from a five-tab page (Dashboard/Calendar/
  Tasks/Contacts/Notes, each with its own read-only IndexedDB-mirror list)
  to a single focused screen**: the offline indicator + a one-line "last
  synced / N changes waiting to sync" summary + the Quick Add form, nothing
  else. The tab bar (`offline-main-tabs`), all five `#offline-*` panel
  render targets, and their empty-state markup are gone. Re-adding a real
  offline *read* surface (browsing local tasks/events/contacts while
  offline) is left for a separate future slice, not bundled into this UI
  fix -- this pass is Quick Add only, per the direct scoping decision.

  **Removed the "Quick Capture Syntax" preview textarea** from
  `_offline_quick_add.html` -- flagged directly as confusing. Root cause
  matched the complaint: it displayed a capture string generated from the
  visual fields, but `offline_shell.js`'s submit handler always read those
  fields directly and never parsed the textarea back in, so it was pure
  decoration with no function, just an extra thing to look at.

  `offline_shell.js` rewritten from ~520 lines (five-panel render + tab
  wiring + per-row task complete/delete handlers) down to ~190: it now
  only reads the mirror to compute the sync summary and populate the label
  picker (`getAllTasks`/`getAllEvents` still called for label aggregation,
  `getLastSyncedAt`/`getOutboxCount` for the summary line), plus the
  Quick Add builder's entity-type toggle and submit-to-`CCOfflineWrite`
  wiring, unchanged in substance. `wireTabs`/`wireWriteHandlers` (the
  per-row complete/delete click handlers for a task/contact/note list that
  no longer renders) removed outright. `style.css` lost the now-dead rules
  those five panels/tabs used (`.offline-main-tabs`, `.offline-main-panel`,
  `.offline-dashboard-grid/-card`, plus an already-orphaned older trio from
  a superseded 2026-08-18 rework, `.offline-tabs`/`.offline-panels`/
  `.offline-quick-capture-*` -- confirmed dead via grep before removing),
  gaining a small `.offline-page` max-width wrapper so the lone form
  doesn't stretch edge-to-edge on wide viewports.

  `sw.js` `CACHE_NAME` bumped `v78` -> `v79` (`offline_shell.js`/
  `style.css` both changed). `test_pwa_shell.py` updated throughout --
  removed/rewrote every assertion tied to the old tab bar, the five panel
  IDs, the per-row task write hooks, and the capture-text box; added
  negative assertions (`"data-offline-main-tab" not in html"`,
  `"offline-capture-text" not in script`, etc.) so a regression back to
  either would be caught. Net test count unchanged (2019 -> 2019): two
  tests renamed/repurposed in place, none added or removed. Full suite
  re-run in 8 sequential chunks of ~10 files: 301 + 392 + 271 + 163 + 260 +
  262 + 160 + 210 = 2019 passed, same total as the entry below.

  **Repo housekeeping note, still unresolved:** the same ~13-file dirty
  working-tree breadcrumb refactor flagged in the 2026-09-08 entry further
  below (`settings.py` + several Settings templates + `test_settings_
  radicale.py`/`test_settings_time_blocks.py`, `_settings_breadcrumb.html`
  deleted) is still sitting uncommitted and untouched -- confirmed via
  `git status` before committing this slice, deliberately excluded from
  this commit (only the 6 files this slice actually touched were staged:
  `offline_shell.js`, `style.css`, `sw.js`, `_offline_quick_add.html`,
  `offline.html`, `test_pwa_shell.py`). Still worth asking directly next
  session whether that other work is wanted or should be reverted.

  **Next slice:** the deferred larger piece -- a real offline *read*
  surface (browsing local tasks/events/contacts/notes while offline)
  redesigned with the same "single clear screen" standard this pass just
  applied to Quick Add, rather than reviving the old five-tab mirror
  wholesale. Not scoped into a concrete diff yet; worth an AskUserQuestion
  on shape (one combined list vs. separate screens per entity type) before
  building. No live-browser check yet either (same recurring gap every
  entry in this file already notes) -- worth being the first thing done
  next session if Chrome or a sandbox browser becomes reachable, given
  this is a direct UI complaint that was only verified structurally here.

- **Shipped:** 2026-09-09 -- third same-day follow-up, direct request:
  "Delete Everything" -> "Delete" on the purge confirm toast's button.
  Removed the explicit `confirmLabel` override entirely rather than
  hardcoding the string "Delete" -- `ccConfirmSheet`'s own default
  parameter is already `"Delete"` (`static/toast.js`), the exact label
  every other confirm toast in the app already shows, so this now reads
  as "use the standard label" rather than "coincidentally match it."

  `sw.js` `CACHE_NAME` bumped `v77` -> `v78`; `test_pwa_shell.py`'s pin
  updated. No test asserted the old label text (confirmed by grep), so
  no other test changes. Full suite re-run in the same 6-chunk pattern:
  434 + 485 + 282 + 360 + 248 + 210 = 2019 passed, same total as the
  entry below.

  **Next slice:** none mandated -- direct request, fully shipped.

- **Shipped:** 2026-09-09 -- second same-day follow-up, against a
  screenshot of the new purge confirm toast: shorten the description,
  and fix the two buttons not lining up under the typed-phrase input
  box above them.

  Message shortened: "This deletes every task, event, contact, label,
  habit, and published list. Backups already saved to the server (Backup
  card) are kept -- everything else is gone for good." -> "Deletes every
  task, event, contact, label, habit, and published list. Backups are
  kept." Confirm button label shortened too, "Permanently Delete
  Everything" -> "Delete Everything" -- it was wide enough on its own to
  be most of what made the button row look uneven against the input
  above it.

  Root cause of the alignment complaint: `.toast-actions` (the shared
  Cancel/Confirm row every confirm toast uses) is `justify-content:
  flex-end` -- fine for the plain confirm toast's normal short labels
  (default "Delete"), but on this longer-label variant the two buttons
  together got wide enough to visually read as spanning the toast, just
  unevenly (packed right, empty gap on the left) rather than lining up
  with the input's own left/right edges above them. Fixed with a
  variant-scoped override rather than touching the shared rule every
  other confirm toast in the app already relies on: new
  `.toast-confirm-typed .toast-actions{justify-content:stretch}` +
  `.toast-confirm-typed .toast-action{flex:1 1 0}` makes the two buttons
  split the row evenly, edge-to-edge, flush with the typed-phrase
  input's own width (`style.css`, right after `.toast-typed-input`).

  `sw.js` `CACHE_NAME` bumped `v76` -> `v77`; `test_pwa_shell.py`'s pin
  updated. No test text asserted the old copy/label strings (confirmed by
  grep before editing), so no test changes needed beyond the version pin.
  Full suite re-run in the same 6-chunk pattern: 434 + 485 + 282 + 360 +
  248 + 210 = 2019 passed, same total as the entry below (no tests
  added/removed).

  **Next slice:** none mandated -- direct request, fully shipped. Still
  worth the same real live-browser check the entry below already flags
  (type the phrase, confirm the layout actually reads right at real
  viewport widths) -- this whole toast has only ever been verified
  structurally/by reasoning about CSS, never rendered.

- **Shipped:** 2026-09-09 -- same-day follow-up direct request: "Reset
  database (purge all)" converted from a standalone modal dialog to a
  floating confirm toast, plus a direct question about whether purge
  deletes backups (it never did -- see below).

  **Backups were already safe.** Read `db.purge_all_data` (db.py) and
  `data_health.py` end to end before changing anything: the purge only
  runs `DELETE FROM` against this app's own SQLite tables (tasks, events,
  contacts, labels, habits, etc.); backups are `backup-*.json` files on
  disk in a separate directory, discovered by globbing
  (`data_health.list_backups`), with verification results cached in a
  sidecar file next to each one -- nothing in the purge path opens,
  globs, or touches that directory. No logic changed here; the new
  confirm toast's own copy now says this explicitly instead of the old
  modal's vaguer "there is no backup unless you made one yourself."

  **Modal -> toast**, keeping the typed "DELETE ALL" gate (direct choice
  over simplifying to the plain Cancel/Delete confirm every other
  destructive action uses -- this is the one truly irreversible,
  everything-in-the-app action on the page, worth the extra step). New
  `typedConfirm` option on `ccToast`/`ccConfirmSheet` (`static/toast.js`):
  renders an inline text input in the persistent confirm toast, any
  action marked `gated: true` starts disabled, and only the exact
  `matchValue` re-arms it -- the same arm/disarm behavior the old modal's
  server-disabled-button + delegated-input-listener pair had, just owned
  by the reusable toast component now instead of one page's own script.
  Enter-to-submit while armed included for parity with the old form.

  The "Reset database" menu item is now a plain `<button
  data-action="purge-all">` (`data_maintenance.js`), not a link to a
  modal page -- opens the confirm toast, and on confirm does a plain
  `fetch` POST to the unchanged `/settings/purge-all` (session/cookie
  invalidation logic untouched) followed by `window.location.reload()`
  (still carries the forced re-login redirect when auth is enabled, since
  the reload re-requests the current URL without the now-invalid
  cookie). `purge_modal.html` deleted outright; its GET
  `/settings/purge-confirm` route removed from `routers/settings.py` --
  it was only ever reachable from this one in-page trigger, nothing
  external ever linked to it, so no redirect-for-old-bookmarks was kept
  (contrast the `/settings/data-health` style redirects elsewhere in this
  file, which stay because those WERE real prior URLs).

  **Progressive-enhancement note, stated plainly rather than glossed
  over:** this action is now 100% JS-dependent end to end -- with no JS
  there's no page to fall back to at all, just an inert button. Same
  practical outcome the old modal already had (its submit button shipped
  server-disabled and only JS could ever arm it, so completing a purge
  already required JS), but previously at least the warning text was
  reachable as a real page; now it isn't. `data_maintenance.js`'s own
  header comment was rewritten to say this outright instead of the
  now-inaccurate "every surface works without this script" it used to
  claim for all three dialogs.

  `_modal_footer.html`'s `footer_primary_disabled`/
  `footer_primary_extra_attr` params (added 2026-08-30 specifically for
  this modal) have no caller left anywhere in the templates tree --
  confirmed by grep before deciding what to do with them. Left the
  mechanism itself in place (generic, harmless, and this shared partial
  is used by many other modals) but rewrote its docstring so it no longer
  points at a deleted file as a live example.

  `sw.js` `CACHE_NAME` bumped `v75` -> `v76` (`toast.js`,
  `data_maintenance.js`, `style.css` all changed); `test_pwa_shell.py`'s
  pin updated. Test changes: removed the one test that called the now-gone
  `purge_confirm_page` route directly and the one asserting the old
  document-level `input` listener (that gate moved into `toast.js`, no
  longer delegated at the page level); added a new `TestPurgeAllConfirm
  Toast` class in `test_data_health.py` (4 tests: trigger markup, the
  confirm/fetch wiring, the arm/disarm gate in `toast.js`, and a direct
  grep-the-source check that `purge_all_data` never references
  `backups_dir`/`glob`/`unlink`/`rmtree` -- the safety property behind
  the toast's own copy, pinned so a future edit can't silently reintroduce
  backup deletion without a test catching it). Net +2 tests across the
  suite (-1 removed test in `test_phase8_settings_hub.py`, +3 net in
  `test_data_health.py`).

  Full suite re-run in the same 6-chunk pattern: 434 + 485 + 282 + 360 +
  248 + 210 = 2019 passed (2017 + 2 net new), no failures.

  **Next slice:** none mandated -- direct request, fully shipped. Worth a
  real live-browser check once one is reachable (type the phrase, confirm
  the button arms/disarms, confirm the purge actually runs and reloads)
  -- same recurring verification gap every entry in this file already
  notes. The repo-housekeeping note from two entries below (unrelated
  uncommitted breadcrumb refactor sitting in the working tree) is still
  unresolved, still untouched by this slice.

- **Shipped:** 2026-09-09 -- direct request, second of the two agreed
  Data & Maintenance slices from the entry below: the `?note=`/`?error=`
  redirect banner now shows as a `ccToast` instead of static page text,
  the same floating-notification pattern every delete/archive elsewhere
  in the app already uses (`app.js`).

  Deliberately kept the server-side redirect-with-query-param shape
  entirely intact rather than converting all nine of this page's POST
  routes to fetch-based submits -- that's what keeps every action a plain
  form post that still works with no JS at all (this file's own
  "progressive enhancement only" header comment). The banner
  `settings_data_maintenance.html` already rendered from
  `request.query_params` is now the explicit no-JS fallback (still
  renders server-side, unchanged text/wording), tagged
  `data-dm-flash="note"` / `data-dm-flash="error"`. New
  `data_maintenance.js` block, on `DOMContentLoaded`: if `window.ccToast`
  exists, fire it with the banner's own text as the message (variant
  `error` for the error case, default for note -- default's own "Done"
  title reads fine against messages like "Compacted and reindexed the
  database."), remove the banner element, and strip `note`/`error` from
  the URL via `history.replaceState` so a refresh or shared link doesn't
  replay the same message. If `ccToast` isn't available for any reason,
  the banner is simply left alone -- a real fallback, not dead markup.

  `sw.js` `CACHE_NAME` bumped `v74` -> `v75` (data_maintenance.js
  changed); `test_pwa_shell.py`'s pin updated. No new tests -- same "no
  JS unit-test harness for `static/*.js` in this repo" gap every other
  JS-only fix in this file already notes; verified via `node --check` on
  both changed JS files (syntax) and the full suite for regressions on
  the server-rendered banner text/attributes, which is unchanged.

  Full suite re-run in the same 6-chunk pattern as the entry below:
  434 + 482 + 282 + 361 + 248 + 210 = 2017 passed, same total, no tests
  added/removed.

  **Next slice:** none mandated -- both agreed slices from the entry
  below are now shipped. Worth a real live-browser check once one is
  reachable (trigger an action, confirm the toast fires and the banner
  never flashes visibly first) -- same recurring verification gap every
  entry in this file already notes. The repo-housekeeping note in the
  entry below (unrelated uncommitted breadcrumb refactor sitting in the
  working tree) is still unresolved, still untouched by this slice.

- **Shipped:** 2026-09-08 -- direct request: audit + first fix pass on
  Data & Maintenance (`settings_data_maintenance.html`), against a direct
  ask to check the page for standards compliance -- icons on every
  action, no repeated actions, on-page text vs. toast notifications, and
  more minimal status-card text. Audited first (findings only, no code),
  then implemented the first of two agreed slices: dedupe + minimal card
  text. The toast-notification slice (replacing the `?note=`/`?error=`
  redirect banner with `ccToast`) is deliberately deferred, not started.

  **Four verbatim-duplicate actions removed**, each was the exact same
  endpoint/URL offered under two different labels in two different status
  cards' menus -- one home per action now:
  - "Verify latest backup" (Database card, called `/settings/data-health/
    verify` with no filename, which just falls back to the latest backup
    anyway) dropped in favor of the Backup card's "Verify integrity"
    (same endpoint, explicit filename).
  - "Clean up sync data" (Database card) dropped in favor of the Sync
    card's "Clean up now" -- both posted to `/settings/data-health/
    sync-gc`.
  - "Force sync" (Database card, `data-action="force-sync"`) dropped in
    favor of the identical button already in the Sync card.
  - "Restore a file..." (Backup card, `/export/import-modal`) dropped in
    favor of the Sync card's "Import data..." -- same dialog.

  The Database card's now-empty "Clean up sync data / Force sync"
  `action-menu-section` was removed entirely rather than left as an empty
  divider.

  **Status-card meta text trimmed**, per "I would like to have the text
  inside status-cards to be more minimal": dropped the redundant
  "Last backup:" label prefix (the card is called Backup, the status pill
  above already says Verified/Not verified/etc.); dropped the "Not yet
  verified" meta line entirely for the not-yet-verified state, since the
  status pill directly above it already says exactly that with no
  additional information in the meta line; shortened "Last checked" ->
  "Checked", "Cleanup last ran" -> "Last cleanup", "Sync cleanup not run
  yet" -> "No cleanup yet", "No backups yet -- \"Backup now\" saves one on
  the server." -> "No backups yet." (the affordance is the menu itself,
  doesn't need re-explaining in the meta line).

  Icons audited separately, no change needed -- every actual clickable
  action (buttons, action-menu items, links) already carries an icon
  consistently; the two `<select>` autosubmit rows (auto-archive,
  sync retention) have none, but they're inline settings controls, not
  menu actions, and no other Settings page in this app puts an icon on a
  bare select label either.

  Two structural tests (`test_data_health.py`, `test_phase8_settings_
  hub.py`) had hardcoded "this link renders twice" counts for the
  now-deduped `/export/import-modal` href -- updated `== 2` -> `== 1`
  at both sites. Two more assertions rewritten rather than just
  adjusted, since the thing they were checking for (`"Last backup: ..."`,
  `"Not yet verified"`) no longer exists as literal text -- see
  `test_backup_facts_are_human_readable_and_only_in_the_backup_card` and
  `test_verification_state_flips_the_card_meta_line`. No `sw.js` bump --
  template + tests only, no static JS/CSS changed.

  **Repo housekeeping note:** the working tree already had ~13 other
  files modified/deleted (a `settings.py` + Settings-breadcrumb refactor
  across several other templates, `_settings_breadcrumb.html` deleted)
  from some earlier, uncommitted session that never reached its own
  commit -- untouched and unrelated to this slice, deliberately left
  alone (not staged, not part of this commit) rather than guessed at or
  swept in. Worth asking directly next session whether that work is
  still wanted or should be reverted -- it's just sitting there dirty
  right now.

  Full suite run in 6 sequential chunks (same per-call-independent-
  sandbox constraint every entry in this file already notes): 434 + 482 +
  282 + 361 + 248 + 210 = 2017 passed, same total as the entry below (no
  tests added/removed, two rewritten in place).

  **Next slice:** the toast-notification pass -- replace the `?note=`/
  `?error=` query-param banner (`.settings-hint-accent`/`.settings-hint-
  error` at the top of the page) with `window.ccToast(...)`, the pattern
  every delete/archive action elsewhere in the app already uses
  (`app.js`). Likely a small JS shim that reads those two query params on
  page load and fires a toast instead of adding a second templated
  banner -- keeps every action's existing server-side redirect intact
  rather than converting nine routes to fetch-based submits. Direct user
  request, not yet scoped into a concrete diff.

- **Shipped:** 2026-09-08 -- direct report: a holiday could be saved with
  no start/end date at all, surfacing a raw FastAPI 422 JSON blob
  ("Something went wrong. Could not save: {\"detail\":[{\"type\":\"missing\",
  \"loc\":[\"body\",\"date_from\"]...}") in the error toast -- the second
  attempt (with dates actually picked) then succeeded, so nothing was
  corrupted, just a confusing round trip.

  Root cause: `_datetime_picker.html`'s `required` kwarg puts a `required`
  attribute on the hidden `<input type="hidden">` the picker writes its
  value to -- but the HTML spec explicitly bars `type="hidden"` inputs from
  constraint validation, so that attribute has always been a complete
  no-op. The component's own header comment claimed otherwise ("the hidden
  input carries required so the browser still blocks an empty form submit
  the way the native date input it replaces did") -- never actually true,
  for every `required=true` caller (Holidays' two date fields, event
  detail's "Move this occurrence" range, the habit check-in's entry date),
  not just this report's one.

  Fixed with a real guard rather than trying to coax the native
  `required` attribute into working (impossible on a hidden input short of
  swapping its type, which would break the value contract every server
  route already expects): a single document-level, capture-phase `submit`
  listener in `datetime_picker.js` that checks each required `.dtp`'s
  hidden input for an empty value and, if found, blocks the submit
  (`preventDefault` + `stopImmediatePropagation`) before it ever reaches
  modal.js's own fetch-based per-form handler or a plain native submit --
  capture-phase on `document` runs before target-phase listeners on the
  form itself, sidestepping any registration-order race with modal.js's
  own per-form wiring. Flags the offending trigger (new
  `.dtp-trigger-invalid`, style.css) and opens its panel via a synthetic
  click so the fix is one click away, plus a toast. The invalid flag
  clears itself the moment the picker's value actually changes
  (`updateTrigger()`, called from every commit path).

  Also cleaned up the underlying error toast for the case where server-side
  rejection still happens (any other 422, or a future `required` picker
  added without this guard catching it first): `modal.js` gained
  `friendlyErrorMessage()`, which recognizes FastAPI/Pydantic's own
  `{"detail":[{type,loc,msg}]}` shape and renders "field: message" instead
  of dumping the raw JSON; anything else still falls back to the raw text
  exactly as before.

  No Python changed -- `routers/settings.py::create_holiday`'s
  `Form(...)`-required fields were already correct given a well-formed
  request; this was purely a client-side gap. `sw.js` `CACHE_NAME` bumped
  `v73` -> `v74` (style.css, datetime_picker.js, modal.js all changed);
  `test_pwa_shell.py`'s pin updated. No new Python tests -- this repo has
  no JS unit-test harness for `static/*.js` (confirmed by grep: nothing
  under `tests/` exercises `datetime_picker.js`'s behavior directly, only
  `test_pwa_shell.py`'s asset-list/cache-version checks), consistent with
  every other JS-only fix already in this file. Verified via `node
  --check` on both changed JS files (syntax) and a full sequential-chunk
  test run (10 chunks by filename, `test_caldav_bridge_live.py` excluded
  as always): 2017 passed, 0 failed -- no regressions, no tests
  added/removed since this was a client-side-only change.

  **Next slice:** none mandated -- direct report, not on any roadmap
  list. Worth a real live-browser check once one is reachable (submit an
  empty Holiday form, confirm the toast + trigger highlight + panel
  auto-open all actually fire) -- same recurring verification gap every
  entry in this file already notes.

- **Shipped:** 2026-09-07 -- same-day follow-up direct report on the
  Notion-style banner rework two entries below: "the text has a bit of a
  problem if it's sitting behind a dark banner and the text is black,
  while the theme is white... make the text sit below the banner." Root
  cause: `.page-banner-header-row` used `align-items:center`, which
  vertically centers the title against the avatar's full 72px height --
  since the row itself starts 36px above the cover's bottom edge (the
  overlap that lets the avatar straddle it), centering put the title's own
  top half inside that overlapping 36px too, i.e. literally over the
  photo, where the page's normal `--fg-primary` text color reads against
  whatever the image's own colors are instead of the page background. The
  avatar was never affected (its own straddle is the intended look), only
  the shorter title sharing its row.

  Fixed with `align-items:flex-end` instead -- both the avatar and the
  title now bottom-align within the row, so the title (always shorter than
  72px) sits entirely inside the row's lower 36px, which is the actual
  below-the-photo portion, matching the avatar's own bottom half. One-line
  CSS change (style.css's `.page-banner-header-row`), no template/DOM
  changes.

  `sw.js` `CACHE_NAME` bumped `v70` -> `v71`; `test_pwa_shell.py` updated.
  No new tests -- the existing `TestPageBannerNotionStyleHeaderRow` tests
  (added two entries below) only assert DOM order, which is unchanged;
  this was a pure vertical-alignment fix, verified by re-checking the
  row's geometry by hand rather than a new assertion (nothing meaningful
  to assert about "which side of a computed box a flex child's baseline
  lands on" without an actual rendered screenshot, still not available
  this session). Full suite: 2015 collected, same total as the entry two
  below (no tests added/removed), 2014 passed + the same 1 pre-existing
  unrelated failure noted in the entry below.

  **Next slice:** none mandated -- direct report. Worth a real visual
  check (both light and dark theme, against a genuinely dark banner image)
  once a browser is reachable -- same recurring verification gap this
  whole banner-rework arc has had all session.

- **Shipped:** 2026-09-07 -- direct report (with a screenshot): "the
  avatar and text for the big banner is a bit off... remake it Notion-
  like." Root cause: `.page-banner-title` (Home's greeting / a label's
  name) rendered as white overlay text pinned to the cover photo's own
  bottom-left, immediately next to the avatar -- fine in the abstract, but
  this pass's earlier "first-run default banners" slice means every page
  now actually shows a real photo there by default, and the two crowded
  together (title baseline sitting right at the avatar's top edge)
  wherever the photo's own bottom-left happened to be busy, exactly what
  the screenshot showed. Rebuilt on Notion's own page-cover convention:
  the avatar still straddles the cover's bottom edge (half over the photo,
  half below, unchanged), but the title now renders entirely below the
  cover in the page's normal text color, on the same row as the avatar's
  lower half -- never competing with the photo's own content, no
  readability scrim needed for it anymore.

  Converted `_page_banner.html` from a plain `{% include %}` into a
  `{% call %}` macro (`page_banner(title_html)`, same pattern
  `_page_header_narrow.html` already established) so the shared cover/
  avatar/title layout lives in one file instead of being hand-duplicated
  across `dashboard.html`/`label_detail.html`/`project_detail.html` --
  each now does `{% set _title %}...{% endset %}` (plain greeting for
  Home, `icon(...) ~ name` for a label/Space/Project page) and
  `{% call page_banner(_title) %}...edit-mode action buttons...{% endcall %}`.
  The edit-mode actions (New widget / Add-Change banner / Reset layout)
  moved to a real DOM child of `.page-banner` (nested inside the cover,
  still floating bottom-right over the photo) instead of a sibling
  anchored to the whole `.page-banner-wrap` -- needed because the wrap's
  own height now includes the new header row below the photo too, so the
  old "anchor to the wrap's bottom edge" trick would've drifted the
  buttons onto the header row instead of staying pinned to the photo's
  own corner. New `.page-banner-header-row` (style.css) uses
  `margin-top:-36px` (half the avatar's own 72px) to recreate the
  straddle-the-edge overlap without needing to know the cover's actual
  rendered height (responsive, aspect-ratio-driven) -- expressed relative
  to the avatar's fixed size instead, so it holds at every viewport width.

  `sw.js` `CACHE_NAME` bumped `v69` -> `v70`; `test_pwa_shell.py` updated.
  4 new tests (`test_banners.py`'s `TestPageBannerNotionStyleHeaderRow`)
  lock in the new DOM shape (title after the cover's own closing tag, not
  inside it; actions still nested inside `.page-banner`; avatar before
  title in the header row; same layout on a Project page too). Full
  suite: 2015 collected (2011 + 4 net new), 2014 passed + the same 1
  pre-existing unrelated failure noted in the entry below (untouched,
  still not investigated).

  **Next slice:** none mandated -- direct report, not on any roadmap list.
  Worth a real visual pass once a browser is reachable (no live-render
  verification this session either, same recurring constraint noted
  throughout this file) -- everything above is verified structurally
  (rendered HTML inspected directly via the router functions, full test
  suite green) rather than an actual screenshot.

- **Shipped:** 2026-09-07 -- direct request: fixed the three real gaps an
  earlier ad-hoc audit flagged in the banner/customization surfaces
  (documented in that audit's own summary, not a file in this repo).

  1. **Label/Space color was never validated server-side.** `create_label`/
     `update_label`/`set_label` (routers/labels.py) all wrote `color or
     "blue"` -- any string at all, not just one of the 16 names in this
     file's own `COLORS` list -- straight into `label_config.color`, which
     three templates (`_label_pill.html`, `_labels_table_body.html`,
     `_widget_items.html`'s `widget_pill`) then interpolate into a CSS
     class with no matching rule for a bogus value (rendering an unstyled
     pill, not a security issue -- Jinja2 autoescapes the attribute). Fixed
     at all three write sites: `color if color in COLORS else "blue"`,
     matching the one consumer (`filled_card`) that already validated this
     way.

  2. **Reserved banner-scope name collision.** The global default banner
     and the four season banners (`db.PAGE_HEADER_BANNER_SCOPE`/`db.
     SEASON_BANNER_SCOPES`, both added this week) live in the same
     `page_banner_<key>` app_meta namespace a label's own banner does nothing
     stopped a label literally named e.g. `__page_header__` from silently
     reading/writing the app-wide default. New `_reject_reserved_label_
     name` guard in routers/labels.py, called from every write path that
     can set a label's *name*: `create_label`, `update_label` (only when
     actually renaming), the standalone `/{name}/rename` endpoint,
     `/{name}/merge`'s `dest_name`, and the legacy `/{name}/set` route's
     own `name` (defense in depth -- a direct POST to that URL could set a
     label_config row under a reserved name without ever going through
     create_label).

  3. **Photo/banner uploads trusted the browser's Content-Type header
     alone.** This app has no auth, so any POST could claim `image/jpeg`
     for arbitrary bytes; the three upload routes (routers/banners.py's
     `upload_banner`, routers/contacts.py's `_read_photo`, routers/
     settings.py's `set_profile_photo`) stored and later re-served
     whatever type the header claimed, never checking the bytes
     themselves. New `src/image_sniff.py` (`sniff_image_type`) -- a small
     hand-rolled magic-byte check for JPEG/PNG/GIF/WEBP, deliberately not
     Pillow (contacts.py's own pre-existing comment already rules that out
     as "a new dependency" this codebase avoids). All three routes now
     reject a file whose bytes don't match any real image signature, and
     store the *sniffed* type rather than the declared one (so a
     correctly-imaged-but-mislabeled upload isn't rejected, just
     re-typed). Checked `banner_editor.html`'s "5:1 aspect ratio" language
     first, in case that looked like an enforceable rule too -- it isn't:
     the template's own copy says "Non-5:1 images are center-cropped to
     fit," so aspect ratio was never a real constraint to enforce, just a
     crop-tool default.

  19 new tests across `test_phase2_labels.py` (`TestColorValidation` +
  `TestReservedLabelNameGuard`, 11), `test_banners.py`
  (`TestBannerUploadImageSniffing`, 3), and `test_image_caching.py`
  (`TestPhotoUploadImageSniffing`, 5 -- two of which drive
  `contacts._read_photo` via `asyncio.run(...)` since this suite has no
  pytest-asyncio configured and this is the first async route function to
  need a direct-call test). Full suite: 2011 collected, 2010 passed + 1
  pre-existing unrelated failure (`test_dashboard_router.py::
  TestAgendaWidgetAllUpcoming::test_todays_earlier_events_still_count_as_
  upcoming` -- confirmed via `git stash` that it fails identically on the
  prior commit, a real but out-of-scope bug, not touched this pass). No
  `sw.js` bump (no static asset changed).

  **Next slice:** the dashboard_router agenda test failure above is worth
  a look -- not investigated further this pass since it's unrelated to
  the audit fixes, but it's a real assertion failure, not a flake that
  passed on retry.

- **Shipped:** 2026-09-07 -- direct request: first-run default banners +
  avatar, sourced from image files the user dropped in a new repo-root
  `pictures/` directory (`banner_51.jpg`, `spring_51.jpg`/`summer_51.jpg`/
  `autumn_51.jpg`/`winter_51.jpg`, `avatar.jpg` -- all `_51` files are the
  5:1 banner aspect ratio; plain-named siblings in the same folder are
  unused leftovers, not wired to anything). Two related but separate
  pieces, per direct clarification (AskUserQuestion) before building:

  1. **One-time seed, not a permanent fallback.** New `main._seed_default_
     media(conn, pictures_dir)`, called once from `lifespan` (wrapped in
     try/except -- a missing/broken `pictures/` dir must not refuse to
     boot the app). Gated on an app_meta flag
     (`default_media_seeded_v1`) checked/set unconditionally on first call
     regardless of which individual files were found, so a database is
     only ever seeded once, period -- a value the user edits or removes
     afterward is never re-applied on a later restart, and a `pictures/`
     directory that gains files later doesn't retroactively backfill them.
     Writes through the exact same app_meta shape a real upload would
     (`db.set_page_banner`/`db.set_profile_photo`, base64 + content-hash
     `version`) -- indistinguishable from a user-set banner/avatar after
     the fact, editable/removable as normal in Settings.

  2. **New season tier in `db.banner_for_object`'s fallback chain**, for
     tasks/events specifically (direct request: "all data... default to
     their season"). Chain is now: own label(s) -> Project label -> parent
     Space -> **season matching the object's own due/start date
     (new `db.season_for_date`, meteorological Northern Hemisphere,
     Dec-Feb/Mar-May/Jun-Aug/Sep-Nov) -> the single global default
     (`db.PAGE_HEADER_BANNER_SCOPE`, same one every page already falls
     back to)** -> None (the pre-existing flat-gradient fallback,
     `_detail_cover.html`, now only reached by an object type not in the
     new `_SEASON_DATE_FIELD` map, or a dated task/event when even the
     global default is unset). Deliberately scoped to task (`due_at`) and
     event (`start_at`) only, per explicit instruction not to change any
     other object type's banner behaviour this pass -- contacts keep
     resolving to None/gradient exactly as before (`_SEASON_DATE_FIELD`
     has no "contact" key, confirmed by a new test). Habits are already
     covered for free -- a habit is a labeled task under the hood, same
     `db.banner_for_task` wrapper every other task uses.

     `PAGE_HEADER_BANNER_SCOPE` moved from `deps.py` to `db.py` (deps.py
     re-exports the same name) since `db.banner_for_object` needed it and
     `db.py` can't import `deps.py` (circular -- deps.py already imports
     db). Four new sentinel scopes alongside it, `db.SEASON_BANNER_SCOPES`
     -- same "just another page_key" mechanism as the existing default, no
     new storage or routes; a season banner is set/edited/removed through
     the ordinary `/banners/editor?scope=__season_summer__` etc., though no
     UI entry point links to that scope directly yet (only reachable by
     hand-editing the URL, or automatically once seeded) -- flagged for a
     future settings-surface follow-up, not required by this slice's own
     ask.

  No templates/CSS/JS touched -- `_detail_cover.html` already renders any
  `banner` dict generically (version/scope or image_url), so the new
  fallback tiers render through the exact same code path unchanged. No
  `sw.js` bump needed (no static asset changed). 15 new tests (`test_
  banners.py`'s new `TestBannerSeasonAndDefaultFallback`, 8; new file
  `test_default_media_seed.py`, 7, testing `_seed_default_media` directly
  against a temp `pictures_dir` rather than the real repo-root one).
  Full suite: 1992 passed (1977 + 15 net new), run in 6 sequential chunks
  (background processes don't survive across tool calls in this sandbox,
  same constraint as every prior session).

  **Next slice:** deferred by direct instruction, not built this pass --
  letting contacts/habits have their **own** dedicated banner (like a
  Project/Space page has), independent of any label, falling back to the
  app default when unset. Would need: a banner scope keyed by contact
  uid/habit uid rather than a label name (contacts/habits have no
  generated dashboard page the way a label does, so `get_page_banner`'s
  `page_key` convention extends but the *entry point* -- where "Add
  banner" lives on `contact_detail.html`/`habit_task_detail.html` -- is
  new UI, not just a new scope string), and deciding whether a contact/
  habit's own banner should outrank or lose to its label-based resolution
  in `banner_for_object`'s priority order (undecided, worth an
  AskUserQuestion before building rather than guessing). Also worth
  surfacing the four season scopes somewhere in Settings > Appearance
  (currently only the global default has a UI entry point) as a small
  follow-up, unless a future pass decides the automatic season resolution
  alone is enough and no manual override UI is needed.

- **Shipped:** 2026-09-07 -- direct report: Calendar/Planner had double
  the normal bottom space under the grid. `.calendar-viewport` (Month/
  4-Week/Day) and `.project-calendar-layout` (Week) both carry the plain
  `.card` class, whose `margin-bottom:var(--space-4)` sat at the very
  bottom of `main.main-calendar`'s fixed-height flex column -- as the
  last flex child, that inherited margin ate into the shell's own
  visible height on top of main's own bottom padding, reading as roughly
  double the gap every other page has. Zeroed `margin-bottom` on both,
  scoped to being `main.main-calendar`'s own direct child -- `.card`'s
  margin-bottom is untouched everywhere else it's used (same scoping
  pattern as the earlier Planner Unscheduled-work/grid gap fix this
  session, `.project-calendar-layout > .card{margin-bottom:0}`).

  `sw.js` `CACHE_NAME` bumped `v68` -> `v69`; `test_pwa_shell.py`
  updated. Full suite: 1977 passed, same total as before.

  **Next slice:** none mandated -- direct request, not on
  `audit-fixes-2.0.md`'s list.

- **Shipped:** 2026-09-07 -- two direct reports, both about empty states
  showing content that isn't there:

  1. **Empty-state card background** (Contacts specifically reported,
     Tasks named as the good example): `#contacts-body` carried `.card`
     on the OUTER wrapper unconditionally, so the empty state (a sibling
     of the actual contact list inside that same wrapper) inherited a
     card background it was never meant to have -- Tasks' own
     `#tasks-body` has no such wrapper class; only the actual table's own
     wrapper div is `.card`. Moved `.card` off `#contacts-body` onto
     `.contact-list` itself (only rendered when there are contacts) to
     match. Found and fixed the identical bug in Notes' `#notes-body`
     while auditing for the same pattern (not explicitly reported, but
     structurally the same issue) -- `.card` moved onto `.checklist`.
     Labels manage wasn't affected -- its empty state is a `<tr>` inside
     the same always-present `<table>`, a different pattern already
     normalized earlier (`_empty_state_row.html`, audit-fixes-2.0.md item
     14), not a card-behind-empty-state case.

  2. **Tasks: empty Habits/main table rendering unconditionally.**
     `_build_task_groups` (routers/tasks.py) always appends a Habits
     group regardless of whether any habits exist -- grouping is
     unconditional, one fixed order, per that function's own 2026-08-28
     comment -- so the template's `{% if _habits_group %}` was always
     true, rendering an empty "Habits (0)" table (header row, no data)
     whenever there were zero habits. Direct instruction reverses a prior
     explicit decision here (`test_habits_table_is_always_present_even_
     with_no_habits_yet`, 2026-08-29: "the '+ Add habit' affordance needs
     somewhere to live even before any habit exists") -- renamed that
     test to assert the opposite and documented the reversal in its own
     comment; creating a first habit still works via the sidebar's global
     quick-add/task creation's own habit toggle, just not from a
     dedicated empty table anymore.

     Root-caused a second, related bug while fixing this: an account with
     *only* habits (no regular/completed tasks) still rendered the whole
     empty Project/Unassigned/Completed table above the Habits one --
     `has_any` (used to gate the whole content-vs-empty-state branch)
     didn't distinguish "habits exist" from "regular tasks exist," it was
     just their combined OR. Added two narrower flags to `_tasks_list_
     context`, `has_main_tasks` (`open_tasks or completed_tasks`) and
     `has_habits` (the Habits group's own item count) -- `has_any` stays
     as their combined OR for the page's own top-level empty state,
     `_tasks_body.html` now gates each table independently on the
     narrower flag. Completed itself was never a separate table to begin
     with (its tasks flatten into `#task-table`'s own `<tbody>`) -- an
     empty Completed group already contributed zero rows silently,
     nothing to gate there; the report's mention of it was really about
     the combined main-table-with-Completed-rows case, covered by
     `has_main_tasks`.

     `_tasks_list_context` is shared between the full page and the
     async-CRUD fragment route (`GET /tasks/regions?region=table`, both
     call it directly) -- both new flags flow through automatically, no
     second place to update.

  Two tests updated (`test_habits_table_is_always_present_even_with_no_
  habits_yet` renamed + inverted, `test_habits_group_name_and_add_link_
  are_in_its_header` given a real habit to seed since the table it
  asserts against no longer renders at zero), two new tests added
  (`test_habits_table_reappears_once_a_habit_exists`, `test_main_task_
  table_is_hidden_when_only_habits_exist`). No `style.css` changes this
  pass -- templates + `routers/tasks.py` + tests only, no `sw.js` cache
  bump needed. Full suite: 1977 passed (+2 net new tests over the 1975
  baseline, both accounted for above).

  **Next slice:** none mandated -- direct request, not on
  `audit-fixes-2.0.md`'s list.

- **Shipped:** 2026-09-07 -- follow-up correction to the header-height
  fix two entries below: direct measurement after that fix still showed
  50px on pages with the filter-dropdown button and 46px on plain pages,
  not 48 either way (symmetric ±2px, not just "still too tall"). Root
  cause: that fix's math (8px padding top + 8px bottom = a 32px content
  budget inside a 48px target) missed that `.page-header-narrow` *also*
  has a 1px border on top of the padding -- with the header's height
  still auto/content-driven at that point, a 32px-tall control actually
  needed 32 + 16 (padding) + 2 (border) = 50px of auto-height to render
  without clipping, and a 28px control (plain pages' tallest content,
  `.icon-btn`) needed 46px -- both exactly matching the new measurement.

  Fixed at the root this time instead of chasing individual controls'
  heights again: `.page-header-narrow` now sets `height:48px` explicitly
  (it already had `overflow:hidden`, for the optional banner image, so
  anything that doesn't fit gets absorbed instead of pushing the row
  taller) -- real content budget is `48 - 16 (padding) - 2 (border) =
  30px`. `.filter-dropdown-trigger` adjusted `32px -> 30px` to fit it
  without clipping. Also checked every other control that can render in
  `.page-header-narrow-actions` for the same risk: `.icon-btn` (28px)
  already fits; `calendar_month.html`'s Month|Day `.segmented` switch
  (`.segmented`'s 3px padding + `.seg-btn`'s 6px, ~35px total) did not --
  added a `.page-header-narrow-actions`-scoped compact override
  (`.segmented{padding:2px}`, `.seg-btn{padding:3px 12px}`) so it fits
  too, scoped to that one actions-slot context since `.segmented` is
  reused at its normal size all over Settings/modals correctly.

  `sw.js` `CACHE_NAME` bumped `v67` -> `v68`; `test_pwa_shell.py`
  updated. Full suite: 1975 passed, same total as before.

  **Next slice:** none mandated -- direct request, not on
  `audit-fixes-2.0.md`'s list. Still no live browser to actually confirm
  48px against a ruler (see the entry two below's own verification-note
  caveat, unchanged this pass) -- worth being the first thing checked
  next session if Chrome or a sandbox browser becomes available.

- **Shipped:** 2026-09-07 -- extended the flex-shell "page fits the
  viewport, body scrolls internally" model (built for Calendar/Planner
  earlier this session, `main.main-calendar`) to a new generic
  `main.main-shell` modifier, applied to Tasks, Contacts, Notes, Labels
  manage, and Dashboard -- direct request, scoped deliberately after
  discussion: these five have a clean "one header, one scrollable body"
  shape; Settings (hub + sub-pages), Search, Published lists, and
  Project/Label detail pages were explicitly held for a follow-up since
  several don't share that shape (multi-column forms, a Kanban board) and
  need their own look at what should actually scroll first.

  Same mechanics as `main.main-calendar` (height-locked flex column,
  `100dvh` with a `100vh` fallback, nothing subtracted on desktop, the
  mobile bottom nav bar's 64px on mobile) but generalized: since these
  five pages' body markup shares no common class the way Calendar's
  `.calendar-viewport`/`.project-calendar-layout` does, each page's own
  template applies one explicit `.main-shell-body` class to whichever
  element is actually its scrollable region -- `#tasks-body`,
  `#contacts-body`, `#notes-body`, `#modal-target` (Labels manage's
  existing wrapper), and a new wrapper `<div>` around Dashboard's
  `{% include "_widget_workspace.html" %}`. `main.main-calendar` itself
  wasn't folded into this -- it already works and didn't need touching.

  Dashboard's `#dashboard-grid` (the masonry widget grid) needed a check
  before assuming this was safe: `static/app.js`'s masonry layout sets
  `grid.style.height` directly, computed from total card content --
  taller than the viewport whenever there's more than a screenful of
  widgets. Confirmed this composes fine with the new wrapper exactly the
  way Calendar's `.time-grid-body` (also taller than its own budget)
  already scrolls inside `.time-grid-wrap` one level up -- the grid keeps
  setting its own real content height unchanged, `.main-shell-body` is
  the one that actually gets the fixed viewport-derived height and
  `overflow-y:auto`.

  Checked `#modal-target`'s other meaning in this codebase before adding
  a class to Labels manage's copy of it -- `static/modal.js` reads a
  fetched page's `#modal-target` `classList` for `modal-height-md`/`-lg`/
  `-stable-height` markers when a page is opened via `data-modal`, and
  three tests assert exact `id="modal-target"` class strings on three
  *other* templates' own `#modal-target` divs (`quick_add.html`,
  `dashboard_customize.html`, the view/edit modal pair) -- confirmed
  those are separate elements in separate templates, and confirmed
  `injectModalContent()` only takes `#modal-target`'s `innerHTML` (the
  outer div and its classes never survive into the injected modal DOM
  either way), so adding `main-shell-body` to Labels manage's own
  `#modal-target` is inert for the modal-injection path regardless.

  Full suite re-run in the same 4-chunk pattern: 678 + 434 + 530 + 333 =
  1975 passed, same total, no tests added/removed (the tests referencing
  `#tasks-body`/`#modal-target`/etc. are substring/exact-match checks
  unaffected by an added class, verified each one individually before
  running the full suite).

  `sw.js` `CACHE_NAME` bumped `v66` -> `v67`; `test_pwa_shell.py`
  updated.

  Verification note, same caveat as every entry in this session: still no
  live browser (Claude in Chrome unreachable, no system browser installed
  in this sandbox for a headless render) -- everything above is verified
  structurally (served CSS/HTML matches source, braces balanced, full
  test suite green) and by reading the relevant JS (`app.js`'s masonry,
  `modal.js`'s `#modal-target` handling) rather than an actual rendered
  screenshot. Worth a real visual pass on all five pages next session.

  **Next slice:** the four held-back page groups (Settings, Search/
  Published lists, Project/Label detail) -- per direct discussion, each
  needs its own look at what should scroll before getting `main-shell`,
  not a blind copy of this pass.

- **Shipped:** 2026-09-07 -- Header bar height inconsistency: Tasks'
  narrow header measured 58px (direct DevTools measurement) against 48px
  on every other page. Root cause: `.filter-dropdown-trigger` (the "Date"
  filter button, rendered inside `_page_header_narrow.html`'s actions
  slot) is `height:40px`, taller than the 32px content budget every other
  header control (`.icon-btn`, the h2 title) fits inside -- forces the
  whole flex row taller wherever it renders. Tasks' Date filter is
  unconditional so it always renders and always showed this; Calendar's
  label filter and Contacts' tag filter are conditional on having any
  labels/tags, so an empty account's headers happened to dodge the same
  bug -- it would have surfaced there too the moment either page had a
  real filter to show. Fixed at the source: `.filter-dropdown-trigger`
  `height:40px` -> `32px`, so every header stays 48px regardless of which
  controls happen to render in it.

  `sw.js` `CACHE_NAME` bumped `v65` -> `v66`; `test_pwa_shell.py`
  updated. Full suite: 1975 passed, same total, no tests added/removed
  (the two tests referencing `filter-dropdown-trigger` only check class
  presence/ordering, not pixel values).

  **Next slice:** none mandated -- direct request, not on
  `audit-fixes-2.0.md`'s list.

- **Shipped:** 2026-09-07 -- Planner: fixed the gap between the
  "Unscheduled work" panel and the time grid below it reading as roughly
  double what it should be (direct report against a real screenshot).
  Root cause: `.project-calendar-layout` (the flex column wrapping both)
  has its own `gap:16px`, but both children also carry the plain `.card`
  class, whose `margin-bottom:var(--space-4)` (also 16px) stacks on top
  of the flex gap instead of collapsing into it -- flex `gap` and margins
  never collapse with each other, so the real space was 32px. Fixed with
  `.project-calendar-layout > .card{margin-bottom:0;}`, scoped to just
  this flex layout's direct children rather than touching `.card`'s
  `margin-bottom` itself, which still does real work in every plain
  document-flow context `.card` is used in elsewhere.

  `sw.js` `CACHE_NAME` bumped `v64` -> `v65`; `test_pwa_shell.py`
  updated. Full suite re-run in the same 4-chunk pattern: 678 + 434 + 530
  + 333 = 1975 passed, same total, no tests added/removed.

  **Next slice:** none mandated -- direct request, not on
  `audit-fixes-2.0.md`'s list.

- **Shipped:** 2026-09-07 -- Calendar "fit the page" layout, structural
  cleanup pass on top of the three entries below. Two direct asks, both
  in `style.css`:

  1. **`main-full-width{margin-right:var(--space-5)}` removed.** It was
     stacked on top of main's own right padding, leaving an unused strip
     on the right edge of exactly the pages (Calendar/Planner/Dashboard/
     labels/projects) this class exists to make use the full width
     available. Now just `max-width:none`.

  2. **The desktop-only and mobile-only "Calendar fit the page" passes
     (the three entries below, `v61`-`v63`) folded into one
     breakpoint-independent `main.main-calendar` ruleset**, per a direct
     suggestion to look at how real apps avoid the `100vh`-causes-a-
     scrollbar problem instead of tuning yet another magic-number
     estimate (`--calendar-chrome-h`, the desktop pass's fixed 172px
     guess for "everything around the grid," was still leaving a
     page-level scrollbar because a fixed estimate is wrong the moment
     the real header height differs from it). The fix real apps use:
     a flex shell, not arithmetic -- lock ONE outer container's height to
     the viewport, let flexbox distribute the remainder between a
     `flex:none` header and a `flex:1` body, and the browser does the
     subtraction instead of a hardcoded number. `main.main-calendar` is
     that shell now, unconditionally (same flex/scroll/sticky/grow-fill
     rules at every width) -- the ONLY thing that still differs by
     breakpoint is how much of the viewport gets subtracted for the
     shell's own height (`100dvh` on desktop with nothing to reserve,
     `100dvh - 64px` on mobile for the fixed bottom nav bar), each in its
     own tiny media query. `--calendar-chrome-h` is gone entirely -- see
     the ruleset's own comment (style.css, right after `.week-event`) for
     the full writeup, sources: [dvh explainer](https://savvy.co.il/en/blog/css/css-dynamic-viewport-height-dvh/),
     [Smashing Magazine on the 100vh scrollbar problem](https://www.smashingmagazine.com/2023/12/new-css-viewport-units-not-solve-classic-scrollbar-problem/).
     Also dropped the old `.calendar-viewport`'s `min-height:320px` floor
     while consolidating -- a fixed floor is the same class of bug as
     `--calendar-chrome-h`, just smaller (it can force the shell taller
     than a genuinely short viewport); relying on the widget's own
     `overflow-y:auto` instead is what actually guarantees no page-level
     scrollbar at any window size.

  Tried Claude in Chrome again this pass for real visual verification
  (not just reasoning from CSS/screenshots) -- extension still not
  reachable. Verified instead via: braces-balanced check, `curl` against
  this sandbox's own running `webapp` instance confirming the served
  `/static/style.css` has no leftover `--calendar-chrome-h` references
  and the new `main.main-calendar` rules are present, and the full test
  suite. A real live-browser pass (resize to actual desktop/mobile
  widths, screenshot, check DevTools computed height) is still worth
  doing next session once Chrome is reachable, given how much the two
  "fixed but wasn't" rounds before this one turned on things that only a
  real render would have caught immediately.

  `sw.js` `CACHE_NAME` bumped `v63` -> `v64`; `test_pwa_shell.py`
  updated. Full suite re-run in the same 4-chunk pattern: 678 + 434 + 530
  + 333 = 1975 passed, same total, no tests added/removed.

  **Next slice:** none mandated -- direct request, not on
  `audit-fixes-2.0.md`'s list.

- **Shipped:** 2026-09-07 -- Calendar "fit the page" layout, two
  same-day correction passes on top of the two entries below (screenshots
  showing the Month/4-Week card still ending after 4 rows with blank
  space beneath it, on both a desktop-width and mobile-width screenshot,
  plus a new "widget overflows behind the mobile bottom nav" report).

  1. **The real bug the screenshots caught:** the prior two passes gave
     `.calendar-viewport` a height budget and `overflow-y:auto`, but
     never anything that grows Month/4-Week's rows to actually use that
     budget when their content is *shorter* than it -- a plain flex
     column doesn't stretch its children just because the column itself
     has room. So the "dead space" symptom hadn't gone away, it had just
     moved from "below the widget" (page background) to "inside the
     widget" (still inside `.calendar-viewport`'s own barely-different
     card background, #3e3e3e vs #363636 in dark mode -- easy to miss in
     a screenshot, but the same visual problem). Fix: `flex:1 1 0` on
     `.month-week-grid` (both the desktop `min-width:721px` block and the
     mobile `main.main-calendar` block) so week rows grow to fill
     leftover space -- `.month-day-cell`'s own unmodified base
     `min-height:90px` still acts as each row's floor, and
     `.calendar-viewport`'s `overflow-y:auto` is still the fallback if
     that floor ever adds up to more than the budget. Net effect: rows
     grow to fill when there's room (the old 2026-08-08 shrink-to-fit
     pass's actual goal, just via growing instead of shrinking), scroll
     when there isn't -- no case left where the box has unused space.

  2. **Mobile overflowing behind the bottom nav bar** (separate direct
     report): `main.main-calendar`'s mobile height was
     `calc(100vh - 64px - env(safe-area-inset-bottom))`. Two bugs: (a)
     `.mobile-tabbar` is a fixed `height:64px` box with its own
     safe-area padding baked *inside* that 64px (border-box), not added
     past it, so subtracting the inset a second time here just left an
     unwanted gap, not the overflow itself; (b) the real culprit is the
     classic mobile `100vh` bug -- `100vh` measures the *largest*
     possible viewport (address bar hidden), which on a real phone can
     be taller than what's actually on screen, letting a
     `height:100vh`-based box run past the true bottom of the screen and
     under the fixed nav bar. Switched to `100dvh` (dynamic viewport
     height, tracks the real current viewport), kept as a second
     declaration after the `100vh` one so browsers without `dvh` support
     still get the old value instead of losing the property outright.

  Also confirmed while investigating the "nothing changed" reports across
  both this pass and the two below: `base.html`'s manifest `<link>` and
  `pwa.js`'s registration are both currently commented out ("PWA shell --
  DISABLED"), so **no service worker is actually registered right now**
  and the whole `CACHE_NAME` mechanism (bumped for all three passes,
  matching the file's own established convention, now at `v63`) is
  inert. It was never what was blocking these reports from showing up --
  a plain browser HTTP cache or an un-restarted dev server is the more
  likely explanation, worth checking directly (view-source or DevTools
  computed style against the live `/static/style.css`) before assuming a
  CSS logic bug next time something "doesn't show up."

  Tried to verify this pass in a live browser (Claude in Chrome) instead
  of reasoning from static screenshots alone -- the extension wasn't
  reachable this session, so verification stayed at: braces-balanced
  check, `curl` against this sandbox's own running `webapp` instance
  confirming the new rules are actually in the served `/static/
  style.css`, and the full test suite. Worth an actual live-browser pass
  (resize to a real mobile width, screenshot, check DevTools computed
  height on `.calendar-viewport`) next session if another visual report
  comes in.

  `sw.js` `CACHE_NAME` bumped `v62` -> `v63`; `test_pwa_shell.py`
  updated. Full suite re-run in the same 4-chunk pattern: 678 + 434 + 530
  + 333 = 1975 passed, same total, no tests added/removed.

  **Next slice:** none mandated -- direct request, not on
  `audit-fixes-2.0.md`'s list.

- **Shipped:** 2026-09-07 -- Calendar "fit the page" layout, desktop
  follow-up to the mobile entry directly below. Direct report that the
  mobile fix "isn't working, nothing new has been added" turned out to be
  a width mix-up, not a caching bug: the report was made from a browser
  window still >720px wide, where the mobile-only rules never applied at
  all (desktop already had its own, older fit-the-page behavior from
  2026-08-08, which is why "desktop works" -- just not the same way).

  Separately, direct follow-up request: make desktop Month/4-Week use the
  same "widget gets a scrollbar, page doesn't" model Week/Day already
  had, instead of their own 2026-08-08 shrink-to-fit row logic. Dropped
  that logic from the `@media (min-width:721px)` block in style.css (the
  128vh/100vh per-view budget tuning, `.month-viewport`'s
  `overflow:hidden`, and the `.month-week-grid`/`.month-day-cell`
  flex-shrink overrides) -- all four calendar views now share one
  `.calendar-viewport{height:calc(100vh - var(--calendar-chrome-h));
  overflow-y:auto}` rule. `.month-weekday-row` picked up the same
  `position:sticky` treatment `.time-grid-top`/`.time-grid-head` already
  had, so it stays pinned while the week rows scroll underneath instead
  of scrolling away with them. Old shrink-to-fit CSS is recoverable via
  `git log -p` on this file if that look is ever wanted back (commit
  `db9b942`).

  `sw.js` `CACHE_NAME` bumped `v61` -> `v62` (style.css changed again);
  `test_pwa_shell.py`'s pin updated. Full suite re-run in the same
  4-sequential-chunk pattern as the mobile entry below (background
  processes don't survive across tool calls in this sandbox): 678 + 434
  + 530 + 333 = 1975 passed, same total, no tests added/removed.

  **Next slice:** none mandated, same as the mobile entry below -- this
  was a direct request, not on `audit-fixes-2.0.md`'s list.

- **Shipped:** 2026-09-07 -- Calendar/Planner "fit the page" layout,
  mobile follow-up (direct report against a resized/narrow browser
  window, not a phone: the Calendar widget left a dead strip of blank
  page below it instead of filling the screen, and Planner's 24-hour
  grid scrolled the whole page instead of scrolling internally). The
  2026-08-08 desktop pass (`.calendar-viewport`'s own comment, style.css)
  explicitly punted on mobile ("a shrink-to-fit calendar grid on top of
  that is a separate problem this pass doesn't attempt to solve blind")
  -- this is that follow-up, scoped to the max-width:720px breakpoint
  (which also fires on a narrow *desktop* window, not just real phones).

  Rather than porting the desktop block's fixed `--calendar-chrome-h`
  estimate (tuned for a two-row toolbar that doesn't exist at this width,
  and the header's filter row can wrap to a second line here, making any
  fixed guess unreliable), went with a flex-shell approach instead: new
  `main-calendar` modifier class (calendar_day/week/month/fourweek.html's
  `main_class` block only -- NOT `main-full-width` itself, which
  dashboard.html/label_detail.html/project_detail.html also use for
  unrelated widget-grid/Kanban content that should keep ordinary page
  scroll). `main.main-calendar` becomes a height-locked flex column
  (`height:calc(100vh - 64px - env(safe-area-inset-bottom))`, the 64px
  matching `.mobile-tabbar`'s own height) -- the page header sizes itself
  (`flex:none`), and whatever's left goes to the actual view widget
  (`.calendar-viewport` directly for Month/4-Week/Day, or
  `.project-calendar-layout` for Planner/Week, whose own
  `.calendar-viewport` is one level deeper next to the Unscheduled-work
  aside). No magic number to keep in sync with header content, and Week/
  Day's `.time-grid-wrap` keeps the same sticky-header-then-scroll
  pattern the desktop rule already established (`position:sticky` on
  `.time-grid-top`/`.time-grid-head`, `overflow-y:auto` on the wrap).
  Month/4-Week get a plain `overflow-y:auto` directly on
  `.calendar-viewport` instead of desktop's shrink-to-fit grid math
  (`.month-viewport` row-flexing) -- simpler, and matches what was
  actually asked for ("the widget should have a scrollbar"), not desktop's
  shrink-to-fit look.

  style.css only (new rules inside the existing `@media (max-width:720px)`
  block) + the 4 templates' `main_class` block gaining the new class --
  no JS, no Python. Per the `sw.js` v15/v16 lesson already documented
  there (style.css changes need a `CACHE_NAME` bump to actually reach an
  installed PWA), bumped `cc-shell-v60` -> `v61`; `test_pwa_shell.py`'s
  version-pin assertion updated to match. Full suite re-run in 4
  sequential chunks (background/parallel test running isn't reliable in
  this sandbox -- a detached process doesn't survive across tool calls
  here, unlike the 12-parallel-chunk approach the CSP slice above used
  elsewhere): 678 + 434 + 530 + 333 = 1975 passed, same total as the
  CSP slice's own baseline (no tests added/removed, just one assertion's
  expected string updated).

  **Next slice:** none mandated -- 2.0's fix list (`audit-fixes-2.0.md`)
  was already fully shipped before this slice; this was a direct request,
  not on that list. Check `roadmap.md`'s 2.0 section fresh next session
  per the CSP slice's own note below, to confirm 2.0 is actually ready to
  ship.

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md item 11, the CSP
  `unsafe-inline` migration -- the last mandatory item on the pre-2.0 fix
  list, saved for last on purpose as the largest/riskiest. Scoped as
  **full elimination** (a direct choice, not the narrower "nonce just the
  `<script>`/`<style>` tags, keep `unsafe-inline` on style-src for
  attributes" reading the item's own one-line spec would also have
  allowed) -- nonces don't cover `style="..."`/`onclick=`/`onchange=`
  attributes at all, so a narrower scope would have left `'unsafe-inline'`
  on style-src regardless.

  `security_headers.py`'s `SecurityHeadersMiddleware` now generates a
  fresh `secrets.token_urlsafe(16)` nonce per request, stashes it on
  `scope["state"]["csp_nonce"]` *before* calling `self.app` (Starlette's
  `Request.state` lazily reads `scope["state"]`, confirmed by reading
  `starlette/requests.py` directly rather than assuming), and formats
  `CSP_POLICY` (now a `{nonce}` template string) into the response header.
  `deps.py` exposes the same value to templates as a `csp_nonce()` Jinja
  global, same pattern as `icon`/`static_url`. `CSP_POLICY` is now:
  `script-src 'self' 'nonce-<value>'` / `style-src 'self'
  'nonce-<value>'` -- no `'unsafe-inline'` anywhere in the policy, on
  either directive.

  Three categories of markup needed elimination, each with a different
  fix:
  1. **Real inline `<script>`/`<style>` tags** (9 templates + `_page_
     banner.html`) -- `nonce="{{ csp_nonce() }}"` added directly.
  2. **`onclick=`/`onchange=` attributes** (24 occurrences once re-counted
     against current markup, one more than the 23 originally surveyed --
     `_widget_list_multiselect.html` had one the initial grep missed)
     moved to delegated `addEventListener` listeners in static JS (a new
     `data-change-submit` delegated listener in `app.js`; `settings_data_
     maintenance.html`'s force-sync button moved from an inline `<script>`
     into `data_maintenance.js` as a `data-action="force-sync"` delegated
     click handler).
  3. **`style="..."` attributes** (84 of the 85 surveyed turned out real
     once inspected -- one grep hit was a `style="list"`/`style="cards"`
     widget-variant doc comment, not a CSS attribute). Split by whether
     the value is fixed or per-request/per-row computed:
     - **Static** (~70 of 84): became CSS classes/utilities in style.css
       (`.field-narrow`, `.text-caption`, `.form-contents`, `.col-
       checkbox`/`.col-actions-narrow`, `.empty-state-compact`/`.empty-
       state-loose`, `.text-right-nowrap`, `.align-middle`, `.settings-
       hint-accent`/`.settings-hint-error`, plus several component-scoped
       classes), or folded into bounded-range CSS (`nth-child`/`[data-
       cols]`) for the Month/4-Week grid's 1-7 `grid-column` values and
       the Weekly Schedule widget's 1-7 `grid-template-columns` values --
       neither actually varies continuously, so a fixed CSS rule per
       count covers every case without any JS. `--hr-h` (calendar
       pixels-per-hour) turned out to be a hardcoded Python constant
       (`grid_layout.PX_PER_HOUR = 48`) masquerading as a per-request
       inline var -- moved to a `:root` token.
     - **Dynamic** (14 of 84: calendar grid event/overlay positioning,
       `_detail_cover.html`'s label/Space accent color, `_widget_spaces_
       projects.html`'s progress-bar width) -- genuinely per-row computed,
       can't be a nonced `<style>` tag (nonces don't cover attributes) or
       a static class (value varies). Fixed via a new generic **`data-
       style` -> CSSOM applier**, `static/dynamic_styles.js`: renders the
       exact same `style="..."` syntax into `data-style="..."` instead (a
       mechanical rename at each of the 4 call sites, no template-logic
       change), then a global script applies it via `element.style.
       setProperty(...)` on load + via the same `MutationObserver`-driven
       convention `a11y_icon_labels.js` already established (async-CRUD
       region refreshes, modal-injected content, quick_add/command-
       palette inserts all covered automatically, no per-feature re-init
       hook). CSSOM `.style` writes aren't restricted by `style-src` at
       all -- only `<style>` elements and HTML `style=` attributes are --
       the standard technique for CSP-strict dynamic styling. Tradeoff
       noted in `dynamic_styles.js`'s own header comment: these values now
       apply in a deferred JS pass rather than being present in the
       initial HTML, so a no-JS visitor (or very slow JS load) briefly
       sees unpositioned/uncolored elements first -- same class of
       tradeoff `a11y_icon_labels.js` already accepted, not new to this
       slice.

  New tests in `test_security_headers.py`: nonce presence, two requests
  get two different nonces, `'unsafe-inline'` absent from both script-src
  and style-src, a real Jinja-rendered `<script nonce=...>` matches the
  same request's response header. Two pre-existing tests had hardcoded
  old markup and needed updating (grepped `tests/` for every touched
  pattern first, same discipline as every prior slice in this file):
  `test_detail_modals_rework.py`'s `style="color:..."` assertions ->
  `data-style="color:..."`, `test_phase8_settings_hub.py`'s
  `onchange="this.form.requestSubmit()"` assertion -> `data-change-
  submit`. `sw.js` CACHE_NAME bumped v59 -> v60 (style.css changed
  extensively; new `dynamic_styles.js` added to `SHELL_ASSETS`, same
  "base.html script needed on every page" category as `a11y_icon_
  labels.js`; app.js/data_maintenance.js/habit_checkin.js also changed),
  `test_pwa_shell.py`'s pin updated. Full suite: 1975 passed (+5 net new
  tests over the 1970 baseline), verified independently after the
  implementing agent's own run -- both counts agreed, `test_caldav_
  bridge_live.py` excluded as always. Also independently grepped the
  whole `templates/`/`security_headers.py` tree afterward for
  `unsafe-inline`/stray `style="`/`onclick=`/`onchange=` -- zero real
  hits (the one remaining `style="` grep match was the doc-comment false
  positive noted above).

  Implemented via a dispatched agent (repo-wide mechanical scope across
  25 templates, 4 new/changed JS files, and style.css -- not hand-edited
  inline this session) given the size; verified independently afterward
  (full test suite re-run from scratch in 12 parallel chunks, diff read
  for `security_headers.py`/`deps.py`/`dynamic_styles.js`, grep sweep for
  any residual `unsafe-inline`/`style=`/`onclick=`/`onchange=`) rather
  than taking its own report at face value.

  **Next slice:** none mandatory -- item 11 was the last item on the
  original pre-2.0 list (`audit-fixes-2.0.md`'s items 1-11). Second-wave
  items 12-15 (z-index scale, item 9's UI polish, item 13's icon-button
  dedup, item 14's empty-state-row dedup, item 15's stale-roadmap-claim
  fix) are **all already shipped** too, per this file's own entries above
  -- `audit-fixes-2.0.md` has nothing left open. Check `roadmap.md`'s 2.0
  section fresh next session to confirm 2.0 is actually ready to ship, or
  whether anything else was scoped into that release beyond this fix
  list.

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md item 15, the stale
  `roadmap.md` claim about Tasks-table pagination. Confirmed via `git log`
  (per the audit item's own citation) that commit `2162403` shipped
  `GET /tasks?page=&limit=` pagination of the Table view's ungrouped Open
  section 2026-08-15, then `d86a34d` ("Major rework session, 2026-08-28")
  retired it as a side effect of making the Tasks table's Project ->
  Habits -> Unassigned -> Completed grouping unconditional -- that
  commit's own message says "pagination retired as a consequence." Not a
  bug, nothing to restore: the grouped design has no ungrouped "Open
  section" left to paginate.

  Pure documentation fix, matching how this doc already marks other
  superseded decisions (`~~strikethrough~~` + a "shipped ... as a slice"
  note, e.g. the Phase B pagination/collapsible-sections line right above
  the 1.9 section). Updated two spots in `roadmap.md`: the top-of-file
  1.9 changelog parenthetical (added "later superseded 2026-08-28, see
  1.9 below") and the 1.9 section's own pagination paragraph (past tense
  + a new "**Superseded 2026-08-28:**" explanation, same shape). Left the
  "Things that can slip past the map" section's own item-15 summary alone
  -- it already correctly describes this as a stale claim to fix, no
  update needed there.

  No code touched, nothing in `tests/` references this roadmap text --
  no test run needed (same reasoning as every other doc-only slice in
  this file, e.g. the 2026-09-03 STATE.md trim).

  **Next slice** (per `audit-fixes-2.0.md`'s order): item 11, the CSP
  `unsafe-inline` migration -- the only item left in the list, deliberately
  saved for last as the largest/riskiest (touches every inline
  script/style across templates, move `security_headers.py:52-62` to a
  nonce-based CSP for script-src/style-src).

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md item 14, the empty-state
  table row, duplicated 5x. `labels_manage.html`, `settings_holidays.html`,
  and `settings_time_blocks.html` (Sleep and Leisure -- two independent
  call sites, same pattern as items 9/13) each repeated an identical
  `<tr id="empty-state-row"><td colspan="5" class="text-muted" style=
  "font-size: var(--text-footnote);">No {X} yet</td></tr>`.
  `_labels_table_body.html` repeated the same *id*, but -- read directly
  rather than assumed from the audit item's own "differing only in
  colspan and message" framing -- its actual markup is a materially
  different shape: `colspan="4"`, the app's shared `.empty-state` class
  instead of `text-muted` + inline style (that class already supplies its
  own padding/color/font-size, so an inline style there would be
  redundant), and a richer message with a call-to-action and literal
  `&lsquo;`/`&rsquo;` entities.

  New `_empty_state_row.html` macro (`empty_state_row(colspan, message,
  css_class='text-muted', style='font-size: var(--text-footnote);')`),
  its own file rather than folded into `_bulk_actions_bar.html`/
  `_row_action_buttons.html` -- matching how `_label_pill.html` (a
  similarly tiny one-line macro) is already scoped to its own file, per
  the audit item's own suggestion to check that convention first.
  `message` renders with `|safe` so `_labels_table_body.html`'s entity
  markup renders as intended instead of being double-escaped -- every
  call site's `message` is a static string authored in this codebase,
  never user input, same trust boundary the un-extracted markup already
  had. `settings_data_maintenance.html:191`'s "No backups yet" `<span>`
  stayed out of scope, per the audit item's own explicit carve-out (a
  plain list `<span>`, not a `<tr>`/`<td>`, a naming coincidence not real
  duplication).

  Grepped `tests/` for `empty-state-row`/`empty-state`/each of the 5 call
  sites' own message text first: three tests assert the message text
  itself (`test_settings_time_blocks.py`'s Sleep/Leisure strings,
  `test_settings_holidays.py`'s Holidays string) and survive unchanged
  since the macro renders identical text; nothing hardcoded the old
  `class`/`colspan`/inline-style markup directly, so no test changes
  needed. Pure template change, no CSS/JS touched, no new/removed static
  asset -- no `sw.js` bump needed (same "templates-only" reasoning as
  items 8/9/13). Full suite: 1970 passed (same count as item 13 -- pure
  markup refactor, no row/behavior change), run as 12 parallel background
  chunks in one bash call, `test_caldav_bridge_live.py` excluded as
  always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): item 15 (stale
  roadmap claim about Tasks-table pagination -- a two-minute doc fix), or
  item 11 (CSP `unsafe-inline` migration, still deliberately skipped,
  largest/riskiest -- the only remaining item after 15). No dependency
  chain between 15 and 11.

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md item 13, the icon-button
  Edit/Delete pair extraction (same shape as item 9's `.bulk-actions-bar`
  extraction, not caught in that pass). `settings_holidays.html`,
  `settings_time_blocks.html` (Sleep and Leisure -- two independent call
  sites, same as item 9), `labels_manage.html`, and `_labels_table_body.html`
  each repeated an identical `<div class="action-buttons">` block (an Edit
  icon-link opening a modal + a Delete `<form>` with a confirm-sheet),
  differing only in the edit/delete URLs, the `title` noun, and the
  confirm-sheet message text.

  New `_row_action_buttons.html` macro (`row_action_buttons(edit_url,
  delete_url, noun, confirm_message)`), following the exact convention
  `_bulk_actions_bar.html` established in item 9 (header comment explaining
  what it replaces and why, imported via `{% from ... import ... %}` at
  each call site, no `with context` needed -- `icon()` is a Jinja global,
  same as the bulk-bar macro). `confirm_message` stays a full parameter
  assembled by each caller (e.g. `'Delete "' ~ (h.label or '(untitled)') ~
  '"? This removes...'`) rather than a template the macro fills in, per the
  audit item's own note that the trailing wording varies enough per-caller
  (labels' "clears usage, not a real delete" phrasing) that it can't be
  generic.

  One behavioral wrinkle, called out in the macro's own header comment:
  the un-extracted markup had each confirm-sheet message written as literal
  template text with a bare `"` char embedded mid-string (e.g.
  `data-confirm-sheet="Delete "{{ h.label }}"? ..."`), which is invalid
  HTML -- the browser's attribute parser ends at that first embedded quote.
  Moving the message into a `{{ confirm_message }}` variable means Jinja's
  normal autoescaping now converts those embedded `"` into `&quot;`, which
  a browser decodes back to `"` when JS reads `dataset.confirmSheet` --
  same string the confirm-sheet code sees either way, but now inside valid
  HTML instead of a malformed attribute. Not treated as a fix in scope for
  this item (nothing asked for it), just a side effect of the extraction
  worth flagging in case it's ever cited as intentional elsewhere.

  Grepped `tests/` for `action-buttons`/`data-confirm-sheet` plus each of
  the 4 templates' own title text first (`test_settings_holidays.py`'s
  `assert "Edit holiday" in body` is the only hit tied to this markup) --
  survives unchanged since the macro renders the identical title strings.
  No test hardcoded the old `<div class="action-buttons">` structure
  itself. Pure template change, no CSS/JS touched, no new/removed static
  asset -- no `sw.js` bump needed (same "templates-only" reasoning as
  items 8/9). Full suite: 1970 passed (same count as item 12 -- pure
  markup refactor, no row/behavior change), run as 12 parallel background
  chunks in one bash call, `test_caldav_bridge_live.py` excluded as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): item 14 (empty-state
  table row, duplicated 5x -- `_labels_table_body.html`, `labels_manage.
  html`, `settings_holidays.html`, `settings_time_blocks.html` twice) or
  item 15, or item 11 (CSP `unsafe-inline` migration, still deliberately
  skipped, largest/riskiest). No dependency chain between any of them.

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md item 12, a shared z-index
  scale (skipped item 11, the CSP `unsafe-inline` migration, per direct
  request -- still open, see below). The item's own investigation had
  already confirmed today's stacking is *correct*, just correct via a
  dozen scattered comments cross-referencing each other instead of one
  source of truth -- this was a naming/documentation refactor, not a
  fix, with the item's own warning to heed: "don't just sort-and-
  renumber... some orderings are load-bearing."

  Scoped deliberately, after reading all 51 `z-index` grep hits in
  `style.css` (39 live declarations, the rest inside comments) in full
  context: only the **fixed/portal-positioned overlay and nav elements
  that can end up stacked against each other at the same time** got
  named tokens -- 9 new custom properties in the Tokens block
  (`--z-rail`, `--z-fab`, `--z-modal`, `--z-nav-scrim`,
  `--z-overlay-panel`, `--z-mobile-tabbar`, `--z-modal-stacked`,
  `--z-toast`, `--z-top`), covering 16 call sites: `.tabbar` (both its
  desktop-rail value and its separate mobile-bottom-sheet-drawer value),
  `.fab`, `.modal-overlay`, `.mobile-nav-scrim`, `.mobile-tabbar`,
  `.toast-stack`, `.command-palette-overlay`, `.cropper-overlay`,
  `.multiselect-panel`, `.action-menu-panel`, `.color-popover`,
  `.icon-popover`, `.dtp-panel`, `.skip-link`, `.drag-ghost`. Every
  value matches exactly what was already hardcoded at that site --
  confirmed mechanically afterward (grepped each new variable's own
  name, counted occurrences against the expected definition + comment-
  mention + usage-site count for every single one).

  **Deliberately left as raw numbers:** the many single-component drag/
  lift z-index values inside the Calendar/Timeline/Month grids
  (`.time-event`/`.time-event.dragging`, `.schedule-ghost`,
  `.allday-task.dragging`, `.month-event-item.dragging`,
  `.timeline-gutter-sep`/`-row`, `.timeline-create-ghost`,
  `.widget-card.is-dragging`/`.is-stack-target`), plus small single-use
  resets (`.seg-btn`, `.tab-btn.active::before`, `.month-day-cell`,
  `.modal-close`, page-banner/header layering). Each of these only ever
  orders itself against its own siblings inside one local stacking
  context that's already explained right where it's declared (some of
  those very comments describe a *previously fixed* regression from
  values leaking across contexts, e.g. the 2026-08-09 time-grid fix) --
  they never compete against the cross-component overlay ladder, so
  folding them into the same token set would document a relationship
  that doesn't actually exist. New token block's own header comment
  states this scoping explicitly for the next person who edits it.

  Comments with an explicit bare-number callout got updated to point at
  the new variable name instead (the skip-link's "z-index:1000 matches
  the app's highest existing layer" comment, and `.multiselect-panel`'s
  "z-index matches those two popovers (150) -- needs to sit above ...
  (100)" comment) -- every other comment either had no literal number in
  its prose or didn't need touching.

  No CSS-rendering test harness in this suite (per this file's own
  recurring note), and `grep`ping `tests/` for `z-index` first turned up
  zero hits -- no test asserts any of these values today. Manual check
  substituted for a screenshot pass (no browser available in this
  session's sandbox, same constraint noted in earlier CSS-only slices):
  traced every one of the 16 converted call sites back to its resolved
  numeric value and confirmed each matches its pre-refactor number
  exactly, so the actual stacking order (modal 100 < overlay-panel/
  drawer 150 < mobile-tabbar 160 < modal-stacked/toast 200 < top 1000,
  and nav-scrim 140 < overlay-panel 150 < mobile-tabbar 160 for the
  mobile drawer specifically) is unchanged -- this is a refactor
  verified by construction (every substitution grepped 1:1 against its
  original raw number before commit), not by rendering the page.
  `sw.js` CACHE_NAME bumped v58 -> v59 (`style.css` content changed),
  `test_pwa_shell.py`'s pin updated. Full suite: 1970 passed (same count
  as item 10 -- pure CSS token refactor, no row/behavior change).

  **Next slice:** item 11 (CSP `unsafe-inline` migration, still
  deliberately skipped, largest/riskiest item) or items 13-15 (icon-
  button edit/delete pair dedup, and whatever items 14-15 turn out to
  be per `audit-fixes-2.0.md`) -- no dependency chain between any of
  them, pick whichever next per the usual one-slice-per-session
  discipline.

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md item 10, performance
  housekeeping (the last mandatory item before the CSP `unsafe-inline`
  migration). Two parts per the doc's own spec:
  1. **`defer` added to every global/page `<script src>` tag.** Not just
     `base.html`'s 22 global scripts (lines 504-611 at the time this slice
     started) -- auditing first (via a dispatched research pass) found
     that `base.html`'s own `{% block extra_scripts %}` placeholder is
     immediately followed, in the rendered HTML, by each page template's
     page-specific scripts, and those were still plain synchronous
     `<script src>` tags. Deferring only the base.html globals while
     leaving page-specific scripts synchronous would have **reversed**
     execution order: deferred scripts run only after the whole document
     finishes parsing (right before `DOMContentLoaded`), so a page's own
     synchronous extra_scripts content would have started running before
     `window.ccApi` (async_crud.js), `CCModal`, `CCQuickAdd`, etc. existed
     -- exactly the kind of regression this suite's lack of a JS-execution
     test harness wouldn't catch. Fixed by deferring both: base.html's 22
     tags, plus every `<script src>` in the 15 page templates that
     override extra_scripts with real script tags (`tasks_list.html`,
     `calendar_fourweek.html`, `calendar_month.html`, `calendar_day.html`,
     `calendar_week.html`, `label_detail.html`, `dashboard.html`,
     `contacts_list.html`, `published_lists.html`, `notes.html`,
     `habit_detail.html`, `offline.html`, `settings_data_maintenance.html`,
     `labels_manage.html`, `settings_time_blocks.html`,
     `settings_holidays.html`). `time_block_edit_modal.html`/
     `holiday_edit_modal.html` were confirmed to have no real
     extra_scripts content (modal-only templates, per their own comments)
     -- correctly excluded. Inline `<script>` blocks with no `src`
     (base.html's head theme-init script; extra_scripts' own inline
     blocks like `calendar_week.html`'s `window.PROJECT_CALENDAR`
     assignment, and the `bulk_select.js`-consuming `DOMContentLoaded`
     listeners in `labels_manage.html`/`settings_time_blocks.html`/
     `settings_holidays.html`) can't take `defer` (browsers ignore it on
     scripts without `src`) and didn't need to -- audited each one first
     and confirmed none calls a base-global synchronously at top level
     outside a `DOMContentLoaded` listener or later `onclick` handler, so
     none was at risk. The four PWA-shell scripts already disabled inside
     a Jinja `{# #}` comment (pwa.js, offline_db.js,
     offline_sync_client.js, offline_status.js) were left alone -- dead
     code, never rendered either way.
  2. **Dependency lockfile check.** `pyproject.toml`'s own deps are indeed
     lower-bounded only, as the audit item says, but `uv.lock` (repo root,
     tracked in git, not gitignored) already pins every dependency to an
     exact version with a hash -- confirmed by reading it directly rather
     than trusting the audit item's framing at face value. No action
     needed for this half of the item.
  No `sw.js` bump -- only the `defer` attribute changed on existing
  `<script>` tags in templates; no static JS file content changed and no
  entry was added to or removed from `SHELL_ASSETS`, same "templates-only
  change" reasoning as every other slice in this list that didn't bump
  the cache version. Full suite: 1970 passed (same count as slice 9 -- a
  load-order/timing change with no test harness for JS execution in this
  suite, verified instead by the extra_scripts audit above rather than a
  new test), run as 84 parallel per-file background processes in one
  call, `test_caldav_bridge_live.py` excluded as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): #11, the CSP
  `unsafe-inline` migration -- move `security_headers.py:52-62` to a
  nonce-based CSP for script-src/style-src. Saved for last on purpose:
  largest and riskiest item in the list, touches every inline
  script/style across templates. Independent second-wave items #12-15
  also remain open (z-index scale, and others per `audit-fixes-2.0.md`'s
  own listing) -- no dependency chain between them and #11, doable in any
  order.

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md item 9, lower-priority UI
  consistency polish, reached via a user-shared proposal to restructure
  `templates/` into a layouts/components/widgets/pages folder split
  (plus a `.ui-*` CSS prefix). Before adopting that wholesale, checked it
  against the actual codebase: `templates/` already has 94 files, 13 of
  which use `{% macro %}` for parameterized reusable pieces, and an
  established underscore-prefix partial convention (`_widget_card.html`,
  `_label_pill.html`, `_detail_cover.html`, `_modal_footer.html`, etc.) --
  a lighter version of the proposed split, already working. Buttons
  turned out to already be one consistent `.btn primary/ghost/danger/
  tonal` + `.btn-sm` convention (grepped every `class="...btn..."` variant
  across templates first), not the "twelve independent implementations"
  the proposal's framing assumed. So a folder/prefix rename was judged
  not worth the churn -- see `roadmap.md`'s 2.0 section for the full
  verdict -- and the proposal's one piece of grep-confirmed real
  duplication was folded into this already-planned item instead of
  standing up a parallel track. All three of item 9's sub-items landed:

  1. **`.bulk-actions-bar` extraction.** New `_bulk_actions_bar.html`
     macro (`bulk_actions_bar(id_prefix, delete_label='Delete')`) replaces
     four copies of the same `<div class="bulk-actions-bar">` +
     `.bulk-count` span + spacer + Delete/Clear button block that had
     drifted apart only in id prefix and the Delete label:
     `settings_holidays.html`, `settings_time_blocks.html` (Sleep *and*
     Leisure sections -- two separate macro calls, two independent
     `CCBulkSelect` instances as before), `labels_manage.html` (Delete
     label overridden to "Remove from everything", its own established
     wording). `tasks_list.html`'s bar deliberately stayed out of scope --
     confirmed via `static/bulk_select.js`'s own header comment that it's
     driven by bespoke `tasks_table.js` (richer per-domain bulk actions,
     async-CRUD region-swap reconciliation) with unprefixed ids
     (`bulk-actions-bar`/`bulk-count`), not `CCBulkSelect` -- exactly what
     the audit item's own wording already scoped to ("three-plus copies
     across settings_holidays.html, settings_time_blocks.html,
     labels_manage.html", no mention of tasks_list.html).
  2. **`.card-danger` utility class** (style.css, next to `.card`) replaces
     `settings_data_maintenance.html`'s one-off inline `style="background:
     var(--tag-red-bg);border:1px solid var(--tag-red-fg)"` on the "Needs
     attention" card. Named generically (not e.g. `.card-needs-attention`)
     since a warning-tinted card isn't unique to that one page.
  3. **`_filter_dropdown.html`'s wrapper question, confirmed still earning
     its keep.** Investigated rather than assumed: it isn't actually a
     wrapper over `_widget_list_multiselect.html` at all (no include/
     extend relationship) -- it's a parallel template that deliberately
     duplicates the `.multiselect`/`.multiselect-trigger`/`.multiselect-
     panel` markup/CSS classes while sharing the same JS handler, per its
     own header comment, because the semantics genuinely differ (GET-
     navigate page filter vs. a `<form>`-bound field saved via a Save
     button). No code change -- the audit item's "confirm" framing
     already allowed for that as a valid outcome.

  `sw.js` CACHE_NAME bumped v57 -> v58 (style.css changed again; new
  `_bulk_actions_bar.html` template is not in `SHELL_ASSETS`, same
  "server-rendered template, not a static asset" reasoning as every prior
  templates-only addition), `test_pwa_shell.py`'s pin updated.
  `test_data_health.py::test_needs_attention_section_appears_only_when_
  something_is_wrong` updated for the new `class="card card-danger"`
  marker (was asserting the old inline-style string). Grepped `tests/`
  for the old `.bulk-actions-bar` ids/markup first -- no other test
  hardcoded the pre-extraction structure, only that one inline-style
  assertion needed updating. Full suite: 1970 passed (same count as item
  8 -- pure markup refactor + one assertion-string update, no row/
  behavior change), run as 84 parallel per-file background processes in
  one call, `test_caldav_bridge_live.py` excluded as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): #10, performance
  housekeeping (`defer` on the 24 `<script>` tags) -- the last mandatory
  item before the CSP `unsafe-inline` migration, sequenced last on
  purpose for being the largest/riskiest.

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md slice 8, settings-page
  heading consistency (`audit-fixes-2.0.md`'s item 8). Wrapped
  `settings_holidays.html`'s and `settings_time_blocks.html`'s sections in
  the `.settings-group` + `h2.section-label` pattern `settings_general.
  html`/`settings_appearance.html`/`settings_data_maintenance.html` already
  use, replacing bare `<h1>`-only content (Holidays) and inline-styled
  `<h2 style="margin:...">` sub-headings (Sleep Time / Leisure Time).

  `settings_holidays.html` had only one logical section, so the whole
  bulk-actions-bar + table block is now wrapped in one `<div class=
  "settings-group">` with a new `<h2 class="section-label">{{ icon
  ('calendar', 'icon-sm') }} Holidays</h2>` -- the page's own `<h1>Holidays
  </h1>` title is left in place (same "h1 page title + h2 section label"
  layering `settings_data_maintenance.html` already uses), even though the
  two labels read the same word here since there's only one section to
  name. `settings_time_blocks.html` got two `.settings-group` wraps, one
  per existing sub-section, each swapping its old `style="margin:..."` h2
  for `<h2 class="section-label">` with `moon`/`sun` icons (matching the
  page's own `moon` header icon for Sleep, `sun` as Leisure's nearest
  sprite-available opposite -- no dedicated "leisure" icon exists in
  `_icons_sprite.html`).

  Pure template change (both files), no CSS/JS touched -- `.settings-group`/
  `.section-label` are pre-existing classes already used elsewhere, nothing
  new added to style.css. No `sw.js` bump needed (server-rendered templates,
  not static assets, same reasoning as every other templates-only slice in
  this list). Grepped `tests/` for the old markup first (`Sleep Time`,
  `Leisure Time`, `settings_holidays`, `settings_time_blocks`, bare
  `<h1>Holidays</h1>`) -- no test asserted the removed inline styles or the
  old unwrapped structure, so no test changes needed. Full suite: 1970
  passed (same count as slice 7 -- no row/behavior change), run as 84
  parallel per-file background processes in one call, `test_caldav_
  bridge_live.py` excluded as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): #9, lower-priority UI
  consistency polish (optional, doesn't block 2.0 -- promote
  `settings_data_maintenance.html`'s inline-styled "Needs attention" card
  to a `.card-danger`/`.card-tinted` utility class; extract the copy-pasted
  `.bulk-actions-bar` markup across `settings_holidays.html`/
  `settings_time_blocks.html`/`labels_manage.html` into one shared partial;
  confirm whether `_filter_dropdown.html`'s class-renaming wrapper over
  `_widget_list_multiselect.html` is still earning its keep). If skipping
  #9 as optional, the next mandatory slice is #10, performance housekeeping
  (`defer` on the 24 `<script>` tags).

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md slice 7, dead code cleanup
  (`documentation/plans/audit-fixes-2.0.md`'s item 7). Deleted `db.py`'s
  `find_contact_by_name` and `list_task_label_names` (zero call sites
  anywhere, confirmed via repo-wide grep including tests/) and six
  orphaned templates: `_labels_body.html`, `_widget_add_form.html`,
  `_task_relations.html`, `_event_relations.html`, `label_edit_modal.html`,
  `_task_heatmap.html`.

  Per this file's own flag from the previous slice ("before deleting
  `_task_heatmap.html`, confirm whether `task_detail.html` used to render
  a recurring-task heatmap and silently lost it"), investigated via git
  history before deleting: it was never wired up, even at the commit that
  created it -- `task_detail.html` never included it, at any point in its
  history. Not a regression. Habit-task detail pages render a heatmap via
  a separate, still-live file (`_habit_heatmap.html`) -- unrelated to this
  one. The other five templates were already confirmed dead/unreferenced
  by comments left during the 2026-09-03 `.detail-identity-dot`/
  `.relations-group` cleanup, and their retired CSS classes were already
  removed in that prior work -- verified by grep before this slice, no
  further CSS cleanup needed here (the audit doc's "closes two report
  items at once" framing had already happened as a side effect of earlier
  work, not left for this slice).

  One test hardcoded a since-deleted filename:
  `test_modal_uniformization.py::test_every_modal_template_includes_
  shared_footer`'s modal-file sweep list included `label_edit_modal.html`
  literally -- removed the entry (the test's purpose, every modal
  template includes the shared footer partial, doesn't need a template
  that no longer exists in the list). No other test referenced any of the
  six deleted files (grepped `tests/` for each name first). No `sw.js`
  bump needed -- none of the deleted files are in `SHELL_ASSETS` (server-
  rendered templates, not static assets), same reasoning as the N+1 fix
  in slice 3. Full suite: 1970 passed (same count as slice 6 -- pure
  deletions, no new coverage needed), run as 84 parallel per-file
  background processes in one call, `test_caldav_bridge_live.py` excluded
  as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): #8, settings-page
  heading consistency -- wrap `settings_holidays.html`'s heading to match
  the pattern other settings pages use (see the doc's item 8 for the
  exact spec).

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md slice 6, the touch-target +
  skip-link + contrast bundle (`documentation/reports/full-app-audit-
  2026-09-07.md`'s remaining low/medium accessibility findings not covered
  by slices 4/5). One CSS-mostly slice, same shape as the 2026-09-04
  touch-target session:
  1. **Coarse-pointer size bumps** for `.color-swatch-current` (20px ->
     32px) and `.heatmap-cell` (11px -> 16px), same `@media (pointer:
     coarse)` pattern `.icon-btn`'s existing fix already established --
     `.heatmap{overflow-x:auto}` already handles a wider grid, so growing
     cells needed no other layout change.
  2. **`.stepper-btn` fixed on both axes**: a coarse-pointer width bump
     (30px -> 44px, matching the app's own "~44px touch-target floor"
     precedent) plus `tabindex="-1"` removed from all 12 occurrences
     across 6 templates (`_task_form_fields.html`, `_widget_builder_
     fields.html`, `habit_form.html`, `_widget_edit_form.html`,
     `habit_task_form.html`, `_habit_detail_body.html`) -- these are real
     `<button>` elements with their own `aria-label`, `stepper.js` only
     ever binds a click handler, so removing the attribute restores
     natural tab order with no JS change needed.
  3. **New skip-to-content link** (`base.html`, first element in `<body>`,
     before `_icons_sprite.html`/`.app-window`) jumping to a new `id=
     "main-content"` on the existing `<main>`. New `.skip-link` CSS class
     (style.css, next to `.sr-only`) -- deliberately not `.sr-only` itself,
     since that's clip-based with no un-clip state; this one sits off-
     screen via `top:-40px` and slides to `top:var(--space-3)` on
     `:focus`, `z-index:1000` (the app's highest existing layer) so it
     renders above the sidebar/topbar it's meant to skip past.
  4. **`--fg-tertiary` darkened, light theme only** (`#8e8e93` ->
     `#737378`) -- the old value read ~3.3:1 against `--bg-elevated`,
     below WCAG AA's 4.5:1, and is used at small sizes in several places
     (`.week-overview-day-label`, `.heatmap-empty`, `.heatmap-month-
     label`). `#737378` clears 4.5:1+ against white while staying
     visibly a step lighter than `--fg-secondary` (`#6e6e73`) -- verified
     with a short ad hoc relative-luminance/contrast-ratio script, not
     eyeballed. Dark theme's `--fg-tertiary` (`#a3a3a8`) was left alone --
     already clears ~4.3:1+ against its own backgrounds, and the audit
     finding was scoped to light theme specifically.
  5. **`.week-overview-grid`'s breakpoint aligned**: `700px` -> `720px`,
     matching the ~20 other `max-width:720px`/`min-width:721px` uses
     already in style.css (confirmed via grep which of 720/721 dominates
     before picking).
  `sw.js` CACHE_NAME bumped v56 -> v57 (style.css + base.html changed, no
  new files added to `SHELL_ASSETS`), `test_pwa_shell.py`'s pin updated.
  No test asserted the old stepper `tabindex="-1"`, the 700px breakpoint,
  or the pre-darkened `--fg-tertiary` value (grepped `tests/` for each
  first) -- no test changes needed. Full suite: 1970 passed (same count as
  slices 4/5 -- no row/behavior change to add coverage for), run as 84
  parallel per-file background processes in one call, `test_caldav_
  bridge_live.py` excluded as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): #7, dead code
  cleanup -- delete `db.py`'s `find_contact_by_name`/`list_task_label_
  names` and templates `_labels_body.html`/`_widget_add_form.html`/
  `_task_relations.html`/`_event_relations.html`/`label_edit_modal.html`.
  Before deleting `_task_heatmap.html`, confirm whether `task_detail.html`
  used to render a recurring-task heatmap and silently lost it (regression)
  versus the comment just being stale -- do not delete on the assumption
  it's dead until that's confirmed.

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md slice 5, icon-only
  accessible names (`documentation/reports/full-app-audit-2026-09-07.md`'s
  "icon-only buttons relying on `title` alone with no `aria-label`" finding
  -- `_task_row.html:144`/`_habit_row.html:115`'s row-delete buttons,
  `labels_manage.html`/`_labels_table_body.html`/`settings_holidays.html`/
  `settings_time_blocks.html`'s Edit/Delete icon links, and a longer tail
  across widget/picker/relation-row templates).

  The doc's own sketch asked for "ideally a shared macro/JS default keyed
  off the existing title, not 30 hand-edited templates" -- landed as a
  single new global script, **zero template edits**, rather than even the
  macro option: `static/a11y_icon_labels.js` scans for the underlying
  pattern (`[title]:not([aria-label]):not([aria-labelledby])` on a
  `button`/`a`/`label`/`input` whose `textContent` is empty once whitespace
  is stripped -- i.e. genuinely icon-only, nothing visible for the name to
  already come from) and copies `title` onto `aria-label`. Elements that
  *do* have visible text alongside an icon (e.g. `_calendar_week_grid.html`'s
  all-day task links, icon + `{{ t.title }}`) are deliberately skipped --
  their accessible name already comes from that visible text, and
  overwriting it with just the bare `title` string would drop text a
  sighted user can see (WCAG 2.5.3), not fix anything. Confirmed via
  `deps.py::_icon`'s own docstring/output (`<svg class="icon" aria-hidden=
  "true"><use ...></svg>`, no inner text ever) that every existing
  icon-only control's `textContent` really is empty -- the heuristic isn't
  guessing.

  Runs once on `DOMContentLoaded` over the whole document, then a
  `MutationObserver` on `document.documentElement` (childList+subtree)
  covers everything added afterward -- modal.js's innerHTML content swap,
  async_crud.js's region refreshes, quick_add/command-palette inserts --
  with **no per-feature `wireContent()` hook needed**, unlike every other
  modal-injected-content script in this app (label_role_picker.js,
  event_format_toggle.js, etc., each needs its own `window.CCWhatever.
  init(body)` call from modal.js). This one script's coverage is
  unconditional and automatic, including for any future icon-only control
  nobody remembers to hand-annotate.

  Loaded globally in `base.html` right after `mobile_nav_drawer.js` (same
  "base.html script needed on every page" category). `sw.js` CACHE_NAME
  bumped v55 -> v56 (new script added to `SHELL_ASSETS`, same reasoning as
  `mobile_nav_drawer.js`'s own v53 entry), `test_pwa_shell.py`'s pin
  updated. No test harness for JS behavior in this suite (per this file's
  own recurring note) -- verified by reading `deps.py::_icon`'s actual
  output plus every touch-point template listed in the audit (all render
  `title` with no accompanying visible text, confirmed by reading each
  file directly, not assumed from the audit's own summary) rather than a
  new test. Full suite: 1970 passed (same count as slice 4 -- no Python/
  template change to add coverage for), run as 84 parallel per-file
  background processes in one call, `test_caldav_bridge_live.py` excluded
  as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): #6, the touch-target +
  skip-link + contrast bundle -- coarse-pointer size bumps for
  `.color-swatch-current`/`.heatmap-cell`, fixing `.stepper-btn` (missing
  coarse-pointer size AND `tabindex="-1"` removing it from tab order), a
  skip-to-content link in `base.html`, darkening `--fg-tertiary` (light
  theme) or restricting it to large/bold text, and aligning
  `.week-overview-grid`'s `700px` breakpoint to the app's standard `720px`.

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md slice 4, the modal keyboard
  focus trap (`documentation/reports/full-app-audit-2026-09-07.md` finding
  #2, the one accessibility finding rated high -- WCAG 2.1.2/2.4.3, a
  keyboard user could Tab straight out of an open modal into the page
  behind it). `static/modal.js` previously had only an Escape handler
  (line 557); added `trapTabKey`, wired into the same document-level
  `keydown` listener, alongside a new `getFocusableElements`/
  `FOCUSABLE_SELECTOR` helper. Queries `#modal-dialog` (the persistent
  wrapper element -- see `stabilizeHeight`'s own comment on why this is
  the stable element to query, not `#modal-body`, since content underneath
  it gets swapped by `refreshModalContent`/navigation) fresh on every
  Tab keypress rather than caching a focusable list at open time, so it
  stays correct across those swaps. Shift+Tab off the first focusable (or
  from outside the dialog entirely) wraps to last; Tab off the last (or
  from outside) wraps to first; a modal with zero focusable elements
  (rare, but not provably impossible) sends focus to the dialog itself
  instead of doing nothing -- needed `tabindex="-1"` added to
  `#modal-dialog` in `base.html` (JS-focusable fallback target, not in the
  natural tab order).

  `sw.js` CACHE_NAME bumped v54 -> v55 (`modal.js` is in `SHELL_ASSETS`),
  `test_pwa_shell.py`'s pin updated. No existing test exercises modal
  keyboard behavior (this suite has no JS-execution harness, per this
  file's own recurring note) -- grepped `tests/` for `focus.trap`/`Tab`/
  `modal.js` first, the only hits were `test_pwa_shell.py`'s precache-list
  assertion, already updated. Full suite: all 84 non-live test files
  green, run as one file-per-background-process batch inside a single
  bash call (16 cores available this session, so per-file parallelism
  finished well under the 45s per-call cap instead of needing pre-built
  chunk files -- `test_caldav_bridge_live.py` excluded as always).

  **Next slice** (per `audit-fixes-2.0.md`'s order): #5, icon-button
  accessible names -- an `aria-label` fallback keyed off each element's
  existing `title`, touching `_task_row.html:144`, `_habit_row.html:115`,
  `labels_manage.html:75`, `_labels_table_body.html:28`,
  `settings_holidays.html:61`, `settings_time_blocks.html:63,125`, and the
  widget/picker/relation-row templates the audit report lists. Mechanical,
  many touch points, low risk.

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md slice 3, the N+1 query fix
  flagged as the highest-impact single fix in the whole audit report
  (`documentation/reports/full-app-audit-2026-09-07.md` finding #1).
  `db.py:1415` `_attach_tags` and `db.py:3030` `_attach_contact_phones_
  emails` were each called once per row inside every `list_*`/`_search_*`
  function (14 call sites: `list_events`, `list_tasks_*` x3, `related_
  tasks_for_event`, `related_events_for_task`, `work_allocations_for_task`,
  `list_tasks_by_labels`, `list_events_by_labels`, `_search_tasks`,
  `_search_events`, `_search_contacts`, `_search_notes`, `list_contacts`,
  `list_notes`) -- each contact row alone cost the base query plus 6 extra
  per-row queries (tags + 5 child tables: phones/emails/websites/
  addresses/social_profiles).

  Fixed with two new batch helpers, `_attach_tags_bulk` and `_attach_
  contact_phones_emails_bulk` (both right next to their per-row
  originals), each running one `SELECT ... WHERE ... IN (...)` for the
  whole result set and grouping rows by uid in Python instead of querying
  per row. Every one of the 14 call sites above now decodes its rows into
  plain dicts first (`_row_to_dict`), batch-attaches tags (and phones/
  emails for contacts) once, then does whatever per-row shaping it used to
  do (search's `out.append({...})`, `list_contacts`'s photo-version
  backfill) over the already-tagged dicts. The single-row `get_event`/
  `get_task`/`get_contact`/`get_note`-style functions were deliberately
  left calling the original per-row `_attach_tags`/`_attach_contact_
  phones_emails` -- one row has no N+1 to fix, and a bulk query of size 1
  would just be the same query with extra ceremony.

  No schema change, no row-shape change (each dict still gets the same
  `tags`/`phones`/`emails`/etc. keys attached, just computed via a
  different query shape) -- existing tests cover this as-is, no test
  changes needed. Pure Python change, isolated to db.py, no template/CSS/
  JS touched -- no `sw.js` bump needed. Full suite: 1970 passed, run as 12
  parallel background chunks within one call (this sandbox's own /tmp-
  and background-process-don't-persist-between-bash-calls limitation, same
  as every other multi-chunk session this file documents -- build the file
  list, split, launch, and `wait` all inside one call), `test_caldav_
  bridge_live.py` excluded as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): #4, the modal
  keyboard focus trap (`static/modal.js` -- Tab/Shift+Tab cycling within
  an open `.modal`).

- **Shipped:** 2026-09-07 -- audit-fixes-2.0.md slice 2, "silent-
  misconfiguration guards" (two independent fixes, `documentation/reports/
  full-app-audit-2026-09-07.md` findings #4 and the `config.py:69` Radicale
  one). Both diverged from the doc's original one-line sketch once actually
  implemented -- see `audit-fixes-2.0.md`'s own entry for the reasoning,
  summarized here:

  1. **Non-loopback exposure warning** (`src/auth.py`). The finding asked
     for a startup-time check, but the ASGI app is never told what host
     uvicorn bound to (systemd's `--host 0.0.0.0`, `main.py::main()`'s own
     hardcoded `0.0.0.0`, and a bare `uvicorn` CLI invocation all bypass
     any config this app owns) -- there is no "at startup" hook with that
     information. Landed as a request-time check instead:
     `AuthMiddleware._warn_if_exposed`, called from the existing `elif not
     self._configured(...)` branch (the exact "deploy_mode == local, no
     account configured, i.e. auth is genuinely off" branch, so no new DB
     read), reads the real local socket address off `scope["server"]` --
     for a listener bound to `0.0.0.0`, that's the actual interface a
     connection arrived on, not the literal string `"0.0.0.0"` -- and logs
     a `logger.warning` once per process the first time that address isn't
     loopback (`127.0.0.1`/`::1`/`localhost`, new `_is_loopback_host`
     helper), cached on `app.state._cc_exposure_warned` the same way
     `_configured` caches its own answer.
  2. **Radicale devpass fail-startup** (`src/config.py` +
     `src/main.py`). The finding's literal phrasing ("fail startup in
     production mode if creds are still at the dev default") would have
     broken every existing standalone production deploy that doesn't run
     Radicale at all -- the common case, since `scripts/curodav-ctl`'s env
     template ships `CC_RADICALE_*` commented out, which means the
     devuser/devpass fallback is what a perfectly correctly-configured
     no-Radicale production install already runs with today, silently and
     harmlessly (there's nothing real behind that URL, so the credentials
     never actually authenticate anywhere). An unconditional check would
     have failed all of those too -- directly contradicting this doc's own
     "no behavior change for a correctly-configured deploy" framing. Landed
     gated on the bridge actually connecting: `main.py`'s lifespan (the
     existing Radicale-optional `try`/`except`, which must never raise for
     an unreachable server) gained an `else` branch that runs only after
     `CalDavBridge(settings)` succeeds -- if `deploy_mode == "production"`
     and the now-live connection is still authenticated with the exact
     devuser/devpass pair (new `config.uses_default_radicale_credentials`,
     checked against the *effective* settings, i.e. after
     `apply_persisted_radicale_overrides`, so a /setup-entered password
     that happens to literally be "devpass" is still caught), it raises
     `RuntimeError` -- deliberately allowed to propagate and fail the whole
     lifespan startup, unlike the broad `except Exception` right above it.
     A standalone/no-Radicale production deploy (bridge stays `None`) never
     reaches this branch at all, so it boots exactly as before.

  New tests: `test_auth.py::TestIsLoopbackHost` (6 cases),
  `TestAuthMiddlewareExposureWarning` (4 cases -- loopback silent,
  non-loopback warns once via `caplog`, auth-enabled silent, forced-/setup
  production silent), `TestUsesDefaultRadicaleCredentials` (4 cases). The
  `main.py` lifespan wiring itself has no test harness in this suite (no
  `test_main.py` exists) -- verified instead with two ad hoc scripts (not
  added to the suite, same convention this file has used before for
  lifespan-adjacent checks): one confirms the `RuntimeError` actually fires
  end-to-end with a stubbed always-connects `CalDavBridge`, the other
  confirms an unreachable-Radicale stub still boots clean. Pure Python
  change (`auth.py`, `config.py`, `main.py`), no template/CSS/JS touched --
  no `sw.js` bump needed. Full suite: 1970 passed, run as 12 parallel
  chunks within one call (this sandbox doesn't persist `/tmp` or
  background processes *between* bash calls this session, unlike some
  prior sessions -- chunking + backgrounding + `wait` all had to happen
  inside one call), `test_caldav_bridge_live.py` excluded as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): #3, the `_attach_tags`/
  `_attach_contact_phones_emails` N+1 query fix -- flagged as the
  highest-impact single fix in the whole audit.

- **Shipped:** 2026-09-07 -- a Cowork full-app audit (code quality, security,
  UX/accessibility/mobile, performance, UI consistency) ran this same day;
  findings are in `documentation/reports/full-app-audit-2026-09-07.md`, and
  the fix order before 2.0 is `documentation/plans/audit-fixes-2.0.md`
  (linked from `roadmap.md`'s 2.0 section). This entry is **slice 1 of
  that list**: session revocation.

  **Bug (well, gap) fixed:** sessions were stateless 30-day signed cookies
  with no revocation path at all -- changing the login password (Settings
  > General or first-run /setup) didn't invalidate any cookie already
  issued under the old password, so a stolen cookie (or the just-replaced
  password's own session) stayed valid for up to 30 more days regardless.
  Fixed by reusing the exact mechanism `routers/settings.py::purge_all`
  already had for this (drop the auto-generated session-signing secret,
  which lives in `app_meta`, so every cookie's HMAC stops verifying) and
  generalizing it to a second trigger: new `auth.rotate_session_secret`
  is now called from both `routers/auth.py::setup_submit` and
  `routers/settings.py::change_login_password`, right where each already
  mints its own fresh cookie for the current browser -- so the account
  owner's own session survives (re-signed under the new secret) while
  every other outstanding session, and a stolen cookie, immediately stops
  working. A no-op when `CC_AUTH_SECRET` is set (operator-fixed, not in
  `app_meta` -- see the function's own docstring for the equivalent
  operator action there). Both call sites also update
  `app.state._cc_auth_secret` in the same request (the in-process cache
  `AuthMiddleware` reads), matching what `purge_all` already had to do --
  without it, the very redirect the password-change response issues would
  have looked unauthenticated to itself.

  New tests: `test_auth.py::TestRotateSessionSecret` (4 cases: persists a
  new secret, an old token stops verifying against the rotated one, no-op
  when `CC_AUTH_SECRET` is fixed, repeated calls produce different
  secrets) plus `TestSetupSubmit::test_persists_a_session_secret_and_
  caches_it_on_app_state`; `test_settings_login_password.py` gained
  `test_rotates_session_secret_so_old_sessions_are_revoked` (end-to-end:
  a pre-change token fails against the post-change secret, the response's
  own new cookie succeeds, `app.state` agrees) and `test_env_fixed_secret_
  is_not_rotated`. Pure Python change (auth.py + the two router files),
  no template/CSS/JS touched -- no `sw.js` bump needed. Full suite: 1955
  passed, run as 12 chunks of ~7 files each (this sandbox's own
  background-process-per-bash-call limitation meant even smaller per-call
  chunks than usual were needed this session -- some individual test
  files, e.g. `test_offline_sync.py`, take ~20s alone here, apparently
  slow disk I/O in this particular sandbox rather than anything about the
  test itself), `test_caldav_bridge_live.py` excluded as always.

  **Next slice** (per `audit-fixes-2.0.md`'s order): #2, the two
  silent-misconfiguration guards (unauthenticated local mode exposed
  publicly; the dev Radicale password fallback in production).

- **Shipped:** Direct follow-up, same day (2026-09-04), immediately after
  the mobile-nav redesign below -- "also implement and fix the other
  problems described in this conversation," the two touch-target gaps the
  earlier Cowork audit flagged but deliberately left unfixed (audit-only
  was the scope at the time):
  1. **`.task-row-delete` (Tasks/Habits table row delete button) had no
     touch fallback.** It's hover-reveal-only (`tr:hover`/
     `tr:focus-within`, opacity not display, so it stays a real focusable
     target) -- fine for keyboard/mouse, but a touch device has no
     reliable `:hover` state and there was no way to reach `:focus-within`
     either (tapping the row's title link navigates away instead of just
     focusing it), so the button was tappable but practically invisible on
     a phone. Added `@media (hover:none){ .task-row-delete{opacity:.55;} }`
     -- feature-detects the input mechanism rather than screen width (also
     covers a touch-primary tablet at a wide viewport), dimmed rather than
     full-opacity so it still reads as secondary the way hover-reveal
     signals on desktop.
  2. **`.icon-btn` (modal close, calendar nav arrows, etc.) was 28px,
     under the ~44px touch-target guideline** (Apple HIG / Material
     Design) -- fine for a mouse, tight for a finger. Added
     `@media (pointer:coarse){ .icon-btn{width:40px; height:40px;} }` --
     real box growth (not a padding-only/pseudo-element hit-area trick),
     scoped to the base rule only; more specific overrides further down
     (`.cropper-rotate-group .icon-btn`'s 32px compact toolbar, etc.) are
     untouched, each would need its own layout check before growing.
  `sw.js` CACHE_NAME bumped v53 -> v54 (style.css changed), `test_pwa_
  shell.py`'s pin updated. Neither class is referenced by any existing
  test (grepped `tests/` first). Full suite: 1948 passed across 5
  foreground chunks (same count as the mobile-nav slice right below --
  no tests added this round, just two CSS fixes),
  `test_caldav_bridge_live.py` excluded as always.

- **Shipped:** Direct request, 2026-09-04 -- mobile navigation redesign,
  reached via a Cowork mobile-touch/nav audit (no code changes -- Pointer
  Events/`touch-action:none` already covered every drag interaction, only
  gap found was `.task-row-delete`'s hover-only reveal, not fixed here)
  followed by a real install screenshot: the old `@media (max-width:720px)`
  treatment packed all ~8 rail destinations (Home/Calendar/Planner/Tasks/
  Contacts/Search/Settings/+New) into one crushed 64px row, exactly what
  the screenshot showed. Pushed back once on the user's own 3-item
  proposal (Calendar/Tasks dropping to two-tap access) before building --
  they confirmed the minimal version anyway, so this isn't a compromise,
  it's what was asked for after the tradeoff was surfaced.
  1. **New persistent `.mobile-tabbar`** (`templates/base.html`) -- exactly
     3 buttons fixed to the bottom edge: a Sidebar toggle
     (`#mobile-nav-toggle`), Home, Search. Desktop-hidden entirely (style.
     css scopes it to `max-width:720px`); `.tabbar` (the rail) renders
     normally above that width and this bar never displays.
  2. **`.tabbar` itself becomes a bottom-sheet drawer below 720px** --
     same rail markup desktop uses, not a trimmed copy (explicit decision:
     "mirrors the desktop expanded sidebar's content, not a subset"), so
     Spaces/Projects/tree-toggles -- hidden outright in the old mobile
     block -- are un-hidden and given the same row layout
     `html[data-sidebar-expanded]` uses on desktop (duplicated into the
     mobile media query since that ruleset itself is guarded to
     `@media (min-width:721px)` and never fires at phone widths). Hidden
     below the viewport by default (`transform:translateY(110%)`), toggled
     via `html[data-mobile-nav-open]` (new `static/mobile_nav_drawer.js`).
     Rows are 44px min-height (not desktop-expanded's 36px) for a real
     touch-target floor. `#mobile-nav-handle` gives it the same drag-to-
     dismiss grab handle `#modal-handle` (static/modal.js) already uses,
     same Pointer Events pattern, same ~90px dismiss threshold -- one
     visual/interaction convention for both bottom sheets in the app, not
     two. `#mobile-nav-scrim` darkens behind it, tap to close, stopping
     short of `.mobile-tabbar` (`bottom:64px`, not 0) so Home/Search/the
     toggle stay reachable while the drawer is open.
  3. Caught and fixed before commit: the "hide these three elements above
     the mobile breakpoint" default rule was accidentally placed *after*
     the `@media (max-width:720px)` block in style.css -- since both share
     equal specificity, source order (not media-query nesting) decides the
     winner when both apply, so it was clobbering the mobile-only
     `display:` overrides at every width including mobile ones. Moved
     before the block instead.
  `sw.js` CACHE_NAME bumped v52 -> v53 (new `static/mobile_nav_drawer.js`
  added to SHELL_ASSETS -- same "base.html script needed on every page"
  category as `sidebar_tree.js` -- plus style.css/base.html changed),
  `test_pwa_shell.py`'s pin updated. No existing test asserts the old
  mobile markup/CSS shape (this suite has no JS/CSS rendering harness, per
  this file's own recurring note) -- `test_sidebar_tree.py`/
  `test_nav_and_deactivation.py` (assert `.tabbar`'s inner markup, which
  is unchanged -- only wrapped differently at mobile widths) re-run clean.
  Full suite: 1948 passed across 5 foreground chunks (this sandbox's
  background-process-per-bash-call limitation, `test_caldav_bridge_live.py`
  excluded as always).

  **Not done, flagged not fixed:** an unrelated, large *pre-existing*
  staged-but-uncommitted change was found sitting in this repo's index at
  session start (`git status --short` before any edit here) -- a docs
  reorg (`plans/`/`features/`/root guide `.md` files moved under
  `documentation/`), deploy script removal, new `.github/workflows/`.
  Not this session's work, not touched or folded into this commit --
  committed only this slice's own files (`git commit -- <paths>`, a
  partial commit that leaves the rest of the index staged and alone).
  Whoever owns that restructuring still needs to commit or discard it
  separately.

- **Bug fix:** Direct report, 2026-09-04 -- "two events overlap in the week
  view, I move one via mouse but they still show half width... they should
  go to normal width when the event is moved and there is no overlap."
  Root cause: overlap layout (`left_pct`/`width_pct` lane widths) is
  computed entirely server-side by `grid_layout.layout_day` and baked into
  the rendered HTML once; `static/calendar.js`'s `.time-event` drag/resize
  handler (`setupEvent`'s `end()`) only ever moved `top`/`height` live and,
  on a successful save, patched just the `.te-time` label text -- it never
  triggered a re-layout of the column, so both the dragged event and
  whatever it used to overlap with stayed at their pre-drag width until an
  actual page load. Every *other* calendar drag path already goes through
  the app's async-CRUD convention (`window.ccApi.dispatchChange` ->
  `cc-entity-changed` -> `async_calendar.js`'s region refresh, which
  re-runs `layout_day`): month/day-cell drag (`calendar_month_drag.js`),
  all-day-row drag (`calendar_week_allday_drag.js`), work-allocation drag
  (`project_calendar.js`), modal edits (`modal.js`) -- `calendar.js`'s own
  handler was the one holdout patching DOM by hand instead. Fixed by
  making it follow the same convention: `end()`'s success handler now
  calls `dispatchChange({type:"event", action:"move", uid})` instead of
  patching `.te-time` (that patch, and the now-dead `minutesToDisplayTime`
  12h/24h helper it alone used, are removed -- the region refresh
  re-renders the label server-side instead).

  Patched a second hole found while fixing the first: Day view
  (`calendar_day.html`) had no async-CRUD region at all -- unlike Week's
  `#week-grid`, there was nothing for `dispatchChange` to refresh, so a
  Day-view drag would have kept going stale even after the `calendar.js`
  fix. Added the same region Week/Month/4-Week already have: split Day's
  grid markup into `_calendar_day_grid.html` (`id="day-grid"`), added a
  `_day_view_context` helper (`routers/calendar.py`, mirroring
  `_week_view_context`/`_four_week_view_context`) shared by the full page
  and a new `region == "day"` branch on `GET /calendar/regions`, and gave
  `async_calendar.js` a `refreshDay`/`dayEl` branch (re-binds via the same
  `CCWeekGrid.init()` Week uses -- Day never loads
  project_calendar.js/CCWeekAllDayDrag/CCUnscheduledPanel, so only that
  one re-bind applies). `calendar_day.html` now also loads
  `async_calendar.js`.

  Pure JS/Python/template change -- `calendar.js`/`async_calendar.js`
  aren't in `sw.js`'s `SHELL_ASSETS` precache list (page-specific scripts,
  not part of the global app shell), so no `sw.js` CACHE_NAME bump needed.
  Full suite: 1953 (1 pre-existing, unrelated failure --
  `test_dashboard_router.py::TestAgendaWidgetAllUpcoming::
  test_todays_earlier_events_still_count_as_upcoming` is UTC-now-vs-local-
  date sensitive and tripped over the calendar rolling from 09-03 to
  09-04 mid-session; not touched by this change, pre-existing per its own
  2026-09-03 changelog entry above).

- **Bug fix:** Direct report, same day (2026-09-03) -- "the data is not put
  in the today widget or the upcoming correctly." Real, reproduced bug in
  `routers/dashboard.py::_render_agenda`'s `next_30_days`/`all_upcoming`
  branch: it compared an event's full `start_at` timestamp against
  `datetime.now().isoformat()` (wall-clock precision), so any event whose
  clock time on *today's own date* was earlier than the moment the page
  rendered (midnight, or any earlier hour) got silently dropped from
  "Upcoming" -- exactly the screenshot's symptom, three real events on
  today's date, all missing, jumping straight to +3/+7-day events instead.
  Fixed to a pure date-level comparison (`start_at[:10] >= today_iso`),
  matching the convention every other boundary in this same function
  already uses (the Tasks branch two lines up, the `range == "today"`
  branch's own `[:10] == today_iso`) and matching routers/calendar.py's
  month/week/day views, which only ever reason in whole days. New
  regression test (`test_dashboard_router.py::TestAgendaWidgetAllUpcoming
  ::test_todays_earlier_events_still_count_as_upcoming`) seeds an event
  earlier today, one an hour from now, and one yesterday -- only yesterday
  should drop. Pure Python fix, no template/CSS/JS touched -- no `sw.js`
  bump needed. Full suite: 1953 passed.

  Separate follow-up, same day, immediately after: confirmed via
  AskUserQuestion that the "Today" pane's "Nothing to show" was exactly
  the flagged design gap above (the user had already hand-fixed their own
  copy of the widget) -- direct request to change the *default* for
  future first-time seeds: "modify the default to not be overdue only,
  but be overdue, tasks and events." `_DEFAULT_STACK_MEMBER_TYPES`'s third
  member's `show` widened from `["overdue"]` to `["overdue", "tasks",
  "events"]` -- every Show section `range="today"` actually supports, so
  a fresh "Today" pane shows what its name implies. Scoped to the one-time
  seed only (`_ensure_default_widgets`/`_ensure_default_label_widgets`'s
  own app_meta flag) -- doesn't touch anyone who already has widgets,
  seeded or hand-built. 5 assertions across `test_dashboard_router.py`
  and `test_dashboard_usability_rework.py` updated for the new default
  Show list. Pure Python change, no `sw.js` bump needed. Full suite:
  1953 passed.

- **Shipped:** Direct follow-up, same day (2026-09-03), immediately on top
  of the header-clipping-fix + Work-sessions-header-merge entry right
  below ("the two lines in the middle of this modal"): the merge fixed the
  divider *between* "Work sessions" and "Scheduled work" (by deleting the
  second heading entirely), but `.detail-plain-section`'s own border-top
  was still redundant with whatever came right before it -- `.detail-meta-
  panel`'s own border-bottom (active whenever it's not `:last-child`,
  which is exactly when Work sessions follows it) or the habit heatmap's
  real `.detail-card` box edge/shadow. Two hairlines a `margin-top` gap
  apart where one already existed. Fix: `.detail-plain-section`'s
  border-top removed outright, `margin-top` alone provides the spacing --
  confirmed by rendering the real template output directly (a short ad
  hoc script, not a screenshot guess) before and after. `sw.js`
  CACHE_NAME bumped v51 -> v52, `test_pwa_shell.py`'s pin updated. Full
  suite: 1952 passed.

- **Shipped:** Direct follow-up, same day (2026-09-03), immediately on top
  of the badge-clipping-fix + Work-sessions-rework entry right below:
  1. **Real regression fix** ("edit the header so that it doesn't clip
     (margins)"), caught from a screenshot of the *edit* event modal, not
     a detail-view modal -- the v48 `.modal-header` rewrite (`padding:0`,
     so the cover banner could bleed edge-to-edge) had stripped the
     *only* margin every plain `*_form.html` edit modal's bare `<h1>`
     relied on (event/task/contact/habit/label/note/... -- 20+ templates,
     confirmed by grepping every `.modal-header` consumer, not assumed).
     `.modal-header`'s original padding + row layout is restored exactly;
     the cover-bleed behavior moved to a new `.detail-header-inner`
     wrapper (negative margins sized to match that padding exactly, both
     the desktop and mobile-breakpoint values) used only by the 4
     detail-view templates, which now wrap their `detail_cover(...)` +
     `.detail-heading-row` pair in it instead of putting them directly in
     `.modal-header`.
  2. **Work sessions header merge** (direct follow-up: "merge the Work
     sessions and the Scheduled work 1.0h / 1.0h, because it's
     redundant... don't have two dividers between the two - none is
     enough") -- the separate "Scheduled work" sub-heading
     (`.relations-group`/`.relations-group-head`, a leftover from when
     this card could hold more than one labeled group) is gone; its hours
     readout is now a second `.checklist-progress` pill on the "Work
     sessions" heading itself. This also fixed an unintended second
     divider: `.relations-group`'s own `border-top` was firing because it
     was the *second* child of the macro's output (after the `<h2>`), so
     its `:first-child` CSS exemption never actually matched -- on top of
     `.detail-plain-section`'s own top border from the earlier entry
     below, that read as two hairlines where one now suffices.
     `.relations-group`/`.relations-group-head` CSS removed as fully dead
     (its only other two consumers were already the same unreferenced
     `_task_relations.html`/`_event_relations.html` files noted in the
     `.detail-identity-dot` cleanup below).
  `sw.js` CACHE_NAME bumped v50 -> v51 (checked `git log` first, no
  concurrent commits since this session's own v50), `test_pwa_shell.py`'s
  pin updated. Full suite: 1952 passed (four parallel chunks by file).

- **Shipped:** Direct follow-up, same day (2026-09-03), two small fixes on
  top of the cover-banner baseline shipped earlier the same day:
  1. **Bug fix** ("the icon is cut by the body, not sitting on top") --
     `.detail-cover-icon` (the floating badge) used to be a child of
     `.detail-cover`, which needs `overflow:hidden` to clip the image/
     gradient fill to the cover's rounded top corners; that same
     `overflow:hidden` was clipping the badge's own bottom overhang, its
     entire reason for existing. Fixed by introducing `.detail-cover-wrap`
     (a plain, non-clipping positioning context) as the actual parent of
     both `.detail-cover` and `.detail-cover-icon`, siblings now instead
     of parent/child -- `_detail_cover.html` + style.css both changed, no
     other template changes needed (all four detail modals go through the
     one shared macro).
  2. **Work sessions rework** (direct request: "could we also rework the
     work sessions" -> clarified via AskUserQuestion -> "visual polish
     without having the background color card div"): task_detail.html's
     and habit_task_detail.html's Work sessions section dropped the
     elevated `.detail-card` wrapper for the new `.detail-plain-section`
     (a top hairline instead of a tonal box -- same "no background card"
     treatment the meta grid got in the very first 2026-09-03 session
     today) plus a `.work-session-row` modifier per row (a little more
     vertical padding than the default `.checklist-row` density, a small
     clock icon ahead of "Session N") -- purely visual, no new fields or
     endpoints. The habit heatmap card right above it on the habit-task
     page keeps its real `.detail-card` treatment, unaffected -- scoped
     to Work sessions specifically, matching how the meta-grid change was
     scoped narrowly too.
  `sw.js` CACHE_NAME bumped v49 -> v50 (picking up from another session's
  concurrent v48->v49 datetime-picker bump the same day -- this repo saw
  parallel sessions today, checked via `git log` before bumping rather than
  assuming the last value this session itself had written), `test_pwa_
  shell.py`'s pin updated. `test_detail_modals_rework.py`'s task-page
  card-count test rewritten (Work sessions was the last real `.detail-card`
  on that page; now there are zero). Full suite: 1952 passed (four
  parallel chunks by file, same convention as every other multi-file
  session this file documents).

- **Shipped:** Direct request, same day (2026-09-03) -- reworked the shared
  date+time range picker's hour selection (`_datetime_picker.html`'s
  `datetime_picker` macro / `static/datetime_picker.js`), used by the event
  create/edit modal (`_event_form_fields.html`'s Start & end field) among
  other callers. Reached via several mockup rounds (static HTML, shared as
  files, not built against real data) rather than a single guess: a first
  pass of grid/slider/preset alternatives to the old scrolling 24-row hour
  list was all rejected as "counterintuitive" (the slider drags/rounds
  imprecisely, the grids/presets don't reach every hour); a follow-up typed
  HH:MM text-field pass was rejected too, as "too much input needed"; a
  compact single-column mockup (full calendar + two small Start/End chips
  under it, no second column) landed on its "closed" state but not its
  click-to-open-a-dropdown interaction; the final round dropped the dropdown
  in favor of segmented in-place editing and was approved outright ("yes.
  this one. implement").
  1. **Range mode's panel is a single column now** (`.dtp-panel--range`,
     style.css, flex column instead of a 2-col grid) -- month calendar, then
     one `.dtp-hour-row` of two `.dtp-hour-chip`s (Start/End) underneath,
     same width as date mode's own panel. The old scrolling/click-drag
     24-row `.dtp-hour` list is gone entirely (datetime_picker.js's
     `renderHours`/`paintHours`/`pickHour`/`attachHourDrag` removed).
  2. **Each chip is a native-time-input-style segmented field** -- hour and
     minute (plus AM/PM, 12h setting only) segments, exactly one highlighted
     ("active") at a time while that chip has real focus. Arrow Up/Down nudge
     the active segment (wrapping 23→00/59→00); Arrow Left/Right move which
     segment is active; typing digits sets a value directly and
     auto-advances hour→minute after two digits (`typeDigit`); Backspace
     clears the active segment. Minutes are a real independently-tracked
     `state.startMinute`/`endMinute` now, not derived via the old
     "keep-the-original-minute-unless-hour-changes" trick the whole-hour
     click grid needed.
  3. **No Apply button anywhere (range or time mode).** Every edit -- a day
     click, a segment nudge, a typed digit -- commits straight to the hidden
     inputs immediately (`commitLive`), the same auto-commit contract `date`
     mode already had; the panel just stays open afterward since one edit is
     rarely the last one. Time mode (hours-only, no calendar -- the weekly
     Sleep/Leisure block picker) reuses the exact same chip row, gaining a
     minimal one-row header (`renderTimeHeader`) just to hold Clear.
  4. **Clear moved into the header, icon-only,** for range mode too now
     (previously only date mode had this; range/time had a text Clear in a
     footer that no longer exists) -- reuses the existing `.dtp-clear-nav`
     treatment next to the month-nav arrows, still hidden whenever `submit`
     is set.
  5. **Submit-mode callers** (event_detail.html's "Move this occurrence",
     `_task_work_allocations.html`'s per-session set-times, both
     `data-dtp-submit="1"`) lost their Apply-triggered `requestSubmit()` and
     gained a close-triggered one instead: a new `state.dirty` flag (reset
     on open, set on any real edit) means the enclosing form submits only if
     the panel is closed *after* an actual edit landed a complete value --
     opening a submit-mode picker just to look, then clicking away, no
     longer silently re-POSTs unchanged values.
  `sw.js` CACHE_NAME bumped v48 → v49 (style.css + datetime_picker.js
  changed), `test_pwa_shell.py`'s pin updated. No other tests touch this
  component's JS-rendered markup (grepped `dtp-hour`/`dtp-panel`/
  `dtp-trigger`/etc. across `tests/` first -- none), so no other test
  changes were needed. Full suite: 1952 passed (four chunks by file, same
  convention as every other multi-file session this file documents).

- **Shipped:** Direct request, same day (2026-09-03) -- "all dates should be
  displayed more minimally, with a single script that resolves all dates
  from the standard complicated format to a more human readable format.
  EVERYWHERE." Audited every template for raw ISO date/datetime display
  text (`grep` across `src/templates` for `_at`/`date_from`/`date_to`/
  `created_at`/`checked_at` references, excluding form-input `value=`
  attributes and JS `data-*` attributes, which must stay raw ISO for
  `datetime_picker.js`/drag-calc to keep working) rather than adding a new
  formatter: the app already had a "single script" for this --
  `deps.py`'s `relative_date` Jinja filter (short dates: "Today"/
  "Tomorrow"/"Yesterday"/"5 Sep"/"5 Sep 2027") and `fmt_dt` filter (full
  timestamps: "Aug 25, 2026, 8:57 PM") -- it just wasn't applied
  everywhere yet. Six templates had raw `value[:10]`/bare-field date text
  that skipped both filters; switched each to whichever of the two
  already-established filters matches the field (short date vs.
  full timestamp), no new code: `task_detail.html` (due/start),
  `event_detail.html` (start/end, occurrence-card date, "Moved to" date --
  the datetime_picker's own prefill value at line 150 left untouched, it
  needs raw ISO), `project_detail.html` (deadline/event leading date,
  Kanban card due-date tag), `settings_holidays.html` (date_from/date_to
  range), `settings_data_maintenance.html` (sync-conflict `created_at`,
  integrity `checked_at`, both `fmt_dt` to match the pre-existing
  `latest_backup.created_at | fmt_dt` on the same page). Confirmed via
  grep that calendar grid templates' `start_at`/`end_at` uses are all
  `data-start`/`data-end` JS attributes or already-filtered `fmt_time`
  calls, not raw display text -- left alone. `test_settings_holidays.py`'s
  `test_lists_existing_holidays_as_rows_with_edit_buttons` updated
  ("2026-12-20"/"2027-01-05" -> "20 Dec"/"5 Jan 2027", the new
  `relative_date` output for today = 2026-09-03). Full suite: 1952 passed
  (four parallel chunks by file). No new filter, no `sw.js` cache bump
  (server-rendered text, not a static asset).

- **Shipped:** Direct request, same day (2026-09-03), on top of the two
  view/edit-modal design follow-ups right below: after a mockup pass (4
  static HTML variants, shared as a file, not built against real data)
  exploring ways to "spice up" the bland restyled view modal, the user
  picked one outright -- "I like variant B so much I want it to be the
  baseline for all view modal windows. Implement." -- a Notion-style cover
  banner replacing the plain `.detail-identity-dot + title` header row
  across all four detail modals (event/task/contact/habit-task).
  1. **New shared `_detail_cover.html` macro** (`detail_cover(accent,
     banner, badge_html, avatar_mode=false)`), imported by all four
     detail templates. Renders a `.detail-cover` strip: a real resolved
     banner image (`.detail-cover-img`) when one exists, else a flat
     accent-color gradient fill (`.detail-cover-fill`, CSS custom prop
     `--cover-accent`) -- with a floating `.detail-cover-icon` badge
     (a small white icon card, or `.detail-cover-icon-avatar` for
     contacts, a ringed avatar with no card chrome) overlapping its
     bottom edge. Which of the two wins was a real design collision, not
     a guess -- resolved via AskUserQuestion before touching any code
     (real image wins, color is the fallback, one cover slot instead of
     stacking a color header above the pre-existing task image banner).
  2. **`db.banner_for_task` generalized to `db.banner_for_object(conn,
     object_type, obj)`** (same label > Project > Space priority chain,
     now keyed on any `object_labels` type) -- `banner_for_task` kept as
     a thin name-preserving wrapper so its own tests and both pre-existing
     call sites (task_detail, project_detail's Kanban cards) didn't need
     to change. Wired up fresh for events (`routers/calendar.py`'s
     `event_detail` -- STATE.md had flagged this exact gap, "generalizes,
     just not wired to event_detail.html yet") and contacts
     (`routers/contacts.py`'s `contact_detail`); habit-task detail reuses
     task_detail's route so it got `banner`/`status_colors` for free.
  3. **New `deps.py` global `stable_color(seed)`** -- contacts have no
     color field the way events (calendar_color) and tasks (status) do,
     so a contact's cover-fill color is deterministically derived from
     its own `uid` (md5 -> one of the same 16 `.cal-*` names
     routers/labels.py's `COLORS` uses, duplicated locally rather than
     imported to avoid a circular import with routers/labels.py).
  4. **task_detail.html's old standalone `.detail-modal-banner` body
     strip is retired** -- that resolved image now renders inside the
     new cover instead of a second, separate strip below the header.
     `.detail-identity-dot` CSS is removed too (its only other consumers,
     `_task_relations.html`/`_event_relations.html`, were already dead/
     unreferenced templates per routers/tasks.py's and routers/
     calendar.py's own "now unreferenced" comments -- confirmed via grep
     before removing, not assumed).
  `.modal-header` restructured from a single flex row to a column (cover
  above a new `.detail-heading-row` for the title) -- a global rule
  change, safe because static/modal.js's `injectModalContent` copies this
  div's *children* into the dialog's persistent `#modal-header` (which
  carries the same class/CSS), never the div's own class list, so no
  modifier class on `.modal-header` itself would have survived the
  modal-JS path; every state that differs (image vs. gradient) lives on a
  child element's class instead. Mobile breakpoint updated to match
  (shorter, unrounded cover under the bottom-sheet's drag handle).
  `sw.js` CACHE_NAME bumped v47 -> v48, `test_pwa_shell.py`'s pin updated.
  `test_detail_modals_rework.py`'s `TestIdentityMark` rewritten for the
  new markup (3 tests); `test_banners.py`'s task-detail banner tests
  updated for the new `.detail-cover-img`/`.detail-cover-fill` classes/
  location, plus 2 new tests covering the event/contact wiring. Full
  suite: 1952 passed (four parallel chunks by file, same convention as
  every other multi-file session this file documents).

- **Shipped:** Direct follow-up, same day (2026-09-03), on top of the
  Format-toggle rework right below: "make the input boxes more dense: half
  width modal windows (especially valuable for the reminders, recurrence,
  holiday calendar). The format settings should be right at the end of the
  modal, not before the reminders." Both purely a `_event_form_fields.html`
  reorder/class change, no CSS/JS touched -- the 2-column `.field-grid`
  and the `.field` (half) vs. `.field field-wide` (full row) split already
  existed (Holiday calendar was already `ms_wide=false`/half; Labels was
  already a plain half-width `.field` too):
  1. **Reminders and Recurrence dropped `field-wide`.** Each used to claim
     a full row for one short input; now plain `.field`s, so they land
     side by side in the grid the same way Holiday calendar already did.
  2. **Format (+ its Location/Meeting URL fields) moved from right after
     All day/before Labels down to the very end of the field grid, after
     Holiday calendar.** Pure reorder -- the `_has_location`/`_has_meeting`
     Jinja sets and the field's show/hide CSS (`#event-form:has(...)`,
     style.css, untouched) don't care where in the DOM the field sits.
  New field order: Title, Description, Start & end, All day, Labels,
  Reminders + Recurrence (side by side), Holiday calendar (+ Exclude Sat/
  Sun, hidden until recurring), Format (+ Location or Meeting URL,
  whichever the Format pick reveals) last. Verified with an ad hoc
  TestClient-free script (new_event_form's rendered body, not added to the
  suite -- no existing test asserts field order, confirmed by grep before
  starting) that `reminders` < `recurrence` < `holiday_calendar` <
  `event_format_in_person` by string offset, and that neither Reminders'
  nor Recurrence's own `.field` div carries `field-wide` anymore. `sw.js`
  CACHE_NAME bumped v46 -> v47 (template-only change), `test_pwa_shell.
  py`'s pin updated. Full suite: 1945 passed (four parallel chunks, same
  as the entry below), unaffected since no test asserted the old order or
  width.

- **Shipped:** Direct request, same day (2026-09-03), two view/edit-modal
  design follow-ups the user flagged as still outstanding from the
  2026-09-02 detail-modal design pass ("we have not restyled the view
  modal to not use the colored bg card div... also we have not fixed the
  CSS for some edit modal... I would prefer to move away from how the
  Format toggle looks — too cramped between icons and text, the gray, out
  of place, no clear subordination, no clear 'not one of these' state").
  Confirmed direction via AskUserQuestion (3 questions) before touching
  code:
  1. **View modals: the meta grid's wrapper is no longer an elevated
     tonal `.detail-card` with a colored left accent.** New `style.css`
     class `.detail-meta-panel` (no background/border/shadow/hover-lift,
     just a bottom hairline separating it from whatever follows) replaces
     `.detail-card` on the *meta grid specifically* in all four detail
     modals — `event_detail.html`, `task_detail.html`,
     `contact_detail.html`, `habit_task_detail.html` — including dropping
     the now-unused `style="--detail-accent: ..."` inline attribute from
     the two that had one (event/task). Scoped deliberately narrow: a
     *second*, later `.detail-card` in event/task/habit-task (the
     occurrence card, Work sessions card, habit heatmap) keeps the real
     card treatment untouched — the feedback was about the meta display
     specifically, not every card in a detail modal. Calendar-color signal
     for events still survives via the header's `.detail-identity-dot`
     and the Start value's own `.color-dot`, so nothing about "which
     color is this" was lost, just the big tinted box.
  2. **Edit modal's Format toggle (In person / Online) rebuilt on the
     existing tile/card picker pattern** (`.tile-select`/`.tile-option`,
     already used by the widget builder's Data source field) instead of
     the cramped `.segmented`/`.seg-btn` pill row — `_event_form_fields.
     html`, three equal cards now, icon above label, obvious selected
     look (border + tint) vs. a plain neutral outline unselected. Added a
     third, explicit **None** option (`id="event_format_none"`, value
     `none`) — "neither Location nor Meeting URL set" used to be an
     implicit state (both radios simply unchecked, including on every
     brand-new event); it's now a real, visibly-selected third choice,
     checked whenever `_has_location`/`_has_meeting` are both false. Kept
     the original `event_format_in_person`/`event_format_online` ids and
     the `event-format-segmented` wrapper class in place (just added
     `tile-select` alongside) specifically so existing tests and
     `event_format_toggle.js`'s own selector didn't need touching beyond
     the one real behavior change: picking None now clears *both*
     Location and Meeting URL (previously the clear-the-other-field logic
     only ever knew about one "other" field, since None wasn't a value it
     handled).
  `sw.js` CACHE_NAME bumped v45 → v46 (style.css + templates + JS
  changed), `test_pwa_shell.py`'s pin updated. `test_detail_modals_rework.
  py` updated for the `.detail-card` → `.detail-meta-panel` rename (3
  tests asserting the literal wrapper class, 1 asserting `--detail-accent`
  presence — replaced with an assertion on the still-present
  `.color-dot`/`.detail-identity-dot`, 1 card-count test dropped from 2 to
  1 now that only the Work sessions card is a real `.detail-card` on the
  task page); `test_event_format_field.py` gained a new
  `TestFormatFieldNoneOption` class (4 tests: new-event/edit-with-neither
  check None, edit-with-location/edit-with-meeting don't). Full suite:
  1945 passed (four parallel chunks by file, same convention as every
  other multi-file session this file documents).

- **Shipped:** Direct follow-up, same day (2026-09-03), calendar drag-and-drop
  consistency + a new capability, three bundled changes from one
  conversation ("in the planner and calendar pages... there should be drag
  and drop support" -> turned out Week/4-Week/Month already had it wired,
  the actual gaps were narrower):
  1. **CSS bug: the Month/4-Week dragging chip looked like it was
     disappearing, not being picked up.** `.month-event-item.dragging,
     .month-due-task-item.dragging` was `opacity:.5; cursor:grabbing` only
     -- no shadow/outline/z-index, unlike Week's `.time-event.dragging`
     (ring outline + elevated shadow + z-index:30 + opacity:.95). Direct
     feedback: "the css is wrong... the events are not shown as dragged."
     Now both share the same ring-outline/shadow/opacity-.95 treatment
     (Month/4-Week uses z-index:5, not Week's 30 -- no tall shared
     absolutely-positioned canvas there to clear).
  2. **New: drag-and-drop for the Week view's all-day row.**
     `_calendar_week_grid.html`'s `.allday-task` items (events and
     due-date tasks) had zero drag wiring before this -- not broken, never
     built; `calendar.js` only ever binds `.time-event:not(.work-
     allocation)`, which this row's items never carry. New file
     `static/calendar_week_allday_drag.js`, modeled directly on Month/
     4-Week's own `calendar_month_drag.js`: day-shift only (no time axis,
     no resize -- multi-day span-resize is a separate unbuilt feature), same
     `/events/{uid}/reschedule` and `/tasks/{uid}/update-field` (field
     `due_at`) endpoints, same recurring-event exclusion (no `data-uid`
     rendered for a recurring event, so it stays click-only). Needed
     `data-date` added to `.allday-col` and `data-uid`/`data-start`/
     `data-end`/`data-due` added to the two `.allday-task` link kinds,
     neither of which existed before. Wired into `calendar_week.html`'s
     script block and into `async_calendar.js`'s `refreshWeek()` re-bind
     (`CCWeekAllDayDrag.init()`) so a swapped-in `#week-grid` region after
     any change gets the bindings re-attached, same pattern every other
     region-refresh hook already uses. Day view's own `.allday-task` strip
     (`calendar_day.html`) was deliberately left alone -- out of scope,
     wasn't requested.
  3. **Task due-date chips: fallback icon changed from `square` (read as
     an empty checkbox) to `alert-triangle`.** Direct feedback: "the icon
     next to tasks... should not be a checkbox, but better a warning sign
     (because that is the due date of the task)." The `default('square',
     true)` fallback (used whenever a task's own label has no configured
     icon) was one identical pattern repeated in 5 templates --
     `_calendar_week_grid.html`, `calendar_day.html`,
     `_calendar_month_grid.html`, `_calendar_fourweek_grid.html`,
     `_widget_agenda.html` -- confirmed with the user this should change
     everywhere, not just Week, since it's genuinely the same element/
     meaning in each place.
  Full suite: 1941 passed (four file-list chunks, `test_caldav_bridge_live.py`
  excluded as always -- background/nohup pytest runs don't survive between
  tool calls in this sandbox, so chunks were run as direct foreground calls
  against explicit file-list slices instead).

- **Shipped:** Direct follow-up, same day (2026-09-03), "the font in the
  tasks table is much too small, compare the two tables -- I want a much
  more standardized font." The three density-pass sizes fighting for
  attention in one row (Status chip 11px, compact Date 13px, everything
  else -- Habits' plain-text Cadence/Streak/Check-in, both tables' Labels
  pills -- inheriting whatever the page default happened to be, ~15.5px)
  are now one number: `.task-table tbody td{font-size:var(--text-
  footnote)}` (14px), with the Status chip's and Labels pill's own
  `font-size:11px` overrides dropped entirely (inherit the td's 14px) and
  a new `.task-table .dtp--compact .dtp-trigger{font-size:inherit;}`
  overriding the compact date trigger's normally-global 13px specifically
  inside this table. The Title cell keeps its own explicit larger size
  (`.task-title-cell a`, `var(--text-body)`, from the original density
  pass) -- an element's own directly-matching rule always wins over an
  inherited ancestor value regardless of the ancestor selector's
  specificity, so this one deliberate exception to the new baseline was
  safe to leave alone. Pure CSS, no markup touched -- full suite unaffected
  (1946 passed, same as before this entry).

- **Fixed two real bugs + one more design follow-up**, same day
  (2026-09-03), reported as "the setting is on, no icons show, something's
  rotten... the Tasks table doesn't match Habits (font, corner radius)...
  also I want label colors lighter/pastel, based on the chosen color":
  1. **Bug: an icon picked in the label editor never saved.**
     `label_form_modal.html` (the live "New Label"/"Edit label" modal --
     confirmed via `routers/labels.py::edit_label_modal`, which template
     actually serves the Edit button, since `label_edit_modal.html` looked
     plausible but turned out to be orphaned/unrouted) posts an `icon`
     radio (`_icon_swatch_picker.html`) into `create_label`/`update_label`
     -- neither route declared an `icon: str = Form(...)` param, so
     FastAPI silently dropped the field on every submit, and `db.
     upsert_label_config`'s own partial-update contract ("only touch what
     you're told to") meant an absent key wasn't cleared, just silently
     never changed. Confirmed end-to-end with a `Request` carrying a real
     `.app.state.settings.db_path` (the bare-`Request` harness this suite
     otherwise uses can't exercise `label_icon()`'s DB-backed path at all
     -- see the entry below) that the render side was already correct
     given a label that actually has an icon; the picker's own submit was
     the break. Fixed by declaring `icon` on both routes. New tests in
     `test_phase2_labels.py::TestIconPersistence` (create, update-new,
     update-change, "No icon" radio clears it, doesn't disturb color/
     group saved alongside it).
  2. **Bug (found while verifying #1): a standalone Habit entity's own
     labels never rendered anywhere**, icon or plain. `routers/tasks.py`'s
     `_habit_group_items` hardcoded `"tags": []` on the entity-kind branch
     instead of reading `h.get("tags")` -- `db.list_habits`'s own
     `_habit_row_to_dict` already attaches real labels via `object_labels`,
     the same mechanism every other entity type uses, so the data existed
     and was computed, just discarded one line later. A habit-*labeled
     task* right above it in the same function (`kind: "task"`,
     `t.get("tags")`) never had this bug. New test:
     `test_tasks_habits_view.py::TestHabitsViewRetired::
     test_standalone_habit_entity_carries_its_own_labels`.
  3. **Design: Tasks/Habits row pills now match each other exactly, and
     are pastel.** `_habit_row.html`'s Labels cell had no `.cell-tags`
     wrapper (only `_task_row.html`'s did), so the density pass's radius/
     font-size override (originally `.task-labels-select .cell-tag`) never
     reached it -- Habits kept the app's default 8px/13px pill next to
     Tasks' new fully-rounded 11px one. Added the same `.cell-tags` wrapper
     to `_habit_row.html`, retargeted the CSS rule to `.cell-tags
     .cell-tag` so one selector now covers both. Separately, label pills
     everywhere (`label_pill`'s `.cell-tag.cal-<color>`, not just these two
     rows) now paint with the same light/tinted `--tag-<color>-bg`/`-fg`
     pair `.tag-<color>` pills already used elsewhere in the app (all 16
     colors already had one, light AND dark theme -- nothing new to
     invent) instead of the bold saturated `--cal-bg-*`/`--cal-fg-*` pair
     built for the calendar's own filled surfaces. Scoped to `.cell-tag.cal-
     *` (2-class, beats the bare `.cal-*` rule regardless of source order)
     so calendar dots/filled-cards/timeline bars keep their original bold
     look -- only the label-pill element repaints, everywhere it's used.
  Full suite: 1946 passed (four parallel chunks, `test_caldav_bridge_live.py`
  excluded as always).

- **Shipped:** Direct follow-up, same day (2026-09-03), on top of the two
  entries right below: "labels should all look like pils and have their
  respective icons visible. also all pils should have the same rounded
  corners and text should have the same size." The quiet dot+muted-text
  Labels treatment from the density-pass entry below (`label_pill_quiet`,
  `.cell-tag-quiet`) is reverted outright, same day it shipped -- the
  Tasks/Habits row's Labels cell goes back to the original `label_pill`
  (full color fill + icon, same macro every other page's read-only tag
  display already used); `label_pill_quiet` deleted from _label_pill.html
  rather than left as dead code, its two call sites (_task_row.html/
  _habit_row.html) reverted to `label_pill`. Icon visibility itself is
  unchanged code -- gated by `_show_label_icons()` (Settings > Appearance
  > "Show icons next to labels", off by default) AND the individual
  label's own configured icon (Settings > Labels) -- neither of those
  toggles was touched this session; if a label still shows no icon after
  this, check both settings, not a code path. New this round: the Labels
  pill and the Status chip next to it now share one shape -- `.cell-tag`'s
  app-wide default (`var(--radius-sm)` 8px / `var(--text-caption)` 13px)
  never matched the Status trigger's own compact-chip override from the
  density pass (`var(--radius-pill)` fully rounded / 11px), which is what
  read as "not all pills have the same rounded corners." Fixed with a
  `.task-labels-select .cell-tag` override (radius-pill + 11px) scoped to
  this one row's Labels cell specifically -- every other page's label
  pills (task/event/contact detail, project Kanban, widget builder) keep
  the app's normal 8px/13px look untouched. Full suite: 1940 passed (four
  parallel chunks). Verified the reverted markup directly (bare-Request
  script, same harness limitation as always -- no real `request.app`, so
  `_label_color`/`_label_icon`'s broad except silently falls back to
  default color/no icon in that harness specifically; not evidence of a
  real bug, just untestable outside a live ASGI request the way this
  suite is structured) -- confirmed `.task-labels-select .cell-tag` with
  the new radius/font-size lands, `label_pill`'s icon-conditional markup
  is back in place.

- **Shipped:** Direct follow-up, same day (2026-09-03): "don't repeat
  column headers, say them once. don't group tasks by label anymore, make
  one single big table. also I want the white card background div back."
  Three changes on top of the design pass right below:
  1. **One flat table, one header.** `_tasks_body.html`'s per-group
     `.card`+`<table>`+`<thead>` (Project/Unassigned/Completed, each
     repeating Title/Status/Date/Labels in its own header) is gone --
     collapsed into one `<table id="task-table">` inside one `.card` with
     one plain `<thead>`. `routers/tasks.py`'s `_build_task_groups`/
     `groups` context is untouched (still Project-alphabetical -> Habits
     -> Unassigned -> Completed, per `test_tasks_grouping.py`) -- the
     template just concatenates every non-Habits, non-Completed group's
     tasks into one `<tbody>` in that same order, then Completed's own
     tasks last in the same `<tbody>` (still dimmed via the existing
     `.task-row-completed` class, just no longer behind its own header).
     Habits keeps its fully separate table/header/`+` -- confirmed with the
     user this wasn't part of the "grouped by label" complaint, it's a
     different column set for a different row kind, not a label grouping.
  2. **Single "+ Task nou" add button**, replacing every per-group `+` --
     `_tasks_toolbar.html` now renders one `<a href="/tasks/new" ... class="btn
     primary" data-fab>` next to the Date filter in the page header's
     actions slot (same slot/pattern Notes' own header button uses); the
     project a new task belongs to is picked inside the create modal's own
     Labels field, same as every other path that ever set one.
  3. **White card background back** -- reverted the same session's earlier
     `.task-group-card`/`.task-table-habits` flattening override
     (`background:none`/no shadow/no hover-lift) entirely; both fall back
     to the plain `.card`+`.table-scroll` elevated look with no override.
     Moot for `.task-group-card` specifically now anyway, since (1) above
     means there's only ever one of it on the page.
  Confirmed with the user before implementing (AskUserQuestion, two
  questions): Completed tasks stay clustered at the end of the one table
  (dimmed, no header) rather than fully interleaved by date, and the
  add-task affordance is one button above the table (project picked in the
  form) rather than a per-row project column. Updated
  `test_tasks_table_habits_split.py`'s `TestGroupNameAndAddButtonInTableHeader`
  -- its three per-group-header tests asserted exactly the design being
  undone here (`>Garden (1)<`/`>Unassigned (1)<`/`>Completed (1)<` inside a
  `<thead>`), replaced with tests asserting the merged table's single
  header, that Project/Unassigned tasks actually land in the same
  `<tbody>`, that Completed still renders dimmed inline, and that exactly
  one `href="/tasks/new"` exists on the page; the Habits-table-specific
  test in the same class was untouched (that table didn't change). Full
  suite: 1940 passed (four parallel chunks, `test_caldav_bridge_live.py`
  excluded as always).

- **Shipped:** Direct request (2026-09-03), seven-point design pass on the
  Tasks table's density/hierarchy ("kill the giant empty space in every
  row... stop treating every group as a giant card... make the task name
  dominant... status should not consume an entire column... labels need to
  be less visually aggressive... put the + where it actually belongs...
  delete should be hidden until hover"). All CSS plus a handful of small
  template hooks, no column-layout rewrite, no JS changes — kept the
  existing `<table>`/`<tr>`/`<td>` structure (and its Status/Date/Labels
  `<th>`s) rather than the two-line flex-row shape the request's own
  mockups sketched, specifically so `static/tasks_table.js`'s delegated
  selectors (`closest("tr")`, `td:nth-child(2) a`, etc.) and the existing
  markup-assertion tests (`test_tasks_table_labels_status_title.py`,
  `test_tasks_table_habits_split.py`) didn't need touching:
  1. Row height: `.task-table thead th`/`tbody td` padding scoped down
     from the app's default 10-12px to 8px (same "#labels-table gets its
     own scoped override, not a bare `tbody td` rule" precedent already in
     style.css) — lands at ~44px (the trailing delete `.icon-btn` is the
     tallest cell at 28px square).
  2. Groups: `.task-group-card`/`.task-table-habits` (both also `.card` +
     `.table-scroll`) flattened — `background:none` (drops the elevated
     fill AND `.table-scroll`'s edge-fade gradients, which are painted in
     the same now-absent `--bg-elevated` and would otherwise show as stray
     tinted rectangles at the edges), `box-shadow:none`, no hover-lift. The
     header row's own 2px `border-bottom` (unchanged) is now the only
     boundary between groups.
  3. Title: `.task-title-cell a` bumped to 600 weight / `--text-body`. The
     title column's floor width dropped 140px -> 64px (140px was the
     "checkbox -> enormous whitespace -> status" gap the request pointed
     at directly — a short title like "h" was reserving room nothing used);
     the existing `:has([data-editing])` 280px floor while typing is
     untouched. Date (`.dtp--compact .dtp-trigger`) recolored to
     `--fg-secondary`, a rung below the title.
  4. Status: `.task-status-select .pill-select-trigger` padding/font
     shrunk further (2px 7px / 11px) into a small colored chip. Not a
     literal single dot — four live statuses (Active/Completed/Archived/
     Paused) need to stay distinguishable without opening the menu, which
     the request's own fallback wording ("if you have multiple states, use
     a tiny status indicator... clicking it opens the state menu") already
     allows for.
  5. Labels: new `_label_pill.html::label_pill_quiet(tag)` macro — a small
     `.color-dot` (reused as-is, just painted via the label's own
     `.cal-<color>` class for its `background`) plus plain muted text,
     replacing the old bold filled `.cell-tag` pill in the Tasks/Habits
     row's *closed-state* display only (`_task_row.html`, `_habit_row.html`).
     The Labels dropdown *panel* options still render the original
     `label_pill` (full color) — the request's own carve-out for "when
     labels are an important filtering mechanism." Every other `label_pill`
     caller (task/event/contact detail, project Kanban, widget builder)
     untouched.
  6. Header `+`: `.task-add-btn`/`.task-add-btn-label` — icon stays
     icon-only at rest, a `max-width:0`-collapsed "Add task"/"Add habit"
     label expands in on hover/focus instead of a bare glyph alone at the
     end of a header row.
  7. Delete: `.task-row-delete{opacity:0}`, revealed on `tr:hover` OR
     `tr:focus-within` (not `display`/`visibility`, so it stays a real
     focusable target for keyboard tabbing — `:focus-within` reveals it the
     moment focus reaches it, before a sighted keyboard user needs to see
     it) — new `.task-row-actions`/`.task-row-delete` classes on the
     trailing `<td>`/button in both `_task_row.html` and `_habit_row.html`.
  Deliberately NOT built: the mockups' ⋮ Edit/Duplicate/Move/Delete menu —
  Edit and Delete already exist (open the row, delete icon), but Duplicate
  and Move have no backend support at all (no duplicate-task endpoint, no
  per-row move-to-list action outside the bulk-actions bar), so inventing
  menu items for features that don't exist would be worse than the plain
  hover-reveal delete this ships instead. Also not built: using the
  bulk-select checkbox itself as a one-click "mark complete" toggle (the
  mockups' `□`/`✓` idea) — that checkbox is the bulk-selection control
  (`static/tasks_table.js`'s whole shift-click/drag-paint/bulk-actions-bar
  system keys off it); overloading it with a second, conflicting meaning
  would break bulk-select outright, not simplify the row. Status stays its
  own compact control instead (item 4 above).
  Verified: full suite passed (four parallel chunks by test-file, this
  environment's background-process-per-bash-call limitation meant a single
  bash call had to launch all four AND `wait` on them together rather than
  polling separately — 1939 passed, 0 failed, `test_caldav_bridge_live.py`
  excluded as always). Also spot-checked the rendered `/tasks` HTML
  directly (a seeded in-memory-DB script, not added to the suite) to
  confirm `label_pill_quiet`'s markup and the new hover/`+`-label classes
  actually land where expected — the Python test suite has no JS/CSS
  harness (per this file's own recurring note), so the seven points above
  are validated by source/markup inspection, not a computed-style
  assertion.

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
