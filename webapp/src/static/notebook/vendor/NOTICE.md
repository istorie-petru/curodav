Vendored pre-built UMD bundles (STATE.md's "Editor.js sourcing" decision,
2026-09-29) -- no npm/build step in this app, so upgrades are manual:
re-download the file at a newer version, commit it in place, **and
re-extract its CSS (see "CSS extraction" below) -- do not skip this, see
why below.**

| file              | package            | version | global        |
|--------------------|---------------------|---------|---------------|
| editorjs.umd.js    | @editorjs/editorjs  | 2.31.7  | `EditorJS`      |
| header.umd.js      | @editorjs/header    | 2.8.9   | `Header`        |
| list.umd.js        | @editorjs/list      | 2.0.9   | `EditorjsList`  |
| dragdrop.umd.js    | editorjs-drag-drop  | 1.1.16  | `DragDrop`      |
| simpleimage.umd.js | @editorjs/simple-image | 1.6.0 | `SimpleImage` |
| inlinecode.umd.js  | @editorjs/inline-code  | 1.5.2 | `InlineCode`  |
| undo.umd.js        | editorjs-undo       | 2.0.28  | `Undo`          |
| prism.js           | prismjs             | 1.29.0  | `Prism`         |

Source: `https://cdn.jsdelivr.net/npm/<package>@<version>/dist/<file>`
(jsdelivr mirrors the package's own npm-published `dist/` build; not a
CDN dependency at runtime -- these are the exact bytes, vendored once).
Each package's own license (MIT) ships inside its own npm package, not
duplicated here. `dragdrop.umd.js` is jsdelivr's `/dist/bundle.min.js`,
renamed on disk to match this directory's own `<tool>.umd.js` convention
-- it's the same already-minified UMD bundle either way, confirmed MIT
via the npm registry's own package metadata (the package itself ships no
LICENSE file).

`table`/`delimiter` (2026-10-02) were extracted the same way as the
original five, but via a Python JS-string-literal parser (handles the
escape sequences directly, since a live browser wasn't available at the
time) rather than reading `document.querySelectorAll('style')` live --
functionally identical result, documenting the deviation from the
procedure below in case future output ever looks suspicious and needs
re-deriving from the live DOM instead.

`quote.umd.js`/`warning.umd.js` (@editorjs/quote, @editorjs/warning) were
vendored 2026-10-02 and removed again 2026-10-03, direct request ("the
quote and warning ones look bad, rework") -- replaced by first-party
`notebook_blocks.js` (Quote + Callout tools, plain Tool API, no vendored
dependency) rather than patched in place, since the requested look
(colored left bar / icon+color-picker callout) wasn't reachable by
styling their existing DOM shape alone. `dragdrop.umd.js` has no CSS of
its own to extract (confirmed -- no self-injected `<style>` IIFE in the
bundle, it only moves existing block DOM nodes around via the Editor.js
API, draws no new chrome).

`simpleimage`/`inlinecode`/`undo` (2026-10-03, direct request after a
plugin-maintenance audit) -- `simple-image.umd.js`/`inline-code.umd.js`
were renamed to this directory's flat `<name>.umd.js` convention (their
own npm `dist/` folders use `simple-image.umd.js`/`inline-code.umd.js`
with a hyphen; harmless rename, same bytes). `undo.umd.js` is
`editorjs-undo`'s `dist/bundle.js` (jsdelivr), likewise renamed; it has no
CSS of its own (confirmed -- no self-injected `<style>` IIFE, same check
as `dragdrop.umd.js` above), it only tracks `editor.save()` snapshots and
calls the public Editor.js API to restore them.

`code.umd.js`/`delimiter.umd.js` (@editorjs/code, @editorjs/delimiter)
were removed 2026-10-03, same direct-request round that asked for code
syntax highlighting and multiple delimiter styles -- neither upstream
tool has any data/config/renderSettings hooks to grow a language picker
or a style picker onto (confirmed in both their sources), so both were
replaced outright by first-party tools instead of patched: Delimiter
moved into `notebook_blocks.js` (a plain style string + CSS, no new
dependency), Code into its own `notebook_code.js` (needs the much larger
Prism dependency below, kept separate rather than folding into
`notebook_blocks.js`).

`prism.js` is **not** jsdelivr's own single bundle -- Prism ships
`core` + one file per language as separate npm `dist/` files with a real
dependency graph between them (see `prismjs@1.29.0/components.json`),
e.g. `javascript` requires `clike`, `php` requires `markup-templating`
requires `markup`. This file is `core` + a curated 19-language subset
concatenated in dependency-resolved order (list below), downloaded
individually from jsdelivr and joined with a plain `cat`, byte-for-byte,
no re-minification -- verified after joining (Node, `eval` + call
`Prism.highlight`) that concatenation didn't silently break anything
(each component is its own IIFE reading/writing the shared `Prism`
global, the same thing sequential `<script>` tags would do, just joined
into one file instead of twenty `<script>` tags). **On a version bump,
re-download every file below at the new version and re-concatenate in
this exact order** -- re-ordering or dropping a dependency breaks the
languages after it silently (no error, that language's tokens just won't
colorize).

Order: `core`, `clike`, `markup`, `css`, `javascript`, `typescript`,
`python`, `bash`, `json`, `yaml`, `sql`, `c`, `cpp`, `csharp`, `java`,
`go`, `rust`, `markup-templating`, `php`, `ruby`, `markdown`. Source for
each: `https://cdn.jsdelivr.net/npm/prismjs@1.29.0/components/prism-
<name>.min.js`. No CSS vendored alongside it -- notebook_code.css's own
`.token.*` rules are first-party (this app's existing color tokens, not
one of Prism's fixed single-theme stylesheets); see that file's own
comment.

## CSS extraction (2026-10-01, required reading before any version bump)

Each `.umd.js` file above also bundles its own CSS, self-injected at
runtime via a `document.createElement("style")` + `document.head.
appendChild(...)` IIFE at the top of the file (Vite's
`vite-plugin-css-injected-by-js` -- none of these packages publish a
separate `.css` file in their npm `dist/`, confirmed via jsdelivr's
package listing for all five). **That injected `<style>` tag has no CSP
nonce, and this app's CSP (`style-src 'self' 'nonce-{nonce}'`, no
`'unsafe-inline'`) silently blocks every inline `<style>` without one --
the bundle's CSS never applies, and the editor renders completely
unstyled (confirmed live: every injected `<style>` tag had `.sheet ===
null`).**

The fix, already applied: each bundle's CSS is extracted once into a
sibling `.css` file (`editorjs.css`, `header.css`, `list.css`,
`table.css`, etc.) and loaded via a normal `<link rel="stylesheet">` in
`notebook_document.html`'s `extra_head` block instead -- `style-src
'self'` already permits same-origin linked stylesheets with no nonce
needed at all; only literal inline `<style>`/`style=""` need one.

**On a version bump, re-run this extraction** (the old `.css` files are
now stale once the `.js` changes): load the editor page in a browser with
the new `.js` files in place, then in the console read
`document.querySelectorAll('style')` -- each bundle's IIFE will have
already executed and created its `<style>` tag with the new CSS in
`.textContent`, fully decoded by the browser (reading from the live DOM
avoids hand-parsing escaped strings out of minified JS). Match each
captured block to its source bundle by its CSS class names, then
overwrite the corresponding `.css` file. `editorjs.umd.js` injects
*several* separate `<style>` tags (a tooltip library, the core editor
CSS, a hint-alignment snippet, a notify/toast CSS, and the built-in
Paragraph tool's own CSS) -- all of those go into the one `editorjs.css`.

`table.umd.js`/`table.css` (@editorjs/table) were removed 2026-10-10: the table is a first-party tool now (`notebook_table.js`), which loads the old tool's saved data unchanged.
