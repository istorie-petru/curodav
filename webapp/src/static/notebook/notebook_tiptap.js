// Page glue for the Tiptap editor (the default; ?editor=legacy is an explicit opt-in to the Editor.js one).
// The note is stored as the same Editor.js block list, so the server side is unchanged; notes with content the
// new editor cannot hold yet open read-only and are never saved from here.
(function () {
  var mount = document.getElementById("notebook-editor");
  if (!mount || !window.CurodavEditor || !window.NotebookTiptapToolbar) return;
  var contentUrl = mount.getAttribute("data-content-url");
  var openedAt = performance.now();
  var saveTimer = null;
  var retryTimer = null;
  var inFlight = false;
  var bigBody = false;
  var lastSaved = null;
  var failedSaves = 0;
  var handle = null;
  var endnotes = null;
  var draftKey = "nb-draft:" + mount.getAttribute("data-uid");
  var draftTimer = null;

  // The text as it is being written is kept in this browser and stored on the server at the moments below; what
  // the server does not have yet survives a closed tab or a lost connection and is sent when the page next opens.
  function readDraft() {
    try { return JSON.parse(localStorage.getItem(draftKey)); } catch (e) { return null; }
  }
  function writeDraft() {
    try {
      localStorage.setItem(draftKey, JSON.stringify({ blocks: handle.blocks(), at: Date.now() }));
    } catch (e) {}
  }
  function clearDraft() {
    try { localStorage.removeItem(draftKey); } catch (e) {}
  }

  function measure(name, since) {
    if (window.ccPerf) window.ccPerf.add(name, performance.now() - since);
  }

  function scheduleRetry() {
    if (retryTimer) return;
    var wait = Math.min(30000, 3000 * Math.pow(2, Math.min(failedSaves, 4)));
    retryTimer = setTimeout(function () {
      retryTimer = null;
      save(false);
    }, wait);
  }

  var again = false;

  // Resolves when the request has finished, either way, so a caller can wait for it before the page goes away.
  function save(leaving) {
    // One request at a time; whatever was typed meanwhile goes out right after, as one save.
    if (inFlight && !leaving) {
      again = true;
      return Promise.resolve();
    }
    var blocks = handle.blocks();
    var text = JSON.stringify(blocks);
    if (text === lastSaved) {
      failedSaves = 0;
      return Promise.resolve();
    }
    var body = JSON.stringify({ time: Date.now(), blocks: blocks, version: "tiptap" });
    // A keep-alive request is capped at 64 KB. Every save that fits is sent with it, so a page that closes
    // while the request is on its way does not cancel it.
    bigBody = body.length >= 60000;
    var started = performance.now();
    inFlight = true;
    return window.NotebookSave.put(contentUrl, body, !bigBody)
      .then(function (resp) {
        inFlight = false;
        if (!resp) return;
        measure("editor save", started);
        lastSaved = text;
        failedSaves = 0;
        if (JSON.stringify(handle.blocks()) === text) clearDraft();
        document.dispatchEvent(new CustomEvent("notebook-saved"));
        if (again) {
          again = false;
          return save(false);
        }
      })
      .catch(function () {
        inFlight = false;
        again = false;
        if (failedSaves++ === 0) window.ccToast({ message: "Could not reach the server. Your changes are kept in this browser and will be sent when the connection returns.", variant: "error" });
        scheduleRetry();
      });
  }

  // Everything typed so far goes to the browser copy and to the server now.
  function saveNow() {
    if (draftTimer) {
      clearTimeout(draftTimer);
      draftTimer = null;
      writeDraft();
    }
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
    return save(true);
  }

  function unsaved() {
    return !!(saveTimer || retryTimer || inFlight || again || draftTimer) || failedSaves > 0;
  }

  window.addEventListener("online", function () {
    if (failedSaves > 0) {
      clearTimeout(retryTimer);
      retryTimer = null;
      save(false);
    }
  });

  // Closing or reloading with changes that cannot be sent in time (the server is out of reach, or the note is too
  // large for a closing request) asks first; otherwise the save simply goes out as the page leaves.
  window.addEventListener("beforeunload", function (e) {
    if (!handle || handle.readOnly || !unsaved()) return;
    saveNow();
    if (bigBody || failedSaves > 0 || retryTimer) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  // A click on a link inside the app waits for the save to finish, so the next page already has the new text.
  document.addEventListener(
    "click",
    function (e) {
      if (!handle || handle.readOnly || !unsaved() || e.defaultPrevented || e.button !== 0) return;
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      var link = e.target.closest && e.target.closest("a[href]");
      if (!link || link.target || link.hasAttribute("data-modal") || link.hasAttribute("download")) return;
      if (link.origin !== window.location.origin || link.getAttribute("href").charAt(0) === "#") return;
      e.preventDefault();
      var go = function () { window.location.href = link.href; };
      Promise.race([saveNow(), new Promise(function (r) { setTimeout(r, 2000); })]).then(go, go);
    },
    true
  );

  mount.addEventListener(
    "keydown",
    function (e) {
      if (e.key.length !== 1 || e.ctrlKey || e.metaKey) return;
      var pressed = performance.now();
      requestAnimationFrame(function () {
        setTimeout(function () {
          measure("editor typing", pressed);
        }, 0);
      });
    },
    true
  );

  // Links open with Ctrl or Cmd plus click, like the entries' dotted names.
  mount.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest(".ProseMirror a[href]");
    if (link && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      window.open(link.getAttribute("href"), "_blank", "noopener");
    }
  });
  function modifier(e) { mount.classList.toggle("nb-mod-down", e.ctrlKey || e.metaKey); }
  document.addEventListener("keydown", modifier);
  document.addEventListener("keyup", modifier);

  // ---- Endnotes: numbered by the order of the markers in the text; each note is edited in the list under the editor ----
  var NOTE_TAGS = { B: 1, STRONG: 1, I: 1, EM: 1, U: 1, S: 1, CODE: 1, SUB: 1, SUP: 1, A: 1, BR: 1 };

  function cleanNote(html) {
    var box = document.createElement("div");
    box.innerHTML = html;
    (function walk(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (child) {
        if (child.nodeType === 3) return;
        if (child.nodeType !== 1 || !NOTE_TAGS[child.tagName]) {
          child.replaceWith.apply(child, Array.prototype.slice.call(child.childNodes));
          return;
        }
        Array.prototype.slice.call(child.attributes).forEach(function (a) {
          if (!(child.tagName === "A" && a.name === "href")) child.removeAttribute(a.name);
        });
        walk(child);
      });
    })(box);
    return box.innerHTML;
  }

  function buildEndnotes(editor) {
    var footer = document.createElement("div");
    footer.className = "cdx-footnote-footer";
    footer.hidden = true;
    mount.parentNode.insertBefore(footer, mount.nextSibling);
    var scheduled = false;

    function notes() {
      var found = [];
      editor.state.doc.descendants(function (node, pos) {
        if (node.type.name === "endnote") found.push({ pos: pos, bag: node.attrs.bag, node: node });
      });
      return found;
    }

    function update(id, attrs) {
      var found = notes().filter(function (n) { return n.bag["data-note-id"] === id; })[0];
      if (!found) return;
      var bag = Object.assign({}, found.bag);
      Object.keys(attrs).forEach(function (name) {
        if (attrs[name] === null) delete bag[name];
        else bag[name] = attrs[name];
      });
      editor.view.dispatch(editor.state.tr.setNodeMarkup(found.pos, null, Object.assign({}, found.node.attrs, { bag: bag })));
    }

    function setNote(id, html) {
      update(id, { "data-note": html });
    }

    function render() {
      scheduled = false;
      var all = notes();
      if (!all.length) {
        footer.hidden = true;
        footer.replaceChildren();
        return;
      }
      footer.hidden = false;
      var list = footer.querySelector(".cdx-footnote-list");
      if (!list) {
        footer.innerHTML = '<div class="cdx-footnote-footer__heading">Endnotes</div><ol class="cdx-footnote-list"></ol>';
        list = footer.querySelector(".cdx-footnote-list");
      }
      var seen = {};
      all.forEach(function (n, i) {
        var id = n.bag["data-note-id"];
        seen[id] = true;
        var kind = n.bag["data-footnote-kind"] || "";
        var li = document.getElementById("fn-" + id);
        if (li && li.classList.contains("cdx-footnote-list-item-structured") !== !!kind) {
          li.remove();
          li = null;
        }
        if (!li) {
          li = document.createElement("li");
          li.id = "fn-" + id;
          var row = document.createElement("span");
          row.className = "cdx-footnote-structured-row";
          var body = document.createElement("span");
          body.className = "cdx-footnote-text";
          if (kind) {
            li.classList.add("cdx-footnote-list-item-structured");
          } else {
            body.contentEditable = "true";
            body.spellcheck = false;
            body.addEventListener("input", function () { setNote(id, cleanNote(body.innerHTML)); });
          }
          row.appendChild(body);
          if (window.notebookEndnoteMenuButton) row.appendChild(window.notebookEndnoteMenuButton(li));
          li.appendChild(row);
        }
        if (list.children[i] !== li) list.insertBefore(li, list.children[i] || null);
        var body = li.querySelector(".cdx-footnote-text");
        var text = n.bag["data-note"] || "";
        if (document.activeElement !== body) {
          if (body.innerHTML !== cleanNote(text)) body.innerHTML = cleanNote(text);
        }
      });
      Array.prototype.slice.call(list.children).forEach(function (li) {
        if (!seen[li.id.slice(3)]) li.remove();
      });
    }

    function schedule() {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(render);
    }
    editor.on("update", schedule);
    mount.addEventListener("click", function (e) {
      var marker = e.target.closest && e.target.closest("sup.cdx-footnote-ref");
      var li = marker && document.getElementById("fn-" + marker.getAttribute("data-note-id"));
      var body = li && li.querySelector(".cdx-footnote-text[contenteditable=true]");
      if (body) body.focus();
    });
    render();
    window.notebookEndnoteBridge = { update: update, refresh: render };
    return {
      insert: function () {
        var id = "n" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
        editor.view.focus();
        editor.chain().insertContent({ type: "endnote", attrs: { bag: { class: "cdx-footnote-ref", "data-note-id": id, "data-note": "", contenteditable: "false" }, inner: "" } }).run();
        render();
        var body = document.querySelector("#fn-" + id + " .cdx-footnote-text");
        if (body) body.focus();
      },
    };
  }

  // A note that failed to load stays closed: an empty editor would autosave over the real content.
  window.NotebookSave.load(contentUrl)
    .catch(function () {
      window.ccToast({ message: "Could not open this document. Reload the page to try again.", variant: "error", persistent: true });
      return null;
    })
    .then(function (initial) {
      if (!initial) return;
      var blocks = initial.blocks || [];
      var serverText = JSON.stringify(blocks);
      var draft = readDraft();
      var restored = false;
      if (draft && Array.isArray(draft.blocks) && JSON.stringify(draft.blocks) !== serverText) {
        // Text that never reached the server is the newest thing written: it is restored and sent.
        blocks = draft.blocks;
        restored = true;
      } else if (draft) {
        clearDraft();
      }
      handle = window.CurodavEditor.create(mount, blocks, function () {
        var changed = performance.now();
        if (draftTimer) clearTimeout(draftTimer);
        draftTimer = setTimeout(writeDraft, 300);
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(function () {
          saveTimer = null;
          save(false);
        }, 600);
        measure("editor change", changed);
      });
      lastSaved = restored ? serverText : JSON.stringify(handle.blocks());
      if (restored) saveTimer = setTimeout(function () { saveTimer = null; save(false); }, 500);
      window.notebookEditor = {
        save: function () {
          return Promise.resolve({ time: Date.now(), blocks: handle.blocks(), version: "tiptap" });
        },
      };
      var tocTimer = null;
      function refreshOutline() {
        if (!window.notebookRenderToc) return;
        clearTimeout(tocTimer);
        tocTimer = setTimeout(function () { window.notebookRenderToc(mount); }, 300);
      }
      handle.editor.on("update", refreshOutline);
      refreshOutline();
      if (!handle.readOnly) {
        endnotes = buildEndnotes(handle.editor);
        window.NotebookTiptapToolbar.build(handle.editor, mount, { insertEndnote: function () { endnotes.insert(); } });
        if (window.notebookWireMentions) window.notebookWireMentions(mount);
      }
      measure("editor open", openedAt);
      if (handle.readOnly) {
        var banner = document.createElement("div");
        banner.className = "nb-readonly-banner";
        banner.setAttribute("role", "status");
        var what = handle.reasons.length ? "It holds " + handle.reasons.join(", ") + " blocks the new editor cannot hold yet" : "It holds content the new editor cannot hold yet";
        banner.append(what + ", so it is read-only here and nothing is changed. ");
        var link = document.createElement("a");
        link.href = "?editor=legacy";
        link.textContent = "Open it in the old editor to edit";
        banner.append(link, ". ");
        var convert = document.createElement("button");
        convert.type = "button";
        convert.className = "btn ghost btn-sm";
        convert.textContent = "Convert to the new editor";
        convert.addEventListener("click", function () {
          var result = window.CurodavEditor.forceConvert(blocks);
          var parts = [];
          if (result.dropped.length) parts.push("These blocks are removed: " + result.dropped.join(", ") + ".");
          if (result.cleaned) parts.push(result.cleaned + " block" + (result.cleaned === 1 ? " loses" : "s lose") + " formatting the new editor cannot hold.");
          if (!parts.length) parts.push("Nothing is removed.");
          window.ccConfirmSheet({
            message: "Convert this note to the new editor? " + parts.join(" ") + " The earlier version stays in the note's history.",
            confirmLabel: "Convert",
            onConfirm: function () {
              var body = JSON.stringify({ time: Date.now(), blocks: result.blocks, version: "tiptap" });
              window.NotebookSave.put(contentUrl, body, false)
                .then(function (resp) {
                  if (resp) window.location.reload();
                })
                .catch(function () {
                  window.ccToast({ message: "Could not convert this note.", variant: "error" });
                });
            },
          });
        });
        banner.append(convert);
        mount.parentNode.insertBefore(banner, mount);
      }
      document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "hidden") saveNow();
      });
      window.addEventListener("pagehide", saveNow);
      // Leaving the editor (a click elsewhere on the page) is a natural moment to store what was typed.
      mount.addEventListener("focusout", function (e) {
        if (!mount.contains(e.relatedTarget)) saveNow();
      });
    });
})();
