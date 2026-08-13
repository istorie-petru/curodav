# Open work

The low-priority and app-local open work — features that don't reshape the
app's architecture or its presentation as a whole. The grand rework
(project-enabled labels, the Schedule/recurrence rework, virtual/derived states,
the new view surfaces, offline-first sync) lives in
[`open-priority.md`](open-priority.md); the single build order across both is in
[`roadmap.md`](roadmap.md). Shipped work lives in
[`features/`](../features/README.md); what's been deliberately cut lives in
[`abandoned.md`](abandoned.md).

**Version:** the app is at **1.1** (1.0 was the first full release; 1.1 —
Virtual & derived states — shipped 2026-08-13). The
items here ship as `1.2` … `1.9` minor releases and don't block the rework in
`open-priority.md`; the next full release is **2.0**. Versioning scheme and
phase history (0.1 → 1.0): [`abandoned.md`](abandoned.md); release-by-release
order: [`roadmap.md`](roadmap.md).

## Build order — how these land most optimally

The sections below are grouped by feature, not presented as one coherent plan.
This chapter proposes the dependency-driven order to implement them in. Each
step is sized to ship on its own; nothing here blocks the work in
[`open-priority.md`](open-priority.md) or vice versa.

1. **Universal command surface** — self-contained; one shared search / picker /
   command palette. Absorbs the previously scoped global-search plan. No model
   changes.
2. **Configurable views + optional Schedule module** — settings-layer toggles
   over already-shipped views; pure UI/feature-state changes, cheap to verify
   because they must not touch data.
3. **Widget consolidation + Streak + Next Deadline** — dashboard-local; a single
   `app_meta`-guarded migration.
4. **Data health & maintenance** — independent and low-risk; scheduled early
   because verified backups are the prerequisite for trusting the offline/sync
   work in `open-priority.md`.
5. **Contacts field parity** — isolated to the Contacts entity and its vCard
   round-trip.
6. **Webapp usability + DAVx5 hosting** — Phase B (pagination) is app-wide UI
   polish; Phase C is pure infra and blocked on a domain + server.
7. **Project check-in (optional)** — a lightweight, app-local addition to the
   project stack; ships whenever, without blocking the rework.

## Universal command surface (global search / picker / command palette)

Absorbs the earlier scoped plan for "global search / picker across tasks,
events, and contacts." Search and the Command Palette share one interaction
component rather than being two unrelated interfaces.

**Status:** picker plan scoped (build order below); the command-surface decision
extends it. Not started — no code.

### The shared component

One searchable **picker / command surface** that finds a task, event, or contact
by name — plus working filters — usable anywhere you currently pick "one of
everything" from a flat `<select>`. Today those pickers don't scale: the
Relations card's "link an existing event/task" row renders a single dropdown of
every not-yet-linked item sharing a label (`_task_relations.html` /
`_event_relations.html`, backed by `list_events_sharing_labels` /
`list_tasks_sharing_labels`). Fine at small volume; unusable once the pools
grow.

The component supports different **invocation modes and contexts**: global
search, navigation, creation, entity selection, and actions. `Ctrl+K` opens the
command palette; invoking the same component from a relation selector puts it
into entity-selection mode. Available commands and actions depend on the current
context: navigation, creation, opening entities, assigning labels, completing
tasks, deleting entities where appropriate, and other safe application actions.
Destructive actions require appropriate confirmation where necessary.

### Filters

**Explicit** (user-controllable, AND together):
- free-text search on title/name;
- type filter (tasks / events / contacts / any);
- label filter (multi-select, the app's shared label vocabulary);
- tasks: status, due date; events: date range; contacts: nothing extra.

**Implicit** (applied automatically by the caller, shown as badges so the user
knows why the list is narrowed):
- *shared-label rule* — when used as the relation picker on a task or event,
  candidates are pre-filtered to items carrying ≥1 label in common with the
  source (the exact rule `_shares_label` enforces today);
- *not-already-linked* — already-linked items are excluded;
- *type* — when launched from a task's Relations card it can only pick events
  (and vice versa), so the type filter is pre-set;
- *context scoping* — e.g. a widget or label page can open the picker
  pre-scoped to its label.

### Search scope and indexing

Global search is fuzzy and operates across the application's meaningful indexed
metadata — titles, descriptions, labels, contacts, and other searchable fields.
Search indexing is designed explicitly rather than indexing arbitrary internal
database fields.

### Why it matters for relations

It replaces the two one-way `<select>`s with one shared component and makes
"link both ways" (task↔event) practical at real data volumes. It also unlocks
the global search / command palette (Ctrl-K), and could back the per-view search
boxes in Tasks/Contacts/Schedule with a single query layer instead of each
view's own `q=` handling.

### Build order when green-lit

1. Query layer: one `search_entities` (or `picker_candidates`) function with the
   filter vocabulary above, plus tests per filter combination.
2. Reusable picker UI: modal with search box + filter dropdowns + result list,
   `data-modal-keep-open` compatible so it can replace the current relations
   add-row.
3. Wire into Relations both ways (task→event and event→task), keeping the
   implicit shared-label + not-already-linked filters and the defensive
   `_shares_label` re-check on submit.
4. Standalone search entry point (a `/search` page or Ctrl-K) across all three
   types with the same filters.
5. Command palette on the same component: context-dependent commands/actions,
   fuzzy matching, destructive-action confirmation.
6. Remove the now-dead `linkable_*` `<select>` pools from
   `_task_relations.html` / `_event_relations.html`.

**Not in scope:** a search engine / indexing service as an external system;
indexing arbitrary internal database fields (only the meaningful metadata listed
above is indexed). Note: the earlier picker plan excluded fuzzy matching and
description/note search (title-only); the command-surface decision explicitly
adds fuzzy matching over titles, descriptions, labels, and contacts, so that
exclusion is superseded.

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

## Data health & maintenance

**Status:** decision recorded — no code.

Settings contains a **Data Health** section exposing the operational state of
the data layer: database integrity/status; last successful backup; last backup
verification; synchronization status and last sync time for connected
endpoints/devices; storage usage; relevant entity statistics.

Backups are **actively verified**, not merely created. Verification at minimum
validates JSON structure, expected top-level data, required entity collections,
and basic data integrity.

Provide both **GUI and CLI** workflows for creating backups, verifying backups,
restoring backups, checking database integrity, and performing supported repair
operations. GUI and CLI use the same underlying maintenance services rather than
separate logic. Restore operations clearly communicate their destructive
implications and preserve a recoverable backup of the current state where
practical.

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
