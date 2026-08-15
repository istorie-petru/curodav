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

**Second direct steer, 2026-08-15 (later the same day):** start Modal
window uniformization's audit-then-write-rules pass now, ahead of Project
check-in — see its own section below for the completed audit + rules.
Contacts field parity (4 of 6 sub-slices still open) is untouched by this
steer and still comes before Modal uniformization's *implementation*
slices D-H (not its design pass, which doesn't touch live modals) — see
that section's own note on why.

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

**Status:** audit + rules written 2026-08-15; **slices A, B, C shipped
2026-08-15** (see the implementation-slices list below) — every hand-
rolled `.modal-footer` is now `_modal_footer.html`, note_form's Delete is
confirmed, and the widget-builder's two "New widget" triggers are wide.
Slices D-H are still open. Jumped ahead of Project check-in in the
reprioritized queue at direct user request (2026-08-15); the "sequence it
last" reasoning below still explains *why* it was originally queued last,
it just didn't gate the design pass or slices A-C (none of the three
touched a modal the still-open Contacts/Project-check-in work is adding
fields to) — only D-H still wait on those, per the note below.

Original reasoning for the "last" placement, still true for
implementation: this cuts across every entity's create/edit modal, so
touching it before the items above (which still touch modals — Event
format's Format field, shipped 2026-08-15, see `features/calendar.md` §
Event CRUD & fields; Contacts parity adds several fields to the contact
modal, 4 of 6 sub-slices still open) risks uniformizing a modal now and
then immediately redoing the touch-up when those items land new fields.
Implementation slices D-H below should still wait for Contacts field
parity and Project check-in to finish touching the entity modals; slices
A-C are narrow enough (one file, or a one-line trigger attribute) that
there's nothing left for a later feature to collide with.

### Audit (every modal template against `_modal_footer.html`'s convention)

Every template with a `.modal-header`/`.modal-body` pair
(`grep -l "modal-header\|modal-body" src/templates/*.html`) was read in
full. 15 real modal fragments exist: `task_form`/`task_detail`,
`event_form`/`event_detail`, `contact_form`/`contact_detail` (the "core
three", already uniform with each other — see their own 2026-08-08 "one
cohesive stroke" comments), `habit_form`, `habit_task_form`,
`label_edit_modal`, `label_merge_modal`, `note_form`, `quick_add`,
`banner_editor`, `_widget_edit_modal`, `_modal_widget_customize`.

**Footer — three different implementations, not one:**

1. **`_modal_footer.html` (the shared partial)** — used only by the core
   three's detail/edit pairs. Back-left (chevron icon) / spacer / demoted
   `.detail-delete-link` text-link (undo or confirm-sheet mode) / primary
   `.btn.primary` (icon + label) on the right.
2. **Hand-rolled `.modal-footer` markup** — `habit_form`, `habit_task_form`,
   `label_edit_modal`, `label_merge_modal`, `note_form`, `quick_add`,
   `_modal_widget_customize`. Each reinvents the same bar with small,
   pointless differences: Delete rendered as a filled `.btn.danger` button
   (habit_form, label_edit_modal, note_form) instead of the core three's
   demoted text-link; Cancel/Save sometimes carry icons (quick_add,
   label_edit_modal, label_merge_modal) and sometimes don't (habit_form,
   habit_task_form, note_form); Delete confirmation is `data-confirm-sheet`
   in some (habit_form, label_edit_modal, label_merge_modal) and **entirely
   absent** in one — see the safety issue below.
3. **No footer at all, Save embedded in the body form instead** —
   `_widget_edit_modal.html` (its `_widget_edit_form.html` already carries
   `widget-filters-autosave` — the inline "Save filters" button may already
   be vestigial) and `banner_editor.html` (every action there — upload,
   remove — is instant/auto-submitting, so there's arguably nothing for a
   footer to do, but that's a judgment call this doc is now making
   explicit rather than an accident).

**Safety issue found, not just cosmetic:** `note_form.html`'s Delete form
has neither `data-confirm-sheet` nor `data-delete-undo` — clicking it
deletes the note immediately and irreversibly, the only entity delete
action anywhere in the app with zero confirmation or undo. Worth fixing on
its own, independent of the rest of this uniformization (see slice A).

**Title treatment — two legitimate shapes, correctly split, but a stray
third:** detail/view modals (core three only) get the rich identity header
— a status-colored dot/avatar + large bold `.detail-title`
(`.modal-header h1.detail-title{font-weight:700}` is the only CSS rule
that applies this). Every create/edit form and small utility modal gets a
plain `<h1>text</h1>`, no identity, no icon — *except* `banner_editor.html`
and `_widget_edit_modal.html`, which icon-prefix their plain h1
(`{{ icon('image') }} Page banner`, `{{ icon('edit') }} Edit widget`) for
no documented reason while every sibling utility modal
(`_modal_widget_customize`, `label_edit_modal`, `note_form`, ...) doesn't.

**Body layout — mostly already consistent, one real gap:** the "form"
shape (`.modal-body > .card > .field-grid`, the card flattened
borderless/chromeless by `.modal-body .card{border:none; box-shadow:none}`)
is used correctly and consistently by every plain create/edit form —
core three, `habit_form`, `habit_task_form`, `label_edit_modal`,
`label_merge_modal`, `note_form`. The "detail" shape (a stack of
`.detail-card`s) is used correctly and consistently by the core three's
view modals. Two modals are legitimately a third shape — a two-pane
`.widget-builder` grid (config pane + live preview,
`_widget_edit_modal.html` and `_modal_widget_customize.html`) — and
`banner_editor.html` is a legitimate fourth, bespoke, one-off layout
(image preview + upload control, not a field-grid at all). None of these
three are wrong to diverge from "form"/"detail" — a two-pane builder or an
image uploader genuinely isn't either shape — but see sizing below for
where this bites.

**Sizing — the one real functional bug found:** `data-modal-size="wide"`
is set on the *opening trigger link*, not derived from the fragment's own
content, and only 2 of the 3 wide-shaped surfaces opt in
(`banner_editor.html`'s trigger, `_widget_edit_modal.html`'s trigger both
carry it). `_modal_widget_customize.html` — the exact same
`.widget-builder` two-pane grid — is opened via `dashboard.html`'s and
`label_detail.html`'s "New widget" links, **neither of which sets
`data-modal-size="wide"`**, so the identical two-column config+preview
layout squeezes into the default ~narrow width there while the
per-widget-edit version of the same layout gets the wide dialog. This is a
real, fixable inconsistency, not a style preference.
`.modal-stable-height` (a fixed, capped-at-720px height so a view↔edit
cross-fade or a tab switch doesn't jump/resize the dialog) is opted into
by the core three's pairs and by `quick_add` (its task/event tab switch);
every other modal free-heights to its own content, which is correct for a
single-state form — this one isn't actually inconsistent, just never
written down as a rule until now.

### Rules ("real uniform modal windows")

1. **Footer:** every modal renders its footer through `_modal_footer.html`
   — no more hand-rolled `.modal-footer` markup anywhere. The partial needs
   two small extensions to cover the legitimate non-CRUD shapes found
   above: (a) a primary-only mode with no back/cancel link and no Delete
   (`_modal_widget_customize`'s "Add widget"), (b) confirming that
   `footer_delete_mode='confirm'` (already supported) is the right choice
   wherever an action has no natural undo destination (note_form, whose
   notes list has no per-row undo-toast precedent the way tasks/events/
   contacts do). A modal whose form autosaves with no discrete save step
   (`_widget_edit_modal`) still gets a footer — just Back/Done only, no
   primary button — rather than an embedded button and no footer.
2. **Delete confirmation is never optional.** Every destructive action
   reachable from a modal footer must be `undo` or `confirm` mode, never a
   bare POST. Fixes note_form immediately (slice A, small and independent
   of the rest).
3. **Title:** plain `<h1>` for every create/edit form and utility modal, no
   icon prefix, no identity treatment — keep the rich identity header
   (dot/avatar + bold `.detail-title`) exclusive to real-entity detail/view
   modals, matching what's already consistently true today. Drop the
   inconsistent icon-prefix on `banner_editor`/`_widget_edit_modal`'s `<h1>`
   to match every other utility modal, rather than adding icons everywhere
   else to match them — smaller diff, and a plain title is already the
   overwhelming majority convention.
4. **Body layout:** exactly two shapes for anything that's a plain form or
   a plain read-only view — "form" (`.modal-body > .card > .field-grid`)
   and "detail" (a stack of `.detail-card`s) — already correctly applied
   everywhere they belong. A modal may declare a third, custom shape
   (two-pane builder, bespoke uploader) only when neither shape fits, and
   doing so doesn't exempt it from rule 1's footer requirement.
5. **Sizing:** two named sizes, `default` and `wide` (`.modal`/
   `.modal.is-wide`, already exist). `wide` is for any modal whose content
   is a two-pane layout or a wide table; every trigger opening such a
   fragment must carry `data-modal-size="wide"` — no exceptions, since the
   fragment can't set its own dialog width. Fixes the Add-widget/Customize
   trigger gap (slice C). `.modal-stable-height` is for any modal whose own
   content changes shape post-open without a full re-navigation (a view↔edit
   cross-fade, or `quick_add`'s tab switch) — everything else free-heights,
   which is already how every other modal behaves today.

### Implementation slices (small, pick off independently, in this order)

- ~~**A. Fix `note_form.html`'s unconfirmed Delete**~~ — **shipped
  2026-08-15**, folded into slice B (below) rather than done separately —
  `note_form.html`'s Delete now goes through `_modal_footer.html`'s
  `confirm` mode like every other migrated modal's Delete.
- ~~**B. Migrate the hand-rolled-footer modals onto `_modal_footer.html`**~~
  — **shipped 2026-08-15** — `habit_form`, `habit_task_form`,
  `label_edit_modal`, `label_merge_modal`, `note_form`, `quick_add` all now
  render their footer through the shared partial; no hand-rolled
  `.modal-footer` markup remains outside `_modal_widget_customize`/
  `_widget_edit_modal`/`banner_editor` (slices D-F). `_modal_footer.html`
  gained one small extension along the way: an optional `footer_primary_id`
  (only `quick_add.html` needs it — `static/quick_add.js`'s tab switch
  retargets the Save button's `form` attribute via `getElementById`, which
  needs a stable id the partial didn't expose before). 9 new tests
  (`test_modal_uniformization.py`), full suite 1431 passed.
- ~~**C. Add `data-modal-size="wide"` to the "New widget" triggers**~~ —
  **shipped 2026-08-15** — `dashboard.html`'s and `label_detail.html`'s
  "New widget" links now carry `data-modal-size="wide"`, matching
  `_widget_edit_modal`'s trigger; the identical `.widget-builder` two-pane
  grid no longer squeezes into the default width from either entry point.
  Covered by `test_modal_uniformization.py`'s
  `TestNewWidgetTriggerWideSizing`.
- **D. `_modal_widget_customize.html` onto `_modal_footer.html`**
  (primary-only mode) — do after C so the sizing fix is visible during
  testing.
- **E. Resolve `_widget_edit_modal`'s embedded Save vs. its footer** —
  either drop the inline "Save filters" button (rely purely on the
  existing autosave) and add a Done-only footer, or keep an explicit Save
  and move it into the footer instead of the body; needs a quick direct
  check with the user on which behavior autosave actually already
  delivers before picking (do not guess).
- **F. `banner_editor.html`: decide footer or no-footer as a documented
  exception** — either add a plain Done-only footer for consistency with
  rule 1, or record it explicitly as the one allowed no-footer case
  (a modal where literally every body action is a complete, instant
  operation) so it isn't rediscovered as a "bug" later.
- **G. Drop the icon prefix from `banner_editor`/`_widget_edit_modal`'s
  `<h1>`** to match rule 3.
- **H. Full-app modal sweep** — after A-G ship, re-grep every modal
  template once more to confirm no leftover hand-rolled footer/title
  pattern survived (this file's own audit list above is the checklist).

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
