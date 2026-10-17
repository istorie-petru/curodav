(function () {
  var mount = document.getElementById("notebook-editor");
  if (!mount || !window.EditorJS) return;

  var contentUrl = mount.getAttribute("data-content-url");
  var saveTimer = null;
  var failedSaves = 0;

  // No save-status text: a failed save raises one error toast (and again
  // only after a later save succeeds and fails anew), so a normal save is
  // silent.
  // The last blocks that reached the server (as JSON), so a save with nothing new in it sends nothing.
  var lastSaved = null;
  var KEEPALIVE_LIMIT = 60000;

  function save(editor, leaving) {
    return editor
      .save()
      .then(function (data) {
        var blocks = JSON.stringify(data.blocks);
        if (blocks === lastSaved) return null;
        var body = JSON.stringify(data);
        return fetch(contentUrl, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: body,
          // A request started while the page is going away survives it only with keepalive, which has a size limit.
          keepalive: !!leaving && body.length < KEEPALIVE_LIMIT,
        }).then(function (resp) {
          if (!resp.ok) throw new Error("save failed");
          lastSaved = blocks;
          failedSaves = 0;
          document.dispatchEvent(new CustomEvent("notebook-saved"));
        });
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

  function replaceBlock(editor, index, type, data) {
    editor.blocks.insert(type, data, {}, index, true);
    editor.blocks.delete(index + 1);
  }

  // The text before the caret in a block, and the HTML after it.
  function splitAtCaret(editable, range) {
    var head = document.createRange();
    head.selectNodeContents(editable);
    head.setEnd(range.startContainer, range.startOffset);
    var tail = document.createRange();
    tail.selectNodeContents(editable);
    tail.setStart(range.startContainer, range.startOffset);
    var holder = document.createElement("div");
    holder.appendChild(tail.cloneContents());
    return { before: head.toString(), rest: holder.innerHTML, restText: holder.textContent };
  }

  var SKIP = "code, pre, .cdx-code, .cdx-wikilink, .cdx-footnote-list, .cdx-footnote-input, .nbt";

  // Block markers typed at the start of a block: `# `, `- `, `1. `, `> `, `[ ] ` and Enter after ``` or ---.
  // They work on text that is already written, and keep the text that follows the caret.
  function wireMarkdownShortcuts(editor, mount) {
    var T = window.NotebookTyping;
    mount.addEventListener("keydown", function (e) {
      var sel = window.getSelection();
      if (!sel.rangeCount || !sel.getRangeAt(0).collapsed) return;
      var range = sel.getRangeAt(0);
      var node = range.startContainer;
      var el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
      var editable = el && el.closest("[contenteditable=true]");
      if (!editable || editable.closest(".nbt")) return;
      var block = editor.blocks.getBlockByElement(editable);
      if (!block) return;
      var index = editor.blocks.getBlockIndex(block.id);
      var split = splitAtCaret(editable, range);
      var key = e.key === " " ? "Space" : e.key;

      // Backspace at the start of a heading turns it back into a paragraph instead of merging it away.
      if (key === "Backspace" && block.name === "header" && split.before === "" && split.restText.trim()) {
        e.preventDefault();
        replaceBlock(editor, index, "paragraph", { text: split.rest });
        return;
      }
      if (key !== "Space" && key !== "Enter") return;
      if (block.name === "header" && key === "Space") {
        var level = T.headingLevelMarker(split.before);
        if (level) {
          e.preventDefault();
          replaceBlock(editor, index, "header", { text: split.rest, level: level });
        }
        return;
      }
      if (block.name !== "paragraph") return;
      var marker = T.blockMarker(split.before, key, split.restText);
      if (!marker) return;
      e.preventDefault();
      if (marker.type === "header") replaceBlock(editor, index, "header", { text: split.rest, level: marker.level });
      else if (marker.type === "list") {
        var item = { content: split.rest, meta: marker.style === "checklist" ? { checked: marker.checked } : {}, items: [] };
        replaceBlock(editor, index, "list", { style: marker.style, items: [item] });
      } else if (marker.type === "quote") replaceBlock(editor, index, "quote", { text: split.rest, caption: "", color: "blue" });
      else if (marker.type === "code") replaceBlock(editor, index, "code", { code: "", language: "plaintext" });
      else if (marker.type === "delimiter") replaceBlock(editor, index, "delimiter", { style: "stars" });
    });
  }

  // The caret leaves the block holding `from` for the editable text of the next (or previous) block. It reads the
  // blocks from the page, because Editor.js's own "current block" can lag behind where the caret really is.
  window.notebookMoveToBlock = function (from, down) {
    var block = from.closest(".ce-block");
    var sibling = block && (down ? block.nextElementSibling : block.previousElementSibling);
    while (sibling) {
      var fields = sibling.querySelectorAll("[contenteditable=true]");
      var target = fields.length ? fields[down ? 0 : fields.length - 1] : null;
      if (target) {
        // Going through Editor.js keeps its own idea of the current block right, so its arrow keys keep working.
        var api = window.notebookEditor;
        var found = api && api.blocks.getBlockByElement(target);
        if (found && api.caret.setToBlock(api.blocks.getBlockIndex(found.id), down ? "start" : "end", 0)) return true;
        target.focus();
        var range = document.createRange();
        range.selectNodeContents(target);
        range.collapse(down);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        return true;
      }
      sibling = down ? sibling.nextElementSibling : sibling.previousElementSibling;
    }
    return false;
  };

  // Arrow keys in lists: Down at the end of an item goes to the next item, and from the last item to the next
  // block; Up at the start of an item goes to the previous item, and from the first item to the previous block.
  function wireListArrows(editor, mount) {
    mount.addEventListener(
      "keydown",
      function (e) {
        if ((e.key !== "ArrowDown" && e.key !== "ArrowUp") || e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) return;
        var item = e.target.closest && e.target.closest(".cdx-list__item-content");
        var sel = window.getSelection();
        if (!item || !sel.rangeCount || !sel.getRangeAt(0).collapsed) return;
        var split = splitAtCaret(item, sel.getRangeAt(0));
        var down = e.key === "ArrowDown";
        if (down ? split.restText !== "" : split.before !== "") return;
        var block = item.closest(".ce-block");
        var items = Array.prototype.slice.call(block.querySelectorAll(".cdx-list__item-content"));
        var next = items[items.indexOf(item) + (down ? 1 : -1)];
        e.preventDefault();
        e.stopPropagation();
        if (next) {
          next.focus();
          var range = document.createRange();
          range.selectNodeContents(next);
          range.collapse(down);
          sel.removeAllRanges();
          sel.addRange(range);
        } else window.notebookMoveToBlock(item, down);
      },
      true
    );
  }

  function insideSkipped(node) {
    var parent = node && (node.nodeType === Node.TEXT_NODE ? node.parentElement : node);
    return !parent || parent.closest(SKIP) || !parent.closest(".ce-block");
  }

  function checkpoint(undo) {
    if (undo) undo.checkpoint();
  }

  function elementFor(tags, href) {
    var inner = null;
    var outer = null;
    tags.forEach(function (tag) {
      var el = document.createElement(tag);
      if (tag === "code") el.className = "inline-code";
      if (tag === "a") {
        el.setAttribute("href", href);
        el.setAttribute("target", "_blank");
        el.setAttribute("rel", "nofollow");
      }
      if (inner) inner.appendChild(el);
      else outer = el;
      inner = el;
    });
    return { outer: outer, inner: inner };
  }

  // Inline markers: `**bold**`, `*italic*`, `_italic_`, `~~strike~~`, `` `code` ``, `***both***` and `[text](url)`
  // convert when the closing marker is typed, when an opening marker is typed in front of text that already has
  // its closer, and when text is selected and a marker is typed. Backspace right after a conversion brings the markers back.
  function wireInlineMarkdown(editor, mount) {
    var T = window.NotebookTyping;
    var last = null; // {el, tail, rule} of the conversion just made

    function placeCaretIn(node, offset) {
      var caret = document.createRange();
      caret.setStart(node, offset);
      caret.collapse(true);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(caret);
    }

    mount.addEventListener("keydown", function (e) {
      var sel = window.getSelection();
      if (!sel.rangeCount) return;
      var range = sel.getRangeAt(0);
      var undo = window.notebookUndo;
      // Backspace right after a conversion gives back the typed markers.
      if (e.key === "Backspace" && last && range.collapsed && range.startContainer === last.tail && range.startOffset === 1) {
        e.preventDefault();
        checkpoint(undo);
        var text = document.createTextNode(T.typedForm(last.rule));
        last.el.replaceWith(text);
        last.tail.remove();
        placeCaretIn(text, text.textContent.length);
        last = null;
        mount.dispatchEvent(new Event("input", { bubbles: true }));
        return;
      }
      // A marker typed over a selection wraps it.
      if (range.collapsed || e.ctrlKey || e.metaKey || e.altKey || "*_~`".indexOf(e.key) === -1 || e.key.length !== 1) return;
      if (insideSkipped(range.commonAncestorContainer)) return;
      var editable = (range.commonAncestorContainer.nodeType === Node.TEXT_NODE ? range.commonAncestorContainer.parentElement : range.commonAncestorContainer).closest("[contenteditable=true]");
      if (!editable || !editable.contains(range.startContainer) || !editable.contains(range.endContainer)) return;
      var ancestor = range.commonAncestorContainer.nodeType === Node.TEXT_NODE ? range.commonAncestorContainer.parentElement : range.commonAncestorContainer;
      var parent = ancestor && ancestor.tagName === "I" && ancestor.textContent === range.toString() ? ancestor : null;
      var italic = !!parent;
      var tag = T.selectionTag(e.key, !!italic);
      if (!tag) return;
      e.preventDefault();
      checkpoint(undo);
      if (tag === "b" && italic) {
        var bold = document.createElement("b");
        while (parent.firstChild) bold.appendChild(parent.firstChild);
        parent.replaceWith(bold);
        var again = document.createRange();
        again.selectNodeContents(bold);
        sel.removeAllRanges();
        sel.addRange(again);
      } else {
        var wrapper = elementFor([tag]).outer;
        wrapper.appendChild(range.extractContents());
        range.insertNode(wrapper);
        var inside = document.createRange();
        inside.selectNodeContents(wrapper);
        sel.removeAllRanges();
        sel.addRange(inside);
      }
      last = null;
      mount.dispatchEvent(new Event("input", { bubbles: true }));
      setTimeout(function () { checkpoint(undo); }, 80);
    });

    mount.addEventListener("input", function (e) {
      var sel = window.getSelection();
      var anchor = sel.rangeCount && sel.anchorNode;
      // The zero-width anchor left after a conversion goes as soon as real text follows it.
      if (anchor && anchor.nodeType === Node.TEXT_NODE && anchor.textContent.length > 1 && anchor.textContent.indexOf("​") !== -1) {
        var off = sel.anchorOffset - (anchor.textContent.slice(0, sel.anchorOffset).split("​").length - 1);
        anchor.textContent = anchor.textContent.replace(/​/g, "");
        placeCaretIn(anchor, Math.max(0, off));
      }
      if (e.inputType !== "insertText" || !e.data) return;
      var typed = e.data.charAt(e.data.length - 1);
      if (last && "*_~`)".indexOf(typed) === -1) last = null;
      if ("*_~`)".indexOf(typed) === -1 || !sel.rangeCount || !sel.isCollapsed) return;
      var node = sel.anchorNode;
      if (!node || node.nodeType !== Node.TEXT_NODE || insideSkipped(node)) return;
      var before = node.textContent.slice(0, sel.anchorOffset);
      var after = node.textContent.slice(sel.anchorOffset);
      var rule = T.inlineRule(before, after, typed);
      if (!rule) return;
      var undo = window.notebookUndo;
      checkpoint(undo);
      var range = document.createRange();
      range.setStart(node, rule.start);
      range.setEnd(node, rule.end + rule.consume);
      range.deleteContents();
      var made = elementFor(rule.tags, rule.href);
      made.inner.textContent = rule.content;
      range.insertNode(made.outer);
      var tail = document.createTextNode("​");
      made.outer.after(tail);
      placeCaretIn(tail, 1);
      last = { el: made.outer, tail: tail, rule: rule };
      mount.dispatchEvent(new Event("input", { bubbles: true }));
      if (undo) setTimeout(function () { undo.checkpoint(); }, 80);
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
        placeholder: "Start writing...",
        tunes: ["align", "blockColor", "duplicate"],
        autofocus: true,
        tools: {
          header: {
            class: window.NotebookHeader || window.Header,
            config: { levels: [1, 2, 3, 4, 5], defaultLevel: 2 },
          },
          list: { class: window.EditorjsList, inlineToolbar: true },
          quote: { class: window.NotebookQuote, inlineToolbar: true },
          code: window.NotebookCode,
          table: { class: window.NotebookTable, inlineToolbar: true },
          delimiter: window.NotebookDelimiter,
          timeline: { class: window.NotebookTimeline, inlineToolbar: true },
          callout: { class: window.NotebookCallout, inlineToolbar: true },
          image: window.NotebookImage,
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
          if (window.notebookRenumberFigures) window.notebookRenumberFigures(mount);
          if (window.notebookRenderRelationships) {
            window.notebookRenderRelationships(mount);
          }
          scheduleSave(editor);
        },
      });
      window.notebookEditor = editor;
      editor.isReady.then(function () {
        return editor.save();
      }).then(function (data) {
        if (lastSaved === null) lastSaved = JSON.stringify(data.blocks);
      });
      // Closing the tab or leaving the page inside the wait before an autosave must not lose what was just typed.
      function saveNow() {
        if (!saveTimer) return;
        clearTimeout(saveTimer);
        saveTimer = null;
        save(editor, true);
      }
      document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "hidden") saveNow();
      });
      window.addEventListener("pagehide", saveNow);
      if (window.notebookWireMentions) window.notebookWireMentions(mount);
      if (window.notebookWireBlockDrag) window.notebookWireBlockDrag(mount);
      wireMarkdownShortcuts(editor, mount);
      wireListArrows(editor, mount);
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
      editor.isReady.then(function () {
        if (window.notebookRenumberFigures) window.notebookRenumberFigures(mount);
      });
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
