import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><body><div id='m'></div></body>", { pretendToBeVisual: true });
for (const key of ["window", "document", "navigator", "Node", "HTMLElement", "Element", "DOMParser", "MutationObserver", "getComputedStyle", "Range", "Selection"]) {
  Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true, writable: true });
}
const { create, lossy } = await import("../src/index.js");

const sample = [
  { type: "header", data: { text: "Title", level: 2 } },
  { type: "paragraph", data: { text: "See <span class=\"cdx-wikilink\" contenteditable=\"false\" data-target-uid=\"u1\" data-target-title=\"Other\">Other</span>, <mark class=\"nb-tc-red\">red</mark> H<sub>2</sub>O<sup class=\"cdx-footnote-ref\" data-note-id=\"n1\" data-note=\"A note\" contenteditable=\"false\"></sup> and <data class=\"cdx-mention\" data-kind=\"note\" value=\"note:u2\" contenteditable=\"false\">Mentioned</data>" } },
  { type: "image", data: { images: [{ src: "/notebook/images/abc", alt: "a" }], columns: 1, width: 80, caption: "A <i>caption</i>", credit: "", numbered: true } },
  { type: "paragraph", data: { text: "Plain <b>bold</b> and <i>italic</i> with <code>code</code> and <a href=\"https://x.org\">link</a>" } },
  { type: "list", data: { style: "unordered", items: [{ content: "one", meta: {}, items: [{ content: "nested", meta: {}, items: [] }] }, { content: "two", meta: {}, items: [] }] } },
  { type: "list", data: { style: "ordered", items: [{ content: "first", meta: {}, items: [] }] } },
  { type: "list", data: { style: "checklist", items: [{ content: "done", meta: { checked: true }, items: [] }, { content: "todo", meta: { checked: false }, items: [] }] } },
  { type: "quote", data: { text: "wise words", caption: "Seneca", color: "green" } },
  { type: "callout", data: { type: "tip", title: "Heads up", message: "read <b>this</b>", hideTitle: false } },
  { type: "timeline", data: { showDates: true, color: "purple", items: [{ title: "Start", description: "begin <i>here</i>", date: "2024" }, { title: "End", description: "", date: "" }] } },
  { type: "code", data: { code: "a < b\nprint(1)", language: "python" } },
  { type: "delimiter", data: { style: "dots" } },
  { type: "table", data: { withHeadings: true, content: [["A", "B"], ["1", "2"]] } },
];

function roundTrip(blocks) {
  const handle = create(document.getElementById("m"), blocks, () => {});
  const out = handle.blocks();
  handle.editor.destroy();
  return out;
}

const normalize = (blocks) => JSON.parse(JSON.stringify(blocks).replaceAll("<strong>", "<b>").replaceAll("</strong>", "</b>").replaceAll("<em>", "<i>").replaceAll("</em>", "</i>"));

test("supported blocks survive a round trip", () => {
  assert.equal(lossy(sample), false);
  assert.deepEqual(normalize(roundTrip(sample)), sample);
});

test("blocks the new editor cannot hold yet make the note read-only", () => {
  assert.equal(lossy([{ type: "html", data: { html: "<p>x</p>" } }]), true);
  assert.equal(lossy([{ type: "paragraph", data: { text: "a <span class=\"x\">b</span>" } }]), true);
  assert.equal(lossy([{ type: "paragraph", data: { text: "a" }, tunes: { align: { alignment: "center" } } }]), false);
});

test("an empty note opens", () => {
  assert.deepEqual(roundTrip([]).length <= 1, true);
});

test("markdown pasted or typed anywhere is recognised", async () => {
  const { markdownToHtml } = await import("../src/markdown.js");
  const html = markdownToHtml("# Title\n\n- one\n- [x] done\n\n> [!tip] Heads up\n> body\n\n**bold** and ==mark==\n\n| a | b |\n|---|---|\n| 1 | 2 |\n");
  const handle = create(document.getElementById("m"), [], () => {});
  handle.editor.commands.setContent(html);
  const types = handle.blocks().map((b) => b.type);
  assert.deepEqual(types, ["header", "list", "callout", "paragraph", "table"]);
  handle.editor.destroy();
});

test("a closing marker typed before the opening one is still found", async () => {
  const handle = create(document.getElementById("m"), [{ type: "paragraph", data: { text: "say hello** and bye" } }], () => {});
  const { state } = handle.editor;
  handle.editor.commands.insertContentAt(5, "**");
  handle.editor.commands.setTextSelection(1);
  await new Promise((resolve) => setTimeout(resolve, 700));
  assert.equal(handle.blocks()[0].data.text.includes("<b>") || handle.blocks()[0].data.text.includes("<strong>"), true, handle.blocks()[0].data.text);
  handle.editor.destroy();
});
