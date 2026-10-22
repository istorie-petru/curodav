// Checks every note in a Curodav database against the new editor, without changing anything.
//   node check-library.mjs /path/to/curodav.db
// For each note it reports whether the new editor can hold it, and for those it can, whether opening and saving
// it gives back exactly the same blocks (apart from <b> and <strong> style differences).
import { DatabaseSync } from "node:sqlite";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><body><div id='m'></div></body>", { pretendToBeVisual: true });
for (const key of ["window", "document", "navigator", "Node", "HTMLElement", "Element", "DOMParser", "MutationObserver", "getComputedStyle", "Range", "Selection"]) {
  Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true, writable: true });
}
const { create, lossy, unsupportedBlocks } = await import("./src/index.js");

const withoutEmptyParagraphs = (blocks) => blocks.filter((b) => !(b.type === "paragraph" && !(b.data && b.data.text)));
const normalize = (blocks) =>
  JSON.stringify(withoutEmptyParagraphs(blocks)).replaceAll("<strong>", "<b>").replaceAll("</strong>", "</b>").replaceAll("<em>", "<i>").replaceAll("</em>", "</i>").replaceAll(/\s+/g, " ");

const db = new DatabaseSync(process.argv[2], { readOnly: true });
const rows = db.prepare("SELECT uid, title, content_json FROM notebook_documents").all();
const summary = { total: rows.length, same: 0, changed: [], legacy: [] };
for (const row of rows) {
  let blocks = [];
  try {
    blocks = JSON.parse(row.content_json || "{}").blocks || [];
  } catch (err) {
    summary.legacy.push(`${row.title}: unreadable content`);
    continue;
  }
  if (lossy(blocks)) {
    summary.legacy.push(`${row.title}: ${unsupportedBlocks(blocks).join(", ") || "formatting"}`);
    continue;
  }
  const handle = create(document.getElementById("m"), blocks, () => {});
  const out = handle.blocks();
  handle.editor.destroy();
  if (normalize(out) === normalize(blocks)) summary.same += 1;
  else summary.changed.push(row.title);
}
console.log(`Notes: ${summary.total}`);
console.log(`Open in the new editor and save back unchanged: ${summary.same}`);
console.log(`Open in the new editor but would be rewritten (check these): ${summary.changed.length}`);
summary.changed.forEach((t) => console.log(`  - ${t}`));
console.log(`Still open in the old editor for now: ${summary.legacy.length}`);
summary.legacy.forEach((t) => console.log(`  - ${t}`));
