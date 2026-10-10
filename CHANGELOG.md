# Changelog

All notable changes to this project are documented here, one entry per
tagged release. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [3.7.0]

- Notebook Browse is a table with load more, bulk edit and bulk delete, and filters that toggle on and off.
- Editor: inline tools, text and background color, a More menu, markdown paste and block color and duplicate. Undo loads the saved document first, updates in place and keeps its history between sessions.
- Endnotes are created from the inline toolbar, are rich text, and each has a menu to generate a citation.
- Tables are a first-party spreadsheet-like block: merged cells, header row and column, sorting, cell colors, simple formulas (text, joining with &, comparisons, IF, AND, OR, NOT, ranges) and markdown, TSV and CSV paste and export.
- Mentions: `@` for contacts, `$` for tasks and events and `:` for icons, in text, tables and formulas.
- Glossary: an Auto-fill button attaches every term found in the document.
- Properties: each Settings > Notebook field gets an input for its type and is validated when saved.
- Search contents: find and replace across notes with a preview first, a per-note choice and a warning toast when more than five notes change.
- One rule for floating menus and bars: they close on an outside click, Escape, or when another opens.
- Password recovery: the recovery token is no longer shown in Settings. `curodav-ctl token` prints it (`--new` replaces it) and `curodav-ctl password-reset` uses it; a new password needs at least 8 characters.
- Touch devices: long-press a row to select it instead of using checkboxes, and the phone status bar follows the light and dark theme.

## [3.6.0]

- Home, groups and labels can each show as the Secretariat, Sections or a dashboard. Home defaults to the Secretariat, which hides empty sections, lists events today, tasks due today and this week on the left and other reminders on the right, shows label pills, and keeps completed tasks until the day ends.
- Work sessions have a title, an hours estimate and a difficulty. The Planner has an Unscheduled work sidebar.
- Contacts have a pseudonym, a role and an honorary title, and each published contact list chooses which name it syncs.
- Task and event details describe repeats in plain words instead of the raw rule.
- Label views list habits due today in the agenda, show eight items, and have an Archive button.
- `./run.sh skipauth` skips the login for a local run only, and refuses to start over a stale server.
- Date-dependent tests read the injected clock.

## [3.5.0]

- Settings: General, Your Profile, Notifications, Appearance, Data & Maintenance and Notebook open as modals that stay open while a setting saves. The Database, Backup and Sync status cards now sit on the main Settings page. Notebook settings split into Notebook (sidebar layout) and Frontmatter (custom fields).
- Bulk select: buttons are icon-only with tooltips, and an Edit button changes the same fields on every selected row (tasks: status, dates, repeat, labels; contacts: label, organization, title; labels: color).
- Habits and Contacts share one section heading; cards share title, body and footer parts; amount habits use the same check button as other habits and show their count in the row.
- Contacts field: type a new name to create a contact straight from a task or event.
- Password recovery: Settings shows a recovery token, and `curodav-ctl password-reset` (or `scripts/password_reset.py`) resets the login with it. Local dev builds can clear the stored login with `--dev-clear`.
- Tests: files renamed by feature, rules about assets and templates moved to core tests, and tests that asserted on CSS, script or template text removed.

## [3.4.0]

- Shared interface components: round radio and square checkbox, named input
  components for every form control, one empty-state component, one pill
  look, a shared drag-and-drop upload zone, and icon-only header buttons
  with tooltips. Placeholder text is gone from forms (search boxes use a
  magnifier icon instead); the contact form's address parts have labels.
- Dropdowns: search turns on automatically above seven items, and a long
  dropdown that can add items merges search and add-new into one box.
- Modals keep a back-stack: Escape and Cancel walk back through the modals
  you opened.
- Contacts: a new contact is a hidden buffer contact from the moment the
  form opens, so its photo can be uploaded and cropped before saving; the
  photo can be re-cropped later from the upload modal. Tasks and events have
  a Contacts field, and a contact lists the tasks and events it is involved
  in.
- Event and accent colors are checked against both themes for readability;
  dark-theme fills are lighter, with dark text.
- Test suite reorganized (dashboard, auth and offline-sync areas) with new
  core tests for the interface rules.

## [3.3.0]

- Added Notebook, a new block-based note-taking module (Editor.js, vendored
  with no CDN dependency) -- a top-level nav destination with its own All
  Documents view, organized through the existing Groups/Labels system
  (not folders): a Notebook dashboard widget lists a label/group's
  documents, with a "New document" action that pre-attaches the current
  label and opens straight into the Editor. Document content autosaves;
  title and delete are plain, no-JS-required forms.
- Removed the old quick-capture `notes` feature outright (no migration --
  nothing had real data in it) -- absorbed into Notebook instead. Its
  router, table, and search/quick-capture/command-palette integration are
  gone.

## [3.2.0]

- Command palette and full search page: past events no longer clutter the
  default empty-query browsing view (`exclude_past_events`, whole-day
  cutoff) -- a real typed query still surfaces them, and the relation-
  picker mode (for_task/for_event) is untouched.
- Command palette rows and search-page results collapsed from two lines
  to one: title and subtitle now sit on a single flex row with a "·"
  separator, truncating the title first instead of always wrapping to a
  second line.
- Dropped the `.main-shell-body` `margin-bottom:6dvh` outright (and the
  Dashboard-only `--flush` modifier that had opted just Dashboard out of
  it) -- the same "veil that hides content" symptom reported for
  Dashboard on 2026-09-24 was confirmed across Tasks/Contacts/Notes/
  Habits too.
- Removed the top border between contact list sections (label groups).

## [3.1.0]

- 24 more flair ids: 18 real event-type icons (bills, delivery, doctor,
  flight, hotel, interview, online classes, party, photography, shopping,
  studying, trip, tv, video call, vote, ...), `restaurant` split out of
  `dinner` as its own id, and 8 scenery/color backgrounds (university,
  museum, mountain, sea, sky, wood, ...).
- Months and seasons are matched by an object's own due/start DATE, not
  by keyword against its name -- a new month tier (`db.MONTH_BANNER_
  SCOPES`, one tier more specific than the existing season tier) joins
  the app's existing season fallback. Both tiers now also read an
  operator's `flairs_dir` as their default photo source (drop `july.jpg`/
  `summer.jpg` in directly, same as any other flair), falling back from
  an explicit banner-editor upload on that scope.
- A task/event's own flair match now also tries its description, as a
  backstop when the title alone matches nothing usable -- title stays
  the dominant signal, description never outranks a real title match.
- New Settings > Flairs page: shows how many of the ~106 known flair ids
  currently have a photo configured, and a bulk-upload dropzone accepting
  a `.zip`, a whole folder, or several photos at once -- a zip's contents
  are smart-filtered by filename at any depth, with a result summary
  reporting anything skipped and why.

## [3.0.0]

- Habit/task "mark done" checkboxes consolidated onto one shared component:
  the Habit Check-in widget, the Agenda widget's habit and task rows, and
  the Calendar day-grid's all-day habit chips all now share the same
  toggle/quantity/avoid form markup, sizing, colors, and hover styling
  instead of four hand-rolled copies.
- A checked-off task or habit stays visible (checked, struck through) for a
  short grace period instead of disappearing the instant a widget re-fetches.
- Fixed a habit check-in not refreshing sibling Dashboard widgets that
  also showed the same habit (e.g. Habit Check-in staying stale after a
  check-in from the Agenda widget) until a full reload.
- Widget row title size/weight, checkbox sizing/hover, and the week
  strip's "today" cell fill unified across widgets.
- Unscheduled Work row tightened; the "Labels in this group" widget always
  renders as a card grid now (Groups & Labels style), with square card
  sizing and padding fixes.
- "Labels in this group" is no longer a separate, always-pinned full-width
  widget. A group's page now gets the same 25/50/25 layout Home has --
  quarter-width Today, half-width At a glance/Upcoming stack, and its own
  label list in a quarter-width third column instead.
- Edit label / Edit group are icon-only square buttons now, pinned to the
  right edge of the page header's actions row.
- Contacts/Labels bulk delete now refreshes the page's live region in
  place instead of a full reload (`CCBulkSelect`'s new `changeType`
  option, same claim protocol every other async-CRUD mutation uses).
- Tasks table label pills link to the label preview again, now that the
  Labels cell is a plain read-only cell rather than an editable dropdown
  trigger a link couldn't nest inside.
- Event markers everywhere (label preview modal, label/project Agenda
  cards) finished moving from a plain color dot to a colored `calendar`
  icon (`widget_event_dot` renamed `widget_event_icon`).
- Widget "Limit" field's default and its `0` (no limit) cap both lowered
  from 20 to 8.
- Fixed a crash opening a group's page (`TypeError: 'NoneType' object is
  not iterable`) from an incomplete `_filtered_tasks` edit.

## [2.9.0]

- Docker Compose deploy path (`deploy/docker/`): an alternative to
  `curodav-ctl`'s systemd install, app + Radicale as containers.
- README: app icon and screenshots, a new Docker Compose install section.
- Fixed `uv.lock`'s workspace manifest, stale since the v2.8.0
  `command-center` -> `curodav` rename -- `uv sync --frozen` (used by both
  the new Docker build and `curodav-ctl`'s own install/update) was failing
  outright with "Missing workspace member `curodav`".

## [2.8.0]

- Settings notifications reworked onto its own dedicated page; accent-color
  and banner pickers redesigned.
- Unscheduled Work panel redesigned, plus a "Labels in this group" widget.
- Row hover, header icons, and habit check-in styling standardized to one
  shared token across the app.
- Default banner/avatar photos restored as an operator-supplied, keyword-matched
  "flairs" system instead of bundled copyrighted images (see the Wiki's
  [Flairs](https://github.com/istorie-petru/curodav/wiki/Flairs) page).
- Icon set reverted to Lucide stroke icons.

## [2.7.0]

- Habits: amount habits, one Notifications settings page, per-habit reminder
  time, compact rows with a history panel, an approved edit-modal redesign.
- Calendar/Labels/flat-UI audit fixes merged: contrast, headers, now-line, day
  popover, agenda, label rail titles and icon fallback, banner icon chip.
- Typed date/time fields replace the old range picker app-wide.
- Contacts: single label per contact, grouped rows, a real archived flag.
- Groups: rename + member checklist, a dedicated dashboard widget.

## [2.6.0]

- Habits rebuilt as a dedicated feature: its own page, detail view (month
  calendar, day notes, log-a-day), amount units and avoid habits, vacation/
  pause, strength score and insights.
- Web Push notifications: VAPID subscriptions, a reminder scheduler for
  events/tasks/habits/sleep, configurable reminder types and a morning digest.
- Labels reorganized into modules: one page per label, old URLs redirect,
  text groups get their own pages, label preview modal.

## [2.5.0]

- Relative-date shorthand (Tmw/Yest), the card UI model removed app-wide in
  favor of flat pages, icon set swapped to Material Design Icons, design
  tokens tightened.
- Responsive tables via container queries; image editor aspect-ratio locking.
- Habits: first slice of the current model (a shared habit view over a
  habit-labeled task, schedule-aware streaks, a visible heatmap).

## [2.4.0]

- Contacts and label-color polish across task/event dots.
- Modal header restyle: circular close button, banner carries into edit.
- Labels table: grouped-row coloring and inheritance fixes.

## [2.3.0]

- Deploy hardening: `curodav-ctl` install/update reliability fixes, Radicale
  auth rate-limited via nginx.
- "Spaces" reworked into a labels-as-membership model (superseded again in
  2.6 by the label-modules rework).
- Published Lists gained negative (exclude) label filtering.
- Contact photos served transcoded to WebP regardless of source format.

## [2.2.0]

- `curodav-ctl` automates the DAVx5/Radicale public-access setup end to end.
- Published Lists' public URL fixed.

## [2.1.0]

- Settings reorganized: a merged Data & Maintenance hub, holidays and sleep/
  leisure time blocks moved onto the grouped-list + modal pattern.
- Kanban drag-and-drop, a reworked Calendar/Planner, Contacts field parity
  work, the bulk-actions bar relocated out of table headers.

## [2.0.0]

- The audit-fixes gate that closed out the 1.x series: a large pass of UI/UX
  fixes across Calendar, Dashboard, banners, published lists, and Settings.
- Deploy scaffolding for public CalDAV/CardDAV access (Cloudflare Tunnel +
  Radicale + nginx).
- README rewritten for first-time installers.

## [1.9.0]

- Tasks table pagination.
- The Schedule module and its University Space section removed entirely
  (superseded by ordinary recurring Calendar events with odd/even-week
  support, shipped in 1.6).

## [1.8.0]

- Offline-first PWA: installable app shell, a local IndexedDB mirror and
  write path, and tombstone garbage collection for the sync engine.

## [1.7.0]

- Information architecture rework: dedicated Today and Week planning
  surfaces (both later folded back into the Dashboard and Calendar once
  those covered the same ground — see 1.9's notes and the Wiki's
  [Feature Map](https://github.com/istorie-petru/curodav/wiki/Feature-Map) page).

## [1.6.0]

- Configurable recurrence terminology, manual per-occurrence recurrence
  exceptions, generalized holiday calendars, classes linked as project
  labels.

## [1.5.0]

- The deadline-vs-work-allocation distinction: a task's due date and its
  scheduled work sessions are explicitly separate concepts.

## [1.4.0]

- Work allocations (scheduled work sessions) and the project week calendar.

## [1.3.0]

- The project-enabled label stack: a project is a label with a date range,
  not a separate entity.

## [1.2.0]

- The task model settled: flat tasks plus work allocations, subtasks
  removed outright.

## [1.1.0]

- Virtual and derived task states (later replaced by the simpler, purely
  temporal derivation described in the Wiki's
  [Feature Map](https://github.com/istorie-petru/curodav/wiki/Feature-Map) page).

## [1.0.0]

- First stable release of the FastAPI webapp as the sole client: home
  dashboard, calendar, tasks, contacts, habits, and the universal label
  system.
