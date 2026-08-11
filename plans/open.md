# Open work

Everything that's been scoped but not yet shipped, plus known open risks.
Shipped work lives in [`features/`](../features/README.md); what's been
deliberately cut lives in [`abandoned.md`](abandoned.md).

## Build order — how these land most optimally

The sections below are grouped by feature, not presented as one coherent plan.
This chapter proposes the dependency-driven order to implement them in. Each
step is sized to ship on its own. The already-scoped items (Contacts field
parity, Widget consolidation, DAVx5 hosting) are largely independent and can run
in parallel with the steps here.

1. **Virtual & derived states** — the virtual-state model (temporal states are
   not labels), the shared aggregation service, and Importance/Urgency. Every
   other surface reads their output: without this, Today, Week, Dashboard, and
   the system filters each re-implement the same math. It must also settle the
   WebDAV representation of importance/urgency here, because it replaces the
   current priority field and anything sync-related builds on it.
2. **Information architecture & view surfaces** — Dashboard (orientation),
   Today (execution), Week (planning), Spaces (context), unchanged core views.
   Built on step 1; each view becomes a projection of shared data rather than a
   new data model.
3. **Configurable views + optional Schedule module** — settings-layer toggles
   over already-shipped views. Pure UI/feature-state changes, cheap to verify
   because they must not touch data.
4. **Universal command surface** — self-contained: one shared search / picker /
   command palette. Absorbs the previously scoped global-search plan.
5. **Task hierarchy & subtask scheduling** — one open decision has to be settled
   first (the subtask model vs. `projects.md`, flagged in its section); then the
   lightweight-subtask workflow and calendar work sessions build on the shipped
   subtask/relations support.
6. **Data health & maintenance** — independent and low-risk; scheduled early
   because verified backups are the prerequisite for trusting the offline/sync
   work that follows.
7. **Offline-first editing & synchronization** — the largest and most
   design-heavy item. Its sync model (identifiers, tombstones, conflict
   resolution, and how importance/urgency and work sessions map to WebDAV) must
   be written before any code. Can start in parallel with steps 3–6 once step
   1's WebDAV mapping is fixed.

## Information architecture & view surfaces

The application deliberately distributes information across views according to
the question each view answers, rather than letting the Dashboard become a
container for every feature. Major surfaces have distinct purposes — Dashboard
for orientation, Today for execution, Week for planning, Spaces for context, and
Calendar/Tasks/Contacts for direct management. Views are projections of shared
entity data, not independent representations with duplicated state.

**Status:** decisions recorded — no code. Surfaces build on the aggregation
service (see "Virtual & derived states").

### Dashboard — orientation

Answers **"What's happening in my life?"** A concise overview of the current
situation aggregated from existing entities and system states — not a second
management interface. Widgets prioritize current and upcoming information,
important/urgent items, and high-level workload over exposing every feature at
once.

### Today — execution

Answers **"What am I dealing with now?"** An operational view of the current
day combining today's calendar events, scheduled task work, due/overdue tasks,
important upcoming items, and relevant workload. Generated from existing data —
no separate Today data model.

### Week — planning

Answers **"How should I allocate my time over the coming week?"** Shows calendar
commitments together with schedulable task/subtask work, due dates, remaining
estimated effort, and available time. Unscheduled work is visible and draggable
onto available calendar intervals. A planning surface, not merely another
calendar layout.

### Spaces — context

Answers **"What belongs to this area of my life?"** Spaces remain contextual
projections generated from labels and extended by specialized modules — not a
manually maintained folder hierarchy. A University Space exposes generic
calendar/task/contact functionality while the University module adds courses,
schedule, professors, credits, and assignments.

### Core management views

Calendar, Tasks, and Contacts stay the direct management interfaces for their
entity types: Calendar manages temporal occurrences, Tasks manages desired
outcomes and their state, Contacts manages people. Other surfaces provide
contextual projections of these entities rather than duplicating their
management logic.

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
destructive data operation.

## Virtual & derived states

Three related decisions consolidated into one model: temporal/state views are
not labels, one shared service computes them, and Importance/Urgency are the two
semantic properties that feed the `Important` / `Urgent` states.

**Status:** decisions recorded — no code. This is step 1 of the build order.

### System-derived views and virtual states (not labels)

The application distinguishes user-created labels (manually assigned and managed
by the user), behavioral system rules (configurable system features that affect
behavior, e.g. Habit, Schedule), and derived system views. Temporal/state
concepts — `Today`, `Tomorrow`, `This Week`, `This Month`, `Overdue`, `Urgent`,
`Important` — are **not labels** in the data model or the UI label system. They
are **virtual views / filters / navigation states** presenting dynamically
computed subsets. They may be exposed the same way labels are (selectable chips,
sidebar entries, quick filters), but they are query-driven projections, not
assignable metadata. An entity appears in `Today` because its date falls within
today's range, not because it was tagged. No duplicated state; no polluting the
label system with derived information.

### Derived-state and aggregation service

A shared application service calculates the temporal and planning aggregates
multiple views use: task counts by state; completed / remaining / overdue work;
estimated and scheduled task effort; calendar occupied / free time; conflicts;
upcoming important or urgent entities. It feeds the Dashboard, Today, Week,
Spaces, and the system filters rather than each page re-implementing the math.
Values are normally calculated from source data; stored as persistent fields
only if profiling demonstrates a genuine performance requirement. The resulting
system states (`Today`, `This Week`, `Overdue`, `Important`, `Urgent`) are
therefore virtual / derived in the UI.

### Importance and urgency (replacing WebDAV priority)

`Importance` and `Urgency` are explicit semantic properties that replace the
existing WebDAV priority concept. They are system-level properties, not ordinary
labels stored on entities; their resulting states surface through virtual system
labels `Important` and `Urgent`. Labels can contribute rules: the `Exam` label
may imply high importance; the `Conference` label may imply urgency when the
event is within a configurable threshold (e.g. one week or one month). The
resulting value is derived from all applicable sources — explicit user
configuration, label-based rules, temporal state — using deterministic
precedence rather than physically created chains of labels, e.g.
`effective importance = max(explicit importance, label-derived importance)`.
Represented consistently in WebDAV synchronization rather than a separate
incompatible priority model.

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

## Task hierarchy & subtask scheduling

**Status:** decisions recorded — no code. One model conflict must be resolved
before implementation (see below).

### Task hierarchy and contextual planning

Intended workflow: create a task such as `Finish Paper XYZ`, classify it with
labels such as `University` and `Historiography`, and break it into lightweight
subtasks such as `Research`, `Introduction`, `Body`, `Abstract`, `Cleanup`.
Subtasks must be significantly easier to create and manipulate than the current
task workflow — inline creation, keyboard/mouse-friendly ordering, completion,
editing. The parent task represents the overall outcome; subtasks represent
concrete units of work. The hierarchy stays lightweight — a subtask does not
need to carry the full configuration of an independent task.

### Task work sessions and subtask scheduling

A task and each of its subtasks is independently schedulable through associated
calendar work sessions. A parent task does not need its own work session if its
actual work is represented entirely by scheduled subtasks. `Finish Paper XYZ`
may contain `Research` / `Introduction` / `Body` / `Abstract` / `Cleanup`, each
with one or multiple work sessions; the parent reports total estimated,
scheduled, completed, and remaining work by aggregating its descendants. A
simpler task such as `Finish Historiography Homework 1` can itself have a work
session without subtasks. The fundamental schedulable unit is therefore **work
required by a task**, not necessarily the parent task. Work sessions are
represented as associated calendar events, so they participate in the calendar,
free-time calculation, conflict detection, and the Week planning view.

**Open conflict — resolve before implementation:** this restores a subtask
hierarchy, but `projects.md` — the current planning model — explicitly proposes
*removing* subtasks ("the existing task hierarchy should therefore be simplified
by removing subtasks") and representing scheduled work with calendar work
allocations on flat tasks. The two agree that scheduled work is a calendar event
linked to a task (a work allocation in `projects.md`, a work session here), but
the subtask-parent aggregation is a direct reversal. The shipped app already has
real subtasks (`parent_uid`), so this is a keep-and-strengthen vs. remove call
on a shipped feature. Pick one model before coding.

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

## Offline-first editing & synchronization

**Status:** decision recorded — no code. The sync model must be written before
implementation (see below).

The application supports opening existing locally available data and
creating/editing entities while offline. Local changes are persisted reliably
and queued for synchronization. When connectivity returns, the sync system
detects the connection, begins synchronization automatically, processes pending
changes, and communicates the result to the user.

The UI provides clear **non-blocking status notifications** for entering offline
mode, reconnecting, synchronization in progress, successful synchronization, and
synchronization failure.

**Before implementation, the synchronization model must explicitly define:**
entity identifiers, local change tracking, ordering, deletion/tombstones,
retries, idempotency, conflict detection, and conflict resolution. A "last write
wins" policy should not be adopted casually because it can silently destroy
offline changes. Offline UI notifications are straightforward; reliable
conflict-safe synchronization is the underlying engineering requirement. Prior
art to draw on: the HLC per-field merge decision preserved in `abandoned.md`.

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

- **Subtask-model conflict**: restoring subtasks (see "Task hierarchy & subtask
  scheduling") reverses `projects.md`'s remove-subtasks model; pick one before
  implementation.
- **`project_label_for` heuristic** (`db.py`): a schedule class/habit picks
  "the project" as whichever attached label isn't a Space, chosen alphabetically
  when more than one non-Space label qualifies. Low risk at current usage; flag
  a decision if it ever needs to be relied on at higher stakes.
- **Recurring-event single-occurrence editing**: recurrence expands a master
  RRULE; editing one occurrence vs. the whole series needs an exception model
  that hasn't been built.

---

## How open work gets tracked

A focused plan starts its life as a section here. When you give it a go-ahead,
expand it into a full phase spec (acceptance line, concrete slices); when it
ships, describe the outcome in [`features/`](../features/README.md) and remove
the section from this file.
