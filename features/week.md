# Week (planning) — retired, folded into Calendar (1.9 side work)

`GET /week` (`routers/week.py::week_view`) shipped in 1.7 slice 2
("Week — planning", `plans/open-priority.md` § Information architecture &
view surfaces). It is **retired** — `routers/week.py`,
`templates/week_planning.html`, and `tests/test_week_planning.py` are gone.
`GET /week` now redirects (302, `routers/calendar.py::week_redirect`,
registered on that module's unprefixed `events_router` since the redirect's
own path can't live under `router`'s `prefix="/calendar"`) to
`/calendar/week`, preserving any `?date_=` query param — same "any bookmark
still lands somewhere real" precedent this repo already established for
`/calendar/timetable` (see `features/calendar.md`).

## Why this was safe to retire outright (not ported like `/today`)

Unlike `/today` (whose Important & urgent / scheduled-work-hours sections
had no existing Dashboard equivalent and needed new widget types before
retirement), `/week`'s entire cross-project planning capability — the
Unscheduled work sidebar, drag-to-schedule, block move/resize/delete, the
session stepper — was **already fully present** at `/calendar/week` before
this retirement, confirmed by reading both routers/templates directly
(not assumed): the "Calendar Week + Timetable merged" side work
(`plans/STATE.md`, 2026-08-14) had already folded the former "Timetable"
sub-view's identical planning capability into the ordinary Calendar Week
grid. `/week` had simply become a third copy of the same thing `/calendar/
week` and the project Week Calendar (`/projects/{name}/calendar`) already
did — see `features/calendar.md`'s own Week section for the full
"Unscheduled work" panel/drag/session-stepper behavior, which is identical
to what this page used to describe.

## Notes

- The `/week` tabbar entry is gone (`base.html`) — Home, Calendar, Tasks,
  Projects, Schedule, and Contacts remain.
- Every open task with no dated work session still drags onto
  `/calendar/week`'s grid exactly as it did on the old `/week` page; no
  scheduling functionality was lost, only the separate page.
