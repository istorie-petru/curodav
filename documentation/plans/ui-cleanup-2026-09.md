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
   **investigated 2026-09-24**: premise was false (not dashboard-only), no
   change made.
4. **App title + PWA icon** (item 8) — static/manifest change, no backend.
5. **Notes removal/hiding decision** (item 13) — needs one clarifying
   question (remove entirely vs. feature-flag/hide) before any code.
6. **Card model removal** (item 4) — mechanical CSS pass, well-scoped once
   swept.
7. **Icon set swap to MaterialDesign-SVG** (item 5) — large diff, low
   logical risk; fine to do in one dedicated session since it's mechanical.
8. **Settings `.segmented` → dropdown** (item 9) — self-contained component
   swap, check for an existing select-based single-choice convention first.
9. **Design token tightening** (item 12) — audit current token count before
   scoping; likely its own investigation-then-cut slice.
10. **Search window simplification + event "overdue" rewording** (item 10).
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
13. **Image editor aspect-ratio lock + square avatars** (item 16).
14. **Responsive tables** (item 11) — needs a decision between the two
    proposed approaches (JS column-cutting vs. card-grid fallback) before
    starting.
15. **Habits/routines as a distinct frontend data model** (item 14) — audit
    what `test_habit_ui_rework.py`/`test_habits_router.py`/
    `test_tasks_habits_view.py`/`habit_checkin.js` already cover before
    assuming greenfield.
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

## 5. Move away from the card model

Page background matches the theme (white/dark), not a gray card fill;
widgets render directly on the body instead of inside a bordered/shadowed
card. Keep the hover animation only where it's still doing something (flex
layouts, still-card-shaped widgets) — drop it from plain page backgrounds if
cards are kept in some places rather than removed outright everywhere.
Direct request explicitly separates "remove cards" from "remove hover
animation for cards if we don't remove them" — read as two independent
toggles, not one change gated on the other.

## 6. Icon set swap to MaterialDesign-SVG

Replace the current icon source (`deps.py`'s `icon()` helper + wherever its
SVGs/sprite live today — audit before starting) with
[Templarian/MaterialDesign-SVG](https://github.com/Templarian/MaterialDesign-SVG).
Every icon name used across templates needs a mapped equivalent in the new
set — large mechanical diff, low logical risk, but budget a full session for
the audit + swap + visual check alone.

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

## 8. ~~`main-shell-body`'s `margin-bottom: 6dvh`~~ — INVESTIGATED 2026-09-24, no change

"If `main-shell-body` is only used in dashboard pages, remove the
`margin-bottom: 6dvh`." Conditional on the audit — the premise doesn't
hold: `.main-shell-body` is genuinely applied on four page shapes, not
just Dashboard — `_tasks_body.html` (`#tasks-body`), `_contacts_body.html`
(`#contacts-body`), `_notes_body.html` (`#notes-body`), and
`dashboard.html`'s widget-grid wrapper — all sharing the one "flex shell"
rule style.css documents at `.main-shell-body{...}` (2026-09-07, "extend
Calendar/Planner's viewport-fit model to every page with a clear
header+scrollable-body shape"). `labels_manage.html` still turned up in a
grep for the class name, but only inside a comment explaining it
*opted out* of this shell 2026-09-08 — it doesn't actually carry the class.

Since the condition in the request is false, nothing was removed — the
margin is shared, load-bearing spacing for Tasks/Contacts/Notes too, not a
dashboard-only leftover, and the request was explicitly conditional
("if... only used in dashboard pages"). No code change; flagging back to
Peter in the session that shipped this rather than guessing at a
scoped-modifier-class alternative nobody asked for.

## 9. App title + PWA icon

Browser-tab title becomes a constant "Curodav" (app name) instead of the
current per-page `{% block title %}Dashboard{% endblock %}` pattern —
decide whether the app name replaces the per-page title entirely or is
appended/prefixed to it (e.g. "Curodav" vs. "Tasks — Curodav"; the request
only said "constant... to be [app-name]", read literally that's a full
replacement, confirm before assuming). Add a PWA icon (manifest.json's
`icons` array — check what it currently points to, likely a placeholder or
missing).

## 10. Settings `.segmented` → dropdown

"Instead of having `class="segmented"` in the settings, I would much rather
prefer drop down menu with select one (radiobox drop down menu)." Find
every `.segmented` usage (grep templates + style.css) and replace with a
native `<select>`-based single-choice control. Check
`UI_CONSISTENCY_GUIDE.md`/`features/design-system.md` first for whether a
select-based convention already exists elsewhere to reuse rather than
inventing a new pattern.

## 11. Search window simplification

Remove the search modal's footer; move filters into that space instead.
Add explicit menu actions beyond search itself — Edit mode toggle, Import/
Export/Backup — reachable from the same surface. Remove the "Add label" and
"Delete" buttons from the search window. Separately: redo "overdue" wording
— events can't be overdue, they just pass, so an event's status label needs
its own wording distinct from a task's "Overdue."

## 12. Design token tightening

Cap most token categories at ~3 options: ~3 font families, ~3 font sizes,
~2 font weights, and reduce to two consistent "role" colors — one
guaranteed-legible active/foreground text color, one consistent background
(the example given: the sidebar's own text-on-background pairing). Needs an
audit of `style.css`'s current `:root` custom properties (how many font
sizes/weights/colors actually exist today) before scoping the cut.

## 13. Notes: remove or hide from the app's HTML

"REMOVE THE NOTES (OR HIDE THEM) FROM THE APP'S HTML" — genuinely
ambiguous which. Full removal drops the Quick Capture `!n` marker
(`quick_capture.py`) and `features/notes.md`'s whole scope; hiding could be
a nav/feature-flag change only, with data and routes intact underneath.
**Ask before implementing** — don't guess between these, the blast radius
differs enormously (data-destructive vs. cosmetic).

## 14. Habits/routines as a distinct frontend data model

"I also think that we strongly need to make habits/routines a different
data model, at least in the frontend. They can still be tasks in the
backend, but I think that habits need to be incorporated much more into the
UI." Audit `test_habit_ui_rework.py`, `test_habits_router.py`,
`test_tasks_habits_view.py`, `test_tasks_table_habits_split.py`, and
`static/habit_checkin.js` first — there's already some habit-specific UI
surface; this item is about how much further it needs to diverge from a
plain task's presentation, not a from-scratch build.

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

## 16. Image editor: aspect-ratio lock + square avatars

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

## Known open risks

- Item 4 (labels-as-modules) and item 2 (narrow dashboards) both touch a
  large amount of already-shipped, tested surface from 2026-08-29 through
  2026-09-21. Neither should be started without re-confirming scope live —
  see the "Known conflict" note at the top of this doc.
- Item 7 (Web Push) assumes no existing scheduler/reminder-delivery
  mechanism; if one is found during audit, this doc's "only leisure/sleep is
  a new mechanism" constraint may already be satisfied for events/tasks/
  habits and the item shrinks considerably.

## How open work gets tracked

Same convention as `open.md`/`open-priority.md`: strike an item
(`~~item~~`) and add a `**Shipped <date>**` note with a pointer to the
`STATE.md` entry when it lands; leave everything else as-is so this stays a
faithful record of what Peter actually asked for.
