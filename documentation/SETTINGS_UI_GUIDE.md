# Settings: one canon per job, not one pattern per page

`UI_CONSISTENCY_GUIDE.md` covers components app-wide. Settings needs its
own guide on top of that because it's where the drift is worst: several
pages show the *same kind of data* (a small set of user-managed records)
using visibly different layouts, because each was built in its own session
without checking what the sibling page already did.

## What's actually there today (audited directly, not assumed)

Three different shapes currently do overlapping jobs across Settings:

1. **`settings_general.html`** — `.card` containing a stack of
   `.settings-field-row` rows (label + hint on the left, one control on
   the right, autosubmits). This is for **single-value preferences** —
   week start, time format, 4-week position, recurrence terminology. One
   value in, one value stored, nothing to create/delete/list.
2. **`settings_holidays.html` / `settings_time_blocks.html`** — a small
   "add new" `.card` with an inline form, then a **separate**
   `.card.table-scroll` holding an editable `<table>` — every cell is its
   own inline `<input>` that PATCHes on change (`settings_holidays.js`,
   mirroring `tasks_table.js`'s pattern). This is for **managing a small
   set of named records**, each with a few fields — a holiday has a
   label/calendar/date range, a time block has a label/time range/days.
3. **`labels_manage.html`**, elsewhere in the app (not under Settings'
   `.card`/`.settings-field-row` convention at all) — a grouped list of
   rows (`_labels_body.html`), each with a plain **Edit** button that opens
   `label_edit_modal.html`, a real form in a modal. Also managing a small
   set of named records, each with a few fields — the *same job* as
   holidays/time blocks above, solved a different way.

`settings_advanced.html` and `settings_data_health.html` each additionally
mix in a **third** row shape, `.settings-row` (a whole `<a>` styled as a
row, for navigating out or triggering a download — Export's file links,
the Settings hub's own category list) alongside `.settings-field-row`
(single-control actions) on the same page. And `settings_data_health.html`
ends with yet another `.card.table-scroll` table for its Backups list.
`settings_sync_conflicts.html` is a fourth full page that's *only* that
table pattern.

None of these are "wrong" in isolation — but holidays, time blocks,
backups, and sync conflicts are four different pages independently
choosing between "inline-editable table" and "the Labels modal pattern"
with no shared rule, which is exactly the kind of accidental divergence
`UI_CONSISTENCY_GUIDE.md` exists to prevent. Settings needs the same rule
applied deliberately, once.

## The canon, going forward

**Two patterns, chosen by what the data actually is — not by which page
happens to need it this week:**

### A. Displaying/toggling a setting → `settings_general.html`'s pattern

`.card` > `.settings-field-row` (label + hint left, one control right,
autosubmit where the choice is a complete action on its own — a radio/
segmented pick, a select, a toggle). This is already the canonical shape
and is used correctly on `settings_general.html`, `settings_appearance.html`,
and (for its status/action rows specifically) `settings_data_health.html`
and the action rows of `settings_advanced.html`. Any new single-value
preference goes here, unchanged.

### B. Managing a set of user-created records → Labels' grouped-list + modal pattern

Adopt what `labels_manage.html`/`_labels_body.html`/`label_edit_modal.html`
already do, for **any** page whose job is "a short list of named things the
user creates, edits, and deletes" — a holiday, a sleep/leisure time block,
and any future page shaped the same way:

- A **grouped list** of plain rows (name + the 1-2 facts that matter at a
  glance — e.g. a holiday's date range, a time block's time range/days),
  each with a single **Edit** action.
- Edit opens a **modal form** (the record's fields, Save/Cancel), the same
  `#modal-target` convention every other create/edit surface in the app
  already uses (`features/architecture.md` §2) — not inline per-cell
  editing.
- A single **"+ Add"** entry point into the same modal, empty, rather than
  a separate always-visible inline add-form card.

This means `settings_holidays.html` and `settings_time_blocks.html` should
be **rebuilt onto this pattern**, replacing their current inline-editable
tables — real implementation work (new modal template, router changes from
per-field PATCH to a normal create/update form submit, updated tests), not
a copy-paste. Treat it as its own slice under `plans/STATE.md`'s workflow,
not a drive-by change; this file records the *target shape* so that slice
has a clear spec instead of reinventing the pattern a third way.

**What does *not* move to this pattern:** Backups and Sync conflicts are
not user-authored records — they're a *log* (backups happened; conflicts
were detected) with per-row actions (Verify/Restore, Restore/Dismiss), not
things a user creates and names. A table stays correct for these; see the
merge proposal below for how they should actually be organized instead.

### The third shape (`.settings-row` link rows) is fine, kept narrow

Rows that navigate elsewhere or trigger an immediate download/action with
no further input (Export's file links, the Settings hub's own category
list) are legitimately a third, different thing — a link, not a setting or
a record. Keep `.settings-row` for exactly that, don't fold it into A or B,
and don't let it drift into being used for anything else either.

## Reorganization: Advanced + Data health + Sync conflicts (shipped 2026-08-17)

These three currently split "everything about your data's safety and
lifecycle" across three separate pages with no priority ordering within
any of them — a destructive "Purge all data" button sits in the same
visual weight as "Reset dashboard layout" on Advanced, and an unresolved
sync conflict is invisible unless you happen to visit its own page.

**Implemented** as a merged **"Data & Maintenance"** hub category at
`/settings/data-maintenance` — one page, sub-sectioned (the old three URLs
plus `/export` are 303 redirects into it; every POST action endpoint keeps
its URL but redirects back here). The ordered shape, exactly as proposed
below:

1. **Needs attention, first, visually urgent.** Unresolved sync conflicts
   and any failed integrity check belong at the very top, not buried in a
   page nobody visits unless told to. A conflict count badge on the
   Settings hub row itself (today `settings_index.html` shows every
   category identically — a category with 0 vs 3 unresolved conflicts
   looks the same) is the other half of "visible" — worth doing alongside
   the page reorg, not instead of it. This section uses color deliberately
   (a warning/error tone from the M3 token set, not the neutral `.card` —
   see `UI_CONSISTENCY_GUIDE.md` §10) — this is the one place in Settings
   where "looks the same as everything else" is the wrong outcome.
2. **Health status, visual, second.** Database integrity / last
   backup / last verification / sync status — today these are plain text
   ("OK" / "Problem found") in ordinary `.settings-field-row`s, which is
   exactly what makes them easy to skim past. Small colored status
   indicators (a dot or chip using the same success/warning/error tokens,
   not a new color system) turn this into something scannable at a glance,
   which is what "data health should be visual" means concretely — not a
   new chart library, just making OK vs. not-OK actually look different.
3. **Primary actions, visible, third.** Backup now / restore / verify —
   the things a user actually comes here to *do* — as real buttons, not
   competing for attention with informational rows. `.btn primary` for the
   one most-likely action (Backup now), `.btn ghost` for the rest, same
   rule as `UI_CONSISTENCY_GUIDE.md` §2.
4. **Export & import**, fourth — useful, not urgent, not primary.
5. **Danger zone, last, visually separated.** Purge completed / purge all
   — already using `.btn danger`, correctly — but should sit in its own
   clearly-labeled section at the very bottom, never adjacent to routine
   actions the way "Reset dashboard layout" currently sits directly above
   "Purge all data" on Advanced today.
6. **Backups list & storage stats**, last — reference information, kept
   as the existing table pattern (it's a log, per the rule above).

This reordering (and the sync-conflict badge) was implemented 2026-08-17 as
its own slice — see `features/settings.md` § Data & Maintenance and the
`settings_data_maintenance.html` template for the shipped shape.

## Quick self-check before adding anything to Settings

- [ ] One value, one control? → pattern A (`settings_general.html`'s shape).
- [ ] A short list of named things the user creates/edits/deletes? →
      pattern B (Labels' grouped-list + modal) — not a new inline table.
- [ ] A link out or an immediate download/action with no input? →
      `.settings-row`, nothing else.
- [ ] A log/history with per-row actions (backups, conflicts)? → the
      existing table pattern is correct — just make sure anything urgent
      in it is visually flagged, not identical-looking to routine rows.
- [ ] About to lay out a Settings page a fourth different way? → stop,
      state the case, ask first (`UI_CONSISTENCY_GUIDE.md`'s standing rule).
