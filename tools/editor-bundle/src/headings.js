// Chapter-style numbers before headings (Part I, 1, 1.1, 1.1.1, A), drawn as a data attribute the stylesheet shows.
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

function romanize(num) {
  const table = [[1000, "M"], [900, "CM"], [500, "D"], [400, "CD"], [100, "C"], [90, "XC"], [50, "L"], [40, "XL"], [10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]];
  let out = "";
  for (const [value, letters] of table) while (num >= value) { out += letters; num -= value; }
  return out;
}

function letterize(num) {
  let out = "";
  while (num > 0) {
    out = String.fromCharCode(65 + ((num - 1) % 26)) + out;
    num = Math.floor((num - 1) / 26);
  }
  return out;
}

function numbers(doc) {
  const c = { part: 0, chapter: 0, section: 0, subsection: 0, paragraph: 0 };
  const decorations = [];
  doc.descendants((node, pos) => {
    if (node.type.name !== "heading") return node.isBlock && node.childCount > 0;
    let label = "";
    switch (node.attrs.level) {
      case 1: c.part++; label = romanize(c.part); break;
      case 2: c.chapter++; c.section = 0; c.subsection = 0; label = String(c.chapter); break;
      case 3: c.section++; c.subsection = 0; label = c.chapter + "." + c.section; break;
      case 4: c.subsection++; label = c.chapter + "." + c.section + "." + c.subsection; break;
      default: c.paragraph++; label = letterize(c.paragraph);
    }
    decorations.push(Decoration.node(pos, pos + node.nodeSize, { "data-toc-num": label }));
    return false;
  });
  return DecorationSet.create(doc, decorations);
}

export const HeadingNumbers = Extension.create({
  name: "headingNumbers",
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey("headingNumbers"),
        state: { init: (_, { doc }) => numbers(doc), apply: (tr, old) => (tr.docChanged ? numbers(tr.doc) : old) },
        props: { decorations(state) { return this.getState(state); } },
      }),
    ];
  },
});
