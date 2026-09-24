# UI/UX cleanup & labels-as-modules — 2026-09-24 request batch

Source: one direct message from Peter bundling ~17 distinct changes in a
single pass (2026-09-24). Per `STATE.md`'s slice-discipline convention this
was **not** built in one session — Peter confirmed ("log it all, then pick
one slice") that this doc exists to hold the full backlog while sessions pick
it apart one slice at a time, same pattern `audit-fixes-2.0.md` used for its
own audit findings.

Two points were resolved by direct question before this doc was written
(`AskUserQuestion`, same session):
- **Session structure**: log everything here, implement one slice per
  session going forward — not a single "plow through all of it" pass like
  2026-09-21's.
- **Label-pill link target** (item 4's "should this open as a modal or a
  full page" question, left open in Peter's own message): **context-
  dependent** — modal when clicked from inside a widget/card (dashboard,
  Kanban, agenda rows — consistent with how task/event rows already open
  via `data-modal`), full page when clicked from the sidebar or a dedicated
  label-list view.

Three items in Peter's message (his own 2, 14, and 16 in the order they
arrived) are really one evolving spec — the labels/sidebar/dashboard model
kept getting refined across the same message, with each later mention
narrowing the one before it. They're merged into one section (item 4 below)
in the *final*, most-refined form, not the order they were said in.

**Relationship to existing docs**: `sidebar-redesign.md`'s "Dashboard Header
(Expanded)" section (full-width photo, large circular avatar overlapping the
bottom-left) is now **superseded** by item 2 below — dashboards go narrow
too, no more avatar-overlap treatment. Its "Cards rethoric" line ("no more
cards/widget feel") is the same idea item 5 below now makes concrete
(specific background/hover rules instead of a general aesthetic note).
`ofline-first-pwa.md` covers actual offline data sync (local-first CRUD +
background sync engine) — item 9's Web Push notifications and PWA icon are
additive to that scope, not a restatement of it; don't conflate the two when
picking either up.

**Known conflict, flagged not resolved**: item 4 (below) directly reverses
work shipped 2026-09-16 — plain labels, Spaces, and Projects each got their
own dedicated Kanban+Agenda page at `/settings/labels/{name}`
(`routers/labels.py::label_detail`, `routers/spaces.py`,
`routers/projects.py`, `label_kanban_detail.html`, `project_detail.html`),
plus the 2026-08-29/2026-09-13 Space/Project `icon_tile` banner treatment
and dedicated sidebar rail sections. Whoever picks up item 4 should
re-confirm the reversal's exact scope with Peter before deleting that
machinery — it's a lot of shipped, tested surface to unwind, and "final
model" language in Peter's message suggests he'd iterated past his own
earlier phrasing in the same breath.

## Build order — suggested, not mandatory

Sized the same way `audit-fixes-2.0.md` ordered its own list: cheapest/most
isolated first, biggest/riskiest last, so a session can always find a slice
that fits its remaining budget.

1. ~~**Relative-date shorthand**~~ (item 1) — **shipped 2026-09-24**, this
   session. Smallest possible slice, good session opener; see below.
2. ~~**Dashboard widget height not updating after sidebar resize**~~
   (item 3) — **shipped 2026-09-24**, same session. Root cause wasn't what
   this doc first guessed (see item 3's own entry below).
3. ~~**`main-shell-body`'s `margin-bottom: 6dvh` audit**~~ (item 6) —
   **shipped 2026-09-24**: premise was false (not dashboard-only), so
   scoped to Dashboard alone via a new `--flush` modifier once Peter
   confirmed that was the actual ask.
4. ~~**App title + PWA icon**~~ (item 8) — **shipped 2026-09-24**: title
   suffix convention resolved, PWA icon turned out to already exist —
   just needed its manifest link re-enabled.
5. ~~**Notes removal/hiding decision**~~ (item 13) — **shipped 2026-09-24**:
   Peter chose hide over remove; every HTML-visible surface (quick-capture
   marker, palette preview, global search, page navigation) turned off,
   data/routes untouched.
6. ~~**Card model removal**~~ (item 4) — **shipped 2026-09-24**: turned out
   bigger than "mechanical" once scoped (35 templates) — asked scope +
   hover questions first, Peter chose app-wide both times.
7. ~~**Icon set swap to MaterialDesign-SVG**~~ (item 5) — **shipped
   2026-09-24**: 190 icons (not ~51), all real MDI path data fetched and
   verified, not guessed. Found and fixed a pre-existing bug along the
   way (two icons referenced but never defined in the old sprite).
8. ~~**Settings `.segmented` → dropdown**~~ (item 9) — **shipped
   2026-09-24**: reused the existing single-select dropdown convention as
   expected; the Theme picker needed real JS work (no server round-trip),
   and the pass caught two real pre-existing bugs in the shared partial.
9. ~~**Design token tightening**~~ (item 12) — **shipped 2026-09-24**: scoped
   to typography (font-size/font-weight) after auditing; color tokens
   excluded (see item 12's own entry below for why).
10. ~~**Search window simplification + event "overdue" rewording**~~
    (item 11) — **shipped 2026-09-24**: footer removed and filters moved
    into its place, an explicit menu (Edit mode/Import/Export/Backup)
    added, Add label/Delete removed along with their now-dead backend
    endpoints, and the date-grouped "Overdue" bucket split from a new
    "Past" bucket so an event no longer borrows a task's wording.
11. **Labels-as-modules + sidebar/dashboard rework** (item 4 in Peter's
    numbering, renumbered 15 here) — the biggest item; almost certainly
    needs its own multi-slice breakdown (schema/module migration, then
    URL/routing collapse, then sidebar chevron fix + group pages, then
    label-pill linking). Do NOT attempt as one slice.
12. **Narrow banners everywhere, including dashboards** (item 2) — note this
    was explicitly deferred once already (`_page_header_narrow.html`'s own
    header comment, 2026-08-29: "a separate, riskier follow-up ... flagged
    in STATE.md, not done here"). Its exact scope (does "any dashboard"
    include Space/Project pages, which may not exist anymore after item 15)
    depends on how item 15 lands — sequence after it.
13. ~~**Image editor aspect-ratio lock + square avatars**~~ (item 16) —
    **shipped 2026-09-24**: ratio presets removed, avatars locked 1:1 and
    banners 5:1 in the cropper; displayed avatars stay circles (Peter's
    correction: "square" meant the crop selector, not the avatars).
14. ~~**Responsive tables**~~ — **shipped 2026-09-24**: Peter chose
    priority-based column hiding (CSS container queries, no JS) over a
    card-grid fallback, main list pages only. See the "Responsive tables"
    section below (it never had a numbered section of its own; the "(item
    11)" this line used to carry was a numbering slip -- 11 is Search).
15. **Habits/routines as a distinct frontend data model** (item 14) —
    **slice 1 of 4 shipped 2026-09-24** (Habit entity removed, shared
    `habit_view.py`, Dashboard widget now lists habit tasks); slices 2-4
    (Habits page, bigger widget, agenda/calendar + detail) in item 14's
    section below.
16. **Default dashboard layout (25/50/25)** (item 17) — depends on 15 (a
    real Habit Check-in widget, not just today's `habit_checkin.js`).
17. **Web Push notifications** (item 7) — mostly independent infra, large;
    fine to pick up anytime once someone's ready for a multi-session push
    (subscription flow, VAPID keys, a scheduler for wall-clock-timed
    notifications — verify none of that exists yet before assuming).

## 1. ~~Relative-date shorthand~~ — SHIPPED 2026-09-24

"The relative time for dates should use short form instead of long
(Tomorrow -> Tmw) so it never exceeds 5 characters." Landed as
`deps.py::_relative_date`'s two named cases shortened: `"Tomorrow"` ->
`"Tmw"`, `"Yesterday"` -> `"Yest"` (`"Today"` already fit at 5 chars,
unchanged). The day-month fallback (`"5 Sep"`, up to `"25 Sep 2027"`) was
read as out of scope — "relative time" means the three humanized words, not
the absolute short-date fallback, which is already as compact as a real
calendar date can be. `_holiday_date` (Holidays table) inherits the fix for
free since it delegates to `_relative_date`. New `test_relative_date.py`
covers all three named cases plus the fallback and degrade-on-bad-input
behavior. Full suite: 2,374 passed (2,368 prior + 6 new), 0 failed.

Note for later: `_widget_items.html`'s `relative_due` macro
("Overdue"/"Tomorrow"/"In N days") is dead code — imported nowhere, called
nowhere (grepped, confirmed 2026-09-24). Left untouched this slice (not
worth touching unused code in an unrelated pass); worth a straight deletion
whenever someone's next to that file, not a "port the character-budget fix
into it" task since nothing calls it.

## 2. Narrow banners everywhere, including dashboards

"All banners should be narrow - even on dashboard pages. Remove the avatar
from any dashboard - keep only the icon as of any narrow banner. The title
should be displayed inside the banner title like on any other narrow
banner."

Read as: every page currently rendering the full hero `page_banner()` macro
(`_page_banner.html` — Home, and today's Space/label/Project dashboards)
switches to the thin `page_header_narrow()` treatment
(`_page_header_narrow.html`) instead. Concretely:
- Home's avatar (the person's profile photo) goes away; the dashboard
  header shows only an icon (which icon — a fixed "home" glyph, or nothing
  page-specific — wasn't specified, ask).
- A Space/Project's `icon_tile` (colored squircle) likely becomes the
  narrow header's icon slot instead of the hero avatar-tile straddle.
- The title moves into `.page-header-narrow-title`, same as Tasks/
  Contacts/Calendar/Settings already render.
- The page-specific actions currently living in `page_banner()`'s caller
  slot (New widget / Add-Change banner / Reset layout, dashboard.html:40-73)
  need a new home in `page_header_narrow_actions` — that slot already
  supports arbitrary caller content (Calendar's prev/next/subnav uses it),
  so this is additive, not a new mechanism.
- Whether a per-page uploaded banner image survives at all once the hero
  cover photo goes away, or whether "narrow" banners keep the thin gradient
  background image `_page_header_narrow.html` already supports (the single
  Settings > Appearance default, not a per-page upload) is an open question
  — the per-page banner upload/edit UI (`banner_editor.html`,
  `routers/banners.py`) is substantial machinery to potentially retire.

Depends on item 15 (labels-as-modules) for exact scope — if Space/Project
dashboards stop existing as a page type, "any dashboard" narrows to just
Home (+ whatever the group pages from item 15 turn out to be).

## 3. ~~Dashboard widget height doesn't update after sidebar resize~~ — SHIPPED 2026-09-24

This doc's own first-pass guess (missing `ResizeObserver`/resize listener)
was **wrong** — `sidebar_tree.js` already dispatches a synthetic `window`
`resize` event on toggle (twice: immediately + after the 160ms width
transition), and `app.js`'s `layout()` is already wired to real `resize`
events, so re-layout genuinely does run on every sidebar toggle. Confirmed
this by instrumenting the running app with Playwright before touching
anything (`measure.js`/`measure2.js`/`measure3.js`/`measure4.js` in this
session's scratchpad) rather than guessing from the code alone — the first
few repro attempts with ordinary widget content showed no discrepancy at
all, which is what led to actually proving the mechanism rather than
settling for "should be fine."

Real bug, found once a widget's content was made tall enough to need MORE
height than a prior layout pass had already stamped onto it (`app.js`
`layout()`, the `rows.forEach` loop): each pass measured a card's natural
height via `entry.card.offsetHeight` **without first clearing the previous
pass's own `card.style.height`** — so `offsetHeight` just echoed back that
stale explicit height instead of the card's true natural height at its new
width/content. Confirmed via a direct-injection test: appending a long
paragraph to a widget card left its measured height frozen at the OLD
value even on a **fresh page reload** with the paragraph already present
(same bug, no sidebar involved) — proof this wasn't sidebar-specific, any
relayout after the first was equally stuck.

Not width-specific either: row *composition* (which cards share a row)
only depends on `window.innerWidth` (the medium-breakpoint quarter->half
promotion, the mobile single-column collapse) and each card's own
`data-span` — a sidebar toggle changes `grid.clientWidth`, not
`window.innerWidth`, so it never changes which cards share a row, only
their pixel width and (for width-sensitive content) their natural height.

Fix: `card.style.height = ""` added right alongside the existing
`card.style.width = ...` write, before the `offsetHeight` measurement pass
— one line, `app.js`'s `layout()`. Verified with the same injection test:
a card needing 603px (verified against a fresh-reload ground truth) now
reaches 603px after a sidebar toggle instead of staying stuck at whatever
height an earlier pass had set, and every prior non-reflowing test case
(plain empty widgets, the Contacts widget's container-query reflow) still
matches its ground truth exactly. Screenshotted live
(`15-biginject-expanded.png` in scratchpad) — the tall card and its
row-mate visibly share the new, correct height. No automated test added
(`audit-fixes-2.0.md` item 4's own note still holds: "No test harness for
JS behavior in this suite").

## 4. ~~Labels-as-modules + sidebar/dashboard rework~~ (final, merged form)

This merges three passes at the same idea across one message, in the most
refined form (later statements override earlier ones where they conflict):

**Module model** — replace the special-cased Space/Project concepts with
generic per-label flags/fields:
- `sidebar_pin` — shows in the sidebar rail (today's "Spaces get a flat
  sidebar rail section" special case becomes: any label with this flag set).
- `widget_pin` — eligible for the "Spaces & Projects" widget-picker view,
  which stops being reserved for is_space/is_project labels and opens to
  any label with this flag.
- `has_deadline` (bool) + `deadline_date` — today's Project-only deadline
  concept becomes a plain label field.
- `is_archived` — already exists as a real label (2026-09-21 entry #5);
  confirm this is the same flag or a new one.
- `has_dashboard` (yes/no) — if no, the label instead exposes
  `agenda_widget` / `contacts_widget` / `tasks_widget` toggles (presumably
  controlling what a chevron-expanded view or linked page shows, since a
  `has_dashboard=no` label has no page of its own per the final sidebar
  model below).

**URLs** — revert every Space/Project route back to plain `/label` (**not**
`/settings/labels/`) — undo `routers/spaces.py`/`routers/projects.py`'s
separate routing and the `is_space`/`is_project` redirects in
`routers/labels.py::label_detail`.

**Grouping** — revert to plain text-only grouping (undo whatever part of
the Space-as-parent-of-children model added structure beyond a text field).

**Final sidebar model** (the refinement that supersedes a literal reading of
"revert to plain label pages" above): text groups (what were Spaces) each
get a real page, and are the things shown as sidebar entries. Individual
labels are *not* shown as their own top-level sidebar rail items — they're
reached by expanding a group's chevron, or by clicking through a dashboard
widget. This means groups need real pages (new work — not just a revert),
and the sidebar's expand chevron (currently invisible regardless of sidebar
width, per the same message's bug report) becomes load-bearing UI, not
cosmetic, so its fix is part of this slice, not separable.

**Label pills clickable everywhere** → `/labels/x`. Resolved (see doc
intro): modal from inside a widget/card, full page from the sidebar or a
label-list view.

**Not a single-session slice.** Suggested breakdown: (a) schema/module
migration (add the new label fields, backfill from is_space/is_project/
existing deadline data), (b) URL/routing collapse, (c) sidebar chevron fix +
new group pages, (d) label-pill linking. Each of those is independently
testable and shippable.

## 5. ~~Move away from the card model~~ — SHIPPED 2026-09-24

Page background matches the theme (white/dark), not a gray card fill;
widgets render directly on the body instead of inside a bordered/shadowed
card. `.card` turned out to be used in 35 templates (settings pages, every
entity form, Calendar grids, modal bodies, published lists — not just the
dashboard widget grid), and the request's hover-animation wording was
genuinely ambiguous (keep it somewhere, or drop it everywhere) — asked
both questions before touching CSS rather than guessing at that big a
blast radius. Peter chose the broader answer both times: every `.card`
app-wide, hover dropped everywhere with no exceptions.

Landed (`static/style.css`):
- `body`/`html`'s background changed from `--bg-base` (the old gray,
  `#f2f4f7` light / `#363636` dark) to `--bg-elevated` (`#ffffff` /
  `#3e3e3e`) — the same token `.card` used to use, so the two are now
  visually identical. `--bg-base`/`--surface-0` are still defined but
  unused anywhere in the file now — left alone, token cleanup is item 12's
  job, not this one.
- `.card`'s base rule stripped to just `padding`/`margin-bottom` — no more
  `background`/`border`/`border-radius`/`box-shadow`, and its `:hover`
  rule (shadow-deepen + lift) removed outright. `.card-danger` (the
  semantic alert-color variant) is the one deliberate exception, kept
  untouched — it's a warning color, not the generic data-card surface this
  request was about.
- `.widget-card`/`.widget-card-static` lost the extra hairline-border +
  `--elevation-1` + static-hover treatment a 2026-08-30 pass had already
  given them (that pass's own "not minimalist" fix, now superseded by
  going the rest of the way to fully flat) — both classes now just
  inherit the chromeless `.card` base, no rule of their own left.
  `.widget-card--bare` (already fully flat before this change) keeps its
  one still-meaningful override, `padding:0`.
- `.modal-body .card`'s override simplified from `{border:none;
  box-shadow:none; padding:0; margin-bottom:0;}` + a now-redundant
  `:hover` rule down to just `{padding:0; margin-bottom:0;}` — the
  border/shadow neutralization is a no-op now that the base `.card` never
  sets either.

Verified live (screenshots + computed-style checks via the same
Playwright pathway as earlier slices): light mode's `.card` background is
`transparent`/`none` with `body` at `rgb(255,255,255)`; dark mode's
`body` is `rgb(62,62,62)` (`--bg-elevated`'s dark value); checked the
Dashboard, a Settings page (General), and a form modal (New Task) in both
themes — widgets and form sections now sit flush on the page, the modal
dialog itself keeps its own distinct elevated surface (untouched,
`.modal`/`.modal-dialog` never used `.card`).

Bundled: `sw.js`'s `CACHE_NAME` bump (v99 -> v100) for style.css's change,
caught in the same slice this time rather than as a later catch-up.
`test_pwa_shell.py`'s version-string assertion updated to match. No
Python test asserts CSS rule content, so the full suite (2,381 passed)
is unchanged in count — this was purely a visual verification.

## 6. ~~Icon set swap to MaterialDesign-SVG~~ — SHIPPED 2026-09-24

Turned out bigger than "mechanical" once actually scoped: the sprite held
190 hand-drawn Feather-style stroke icons (not just the ~51 hardcoded in
templates — the full `routers/labels.py::ICON_GROUPS` picker palette too),
and a partial swap would have left the app with two icon styles mixed
together (outline + filled), worse than not swapping at all. Asked before
starting whether to do the full 190-icon swap now or defer; Peter chose
now.

Process: attached
[Templarian/MaterialDesign-SVG](https://github.com/Templarian/MaterialDesign-SVG)
(shallow, blobless, sparse-checked-out to just `svg/`, ~36MB) rather than
hand-guessing path data — a guessed path would render a broken or
subtly-wrong icon, not a cheap shortcut. Built a full Feather-name ->
real-MDI-name mapping (`meta.json`'s name/alias/tag index made this
tractable), validated every candidate actually exists as a file before
using it, resolved 6 initial collisions (two names guessing the same MDI
icon, e.g. `edit`/`edit-3`/`pencil` all first landed on `pencil-outline`)
by searching for genuinely distinct real icons instead. Extracted real
`<path d="...">` data for all 190 icons and rebuilt
`templates/_icons_sprite.html` from scratch.

Real style change, not just file swap: Feather icons are stroke/outline
shapes, MDI icons are solid filled shapes. `style.css`'s `.icon` class
flipped from `fill:none; stroke:currentColor;` to `fill:currentColor;
stroke:none;` to match — one central rule governs every icon's color,
individual symbols carry no fill/stroke of their own.

Found and fixed a **pre-existing bug** along the way: a from-scratch
audit of every literal `icon(...)` call site (not just ICON_GROUPS) turned
up two icon names — `rotate-ccw`/`x-circle`, both used by
`event_detail.html`'s occurrence-override buttons — that were never
defined in the *old* Feather sprite either (confirmed against the
pre-change committed file). Both buttons silently rendered no icon at all
(`<use>` against a missing id fails silent in every browser, no console
error). Added real MDI equivalents (`restore`, alias
`rotate-counter-clockwise`; `close-circle-outline`) as part of the same
rebuild.

Verified live (screenshots + a console-error check via the same
Playwright pathway as earlier slices): sidebar rail, the full icon picker
(all category groups), Contacts' empty state, dark mode — all render
clean, distinct, no missing/broken icons, no console errors on a fresh
page load. One test regression caught and fixed: the new sprite's header
comment quoted event_detail.html's exact button label text ("Restore to
series"), which — since the sprite is included on every page via
base.html — collided with a `test_manual_recurrence_exceptions.py`
assertion checking that text was ABSENT from a different page's body;
reworded the comment to describe the buttons without quoting their exact
label strings. Full suite: 2,381 passed (unchanged count — this is a
template/CSS-only change, no Python logic touched).

Bundled: `sw.js`'s `CACHE_NAME` bump (v100 -> v101) for `style.css`'s
`.icon` class change (`style.css` is in `SHELL_ASSETS`; `_icons_sprite
.html` itself isn't a separately-fetched `static/` asset — it's a Jinja
template inlined into every page's own HTML, so it needs no cache-bust of
its own). Checked `SHELL_ASSETS` membership before concluding this,
per this session's own established habit. `test_pwa_shell.py`'s
version-string assertion updated to match.

## 7. Web Push notifications

Leisure/sleep-time start, event start, tasks due today (generic phrasing
when more than one — "you have multiple tasks due today," not a list),
habits due today. Tone: motivational, not a burden/nag.

**Hard constraint, direct request**: notifications must not invent a new
reminder mechanism except for leisure/sleep-time start. Events, tasks, and
habits ride on an existing "reminder" concept that — per this instruction —
should already exist or needs to be added as the one shared primitive
("events should from now on have reminder set on start, tasks and habits
[reminder] on the date due"). Verify what reminder infrastructure (if any)
already exists before building a second one; if none exists yet, that's the
one new mechanism this item is allowed, in addition to leisure/sleep.

Needs: a Web Push subscription flow (check `sw.js`'s current scope/what it
already handles), VAPID key generation + storage (Settings?), a
server-side scheduler capable of firing at specific wall-clock moments (no
existing background scheduler in this app as of 2026-09 — confirm, don't
assume), and copy for each notification type. Large, mostly new
infrastructure — budget multiple sessions.

## 8. ~~`main-shell-body`'s `margin-bottom: 6dvh`~~ — SHIPPED 2026-09-24

"If `main-shell-body` is only used in dashboard pages, remove the
`margin-bottom: 6dvh`." Conditional on the audit — the premise didn't
hold: `.main-shell-body` is genuinely applied on four page shapes, not
just Dashboard — `_tasks_body.html` (`#tasks-body`), `_contacts_body.html`
(`#contacts-body`), `_notes_body.html` (`#notes-body`), and
`dashboard.html`'s widget-grid wrapper — all sharing the one "flex shell"
rule style.css documents at `.main-shell-body{...}` (2026-09-07, "extend
Calendar/Planner's viewport-fit model to every page with a clear
header+scrollable-body shape"). `labels_manage.html` still turned up in a
grep for the class name, but only inside a comment explaining it
*opted out* of this shell 2026-09-08 — it doesn't actually carry the class.

Reported first without changing anything (the condition was false, so a
blanket removal would've been wrong); Peter then confirmed the real ask —
Dashboard specifically needs the margin gone regardless ("that bottom
margin creates a veil that hides content ... it doesn't exist for
dashboard pages"), Tasks/Contacts/Notes untouched.

Landed as a second class, `main-shell-body--flush` (`style.css`), added
alongside `main-shell-body` on `dashboard.html`'s widget-grid wrapper only
— `margin-bottom:0` overrides the shared rule's `6dvh` there, every other
`.main-shell-body` rule (flex sizing, `overflow-y:auto`) stays shared.
Verified live: the wrapper's computed `margin-bottom` is `0px` on
Dashboard, still `42px` (6dvh at a 700px test viewport) on Tasks,
unchanged.

## 9. ~~App title + PWA icon~~ — SHIPPED 2026-09-24

Two open questions asked and resolved before touching anything:

1. **Title scope** — literal "constant" reading (always just "Curodav",
   no per-page text) vs. "Curodav" appended to each page's own title.
   Peter picked appended, matching the existing "Appearance - Settings"
   sub-page convention.
2. **PWA icon** — turned out to already be fully built (`icon-192.png`/
   `icon-512.png`, real custom artwork, `manifest.webmanifest` with both
   sizes) but never linked: `base.html` had `<link rel="manifest">` and
   `<meta name="theme-color">` sitting inside a `{# PWA shell (1.8 slice
   3) -- DISABLED #}` Jinja comment. Favicon/apple-touch-icon were already
   live and unaffected either way (separate `<link>` tags, outside that
   comment). Confirmed via `routers/pwa.py`'s own header comment that this
   manifest link is unrelated to the client-side "Offline Mode" feature
   purged 2026-09-09 for UI complaints (a different surface: the `/offline`
   page, IndexedDB write queue, offline-navigation fallback) — asked
   whether to re-enable just the manifest link (icon/name metadata only,
   no service worker) or leave it off; Peter chose re-enable.

Landed:
- `base.html`'s `<title>` — `{% block title %}{% endblock %}{% if
  self.title() %} - {% endif %}Curodav`. Every page's existing
  `{% block title %}` override still works unchanged (no template beyond
  `base.html` needed touching — `self.title()` just calls the same block),
  now with " - Curodav" appended; a page with no override falls back to
  plain "Curodav" (no "Curodav - Curodav" duplication).
- `base.html`'s `<link rel="manifest">` + `<meta name="theme-color">`
  un-commented. `pwa.js`'s `<script>` tag (service-worker registration)
  deliberately left commented — out of scope, per the resolved question.
- `manifest.webmanifest`'s `name`/`short_name`: `"Command Center"` ->
  `"Curodav"`.

Verified live: `Dashboard - Curodav`, `Tasks - Curodav`,
`Appearance - Settings - Curodav` (three different pages, all correctly
suffixed); the manifest fetches at 200 with `"name": "Curodav"`; full
suite still 2,374 passed including all 15 `test_pwa_shell.py` cases
(`test_base_html_links_the_manifest_and_theme_color` passed both before
and after this change either way — noted for the record, not fixed here,
since it's out of this slice's scope: it reads `base.html`'s raw source
text rather than a rendered response, so it can't actually distinguish
"commented out" from "live," which is why it never caught the manifest
link being disabled in the first place).

## 10. ~~Settings `.segmented` → dropdown~~ — SHIPPED 2026-09-24

"Instead of having `class="segmented"` in the settings, I would much rather
prefer drop down menu with select one (radiobox drop down menu)." Scoped
to the two Settings pages that actually had `.segmented` (`settings_general
.html`, `settings_appearance.html`, 8 controls total) — the other 8 files
using `.segmented` app-wide (event form, tasks toolbar, widget builder,
calendar month, contacts list, quick add, time block modal) are outside
Settings and untouched, per the request's own "in the settings" wording.

An existing select-based convention already existed exactly as the doc's
own note anticipated checking for: `_widget_list_multiselect.html`'s
`ms_mode="single"` (built 2026-08-07 for the widget builder's View/Range
fields specifically *because* a native `<select>`'s open dropdown list is
unstyleable browser chrome — see that partial's own header comment). Added
one new capability to reuse it here: `ms_bare` (skips the partial's normal
`.field`/`<label>` wrapper, since a `.settings-field-row` already has its
own label to the left) and `aria-label="{{ ms_label }}"` on the trigger
button (the wrapper's label previously had no programmatic association
with it at all, in *any* caller — a small accessibility improvement that
falls out of this pass, not scoped to just the new bare mode).

Landed: all 6 of `settings_general.html`'s autosubmit radio groups (Week
starts on, 4-Week view position, Recurrence/Habit-streak terminology, Time
format, Hide sleep hours) and `settings_appearance.html`'s 2 autosubmit
on/off rows (Show icons next to labels, Edit mode) now use `ms_mode
="single"` + `ms_autosubmit` + `ms_bare` — same `data-change-submit`
delegated listener as before, same instant-autosave behavior, just a
dropdown trigger instead of a row of pill buttons.

The Theme picker (System/Light/Dark) needed real work, not just a markup
swap: it's the one settings control with no server round-trip at all
(`window.CCTheme`, a pure client-side localStorage choice, so
`ms_autosubmit`/`ms_form_id` don't apply). Rewrote `static/app.js`'s theme
block to drive the new `.theme-select` radio dropdown instead of the old
`data-theme-choice` buttons: which radio is checked is now native
radio-group behavior (no JS needed), the trigger's summary text is kept in
sync for free by app.js's own generic `.widget-list-multiselect` change
listener (any multiselect on the page gets this, this one included), and
the theme block only still owns applying `data-theme` to `<html>` +
persisting to localStorage + correcting the initially-checked radio at
page load (the server can't know localStorage's content, so it always
renders "System" checked and JS corrects it before the user sees a
mismatch). The one thing this needed to get right *on its own*: the
generic multiselect panel gets portaled out to `#multiselect-portal` while
open (`static/app.js`'s existing portal mechanism, shared with every
other dropdown), so an ancestry-based selector like `.theme-select
input[...]` silently stops matching the moment the panel is ever opened —
the new document-level change listener matches on the flat, portal-proof
`input[name="theme"]` instead (a name unique to this one control
app-wide), the same reasoning `data-change-submit`'s own listener already
uses.

**Found two real bugs along the way, both fixed as part of this pass:**
1. Jinja's `{% set %}` isn't scoped to the `{% include %}` it precedes — a
   value set before one `_widget_list_multiselect.html` include stays set
   for every *later* include of the same partial lower in the same
   template, unless explicitly cleared. Caught live: `ms_root_class =
   'theme-select'` (set for the Theme dropdown) silently leaked into
   `settings_appearance.html`'s next two dropdowns below it (Show icons
   next to labels, Edit mode), until an explicit `{% set ms_root_class =
   '' %}` right after Theme's own include cleared it back out. **Likely
   pre-existing elsewhere too**, not fixed here (out of scope): `_widget_
   builder_fields.html`'s Width dropdown doesn't set its own
   `ms_root_class` and sits right after Range's (`'widget-range-select'`),
   so it's probably inheriting a class that names the wrong field —
   flagged, not investigated further, since fixing it needs confirming
   what (if anything) actually depends on Width's `ms_root_class` being
   absent.
2. `_widget_list_multiselect.html`'s single-mode `_sel_item` lookup falls
   back to `ms_items | first` whenever `ms_selected` is falsy — which an
   empty-string "Off"/"none" value always is. Every *existing* caller with
   an empty-string value happened to already list that item first in
   `ms_items` (accidentally, not by documented convention), which is
   exactly why this never surfaced before. Followed the same workaround
   for all three On/Off rows converted here (Off listed first) rather than
   changing the partial's shared fallback logic, which other callers
   (View/Range) deliberately rely on for a different, genuine "no
   selection yet, default to first" case — documented in each affected
   row's own comment, not just here.

Verified live (same Playwright pathway as earlier slices): opened each
dropdown and confirmed real radio inputs render in a panel (screenshotted);
picked Sunday on Week-starts-on and confirmed it autosubmitted and the
trigger updated; picked Dark on the Theme dropdown and confirmed the whole
page switched to dark mode immediately, `localStorage`/`data-theme` were
set correctly, and — after a full page reload — the dropdown still showed
"Dark" checked correctly (proving the page-load sync logic works, not just
the live-pick path). Confirmed "Show icons next to labels"/"Edit mode"
render their own correct state independently once the `ms_root_class` leak
was fixed (they'd both been silently showing Theme's dropdown state
before that fix).

Bundled: `sw.js`'s `CACHE_NAME` bump (v101 -> v102) for `app.js`'s theme
block rewrite; `test_pwa_shell.py`'s version string updated. Two existing
tests updated for the new markup (`test_calendar_fourweek.py`'s exact-
adjacent-string assertion loosened to a small-gap regex since `checked` no
longer sits right after `value=`; `test_phase8_settings_hub.py`'s theme
test renamed and rewritten for `.theme-select`/real radio values instead
of `id="themeSegmented"`/`data-theme-choice`). Full suite: 2,381 passed
(unchanged count, both updates replace prior assertions rather than adding
new ones).

## 11. ~~Search window simplification~~ — SHIPPED 2026-09-24

Request: remove the search modal's footer; move filters into that space
instead. Add explicit menu actions beyond search itself — Edit mode
toggle, Import/Export/Backup — reachable from the same surface. Remove the
"Add label" and "Delete" buttons from the search window. Separately: redo
"overdue" wording — events can't be overdue, they just pass, so an event's
status label needs its own wording distinct from a task's "Overdue."

**Footer removed, filters relocated**: `.command-palette-footer` (↑↓/↵
keyboard hints + standalone New task/New event buttons) deleted outright
from `base.html`/`style.css`/`command_palette.js`; the type filter pills
moved from above the results list to that now-vacated space below it
(border flipped bottom→top to match). New task/New event stay reachable
everywhere else they already were — the "Create task/event: '<query>'"
rows once a title's typed, the mobile bottom-sheet's own buttons — so
losing the footer-only, nothing-typed-yet shortcut is the actual
simplification, not a capability loss.

**Explicit menu actions added**: a kebab (`.action-menu`) in the input
row, reusing the exact dropdown convention `settings_data_maintenance.html`'s
Backup/Sync/Database menus already use rather than inventing a second
pattern — `app.js`'s existing `initActionMenus()` binds it for free. Items:
Edit mode toggle (same `POST /settings/edit-mode` the pre-existing typed
"edit mode" row already used, now also reachable without typing),
Export data…/Import data… (`/export/modal`, `/export/import-modal`, both
`data-modal`), Download full backup (`/export/data.json`).

**Bug found and fixed before it shipped**: reusing `.action-menu` inside
the command palette broke silently at first — `.action-menu-panel`'s own
`--z-overlay-panel` token (150) sits *below* `.command-palette-overlay`'s
`--z-modal-stacked` (200), so the opened menu painted invisibly behind the
palette's own scrim. Caught live (Playwright screenshot showed nothing,
even though `getComputedStyle` reported the panel as open/visible/
correctly positioned — a pure stacking-order problem, not a logic one).
Fixed with a new `.command-palette-menu-panel` modifier class (kept
through `app.js`'s `document.body` reparent-on-open, since that only
moves the node, not its `className`) whose own rule bumps just this one
panel to `--z-top`, rather than raising `--z-overlay-panel` itself and
pushing every other portaled dropdown (`.multiselect-panel`,
`.color-popover`, `.dtp-panel`) above the command palette too.

**Add label / Delete removed**: the overlay's third mode (label mode,
entered from a result row's own "Add label" button) is gone along with
its one entry point (`enterLabelMode`/`assignLabel`/the whole
`mode === "label"` branch in every function that checked it) — genuinely
dead code once the button was gone, nothing else could reach it. The two
backend endpoints that existed only to serve it,
`GET /api/labels`/`POST /api/entities/{type}/{uid}/labels`
(`routers/search.py`), are removed too — confirmed via grep that
`command_palette.js` was their only caller before deleting. Delete's own
client code (`deleteEntity`/`deleteUrl`) went with it; the per-type
`/delete` routes themselves are untouched (still used by each entity's own
detail page). `buildActions()` now returns `null` (no actions row at all)
when there's nothing left to show — an already-done task, or any event/
contact row, since Mark done is the only action left and it's task-only.

**"Overdue" now task-only**: `command_palette.js`'s date-grouped results
used one shared "Overdue" bucket/header for both a late task and a past
event — wrong, an event just passes, it doesn't carry a task's "unmet
obligation" framing. `dateBucket()` now takes the row's `type` and splits
what was one bucket into "overdue" (tasks) and "past" (events), each
getting its own header when both are present. Scoped to exactly this one
surface after auditing every other "Overdue" site in the app
(`_widget_agenda.html`'s `overdue_table`, `_widget_at_a_glance.html`'s
stat) — both were already task-only, no bug there; `_widget_items.html`'s
`relative_due` macro is unrelated dead code (unchanged, still unused).

**Verified live** (Playwright, same pathway as every other slice this
session): kebab menu opens with all four items and no longer renders
behind the scrim; a seeded overdue task and a seeded past event land under
separate "Overdue"/"Past" headers in the same query's results; a task
result shows exactly one action button ("Mark done"), an event/contact
result shows none; footer is gone from the DOM, filters render `display:
flex` below the results list.

**Tests**: `test_command_palette_actions.py` lost its `TestApiLabels`
(4 tests) and `TestAddEntityLabel` (8 tests) classes with the removed
endpoints — the file is now just the still-valid title-prefill coverage.
Two count-based assertions elsewhere broke because the command palette's
new Export/Import menu items are base.html-wide, so they now appear on
*every* rendered page, not just the Sync card's own settings page —
`test_phase8_settings_hub.py` and `test_data_health.py` (the one test
class in that file that renders through Jinja, not the sibling class that
reads raw template source and was rightly left at `== 1`) updated from
`== 1` to `== 2` with a comment explaining the second occurrence is a
legitimate second entry point, not a same-page duplicate. Full suite:
**2,369 passed, 0 failed** (2,381 prior − 12 removed + 0 net new).

Bundled: `sw.js`'s `CACHE_NAME` bump (v103 → v104); `test_pwa_shell.py`
updated to match. `documentation/features/tasks.md`'s "Search & the
command surface" section rewritten to match current behavior (Add label/
Delete removed, footer/filters/menu changes, overdue/past split, and a
stale Notes/Add-label cross-reference from an earlier slice fixed in
passing).

## 12. ~~Design token tightening~~ — SHIPPED 2026-09-24

Request: cap most token categories at ~3 options: ~3 font families, ~3 font
sizes, ~2 font weights, and reduce to two consistent "role" colors — one
guaranteed-legible active/foreground text color, one consistent background
(the example given: the sidebar's own text-on-background pairing).

**Scoped to typography only** (font-family, font-size, font-weight) —
color tokens deliberately excluded. Audited `style.css`'s color system
first: the app-model/tag/calendar-accent palettes (16 `--cal-bg-*`/
`--cal-accent-*` pairs, each label/tag's own identity color) and the
semantic status colors (`--danger`, `--accent-neutral`, etc.) aren't
decorative excess — each one carries real meaning (which label is which,
what a status means) that a 2-color system would erase, not simplify. A
16-color palette compressed to "two role colors" would break label/tag
disambiguation outright. Flagging this as its own decision rather than a
silent scope cut: if Peter meant the color reduction literally (labels/
tags/calendar too), that's a much bigger, separately-justified change and
should come back as its own slice with its own question, not be folded
into this one via a unilateral read of "somewhat like."

**Font family**: already compliant — one real family (`--font-system`,
used everywhere) plus one raw `monospace` fallback used in exactly one
place (a `font-family:var(--font-mono, monospace)`-style rule that was
actually already dead — see item 3/timeline note below). 2 font "options"
total, no change needed.

**Font size**: audited to 8 tokens before this slice (`--text-xs` 13px,
`--text-sm` 14px, `--text-base` 15px, `--text-md` 15.5px, `--text-lg`
17px, `--text-xl` 18px, `--text-2xl` 21px, `--text-3xl` 26px — the last
completely unused). Consolidated to 4, not the requested 3 — a real
constraint blocked the third cut: merging `--text-xl` UP into `--text-
2xl`'s 21px (the more obvious "9 -> fewer, evenly spaced" move) would
push `.page-header-narrow h1`'s text past its container — that class is a
fixed `height:48px; overflow:hidden` bar used as nearly every page's
title, deliberately height-capped and already tightly tuned. Went the
other direction instead: `--text-2xl` merged DOWN into `--text-xl` at
18px. `--text-2xl`'s other call sites (`.modal-header h1`, `.detail-
heading-row h1`, the page-banner title, the auth brand) all sit in
auto-growing, padding-based containers with no clipping risk, so
absorbing them cost nothing. Final 4: `--text-sm` 13px (was xs+sm merged,
13px kept as the more common of the two), `--text-base` 15px (was
base+md merged, 15.5 was barely distinguishable from 15), `--text-lg`
17px (unchanged, kept standalone — genuine step between body and heading
text), `--text-xl` 18px (was xl+2xl merged). Every `var(--text-xs)` /
`var(--text-md)` / `var(--text-2xl)` call site across `style.css` updated
via scripted find-replace (53/9/5 occurrences respectively), verified
by before/after count.

**Font weight**: not tokenized at all before this slice — 4 raw literal
values in use (400/500/600/700) across 114 call sites, `font-weight:X`
and `font-weight: X` (with-space) both present. New tokens `--font-
weight-regular:400` and `--font-weight-bold:600`. 400 kept standalone
(the real "unemphasized" weight — body/placeholder text); 500/600/700
folded into one `--font-weight-bold` step at 600, since all three were
doing the same "heavier than body text" job at slightly different values
depending on which pass wrote that rule, not a deliberate 3-step
hierarchy. All 114 occurrences replaced with the matching token via a
scripted regex pass; verified zero raw `font-weight:<number>` literals
remain.

Along the way, fixed several comments that had gone stale from the exact
token values they described (pre-existing staleness in some cases, newly
stale from this slice's own change in others) — near `.timeline-canvas`
(a `--font-mono` fallback claim that was never true, plus this slice's
own `--text-xs` -> `--text-sm` rename) and near `.widget-content`'s row
list (a "14px, was 15.5px" comment that's now "13px, merged token"). Left
one older, unrelated stale comment alone (`.dtp--compact .dtp-trigger`'s
own comment references a `--text-caption` token that was never real in
the current system — predates this slice, out of scope for it).

**Verified**: full test suite green (Python has no CSS-value assertions,
so this is a source-correctness check, not a visual one — see below).
`grep` confirmed zero remaining `var(--text-xs|--text-md|--text-2xl|
--text-3xl)` and zero remaining raw `font-weight:<digits>` literals
outside the two new token definitions themselves.

Bundled: `sw.js`'s `CACHE_NAME` bump (v102 -> v103); `test_pwa_shell.py`'s
version string updated to match.

## 13. ~~Notes: remove or hide from the app's HTML~~ — SHIPPED 2026-09-24

"REMOVE THE NOTES (OR HIDE THEM) FROM THE APP'S HTML" — genuinely
ambiguous which, so asked before implementing rather than guessing between
a data-destructive removal and a cosmetic hide. Peter chose hide: existing
notes, `/notes` routes, and `db.py`'s note functions all stay intact and
fully reachable directly; only the creation-by-marker and
search-visibility surfaces turn off.

Audited every HTML-visible surface first (Notes had no sidebar nav entry
to begin with):

1. Quick Capture's `!n` marker (`src/quick_capture.py`) — creates a note
   from the command palette's single-field input.
2. The palette's own live capture-preview gate
   (`static/command_palette.js`'s `CAPTURE_MARKER_RE`) — shows a "Note:
   ..." preview row as you type `!n`, before you even submit.
3. Global search (`routers/search.py`'s `db.search_entities` call, both
   `/api/search` and `/search`) — notes were a fourth searchable type
   alongside tasks/events/contacts.
4. `_STATIC_PAGES`' synthetic "Notes" destination — the command palette's
   page-navigation feature (2026-08-15) listed `/notes` as a jump target
   even with no query.

Landed:
- `quick_capture.py`: `"n"` dropped from `MARKER_TYPES`/`_MARKER_RE`.
  `parse_note` (the pure per-type parser) is untouched and still directly
  callable/testable — only the marker-driven entry point (`_find_marker`)
  can no longer reach it. Typing `!n ...` now gets the same "no entity
  marker found" error any unrecognized marker gets.
- `command_palette.js`: `"n"` dropped from `CAPTURE_MARKER_RE` — the same
  input now falls through to a plain search/create-suggestion state
  instead of a capture preview that would 400 on submit. Verified live:
  typing `!n Some new note text` in Ctrl-K shows ordinary "Create task:
  ..." / "Create event: ..." suggestions, no broken dead end.
- `routers/search.py`: new `_GLOBAL_SEARCH_TYPES = ["task", "event",
  "contact"]`, used as the default for both `/api/search` (when the
  caller passes no explicit `types`) and `/search` — `db.search_entities`
  itself is untouched, so an explicit `types=["note"]` request still
  finds notes (verified with a direct test). `_STATIC_PAGES` lost its
  "Notes" entry.

Verified live (same Playwright pathway as earlier slices): created a note
via the still-live `/notes/new` form, confirmed it renders on `/notes`,
then confirmed `GET /api/search?q=<its content>` returns `[]`. New tests:
`test_quick_capture_parser.py`'s `TestNotes` rewritten for the new
"marker not recognized" behavior plus a new `TestParseNoteDirectly`
(bypasses the marker gate, proves `parse_note` itself still works —
re-enabling later is a two-constant revert, not a rebuild);
`test_quick_capture.py`'s `TestCreateEndpointNote` rewritten the same way;
`test_search_api.py` gained a `_seed_note` helper and five new tests
(excluded by default, still reachable explicitly, `/search` page too,
`_STATIC_PAGES` no longer lists "Notes"). Full suite: 2,381 passed
(2,374 prior + 7 net new).

Also bundled into this slice: `sw.js`'s `CACHE_NAME` bump (v98 -> v99) —
caught two earlier missed bumps from this same session (app.js's masonry
fix, manifest.webmanifest's name change) alongside this slice's own
`command_palette.js` change, per this file's own repeatedly-reinforced
"bump on every static-asset change expected to be visible immediately"
convention (see `sw.js`'s v97/v98 comments — the same lesson keeps
recurring). `test_pwa_shell.py`'s version-string assertion updated to
match.

`quick-capture.md` (the reference spec doc) got a status update at its
top rather than being rewritten past-tense, matching how it already
documents the gap between the v1 spec and what shipped.

## 14. Habits/routines as a distinct frontend data model — IN PROGRESS (slice 1 shipped 2026-09-24; H1-H8 planned)

"I also think that we strongly need to make habits/routines a different
data model, at least in the frontend. They can still be tasks in the
backend, but I think that habits need to be incorporated much more into the
UI." Audit `test_habit_ui_rework.py`, `test_habits_router.py`,
`test_tasks_habits_view.py`, `test_tasks_table_habits_split.py`, and
`static/habit_checkin.js` first — there's already some habit-specific UI
surface; this item is about how much further it needs to diverge from a
plain task's presentation, not a from-scratch build.

**Audit (2026-09-24).** Two habit backends were running side by side:
(A) standalone Habit entities (`habits`/`habit_entries` -- color, icon,
per-entry note, `/habits/{uid}` detail page) with **no creation path left
in the UI** (`/habits` redirected to `/tasks`, `/habits/new` unlinked); and
(B) habit-labeled tasks (`tasks` + `task_completions.value`, with
`target_per_day`, recurrence, weekend/holiday exclusions, work sessions) --
the only kind Tasks' "+ Add habit" creates. The Tasks table merged both
into one Habits group, but the **Dashboard Habit Check-in widget read only
(A)** (`db.list_habits`), so every habit created through the UI never
appeared in it; its empty state pointed at "Settings", which has no habit
creation either.

**Peter's answers (asked first, three questions):**
1. Collapse: "I have no real entities" -- delete the entity path outright,
   no migration.
2. Placement: a **dedicated Habits page** (habits leave the Tasks table).
3. Surfaces: a **bigger check-in widget**, **habits in agenda/calendar**,
   a **habit-specific detail** view -- with a reference app for good
   habit/routine tracking UX: https://inlitx.github.io/streak/ (blocked by
   this environment's network egress policy on 2026-09-24 -- not yet
   looked at; ask Peter for screenshots or to allow the host before
   designing slices 3-4).

**Target model.** Backend: a habit-labeled task is the only habit.
Frontend: one habit view-model (`src/habit_view.py::habit_items` -- title,
cadence label, target, today's value, next value, streak, check-in URLs)
that every habit surface renders from; no habit surface ever shows task
fields (status, due date, Kanban).

**Slices:**
1. ~~Entity removal + shared view-model + widget fix~~ — **shipped
   2026-09-24.** `habit_view.py` added (`habit_items`/`habit_item`, plus
   `excluded_dates_for_row` moved from routers/tasks.py); Tasks' Habits
   group and the Dashboard widget both render from it, so the widget now
   lists habit-labeled tasks and checks in via
   `/tasks/{uid}/completion/{date}/toggle` / `/tasks/{uid}/completions`.
   Removed: `routers/habits.py`'s CRUD/entries/update-field/detail
   endpoints (every `/habits...` GET now 302s to `/tasks`),
   `habit_form.html`, `habit_detail.html`, `_habit_detail_body.html`,
   `static/habits.js`, db.py's entity accessors (`upsert_habit`,
   `list_habits`, `upsert_habit_entry`, `toggle_habit_entry`, ... plus the
   now-callerless `_apply_tags_and_project`), `_habit_row.html`'s
   `kind=entity` branches, `/tasks/bulk`'s `habit_uids`, tasks_table.js's
   `updateHabitField`/`selectedByKind`. The `habits`/`habit_entries`
   tables stay in SCHEMA_SQL (never force-dropped).
2-4. Superseded by the Streak-informed plan just below (same goals --
   Habits page, bigger widget, agenda/calendar + habit detail -- re-cut
   into H1-H8).

### Streak-informed habit plan (2026-09-24)

Reference: Peter pasted the README of InlitX/streak (Flutter, offline,
GPLv3) -- the site itself is blocked from this environment. That's a
feature list, not the design; the screenshots it names (Today, Stats,
Insights, Amounts, Notes) weren't visible, so the *look* below is
inferred from the feature descriptions and this app's own conventions,
not copied.

**What Streak gets right, as principles** (these drive every slice):
- *One tap from wherever you are* -- logging never needs a page load or
  a modal (home screen, widget, notification).
- *The schedule defines the streak* -- "3x a week" or "Mon/Wed/Fri" is a
  first-class schedule, and a streak only counts days the habit was due.
- *Honest history* -- any past day can be filled/cleared, days can carry
  a note, and a pause (vacation) doesn't break anything.
- *Progress is the reward* -- activity grid, month calendar, streak/best/
  completion rate/strength score, a small celebration when a day is fully
  done.

**Where curodav stands** (after slice 1): one-tap check-in exists (widget
+ Tasks Habits group, fetch-based); amount habits exist (`target_per_day`
> 1, no unit); past-day fill exists (53-week heatmap toggle -- but the
detail modal's heatmap is view-only since 2026-08-29); weekend/holiday
exclusions exist; current/longest streak exist; recurrence is a full
RRULE (daily / weekly / BYDAY / INTERVAL). **Real bug**: `habit_heatmap.
streaks()` walks calendar days only -- a weekly or Mon/Wed/Fri habit
"breaks" its streak on every non-scheduled day, so the numbers are wrong
for any non-daily habit today. Verified 2026-09-24 against the real function:
a weekly habit logged on 4 consecutive Mondays -> `(current 0, longest
1)`; a Mon/Wed/Fri habit with every due day kept for two weeks -> `(1, 1)`.

**Adopt** (fits a single-user, server-backed web app):

| # | Slice | What | Backend change |
|---|---|---|---|
| H1 | Schedule-aware streaks | Streak counts *due occurrences*, not calendar days: RRULE BYDAY/INTERVAL days via `recurrence_expand`; "X times per period" counts a week/month as kept when X logs land in it (streak unit = periods). Completion rate = done / due. Fixes the bug above | new `habits_per_period` column (nullable int) on `tasks` + period on the existing RRULE FREQ; pure-function rewrite of `streaks()` with the old daily behavior as the FREQ=DAILY case |
| H2 | Habits page `/habits` | Replaces the redirect; nav rail entry; Habits group leaves the Tasks table. Layout: "Today" list on top (due today first, then not-due-today muted, done last), each row = name, 7-day strip (tap a past day to fill/clear), streak, one-tap check / +1 | none (reads `habit_view`) |
| H3 | Habit detail modal | Habit-only: header stats (current / best streak, completion rate, total), **interactive** year grid (re-enable day toggle), month calendar view, per-day note | `task_completions.note TEXT` (nullable, additive) |
| H4 | Bigger Check-in widget | Same row shape as H2 (7-day strip + streak), sized for the 25% column; "all done today" state with a small celebration (CSS-only, `prefers-reduced-motion` respected) | none -- unblocks item 15 |
| H5 | Habit kinds | *amount* gets a unit ("glasses", "min"); *avoid* habits (log a relapse; streak = days since last relapse, done-by-default) | `tasks.habit_unit TEXT`, `tasks.habit_kind TEXT` ('normal'/'avoid') |
| H6 | Pause (vacation) | Date-range pause per habit (or all habits): paused days behave exactly like today's excluded weekend days | `habit_pauses(task_uid, start, end)` feeding `excluded_dates_in_range` |
| H7 | Agenda/calendar | Due-today habits appear as checkable items in the Agenda widget and the calendar day view (not as timed events) | none |
| H8 | Insights | Strength score (Loop-style exponential moving average of done/due, so one miss dents rather than zeroes), completions per month, "when do you show up" by hour from `task_completions.completed_at` (already stored) | none |

**Adapt, depends on other items:** reminders with Done / Snooze / +1
actions ride on item 7 (Web Push) -- design H1's schedule so the reminder
scheduler can reuse "is this habit due today". Archive-without-losing-
history already works (task status `archived` keeps `task_completions`),
it just needs surfacing on the H2 page (an "Archived" fold).

**Skip, with reasons:**
- *Focus/Pomodoro timer, soundscapes, clock styles* -- a separate
  product; curodav's work sessions (time allocations on the calendar)
  already cover "time spent on a habit". Revisit only if asked.
- *Checklists inside a habit* -- tasks went flat on purpose (1.2 task-
  model decision; checklist items were removed). Re-adding them for
  habits only would reverse that; ask Peter before considering it.
- *Import from Loop/HabitKit/Habitica, app lock, launcher icons, three
  whole-app designs, gamification island, shareable image cards* --
  either phone-app concerns or out of proportion for a single-user app.
  CSV import could come later if Peter actually has history elsewhere.

**Order and why:** H1 first -- every later surface shows streaks, and
they're wrong today for non-daily habits. H2 (the page), then H3
(detail + notes, the only real schema growth besides H5/H6), then H4
(widget, unblocks item 15's layout), then H5-H8 in any order. Each is one
session. **Open questions for Peter before H1/H2**: (1) do "X times per
week" habits matter to you, or are RRULE weekdays enough? (2) avoid
habits -- wanted? (3) should the Habits page replace the Tasks-table
group outright (plan assumes yes, per your earlier answer)?

## 15. Default dashboard layout

New default widget layout for Home:
- 25% Today Agenda (tasks + events)
- 50% Stack "At a glance" + Upcoming (tasks + events)
- 25% Habit Check-in

Depends on item 14 landing enough that "Habit Check-in" is a real,
sizeable widget rather than today's `habit_checkin.js` behavior (audit what
that script currently does before assuming it needs to be built new).
Interacts with the same masonry/widget-grid code item 3's bug lives in —
sequence after item 3's fix so the new default layout isn't tested against
a known-broken resize path.

## 16. ~~Image editor: aspect-ratio lock + square avatars~~ — SHIPPED 2026-09-24

**What shipped** (asked three questions first -- answers below override
the original request text further down where they differ):
- `avatar_cropper.js`: the Free/Square/4:3/16:9/Banner preset buttons are
  gone. Each kind has one locked ratio in `KIND_CONFIG` (avatar `1`,
  banner `5`), named read-only in the toolbar (`.cropper-ratio-label`).
  The resize math was rewritten so no drag can break it: a pure n/s handle
  drives height, every other handle drives width, the size is capped by
  the room on the side being dragged toward (measured from the edges that
  stay put), and `clampBox()` shrinks both sides together -- the old one
  clamped each axis alone, which was how a drag past the canvas edge used
  to squash a "locked" ratio. Output height is derived from output width,
  so the saved file is exactly 1:1 / 5:1 (verified: 240×240, 400×80).
- **Square = the crop selector, not the avatars** (Peter's own answer:
  "The crop border selector should be square. Not the avatars that are
  displayed in the app"). `.avatar-circle` is untouched everywhere; the
  crop box itself was already a rectangle (no circular framing to remove),
  so locking it 1:1 was the whole change.
- **Banners**: cropper locked to 5:1 (matches desktop `.page-banner`);
  phones keep displaying at 3:1 with `object-fit:cover` trimming the sides
  -- Peter chose this over making phones 5:1 too.
- **No server-side crop** (Peter's choice): images that never pass the
  cropper (CardDAV-synced contact photos, banners/profile photos uploaded
  before this) keep their stored bytes; they already *display* at the
  right shape via `object-fit:cover`.

**Verified live** (Playwright): fed a 900×400 image to a contact's avatar
input and a 400×700 image to the banner editor, then dragged every handle
type including far past the canvas edges and moved the box off-canvas --
ratio stayed 1.000 / 5.000 and the box stayed inside the canvas throughout.
`test_image_cropper_ratio.py` pins the source contract.

Original request text:

- Remove "free aspect ratio" as an option in the image editor entirely —
  every editable image type gets a fixed, enforced ratio (`avatar_cropper.js`
  currently offers free-form resize per the request: "persistent aspect
  ratio despite any attempts to resize").
- Enforce the banner aspect ratio on every banner in-app (uploads that don't
  match today apparently get displayed as-is — "the truth is not always
  there").
- Still allow any image to be applied even when it doesn't natively match
  the target ratio — crop/fit at upload time, don't reject the file.
- Avatar / 1:1-ratio images: aspect ratio is not user-editable (always
  square), and render as a **square**, not a circle — both the final
  rendered avatar (retire `.avatar-circle` for the 1:1 case) and the
  cropper's own UI (the crop overlay shouldn't imply circular framing while
  editing a square-locked image).

## ~~Responsive tables~~ — SHIPPED 2026-09-24

Decided by direct question (`AskUserQuestion`) before starting, since the
original request only named two approaches: **hide low-priority columns**
(not a card-grid fallback, not JS measure-and-cut); **main list pages
only** (widget tables stay as they are); a hidden column's data is **not
re-exposed** anywhere -- the row's own detail/edit link already shows it.

**Mechanism** (`style.css`, next to `.table-scroll`): `.table-responsive`
makes a wrapper a named `rtable` inline-size query container, so tiers key
off the *table's own width* (sidebar rail expanded on a mid-size window
squeezes it the same as a phone does). `.col-opt-1` hides at ≤720px of
container, `.col-opt-2` at ≤520px, and ≤340px trims cell side padding
from 8px to 4px. Opt-in rather than on `.table-scroll` itself: inline-size
containment stops a box sizing to its content, which would collapse a
`.table-scroll` in a shrink-to-fit context. `.table-scroll`'s horizontal
scroll is kept as a last-resort safety net only.

**Thresholds were measured, not guessed** (Playwright, seeded long titles
/ several labels / a public published list, viewports 1280 → 300):

| Table | Drops at ≤720 (`opt-1`) | Drops at ≤520 (`opt-2`) |
|---|---|---|
| Tasks | Labels | Status |
| Habits | Cadence, Labels | Streak |
| Labels | — | Usage |
| Holidays | — | Calendar |
| Time blocks | — | Type |
| Published lists | Filter | Type |

Two tables needed more than column hiding, found by measuring:
- **Tasks/Habits title** -- `.task-title-cell`'s 320px nowrap ceiling was
  itself the table's min width (even with every optional column gone, 32 +
  320 + 97 + 44 > a 351px phone container). Under the 720px tier the title
  now wraps instead (`.task-table td.task-title-cell` -- needs the `td`
  to out-rank `.task-table td{white-space:nowrap}`, first attempt without
  it silently didn't apply), including while being inline-edited (the
  `:has([data-editing])` 280px floor would otherwise come back mid-edit).
- **Published lists' Link** -- a nowrap `<code>` URL held the column at
  420px on every viewport under 1024. ≤720: URL capped at 18ch (ellipsis);
  ≤520: URL hidden, just the Copy button (the part that's actually used).

**Result**: no table overflows at ≥375px viewport (before: Tasks/Habits/
Published lists overflowed from ~800px down, Holidays/Time blocks from
~414px). **Residual at 320px**: Holidays overflows by ~10px and Published
lists by ~2px -- the only remaining columns are the ones that can't go
(name, date, Actions -- which is the only edit path on those rows), so
the scroll safety net covers it rather than hiding Actions.

**Not covered** (by choice): Contacts (turned out to be a card list, not a
`<table>`), dashboard widget tables, detail-page subtables, Data health's
conflicts table.

## Known open risks

- Item 4 (labels-as-modules) and item 2 (narrow dashboards) both touch a
  large amount of already-shipped, tested surface from 2026-08-29 through
  2026-09-21. Neither should be started without re-confirming scope live —
  see the "Known conflict" note at the top of this doc.
- Item 7 (Web Push) assumes no existing scheduler/reminder-delivery
  mechanism; if one is found during audit, this doc's "only leisure/sleep is
  a new mechanism" constraint may already be satisfied for events/tasks/
  habits and the item shrinks considerably.
- ~~CSP violation on every modal open~~ -- **fixed 2026-09-24**: not an
  inline `style=` at all. modal.js DOMParser-parses the fetched full page,
  whose base.html head carries `<style nonce>` with *that response's*
  nonce; the parsed document inherits this page's CSP, so it logged a
  `style-src-elem` violation (pinned via Playwright's
  `securitypolicyviolation` event -> modal.js:276). modal.js now strips
  `<style>` blocks before parsing (they could never apply: wrong nonce,
  and the accent rule is already live). Policy unchanged.

## How open work gets tracked

Same convention as `open.md`/`open-priority.md`: strike an item
(`~~item~~`) and add a `**Shipped <date>**` note with a pointer to the
`STATE.md` entry when it lands; leave everything else as-is so this stays a
faithful record of what Peter actually asked for.
