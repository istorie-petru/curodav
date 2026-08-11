# System decisions log

**Purpose:** the record of *why* the system is shaped the way it is — condensed from the original `REWORK_PLAN.md` (2026-07-15), which specified moving the app from Flutter + FastAPI + Postgres to PySide6 + file tree + Syncthing/WebDAV. That rework was fully implemented and later superseded in turn: `desktop/` (the PySide6 app) was deleted 2026-08-07 as the final phase of [`../label-space-rework.md`](../label-space-rework.md), leaving `webapp/` as the sole client. This file is the historical/rationale record, not a live spec — [`architecture.md`](architecture.md) (this folder) is the historical architecture doc for the now-deleted `desktop/`; for the *current* design, see [`../../architecture.md`](../../architecture.md) (root, describes `webapp/`); for current features, see [`../../features/`](../../features/README.md) (marked historical/superseded, per that folder's own README).

## Core decisions (2026-07-15)

| Decision | Choice | Rationale |
|---|---|---|
| Language | Python (PySide6) | Server was already Python; single-language project halves context-switching |
| Qt API | Qt Widgets | Keyboard-heavy desktop UI; closer to Flutter's imperative patterns |
| Source of truth | File tree (`~/CommandCenter/objects/...`) | Enables WebDAV + P2P without a custom protocol |
| Query cache | SQLite (`aiosqlite`) | Populated incrementally via file watcher; disposable, rebuildable |
| P2P sync | Syncthing (optional) | Mature, encrypted, mesh discovery, NAT traversal — zero protocol code |
| WebDAV server | Embedded `wsgidav` | Serves the file tree; toggled in Settings |
| File watching | `watchdog` (inotify/FSEvents) | Keeps the SQLite cache in sync with file changes |
| Merge | HLC per-field (existing ~40-line impl) | Applied on file read when Syncthing conflict files exist |

## Closed decisions

1. **Syncthing:** optional. App runs fully without it; toggled in Settings.
2. **SQLite:** incremental-only, populated by watchdog. No full rebuild on every start. Reindex button in Settings if the cache drifts.
3. **WebDAV:** controllable from Settings (on/off, port, LAN-only toggle, off by default).
4. **Mobile:** abandoned, not deferred. Desktop only (Linux primary, Windows/macOS secondary). See [`../expansion-deferred.md`](../expansion-deferred.md).
5. **Syncthing auto-launch:** the app can launch Syncthing as a subprocess when the P2P toggle is on.

## What happened to the pre-rework code

| Codebase | Fate |
|---|---|
| `server/` (FastAPI + Postgres) | Its data model and HLC logic were ported into the PySide6 app before the folder was deleted (2026-07-17); no longer kept as reference. |
| `app/` (Flutter/Dart) | Fully replaced by the PySide6 app; the sync/core layer logic was ported to Python first, then the folder was deleted (2026-07-17). |
| `dashboard.html`, `identity-mockup-v3.html` (HTML mockups) | Superseded by the OKLCH design tokens implemented directly in `desktop/src/core/design/`; deleted 2026-07-17. |
| Object model | Preserved — same types, statuses, relationships, just serialized to files instead of SQL rows. |
| HLC implementation | Ported — same ~40-line algorithm, Python instead of Dart. |
| Design tokens (OKLCH values) | Ported — same colors, QSS instead of Dart/CSS. |

The original plan had called for keeping `server/` and `dashboard.html` around as reference material. In practice the relevant logic and values were already carried over, so keeping the old files added disk weight (`app/` alone was ~639MB) without ongoing value — all three were deleted once the port was verified complete.

**`desktop/` itself (2026-08-07):** deleted whole — the PySide6 app, its own `tests/`, everything under it — as Phase 8 (the final phase) of [`../label-space-rework.md`](../label-space-rework.md), on the same "delete over extend, no archive branch" precedent already used above for `app/`/`server/`. `webapp/` (FastAPI) is now the sole client; the label-space rework had already moved every data concept `desktop/` cared about (tasks/events/contacts, tags→labels, projects/spaces→labels) onto `webapp/`'s own model over Phases 1–7, so this was a pure subtraction, not a port. A dedicated pre-deletion audit (`label-space-rework.md` Phase 8, "Pre-deletion audit") checked all 12 live `features/*.md` docs first and found two capabilities genuinely dropped with no prior record of that being deliberate — **file attachments** (desktop's content-addressed blob store) and **associative links/backlinks** (desktop's `blocks`/`references`/`mentions`/`related` graph; webapp only kept structural parent/child for subtasks) — plus two narrower-by-design differences flagged for an explicit decision — **WebDAV scope** (desktop mounted/browsed the whole file tree; webapp only offers opt-in read-only published Lists, see Phase 6) and **global search/command palette** (never worked in either app, not a regression). All four were confirmed accepted 2026-08-07 rather than rebuilt — see `label-space-rework.md`'s Phase 8 section for the full audit; not repeated here.

**`desktop/src/qml/` + `models/qml_bridge.py` (2026-07-19):** a separate, unrelated dead-code find, not part of the original rework. A `QQuickWidget`-based bridge (`qml_bridge.py`) and three substantial QML files (`TaskTableView.qml`, `KanbanView.qml`, `CalendarView.qml` — full reimplementations of the Tasks table, Kanban board, and Calendar, not stubs) existed as an apparently abandoned prototype toward a QtQuick-based UI. Confirmed via codebase-wide search that nothing ever imports or instantiates `QmlModuleWidget` — the running app is 100% Qt Widgets and always has been; the QML tree rendered nothing. Deleted rather than wired up or kept as reference, per the same reasoning as the `app/`/`server/` deletions above: two parallel UI implementations of the same views is a maintenance liability, not an asset, and Qt Widgets is the architecture actually documented and tested. See `../design-alignment.md` (deleted 2026-08-11) for the design-reference comparison that prompted the audit that found this.

## Delivery history

Built in the order below; all phases are complete as of 2026-07-17 (see `../../features/` for what each delivered):

1. **Foundation** — file tree schema, `FileRepository`, SQLite index + watchdog, app shell, design tokens, command palette skeleton.
2. **Modules** — Dashboard, Tasks, Calendar, Notes, Kanban (first pass, local-only).
3. **WebDAV + P2P** — embedded WebDAV, Syncthing REST client, HLC conflict resolution on read, sync status UI, full Settings.
4. **Depth** — Roadmap/Goals, Activity feed, Attachments, system tray, notifications, theme settings, import/export.
5. **Interaction hardening** (an additional pass beyond the original 4 phases, tracked as its own set of documents at the time — "PLAN_PHASE1" through "PLAN_PHASE8") — wired the SQLite cache and quick-add to actually persist, added the object inspector panel, tag UI and filtering, kanban drag-and-drop and link management, task table/timeline/checklist/subtask views, project detail views and responsive nav, notes depth (list, daily notes, backlinks, search highlighting), and a test suite (`desktop/tests/`).

Known open work from actually using the finished app is tracked separately in `../tasks-ux-rework.md` (deleted 2026-08-11 — superseded by the webapp rework; no longer active).
