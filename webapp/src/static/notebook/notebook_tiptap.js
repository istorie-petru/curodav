// Page glue for the Tiptap editor (opt-in with ?editor=tiptap while the Editor.js one is still the default).
// The note is stored as the same Editor.js block list, so the server side is unchanged; notes with content the
// new editor cannot hold yet open read-only and are never saved from here.
(function () {
  var mount = document.getElementById("notebook-editor");
  if (!mount || !window.CurodavEditor || !window.NotebookTiptapToolbar) return;
  var contentUrl = mount.getAttribute("data-content-url");
  var openedAt = performance.now();
  var saveTimer = null;
  var lastSaved = null;
  var failedSaves = 0;
  var handle = null;
  var endnotes = null;

  function measure(name, since) {
    if (window.ccPerf) window.ccPerf.add(name, performance.now() - since);
  }

  function save(leaving) {
    var blocks = handle.blocks();
    var text = JSON.stringify(blocks);
    if (text === lastSaved) return;
    var body = JSON.stringify({ time: Date.now(), blocks: blocks, version: "tiptap" });
    var started = performance.now();
    fetch(contentUrl, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: body,
      keepalive: !!leaving && body.length < 60000,
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("save failed");
        measure("editor save", started);
        lastSaved = text;
        failedSaves = 0;
        document.dispatchEvent(new CustomEvent("notebook-saved"));
      })
      .catch(function () {
        if (failedSaves++ === 0) window.ccToast({ message: "Could not save this document. Your last changes are not stored yet.", variant: "error" });
      });
  }

  function saveNow() {
    if (!saveTimer) return;
    clearTimeout(saveTimer);
    saveTimer = null;
    save(true);
  }

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

  fetch(contentUrl, { headers: { Accept: "application/json" } })
    .then(function (resp) {
      if (!resp.ok) throw new Error("load failed");
      return resp.json();
    })
    .catch(function () {
      return { blocks: [] };
    })
    .then(function (initial) {
      var blocks = initial.blocks || [];
      handle = window.CurodavEditor.create(mount, blocks, function () {
        var changed = performance.now();
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(function () {
          saveTimer = null;
          save(false);
        }, 1500);
        measure("editor change", changed);
      });
      lastSaved = JSON.stringify(handle.blocks());
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
      if (handle.readOnly && mount.getAttribute("data-editor-choice") !== "tiptap") {
        // The note uses something the new editor cannot hold yet; the old editor opens it for now.
        handle.editor.destroy();
        var url = new URL(window.location.href);
        url.searchParams.set("editor", "legacy");
        window.location.replace(url.toString());
        return;
      }
      if (handle.readOnly) {
        window.ccToast({ message: "This note uses content the new editor cannot hold yet, so it is read-only here.", variant: "info" });
      }
      document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "hidden") saveNow();
      });
      window.addEventListener("pagehide", saveNow);
    });
})();
