# Open work

The low-priority and app-local open work — features that don't reshape the
app's architecture or its presentation as a whole. The grand rework
(project-enabled labels, the Schedule/recurrence rework, virtual/derived states,
the new view surfaces, offline-first sync) lives in
[`open-priority.md`](open-priority.md); the single build order across both is in
[`roadmap.md`](roadmap.md). Shipped work lives in
[`features/`](../features/README.md); what's been deliberately cut lives in
[`abandoned.md`](abandoned.md).

**Version:** the app is at **1.2** (1.0 was the first full release; 1.1 —
Virtual & derived states — shipped 2026-08-13; 1.2 — the task model decision,
plus most of the Universal command surface as side work — shipped
2026-08-13). The items here ship as `1.2` … `1.9` minor releases and don't
block the rework in `open-priority.md`; the next full release is **2.0**.
Versioning scheme and phase history (0.1 → 1.0): [`abandoned.md`](abandoned.md);
release-by-release order: [`roadmap.md`](roadmap.md).

## Build order — how these land most optimally

The sections below are grouped by feature, not presented as one coherent plan.
This chapter proposes the dependency-driven order to implement them in. Each
step is sized to ship on its own; nothing here blocks the work in
[`open-priority.md`](open-priority.md) or vice versa.

1. **Configurable views + optional Schedule module** — settings-layer toggles
   over already-shipped views; pure UI/feature-state changes, cheap to verify
   because they must not touch data.
2. **Widget consolidation + Streak + Next Deadline** — dashboard-local; a single
   `app_meta`-guarded migration.
3. ~~**Data health & maintenance**~~ — **shipped 2026-08-14** (Settings > Data
   health, `src/data_health.py`, `scripts/data_health.py`) — see
   `features/settings.md`. Unblocks 1.8 (offline-first editing &
   synchronization)'s "trusted only once verified backups exist" precondition.
4. **Contacts field parity** — isolated to the Contacts entity and its vCard
   round-trip.
5. **Webapp usability + DAVx5 hosting** — Phase B (pagination) is app-wide UI
   polish; Phase C is pure infra and blocked on a domain + server.
6. **Project check-in (optional)** — a lightweight, app-local addition to the
   project stack; ships whenever, without blocking the rework.
7. **Command palette actions (optional follow-up)** — see below; small,
   self-contained, no model changes.
8. **Retire the standalone `/projects` page** — presentation-only, no model
   changes; small and self-contained, see below.

## Command palette actions (optional follow-up)

**Status:** decision recorded — no code. The Universal command surface's
query layer, HTTP API, global search/navigation, and the Relations-card
picker all shipped as 1.2 side work — see `features/tasks.md` § Search & the
command surface for what exists (`db.search_entities`, `GET /api/search`,
`/search`, Ctrl-K/Cmd-K, `static/command_palette.js`). What's described here
is only the piece that didn't ship: turning the overlay from search-and-
navigate into an actual **command** palette.

Today picking a result opens it; nothing else. This item would add
context-dependent commands/actions on top of the same overlay and query
layer — opening entities is already covered, so the new surface is
creation, assigning labels, completing tasks, and deleting entities where
appropriate, each scoped to what makes sense for the result's type.
Destructive actions require confirmation the same way other destructive
actions in the app do (`data-confirm-sheet`, see static/modal.js). This is
additive to the shipped overlay, not a rework of it — the query layer,
`/api/search`, and the Relations-picker wiring are unaffected either way.

## Configurable views & optional Schedule module

**Status:** decisions recorded — no code. Settings-layer toggles; must not touch
data.

### Configurable views

Settings allow enabling/disabling the available views per major module —
Calendar: Month / 4-Week / Week / Day; Tasks: Table / Board / Timeline. Disabled
views disappear from the relevant navigation and view switchers but must not
delete data or alter the underlying model; re-enabling restores access.
Deliberately simple — not a general-purpose UI customization system.

### Optional Schedule module

Scheduling is independently enableable/disableable in Settings. Disabling hides
scheduling-specific UI and functionality but must not delete existing scheduled
work sessions, associated calendar events, configuration, or label behavior. All
scheduling configuration persists while disabled so re-enabling restores the
previous state. Disabling a module is a UI/feature-state change, not a
destructive data operation. (The Schedule module itself is being reworked in
`open-priority.md`; this toggle applies to whatever form it takes.)

## Project check-in (optional)

**Status:** decision recorded — no code. A small, optional addition to the
project stack in `open-priority.md`; it ships whenever and never blocks the
rework.

Projects can optionally support a lightweight **check-in** mechanism. A check-in
lets the user review the state of an active project without treating the
check-in as a task. The exact workflow stays deliberately lightweight and must
not introduce another hierarchy of objects — it is a review action on a project,
not a new entity type.

## Retire the standalone `/projects` page (and its two child views)

**Status:** decision recorded — no code. Scoped 2026-08-15, direct feedback
("the projects page and pages derived from it... are not worth existing").
**Presentation-only** — confirmed explicitly with the user: nothing about
the label/project data model, the Settings > Labels admin page, or the
`promote`/`set_dates`/`demote`/`archive` endpoints changes. This removes
only the dedicated pages built to *view* a project; the backend and every
other project feature (Settings > Labels, the label-config `is_project`
lifecycle, work allocations) stay exactly as they are.

**What goes away:**
- `GET /projects` (`routers/projects.py::list_projects`, `templates/
  projects.html`'s square cards) — the project listing page.
- `GET /projects/{name}` and its two tabs — Tasks view and Week Calendar
  view (`routers/projects.py::project_detail`/`project_calendar`,
  `templates/project_detail.html`/`project_calendar.html`). Both are
  redundant with capability that already exists elsewhere: the Tasks view
  duplicates `/tasks?group_by=project` (1.5, already shipped); the Week
  Calendar view duplicates the merged `/calendar/week` grid (2026-08-14
  side work) filtered to one project, which already shows every work
  allocation regardless of project — the same "third copy of the same
  thing" reasoning that retired the standalone `/week` page.

**What stays untouched:** every label/project field and endpoint in
`routers/projects.py`/`db.py` (`promote`, `set_dates`, `demote`, `archive`,
`project_status`, `find_overlapping_project`), Settings > Labels
(`routers/labels.py`, `labels_manage.html`/`label_edit_modal.html`), and
the Dashboard `project_preview` widget (repointed, not removed — below).

**What removing the pages cleanly requires:**
- `base.html`'s tabbar "Projects" entry (`href="/projects"`) dropped —
  same treatment as the `/today`/`/week` tabbar entries.
- `_widget_project_preview.html`'s per-project row link changes from
  `/labels/{name}` to `/tasks?label={name}` (plain filtered Table view, no
  `group_by` — confirmed with the user: grouping is meaningless once
  already filtered to a single label).
- `dashboard.py`'s `quick_links` widget (currently links each project tile
  to `/projects/{name}`) repointed to the same `/tasks?label={name}`
  target, for consistency between the two Dashboard project surfaces.
- `GET /projects` and `GET /projects/{name}` become redirects, not 404s —
  same "any bookmark still lands somewhere real" precedent already used
  for `/today`, `/week`, and `/calendar/timetable`'s own retirements:
  `/projects` -> `/tasks?group_by=project`, `/projects/{name}` ->
  `/tasks?label={name}`.
- `tests/test_project_detail.py` and `tests/test_project_calendar.py`
  deleted (nothing left for their page-content assertions to cover);
  `tests/test_project_stack.py` needs no changes — already router-level
  only, never asserts on `/projects` specifically.

**Not decided yet, flag before implementing:** whether `_task_row.html`'s
project-scoped extraction (pulled out for the project detail Tasks view,
1.4 slice 2) is still worth keeping as a shared macro once its only other
caller is the global Tasks page, or should just be inlined there again.

## Widget consolidation + Streak + Next Deadline

**Status:** Design only, waiting on your go-ahead. 11 widget types → 8:
`at_a_glance` unchanged; `today_agenda`/`weekly_overview`/`upcoming_events`/
`overdue_tasks` → one configurable **Agenda** (Range + Show toggles);
`project_preview`/`filled_cards` → one **Spaces & Projects** (List/Cards style
toggle); `calendar_agenda` cut (reproducible by placing Mini Calendar next to
Agenda); **Streak** and **Next Deadline** are new. One migration
(`app_meta`-guarded, rewrites existing rows in place, nothing lost).
**Already shipped ahead of the rest:** `tasks.completed_at`
(auto-managed in `db.upsert_task`, `test_task_completed_at.py`) — the schema
change the Streak widget reads.

## Contacts field parity with Nextcloud Contacts

**Status:** Planning only — no code written. A full design exists; three of the
target fields are already covered by labels and two should be deliberately
skipped (Address book and Archive — straight reversals of the label model).
Real scope when it starts: Title, multi-value Phone/Email, structured multi-value
Address, Birthday, multi-value Website, and Social network (the last one has a
portability question to settle first — `X-SOCIALPROFILE` vs. app-only).
Five open questions need your call before implementation (type vocabulary,
data migration, address-form UX, date types, social vCard property).
**Build order when green-lit:** Title → Phone/Email → Website → Birthday →
Address → Social network, each a full slice (schema → vCard round-trip →
form/detail/list UI → its own test file).

## Webapp usability + DAVx5 mobile hosting

**Status:** Phase A shipped. Two genuinely open pieces:

- **Pagination / collapsible sections** (Phase B): no `?page=`/`?limit=`
  convention or pager partial exists; the Tasks table is the highest-traffic
  target, then Schedule/etc. Live-volume verification required, not just
  "the template renders."
- **DAVx5 mobile access** (Phase C): a phone running DAVx5 syncs CalDAV/CardDAV
  against Radicale through a public HTTPS reverse proxy (Caddy) with real bcrypt
  auth — pure infra (a `deploy/` directory: Caddyfile, firewall rules, prod
  Radicale config), no app code. Requires a domain + server before this can be
  acted on.

(The Phase B "add a Databases section to project pages" item is superseded —
Databases were removed; see `abandoned.md`.)

## Known open risks

Model- and architecture-level risks are tracked in
[`open-priority.md`](open-priority.md). Nothing in this file currently carries a
known open risk beyond the blockers noted inline: Contacts field parity's five
open questions and the `X-SOCIALPROFILE` portability question, and DAVx5's
domain + server requirement.

---

## How open work gets tracked

A focused plan starts its life as a section here. When you give it a go-ahead,
expand it into a full phase spec (acceptance line, concrete slices); when it
ships, describe the outcome in [`features/`](../features/README.md) and remove
the section from this file.
