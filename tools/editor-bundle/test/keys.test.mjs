import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><body><div id='m'></div></body>", { pretendToBeVisual: true });
for (const key of ["window", "document", "navigator", "Node", "HTMLElement", "Element", "DOMParser", "MutationObserver", "getComputedStyle", "Range", "Selection", "KeyboardEvent"]) {
  Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true, writable: true });
}
globalThis.requestAnimationFrame = globalThis.requestAnimationFrame || ((cb) => setTimeout(cb, 0));
globalThis.cancelAnimationFrame = globalThis.cancelAnimationFrame || clearTimeout;
const { create } = await import("../src/index.js");
const { NodeSelection } = await import("@tiptap/pm/state");

const open = (blocks) => {
  document.getElementById("m").innerHTML = "";
  return create(document.getElementById("m"), blocks, () => {}).editor;
};
const press = (editor, key, mods = {}) => {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...mods });
  const view = editor.view;
  return !!view.someProp("handleKeyDown", (f) => f(view, event));
};
// Puts the caret at the start or end of the first text block whose text matches.
const caret = (editor, text, where = "end") => {
  let pos = null;
  editor.state.doc.descendants((node, p) => {
    if (pos === null && node.isTextblock && (text === "" ? node.content.size === 0 : node.textContent === text)) pos = where === "end" ? p + node.nodeSize - 1 : p + 1;
  });
  assert.notEqual(pos, null, `no block with text "${text}"`);
  editor.commands.setTextSelection(pos);
};
const kinds = (editor) => editor.getJSON().content.map((n) => n.type);
const P = (text) => ({ type: "paragraph", data: { text } });
const list = (...items) => ({ type: "list", data: { style: "unordered", items: items.map((content) => ({ content, meta: {}, items: [] })) } });
const timeline = (...items) => ({ type: "timeline", data: { showDates: false, color: "", items: items.map(([title, description]) => ({ title, description, date: "" })) } });

test("Enter in a quote adds a paragraph, and Enter on an empty one or in the source line leaves it", () => {
  const e = open([{ type: "quote", data: { text: "q", caption: "src", color: "blue" } }]);
  caret(e, "q");
  press(e, "Enter");
  assert.equal(e.getJSON().content[0].content.filter((n) => n.type === "paragraph").length, 2);
  press(e, "Enter");
  assert.deepEqual(kinds(e), ["blockquote", "paragraph"]);
  assert.equal(e.getJSON().content[0].content.filter((n) => n.type === "paragraph").length, 1);
  caret(e, "src");
  press(e, "Enter");
  assert.deepEqual(kinds(e), ["blockquote", "paragraph", "paragraph"]);
});

test("a callout is left with a second Enter or Ctrl+Enter, and an empty one collapses with Backspace", () => {
  const e = open([{ type: "callout", data: { type: "note", title: "t", message: "m" } }]);
  caret(e, "m");
  press(e, "Enter");
  assert.deepEqual(kinds(e), ["callout"]);
  press(e, "Enter");
  assert.deepEqual(kinds(e), ["callout", "paragraph"]);
  assert.equal(e.getJSON().content[0].content[1].content[0].text, "m");
  assert.equal(JSON.stringify(e.getJSON().content[0]).includes("hardBreak"), false);
  const empty = open([{ type: "callout", data: { type: "note", title: "", message: "" } }, P("after")]);
  caret(empty, "", "start");
  press(empty, "Backspace");
  assert.deepEqual(kinds(empty), ["paragraph", "paragraph"]);
  const ctrl = open([{ type: "callout", data: { type: "note", title: "t", message: "m" } }]);
  caret(ctrl, "m");
  press(ctrl, "Enter", { ctrlKey: true });
  assert.deepEqual(kinds(ctrl), ["callout", "paragraph"]);
});

test("a timeline is left with Enter on an empty item, and its last empty item turns into a paragraph", () => {
  const e = open([timeline(["a", "b"])]);
  caret(e, "b");
  press(e, "Enter");
  assert.equal(e.getJSON().content[0].content.length, 2);
  press(e, "Enter");
  press(e, "Enter");
  assert.deepEqual(kinds(e), ["timeline", "paragraph"]);
  assert.equal(e.getJSON().content[0].content.length, 1);
  const single = open([timeline(["", ""])]);
  caret(single, "", "start");
  press(single, "Backspace");
  assert.deepEqual(kinds(single), ["paragraph"]);
});

test("a timeline item can drop its description, and items can be added, moved and removed", () => {
  const e = open([timeline(["one", "d1"], ["two", "d2"])]);
  caret(e, "d1");
  e.commands.timelineToggleDescription();
  const stored = JSON.stringify(e.getJSON());
  assert.equal(stored.includes("d1"), false);
  const handleBlocks = (editor) => JSON.parse(JSON.stringify(editor.getJSON()));
  assert.equal(handleBlocks(e).content[0].content[0].content.length, 2);
  e.commands.timelineToggleDescription();
  assert.equal(handleBlocks(e).content[0].content[0].content.length, 3);
  caret(e, "one");
  e.commands.timelineMoveItem(1);
  let titles = e.state.doc.child(0).content.content.map((item) => item.child(1).textContent);
  assert.deepEqual(titles, ["two", "one"]);
  e.commands.timelineAddItem();
  assert.equal(e.state.doc.child(0).childCount, 3);
  e.commands.timelineDeleteItem();
  assert.equal(e.state.doc.child(0).childCount, 2);
});

test("Backspace at the start of a list item with text takes it out of the list, and the whole list can be unwrapped", () => {
  const e = open([list("one", "two", "three")]);
  caret(e, "two", "start");
  press(e, "Backspace");
  assert.deepEqual(kinds(e), ["bulletList", "paragraph", "bulletList"]);
  assert.equal(e.state.doc.child(1).textContent, "two");
  const all = open([list("one", "two", "three")]);
  caret(all, "two");
  all.commands.unwrapList();
  assert.deepEqual(kinds(all), ["paragraph", "paragraph", "paragraph"]);
  assert.equal(all.state.doc.textContent, "onetwothree");
});

test("Enter in a table cell moves down and adds a row at the end; columns can be aligned and resized widths are kept", () => {
  const e = open([{ type: "table", data: { withHeadings: false, content: [["a", "b"], ["c", "d"]] } }]);
  caret(e, "a");
  press(e, "Enter");
  assert.equal(e.state.selection.$from.parent.textContent, "c");
  press(e, "Enter");
  assert.equal(e.state.doc.child(0).childCount, 3);
  caret(e, "b");
  e.commands.alignColumn("right");
  const blocks = create(document.getElementById("m"), [{ type: "table", data: { content: [["x", "y"]], align: { 1: "center" }, colWidths: [120, 0] } }], () => {}).blocks();
  assert.deepEqual([blocks[0].data.align, blocks[0].data.colWidths], [{ 1: "center" }, [120, 0]]);
  assert.equal(e.state.doc.child(0).child(0).child(1).attrs.align, "right");
});

test("Tab indents code, Backspace turns a heading into a paragraph, Escape selects a code block", () => {
  const e = open([{ type: "code", data: { code: "x", language: "js" } }, { type: "header", data: { text: "H", level: 2 } }]);
  caret(e, "x", "start");
  press(e, "Tab");
  assert.equal(e.state.doc.child(0).textContent, "  x");
  press(e, "Escape");
  assert.ok(e.state.selection instanceof NodeSelection);
  caret(e, "H", "start");
  press(e, "Backspace");
  assert.deepEqual(kinds(e), ["codeBlock", "paragraph"]);
});

test("blocks can be moved and duplicated from the keyboard, and Ctrl+Enter leaves a table", () => {
  const e = open([P("a"), P("b")]);
  caret(e, "b");
  press(e, "ArrowUp", { altKey: true });
  assert.deepEqual(e.state.doc.content.content.map((n) => n.textContent), ["b", "a"]);
  press(e, "d", { ctrlKey: true });
  assert.deepEqual(e.state.doc.content.content.map((n) => n.textContent), ["b", "b", "a"]);
  const t = open([{ type: "table", data: { content: [["x"]] } }]);
  caret(t, "x");
  press(t, "Enter", { ctrlKey: true });
  assert.deepEqual(kinds(t), ["table", "paragraph"]);
});

test("converting does not run on each change", () => {
  let calls = 0;
  document.getElementById("m").innerHTML = "";
  const handle = create(document.getElementById("m"), [P("a")], (value) => { calls += 1; assert.equal(value, undefined); });
  handle.editor.commands.insertContentAt(1, "x");
  assert.equal(calls, 1);
  assert.equal(handle.blocks()[0].data.text, "xa");
});

test("the slash menu adds blocks from an empty line and filters as you type", () => {
  const e = open([P("")]);
  e.commands.insertContent("/");
  e.commands.insertContent("call");
  assert.ok(document.querySelector(".nbslash"));
  press(e, "Enter");
  assert.deepEqual(kinds(e), ["callout"]);
  const t = open([P("")]);
  t.commands.insertContent("/tab");
  press(t, "Enter");
  assert.deepEqual(kinds(t), ["table"]);
  const down = open([P("")]);
  down.commands.insertContent("/");
  press(down, "ArrowDown");
  press(down, "Enter");
  assert.deepEqual(kinds(down), ["heading"]);
  assert.equal(down.getJSON().content[0].attrs.level, 2);
  const esc = open([P("")]);
  esc.commands.insertContent("/q");
  press(esc, "Escape");
  assert.equal(document.querySelector(".nbslash"), null);
  assert.deepEqual(kinds(esc), ["paragraph"]);
  const mid = open([P("some text")]);
  mid.commands.setTextSelection(10);
  mid.commands.insertContent("/q");
  assert.equal(document.querySelector(".nbslash"), null);
});
