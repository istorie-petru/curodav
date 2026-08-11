# Abandoned / out-of-scope

The record of what was deliberately cut or superseded and why — so it isn't
accidentally re-proposed without re-litigating the reasons. If you want to
revive anything here, write a focused plan with a trade-off table and argue from
evidence; this file won't be re-opened by default. Current, shipped behavior is
described in [`features/`](../features/README.md); open work is in
[`open.md`](open.md).

## The deleted desktop client (`desktop/`)

The whole PySide6 app — `desktop/src/`, its `tests/`, everything — was deleted
2026-08-07 as the final phase of the label-space rework (see `features/
architecture.md`). `webapp/` (FastAPI) is the sole client. Everything `desktop/`
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
`server/` (FastAPI + Postgres) were replaced by `desktop/` in 2026-07-17, and
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
