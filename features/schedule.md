# Schedule

`routers/schedule.py` — a semester class timetable that regenerates real events
into the universal `events` pool whenever day/time/parity/semester/holidays
change (`_regenerate_class_event`, `class_to_event_row`), so classes appear on
the calendar automatically.

## Classes page (`/schedule`)

Table/Calendar `?view=` toggle. **Table:** search `q`, label dropdown, sortable
columns (day/time/name/professor/room/credits/parity), grouped by day,
inline-editable pills (Day/Time via `reposition`, Parity via `update-field`,
Enrolled via `toggle-enrolled`). Conflicts + credits-summary bar always computed
over *all* classes; per-class "next occurrence" countdown.

**Weekly grid** (`?view=calendar`): pixel-positioned via `grid_layout.layout_day`
on fake dates; hover-ghost preview, click/click-drag create (1-hour default),
drag/resize snapped to hour → `POST /schedule/classes/{uid}/reposition`.

## Class fields

name, acronym, day, parity (Every/Odd/Even week), start/end time, type
(distinct-values dropdown + "+ Other"), professor (contacts dropdown +
"+ Add new professor…" that creates a contact), room, credits (stepper), label
(`project_uid`), enrolled.

## Holidays & settings

Both are `<details>` on the same page:

- **Holidays**: create + delete (`POST /holidays`, `/holidays/{uid}/delete`),
  both regenerate all class events.
- **Settings**: semester start/end, credits needed, reminder minutes, event label
  (`POST /schedule/settings`).

Shared logic in `schedule.py`: `DAYS`, `first_occurrence`, `generate_occurrences`,
`next_occurrence`, `next_label`, `compute_conflicts`, `credits_summary`.
