# Features

**Historical / superseded (2026-08-07).** `desktop/` — the PySide6 app these docs
describe — was deleted as Phase 8 (the final phase) of
[`../plans/label-space-rework.md`](../plans/label-space-rework.md); `webapp/`
is now the sole client. The docs below are kept as the historical record of
what `desktop/` implemented, same as the Flutter/FastAPI-era history already
preserved in [`../plans/systems/decisions-log.md`](../plans/systems/decisions-log.md)
— they are **not** a description of anything currently running, and nothing
here is being carried forward or rebuilt on that basis alone. `webapp/`
currently has **no equivalent feature-by-feature documentation of its own**
— this is a known, un-filled gap (not something invented here), flagged
during the Phase 8 pre-deletion audit; if you're looking for what `webapp/`
actually does today, the closest things that exist are
[`../architecture.md`](../architecture.md) (root, describes `webapp/`'s
current architecture) and `plans/label-space-rework.md` itself (§0–§2 for
the data model, and the individual `✅ DONE` phases for what shipped).

Original description, left as-is for historical context: this folder
documented what was actually implemented in the app, one feature area per
file, reflecting the current build in `desktop/src/` — not aspirations, not
in-progress work.

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
