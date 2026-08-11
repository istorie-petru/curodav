# Settings

`routers/settings.py` — a hub-and-children layout (rework 2026-08-08). The hub
page (`settings_index.html`) has five categories:

- **General** (`/settings/general`) — display name (drives the Home greeting),
  week start (Mon/Sun), 24h vs 12h time, "4-Week view: current week" position,
  profile picture (upload/remove, 5MB + allowlist, base64 in app_meta).
- **Appearance** (`/settings/appearance`) — theme System/Light/Dark segmented
  control; "Show icons next to labels" toggle.
- **Labels** — link to the `/labels` manage page.
- **Published lists** — link to `/published-lists`.
- **Advanced** (`/settings/advanced`) — reset Home widget layout (links to
  `POST /dashboard/reset`), Export & backup inlined (standard formats + JSON
  backup/restore + import forms; `radicale_url` displayed), auto-archive
  completed tasks (`DAYS_CHOICES`: Never/7/14/30/90), Purge completed
  (tasks-only) and Purge all (full data wipe). Uses `export_context()`.

POST routes: `/settings/display-name`, `/settings/profile-photo`,
`/settings/profile-photo-remove`, `/settings/week-start`,
`/settings/four-week-position`, `/settings/time-format`,
`/settings/label-icons`, `/settings/task-auto-archive`,
`/settings/purge-completed`, `/settings/purge-all`.

See `export.md` for the export/import/backup formats.
