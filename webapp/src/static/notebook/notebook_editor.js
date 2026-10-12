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

  var contentUrl = mount.getAttribute("data-content-url");
  var saveTimer = null;
  var failedSaves = 0;

  // No save-status text: a failed save raises one error toast (and again
  // only after a later save succeeds and fails anew), so a normal save is
  // silent.
  function save(editor) {
    editor
      .save()
      .then(function (data) {
        return fetch(contentUrl, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });
      })
      .then(function (resp) {
        if (!resp.ok) throw new Error("save failed");
        failedSaves = 0;
      })
      .catch(function () {
        if (failedSaves++ === 0) {
          window.ccToast({ message: "Could not save this document. Your last changes are not stored yet.", variant: "error" });
        }
      });
  }

  function scheduleSave(editor) {
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

  // Typing the closing marker of **bold**, *italic*, _italic_, ~~strike~~ or `code` turns the
  // span into formatted text right away, so markdown works as the way of writing.
  var INLINE_RULES = [
    { re: /(^|[^*])\*\*([^*\s](?:[^*]*[^*\s])?)\*\*$/, tag: "b" },
    { re: /(^|[^~])~~([^~\s](?:[^~]*[^~\s])?)~~$/, tag: "s" },
    { re: /(^|[^`])`([^`]+)`$/, tag: "code" },
    { re: /(^|[^*\w])\*([^*\s](?:[^*]*[^*\s])?)\*$/, tag: "i" },
    { re: /(^|[^_\w])_([^_\s](?:[^_]*[^_\s])?)_$/, tag: "i" },
  ];

  function wireInlineMarkdown(editor, mount) {
    mount.addEventListener("input", function (e) {
      var sel = window.getSelection();
      var anchor = sel.rangeCount && sel.anchorNode;
      // The zero-width anchor left after a conversion goes as soon as real text follows it.
      if (anchor && anchor.nodeType === Node.TEXT_NODE && anchor.textContent.length > 1 && anchor.textContent.indexOf("\u200b") !== -1) {
        var off = sel.anchorOffset - (anchor.textContent.slice(0, sel.anchorOffset).split("\u200b").length - 1);
        anchor.textContent = anchor.textContent.replace(/\u200b/g, "");
        var fix = document.createRange();
        fix.setStart(anchor, Math.max(0, off));
        fix.collapse(true);
        sel.removeAllRanges();
        sel.addRange(fix);
      }
      if (e.inputType !== "insertText" || !e.data || "*_~`".indexOf(e.data) === -1) return;
      if (!sel.rangeCount || !sel.isCollapsed) return;
      var node = sel.anchorNode;
      if (!node || node.nodeType !== Node.TEXT_NODE) return;
      var parent = node.parentElement;
      if (!parent || parent.closest("code, pre, .cdx-code, .cdx-wikilink, .cdx-footnote-list, .cdx-footnote-input, .nbt")) return;
      if (!parent.closest(".ce-block")) return;
      var before = node.textContent.slice(0, sel.anchorOffset);
      for (var i = 0; i < INLINE_RULES.length; i++) {
        var m = INLINE_RULES[i].re.exec(before);
        if (!m) continue;
        var undo = window.notebookUndo;
        if (undo) undo.checkpoint();
        var start = before.length - m[0].length + m[1].length;
        var range = document.createRange();
        range.setStart(node, start);
        range.setEnd(node, before.length);
        range.deleteContents();
        var el = document.createElement(INLINE_RULES[i].tag);
        if (INLINE_RULES[i].tag === "code") el.className = "inline-code";
        el.textContent = m[2];
        range.insertNode(el);
        var tail = document.createTextNode("\u200b");
        el.after(tail);
        var caret = document.createRange();
        caret.setStart(tail, 1);
        caret.collapse(true);
        sel.removeAllRanges();
        sel.addRange(caret);
        mount.dispatchEvent(new Event("input", { bubbles: true }));
        if (undo) setTimeout(function () { undo.checkpoint(); }, 80);
        return;
      }
    });
  }

  // Pasting markdown text (no rich HTML on the clipboard) into a paragraph
  // turns it into real blocks; a single line with inline markers is
  // inserted as formatted text instead.
  function wireMarkdownPaste(editor, mount) {
    mount.addEventListener(
      "paste",
      function (e) {
        var md = window.NotebookMarkdown;
        var data = e.clipboardData;
        if (!md || !data || Array.prototype.indexOf.call(data.types, "text/html") !== -1) return;
        var text = data.getData("text/plain");
        if (!text || !md.looksLikeMarkdown(text)) return;
        var editable = e.target.closest && e.target.closest("[contenteditable=true]");
        var block = editable && editor.blocks.getBlockByElement(editable);
        if (!block || block.name !== "paragraph") return;
        var blocks = md.toBlocks(text);
        if (!blocks.length) return;
        e.preventDefault();
        e.stopPropagation();
        if (blocks.length === 1 && blocks[0].type === "paragraph") {
          document.execCommand("insertHTML", false, blocks[0].data.text);
          return;
        }
        var index = editor.blocks.getBlockIndex(block.id);
        var replaceEmpty = editable.textContent.trim() === "";
        var at = replaceEmpty ? index : index + 1;
        blocks.forEach(function (b, n) {
          editor.blocks.insert(b.type, b.data, {}, at + n, n === blocks.length - 1);
        });
        if (replaceEmpty) editor.blocks.delete(at + blocks.length);
      },
      true
    );
  }

  // Each toolbar action, and each word or line typed, closes the previous
  // history step before it and records its own right after, so one action is
  // one undo step instead of merging with what was typed beside it.
  function wireUndoCheckpoints(mount, undo) {
    function around() {
      undo.checkpoint();
      setTimeout(function () {
        undo.checkpoint();
      }, 80);
    }
    document.addEventListener(
      "click",
      function (e) {
        if (e.target.closest && e.target.closest(".ce-inline-toolbar, .ce-popover, .ce-toolbar, .cdx-settings-button, .cdx-mention-popup")) around();
      },
      true
    );
    mount.addEventListener(
      "keydown",
      function (e) {
        if (e.key === " " || e.key === "Enter") undo.checkpoint();
      },
      true
    );
    mount.addEventListener("paste", around, true);
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
        tunes: ["align", "blockColor", "duplicate"],
        autofocus: true,
        tools: {
          header: {
            class: window.Header,
            config: { levels: [1, 2, 3, 4, 5], defaultLevel: 2 },
          },
          list: { class: window.EditorjsList, inlineToolbar: true },
          quote: { class: window.NotebookQuote, inlineToolbar: true },
          code: window.NotebookCode,
          table: { class: window.NotebookTable, inlineToolbar: true },
          delimiter: window.NotebookDelimiter,
          callout: { class: window.NotebookCallout, inlineToolbar: true },
          image: { class: window.SimpleImage, inlineToolbar: true },
          inlineCode: window.NotebookInlineCode,
          strike: window.NotebookStrike,
          color: window.NotebookColor,
          more: window.NotebookMore,
          clearFormat: window.NotebookClearFormat,
          mention: window.NotebookMention,
          align: window.NotebookAlignTune,
          blockColor: window.NotebookBlockColor,
          duplicate: window.NotebookDuplicate,
          footnote: window.NotebookFootnote,
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
      window.notebookEditor = editor;
      if (window.notebookWireMentions) window.notebookWireMentions(mount);
      if (window.notebookWireBlockDrag) window.notebookWireBlockDrag(mount);
      wireMarkdownShortcuts(editor, mount);
      wireInlineMarkdown(editor, mount);
      wireMarkdownPaste(editor, mount);
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
      if (window.NotebookUndo) {
        editor.isReady.then(function () {
          var undo = new window.NotebookUndo({ editor: editor, mount: mount, uid: mount.getAttribute("data-uid") });
          window.notebookUndo = undo;
          undo.start();
          wireUndoCheckpoints(mount, undo);
          window.addEventListener("pagehide", function () {
            undo.persist();
          });
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
    });
})();
