// Syntax colors for code blocks: Prism (already on the page) tokenizes, ProseMirror decorations paint the tokens.
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

function tokenSpans(tokens, offset, out, parentTypes) {
  let at = offset;
  for (const token of tokens) {
    if (typeof token === "string") {
      at += token.length;
      continue;
    }
    const types = parentTypes.concat(token.type, token.alias || []);
    const inner = Array.isArray(token.content) ? token.content : [String(token.content)];
    out.push({ from: at, to: at + token.length, classes: "token " + types.join(" ") });
    tokenSpans(inner, at, out, types);
    at += token.length;
  }
}

function decorate(doc) {
  const Prism = window.Prism;
  if (!Prism) return DecorationSet.empty;
  const decorations = [];
  doc.descendants((node, pos) => {
    if (node.type.name !== "codeBlock") return true;
    const grammar = Prism.languages[node.attrs.language];
    if (grammar) {
      const spans = [];
      tokenSpans(Prism.tokenize(node.textContent, grammar), 0, spans, []);
      for (const span of spans) decorations.push(Decoration.inline(pos + 1 + span.from, pos + 1 + span.to, { class: span.classes }));
    }
    return false;
  });
  return DecorationSet.create(doc, decorations);
}

export const CodeHighlight = Extension.create({
  name: "codeHighlight",
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey("codeHighlight"),
        state: {
          init: (_, { doc }) => decorate(doc),
          apply: (tr, old) => (tr.docChanged ? decorate(tr.doc) : old),
        },
        props: { decorations(state) { return this.getState(state); } },
      }),
    ];
  },
});
