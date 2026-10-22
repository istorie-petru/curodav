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
import { Markdown } from "./markdown.js";
import { CodeHighlight } from "./highlight.js";
import { HeadingNumbers } from "./headings.js";
import { mergeAttributes } from "@tiptap/core";

function extensions() {
  return [
    StarterKit.configure({ heading: { levels: [1, 2, 3, 4, 5] }, blockquote: false, horizontalRule: false }),
    ...BlockExtensions,
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
    Table,
    TableRow,
    TableHeader.extend({ content: "paragraph" }),
    TableCell.extend({ content: "paragraph" }),
    Placeholder.configure({
      placeholder: ({ node }) =>
        ({ paragraph: "Start writing...", calloutTitle: "Title (optional)", calloutMessage: "Callout text", quoteCaption: "Source", timelineDate: "Date", timelineTitle: "Title", timelineDescription: "Description" })[node.type.name] || "",
    }),
  ];
}

// `blocks` is the stored Editor.js block list; `onChange` gets the new block list after each edit.
function create(mount, blocks, onChange) {
  const readOnly = lossy(blocks);
  const editor = new Editor({
    element: mount,
    injectCSS: false,
    extensions: extensions(),
    content: blocksToHtml(blocks),
    editable: !readOnly,
    onUpdate: ({ editor: e }) => onChange(docToBlocks(e.state.doc, e.schema)),
  });
  return { editor, readOnly, blocks: () => docToBlocks(editor.state.doc, editor.schema) };
}

window.CurodavEditor = { create, blocksToHtml, docToBlocks, lossy, extensions };
export { create, blocksToHtml, docToBlocks, lossy, unsupportedBlocks, extensions };
