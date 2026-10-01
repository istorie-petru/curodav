Vendored pre-built UMD bundles (STATE.md's "Editor.js sourcing" decision,
2026-09-29) -- no npm/build step in this app, so upgrades are manual:
re-download the file at a newer version and commit it in place.

| file              | package            | version | global        |
|--------------------|---------------------|---------|---------------|
| editorjs.umd.js    | @editorjs/editorjs  | 2.31.7  | `EditorJS`      |
| header.umd.js      | @editorjs/header    | 2.8.9   | `Header`        |
| list.umd.js        | @editorjs/list      | 2.0.9   | `EditorjsList`  |
| quote.umd.js       | @editorjs/quote     | 2.7.6   | `Quote`         |
| code.umd.js        | @editorjs/code      | 2.9.4   | `CodeTool`      |

Source: `https://cdn.jsdelivr.net/npm/<package>@<version>/dist/<file>`
(jsdelivr mirrors the package's own npm-published `dist/` build; not a
CDN dependency at runtime -- these are the exact bytes, vendored once).
Each package's own license (MIT) ships inside its own npm package, not
duplicated here.
