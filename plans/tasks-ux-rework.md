# Plan: Tasks module UX rework

**Status:** Open, partially shipped 2026-07-19 (Table view items below) · logged 2026-07-12, carried over from `todo.md`
**Feature area:** [`../features/tasks.md`](../features/tasks.md)

Specific interaction fixes for the Tasks module, based on using the current build. Current behavior is described in `features/tasks.md`.

## Table view

- ~~**Project cell** should behave like the **Priority** cell: click it, a dropdown appears, pick a project.~~ **Done 2026-07-19** — a project column didn't even exist before; added, with a dropdown editor. See `../features/tasks.md`.
- ~~**Progress** should be editable inline as a percentage input box, not free text parsed from a `QLineEdit`.~~ **Superseded 2026-07-19** — progress is no longer independently editable *anywhere* in the app (Table, Kanban, or the inspector). It's now purely derived from status (`progress_for_status()`), so there's no percentage-input widget to build — the Progress column in Table view is a read-only pill showing the derived value.
- **Tags** should be added/applied from the row's right-click context menu — no modal dialog. Still open — tags edit as a comma-separated `QLineEdit` in-cell now, with autocomplete added 2026-07-19 (an improvement over a modal, but not the specific right-click-menu interaction asked for).
- **Remove the leading checkbox's current job** (marking done/not-done). Repurpose it as a row **select** checkbox for bulk actions. Still open. (Moot for now regardless — the Table view row never had a leading checkbox to begin with; this was inherited from the now-removed Smart-list `TaskRow`, which did. Worth revisiting if bulk actions are wanted in Table view specifically.)

## Cross-view

- ~~**Visible/hidden customization per view.** Table view: column visibility toggle...~~ **Done 2026-07-19 for Table view** — right-click any header for show/hide + reorder, *and* (added in the same-named 2026-07-19 rework below) drag a header directly to reorder. Kanban view's column/cover-image settings are still open; Kanban's *card field* customization (which fields render on a card) is done as of the same date — see `../features/boards.md`.
- ~~**Remove the Grouped view.**~~ Moot — no Grouped view existed in the shipped code to remove.
- ~~**Remove the List view.**~~ **Done 2026-07-19** — the Smart list view (the app's only flat list view) was removed outright, not just renamed/hidden; see `../features/tasks.md`.
- **Consistent margins.** Still open.
- **Click-to-open-inspector rule, per view:**
  - Table view: clicking a row does **not** open the inspector. **Done 2026-07-19**, and taken further than originally asked — the entire view no longer has *any* path to the inspector (no double-click handler, no "Edit in inspector" context menu item), not just "clicking a row specifically."
  - Timeline view: clicking a bar **does** open the inspector for that task. Not reverified in this pass.
  - Kanban view: clicking a card **does** open the inspector for that task. Reverified 2026-07-19 via `TestKanbanCardDoubleClickOpensInspector`-style coverage in `desktop/tests/test_functional.py` (renamed from the old Smart-list-row test, which targeted the now-removed `TaskRow`).

## Reworked 2026-07-19 — Smart view removed, integrated into Dashboard; Table view Notion-style rework; tag management

See `../features/tasks.md`, `../features/dashboard.md`, `../features/boards.md`, and `../features/tags-and-linking.md` for the full writeups. Summary: the Smart list view is gone (its "Today"/"Overdue" role went to Dashboard, its other saved filters became a chip bar above Table view); progress is derived from status everywhere, not independently editable; Table view's status/priority/project render as colored pills with formatted labels, due dates render relatively, and columns can be drag-reordered; Kanban cards gained customizable field visibility; Settings → Tags gained a write-through merge action and tag-name autocomplete was wired into every tag-entry field.

## Why this matters

The current Table/Kanban/Timeline views were built to functional-but-generic spec (`PLAN_PHASE4.md`, `PLAN_PHASE5.md`) — these are refinements from actually using them, not new features.
