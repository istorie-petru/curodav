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

**Reprioritized 2026-08-15** (direct steer, supersedes the old ordering
below the line): ~~Command palette actions~~ **shipped 2026-08-15** (see
`features/tasks.md` § Search & the command surface), then the expanded
Dashboard widgets work (next up now), then the small Tasks-filter cleanup and
Event format items (both small, no particular urgency, slot in wherever
convenient), then Contacts field parity, then Project check-in, then Modal
window uniformization. Configurable views + optional Schedule module and
Webapp usability's remaining pieces (collapsible sections, DAVx5 — see
`roadmap.md`'s 1.9 row) weren't mentioned in the reprioritization and stay
parked at the back of the queue.

1. ~~**Command palette actions**~~ — **shipped 2026-08-15**, see
   `features/tasks.md` § Search & the command surface.
2. **Dashboard widgets: new widgets + real customization** — see "Widget
   consolidation + Streak + Next Deadline, expanded scope" below. **Next up
   now.**
3. **Tasks page filter cleanup** (small) — see below.
4. **Event format for simple events** (small) — see below.
5. **Contacts field parity** — isolated to the Contacts entity and its vCard
   round-trip.
6. **Project check-in (optional)** — a lightweight, app-local addition to the
   project stack; ships whenever, without blocking the rework.
7. **Modal window uniformization** — see below. Cuts across every entity's
   create/edit modal, so it's last: touching it early would mean redoing the
   touch-up on every modal the items above this one still need to add or
   change.
8. **Configurable views + optional Schedule module** — settings-layer toggles
   over already-shipped views; pure UI/feature-state changes, cheap to verify
   because they must not touch data. Not part of the 2026-08-15
   reprioritization; stays available whenever a session wants a break from
   the above.
9. ~~**Data health & maintenance**~~ — **shipped 2026-08-14** (Settings > Data
   health, `src/data_health.py`, `scripts/data_health.py`) — see
   `features/settings.md`. Unblocked 1.8 (offline-first editing &
   synchronization)'s "trusted only once verified backups exist" precondition.
10. **Webapp usability + DAVx5 hosting** — Phase B's pagination piece
    ~~shipped 2026-08-15~~ (see `features/tasks.md` § Views); collapsible
    sections and Phase C (DAVx5, blocked on domain + server) are what's left,
    neither part of the 2026-08-15 reprioritization.

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

## Widget consolidation, expanded scope (2026-08-15)

**Status:** the original consolidation design shipped 2026-08-15 (side
work, same day as this reprioritization) — 11 widget types → 8 (now 11
counting the pre-existing 1.9-side-work additions untouched by this pass):
`at_a_glance`/`mini_month_calendar`/`habit_checkin`/`contact_list`
unchanged; `today_agenda`/`weekly_overview`/`upcoming_events`/
`overdue_tasks` → one configurable **Agenda** (`config["range"]`/
`config["show"]`); `project_preview`/`filled_cards` → one **Spaces &
Projects** (`config["style"]`, List/Cards); `calendar_agenda` cut
(reproducible by placing Mini Calendar next to Agenda); **Streak** and
**Next Deadline** are new. One `app_meta`-guarded migration
(`_migrate_widget_consolidation`) rewrote every existing dashboard's
widget rows in place, nothing lost (one visual trade-off: every migrated
Agenda widget now renders at Agenda's single "half" default width — see
`features/dashboard.md`'s own Migration section for the full detail).
See `features/dashboard.md`.

Still open, not yet scoped into concrete slices — the three items added
2026-08-15 by direct feedback, after the original design above:

- **Project/Space links widget.** The consolidated **Spaces & Projects**
  widget above already covers "a widget listing projects/spaces" on the
  global Dashboard; what's new here is making the same widget type
  placeable on a *Space's own* dashboard (not just the global one),
  scoped to that Space's children (its projects, or its sub-Spaces) rather
  than everything. Needs a design pass on what "available on any Space"
  means concretely — likely a widget-instance-level scope setting
  (this Space's children vs. everything), not a second widget type.
- **"What needs organizing today" action widget.** A new widget type,
  distinct from Agenda (Agenda lists what's scheduled; this one surfaces
  what *isn't* yet and needs a decision) — pulls together: tasks with no
  work allocation yet that are due soon (`db.task_work_hours`'s
  `remaining` already identifies these, see Week Calendar's "Unscheduled
  tasks" panel for a precedent), open tasks at Urgency=3 with no
  allocation, and today's/tomorrow's events with no clear
  location/meeting-format set (ties into "Event format for simple events"
  below) — the widget's job is surfacing *decisions to make*, not just
  *things scheduled*. Concrete action items and their exact selection
  rules need a design pass before this is buildable; not decided yet.
- **Widgets should be more customizable**, in general — no concrete spec
  yet for what this covers beyond the Range/Show/List-Cards toggles the
  original consolidation design already gives Agenda and Spaces & Projects.
  Needs a follow-up conversation on what other widgets should expose (which
  filters, per-widget label/Space scoping, etc.) before this becomes a
  buildable item rather than a direction.

## Tasks page filter cleanup (small, 2026-08-15)

**Status:** decision recorded for two of three pieces — no code.

The Table view's Date dropdown (`routers/tasks.py`'s `DATE_FILTERS`) carries
three virtual/derived states — `overdue`, `important`, `urgent` — alongside
real date buckets (today/tomorrow/this week/this month). This was a
deliberate 1.1 choice (see the comment above `DATE_FILTERS`: "the derived
`important`/`urgent` states live in the Date dropdown instead" of the
explicit-value-only Importance/Urgency dropdowns) but reads as clutter/
wrong-drawer in practice. Direct feedback, 2026-08-15: they shouldn't be in
the Date dropdown.

- **Important → the Importance dropdown**, **Urgent → the Urgency
  dropdown**, each as an "(any)" style option alongside the existing
  all/1/2/3 explicit values — decided.
- **Overdue needs a new home** — not decided yet. It isn't a value on any
  existing axis (not an Importance/Urgency level, not a status); candidates
  worth considering when this gets picked up: a small toggle/chip in the
  toolbar next to the dropdowns, or folding it into the Status dropdown as
  a virtual pseudo-status the way `important`/`urgent` were virtual date
  values. Your call when this slice starts.
- `DATE_FILTERS`/`DATE_FILTER_LABELS` shrink to just the real date buckets;
  `_apply_date_filter`'s overdue/important/urgent branches move to
  `_apply_importance_filter`/`_apply_urgency_filter` (and wherever Overdue
  ends up). `_sort_keys` and Board's own filter application are unaffected.

## Archived vs. Done — mental-model note, no behavior change (2026-08-15)

Not a to-do, a clarification for future work touching task status: `status`
has always had two distinct completed-ish values — `done` and `archived`
(`STATUSES`, `DONE_STATUSES = ("done", "archived")`). The Table view buckets
both under "Completed" and styles them identically
(`.task-row-completed` — dimmed + strikethrough), which reads as "archived
means the work got finished," but that's not what archiving actually means
— a task can be archived without ever having been genuinely completed (put
away / no longer relevant, not "done"). Direct feedback, 2026-08-15:
record the distinction, no behavior change needed right now. Keep this in
mind if a future slice touches completion stats, Streak widget logic
(reads `tasks.completed_at`, which is presumably only set on a real `done`
transition — worth double-checking it's never set by an archive-only
transition before Streak ships), or the Table view's completed-section
styling.

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

**Status:** Phase A shipped. ~~Pagination / collapsible sections (Phase B)~~
**shipped 2026-08-15** — the Tasks table's Open section, the highest-traffic
target named here; see `features/tasks.md` § Views, "Pagination (1.9,
Webapp usability Phase B)". Collapsible sections and other lower-traffic
surfaces (Schedule/etc., to the extent they still apply post-Schedule-
removal) are deliberately deferred — not part of this slice. One genuinely
open piece remains:

- **DAVx5 mobile access** (Phase C): a phone running DAVx5 syncs CalDAV/CardDAV
  against Radicale through a public HTTPS reverse proxy (Caddy) with real bcrypt
  auth — pure infra (a `deploy/` directory: Caddyfile, firewall rules, prod
  Radicale config), no app code. Requires a domain + server before this can be
  acted on.

(The Phase B "add a Databases section to project pages" item is superseded —
Databases were removed; see `abandoned.md`.)

## Event format for simple events (small, 2026-08-15)

**Status:** decision recorded — no code.

`_event_form_fields.html` currently always shows both Location and Meeting
URL fields on every event, unconditionally (`events.location`/
`events.meeting_url` columns, both nullable, both already exist — this is a
form-visibility change, not a schema change). Direct feedback, 2026-08-15:
most events are simple and don't need either field visible by default —
add a **Format** field with two options, **In person** / **Online**, that
reveals only the relevant field (In person → Location; Online → Meeting
URL) instead of showing both always. Naming decided directly: "Format",
not "type"/"kind"/whatever else this could have been called. Whether
"neither picked" is a valid third state (an event with no format at all,
both fields hidden — the common case for e.g. an all-day reminder) or
Format defaults to one of the two isn't decided yet; default to "neither
picked, both hidden until chosen" unless that turns out awkward once
someone's looking at the actual form.

No backing column needed for "Format" itself if it's derived (In person if
`location` is set, Online if `meeting_url` is set, neither if both are
empty) rather than stored — cheaper than a new column and can't drift out
of sync with the two fields it's switching between. Decide this the same
way when the slice starts, not now.

## Modal window uniformization (2026-08-15)

**Status:** decision recorded, no spec written yet — needs a dedicated
design pass before it's buildable. Last in the reprioritized queue
(2026-08-15) deliberately: this cuts across every entity's create/edit
modal, so sequencing it after the items above (which still touch modals —
Event format adds a field to the event modal, Contacts parity adds several
to the contact modal) avoids uniformizing a modal now and then immediately
having to redo the touch-up when those items land their own new fields.

Direct feedback, 2026-08-15: modal windows across the app don't currently
follow one consistent set of rules for footer layout, title treatment, and
body layout — particularly the difference between a body that's a stack of
cards (`.card`-per-section, e.g. `settings_data_health.html`'s pattern) vs.
a body drawing more directly onto the modal surface (plain field rows, e.g.
`task_form.html`), plus modal height/width sizing overall. `_modal_footer.html`
already exists as one shared footer partial (Back/Cancel + Delete + Save,
see its own docstring), so this isn't starting from zero, but it isn't
consistently used or complete as a spec — some modals may have grown their
own footer markup instead. When this slice starts: audit every modal
template (`grep -l data-modal src/templates/*.html` is the rough entry
point) against `_modal_footer.html`'s existing convention, catalog where
footers/titles/body layout actually diverge, and only then write the "real
uniform modal windows" rules the feedback is asking for — this doc entry is
the placeholder for that pass, not the pass itself.

## Known open risks

Model- and architecture-level risks are tracked in
[`open-priority.md`](open-priority.md). Nothing in this file currently carries a
known open risk beyond the blockers noted inline: Contacts field parity's five
open questions and the `X-SOCIALPROFILE` portability question, DAVx5's
domain + server requirement, and the two open sub-decisions in "Tasks page
filter cleanup" (Overdue's new home) and "Event format for simple events"
(whether a third "neither" Format state stays post-implementation).

---

## How open work gets tracked

A focused plan starts its life as a section here. When you give it a go-ahead,
expand it into a full phase spec (acceptance line, concrete slices); when it
ships, describe the outcome in [`features/`](../features/README.md) and remove
the section from this file.
