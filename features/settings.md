# Settings

`routers/settings.py` — a hub-and-children layout (rework 2026-08-08, template
uniformization 2026-08-17 per `SETTINGS_UI_GUIDE.md`). The hub page
(`settings_index.html`) has seven categories:

- **General** (`/settings/general`) — display name (drives the Home greeting),
  week start (Mon/Sun), 24h vs 12h time, "4-Week view: current week" position,
  profile picture (upload/remove, 5MB + allowlist, base64 in app_meta).
- **Appearance** (`/settings/appearance`) — theme System/Light/Dark segmented
  control; "Show icons next to labels" toggle; "Show the Relations card"
  toggle.
- **Labels** — link to the `/labels` manage page.
- **Holidays** (`/settings/holidays`, 2026-08-14, moved off Schedule's own
  Table view; 2026-08-17 reworked onto the Labels grouped-list + modal
  pattern) — `settings_holidays.html` is now a `.label-list` of every
  `schedule_holidays` row across every named calendar (`id="holiday-list"`),
  each row a title + "calendar · from → to" hint with an Edit button. Edit
  opens `/settings/holidays/{uid}/edit` (`edit_holiday_modal`,
  `holiday_edit_modal.html` — the same modal-in-`#modal-target` shape as
  Labels, with delete in the footer's confirm mode); "+ Add holiday" opens
  `/settings/holidays/new` (`new_holiday_modal`) for a blank row. Saves post
  `POST /settings/holidays/{uid}/update` (`update_holiday`), the old
  per-field `update-field` endpoints are gone. The Calendar field is
  `_widget_list_multiselect.html` in `single`+`allow_new` mode — pick one of
  `db.list_holiday_calendar_names` or type a new one to originate a calendar,
  same idiom as a Labels field; a calendar is just the set of distinct
  `calendar_name` values in `schedule_holidays`, no separate table. A holiday
  calendar is a reusable resource any recurring Calendar event or Schedule
  block can reference (`holiday_calendar` field, see `calendar.md`'s
  Recurrence section and `schedule.md`'s Settings panel) — it earns its own
  hub category rather than staying Schedule-only, unlike Schedule's other
  settings (semester dates etc.), which stay on `/schedule` itself; see
  this router's own "2026-08-14 follow-up" docstring note for the full
  reasoning.
- **Sleep & Leisure Time** (`/settings/time-blocks`, 1.9 side work; 2026-08-17
  reworked onto the same grouped-list + modal pattern) — two `.label-list`
  sections (Sleep, Leisure) over the `time_blocks` table: `kind`
  (`'sleep'`/`'leisure'`, fixed — not a user-named set like a holiday
  calendar), `label`, `start_time`/`end_time` (`"HH:MM"`, plain `<input
  type="time">`, no date component at all), `days` (comma-joined subset of
  `db.TIME_BLOCK_DAYS`, picked via `_widget_list_multiselect.html` in
  `filter` mode). Each row's Edit opens `/settings/time-blocks/{uid}/edit`
  (`time_block_edit_modal.html`, delete in the footer); "+ Add" per section
  opens `/settings/time-blocks/new?kind=sleep|leisure` (`new_time_block_modal`).
  Saves post `POST /settings/time-blocks/{uid}/update` (`update_time_block`,
  kind is *fixed by the row* — a `kind` submitted with the form is ignored —
  and an `end_time <= start_time` edit is dropped as malformed). See
  `calendar.md`'s Views section for where these rows turn into the Week/Day
  grid's soft-hatch overlay and the drag scheduling warning.
- **Data & Maintenance** (`/settings/data-maintenance`, 2026-08-17) — the
  merged page that folds in the former **Data health**, **Advanced**, and
  **Sync conflicts** hub categories (their old URLs, plus `/export`, are now
  303 redirects here; every POST action endpoint keeps its own URL but
  redirects back to this page). Sub-sections, in the order `SETTINGS_UI_GUIDE.md`
  prescribes (visually urgent first, reference last):
  1. **Needs attention** — a warning-tone card (M3 `--tag-red-*` tokens, the
     one deliberately non-neutral block in Settings) that renders *only* when
     something is actually wrong: unresolved sync conflicts (with Restore /
      Dismiss per row, `POST /settings/sync-conflicts/{conflict_id}/restore|dismiss`),
     a failed integrity check, or a latest backup that failed verification.
     The other half of "visible": `settings_index.html` renders a
     `pill-static pill-red` count badge on the hub row itself when
     `conflict_count > 0`.
  2. **Health status** — database integrity / last backup / last backup
     verification / synchronization as colored chips
     (`pill-static pill-green/red/gray`), not plain text rows.
  3. **Maintenance & upkeep** — Backup now (`btn primary`), Verify latest /
     Check integrity / Repair (Compact & reindex) / Reset Home widget layout
     (`btn ghost`, reset posts `POST /dashboard/reset`), plus the
     sync-retention (sync GC days) and auto-archive completed tasks selects.
  4. **Export & import** — the standard-format download links, JSON backup,
     and import/restore forms (from the old Advanced; `radicale_url` shown;
     uses `export_context()`). See `export.md`.
  5. **Danger zone** — Purge completed (tasks-only) and Purge all (full data
     wipe), `.btn danger`, visually separated at the bottom.
  6. **Backups & storage** — storage stats (DB size, backups dir size/count,
     entity counts) and the Backups table (every `backup-*.json` under the
     configured `backup_dir`, newest first, per-row Verify/Restore).
  The maintenance operations are `src/data_health.py` plain functions taking
  `conn`/paths — no HTTP dependency; both this page's routes and
  `scripts/data_health.py` (the CLI: `status`/`backup`/`list`/`verify`/
  `restore`/`integrity-check`/`repair`) call the same functions, so there is
  exactly one implementation of each ("GUI and CLI use the same underlying
  maintenance services", per `open.md`). A backup's payload is the identical
  dict `routers/export.py`'s `build_backup_payload` produces; verification
  caches as a `<file>.verify.json` sidecar next to the backup; restore always
  takes a fresh safety-snapshot backup of the *current* state first and
  aborts without touching the database if the target fails verification.
- **Published lists** — link to `/published-lists`.

POST routes: `/settings/display-name`, `/settings/profile-photo`,
`/settings/profile-photo-remove`, `/settings/week-start`,
`/settings/four-week-position`, `/settings/time-format`,
`/settings/label-icons`, `/settings/holidays`,
`/settings/holidays/new`, `/settings/holidays/{uid}/edit`,
`/settings/holidays/{uid}/update`, `/settings/holidays/{uid}/delete`,
`/settings/time-blocks/new`, `/settings/time-blocks/{uid}/edit`,
`/settings/time-blocks/{uid}/update`, `/settings/time-blocks/{uid}/delete`,
`/settings/task-auto-archive`, `/settings/sync-retention`,
`/settings/data-health/backup`, `/settings/data-health/verify`,
`/settings/data-health/restore`, `/settings/data-health/integrity-check`,
`/settings/data-health/repair`, `/settings/data-health/sync-gc`,
`/settings/sync-conflicts/{conflict_id}/restore`,
`/settings/sync-conflicts/{conflict_id}/dismiss`,
`/settings/purge-completed`, `/settings/purge-all`.

See `export.md` for the export/import/backup formats.
