# Habits

Entirely local (no CalDAV). Two surfaces:

- **Manage list** (`/habits`) — create/archive/unarchive/delete, 12-week mini
  heatmap preview + streaks.
- **Detail** (`/habits/{uid}`) — 53-week GitHub-style heatmap, current/longest
  streak, total days logged, backfill form with stepper + note,
  archive/unarchive.

The heatmap is server-rendered plain HTML — each day cell is a tiny toggle
`<form>` (no JS required); clicking toggles 0/1
(`/habits/{uid}/entries/{date}/toggle`). Explicit-value backfill posts
`POST /habits/{uid}/entries` (referer-aware redirect). Shared math in
`habit_heatmap.py` (`heatmap_weeks`, `heatmap_range`, `streaks`,
`current_half_year`).

Habits also appear as a **Tasks view** (`/tasks/habits`): tasks carrying the
configured habit label (default "Habit", settable inline →
`POST /tasks/habits/settings`) with checkbox/stepper check-in and a half-year
heatmap, plus a dedicated stripped-down habit form (`habit_task_form.html`).
Habit-labeled tasks are hidden from all other tasks views/widgets by default.
