# Schedule

1.6 (Schedule & recurrence rework, 2026-08-14) shipped "Classes as project
labels + recurring events": `routers/schedule.py` no longer owns a dedicated
`schedule_classes` entity. A **class meeting** (a lecture, a seminar, ...) is
now an ordinary recurring row in the universal `events` pool, tagged with the
per-install Schedule system label (`schedule_settings.schedule_label`, default
`Schedule`) plus its course's project-enabled label (`is_project=1`). The
Schedule page/router is a specialized *interface* for creating and managing
those recurring events, not a separate data model — see `schedule.py`'s and
`db.py`'s `label_config` CREATE TABLE module docstrings for the full
rationale, and `plans/open-priority.md` § Schedule & recurrence rework for the
spec this implements.

Course-level facts that describe the whole course rather than any one
meeting — **acronym, type, credits, instructor** — live on the course label's
own `label_config` row (`course_acronym`/`course_type`/`course_credits`/
`course_professor_contact_uid`), not on the event: there's no standard VEVENT
property to round-trip them through. Day/time/parity/room/title genuinely
belong to one meeting and live on that meeting's own event fields
(`start_at`/`end_at`/`recurrence`/`location`/`title`); day and parity are
*derived* from `start_at`/`recurrence` on read (`schedule.event_day`/
`event_parity`), never stored separately.

A course can have more than one recurring meeting (a lecture *and* a seminar,
each its own event) sharing the same course label — editing any one meeting's
Acronym/Type/Credits/Professor fields updates the course's `label_config` row,
so every meeting of that course reflects the same values.

Pre-1.6 databases that still physically carry a `schedule_classes` table (not
force-dropped, per this app's own "never touch old data automatically"
convention) can be converted with
`scripts/migrate_schedule_classes_to_events.py` (idempotent, `--dry-run`
supported) — see that script's own module docstring.

Still using the flat, pre-1.6 `schedule_holidays`/`schedule_settings` model
(semester bounds + one un-named list of holiday date ranges) — the
"generalized non-working-day policy + named holiday calendars" and "manual
recurrence exceptions" and "configurable terminology" items from
`plans/open-priority.md`'s Schedule & recurrence rework section are still
open, tracked in `plans/STATE.md`.

## Classes page (`/schedule`)

Table/Calendar `?view=` toggle. **Table:** search `q`, label dropdown, sortable
columns (day/time/name/professor/room/credits/parity), grouped by day,
inline-editable pills (Day/Time via `reposition`, Parity via `update-field`,
Enrolled via `toggle-enrolled` — maps to the event's own active/archived
`status`). Conflicts (`schedule.compute_conflicts`, over the raw recurring
events) + credits-summary bar (summed once per distinct course label with at
least one active meeting, not once per meeting) always computed over *all*
classes; per-class "next occurrence" countdown
(`schedule.next_occurrence_for_event`, reusing `recurrence_expand.expand_events`
— the same RFC 5545 expansion the Calendar tab itself uses — rather than a
bespoke day/parity walk).

**Weekly grid** (`?view=calendar`): pixel-positioned via `grid_layout.layout_day`
on fake dates; hover-ghost preview, click/click-drag create (1-hour default),
drag/resize snapped to hour → `POST /schedule/classes/{uid}/reposition`.

Every "class row" the templates/JS see is an enriched dict
(`routers/schedule.py::_class_row`) built fresh from the underlying event +
its course label's config on every read — `schedule_classes.html`/
`schedule_class_form.html` needed **no changes at all** for 1.6, only the
router did.

## Class fields

name (the event's own title), acronym/type/credits/professor (the course
label's `label_config` row — see above), day, parity (Every/Odd/Even week,
derived), start/end time, room (the event's own `location`), label
(`project_uid` — the course), enrolled (the event's own `status`).

A class entered before both semester dates are configured still gets a real
event (open-ended recurrence, anchored on today) rather than no record at
all — `schedule.build_class_event_row` never returns `None`; it just can't
generate real bounded occurrences yet.

## Holidays & settings

Both are `<details>` on the same page, unchanged by 1.6:

- **Holidays**: create + delete (`POST /holidays`, `/holidays/{uid}/delete`),
  both regenerate every class event's recurrence/exdates
  (`routers/schedule.py::_regenerate_all`).
- **Settings**: semester start/end, credits needed, reminder minutes, event
  label (`POST /schedule/settings`) — renaming the event label re-tags every
  existing class event from the old name to the new one before regenerating.

Shared logic in `schedule.py`: `DAYS`, `first_occurrence`, `generate_occurrences`,
`compute_excluded`, `event_day`, `event_parity`, `next_occurrence_for_event`,
`next_label`, `build_class_event_row`, `compute_conflicts`.
