# One design, not five — UI consistency across the whole app

For humans and AI sessions both. This supersedes the narrower
`CARD_UI_GUIDE.md` (cards are now just §1 below) — the same rule applies to
*every* recurring UI piece, not just cards: buttons, forms, tables, modals,
tags, toolbars, empty states. **The app has one design system
(`static/style.css`'s M3 token set), and every screen should look like it
came from the same hand.**

## The rule, stated once, applying to everything below

For each component category below there is **one canonical pattern**.
Reach for it by default, everywhere, including Settings. The few variants
that already exist are documented per-section with the *specific, real*
reason each is different — not a stylistic choice, a genuinely different
kind of thing.

**A new variant is a rare exception, not a shortcut.** Before adding a new
CSS class that's a near-copy of an existing component (a new button style,
a new card look, a new way to lay out a form, a new badge), state the case
in plain language first — "this needs X because Y, none of the existing
patterns support it" — and get an explicit yes before writing it. This
applies doubly to an AI session: "I'll just tweak the styling a little for
this one screen" is exactly how an app ends up with five almost-identical
components and no one who decided that on purpose. If approved, add it to
the relevant table below in the same change, so the next person (or
session) sees it was a deliberate, known exception.

---

## 1. Cards

Canonical: bare `.card` (`static/style.css` ~line 796) for any plain content
surface — the default for Settings, forms, list pages.

```html
<div class="card">
  <h2>Section title</h2>
  ... content ...
</div>
```

| Variant | Where | Why it's different, not just styled differently |
|---|---|---|
| `.detail-card` | Task/event/contact detail pages | Colored left accent border keyed to the object's own color — real information `.card` doesn't carry |
| `.filled-card` | Spaces / Quick Links widget tiles | Solid tonal color fill, not a neutral surface — represents "this is a colored thing," not "a section of a page" |
| `.widget-card` | Dashboard grid only | Same look as `.card` — the class only adds drag/resize positioning |
| `.kanban-card` | Board-view task chips | A small draggable list item, not a page section |
| `.auth-card` | Login page only | The one screen with no app chrome around it |

Settings never needs anything but bare `.card`. Settings has its own,
more detailed canon on top of this — which layout to use for which *kind*
of Settings data — see [`SETTINGS_UI_GUIDE.md`](SETTINGS_UI_GUIDE.md).

## 2. Buttons

Canonical: `.btn` + exactly one of two modifiers.

```html
<button class="btn primary">Save</button>
<button class="btn ghost">Cancel</button>
```

- **`.btn primary`** — the one committing/affirmative action per view
  (Save, Create, the FAB-style "+ New"). There should be at most one
  primary button visible at a time — two primaries in the same view means
  the user can't tell which one matters.
- **`.btn ghost`** — everything else clickable that isn't primary:
  Cancel, secondary actions, icon-only toolbar buttons.
- **`.btn danger`** exists for destructive confirms only (delete). Don't
  reach for it to mean "important" — it specifically means "this removes
  something."
- **`.btn-sm`** is a size modifier (compact toolbars, inline table
  actions), stacks with `primary`/`ghost`, isn't a third button style.

Don't hand-roll a `<button>`/`<a>` with inline styles or a bespoke class
to get a "slightly different" button look — every clickable action in this
app should be visually recognizable as a button from the same three
building blocks above.

## 3. Form fields

Canonical: `.field` wraps a label + one input.

```html
<div class="field">
  <label for="title">Title</label>
  <input id="title" name="title" type="text">
</div>
```

- `.field-toggle` — a checkbox/switch row (label sits inline, not above).
- `.field-grid` — two fields side by side; `.field-wide` spans both
  columns inside it.
- `.field-hint` — one small helper line under an input, not a whole
  paragraph of inline instructions.
- `.field-required::after` prints the `*` — don't type a literal `*` into
  a label string.

Every form field in the app should look like this pattern. A form that
free-hands its own label/input layout instead of using `.field` will visually
disagree with every other form the moment it sits next to one.

## 4. Lists of items: table vs. checklist — two legitimate patterns, pick by density

This app has exactly two ways to show "a list of things," and both are
intentional — the split is by *what kind of list it is*, not preference:

- **`<table>`** (real HTML table, `.table-scroll` wrapper) — for
  data-dense, multi-column, sortable/filterable views: Tasks table,
  Settings > Holidays, Data health's backup list. Use when there are 3+
  meaningful columns per row.
- **`.checklist` / `.checklist-row`** — for a simple, single-column list
  of items with an inline action (check off, delete): habit heatmap day
  toggles, the offline shell's task list, search results. Use when a row
  is really just "a name and maybe one action," not real tabular data.

Don't invent a third shape (a hand-styled `<div>` grid pretending to be a
table, or a table with one real column) — pick whichever of the two above
actually matches the data, even if it means changing an already-written
screen to match rather than shipping a new in-between shape.

## 5. Modals

Canonical: `.modal-overlay` > `.modal` > `.modal-header` / body /
`.modal-footer`, following `_modal_footer.html`'s existing shape (a ghost
Cancel + a primary confirm action, in that order, confirm on the right).

- `.modal.is-wide` — the only sanctioned size variant, for a form that
  genuinely needs more horizontal room (e.g. field grids). Don't reach for
  a custom width via inline style.
- `.modal.is-stable-height` — locks height so content swapping (async
  region refresh) doesn't jump the dialog around; opt-in where relevant,
  not a default.
- Every create/edit template must stay **modal-capable**
  (`features/architecture.md` §2) — wrap the fragment so it works both as
  a full page and inside `.modal-body`. Don't build a form that only
  works one of the two ways.

## 6. Tags, pills, and status badges

Canonical: the shared 16-color identity palette (`.tag-{color}` /
`.pill-{color}`, e.g. `.tag-blue`, `.pill-green`) — this is the *one* place
in the app real hex colors are allowed at all (`features/architecture.md`
§3), because these are user-chosen identity colors (labels, calendars),
not UI chrome.

- `.pill-select` — the interactive, clickable variant (status/importance
  dropdown-as-pill on task rows).
- `.pill-static` — same look, non-interactive, for read-only display.
- `.pill-removable` / `.pill-linkable` — small interaction modifiers
  (an "×" or link affordance), still built on the same base pill.

Don't invent a new colored-badge style for a new feature's "status" concept
— if it's a small colored label, it's a pill, using a color from this same
palette, not a new bespoke chip design.

## 7. Toolbars & page headers

Canonical: `.toolbar` (or `.toolbar-2row` when filters need a second row)
at the top of a page — page title, then a `.spacer`, then the page's
actions, ending with the page's one primary button if it has one.

```html
<div class="toolbar top-app-bar">
  <h1>Notes</h1>
  <div class="spacer"></div>
  <a class="btn primary" href="/notes/new">New</a>
</div>
```

Every top-level page (Tasks, Notes, Contacts, Habits, each Settings
category...) should open with this same shape — title left, actions right
— so a user's eyes learn one place to look for "what can I do here,"
regardless of which page they're on.

## 8. Empty states

Canonical: `.empty-state` (plain, centered text) for a minor "nothing here
yet" moment; `.empty-state-rich` (opt-in modifier, icon + title + helper
text + optional CTA button) for a page's primary empty state — the first
thing a new user sees on a page with no data yet.

Don't write a bespoke "nothing to show" message with its own inline markup
— of the ~25 empty states already in the app, all follow one of these two,
and a new one should too.

## 9. Icons

Canonical: `{{ icon('name') }}` (the Jinja global, `deps.py`) rendering
from the single inline sprite (`_icons_sprite.html`) — never an emoji,
never a separate external icon library, never an inline `<svg>` pasted
directly into a template. If the icon you need doesn't exist in the sprite
yet, add a symbol to it rather than reaching for something else — this is
what keeps every icon in the app the same stroke weight and visual family.

## 10. Typography, spacing, and color — already governed by §3 of the rulebook

Not repeated here — see `features/architecture.md` §3 (Look & feel): M3
color tokens only (no hard-coded hex outside §6's identity-color pills),
the 4pt spacing scale (`--space-*`), density-first sizing. Every rule above
is downstream of that same token set — a new component should pull its
colors/spacing/radius from those tokens, never a new literal value.

---

## Quick self-check before writing any new UI markup

- [ ] Does an existing pattern above already cover this? → use it, don't
      restyle it.
- [ ] Is this Settings? → the plainest version of every pattern above,
      zero exceptions.
- [ ] About to write CSS that's a near-copy of something in this file? →
      stop, state the case, ask first.
- [ ] If approved as a genuine exception → add it to the relevant table
      here in the same change.
