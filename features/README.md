# Features

This folder documents what's actually implemented in the app today, one feature area per file. Each doc reflects the current build in `desktop/src/` — not aspirations, not in-progress work. If a feature has known gaps or a queued rework, the doc says so and links to the relevant plan in [`../plans/`](../plans/README.md).

**Read [`STRESS_TEST_2026-07-17.md`](STRESS_TEST_2026-07-17.md) first if you're relying on any "Implemented" label below.** A stress-test pass on 2026-07-17 found that several features documented as implemented (based on the source existing and looking complete) don't actually work end-to-end — global search, the general board object type, WebDAV, calendar recurrence, and JSON/Obsidian import all turned out to be broken, unreachable, or stubbed despite substantial code behind them. The docs below have been corrected inline (look for "Verified broken"/"Verified stub" callouts); anything without one of those callouts was exercised and held up.

| Doc | Covers |
|---|---|
| [`dashboard.md`](dashboard.md) | Today view — stats, pinned/overdue/upcoming, quick-add |
| [`tasks.md`](tasks.md) | Smart lists, table/timeline/kanban views, checklists, subtasks, quick-add tokens |
| [`calendar.md`](calendar.md) | Month/week/day/agenda views, drag/resize, overlap layout, multi-calendar |
| [`notes.md`](notes.md) | **Removed 2026-07-19** — historical record of the old module |
| [`boards.md`](boards.md) | Kanban boards, drag-and-drop, custom pipelines |
| [`projects.md`](projects.md) | Project detail view, derived progress, milestones |
| [`roadmap-goals.md`](roadmap-goals.md) | **Removed 2026-07-19** — historical record of the old module |
| [`search.md`](search.md) | Global search + command palette (FTS5) |
| [`tags-and-linking.md`](tags-and-linking.md) | Tags, structural parent/child, associative links, backlinks |
| [`settings.md`](settings.md) | Preferences popup dialog (seven sections), per-device settings |
| [`window-and-menu.md`](window-and-menu.md) | Top navigation bar, native QMenuBar / Plasma global menu |
| [`sync-and-webdav.md`](sync-and-webdav.md) | Syncthing integration, embedded WebDAV server, HLC conflict merge |
| [`design-system.md`](design-system.md) | Native-palette theming (Plasma/GNOME light/dark), navigation glyphs |
| [`data-and-attachments.md`](data-and-attachments.md) | Attachments blob store, notifications, import/export, activity feed |
| [`calendar-rework-history.md`](calendar-rework-history.md) | Historical: the 2026-07-12 calendar feature-parity pass (pre-rework) |
| [`performance-report-2026-07-12.md`](performance-report-2026-07-12.md) | Historical: a static performance audit of the old Flutter client |

## Workflow

These docs are written or updated once a plan in [`../plans/`](../plans/README.md) is finished — they describe outcomes, not intentions. If you're about to start work, check `plans/` first for whether it's already scoped there.
