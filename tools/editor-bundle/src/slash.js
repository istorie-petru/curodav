// The slash menu: typing "/" at the start of an empty line lists the blocks that can be added, filtered as you type.
// Arrow keys choose, Enter or Tab adds, Escape closes. The toolbar only edits; adding blocks happens here.
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";

const ITEMS = [
  { label: "Heading 1", hint: "#", words: "title h1", run: (c) => c.setHeading({ level: 1 }) },
  { label: "Heading 2", hint: "##", words: "h2", run: (c) => c.setHeading({ level: 2 }) },
  { label: "Heading 3", hint: "###", words: "h3", run: (c) => c.setHeading({ level: 3 }) },
  { label: "Bulleted list", hint: "-", words: "bullets unordered", run: (c) => c.toggleBulletList() },
  { label: "Numbered list", hint: "1.", words: "ordered", run: (c) => c.toggleOrderedList() },
  { label: "Checklist", hint: "[ ]", words: "tasks todo", run: (c) => c.toggleTaskList() },
  { label: "Quote", hint: ">", words: "blockquote", run: (c) => c.toggleBlockquote() },
  { label: "Callout", hint: "> [!tip]", words: "note tip warning danger important", run: (c) => c.insertContent({ type: "callout", attrs: { type: "note" }, content: [{ type: "calloutTitle" }, { type: "calloutMessage" }] }) },
  { label: "Timeline", hint: "", words: "events dates", run: (c) => c.insertContent({ type: "timeline", content: [{ type: "timelineItem", content: [{ type: "timelineDate" }, { type: "timelineTitle" }, { type: "timelineDescription" }] }] }) },
  { label: "Table", hint: "", words: "grid rows columns", run: (c) => c.insertTable({ rows: 3, cols: 3, withHeaderRow: true }) },
  { label: "Code block", hint: "```", words: "source", run: (c) => c.toggleCodeBlock() },
  { label: "Divider", hint: "---", words: "line rule separator", run: (c) => c.setHorizontalRule() },
  { label: "Figure", hint: "", words: "image picture photo", event: "nb-add-figure" },
  { label: "Endnote", hint: "", words: "footnote note reference", event: "nb-add-endnote" },
  { label: "Link to a note", hint: "[[", words: "wikilink entry mention", insert: "[[" },
];

const key = new PluginKey("slashMenu");

function find(state) {
  const { selection } = state;
  if (!selection.empty) return null;
  const { $from } = selection;
  if ($from.depth !== 1 || $from.parent.type.name !== "paragraph") return null;
  const text = $from.parent.textContent;
  const match = /^\/([^\s/]*)$/.exec(text);
  if (!match || $from.parentOffset !== text.length) return null;
  return { query: match[1].toLowerCase(), from: $from.start(), to: $from.pos };
}

const matches = (query) => ITEMS.filter((item) => !query || `${item.label} ${item.words}`.toLowerCase().includes(query));

export const SlashMenu = Extension.create({
  name: "slashMenu",
  addProseMirrorPlugins() {
    const editor = this.editor;
    let menu = null;

    const close = () => {
      if (menu) menu.remove();
      menu = null;
    };

    const choose = (item, spot) => {
      const chain = editor.chain().focus().deleteRange({ from: spot.from, to: spot.to });
      if (item.insert) {
        chain.run();
        document.execCommand("insertText", false, item.insert);
        return;
      }
      if (item.event) {
        chain.run();
        editor.view.dom.dispatchEvent(new CustomEvent(item.event));
        return;
      }
      item.run(chain).run();
    };

    return [
      new Plugin({
        key,
        state: {
          init: () => ({ spot: null, index: 0, dismissed: null }),
          apply(tr, prev, _old, state) {
            const spot = find(state);
            const meta = tr.getMeta(key);
            let { index, dismissed } = prev;
            if (!spot) return { spot: null, index: 0, dismissed: null };
            if (!prev.spot || prev.spot.query !== spot.query) index = 0;
            if (meta && meta.dismiss) dismissed = spot.from;
            if (meta && meta.move) {
              const count = matches(spot.query).length;
              index = count ? (index + meta.move + count) % count : 0;
            }
            return { spot, index, dismissed };
          },
        },
        props: {
          handleKeyDown(view, event) {
            const data = key.getState(view.state);
            if (!data.spot || data.dismissed === data.spot.from) return false;
            const list = matches(data.spot.query);
            if (!list.length) return false;
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              view.dispatch(view.state.tr.setMeta(key, { move: event.key === "ArrowDown" ? 1 : -1 }));
              return true;
            }
            if (event.key === "Enter" || event.key === "Tab") {
              choose(list[data.index], data.spot);
              return true;
            }
            if (event.key === "Escape") {
              view.dispatch(view.state.tr.setMeta(key, { dismiss: true }));
              return true;
            }
            return false;
          },
        },
        view() {
          return {
            update(view) {
              const data = key.getState(view.state);
              const list = data.spot ? matches(data.spot.query) : [];
              if (!data.spot || data.dismissed === data.spot.from || !list.length) {
                close();
                return;
              }
              if (!menu) {
                menu = document.createElement("div");
                menu.className = "nbslash";
                menu.setAttribute("role", "listbox");
                menu.setAttribute("aria-label", "Add a block");
                document.body.appendChild(menu);
              }
              menu.replaceChildren();
              list.forEach((item, i) => {
                const row = document.createElement("div");
                row.className = "nbslash-item" + (i === data.index ? " is-active" : "");
                row.setAttribute("role", "option");
                row.setAttribute("aria-selected", i === data.index ? "true" : "false");
                const name = document.createElement("span");
                name.textContent = item.label;
                const hint = document.createElement("span");
                hint.className = "nbslash-hint";
                hint.textContent = item.hint;
                row.append(name, hint);
                row.addEventListener("mousedown", (event) => {
                  event.preventDefault();
                  choose(item, data.spot);
                });
                menu.appendChild(row);
              });
              try {
                const at = view.coordsAtPos(data.spot.to);
                menu.style.left = `${Math.max(8, Math.min(at.left, window.innerWidth - 248))}px`;
                const below = at.bottom + 6;
                const flip = below + menu.offsetHeight > window.innerHeight;
                menu.style.top = `${flip ? Math.max(8, at.top - menu.offsetHeight - 6) : below}px`;
              } catch (err) {
                /* no layout (tests) */
              }
              const active = menu.querySelector(".is-active");
              if (active && active.scrollIntoView) active.scrollIntoView({ block: "nearest" });
            },
            destroy: close,
          };
        },
      }),
    ];
  },
});
