// Controls drawn on the table itself while the caret is in it: a grip above each column and beside each row (click to
// select it), and plus buttons at the right and bottom edges that add a column or a row.
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { CellSelection, TableMap } from "@tiptap/pm/tables";

function button(className, label, onPress) {
  const el = document.createElement("button");
  el.type = "button";
  el.className = className;
  el.contentEditable = "false";
  el.setAttribute("aria-label", label);
  el.title = label;
  el.addEventListener("mousedown", (event) => {
    event.preventDefault();
    onPress();
  });
  return el;
}

export const TableControls = Extension.create({
  name: "tableControls",
  addProseMirrorPlugins() {
    const editor = this.editor;
    const select = (kind, cellPos) => {
      const { state, view } = editor;
      const $cell = state.doc.resolve(cellPos);
      view.dispatch(state.tr.setSelection(kind === "col" ? CellSelection.colSelection($cell) : CellSelection.rowSelection($cell)));
      view.focus();
    };
    return [
      new Plugin({
        key: new PluginKey("tableControls"),
        props: {
          decorations(state) {
            if (!editor.isEditable) return null;
            const { $from } = state.selection;
            let depth = $from.depth;
            while (depth > 0 && $from.node(depth).type.name !== "table") depth--;
            if (!depth) return null;
            const table = $from.node(depth);
            const start = $from.start(depth);
            const map = TableMap.get(table);
            const widgets = [];
            const at = (row, col) => start + map.map[row * map.width + col];
            for (let col = 0; col < map.width; col++) {
              const pos = at(0, col);
              widgets.push(Decoration.widget(pos + 1, () => button("nbtc-grip nbtc-col", "Select column", () => select("col", pos)), { side: -1, key: `c${col}-${pos}`, ignoreSelection: true }));
            }
            for (let row = 0; row < map.height; row++) {
              const pos = at(row, 0);
              widgets.push(Decoration.widget(pos + 1, () => button("nbtc-grip nbtc-row", "Select row", () => select("row", pos)), { side: -1, key: `r${row}-${pos}`, ignoreSelection: true }));
            }
            const lastCol = at(0, map.width - 1);
            widgets.push(
              Decoration.widget(lastCol + 1, () => button("nbtc-add nbtc-add-col", "Add column", () => {
                select("col", lastCol);
                editor.commands.addColumnAfter();
              }), { side: -1, key: `ac${lastCol}`, ignoreSelection: true })
            );
            const lastRow = at(map.height - 1, 0);
            widgets.push(
              Decoration.widget(lastRow + 1, () => button("nbtc-add nbtc-add-row", "Add row", () => {
                select("row", lastRow);
                editor.commands.addRowAfter();
              }), { side: -1, key: `ar${lastRow}`, ignoreSelection: true })
            );
            return DecorationSet.create(state.doc, widgets);
          },
        },
      }),
    ];
  },
});
