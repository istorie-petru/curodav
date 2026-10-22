// Markdown in, the way Obsidian reads it: pasted text becomes blocks, and typed text is recognised wherever and
// whenever the closing marker lands (before or after the rest, minutes later, in text that was already there).
import { marked } from "marked";
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";

const CALLOUT_TYPES = ["note", "tip", "warning", "danger", "important"];

marked.setOptions({ gfm: true, breaks: false });

function escapeHtml(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function looksLikeMarkdown(text) {
  return /^(#{1,6} |[-*+] |\d+[.)] |> |```|---\s*$|\|.+\|)/m.test(text) || /\*\*[^*\n]+\*\*|~~[^~\n]+~~|==[^=\n]+==|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\)/.test(text);
}

// Obsidian callouts: "> [!tip] Title" opens a quote that becomes a callout.
function calloutFrom(quote) {
  const first = quote.firstElementChild;
  const match = first && /^\s*\[!(\w+)\][ \t]*([^\n]*)/.exec(first.textContent);
  if (!match || !CALLOUT_TYPES.includes(match[1].toLowerCase())) return null;
  const rest = first.innerHTML.replace(/^\s*\[!\w+\][ \t]*/, "").split("\n");
  const title = rest.shift() || "";
  const body = [rest.join("<br>"), ...Array.from(quote.children).slice(1).map((child) => child.innerHTML)].filter(Boolean).join("<br>");
  return `<div data-type="callout" data-callout="${match[1].toLowerCase()}" data-hide-title="${title ? "false" : "true"}"><div data-type="callout-title">${title}</div><div data-type="callout-message">${body}</div></div>`;
}

export function markdownToHtml(text) {
  const holder = document.createElement("div");
  holder.innerHTML = marked.parse(text.replace(/\r\n?/g, "\n"));
  holder.querySelectorAll("blockquote").forEach((quote) => {
    const callout = calloutFrom(quote);
    if (callout) {
      const wrap = document.createElement("div");
      wrap.innerHTML = callout;
      quote.replaceWith(wrap.firstChild);
    }
  });
  holder.querySelectorAll("li > input[type=checkbox]").forEach((box) => {
    const list = box.parentElement.parentElement;
    list.setAttribute("data-type", "taskList");
    box.parentElement.setAttribute("data-checked", box.checked ? "true" : "false");
    const next = box.nextSibling;
    if (next && next.nodeType === 3) next.textContent = next.textContent.replace(/^\s+/, "");
    box.remove();
  });
  holder.querySelectorAll("ul[data-type=taskList] > li").forEach((item) => {
    item.setAttribute("data-type", "taskItem");
    if (!item.hasAttribute("data-checked")) item.setAttribute("data-checked", "false");
  });
  holder.querySelectorAll("h6").forEach((heading) => {
    const five = document.createElement("h5");
    five.innerHTML = heading.innerHTML;
    heading.replaceWith(five);
  });
  holder.querySelectorAll("img").forEach((img) => img.replaceWith(document.createTextNode(img.getAttribute("alt") || "")));
  return holder.innerHTML;
}

// ---- Inline patterns, found anywhere in a text block ----
const PATTERNS = [
  { re: /\*\*(?=\S)([^*\n]+?)(?<=\S)\*\*/g, mark: "bold", open: 2, close: 2 },
  { re: /__(?=\S)([^_\n]+?)(?<=\S)__/g, mark: "bold", open: 2, close: 2 },
  { re: /(?<![*\w])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![*\w])/g, mark: "italic", open: 1, close: 1 },
  { re: /(?<![_\w])_(?=[^\s_])([^_\n]+?)(?<=[^\s_])_(?![_\w])/g, mark: "italic", open: 1, close: 1 },
  { re: /~~(?=\S)([^~\n]+?)(?<=\S)~~/g, mark: "strike", open: 2, close: 2 },
  { re: /==(?=\S)([^=\n]+?)(?<=\S)==/g, mark: "textColor", attrs: { class: "nb-hl-yellow" }, open: 2, close: 2 },
  { re: /`([^`\n]+)`/g, mark: "code", open: 1, close: 1 },
];
const LINK = /\[([^\]\n]+)\]\(((?:https?:\/\/|mailto:)[^)\s]+)\)/g;
const HOLE = "￼";

// The text of a block with one character per position; anything that is not plain text (or is code) is a hole.
function flatten(block, start) {
  const chars = [];
  const positions = [];
  block.descendants((node, pos) => {
    if (node.isText) {
      const code = node.marks.some((m) => m.type.name === "code");
      for (let i = 0; i < node.text.length; i++) {
        chars.push(code ? HOLE : node.text[i]);
        positions.push(start + 1 + pos + i);
      }
    } else if (node.isInline) {
      chars.push(HOLE);
      positions.push(start + 1 + pos);
    }
    return true;
  });
  return { text: chars.join(""), positions };
}

function findMatches(text) {
  const found = [];
  for (const pattern of PATTERNS) {
    for (const m of text.matchAll(pattern.re)) {
      if (m[1].includes(HOLE)) continue;
      found.push({ from: m.index, to: m.index + m[0].length, open: pattern.open, close: pattern.close, mark: pattern.mark, attrs: pattern.attrs });
    }
  }
  for (const m of text.matchAll(LINK)) {
    if (m[0].includes(HOLE)) continue;
    found.push({ from: m.index, to: m.index + m[0].length, link: { label: m[1], href: m[2] } });
  }
  found.sort((a, b) => a.from - b.from || b.to - a.to);
  const kept = [];
  for (const match of found) if (!kept.length || match.from >= kept[kept.length - 1].to) kept.push(match);
  return kept;
}

function convertBlock(view, blockStart) {
  const { state } = view;
  const block = state.doc.nodeAt(blockStart);
  if (!block || !block.isTextblock || block.type.name === "codeBlock") return false;
  const { text, positions } = flatten(block, blockStart);
  const sel = state.selection;
  const matches = findMatches(text).filter((m) => {
    const from = positions[m.from];
    const to = positions[m.to - 1] + 1;
    return sel.to < from || sel.from > to;
  });
  if (!matches.length) return false;
  const tr = state.tr;
  for (const m of matches.reverse()) {
    const from = positions[m.from];
    const to = positions[m.to - 1] + 1;
    if (m.link) {
      tr.replaceWith(from, to, state.schema.text(m.link.label, [state.schema.marks.link.create({ href: m.link.href })]));
      continue;
    }
    const markType = state.schema.marks[m.mark];
    if (!markType) continue;
    tr.delete(to - m.close, to);
    tr.delete(from, from + m.open);
    tr.addMark(from, to - m.open - m.close, markType.create(m.attrs || null));
  }
  tr.setMeta("markdownScan", true);
  view.dispatch(tr);
  return true;
}

const key = new PluginKey("markdownScan");

export const Markdown = Extension.create({
  name: "markdownPaste",
  addProseMirrorPlugins() {
    const editor = this.editor;
    return [
      new Plugin({
        key,
        props: {
          handlePaste(view, event) {
            const data = event.clipboardData;
            const text = data && data.getData("text/plain");
            if (!text || view.state.selection.$from.parent.type.name === "codeBlock") return false;
            const fromEditor = data.types.includes("vscode-editor-data");
            if ((data.types.includes("text/html") && !fromEditor) || !looksLikeMarkdown(text)) return false;
            editor.commands.insertContent(markdownToHtml(text));
            return true;
          },
        },
        view(view) {
          let timer = null;
          const dirty = new Set();
          return {
            update(updated, previous) {
              if (updated.state.doc.eq(previous.doc) && updated.state.selection.eq(previous.selection)) return;
              const start = previous.doc.content.findDiffStart(updated.state.doc.content);
              const end = updated.state.doc.content.findDiffEnd(previous.doc.content);
              if (start != null && end) {
                const to = Math.min(end.b, updated.state.doc.content.size);
                updated.state.doc.nodesBetween(Math.min(start, to), to, (node, pos) => {
                  if (node.isTextblock) dirty.add(pos);
                  return !node.isTextblock;
                });
              }
              clearTimeout(timer);
              timer = setTimeout(() => {
                const blocks = [...dirty];
                dirty.clear();
                const sel = view.state.selection;
                for (const start of blocks) {
                  const node = view.state.doc.nodeAt(start);
                  if (node && sel.from >= start && sel.to <= start + node.nodeSize) dirty.add(start);
                }
                const seen = new Set();
                for (const start of blocks.sort((a, b) => b - a)) {
                  const live = view.state.doc.resolve(Math.min(start, view.state.doc.content.size));
                  const at = live.nodeAfter && live.nodeAfter.isTextblock ? start : null;
                  if (at != null && !seen.has(at)) {
                    seen.add(at);
                    convertBlock(view, at);
                  }
                }
              }, 400);
            },
            destroy() {
              clearTimeout(timer);
            },
          };
        },
      }),
    ];
  },
});
