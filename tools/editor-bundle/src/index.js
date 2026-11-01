import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import Link from "@tiptap/extension-link";
import Underline from "@tiptap/extension-underline";
import Subscript from "@tiptap/extension-subscript";
import Superscript from "@tiptap/extension-superscript";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import Placeholder from "@tiptap/extension-placeholder";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableHeader from "@tiptap/extension-table-header";
import TableCell from "@tiptap/extension-table-cell";
import { blocksToHtml, docToBlocks, lossy, unsupportedBlocks } from "./convert.js";
import { BlockExtensions } from "./nodes.js";
import { KeyExtensions } from "./keys.js";
import { TableControls } from "./tablecontrols.js";
import { SlashMenu } from "./slash.js";
import { Markdown } from "./markdown.js";
import { CodeHighlight } from "./highlight.js";
import { HeadingNumbers } from "./headings.js";
import { mergeAttributes } from "@tiptap/core";

const ALIGN = {
  default: null,
  parseHTML: (el) => el.getAttribute("data-align"),
  renderHTML: (attrs) => (attrs.align ? { "data-align": attrs.align } : {}),
};

function extensions() {
  return [
    StarterKit.configure({ heading: { levels: [1, 2, 3, 4, 5] }, blockquote: false, horizontalRule: false }),
    ...BlockExtensions,
    ...KeyExtensions,
    TableControls,
    SlashMenu,
    Markdown,
    CodeHighlight,
    HeadingNumbers,
    Underline,
    Subscript,
    Superscript,
    Link.extend({
      renderHTML({ HTMLAttributes }) {
        const title = HTMLAttributes.href ? `${HTMLAttributes.href} (Ctrl+click to open)` : null;
        return ["a", mergeAttributes(HTMLAttributes, { title }), 0];
      },
    }).configure({ openOnClick: false, HTMLAttributes: { target: null, rel: null } }),
    TaskList,
    TaskItem.configure({ nested: true }),
    Table.configure({ resizable: true, cellMinWidth: 60, lastColumnResizable: false }),
    TableRow,
    TableHeader.extend({ content: "paragraph", addAttributes() { return { ...this.parent?.(), align: ALIGN }; } }),
    TableCell.extend({ content: "paragraph", addAttributes() { return { ...this.parent?.(), align: ALIGN }; } }),
    // Empty fields of the custom blocks always show their hint; a plain paragraph only does while the caret is in it.
    Placeholder.configure({
      showOnlyCurrent: false,
      includeChildren: true,
      placeholder: ({ node, hasAnchor }) =>
        ({ paragraph: hasAnchor ? "Start writing..." : "", calloutTitle: "Title (optional)", calloutMessage: "Callout text", quoteCaption: "Source", timelineDate: "Date", timelineTitle: "Title", timelineDescription: "Description" })[node.type.name] || "",
    }),
  ];
}

// `blocks` is the stored Editor.js block list; `onChange` is called after each edit and the caller reads `blocks()` when it
// needs them (converting the whole note on every keystroke made long notes slow).
function create(mount, blocks, onChange) {
  const readOnly = lossy(blocks);
  const editor = new Editor({
    element: mount,
    injectCSS: false,
    extensions: extensions(),
    content: blocksToHtml(blocks),
    editable: !readOnly,
    onUpdate: () => onChange(),
  });
  return { editor, readOnly, reasons: readOnly ? unsupportedBlocks(blocks) : [], blocks: () => docToBlocks(editor.state.doc, editor.schema) };
}

window.CurodavEditor = { create, blocksToHtml, docToBlocks, lossy, extensions };
export { create, blocksToHtml, docToBlocks, lossy, unsupportedBlocks, extensions };
