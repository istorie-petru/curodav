// Notebook Editor mode mount (curodav-notes/documentation/plans/
// architecture-notes-module-2026-09-29.md §3) -- initializes Editor.js on
// #notebook-editor, loads content_json via GET .../content, autosaves via
// PUT .../content (the one JSON-in/out exception documented in
// routers/notebook.py). Tools: Editor.js's own header/list/table/
// image(simple-image)/inline-code (vendored UMD bundles), Quote/Callout/
// Delimiter/Code from first-party notebook_blocks.js and notebook_code.js
// (2026-10-03 reworks, replacing @editorjs/quote, @editorjs/warning,
// @editorjs/delimiter, and @editorjs/code outright -- see vendor/
// NOTICE.md for why each), Footnote (an inline tool, not a block) from
// first-party notebook_footnotes.js plus FootnoteInsert (a block tool,
// the "/" slash-menu entry point for the footnote action menu -- item J,
// session 9a, 2026-10-03), WikiLink (also inline) from first-party
// notebook_wikilinks.js (2026-10-03, roadmap's "Wikilinks &
// relationships" section), plus editorjs-drag-drop and editorjs-undo
// (vendored as dragdrop.umd.js/undo.umd.js) wired up after the editor is
// ready below. notebook_toc.js's Outline sidebar and notebook_wikilinks.js's
// own Relationships "Links to" list (2026-10-03) both hook in the same way
// footnotes does -- re-rendered on ready and on every onChange below.
(function () {
  var mount = document.getElementById("notebook-editor");
  if (!mount || !window.EditorJS) return;

  var status = document.getElementById("notebook-save-status");
  var contentUrl = mount.getAttribute("data-content-url");
  var saveTimer = null;

  function setStatus(state, text) {
    if (!status) return;
    status.setAttribute("data-state", state);
    status.textContent = text;
  }

  function save(editor) {
    editor
      .save()
      .then(function (data) {
        setStatus("saving", "Saving...");
        return fetch(contentUrl, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });
      })
      .then(function (resp) {
        if (!resp.ok) throw new Error("save failed");
        setStatus("saved", "Saved");
      })
      .catch(function () {
        setStatus("error", "Could not save");
      });
  }

  function scheduleSave(editor) {
    setStatus("pending", "Unsaved changes...");
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      save(editor);
    }, 1500);
  }

  // Markdown-style fast-writing shortcuts (direct request: "a lot of the
  // markdown writing conventions should be used for fast writing"). Not
  // Editor.js's `conversionConfig` mechanism -- that requires every
  // source/target tool pair to declare matching import/export hooks, a lot
  // of plumbing across first-party and vendored tools alike for what's
  // really just "replace this empty paragraph with that other block type."
  // Instead: a keydown listener on the whole mount (delegation, since
  // blocks are created/destroyed as the user edits) that only fires when
  // the current block's entire text content is *exactly* one of the
  // trigger patterns below with the caret at its very end -- e.g. a block
  // containing only "#" followed by pressing Space. That guard is what
  // keeps "it's a #1 priority" or "a - b" from mis-firing mid-sentence.
  // A plain node-type check on range.startContainer isn't enough here --
  // a collapsed caret's startContainer is sometimes the editable element
  // itself (offset = child count, not a character count) rather than a
  // text node (offset = character count), depending on how the selection
  // got there. `Range.compareBoundaryPoints` looks like the fix (compare
  // against a range collapsed to the editable's own true end) but doesn't
  // actually treat a text-node end point and its parent's equivalent
  // offset as equal here -- confirmed live, (textNode, textNode.length)
  // consistently compares as *before* (parentNode, indexOfTextNode + 1)
  // even though they're the same position. Walking up from the caret
  // instead -- true iff nothing (no sibling, at any level) follows it on
  // the way up to `editable` -- sidesteps that mismatch completely since
  // it never compares across the two point shapes at all.
  function isCaretAtEnd(editable, range) {
    var container = range.endContainer;
    var offset = range.endOffset;
    if (container.nodeType === Node.TEXT_NODE) {
      if (offset !== container.textContent.length) return false;
    } else if (offset !== container.childNodes.length) {
      return false;
    }
    while (container && container !== editable) {
      if (container.nextSibling) return false;
      container = container.parentNode;
    }
    return container === editable;
  }

  function replaceBlock(editor, index, type, data) {
    editor.blocks.insert(type, data, {}, index, true);
    editor.blocks.delete(index + 1);
  }

  function wireMarkdownShortcuts(editor, mount) {
    mount.addEventListener("keydown", function (e) {
      if (e.key !== " " && e.key !== "Enter") return;
      var sel = window.getSelection();
      if (!sel.rangeCount) return;
      var range = sel.getRangeAt(0);
      if (!range.collapsed) return;
      var node = range.startContainer;
      var el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
      var editable = el && el.closest("[contenteditable=true]");
      if (!editable || !isCaretAtEnd(editable, range)) return;

      // Deriving the index from the actual element the caret is in (not
      // `editor.blocks.getCurrentBlockIndex()`) -- that index is only set
      // by Editor.js's own click/focus bookkeeping, which lags behind a
      // caret that got there some other way (e.g. arrow-key navigation
      // right after a block was just inserted), so it can point at the
      // wrong block or report -1 with no block "current" yet at all.
      var block = editor.blocks.getBlockByElement(editable);
      if (!block || block.name !== "paragraph") return;
      var index = editor.blocks.getBlockIndex(block.id);
      var text = editable.textContent;

      if (e.key === " ") {
        var headerMatch = /^(#{1,5})$/.exec(text);
        if (headerMatch) {
          e.preventDefault();
          replaceBlock(editor, index, "header", { text: "", level: headerMatch[1].length });
          return;
        }
        if (text === "-" || text === "*") {
          e.preventDefault();
          replaceBlock(editor, index, "list", {
            style: "unordered",
            items: [{ content: "", meta: {}, items: [] }],
          });
          return;
        }
        if (/^\d+\.$/.test(text)) {
          e.preventDefault();
          replaceBlock(editor, index, "list", {
            style: "ordered",
            items: [{ content: "", meta: {}, items: [] }],
          });
          return;
        }
        if (text === ">") {
          e.preventDefault();
          replaceBlock(editor, index, "quote", { text: "", caption: "", color: "blue" });
          return;
        }
      } else if (e.key === "Enter") {
        if (text === "```") {
          e.preventDefault();
          replaceBlock(editor, index, "code", { code: "", language: "plaintext" });
          return;
        }
        if (text === "---" || text === "***") {
          e.preventDefault();
          replaceBlock(editor, index, "delimiter", { style: "stars" });
          return;
        }
      }
    });
  }

  fetch(contentUrl, { headers: { Accept: "application/json" } })
    .then(function (resp) {
      if (!resp.ok) throw new Error("load failed");
      return resp.json();
    })
    .catch(function () {
      return { blocks: [] };
    })
    .then(function (initialData) {
      var editor = new window.EditorJS({
        holder: mount,
        data: initialData,
        // 2026-10-04 direct request: "on new notes, there should be some
        // default text" -- Editor.js's own top-level `placeholder` option
        // (not saved content, no server/content_json change needed) shows
        // this as grayed-out hint text on the first block while the whole
        // document is still empty, exactly the built-in behavior the
        // vendored bundle already had the CSS for (editorjs.css's
        // `[data-placeholder-active]:focus:before{content:attr(data-
        // placeholder-active)}`) but nothing had ever set this option to
        // turn it on. Confirmed live that attribute is only ever read on
        // `:focus` (not just `:empty`), so `autofocus` is paired with it
        // below -- without it, a brand-new document's placeholder would
        // only appear after the user's first click into the body, which
        // isn't "there should be default text" (visible immediately).
        placeholder: "Start writing...",
        autofocus: true,
        tools: {
          header: {
            class: window.Header,
            config: { levels: [1, 2, 3, 4, 5], defaultLevel: 2 },
          },
          list: { class: window.EditorjsList, inlineToolbar: true },
          quote: { class: window.NotebookQuote, inlineToolbar: true },
          code: window.NotebookCode,
          table: { class: window.Table, inlineToolbar: true },
          delimiter: window.NotebookDelimiter,
          callout: { class: window.NotebookCallout, inlineToolbar: true },
          image: { class: window.SimpleImage, inlineToolbar: true },
          inlineCode: window.InlineCode,
          footnote: window.NotebookFootnote,
          footnoteInsert: window.NotebookFootnoteBlock,
          wikilink: window.NotebookWikiLink,
          wikilinkInsert: window.NotebookWikilinkBlock,
        },
        onChange: function () {
          if (window.notebookRenderFootnoteList) {
            window.notebookRenderFootnoteList(mount);
          }
          if (window.notebookRenderToc) {
            window.notebookRenderToc(mount);
          }
          if (window.notebookRenderRelationships) {
            window.notebookRenderRelationships(mount);
          }
          scheduleSave(editor);
        },
      });
      wireMarkdownShortcuts(editor, mount);
      mount.addEventListener(
        "blur",
        function () {
          if (saveTimer) {
            clearTimeout(saveTimer);
            saveTimer = null;
            save(editor);
          }
        },
        true
      );
      if (window.DragDrop) {
        editor.isReady.then(function () {
          new window.DragDrop(editor);
        });
      }
      if (window.Undo) {
        editor.isReady.then(function () {
          new window.Undo({ editor: editor });
        });
      }
      if (window.notebookRenderFootnoteList) {
        editor.isReady.then(function () {
          window.notebookRenderFootnoteList(mount);
        });
      }
      if (window.notebookRenderToc) {
        editor.isReady.then(function () {
          window.notebookRenderToc(mount);
        });
      }
      if (window.notebookRenderRelationships) {
        editor.isReady.then(function () {
          window.notebookRenderRelationships(mount);
        });
      }
      // Table row/column popover can render partly below the visible
      // scroll area (2026-10-03, direct report -- "the delete row button
      // for the last row ... only the top of the button is clickable").
      // @editorjs/table's own mini-popover (table.css's .tc-popover,
      // opened from .tc-toolbox__toggler) has no viewport/scroll-
      // boundary awareness at all -- for a table near the bottom of
      // #notebook-editor's own scrollable area, the popover just extends
      // past it uncorrected, so "Delete row" et al. are only partially
      // inside the clickable scrolled viewport. Not patching the tool's
      // internals (minified, private, see table.umd.js) -- a plain
      // `scrollIntoView` after it opens is a public, standard browser API
      // that nudges the editor's own scroll just enough to bring the
      // whole popover into view, a no-op if it's already fully visible.
      // Targets the LAST item specifically, not the popover container --
      // scrolling the container into view still left the last item's own
      // few px of padding poking out past the edge (confirmed live: ~6px
      // of "Delete row" still clipped), since the container's own bottom
      // padding sits below it.
      mount.addEventListener(
        "click",
        function (e) {
          var toggler = e.target.closest(".tc-toolbox__toggler");
          if (!toggler) return;
          requestAnimationFrame(function () {
            var toolbox = toggler.closest(".tc-toolbox");
            var popover =
              toolbox && toolbox.querySelector(".tc-popover--opened");
            if (!popover) return;
            var items = popover.querySelectorAll(".tc-popover__item");
            var target = items.length
              ? items[items.length - 1]
              : popover;
            target.scrollIntoView({ block: "nearest" });
          });
        },
        true
      );
    });
})();
