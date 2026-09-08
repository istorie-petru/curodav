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

**Second direct steer, 2026-08-15 (later the same day):** started Modal
window uniformization's audit-then-write-rules pass ahead of Project
check-in — audit, rules, and all 8 implementation slices (A-H) shipped the
same day; see `features/design-system.md`'s "Modal windows" section for
the outcome. Contacts field parity (4 of 6 sub-slices still open) was
untouched by this steer.

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
7. ~~**Modal window uniformization**~~ — **shipped 2026-08-15** (jumped
   ahead of items 5-6 per the second direct steer above) — see
   `features/design-system.md`'s "Modal windows" section.
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
Calendar: Month / 4-Week / Week / Day. Disabled views disappear from the
relevant navigation and view switchers but must not delete data or alter the
underlying model; re-enabling restores access. Deliberately simple — not a
general-purpose UI customization system.

**2026-08-28 update:** the Tasks half of this ("Table / Board / Timeline")
is superseded — the 2026-08-28 "major rework" session retired Kanban and
Timeline outright (`plans/STATE.md`'s entry for that session), so Table is
now the Tasks page's only view; there is nothing left to toggle there. The
Calendar half is untouched and still open.

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

**Status:** Shipped 2026-08-16 (all six slices). Green-lit 2026-08-15 (AskUserQuestion, all five open
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
- ~~**Website**~~ — **shipped 2026-08-15** — multi-value, Home/Work/Other
  vocabulary (same as email/address), new `contact_websites` table (owned
  child rows, same shape as `contact_phones`/`contact_emails`, `url`
  column named for the vCard property, not `value`). No legacy single-
  value column ever existed for Website, so no auto-migration was needed
  (confirmed by grep before writing any code). vCard round-trips as
  multiple `URL` lines with `TYPE=` (Other omits the param), via vobject's
  `card.add("url")`/`card.url_list` — confirmed to behave identically to
  `tel_list`/`email_list` with a live snippet before writing the code, not
  assumed. Create/edit form submits parallel `website_type[]`/
  `website_url[]` arrays, reusing `static/contact_phone_email_rows.js`'s
  existing generic add/remove-row wiring verbatim (already written
  generic enough for a third field group); detail page lists every entry
  with its type + an external link (`target="_blank" rel="noopener"`,
  matching event `meeting_url`'s convention). Left off the compact
  contacts-list row/dashboard widget (org/title/phone/email stay the
  subtitle fields). Search matches website URLs too. See
  `features/contacts.md`. 26 new tests
  (`test_contacts_field_parity_website.py`), full suite 1457 passed.
- ~~**Birthday**~~ — **shipped 2026-08-16** — single-value (unlike Phone/
  Email/Website — a contact has at most one), new `contacts.birthday`
  column storing vCard's own BDAY text verbatim: a full "YYYY-MM-DD" date,
  or a year-less "--MM-DD" date (green-lit, AskUserQuestion, 2026-08-15).
  `db.parse_contact_birthday` validates a create/edit form's raw text
  against both shapes (real calendar-date validation via `datetime.strptime`,
  not just a regex — rejects e.g. `1990-02-30`; a year-less date validates
  against a dummy leap year so `--02-29` is accepted) and is the one call
  site `routers/contacts.py` uses before ever reaching `upsert_contact`,
  400 on anything else. `db.format_contact_birthday` is the reverse: "May
  17, 1990" / "May 17" for display, falling back to the raw stored value
  unchanged for a shape this app didn't write itself (e.g. a bare
  `19900517` from another CardDAV client). vCard round-trips through a
  single BDAY line — vobject treats a string `.value` as opaque text on
  both write and read, confirmed directly against vobject before writing
  `vcard_rows.py`, so no `date`-object parsing is needed anywhere in this
  app just to round-trip either shape. Plain text input on the create/edit
  form (`contact_form.html`, new `.field-hint` CSS), not a native
  `<input type="date">`, since a year-less birthday has no HTML date-input
  equivalent; the detail page shows it formatted via a new `fmt_birthday`
  Jinja filter (`deps.py`). Not searched (`db._search_contacts`/
  `list_contacts`) — same precedent as Address, the other single-value
  field, which isn't searched either. See `features/contacts.md`. 35 new
  tests (`test_contacts_field_parity_birthday.py`); 20 existing call sites
  across 6 test files updated for the new `birthday` form param, full suite
  1492 passed.
- ~~**Address**~~ — **shipped 2026-08-16** — structured, multi-value, full
  vCard ADR (PO Box/Extended/Street/City/Region/Postal code/Country), each
  entry typed Home/Work/Other (same vocabulary as email/website). New
  `contact_addresses` table (owned child rows, same shape as
  `contact_phones`/`contact_emails`/`contact_websites`, seven value
  columns instead of one — a row is dropped only when every field is
  blank). The old flat `contacts.address` column auto-migrates once,
  idempotently, into a single "Other"-typed entry (the whole legacy
  string into `street`, `db.migrate_legacy_contact_address`). vCard
  round-trips as multiple `ADR` lines with `TYPE=` (Other omits it) via
  vobject's `card.add("adr")`/`adr_list` — ADR is one of RFC 2426/6350's
  own typed multi-instance properties, confirmed directly against
  vobject. Create/edit form renders each address as its own card
  (`.contact-address-row`, a 2-column field grid, not the single-line
  rows phone/email/website use); detail page renders each entry via a
  new `fmt_address` Jinja filter (`db.format_contact_address`, vCard's
  own multi-line layout). Not searched, same precedent as Birthday. See
  `features/contacts.md`. 37 new tests
  (`test_contacts_field_parity_address.py`), full suite 1560+ passed.
- ~~**Social network**~~ (`X-SOCIALPROFILE`) — **shipped 2026-08-16**,
  closing out this effort. Multi-value, tagged with a network name
  (Twitter/Facebook/Instagram/LinkedIn/Mastodon/GitHub/Other —
  `db.CONTACT_SOCIAL_TYPES`, not the Home/Work/Other vocabulary every
  other typed field uses). New `contact_social_profiles` table, same
  shape as `contact_phones`/`contact_emails`/`contact_websites` (single
  `value` column). No pre-existing single-value column, so no auto-
  migration (same situation as Website). vCard round-trips as multiple
  `X-SOCIALPROFILE` lines with `TYPE=` naming the network (Other omits
  it) — an X- extension property, but vobject treats it identically to a
  core typed property, confirmed directly against vobject. Create/edit
  form uses the same one-line multi-row shape as Phone/Email/Website;
  detail page renders a URL-shaped value as an external link, a bare
  handle as plain text. See `features/contacts.md`. 25 new tests
  (`test_contacts_field_parity_social.py`), full suite 1586 passed.
  **Contacts field parity with Nextcloud Contacts is now fully shipped.**

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

## Calendar: FullCalendar-parity interactions (scoped 2026-09-08)

**Status:** scoped 2026-09-08, direct request ("check out fullcalendar.io,
implement some of their fixes") — supersedes item 1 of the old "Event
banners (not yet scoped)" section below (2026-09-03's "multi-day event bars
spanning cells" note), now expanded into concrete slices instead of a
one-line placeholder. Confirmed against the actual current code before
scoping: Month, 4-Week, and Week's all-day row all render a multi-day event
as a repeated per-day chip today, not a spanning bar — a deliberate choice
made 2026-08-08 (`_month_grid` dropped the old lane-packed bar layout) and
narrowed further 2026-08-07 (`_is_bar_worthy`, all-day only). This work
explicitly reverses both of those decisions. Also confirmed: Month/4-Week
drag already exists (`calendar_month_drag.js`) but only shifts a whole item
to a different day with no resize, and the dragged chip doesn't visually
follow the pointer (`.month-event-item.dragging` is a static "lifted" style
in place, unlike Week/Day's `.time-event` which is already absolutely
positioned and does track the cursor) — direct follow-up report, 2026-09-08.

**Acceptance:** Month/4-Week render multi-day all-day events as one
continuous bar spanning the cells it covers (wrapping at week boundaries),
draggable to move and resize from either edge, with the dragged bar
visually following the pointer during the drag. The "+N more" overflow
shows an info surface instead of navigating to Day view. Week view supports
dragging an event between the "All day" row and the timed grid in both
directions. Week's async region refresh no longer resets scroll position.
Month/4-Week/Week header navigation (prev/next) updates the grid and a
visible month-name/week-range label via AJAX, no full page reload.

**Slices** (dependency order; 1→2→3 touch the same Month/4-Week templates
so are worth running back-to-back, 4→5 are Week-specific, 6 is independent
and touches all three view headers):

1. **Shipped 2026-09-08.** Backend lane-packing + spanning-bar rendering,
   Month + 4-Week, no drag/resize yet. `git log -p` had no usable
   pre-2026-08-08 bar-lane commit to crib from (this repo's history is
   squashed before that point), so the lane-packing pass in
   `routers/calendar.py` (`_bucket_month_items`, `_week_bars`,
   `_month_day_cells`, `_month_grid`, `_four_week_grid`) was written fresh
   as a standard interval-graph greedy assignment. New `.month-week-bars`
   layer in `_calendar_month_grid.html`/`_calendar_fourweek_grid.html` +
   bounded static CSS classes (no inline `style=`, CSP has no
   `'unsafe-inline'` on style-src) in style.css; non-bar items (timed
   events, tasks) still render as the existing per-day text list beneath
   the bars, offset by a `month-bars-offset-N` class so the two layers
   never overlap. `test_calendar_month_bars.py` rewritten. See
   `plans/STATE.md`'s own entry for this slice for the full detail,
   including a known temporary regression (whole-day drag-to-move on an
   all-day event doesn't work until slice 2 retargets it at the new
   `.month-bar` element).
2. **Drag-move + edge-resize for bars, plus the pointer-follow drag
   ghost.** Move reuses `calendar_month_drag.js`'s whole-day-shift delta
   logic, retargeted at a bar element. Resize is new: left/right edge
   handles that change `start_at`/`end_at`'s date, POSTed to the existing
   `/events/{uid}/reschedule` (no backend endpoint work needed — it
   already accepts both fields) — same move-vs-resize branch pattern
   `calendar.js` already uses for Week/Day's `.te-resize-handle`, ported
   from a bottom edge to horizontal edges. The drag ghost: a floating
   clone (`position: fixed`, `pointer-events: none` so `elementFromPoint`
   still resolves to the day cell underneath it, not the clone) tracking
   the pointer, spawned on drag start and removed on drop — build once
   here for both move and resize rather than patching today's soon-to-be-
   replaced chip drag first.
3. **Shipped 2026-09-09.** "+N more" overflow → info toast instead of a
   Day-view link. Open decision (`ccToast`'s plain-text `message` vs. its
   `actions` array) settled via direct AskUserQuestion answer: `actions`,
   keeping per-item click-through. See `plans/STATE.md`'s own entry for
   this slice for the full detail.
4. **Shipped 2026-09-09.** Week view: drag an event between the "All day"
   row and the timed grid, both directions (FullCalendar's
   `allDayMaintainDuration` equivalent). `calendar_week_allday_drag.js`'s
   `setupItem` and `calendar.js`'s `setupEvent` each gained the other's
   drop-target type (`.time-col` / `.allday-col` respectively); both still
   POST the same `/events/{uid}/reschedule`, which gained one new optional
   field (`all_day`) rather than a new endpoint, exactly as scoped below.
   See `plans/STATE.md`'s own entry for this slice for the full detail,
   including the Day-view side effect (the same timed→all-day code path
   incidentally also works there, since Day loads calendar.js and has its
   own `.allday-col`) and the task-chip exclusion (no time-of-day due-date
   concept in this app, so a task dropped on the timed grid is a no-op).
5. **Week view: stop resetting scroll position on add/move.** Root cause
   confirmed: `async_crud.js`'s `refreshRegion()` does
   `current.replaceWith(fragment)`, replacing `#week-grid` wholesale —
   `.time-grid-wrap` (the actual `overflow-y:auto` scroll container,
   style.css) is a child of that swapped element, so a fresh node with
   `scrollTop: 0` replaces the one the user had scrolled. Fix: in
   `async_calendar.js`'s `refreshWeek()`, capture `.time-grid-wrap`'s
   `scrollTop` before calling `refreshRegion`, restore it on the new node
   after. Small, contained, no backend change — could ride along with
   slice 4 if convenient.
6. **Shipped 2026-09-09.** Live month/week label + AJAX prev/next nav, no
   full page reload -- 4-Week and Week only. Open decision (Week's visible
   label: ISO week number vs. a date range) settled via direct
   AskUserQuestion answer: a date range, matching FullCalendar's own
   default; 4-Week's label follows the same convention. Month excluded
   entirely -- confirmed before building that `month_view` has had no
   route decorator since `calendar_root_redirect` retired it (bare
   `/calendar` always redirects to `/calendar/fourweek`), so there was no
   reachable page left to wire AJAX nav onto. See `plans/STATE.md`'s own
   entry for this slice for the full detail. This was the final slice of
   the arc -- all six now shipped.

## Event banners — "starting soon" notice (not yet scoped)

**Status:** captured 2026-09-03, direct request ("let's not forget") —
still just a placeholder, not designed or slice-sized. A dismissible strip
surfacing the next imminent event wherever the user currently is, closer to
a notification than a calendar-rendering change. Unrelated to the
multi-day-bar work above (that item was originally bundled with this one in
the same 2026-09-03 note; split apart now that the bar work is scoped).

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
