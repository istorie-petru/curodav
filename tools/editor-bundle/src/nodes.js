// The Notebook's own blocks as Tiptap nodes: coloured quote, callout, timeline and divider style.
import { Node, Mark, Extension, mergeAttributes, InputRule } from "@tiptap/core";
import { Plugin, PluginKey, NodeSelection, TextSelection } from "@tiptap/pm/state";
import { TableMap } from "@tiptap/pm/tables";
import Blockquote from "@tiptap/extension-blockquote";
import HorizontalRule from "@tiptap/extension-horizontal-rule";

export const COLORS = ["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "gray"];
export const CALLOUT_TYPES = {
  note: { color: "blue", char: "\ue0f9" },
  tip: { color: "green", char: "\ue07c" },
  warning: { color: "yellow", char: "\ue193" },
  danger: { color: "red", char: "\ue077" },
  important: { color: "purple", char: "\ue176" },
};

const field = (name, tag, content, extra = {}) =>
  Node.create({
    name,
    content,
    defining: true,
    parseHTML: () => [{ tag: `div[data-type="${tag}"]` }],
    renderHTML: ({ HTMLAttributes }) => ["div", mergeAttributes(HTMLAttributes, { "data-type": tag, class: tag }), 0],
    ...extra,
  });


// Shared keyboard helpers: find the enclosing node of a type, and leave a block by adding a paragraph after it.
export const depthOf = ($pos, names) => {
  for (let depth = $pos.depth; depth > 0; depth--) if (names.includes($pos.node(depth).type.name)) return depth;
  return 0;
};

// Puts an empty paragraph after the node at `depth` and moves the caret there. `trim` characters before the caret are deleted first.
export const exitAfter = (editor, depth, trim = 0) =>
  editor.commands.command(({ tr, state }) => {
    const { $from } = state.selection;
    let end = $from.after(depth);
    if (trim) {
      tr.delete($from.pos - trim, $from.pos);
      end -= trim;
    }
    tr.insert(end, state.schema.nodes.paragraph.create());
    tr.setSelection(TextSelection.create(tr.doc, end + 1));
    return true;
  });

// Replaces the node at `depth` with an empty paragraph (an emptied custom block collapses back to plain text).
export const collapseToParagraph = (editor, depth) =>
  editor.commands.command(({ tr, state }) => {
    const { $from } = state.selection;
    const from = $from.before(depth);
    tr.replaceWith(from, $from.after(depth), state.schema.nodes.paragraph.create());
    tr.setSelection(TextSelection.create(tr.doc, from + 1));
    return true;
  });

export const QuoteCaption = field("quoteCaption", "quote-caption", "inline*");

export const Quote = Blockquote.extend({
  content: "paragraph+ quoteCaption?",
  addAttributes() {
    return {
      color: {
        default: "blue",
        parseHTML: (el) => (COLORS.includes(el.getAttribute("data-color")) ? el.getAttribute("data-color") : "blue"),
        renderHTML: (attrs) => ({ "data-color": attrs.color }),
      },
    };
  },
  renderHTML({ HTMLAttributes }) {
    return ["blockquote", mergeAttributes(HTMLAttributes, { class: "cdx-nb-quote" }), 0];
  },
  addKeyboardShortcuts() {
    return {
      // Enter adds a paragraph to the quote; Enter on an empty last paragraph, or in the source line, leaves it.
      Enter: ({ editor }) => {
        const { $from, empty } = editor.state.selection;
        const quote = depthOf($from, ["blockquote"]);
        if (!quote || !empty) return false;
        const kind = $from.parent.type.name;
        if (kind === "quoteCaption") return exitAfter(editor, quote);
        if (kind !== "paragraph" || $from.depth !== quote + 1) return false;
        const last = $from.index(quote) === $from.node(quote).childCount - 1 || $from.node(quote).child($from.index(quote) + 1).type.name === "quoteCaption";
        if ($from.parent.content.size === 0 && last) {
          if ($from.node(quote).childCount === 1) return collapseToParagraph(editor, quote);
          return editor.commands.command(({ tr, state }) => {
            const end = $from.after(quote) - $from.parent.nodeSize;
            tr.delete($from.before(), $from.after());
            tr.insert(end, state.schema.nodes.paragraph.create());
            tr.setSelection(TextSelection.create(tr.doc, end + 1));
            return true;
          });
        }
        return editor.commands.command(({ tr }) => {
          tr.split($from.pos);
          return true;
        });
      },
      // Backspace in an empty source line removes it and goes back to the quote text.
      Backspace: ({ editor }) => {
        const { $from, empty } = editor.state.selection;
        if (!empty || $from.parent.type.name !== "quoteCaption" || $from.parent.content.size) return false;
        return editor.commands.command(({ tr }) => {
          const before = $from.before();
          tr.delete(before, $from.after());
          tr.setSelection(TextSelection.near(tr.doc.resolve(before), -1));
          return true;
        });
      },
    };
  },
});

export const Divider = HorizontalRule.extend({
  addAttributes() {
    return {
      style: {
        default: "stars",
        parseHTML: (el) => el.getAttribute("data-style") || "stars",
        renderHTML: (attrs) => ({ "data-style": attrs.style }),
      },
    };
  },
  renderHTML({ HTMLAttributes }) {
    return ["hr", mergeAttributes(HTMLAttributes, { class: "cdx-nb-delimiter" })];
  },
});

export const CalloutTitle = field("calloutTitle", "callout-title", "inline*");
export const CalloutMessage = field("calloutMessage", "callout-message", "inline*");

export const Callout = Node.create({
  name: "callout",
  group: "block",
  content: "calloutTitle calloutMessage",
  defining: true,
  isolating: true,
  addAttributes() {
    return {
      type: {
        default: "note",
        parseHTML: (el) => (CALLOUT_TYPES[el.getAttribute("data-callout")] ? el.getAttribute("data-callout") : "note"),
        renderHTML: (attrs) => ({ "data-callout": attrs.type }),
      },
      hideTitle: {
        default: false,
        parseHTML: (el) => el.getAttribute("data-hide-title") === "true",
        renderHTML: (attrs) => ({ "data-hide-title": String(attrs.hideTitle) }),
      },
    };
  },
  parseHTML: () => [{ tag: 'div[data-type="callout"]' }],
  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "callout" }), 0];
  },
  addNodeView() {
    return ({ node }) => {
      const dom = document.createElement("div");
      dom.className = "cdx-nb-callout";
      const icon = document.createElement("div");
      icon.className = "cdx-nb-callout__icon";
      icon.contentEditable = "false";
      const body = document.createElement("div");
      body.className = "cdx-nb-callout__body";
      dom.append(icon, body);
      const paint = (n) => {
        const meta = CALLOUT_TYPES[n.attrs.type];
        dom.setAttribute("data-color", meta.color);
        dom.setAttribute("data-hide-title", String(n.attrs.hideTitle));
        icon.textContent = meta.char;
      };
      paint(node);
      return {
        dom,
        contentDOM: body,
        update(updated) {
          if (updated.type !== node.type) return false;
          paint(updated);
          return true;
        },
      };
    };
  },
  addInputRules() {
    // Obsidian's way: "> [!tip] " at the start of a line makes a callout.
    return [
      new InputRule({
        find: /^>\s?\[!(note|tip|warning|danger|important)\]\s$/,
        handler: ({ state, range, match, chain }) => {
          chain()
            .deleteRange(range)
            .insertContentAt(state.selection.$from.before(), {
              type: "callout",
              attrs: { type: match[1] },
              content: [{ type: "calloutTitle" }, { type: "calloutMessage" }],
            })
            .run();
        },
      }),
    ];
  },
  addKeyboardShortcuts() {
    const inside = (editor, names) => names.includes(editor.state.selection.$from.parent.type.name);
    return {
      Enter: ({ editor }) => {
        const { $from } = editor.state.selection;
        if (inside(editor, ["calloutTitle"])) return editor.commands.setTextSelection($from.after() + 1);
        if (inside(editor, ["calloutMessage"])) {
          // A second Enter (a line break right before the caret, or nothing written) leaves the callout.
          const callout = depthOf($from, ["callout"]);
          const before = $from.parent.maybeChild($from.index() - 1);
          const atEnd = $from.parentOffset === $from.parent.content.size;
          if ($from.parent.content.size === 0) return exitAfter(editor, callout);
          if (atEnd && before && before.type.name === "hardBreak") return exitAfter(editor, callout, 1);
          return editor.commands.setHardBreak();
        }
        return false;
      },
      // Backspace never merges the parts: at the start of the text it goes back to the title; an empty callout collapses.
      Backspace: ({ editor }) => {
        const { $from, empty } = editor.state.selection;
        if (!empty || $from.parentOffset !== 0) return false;
        const kind = $from.parent.type.name;
        if (kind !== "calloutTitle" && kind !== "calloutMessage") return false;
        const callout = depthOf($from, ["callout"]);
        const node = $from.node(callout);
        if (!node.textContent.length) return collapseToParagraph(editor, callout);
        if (kind === "calloutMessage") return editor.commands.setTextSelection($from.before() - 1);
        return false;
      },
    };
  },
});

export const TimelineDate = field("timelineDate", "timeline-date", "text*", { marks: "" });
export const TimelineTitle = field("timelineTitle", "timeline-title", "inline*");
export const TimelineDescription = field("timelineDescription", "timeline-desc", "inline*");

export const TimelineItem = Node.create({
  name: "timelineItem",
  content: "timelineDate timelineTitle timelineDescription?",
  defining: true,
  isolating: true,
  parseHTML: () => [{ tag: 'div[data-type="timeline-item"]' }],
  renderHTML: ({ HTMLAttributes }) => ["div", mergeAttributes(HTMLAttributes, { "data-type": "timeline-item", class: "nbtl-item" }), 0],
});

export const Timeline = Node.create({
  name: "timeline",
  group: "block",
  content: "timelineItem+",
  defining: true,
  isolating: true,
  addAttributes() {
    return {
      color: {
        default: "",
        parseHTML: (el) => (COLORS.includes(el.getAttribute("data-color")) ? el.getAttribute("data-color") : ""),
        renderHTML: (attrs) => (attrs.color ? { "data-color": attrs.color } : {}),
      },
      showDates: {
        default: false,
        parseHTML: (el) => el.getAttribute("data-dates") === "true",
        renderHTML: (attrs) => ({ "data-dates": String(attrs.showDates) }),
      },
    };
  },
  parseHTML: () => [{ tag: 'div[data-type="timeline"]' }],
  renderHTML: ({ HTMLAttributes }) => ["div", mergeAttributes(HTMLAttributes, { "data-type": "timeline", class: "nbtl" }), 0],
  addCommands() {
    const spot = (state) => {
      const { $from } = state.selection;
      const item = depthOf($from, ["timelineItem"]);
      return item ? { $from, item, list: item - 1 } : null;
    };
    const blank = (state, withDescription = true) =>
      state.schema.nodes.timelineItem.create(null, [
        state.schema.nodes.timelineDate.create(),
        state.schema.nodes.timelineTitle.create(),
        ...(withDescription ? [state.schema.nodes.timelineDescription.create()] : []),
      ]);
    return {
      timelineAddItem: () => ({ tr, state }) => {
        const at = spot(state);
        if (!at) return false;
        const end = at.$from.after(at.item);
        tr.insert(end, blank(state));
        tr.setSelection(TextSelection.create(tr.doc, end + 4));
        return true;
      },
      timelineDeleteItem: () => ({ tr, state }) => {
        const at = spot(state);
        if (!at) return false;
        const { $from, item, list } = at;
        const parent = $from.node(list);
        if (parent.childCount < 2) return false;
        const index = $from.index(list);
        tr.delete($from.before(item), $from.after(item));
        let start = $from.start(list);
        for (let i = 0; i < Math.max(0, index - 1); i++) start += parent.child(i).nodeSize;
        tr.setSelection(TextSelection.near(tr.doc.resolve(start + 2), 1));
        return true;
      },
      timelineMoveItem: (direction) => ({ tr, state }) => {
        const at = spot(state);
        if (!at) return false;
        const { $from, item, list } = at;
        const index = $from.index(list);
        const parent = $from.node(list);
        const to = index + direction;
        if (to < 0 || to >= parent.childCount) return false;
        const from = $from.before(item);
        const node = parent.child(index);
        const caret = $from.pos - from;
        tr.delete(from, from + node.nodeSize);
        const target = direction < 0 ? from - parent.child(to).nodeSize : from + parent.child(to).nodeSize;
        tr.insert(target, node);
        tr.setSelection(TextSelection.create(tr.doc, target + caret));
        return true;
      },
      timelineToggleDescription: () => ({ tr, state }) => {
        const at = spot(state);
        if (!at) return false;
        const { $from, item } = at;
        const node = $from.node(item);
        const start = $from.start(item);
        if (node.childCount > 2) {
          const last = node.lastChild;
          const from = start + node.content.size - last.nodeSize;
          tr.delete(from, from + last.nodeSize);
          tr.setSelection(TextSelection.near(tr.doc.resolve(from - 1), -1));
        } else {
          const end = start + node.content.size;
          tr.insert(end, state.schema.nodes.timelineDescription.create());
          tr.setSelection(TextSelection.create(tr.doc, end + 1));
        }
        return true;
      },
    };
  },
  addKeyboardShortcuts() {
    const where = (editor) => {
      const { $from } = editor.state.selection;
      const depth = depthOf($from, ["timelineItem"]);
      return depth ? { depth, $from } : null;
    };
    const blankItem = (item) => !item.textContent.length;
    return {
      // Enter walks date, title, description, then adds an item; on an empty item it leaves the timeline instead.
      Enter: ({ editor }) => {
        const spot = where(editor);
        if (!spot) return false;
        const { $from, depth } = spot;
        const item = $from.node(depth);
        const field = $from.parent.type.name;
        const last = field === "timelineDescription" || (field === "timelineTitle" && item.childCount < 3);
        if (!last) return editor.commands.setTextSelection($from.after() + 1);
        if (blankItem(item)) {
          if ($from.node(depth - 1).childCount < 2) return collapseToParagraph(editor, depth - 1);
          return editor.commands.command(({ tr, state }) => {
            const from = $from.before(depth);
            const to = $from.after(depth);
            const end = $from.after(depth - 1) - (to - from);
            tr.delete(from, to);
            tr.insert(end, state.schema.nodes.paragraph.create());
            tr.setSelection(TextSelection.create(tr.doc, end + 1));
            return true;
          });
        }
        return editor.commands.timelineAddItem();
      },
      "Mod-Enter": ({ editor }) => {
        const spot = where(editor);
        return spot ? exitAfter(editor, spot.depth - 1) : false;
      },
      // Backspace removes an empty item (the last one turns the timeline into a paragraph) or an empty description.
      Backspace: ({ editor }) => {
        const spot = where(editor);
        const { empty } = editor.state.selection;
        if (!spot || !empty) return false;
        const { $from, depth } = spot;
        const item = $from.node(depth);
        const field = $from.parent.type.name;
        if ($from.parentOffset !== 0) return false;
        if (blankItem(item)) {
          if ($from.node(depth - 1).childCount < 2) return collapseToParagraph(editor, depth - 1);
          return editor.commands.timelineDeleteItem();
        }
        if (field === "timelineDescription" && !$from.parent.content.size) return editor.commands.timelineToggleDescription();
        return false;
      },
    };
  },
});

// Clicking a block's edge or icon, or pressing Escape inside one, selects the whole block (so it can be moved or deleted).
const SELECTABLE = ["blockquote", "callout", "timeline", "table", "figure", "horizontalRule", "codeBlock", "bulletList", "orderedList", "taskList", "heading", "paragraph"];
const CLICK_SELECTABLE = ["blockquote", "callout", "timeline", "table", "figure", "horizontalRule"];
export const BlockSelect = Extension.create({
  name: "blockSelect",
  addKeyboardShortcuts() {
    return {
      Escape: ({ editor }) => {
        const { selection, doc } = editor.state;
        if (selection.node || selection.$from.depth < 1) return false;
        const top = selection.$from.node(1);
        if (!SELECTABLE.includes(top.type.name)) return false;
        return editor.commands.setNodeSelection(selection.$from.before(1));
      },
    };
  },
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey("blockSelect"),
        props: {
          handleClickOn(view, pos, node, nodePos, event) {
            if (!CLICK_SELECTABLE.includes(node.type.name)) return false;
            const dom = view.nodeDOM(nodePos);
            const onEdge = event.target === dom || (event.target.closest && event.target.closest(".cdx-nb-callout__icon"));
            if (!onEdge) return false;
            view.dispatch(view.state.tr.setSelection(NodeSelection.create(view.state.doc, nodePos)));
            return true;
          },
        },
      }),
    ];
  },
});

export const BlockExtensions = [BlockSelect, Quote, QuoteCaption, Divider, Callout, CalloutTitle, CalloutMessage, Timeline, TimelineItem, TimelineDate, TimelineTitle, TimelineDescription];

// Inline pieces other tools make: endnote markers, wikilinks and mentions. They are kept exactly as stored
// (tag, attributes, inner markup) so nothing is lost until each gets its own editing tool.
function rawInline(name, tag, selector) {
  return Node.create({
    name,
    group: "inline",
    inline: true,
    atom: true,
    selectable: true,
    priority: 1000,
    addAttributes() {
      return {
        bag: { default: {}, parseHTML: (el) => Object.fromEntries(el.getAttributeNames().map((n) => [n, el.getAttribute(n)])), renderHTML: () => ({}) },
        inner: { default: "", parseHTML: (el) => (el.matches("sup") ? "" : el.innerHTML), renderHTML: () => ({}) },
      };
    },
    parseHTML: () => [{ tag: selector, priority: 1000 }],
    renderHTML({ node }) {
      const el = document.createElement(tag);
      for (const [key, value] of Object.entries(node.attrs.bag)) el.setAttribute(key, value);
      el.contentEditable = "false";
      if (tag === "sup" && node.attrs.bag["data-note"]) el.title = node.attrs.bag["data-note"].replace(/<[^>]*>/g, "");
      el.innerHTML = node.attrs.inner;
      return el;
    },
  });
}

export const Endnote = rawInline("endnote", "sup", "sup.cdx-footnote-ref");
export const Wikilink = rawInline("wikilink", "span", "span.cdx-wikilink");
export const Mention = rawInline("mention", "data", "data.cdx-mention");

export const TextColor = Mark.create({
  name: "textColor",
  parseHTML: () => [{ tag: "mark" }],
  addAttributes() {
    return { class: { default: null } };
  },
  renderHTML: ({ HTMLAttributes }) => ["mark", HTMLAttributes, 0],
});

export const Figure = Node.create({
  name: "figure",
  group: "block",
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      data: {
        default: {},
        parseHTML: (el) => {
          try {
            return JSON.parse(el.getAttribute("data-json") || "{}");
          } catch (err) {
            return {};
          }
        },
        renderHTML: (attrs) => ({ "data-json": JSON.stringify(attrs.data) }),
      },
    };
  },
  parseHTML: () => [{ tag: 'div[data-type="figure"]' }],
  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-type": "figure" })];
  },
  addNodeView() {
    return ({ node }) => {
      const dom = document.createElement("figure");
      dom.className = "nbfig";
      dom.contentEditable = "false";
      const paint = (n) => {
        const d = n.attrs.data || {};
        const images = d.images || (d.url ? [{ src: d.url, alt: d.caption || "" }] : []);
        dom.replaceChildren();
        dom.setAttribute("data-width", String(Math.round((d.width || 100) / 5) * 5));
        if (d.numbered) dom.setAttribute("data-numbered", "true");
        else dom.removeAttribute("data-numbered");
        const grid = document.createElement("div");
        grid.className = "nbfig-grid";
        grid.setAttribute("data-columns", String(d.columns || 1));
        for (const image of images) {
          const img = document.createElement("img");
          img.src = image.src;
          img.alt = image.alt || "";
          grid.appendChild(img);
        }
        dom.appendChild(grid);
        const caption = [d.caption, d.credit].filter(Boolean).join(" ");
        if (caption) {
          const text = document.createElement("figcaption");
          text.innerHTML = caption;
          dom.appendChild(text);
        }
      };
      paint(node);
      return {
        dom,
        update(updated) {
          if (updated.type !== node.type) return false;
          paint(updated);
          return true;
        },
      };
    };
  },
});

BlockExtensions.push(Endnote, Wikilink, Mention, TextColor, Figure);
