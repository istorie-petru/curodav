# Abandoned / out-of-scope

The record of what was deliberately cut or superseded and why — so it isn't
accidentally re-proposed without re-litigating the reasons. If you want to
revive anything here, write a focused plan with a trade-off table and argue from
evidence; this file won't be re-opened by default. Current, shipped behavior is
described in [`features/`](../features/README.md); open work is in
[`open.md`](open.md) (low priority) and [`open-priority.md`](open-priority.md)
(the rework).

## Versioning by phase

The app is versioned by the phases it has gone through, not by semantic
versioning:

- A `0.x` version (`0.1` … `0.9`) was a **development phase** — one stage of the
  build-up to the first release. Each minor bump started a new phase.
- An `x.0` version (`1.0`, `2.0`, …) is a **full release**: stable, supported,
  usable as an app. The current app is **1.0**, the first release.
- Minor releases within a major version are numbered `x.1` … `x.9` (`1.1` …
  `1.9`, then `2.1` … `2.9`, …). Each is a distinct feature release; the next
  full release, **2.0**, is reached once all roadmap work is implemented.

### Track record

- **0.1 — the original build.** Flutter `app/` + FastAPI `server/` (Postgres):
  calendar, tasks, contacts, schedule, and the rest of the core feature set in
  one client–server pair. Superseded 2026-07-17.
- **0.2 — the desktop replaces the pair.** The PySide6 `desktop/` becomes the
  single client, carrying the object model, HLC per-field merge, and design
  tokens ported forward from 0.1. The 2026-07-17 stress test runs against it
  (where global search is confirmed broken). Superseded by its successor.
- **0.3 — desktop consolidation.** The QML/QtQuick prototype tree is abandoned
  2026-07-19; boards, tasks, calendar, projects, and notes are matured, and the
  desktop-era feature docs (search, tags-and-linking, settings, sync-and-webdav)
  are written out. Superseded by the webapp.
- **0.4 — the webapp rises.** The FastAPI `webapp/` gains Kanban, subtasks, and
  checklists at explicit request (2026-07-31), built on the plain
  CalDAV/CardDAV model rather than desktop's object graph.
- **0.5 — projects/tags rework, phases 1–8** (2026-08-01): data layer + tag
  registry, projects as a nav destination, list→project linking, grouping and
  archiving, habit tracking, databases with formulas, and the widget dashboard.
- **0.6 — projects/tags rework, phases 9–11** (2026-08-01 → 2026-08-03): the
  task-view rework, month-view drag-to-create, and the Timeline/Gantt port
  complete the rework.
- **0.7 — label-space rework** (2026-08-03 → 2026-08-07): collections give way
  to the universal label model; the Material 3 style pass lands; Databases and
  Grades are removed; `desktop/` is deleted as the rework's final phase and the
  webapp becomes the sole client.
- **0.8 — webapp polish** (2026-08-07 → 2026-08-11): the UI/UX rework, updated
  colors, and the `features/` docs rewritten to describe the current webapp.
- **0.9 — release prep** (2026-08-11 → 2026-08-12): internals cleared, the
  roadmap prepared, and planning reorganized into `open.md` / `open-priority.md`.
- **1.0 — the first release** (2026-08-12 → present): the current webapp as the
  stable, supported, usable app.
- **1.1 — virtual & derived states** (2026-08-12 → 2026-08-13): Importance/
  Urgency replace WebDAV priority (two 1–3 axes over `tasks`, effective values
  derived in `src/derived_state.py`); `Today`/`Tomorrow`/`This Week`/`This
  Month`/`Overdue`/`Important`/`Urgent` are query projections over those values,
  not labels; one shared aggregation service feeds Dashboard and every filter;
  WebDAV `PRIORITY` carries the combined axes (import maps back to urgency
  only). Shipped: `open-priority.md` § Virtual & derived states removed.
- **1.2 — the task model decision** (2026-08-13 →): resolves the subtask
  hierarchy vs. flat-tasks-plus-allocations conflict as **flat tasks + work
  allocations** — subtasks are removed outright (the `tasks.parent_uid` column
  stays on disk, never written or read again; the subtask cascade deletes, "sub"
  tags, and iCal RELATED-TO subtask round-trip are gone; the Relations card
  holds related events only). 0.4's "subtasks" and the earlier "task hierarchy &
  contextual planning" decision are superseded. Shipped: `open-priority.md` §
  Subtask model — the open conflict resolved. (Side work: universal command
  surface.)

Open work in `open-priority.md` and `open.md` ships as the minor releases
`1.1` … `1.9` (see [`roadmap.md`](roadmap.md)); once all of it is implemented,
the next full release is **2.0**.

## The deleted desktop client (`desktop/`)

The whole PySide6 app — `desktop/src/`, its `tests/`, everything — the **0.2**
phase client — was deleted 2026-08-07 as the final phase of the label-space
rework (see `features/architecture.md`). `webapp/` (FastAPI) is the sole client.
Everything `desktop/`
cared about had already been moved onto `webapp/`'s model first, so it was a
pure subtraction, not a port. Before deleting, a dedicated audit checked every
`features/*.md` doc and found these capabilities were genuinely **dropped with
no prior record of it being deliberate** — all four confirmed accepted
2026-08-07 rather than rebuilt:

| Dropped capability | What desktop had | Decision |
|---|---|---|
| **File attachments** | content-addressed blob store | not rebuilt — webapp has nothing beyond contact photos |
| **Associative links/backlinks** | `blocks`/`references`/`mentions`/`related` graph + link picker + backlinks panel | not rebuilt — webapp only has curated event↔task relations |
| **WebDAV scope** | mounted/browsed the whole file tree | not rebuilt — webapp offers opt-in read-only Published Lists only |
| **Global search / command palette** | never worked even in desktop (verified broken in the 2026-07-17 stress test) | not a regression, not rebuilt — webapp has per-view search only |

**Also removed in the same rework's Phase 9:** generic **Databases**
(`databases`/`database_columns`/`database_rows`, `routers/databases.py`, the
"Data" tab) and the **Grades** tracker (`routers/grades.py`, `src/grades.py`,
`formula_engine.py`, the `grades` table) — your explicit choice over "keep
Grades, hide the generic feature."

**Earlier deleted codebases (for the record):** `app/` (Flutter/Dart) and
`server/` (FastAPI + Postgres) — the **0.1** phase — were replaced by
`desktop/` (the **0.2** phase) in 2026-07-17, and
`desktop/`'s own abandoned QML/QtQuick prototype tree was deleted 2026-07-19.
Their object model, HLC conflict logic, and design tokens were ported forward
before each deletion; nothing was lost that was still in use.

## Desktop-era feature docs

The old `features/*.md` docs (boards, tasks, calendar, projects, notes, roadmap,
search, tags-and-linking, settings, window-and-menu, sync-and-webdav,
design-system, data-and-attachments, calendar-rework-history, and the
stress-test/performance reports) described the deleted desktop app. They were
rewritten 2026-08-11 to describe the current webapp instead; the originals live
only in git history.

## Superseded plan documents (all deleted)

- `tasks-ux-rework.md`, `design-alignment.md`, `calendar-and-tasks-rework.md`,
  `apple-vs-google-calendar-plan.md` — desktop-era plans, superseded by the
  webapp rework.
- `spaces-home-pipeline.md`, `spaces-v2-university-material.md` — superseded by
  the label-space rework (the "project/space as a stored thing" model both
  proposed is exactly what the label model replaced).
- `label-space-rework.md`, `command-center-rework.md`, `modal-input-design.md`,
  `settings-rework.md`, `dashboard-usability-rework.md`,
  `webapp-action-pipelines-audit.md` — shipped plans; their outcomes are now
  described in [`features/`](../features/README.md).
- `projects.md`, `schedule.md` — folded into
  [`open-priority.md`](open-priority.md) 2026-08-12; the models both proposed
  (project-enabled labels + work allocations, generalized recurrence) are
  recorded there as open work, not shipped.
- `details.md` — folded into [`open-priority.md`](open-priority.md) 2026-08-12
  as the detailed spec for the project-enabled label stack and Schedule rework
  (project lifecycle, work-allocation semantics, recurrence exceptions,
  holiday calendars); its one low-priority piece (the optional project
  check-in) lives in [`open.md`](open.md).
- `expansion-deferred.md`, `systems/architecture.md`, `systems/decisions-log.md`
  — folded into this file below / the decision history.

## Decision history (what survives from the old logs)

### Architectural choices that still hold (from the original design passes)

- **Single-user is a load-bearing simplification.** No multi-user / sharing /
  teams / RBAC. Adding it would touch the data model, sync, and every feature.
- **SQLite as the query cache, disposable and rebuildable** — a preference/
  annotation store, not a source of truth.
- **Labels, not collections** — see `features/architecture.md` §1.2. This is
  the rework's core decision and is not up for reversal.
- **HLC per-field merge** (ported from the original HLC implementation): the
  conflict-resolution approach for the sync model.

### Deferred / out-of-scope systems (still not scheduled)

| Feature/system | Why deferred |
|---|---|
| Media tracker (TMDB / AniList / Steam) | Independent maintenance liability — external APIs churn, doesn't touch the core object model |
| Infrastructure dashboard (Proxmox / Docker / Uptime Kuma) | Server-side pollers, external API surface, no relation to the core app |
| Mobile app (Android/iOS) | Abandoned outright — a native client is a different UI layer, not a port. (DAVx5 sync against published lists is the planned mobile story — see `open.md`) |
| Multi-user / sharing / teams / RBAC | Single-user is load-bearing (above) |
| Real-time collaborative editing (CRDTs) | Not needed without multi-user; HLC/LWW merge is sufficient for one person on N devices |
| Push notifications (FCM/APNs) | No mobile client, no server |
| Public API | Nothing to expose one from |
| Budget tracking | Never speced past a name-check in the original module wishlist |
| Per-instance recurring-event exceptions | Needs an exception model that wasn't built (see `open.md` risks) |
| Dynamic M3 color (wallpaper-derived palettes) | Below cost for a single user |

## Standing rules this file enforces

- **No compatibility layer** — migrate and delete the superseded path.
- **Don't reintroduce collection partitioning** (`calendar_path`/`list_path`/
  `addressbook_path`-shaped columns on tasks/events/contacts).
- **Don't give a label a delete endpoint or a lifecycle.**
- **Don't grow the nav** — new screens attach to an existing tab or Settings' hub.
