Vendored files for the Notebook editor. The app has no build step, so these are committed as they are and upgraded by hand.

| file             | what                                                          | license |
|------------------|---------------------------------------------------------------|---------|
| tiptap.bundle.js | the Tiptap editor and its extensions, built from `tools/editor-bundle` | MIT (Tiptap and ProseMirror) |
| prism.js         | prismjs 1.29.0, the code highlighter                            | MIT     |

`tiptap.bundle.js` is rebuilt with `npm run build` in `tools/editor-bundle` (see its README). Notes are still stored as the
block list the Editor.js editor used; the bundle's `convert.js` maps it to and from the Tiptap document. Editor.js itself was
removed in 5.0.15: a note holding blocks Tiptap cannot show opens read-only, with a button that converts it.

`prism.js` is not jsdelivr's single file: Prism ships each language as its own component, so the core and the languages the
code block offers were joined in dependency order from `prismjs@1.29.0/components/` and the result committed here.
