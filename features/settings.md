# Settings

`routers/settings.py` — a hub-and-children layout (rework 2026-08-08). The hub
page (`settings_index.html`) has eight categories:

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
- **Sleep & Leisure Time** (`/settings/time-blocks`, 1.9 side work, direct
  feedback) — same Tasks-table-style grid shape as Holidays, two sections
  (Sleep, Leisure) each backed by the new `time_blocks` table: `kind`
  (`'sleep'`/`'leisure'`, fixed — not a user-named set like a holiday
  calendar), `label`, `start_time`/`end_time` (`"HH:MM"`, plain `<input
  type="time">`, no date component at all), `days` (comma-joined subset of
  `db.TIME_BLOCK_DAYS`, picked via `_widget_list_multiselect.html` in
  `filter` mode — "days" is a real multi-select, not single-choice).
  `POST /settings/time-blocks` creates a block (kind fixed per section's
  add-form, rejects `end_time <= start_time` or an unknown kind); `POST
  /settings/time-blocks/{uid}/update-field` inline-edits one field
  (`_TIME_BLOCK_UPDATABLE_FIELDS`; the "days" field takes one comma-joined
  string, not a JSON list — `static/settings_time_blocks.js` collects the
  full checked set before calling it, same one-request-shape-per-field
  convention Holidays' own JS uses); `POST
  /settings/time-blocks/{uid}/delete` removes one. See `calendar.md`'s
  Views section for where these rows turn into the Week/Day grid's
  soft-hatch overlay and the drag scheduling warning.
- **Data health** (`/settings/data-health`, 2026-08-14, `plans/open.md` §
  Data health & maintenance — the verified-backups precondition 1.8's offline
  sync is gated on) — Status card (database integrity via `PRAGMA
  integrity_check`, last successful backup, last backup verification,
  synchronization — a fixed "Not configured — offline sync ships in 1.8"
  placeholder pre-1.8), Storage & entities (DB size, backups dir size/count,
  task/event/contact counts, `data_health.entity_stats` reuses
  `export_context`), Maintenance actions (Backup now, Verify latest, Check
  integrity, Compact & reindex — `REINDEX` + `VACUUM`), and a Backups table
  (every `backup-*.json` under the configured `backup_dir`, newest first,
  per-row Verify/Restore). `src/data_health.py` holds every operation as a
  plain function taking `conn`/paths, no HTTP dependency — both this page's
  routes and `scripts/data_health.py` (the CLI: `status`/`backup`/`list`/
  `verify`/`restore`/`integrity-check`/`repair`) call the same functions, so
  there is exactly one implementation of each ("GUI and CLI use the same
  underlying maintenance services", per `open.md`). A backup's payload is
  the identical dict `routers/export.py`'s `build_backup_payload` produces
  (factored out of `export_data_json` so the on-demand data.json download
  and these server-side backups can never drift). Verification checks JSON
  structure, every required top-level key, that each collection is a list,
  and that every task/event/contact row carries a `uid` — the result caches
  as a `<file>.verify.json` sidecar next to the backup (not in the app
  database: a backup + its sidecar travel together, and the list is always
  recomputed by scanning `backup_dir`, never stored). Restore always takes a
  fresh safety-snapshot backup of the *current* state first ("preserve a
  recoverable backup of the current state where practical", `open.md`) and
  aborts without touching the database if the target fails verification.
  This is deliberately separate from Advanced's existing "Export & backup"
  section below — that's an on-demand *download* the person keeps
  themselves; Data health backups are server-side, verifiable, and
  restorable without leaving the app.
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
