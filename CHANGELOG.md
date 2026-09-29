# Changelog

All notable changes to this project are documented here, one entry per
tagged release. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
