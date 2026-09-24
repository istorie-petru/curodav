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

- **Tasks page, Habits group** (`#habits-table`, `_habit_row.html`) --
  inline-editable title and today's count, cadence, streak text.
- **Dashboard Habit Check-in widget** (`_widget_habit_checkin.html`,
  `static/habit_checkin.js`, fetch-based with no-JS form fallback) --
  scoped by page label like every other item widget.
- **Detail/edit modals** (`habit_task_detail.html` with a view-only
  53-week heatmap, `habit_task_form.html`).

Check-in endpoints: `POST /tasks/{uid}/completion/{date}/toggle` (flip a
day) and `POST /tasks/{uid}/completions` (explicit value; <=0 clears).
Heatmap/streak math lives in `habit_heatmap.py`.

**Removed 2026-09-24** (plans/ui-cleanup-2026-09.md item 14, slice 1): the
standalone Habit entity (`habits`/`habit_entries`, `routers/habits.py`'s
CRUD/entries endpoints, `habit_form.html`, `habit_detail.html`,
`static/habits.js`). Every `/habits...` URL redirects to `/tasks`; the
tables stay physically in an existing database. A dedicated Habits page is
the next slice.
