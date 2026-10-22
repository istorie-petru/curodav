// Converts between the stored Editor.js block list and the Tiptap document, so the server keeps reading
// the same data. Anything the new editor cannot hold yet is reported by `lossy` and the note opens read-only.
import { DOMSerializer } from "@tiptap/pm/model";

const SUPPORTED_INLINE = new Set(["b", "strong", "i", "em", "s", "strike", "del", "u", "code", "a", "br", "mark", "sub", "sup", "data"]);
const SUPPORTED_BLOCKS = new Set(["paragraph", "header", "list", "quote", "code", "delimiter", "table", "callout", "timeline", "image"]);
const COLORS = ["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "gray"];
const CALLOUT_TYPES = ["note", "tip", "warning", "danger", "important"];

function escapeHtml(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function inlineIsSupported(markup) {
  for (const match of String(markup || "").matchAll(/<\/?([a-zA-Z][a-zA-Z0-9]*)([^>]*)>/g)) {
    const tag = match[1].toLowerCase();
    if (tag === "span") {
      if (!/class="[^"]*cdx-wikilink/.test(match[2]) && !match[0].startsWith("</")) return false;
    } else if (tag === "svg" || tag === "use" || tag === "path") {
      continue;
    } else if (!SUPPORTED_INLINE.has(tag)) return false;
  }
  return true;
}

function listItemsSupported(items) {
  return (items || []).every((item) => inlineIsSupported(item.content) && listItemsSupported(item.items));
}

function blockIsSupported(block) {
  const data = block.data || {};
  if (!SUPPORTED_BLOCKS.has(block.type)) return false;
  switch (block.type) {
    case "paragraph":
      return inlineIsSupported(data.text);
    case "header":
      return inlineIsSupported(data.text) && data.level >= 1 && data.level <= 5;
    case "quote":
      return inlineIsSupported(data.text);
    case "callout":
      return inlineIsSupported(data.title) && inlineIsSupported(data.message) && CALLOUT_TYPES.includes(data.type || "note");
    case "timeline":
      return (data.items || []).every((item) => inlineIsSupported(item.title) && inlineIsSupported(item.description) && !/[<&]/.test(item.date || ""));
    case "image":
      return Array.isArray(data.images) ? data.images.length > 0 : !!data.url;
    case "delimiter":
      return ["stars", "dots", "line"].includes(data.style || "stars");
    case "list":
      return listItemsSupported(data.items);
    case "table":
      return (data.content || []).every((row) => row.every((cell) => typeof cell === "string" && inlineIsSupported(cell)));
    default:
      return true;
  }
}

export function lossy(blocks) {
  return (blocks || []).some((block) => !blockIsSupported(block));
}

// The block types the new editor cannot hold yet, for the library check.
export function unsupportedBlocks(blocks) {
  return [...new Set((blocks || []).filter((block) => !blockIsSupported(block)).map((block) => block.type))];
}

function listHtml(data) {
  const style = data.style === "ordered" ? "ol" : data.style === "checklist" ? "ul" : "ul";
  const checklist = data.style === "checklist";
  const render = (items) =>
    `<${style}${checklist ? ' data-type="taskList"' : ""}>` +
    (items || [])
      .map((item) => {
        const checked = checklist ? ` data-type="taskItem" data-checked="${item.meta && item.meta.checked ? "true" : "false"}"` : "";
        return `<li${checked}><p>${item.content || ""}</p>${item.items && item.items.length ? render(item.items) : ""}</li>`;
      })
      .join("") +
    `</${style}>`;
  return render(data.items);
}

export function blocksToHtml(blocks) {
  return (blocks || [])
    .map((block) => {
      const data = block.data || {};
      switch (block.type) {
        case "paragraph":
          return `<p>${data.text || ""}</p>`;
        case "header":
          return `<h${data.level}>${data.text || ""}</h${data.level}>`;
        case "list":
          return listHtml(data);
        case "quote":
          return `<blockquote data-color="${COLORS.includes(data.color) ? data.color : "blue"}"><p>${data.text || ""}</p>${data.caption ? `<div data-type="quote-caption">${inlineIsSupported(data.caption) ? data.caption : escapeHtml(data.caption)}</div>` : ""}</blockquote>`;
        case "image":
          return `<div data-type="figure" data-json="${escapeHtml(JSON.stringify(data)).replace(/"/g, "&quot;")}"></div>`;
        case "callout":
          return `<div data-type="callout" data-callout="${data.type || "note"}" data-hide-title="${!!data.hideTitle}"><div data-type="callout-title">${data.title || ""}</div><div data-type="callout-message">${data.message || ""}</div></div>`;
        case "timeline":
          return (
            `<div data-type="timeline" data-color="${data.color || ""}" data-dates="${!!data.showDates}">` +
            (data.items || [])
              .map((item) => `<div data-type="timeline-item"><div data-type="timeline-date">${escapeHtml(item.date || "")}</div><div data-type="timeline-title">${item.title || ""}</div><div data-type="timeline-desc">${item.description || ""}</div></div>`)
              .join("") +
            "</div>"
          );
        case "code":
          return `<pre><code class="language-${escapeHtml(data.language || "plaintext")}">${escapeHtml(data.code || "")}</code></pre>`;
        case "delimiter":
          return `<hr data-style="${data.style || "stars"}">`;
        case "table": {
          const rows = data.content || [];
          return (
            "<table><tbody>" +
            rows.map((row, r) => "<tr>" + row.map((cell) => `<${data.withHeadings && r === 0 ? "th" : "td"}><p>${cell}</p></${data.withHeadings && r === 0 ? "th" : "td"}>`).join("") + "</tr>").join("") +
            "</tbody></table>"
          );
        }
        default:
          return "";
      }
    })
    .join("");
}

export function docToBlocks(doc, schema) {
  const serializer = DOMSerializer.fromSchema(schema);
  const inline = (node) => {
    const holder = document.createElement("div");
    holder.appendChild(serializer.serializeFragment(node.content));
    holder.querySelectorAll("a[title], sup.cdx-footnote-ref[title]").forEach((el) => el.removeAttribute("title"));
    return holder.innerHTML;
  };
  const listData = (node, style) => ({
    style,
    items: node.content.content.map((item) => {
      const entry = { content: inline(item.firstChild), meta: style === "checklist" ? { checked: !!item.attrs.checked } : {}, items: [] };
      const nested = item.content.content.slice(1).find((child) => /List$/.test(child.type.name));
      if (nested) entry.items = listData(nested, style).items;
      return entry;
    }),
  });
  const blocks = [];
  doc.forEach((node) => {
    switch (node.type.name) {
      case "paragraph":
        blocks.push({ type: "paragraph", data: { text: inline(node) } });
        break;
      case "heading":
        blocks.push({ type: "header", data: { text: inline(node), level: node.attrs.level } });
        break;
      case "bulletList":
        blocks.push({ type: "list", data: listData(node, "unordered") });
        break;
      case "orderedList":
        blocks.push({ type: "list", data: listData(node, "ordered") });
        break;
      case "taskList":
        blocks.push({ type: "list", data: listData(node, "checklist") });
        break;
      case "blockquote":
        {
          const kids = node.content.content;
          const caption = kids.find((kid) => kid.type.name === "quoteCaption");
          blocks.push({ type: "quote", data: { text: kids.filter((kid) => kid !== caption).map(inline).join("<br>"), caption: caption ? inline(caption) : "", color: node.attrs.color || "blue" } });
        }
        break;
      case "figure":
        blocks.push({ type: "image", data: node.attrs.data });
        break;
      case "callout":
        blocks.push({ type: "callout", data: { type: node.attrs.type, title: inline(node.child(0)), message: inline(node.child(1)), hideTitle: !!node.attrs.hideTitle } });
        break;
      case "timeline":
        blocks.push({
          type: "timeline",
          data: {
            showDates: !!node.attrs.showDates,
            color: node.attrs.color || "",
            items: node.content.content.map((item) => ({ title: inline(item.child(1)), description: inline(item.child(2)), date: item.child(0).textContent })),
          },
        });
        break;
      case "codeBlock":
        blocks.push({ type: "code", data: { code: node.textContent, language: node.attrs.language || "plaintext" } });
        break;
      case "horizontalRule":
        blocks.push({ type: "delimiter", data: { style: node.attrs.style || "stars" } });
        break;
      case "table": {
        const rows = node.content.content.map((row) => row.content.content.map((cell) => inline(cell.firstChild)));
        blocks.push({ type: "table", data: { withHeadings: node.firstChild.firstChild.type.name === "tableHeader", content: rows } });
        break;
      }
      default:
        break;
    }
  });
  return blocks;
}
