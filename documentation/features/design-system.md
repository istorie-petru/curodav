# Design system

One token file, `webapp/src/static/style.css` (reworked 2026-08-04 into a full
MD3 pass: elevation system, tonal surfaces, MD3 shape tokens, ripple feedback,
FAB, mobile bottom nav — see the file's own header comment for organization).
Full contract in `architecture.md` §3; the short version:

- Colors come from M3 role tokens (`--md-*`) or legacy aliases that resolve to
  them; templates never hard-code hex except the fixed `.cal-*` calendar and
  `.tag-*`/`.pill-*` label palettes (user-chosen identity colors, identical in
  light and dark).
- Baseline palette seeded `#6750A4` (light/dark pair in `:root` /
  `[data-theme="dark"]`); dynamic wallpaper-sourced color is deliberately
  deferred.
- Shape: buttons/segmented control pill; cards large-surface (~12–16px); dialogs
  28px.
- Theming is a `data-theme` attribute; an inline `<head>` script reads
  `commandCenterWeb.theme` (System/Light/Dark) before CSS to avoid FOUC, with a
  `prefers-color-scheme` listener in app.js; cross-document View Transitions.
- Density: body ~13px, compact tables, 4pt spacing scale (`--space-*`).
- Favicon: green brand logo served as `favicon-16.png` / `favicon-32.png` +
  `apple-touch-icon.png` (the old SVG placeholder was removed 2026-08-11).

Shared input patterns (the app's standard form vocabulary) — tile/card picker,
segmented control, swatch-grid popover, chip multiselect, stepper — live in the
modal/input components (`_modal_footer.html`, `_widget_list_multiselect.html`,
`_widget_builder_fields.html`).

## Modal windows (2026-08-15 uniformization)

Every modal fragment in the app (`grep -l "modal-header\|modal-body"
src/templates/*.html`) follows one set of rules now, closing out an audit
that found three different hand-rolled footer implementations, an
unconfirmed Delete, and a sizing bug (`plans/open.md`'s former Modal window
uniformization section has the full before/after — removed from that file
now that every slice has shipped, per its own "How open work gets tracked"
convention).

- **Footer:** always `{% include "_modal_footer.html" %}` — never hand-rolled
  `.modal-footer` markup. The partial supports three shapes via its Jinja
  variables (see its own docstring for the full contract): the default
  back-link/spacer/delete/primary bar (`footer_back_url` + optional
  `footer_delete_url` + `footer_primary_label`); a primary-only bar with no
  back link at all, for a single "does its own thing and closes" action
  (`_modal_widget_customize`'s "Add widget" — omit `footer_back_url`); and a
  Back/Done-only bar with no primary at all, for a form whose real save
  mechanism already lives in the body — autosave, an instant per-row action —
  rather than the footer (`_widget_edit_modal`, `banner_editor` — omit
  `footer_primary_label`).
- **Delete confirmation is never optional.** Every destructive action reached
  from a modal footer is `footer_delete_mode='undo'` (reversible, has a
  toast-undo path) or `'confirm'` (irreversible, no undo destination) —
  never a bare POST. The `'confirm'` flow (`static/toast.js`'s
  `ccConfirmSheet`) renders as a persistent bottom-right toast in the same
  stack as warnings/errors/undo toasts — icon chip, the question as the
  body, a Cancel + danger Confirm button row — rather than a separate
  anchored popover, so every confirmation speaks the app's one notification
  language. The sync status indicator (`static/offline_status.js`) uses the
  same toast stack for its offline/pending/synchronizing states.
- **Title:** a plain `<h1>text</h1>`, no icon prefix, for every create/edit
  form and utility modal. The rich identity header (a status-colored
  dot/avatar + large bold `.detail-title`, `.modal-header
  h1.detail-title{font-weight:700}`) is reserved for real-entity detail/view
  modals only (task/event/contact).
- **Body layout:** two shapes cover a plain form or a plain read-only view —
  `.modal-body > .card > .field-grid` (form) or a stack of `.detail-card`s
  (detail/view). A modal may declare a third, custom shape (a two-pane
  builder, a bespoke uploader) only when neither fits — it still gets a
  footer via the rules above.
- **Sizing:** two named dialog widths, `default` and `.modal.is-wide`
  (`data-modal-size="wide"` on the *opening trigger link* — the fragment
  itself can't set its own dialog width). `wide` is for any modal whose
  content is a two-pane layout or a wide table; every trigger opening such a
  fragment must carry the attribute. `.modal-stable-height` is for any modal
  whose own content changes shape post-open without a full re-navigation (a
  view↔edit cross-fade, a tab switch) — everything else free-heights.

## Widget bodies (2026-08-17 uniformity pass)

The 13 visual dashboard widgets' body markup (between the shared card chrome
and the widget header) used to be hand-rolled per file — the audit that
kicked off this pass found the same five patterns (link-list rows, status
pills, stat blocks, filled cards, empty states) implemented slightly
differently in every widget, plus two bugs only visible in aggregate: a
status pill with no color class rendered as a transparent pill, and three
arbitrary fixed-width time columns where one `white-space:nowrap` rule is
the actual fix. The bodies now compose one shared partial,
`_widget_items.html` (see `features/dashboard.md` § Widget bodies for the
macro inventory), following UI guide §4 (a widget's simple link list is a
real `<table>`) and §6 (read-only status values render as
`.pill-static.pill-{color}`, never as a bare tag or a `.cell-tag` with no
color).

- **Rows** (`widget_link_row`) take `.widget-row-icon` / `.widget-row-time` /
  `.widget-row-right` classes instead of inline `style="width:...px"` /
  `text-align:right`; `.widget-row-time{white-space:nowrap}` is the fix for
  a date+time cell wrapping to two lines, and the row never fixes a width.
- **Pills** (`widget_pill`) need the `.pill-*` family to cover the full
  16-color identity palette (gray, orange, green, blue, red, purple, yellow,
  brown, pink, lime, mint, teal, cyan, indigo, magenta, slate) — 9 classes
  were added in this pass to complete it, each mapping the same
  `--tag-{color}-bg`/`--tag-{color}-fg` tokens as `.tag-*`.
- **Empty states** (`widget_empty`) render `.empty-state` (`.empty-state--inset`
  inside an already-padded builder pane) — the four builder/preview
  fragments swapped their old inline `padding:16px 0` for the modifier.
- Two bodies stay off the library by design: `_widget_mini_month_calendar`
  (a genuinely custom grid) and the Spaces & Projects list style (its
  `.cell-tag.cal-*` pill is a label-identity swatch, a different kind of
  chip — see `features/dashboard.md`). `tests/test_widget_library.py` is
  the structural sweep that fails CI if a future widget reintroduces a
  hand-rolled variant.
