# Habits

A habit is a **habit-labeled task**: any task carrying the configured habit
label (default "Habit", settable via `POST /tasks/habits/settings`). It uses
the task's own `recurrence` (cadence), `target_per_day` (1 = checkbox, >1 =
a count like "8 glasses"), weekend/holiday exclusions, and work sessions;
its per-day log is `task_completions` (`value` = that day's count).
Habit-labeled tasks are hidden from every other tasks view/widget by default.

**One frontend shape** -- `src/habit_view.py::habit_items` turns each active
habit task into the dict every habit surface renders (title, cadence label,
target, today's value, next value, current streak, check-in URLs), so a
habit never has to look like a task (status/due date/Kanban) anywhere:

- **Habits page** (`/habits`, H2 -- `routers/habits.py`, `habits.html`,
  `_habits_body.html`, `_habit_page_row.html`, `static/habits_page.js`) --
  "To do" / "On track" sections; each row has a one-tap check (or +1 for
  an amount habit), the schedule, period progress and streak, and a
  tap-a-day strip of the last seven days. Every control is a plain POST
  form; the JS submits with fetch and re-renders `#habits-body`. The
  Tasks table no longer shows habits.
- **Dashboard Habit Check-in widget** (`_widget_habit_checkin.html`, H4)
  -- the same row as the Habits page, still-to-do first, "n of N done" /
  "All done for now"; scoped by page label like every other item widget.
  Both surfaces use `static/habit_actions.js` (fetch, then re-render the
  region from the server).
- **Detail modal** (`habit_task_detail.html`) -- streak/best/kept stats, a
  view-only 53-week heatmap, a clickable month calendar (`?month=`), a
  "Log a day" form (date, amount, note) and recent day notes
  (`task_completions.note`). Edit form: `habit_task_form.html`.

**Schedules and streaks** (H1, 2026-09-24) -- `src/habit_schedule.py`. A
streak counts *due windows*, not calendar days: a weekly/monthly habit
(optionally "X times per period" via `tasks.habits_per_period`) counts
weeks/months kept; a fixed-weekday habit (RRULE BYDAY) counts due days,
each window running to the next due day; FREQ=DAILY;INTERVAL=N counts
every-N-day windows. Also: completion rate, best streak, and whether the
open window is still to do (`due_today`).

Check-in endpoints: `POST /tasks/{uid}/completion/{date}/toggle` (flip a
day) and `POST /tasks/{uid}/completions` (explicit value; <=0 clears).
Heatmap/streak math lives in `habit_heatmap.py`.

**Habit form** (`habit_task_form.html`): Kind (Build / Avoid), Unit,
Recurrence preset, "Only on" day chips (any checked -> `FREQ=WEEKLY;
BYDAY=...`), Times per period, Daily target.

**Vacation / pause** (H6, `habit_pauses`): pause one habit (its detail
modal) or all habits (the Habits page's Vacation block) for a date range;
paused days neither keep nor break a streak, and a paused habit sits in
its own "Paused" section instead of "To do".

**Avoid habits** (`tasks.habit_kind = 'avoid'`, H5) log relapses instead
of check-ins; the streak is clean days since the last relapse, shown red
wherever a relapse is logged.

**Removed 2026-09-24** (plans/ui-cleanup-2026-09.md item 14, slice 1): the
standalone Habit entity (`habits`/`habit_entries`, its CRUD/entries
endpoints, `habit_form.html`, `habit_detail.html`, `static/habits.js`).
The tables stay physically in an existing database; old `/habits/...`
URLs redirect to `/habits`.
