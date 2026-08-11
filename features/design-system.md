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
