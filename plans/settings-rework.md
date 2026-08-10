# Plan: Settings rework — an actually usable hub

**Status:** ✅ DONE (2026-08-07), superseded by a full redesign (2026-08-08) — see §6 below.
**Target codebase:** `webapp/` (FastAPI) — `routers/settings.py`, `settings_index.html`, `_settings_nav.html`, `base.html` (theme toggle), plus whatever else the audit below turns up.

---

## 1. Audit — what's actually wrong with Settings today

Read `routers/settings.py`, `settings_index.html`, `_settings_nav.html`, `base.html`, `config.py`, and grepped for every `href="/..."` and `app_meta` key in the app. Findings, not assumptions:

1. **Export/Backup is completely unreachable from the UI.** `routers/export.py` and `export_index.html` are real and working (ICS/VCF/CSV exports, a full JSON backup with restore) — but nothing in `base.html`, `settings_index.html`, or `_settings_nav.html` links to `/export`. The only way to reach it is typing the URL. For a self-hosted app with no server-side backup story beyond "you have the SQLite file," this is the single worst gap — a real feature, invisible.
2. **Habits is missing from the Settings hub itself.** `_settings_nav.html` (the strip shown *on* sub-pages like Labels/Schedule/Published Lists) correctly lists Habits — but `routers/settings.py`'s `GLOBAL_ENTRIES` (what actually renders on `/settings`, the landing page) doesn't include it. You can only discover Habits by already being on a different settings sub-page first.
3. **The hub's "Global / Space / Project" three-section structure contradicts the app's own data model.** Both the "Space" and "Project" sections link to the exact same `/labels` page and list the exact same underlying objects (labels), just pre-filtered by `generate_space`. This is a leftover from before the label-space rework — the whole point of that rework was "there is no Space/Project type distinction, it's all just labels with different behaviors" (see `plans/label-space-rework.md` §0.1). Presenting them as three structurally separate groups on the one page a new user would use to understand the app's own model actively misleads about how it works.
4. **No Appearance section.** The dark/light theme toggle exists, but only as a lone icon button in the tabbar (`base.html`'s `#btnTheme`, client-side `localStorage` only) — not discoverable from Settings at all, where anyone looking for "how do I change the theme" would reasonably look first.
5. **No consistency between the hub and the sub-nav strip.** `_settings_nav.html` (Labels/Habits/Schedule/Published Lists) and `GLOBAL_ENTRIES` (Labels/Schedule/Published Lists) list different sets — whichever page you land on first shows a different picture of "what's in Settings."

## 2. What this plan does NOT do

- No new backend features invented (no notifications system, no user accounts/auth, no Radicale credentials UI — `config.py`'s env-var-only config is a deliberate ops-level boundary for a no-auth self-hosted app, not a gap to expose in a web form).
- No re-litigating the label-space rework's own decisions — this fixes Settings' *presentation* of that model, not the model itself.
- No "About" page — nothing in this app tracks a version number or has external links worth a dedicated page; would be empty ceremony.

## 3. New structure

Four groups, replacing the misleading three:

1. **Organization** — one Labels entry (rename/merge/color/Space behavior all live there already), no artificial Space/Project split. A short line of explanatory text ("Spaces and Projects are both just labels — set 'Generate a Space page' on to make one aggregate its own page") replaces the fake category boundary with an honest one-sentence explanation.
2. **Data** — Habits, Schedule settings, Published Lists, **Export & Backup** (the fix for finding #1 — this is the important addition).
3. **Appearance** — a real theme toggle rendered in Settings (calls the same `localStorage` toggle `base.html`'s existing button already does, via the same JS — not a second, divergent implementation).
4. **Widgets** — the existing Custom widgets toggle, unchanged.

`_settings_nav.html`'s sub-page strip gets Published Lists confirmed present (it already is) and stays otherwise the same shape — it was already closer to correct than the hub was.

## 4. Implementation notes for whoever builds this (immediately, in this same pass)

- `GLOBAL_ENTRIES` in `routers/settings.py` becomes a grouped structure (or split into per-group lists) instead of one flat list, so `settings_index.html` can render the four sections above instead of the old Global/Space/Project cards.
- Theme toggle in Settings: reuse `app.js`'s existing theme-toggle logic (whatever function `#btnTheme`'s click handler calls) rather than writing a second implementation — add a second element that triggers the same function, or refactor the handler to bind to a class/selector both buttons share.
- Delete the `spaces`/`projects` context variables and the two duplicate template sections in `settings_index.html`; replace with the single Labels row (optionally still showing a short list of existing labels for quick access, but as one list, not two framed as different types).
- Add tests per the standing house rule (`plans/label-space-rework.md` §4): Settings hub includes a working `/export` link, includes Habits, has exactly one Labels-related section (not two), and the Appearance toggle is present.

## 5. What shipped

`routers/settings.py`: `GLOBAL_ENTRIES` → `DATA_ENTRIES` (Habits, Schedule, Published lists, **Export & backup — new**), `settings_index` now passes `labels` (every label, one flat sorted list) instead of the old separately-filtered `spaces`/`projects`. `settings_index.html`: four groups (Organization/Data/Appearance/Widgets) replacing Global/Space/Project; a `generate_space=1` label gets a small "Space" badge inline rather than a whole separate section; capped at 8 labels shown with a "+N more" link to the full `/labels` manage page. `static/app.js`: theme logic now drives an arbitrary number of controls via `window.CCTheme.apply()` instead of one hardcoded button — the tabbar icon button and Settings' new switch stay in sync regardless of which one you use. `_settings_nav.html` and `export_index.html` gained matching entries so the hub and the sub-page strip list the same five things (previously each was missing something the other had).

**Found and fixed along the way, not part of the original audit:** `export_index.html`'s intro text still said tasks/events/contacts "live in Radicale" — stale since Phase 1 of the label-space rework moved base storage to plain SQL; corrected to describe what's actually true today (Radicale is now only the transport for opt-in Published Lists).

Tests: `test_phase8_settings_hub.py` rewritten for the new structure (renders four groups not three, `/habits`+`/export` reachable, `/contacts` absent from the Settings-authored entry list, labels shown once not split, theme switch present). Full suite green (414 passed).

## 6. Full redesign (2026-08-08) — Settings becomes its own area, not one page

The 2026-08-07 pass above was real progress but still one long scrolling
page: four groups, a dozen-plus controls, all in one `<main>`. Asked to
rethink the area from scratch rather than restyle it further. Brainstormed
information architecture first (every setting the app actually has, where
it lives, how often it's touched, what's contextual vs. hub-worthy) before
touching code — see `routers/settings.py`'s own module docstring for the
full audit and reasoning.

**New structure — a hub plus five focused child pages, not one page:**

- `/settings` — hub: six rows (General/Appearance/Labels/Data & backup/
  Widgets/Advanced), each icon + name + one-line description + chevron,
  nothing else. Not seven, not four — six because that's how many
  genuinely distinct categories this app's actual settings sort into, not
  because six is a tidy number (see the router docstring for what was
  deliberately *not* added: Notifications, Integrations, Privacy, and
  Calendar/Tasks as their own categories all would have been empty or
  redundant with settings that already live contextually elsewhere).
- `/settings/general` — Your name (display name).
- `/settings/appearance` — Theme, now a real three-way System/Light/Dark
  segmented control instead of an on/off switch. The switch could only
  ever store an explicit light/dark, which meant the OS-follows fallback
  (`prefers-color-scheme`, applied by `base.html`'s inline `<head>` script
  whenever nothing's been stored) became permanently unreachable the
  instant anyone touched the switch once — "System" wasn't a state you
  could get back to. Fixed at the root: `static/app.js`'s `window.CCTheme`
  now treats "System" as *no stored key* (matching what the inline head
  script already does), not a third literal value, and listens for
  `prefers-color-scheme` changes live while "System" is active.
- `/settings/data` — Habits/Published lists/Export & backup, unchanged
  destinations, now a small sub-hub instead of living inline on the main
  hub.
- `/settings/widgets` — Custom widgets toggle + Reset Home to default
  layout, unchanged behavior.
- `/settings/advanced` — the two purge actions (was "Danger zone" at the
  bottom of the old single page; same actions, same confirmations, own
  page now — "Advanced" is exactly what this kind of rarely-touched, real-
  capability control means in every settings app).
- Labels stays at `/labels` (not `/settings/labels`) — it's the app's one
  organizing concept, not a "data feature," and already had its own full
  manage page; no value in a wrapper route around it.

**Hierarchical back-navigation:** every page in the family (the hub's five
children, Labels, and Data & backup's own three children) shares one
partial, `_settings_breadcrumb.html` — an explicit trail (`crumbs` +
`title`) rendered top-of-page, not reliance on browser history (which
breaks for anyone who deep-links straight into a child page). Settings →
Labels → Back returns to Settings; Settings → Data & backup → Habits →
Back returns to Data & backup, not out to whatever page was open before
Settings was ever entered. `base.html`'s Settings gear stays lit for every
`active_tab` starting with `"settings"` plus `labels`/`habits`/
`published_lists`/`export`, one check instead of a hand-maintained tuple
that would silently go stale the next time a child page is added.

**Fast editing, still direct controls, no new modal layers:** every child
page uses one shared row shape (`.settings-field-row`, "Setting name
[ control ]") — a switch autosubmits on change (`custom widgets`), a
segmented control autosubmits on click (theme), free text keeps an
explicit Save (display name — the one control type where "did I actually
finish typing" genuinely matters). No setting that was a direct control
before this redesign became a modal or an extra click during it.

**Labels management, made more complete, not just relocated:**
`labels_manage.html` gained a live client-side search box
(`static/label_search.js`, filters already-rendered rows, no round trip)
and an inline icon picker per row (previously the manage list only let you
recolor a label inline — the icon picker existed on the single-label
detail page, `label_detail.html`, but you had to open each label
individually to reach it). Deliberately did **not** add a true "delete"
concept for labels — that's an intentional model decision from the label-
space rework (`plans/label-space-rework.md` §0.1: a label is a name
pointer, not an entity with a lifecycle), not a gap this redesign should
paper over; "Clear" (strip from everything) stays the only removal action,
relabeled "Remove" in the row for clarity.

**Mirrored vs. contextual, decided per setting, not by default:** Theme
mirrors cleanly (tabbar icon button + Settings > Appearance, one
`localStorage` value, `window.CCTheme` the single source of truth, both
controls always in sync). Schedule's settings (semester dates/credits/
reminder/event label) and the habit-tracking label deliberately stay
contextual-only (`/schedule`'s own `<details>` block; Tasks > Habits' own
`<details>` block) — both already made that move for good reasons just
before this redesign started, and adding a Settings mirror nobody asked
for would recreate the exact "which one is current" drift those earlier
moves were fixing. Not every setting needs to exist in two places; a
mirror only earns its keep when the contextual shortcut is genuinely
faster than the trip through Settings.

Tests: `test_phase8_settings_hub.py` rewritten again — one test class per
page (hub + General/Appearance/Data/Widgets/Advanced), asserting the hub
itself no longer renders any actual control (no `themeSegmented`, no
`display_name` input, no purge forms — those all moved to their own
pages) and that every POST redirects back to its own page, not the hub.
`test_dashboard_usability_rework.py`'s display-name/reset-button tests
updated to call the new `settings_general`/`settings_widgets` routes.
Full suite green apart from five pre-existing, unrelated failures in
`test_phase10_customize_modal.py` (the dashboard widget-builder modal,
untouched by this pass).
