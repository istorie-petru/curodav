// Keyboard behaviour that is not specific to one block: lists, headings, code, tables, moving and duplicating blocks.
import { Extension } from "@tiptap/core";
import { TextSelection } from "@tiptap/pm/state";
import { TableMap } from "@tiptap/pm/tables";
import { depthOf, exitAfter } from "./nodes.js";

const LIST_ITEMS = ["listItem", "taskItem"];
const LISTS = ["bulletList", "orderedList", "taskList"];
const EXITABLE = ["blockquote", "callout", "timeline", "table", "codeBlock", ...LISTS];

// The paragraphs a list holds, nested items included, in reading order.
function flatten(list, out = []) {
  list.forEach((item) => {
    item.forEach((child, _offset, index) => {
      if (index === 0) out.push(child);
      else if (LISTS.includes(child.type.name)) flatten(child, out);
    });
  });
  return out;
}

export const ListKeys = Extension.create({
  name: "listKeys",
  priority: 200,
  addCommands() {
    return {
      // Removes the bullets, numbers or checkboxes of the whole list the caret is in; the text stays.
      unwrapList: () => ({ tr, state }) => {
        const { $from } = state.selection;
        const depth = depthOf($from, LISTS);
        if (!depth) return false;
        let top = depth;
        for (let d = depth - 1; d > 0; d--) if (LISTS.includes($from.node(d).type.name)) top = d;
        const list = $from.node(top);
        const paragraphs = flatten(list);
        const from = $from.before(top);
        tr.replaceWith(from, $from.after(top), paragraphs.length ? paragraphs : [state.schema.nodes.paragraph.create()]);
        tr.setSelection(TextSelection.near(tr.doc.resolve(Math.min(from + 1, tr.doc.content.size)), 1));
        return true;
      },
    };
  },
  addKeyboardShortcuts() {
    return {
      // Backspace at the start of an item (empty or not) takes it out of the list, or one level out when nested.
      Backspace: ({ editor }) => {
        const { $from, empty } = editor.state.selection;
        if (!empty || $from.parentOffset !== 0 || $from.depth < 2) return false;
        const item = $from.node($from.depth - 1).type.name;
        if (!LIST_ITEMS.includes(item) || $from.index($from.depth - 1) !== 0) return false;
        return editor.commands.liftListItem(item);
      },
    };
  },
});

function cellAt(state) {
  const { $from } = state.selection;
  const depth = depthOf($from, ["tableCell", "tableHeader"]);
  if (!depth) return null;
  const table = $from.node(depth - 2);
  const tableStart = $from.start(depth - 2);
  const map = TableMap.get(table);
  return { map, tableStart, rect: map.findCell($from.before(depth) - tableStart) };
}

const cellPosition = (editor, row, col) => {
  const cell = cellAt(editor.state);
  if (!cell) return null;
  const map = TableMap.get(editor.state.doc.nodeAt(cell.tableStart - 1));
  return cell.tableStart + map.map[row * map.width + col] + 2;
};

export const BlockKeys = Extension.create({
  name: "blockKeys",
  priority: 150,
  addCommands() {
    return {
      // Sets the alignment of every cell in the column the caret is in.
      alignColumn: (value) => ({ tr, state }) => {
        const cell = cellAt(state);
        if (!cell) return false;
        const { map, tableStart, rect } = cell;
        for (let row = 0; row < map.height; row++) {
          const pos = tableStart + map.map[row * map.width + rect.left];
          tr.setNodeMarkup(pos, null, { ...tr.doc.nodeAt(pos).attrs, align: value || null });
        }
        return true;
      },
    };
  },
  addKeyboardShortcuts() {
    return {
      // Ctrl+Enter leaves the block the caret is in (quote, callout, timeline, table, code, list).
      "Mod-Enter": ({ editor }) => {
        const { $from } = editor.state.selection;
        if ($from.depth < 1 || !EXITABLE.includes($from.node(1).type.name)) return false;
        return exitAfter(editor, 1);
      },
      // Enter in a table cell goes to the cell below, adding a row at the end.
      Enter: ({ editor }) => {
        const cell = cellAt(editor.state);
        if (!cell) return false;
        const { rect, map } = cell;
        if (rect.bottom >= map.height) editor.commands.addRowAfter();
        const pos = cellPosition(editor, rect.bottom, rect.left);
        return pos ? editor.commands.setTextSelection(pos) : true;
      },
      // Tab indents inside code; Shift+Tab takes the indent back.
      Tab: ({ editor }) => (editor.isActive("codeBlock") ? editor.commands.insertContent("  ") : false),
      "Shift-Tab": ({ editor }) => {
        if (!editor.isActive("codeBlock")) return false;
        const { $from } = editor.state.selection;
        const text = $from.parent.textContent;
        const lineStart = text.lastIndexOf("\n", $from.parentOffset - 1) + 1;
        const lead = /^ {1,2}/.exec(text.slice(lineStart));
        if (!lead) return true;
        const from = $from.start() + lineStart;
        return editor.commands.command(({ tr }) => {
          tr.delete(from, from + lead[0].length);
          return true;
        });
      },
      // A heading becomes a paragraph before Backspace merges it into the block above.
      Backspace: ({ editor }) => {
        const { $from, empty } = editor.state.selection;
        if (!empty || $from.parentOffset !== 0 || $from.parent.type.name !== "heading") return false;
        return editor.commands.setNode("paragraph");
      },
      // Ctrl+A selects the text of the current block first, the whole note on the second press.
      "Mod-a": ({ editor }) => {
        const { $from, from, to } = editor.state.selection;
        if (!$from.parent.isTextblock) return false;
        const start = $from.start();
        const end = $from.end();
        if (from <= start && to >= end) return false;
        return editor.commands.setTextSelection({ from: start, to: end });
      },
      "Mod-Shift-h": ({ editor }) => editor.chain().toggleMark("textColor", { class: "nb-hl-yellow" }).run(),
      "Mod-k": ({ editor }) => {
        editor.view.dom.dispatchEvent(new CustomEvent("nb-open-link"));
        return true;
      },
      "Alt-ArrowUp": ({ editor }) => moveBlock(editor, -1),
      "Alt-ArrowDown": ({ editor }) => moveBlock(editor, 1),
      "Mod-d": ({ editor }) => {
        const { $from } = editor.state.selection;
        if ($from.depth < 1) return false;
        const node = $from.node(1);
        const end = $from.after(1);
        return editor.commands.command(({ tr }) => {
          tr.insert(end, node.copy(node.content));
          tr.setSelection(TextSelection.near(tr.doc.resolve(end + 1), 1));
          return true;
        });
      },
    };
  },
});

function moveBlock(editor, direction) {
  const { $from } = editor.state.selection;
  if ($from.depth < 1) return false;
  const index = $from.index(0);
  const doc = editor.state.doc;
  const target = index + direction;
  if (target < 0 || target >= doc.childCount) return true;
  const from = $from.before(1);
  const node = doc.child(index);
  const caret = $from.pos - from;
  return editor.commands.command(({ tr }) => {
    tr.delete(from, from + node.nodeSize);
    const at = direction < 0 ? from - doc.child(target).nodeSize : from + doc.child(target).nodeSize;
    tr.insert(at, node);
    tr.setSelection(TextSelection.near(tr.doc.resolve(at + caret), 1));
    return true;
  });
}

export const KeyExtensions = [ListKeys, BlockKeys];
