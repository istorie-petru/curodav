# Settings

`routers/settings.py` — a hub-and-children layout (rework 2026-08-08). The hub
page (`settings_index.html`) has six categories:

- **General** (`/settings/general`) — display name (drives the Home greeting),
  week start (Mon/Sun), 24h vs 12h time, "4-Week view: current week" position,
  profile picture (upload/remove, 5MB + allowlist, base64 in app_meta).
- **Appearance** (`/settings/appearance`) — theme System/Light/Dark segmented
  control; "Show icons next to labels" toggle.
- **Labels** — link to the `/labels` manage page.
- **Holidays** (`/settings/holidays`, 2026-08-14, moved off Schedule's own
  Table view) — a Tasks-table-style grid (`settings_holidays.html`,
  `id="holiday-table"`) of every `schedule_holidays` row across every named
  calendar, columns Title/Calendar/Start date/End date, all four
  inline-editable (`POST /settings/holidays/{uid}/update-field`,
  `_HOLIDAY_UPDATABLE_FIELDS`, mirrors `routers/tasks.py`'s inline-edit
  pattern). The Calendar cell is `_widget_list_multiselect.html` in
  `single`+`allow_new` mode — pick one of `db.list_holiday_calendar_names`
  or type a new one to originate a calendar, same idiom as a Labels field;
  a calendar is just the set of distinct `calendar_name` values in
  `schedule_holidays`, no separate table. `POST /settings/holidays` creates
  a new holiday (`calendar_name` default `'Default'`); `POST
  /settings/holidays/{uid}/delete` removes one. A holiday calendar is a
  reusable resource any recurring Calendar event or Schedule block can
  reference (`holiday_calendar` field, see `calendar.md`'s Recurrence
  section and `schedule.md`'s Settings panel) — it earns its own hub
  category rather than staying Schedule-only, unlike Schedule's other
  settings (semester dates etc.), which stay on `/schedule` itself; see
  this router's own "2026-08-14 follow-up" docstring note for the full
  reasoning.
- **Published lists** — link to `/published-lists`.
- **Advanced** (`/settings/advanced`) — reset Home widget layout (links to
  `POST /dashboard/reset`), Export & backup inlined (standard formats + JSON
  backup/restore + import forms; `radicale_url` displayed), auto-archive
  completed tasks (`DAYS_CHOICES`: Never/7/14/30/90), Purge completed
  (tasks-only) and Purge all (full data wipe). Uses `export_context()`.

POST routes: `/settings/display-name`, `/settings/profile-photo`,
`/settings/profile-photo-remove`, `/settings/week-start`,
`/settings/four-week-position`, `/settings/time-format`,
`/settings/label-icons`, `/settings/holidays`,
`/settings/holidays/{uid}/update-field`, `/settings/holidays/{uid}/delete`,
`/settings/task-auto-archive`, `/settings/purge-completed`,
`/settings/purge-all`.

See `export.md` for the export/import/backup formats.
