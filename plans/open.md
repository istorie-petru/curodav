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
Dashboard widgets work (~~shipped 2026-08-15~~), then the small Tasks-filter
cleanup and Event format items (~~both shipped 2026-08-15~~), then Contacts
field parity, then Project check-in, then Modal window uniformization.
Configurable views + optional Schedule module and Webapp usability's
remaining pieces (collapsible sections, DAVx5 — see `roadmap.md`'s 1.9 row)
weren't mentioned in the reprioritization and stay parked at the back of the
queue.

1. ~~**Command palette actions**~~ — **shipped 2026-08-15**, see
   `features/tasks.md` § Search & the command surface.
2. ~~**Dashboard widgets: new widgets + real customization**~~ — **shipped
   2026-08-15**, see `features/dashboard.md`.
3. ~~**Tasks page filter cleanup**~~ (small) — **shipped 2026-08-15**, see
   `features/tasks.md` § Tasks page filter cleanup.
4. ~~**Event format for simple events**~~ (small) — **shipped 2026-08-15**,
   see `features/calendar.md` § Event CRUD & fields.
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

**Status:** In progress. Green-lit 2026-08-15 (AskUserQuestion, all five open
questions answered): type vocabulary matches vCard/Nextcloud exactly (Home/
Work/Cell/Fax/Pager/Other for phone, Home/Work/Other for email/address/
website); existing single-value data auto-migrates as a first entry typed
"Other"; Address uses the full vCard ADR structure (PO Box, Extended, Street,
City, Region, Postal code, Country); Birthday supports both full and
year-less (`--MMDD`) dates; Social network round-trips via the standard
`X-SOCIALPROFILE` vCard property. Two of the original target fields stay
deliberately skipped (Address book and Archive — straight reversals of the
label model already covered by labels).

**Build order:** Title → Phone/Email → Website → Birthday → Address → Social
network, each a full slice (schema → vCard round-trip → form/detail/list UI →
its own test file).

- ~~**Title**~~ — **shipped 2026-08-15** — `contacts.title` column (vCard
  TITLE, distinct from `org`/vCard ORG); create/edit form field; contact
  detail header and the contacts-list row now show "Title at Org" (falling
  back to whichever is present); search (`/contacts?q=`) matches title too.
  See `features/contacts.md`. 17 new tests
  (`test_contacts_field_parity_title.py`), full suite 1382 passed.
- ~~**Phone/Email**~~ — **shipped 2026-08-15** — multi-value, vCard/
  Nextcloud type vocabulary (Home/Work/Cell/Fax/Pager/Other for phone,
  Home/Work/Other for email), new `contact_phones`/`contact_emails` tables
  (owned child rows, no FK constraint, same convention as
  `task_checklist_items`); the old flat `contacts.phone`/`contacts.email`
  columns stay physically present but are dead (never written to again),
  and auto-migrate once, idempotently, into the new tables as a single
  "Other"-typed entry (`db.migrate_legacy_contact_phone_email`, runs at
  schema setup). vCard round-trips as multiple TEL/EMAIL lines with
  `TYPE=` (Other omits the param, vCard has no token for it); create/edit
  form submits parallel `phone_type[]`/`phone_value[]` (`email_type[]`/
  `email_value[]`) arrays on the one Save button, rows added/removed
  client-side (`static/contact_phone_email_rows.js`); detail page lists
  every entry with its type + tel:/mailto: link, list row/dashboard widget
  show only the first entry. Search matches the new tables too. See
  `features/contacts.md`. 40 new tests
  (`test_contacts_field_parity_phone_email.py`), full suite 1422 passed.
- **Website** (multi-value) — not started.
- **Birthday** (full or year-less date) — not started.
- **Address** (structured multi-value, full vCard ADR) — not started.
- **Social network** (`X-SOCIALPROFILE`) — not started.

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

## Modal window uniformization (2026-08-15)

**Status:** decision recorded, no spec written yet — needs a dedicated
design pass before it's buildable. Last in the reprioritized queue
(2026-08-15) deliberately: this cuts across every entity's create/edit
modal, so sequencing it after the items above (which still touch modals —
Event format's Format field ~~shipped 2026-08-15~~, see
`features/calendar.md` § Event CRUD & fields; Contacts parity adds several
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
known open risk beyond the blockers noted inline: DAVx5's domain + server
requirement. (Contacts field parity's five open questions were resolved
2026-08-15 — see that section.)

---

## How open work gets tracked

A focused plan starts its life as a section here. When you give it a go-ahead,
expand it into a full phase spec (acceptance line, concrete slices); when it
ships, describe the outcome in [`features/`](../features/README.md) and remove
the section from this file.
