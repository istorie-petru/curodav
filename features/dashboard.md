# Feature: Dashboard (Today)

**Code:** `desktop/src/features/dashboard/`
**Status:** Implemented

The default landing page. A smart aggregation of everything due, overdue, or pinned, across every object type — not a module of its own data.

## What's built

- **Stats strip** — counts of open tasks, overdue items, items due today, active projects. Click a stat to jump to the filtered list.
- **Overdue/Today sections only** (Pinned and Upcoming removed 2026-07-19, see below) — each renders as one bordered grouped-list box with hairline separators between rows (changed 2026-07-19, see below), not individually-carded rows with gaps between them. Overdue sorted most-overdue first; Today sorted by time.
- **Quick-add row** — type a title with optional tokens (`@today`/`@tomorrow`, `!1`–`!4`, `#project`, `>tag`) and press enter to create a task with smart defaults. Shared logic with the Tasks quick-add lives in `features/shared/create.py`.
- **Activity feed** — computed from object history (created/edited/completed/overdue); see `data-and-attachments.md`.
- Empty states show placeholder text instead of blank space (e.g. "Nothing overdue").

## Underlying query

Roughly: objects where `due_at` is today, or `start_at` is today, or `pinned`, or overdue, and status is not in (done, archived) — across all types, sorted overdue → pinned → timed → rest. Same query shape as the smart lists in Tasks.

## Changed 2026-07-19: grouped-list-card pattern

Comparing against the "ModernPlasma Productivity" design doc (a macOS-styled reference mockup) surfaced a real structural gap: the design's task/agenda lists render as one elevated container per section with 1px hairline separators between rows (the macOS System Settings pattern) — the app instead stacked individually-bordered, individually-shadowed `ObjectCard` widgets with visible gaps between them, which reads as a list of separate cards rather than one grouped list.

Fixed by adding a `flush` mode to `ObjectCard` (`widgets/object_card.py`) — no border/radius of its own, just a bottom hairline, meant to sit directly against the next row — and having `SectionGroup` (this module) wrap flush rows in one bordered `QFrame` container (`section-list-box`) instead of a bare `QVBoxLayout` with spacing. Default `ObjectCard` behavior (search results, link picker, project task list) is unchanged — only `flush=True` differs, and only `SectionGroup` passes it. See `design-system.md` for the fuller design-doc comparison and `../plans/design-alignment.md` for what's still not matched elsewhere (Tasks/Calendar mini-sidebars, a real segmented-control widget, the inspector as a slide-over panel).

## Changed 2026-07-19: Pinned and Upcoming sections removed; absorbed the old Tasks Smart-view role

The Tasks module's Smart list view (a sidebar of saved filters: Today, Upcoming, All Open, High Priority, Waiting, Completed, Archived) was removed entirely — see `tasks.md`. Dashboard took over its "Today"/"Overdue" role specifically (the two filters that make sense on a daily landing page); the request was explicit that Dashboard should show *only* overdue and today, so the pre-existing Pinned and Upcoming sections were dropped in the same pass rather than kept alongside. The remaining Smart filters (Upcoming, All Open, High Priority, Waiting, Completed, Archived) did **not** move here — they became a chip filter bar above the Tasks Table view instead (`features/tasks/table_view.py::SMART_FILTERS`), since Dashboard is deliberately narrow now, not a second home for every saved filter.

`DashboardView.set_objects` no longer computes a `pinned` or `upcoming` list; `StatsStrip`'s four counts (open tasks/overdue/due today/active projects) are unchanged.
