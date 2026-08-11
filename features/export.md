# Export & backup

`routers/export.py` — `/export` redirects to Settings → Advanced (2026-08-08).

## Standard formats

- `/export/events.ics` (icalendar VEVENT)
- `/export/tasks.ics` (VTODO)
- `/export/contacts.vcf` (vobject)
- `/export/tasks.csv`, `/export/contacts.csv`

## JSON

- `/export/labels.json` — label configs + raw `object_labels` membership
  (consolidated from the old `/export/spaces.json` + `/export/tags.json` —
  those were two byte-identical routes, a compatibility layer).
- `/export/schedule.json` — schedule settings + classes + holidays.
- `/export/data.json` — full backup: events/tasks/contacts/labels/object_labels/
  schedule classes + holidays + settings/task_completions/event_task_relations.

All `list_tasks` calls pass `include_habit_tasks=True` so habit-labeled tasks
aren't silently dropped from backups.

## Import / restore

- `POST /export/import/events` (.ics VEVENT)
- `POST /export/import/tasks` (.ics VTODO)
- `POST /export/import/contacts` (.vcf via vobject)
- `POST /export/import/json` (full `_restore`, restores `completed_at` historically)
