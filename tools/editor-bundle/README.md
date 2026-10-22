# Editor bundle

Builds `webapp/src/static/notebook/vendor/tiptap.bundle.js`, the Notebook's new editor (Tiptap). The app itself has no
build step: this bundle is built here and the output is committed.

```
npm install
npm test          # round trip of every supported block through the new editor
npm run build
```

The note is still stored as the Editor.js block list; `src/convert.js` maps it to and from the Tiptap document. A note
with content the new editor cannot hold yet opens read-only. The new editor is opt-in with `?editor=tiptap` on a note.

`node check-library.mjs /path/to/curodav.db` reads every note (read-only) and reports which open unchanged in the new
editor, which would be rewritten, and which still use the old editor.
