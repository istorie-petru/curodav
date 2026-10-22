// The Notebook's own blocks as Tiptap nodes: coloured quote, callout, timeline and divider style.
import { Node, Mark, Extension, mergeAttributes, InputRule } from "@tiptap/core";
import { Plugin, PluginKey, NodeSelection } from "@tiptap/pm/state";
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
        if (inside(editor, ["calloutTitle"])) {
          const { $from } = editor.state.selection;
          return editor.commands.setTextSelection($from.after() + 1);
        }
        if (inside(editor, ["calloutMessage"])) return editor.commands.setHardBreak();
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
  content: "timelineDate timelineTitle timelineDescription",
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
  addKeyboardShortcuts() {
    const where = (editor) => {
      const { $from } = editor.state.selection;
      for (let depth = $from.depth; depth > 0; depth--) if ($from.node(depth).type.name === "timelineItem") return { depth, $from };
      return null;
    };
    return {
      Enter: ({ editor }) => {
        const spot = where(editor);
        if (!spot) return false;
        const { $from, depth } = spot;
        const field = $from.parent.type.name;
        if (field === "timelineDate" || field === "timelineTitle") return editor.commands.setTextSelection($from.after() + 1);
        const itemEnd = $from.after(depth);
        return editor
          .chain()
          .insertContentAt(itemEnd, { type: "timelineItem", content: [{ type: "timelineDate" }, { type: "timelineTitle" }, { type: "timelineDescription" }] })
          .setTextSelection(itemEnd + 4)
          .run();
      },
      Backspace: ({ editor }) => {
        const spot = where(editor);
        if (!spot) return false;
        const { $from, depth } = spot;
        const item = $from.node(depth);
        const list = $from.node(depth - 1);
        if (item.textContent.length || $from.parentOffset !== 0 || list.childCount < 2) return false;
        return editor.chain().deleteRange({ from: $from.before(depth), to: $from.after(depth) }).run();
      },
    };
  },
});

// Clicking a block's edge or icon, or pressing Escape inside one, selects the whole block (so it can be moved or deleted).
const SELECTABLE = ["blockquote", "callout", "timeline", "table", "figure", "horizontalRule"];
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
            if (!SELECTABLE.includes(node.type.name)) return false;
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
    return { class: { default: "" } };
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
