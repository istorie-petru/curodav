// Wikilinks & relationships (2026-10-03, roadmap-mvp-to-full-product-
// checklist's "Wikilinks & relationships" section) -- two parts working
// together, same split as notebook_footnotes.js:
//
// 1. NotebookWikiLink, an Editor.js Inline Tool modeled on
//    notebook_footnotes.js's NotebookFootnote (render()/surround(range)/
//    checkState()/renderActions()). Inserts a `<span class="cdx-wikilink"
//    contenteditable="false" data-target-uid data-target-title
//    data-target-note-type data-target-color data-target-icon>` marker
//    right after the cursor/selection (not wrapping any selected text,
//    same reasoning as Footnote's own marker -- the link's visible text
//    is always the picked target document's own title, never arbitrary
//    selected text, which is also what keeps rendering simple: nothing
//    here has to re-derive a display string later). The marker resolves
//    to a target document's uid at link-creation time via the search/
//    pick popover below (roadmap: "not fuzzy title-text matching at
//    render time") -- once picked, the uid never changes just because
//    the target's title does later.
//
// 2. A live "Links to" list (`renderRelationships`), re-run on every
//    editor change and after initial load, same "walk the live DOM, re-
//    run on change" approach notebook_toc.js/notebook_footnotes.js already
//    use: walks every `.cdx-wikilink` marker in document order, de-dupes
//    by target uid, and groups them by `data-target-note-type` into
//    #notebook-relationships-out (the Relationships tab's "Links to"
//    section). The tab's other section, "Linked from" (backlinks), is
//    server-rendered instead (routers/notebook.py's document_page) --
//    see db.list_notebook_backlinks' own docstring for why that half
//    can't be done this same client-side way.
(function () {
  function linkIcon() {
    return '<svg class="icon" aria-hidden="true"><use href="#icon-link"></use></svg>';
  }

  function mountUid() {
    var mount = document.getElementById("notebook-editor");
    return mount ? mount.getAttribute("data-uid") : "";
  }

  // item G (session 8, 2026-10-03): this document's own url+title, so the
  // "Links to" list's <a> tags can carry it as back_to/back_label (same
  // param pair notebook_document.html's server-rendered "Linked from"
  // list and _widget_notebook_list.html use) -- not document.title (the
  // browser tab title, which base.html suffixes with " - Curodav"), a
  // dedicated data-title attribute on the mount instead.
  function mountTitle() {
    var mount = document.getElementById("notebook-editor");
    return mount ? mount.getAttribute("data-title") || "" : "";
  }

  function selfLinkParams() {
    return "back_to=" + encodeURIComponent("/notebook/" + mountUid()) + "&back_label=" + encodeURIComponent(mountTitle());
  }

  function debounce(fn, ms) {
    var timer = null;
    return function () {
      var args = arguments;
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(null, args);
      }, ms);
    };
  }

  // Shared by all three ways to create a wikilink (toolbar button,
  // slash-command block, typing `[[`) -- the fetch/render pair used to
  // live only on NotebookWikiLink's own prototype; factored out here so
  // the other two entry points don't re-implement the same search call
  // and result-list markup.
  function searchDocuments(query, cb) {
    var url = "/notebook/search?q=" + encodeURIComponent(query || "") + "&exclude=" + encodeURIComponent(mountUid());
    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (resp) {
        return resp.ok ? resp.json() : [];
      })
      .catch(function () {
        return [];
      })
      .then(cb);
  }

  function renderResultsInto(ul, items, onPick) {
    ul.innerHTML = "";
    if (!items.length) {
      var empty = document.createElement("li");
      empty.className = "cdx-wikilink-picker-empty";
      empty.textContent = "No matching documents";
      ul.appendChild(empty);
      return;
    }
    items.forEach(function (item) {
      var li = document.createElement("li");
      li.className = "cdx-wikilink-picker-result";
      li.innerHTML =
        '<svg class="icon icon-sm cal-' + item.color + '" aria-hidden="true"><use href="#icon-' + item.icon + '"></use></svg>' +
        "<span>" + escapeHtml(item.title) + "</span>";
      li.addEventListener("click", function () {
        onPick(item);
      });
      ul.appendChild(li);
    });
  }

  function NotebookWikiLink(params) {
    this.api = params.api;
    this.button = null;
    this.wrap = null;
    this.input = null;
    this.results = null;
    this.currentMarker = null;
  }
  NotebookWikiLink.isInline = true;
  NotebookWikiLink.title = "Wikilink";
  NotebookWikiLink.sanitize = {
    span: {
      class: "cdx-wikilink",
      "data-target-uid": true,
      "data-target-title": true,
      "data-target-note-type": true,
      "data-target-color": true,
      "data-target-icon": true,
    },
  };
  NotebookWikiLink.prototype.render = function () {
    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.classList.add(this.api.styles.inlineToolButton);
    this.button.innerHTML = linkIcon();
    return this.button;
  };
  NotebookWikiLink.prototype.renderActions = function () {
    var self = this;
    this.wrap = document.createElement("div");
    this.wrap.className = "cdx-wikilink-picker";
    this.input = document.createElement("input");
    this.input.type = "text";
    this.input.setAttribute("aria-label", "Search documents");
    this.input.className = "cdx-wikilink-picker-input";
    this.results = document.createElement("ul");
    this.results.className = "cdx-wikilink-picker-results";
    this.wrap.appendChild(window.CCSearchField.wrap(this.input));
    this.wrap.appendChild(this.results);
    var runSearch = debounce(function () {
      self.search(self.input.value);
    }, 200);
    this.input.addEventListener("input", runSearch);
    return this.wrap;
  };
  NotebookWikiLink.prototype.search = function (q) {
    var self = this;
    searchDocuments(q, function (items) {
      renderResultsInto(self.results, items, function (item) {
        self.pick(item);
      });
    });
  };
  NotebookWikiLink.prototype.pick = function (item) {
    if (!this.currentMarker) return;
    applyPick(this.currentMarker, item);
  };
  NotebookWikiLink.prototype.surround = function (range) {
    if (!range) return;
    var existing = this.api.selection.findParentTag("SPAN", "cdx-wikilink");
    if (existing) {
      // Cursor is already inside a wikilink marker -- the button click
      // just reopens the picker (checkState below), nothing to insert.
      return;
    }
    var marker = document.createElement("span");
    marker.className = "cdx-wikilink";
    marker.setAttribute("data-target-uid", "");
    marker.setAttribute("data-target-title", "");
    marker.contentEditable = "false";
    marker.textContent = "New link";
    var insertAt = range.cloneRange();
    insertAt.collapse(false);
    insertAt.insertNode(marker);
    var after = document.createRange();
    after.setStartAfter(marker);
    after.collapse(true);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(after);
  };
  NotebookWikiLink.prototype.checkState = function () {
    var marker = this.api.selection.findParentTag("SPAN", "cdx-wikilink");
    this.currentMarker = marker || null;
    if (this.button) {
      this.button.classList.toggle(
        this.api.styles.inlineToolButtonActive,
        !!marker
      );
    }
    if (marker && this.input) {
      this.input.value = marker.getAttribute("data-target-title") || "";
      this.search(this.input.value);
    }
    return !!marker;
  };

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s || "";
    return div.innerHTML;
  }

  function notifyMountChanged(node) {
    var mount = node.closest ? node.closest("#notebook-editor") : null;
    if (!mount) return;
    renderRelationships(mount);
    mount.dispatchEvent(new CustomEvent("notebook-wikilink-change"));
  }

  function applyPick(marker, item) {
    marker.setAttribute("data-target-uid", item.uid);
    marker.setAttribute("data-target-title", item.title);
    marker.setAttribute("data-target-note-type", item.note_type || "");
    marker.setAttribute("data-target-color", item.color);
    marker.setAttribute("data-target-icon", item.icon);
    marker.textContent = item.title;
    notifyMountChanged(marker);
  }

  // Typing `[` (or `[[`) opens the document dropdown in notebook_mentions.js, which builds the
  // link with this marker.
  window.notebookWikilinkMarker = function (item) {
    var span = document.createElement("span");
    span.className = "cdx-wikilink";
    span.contentEditable = "false";
    span.setAttribute("data-target-uid", item.uid);
    span.setAttribute("data-target-title", item.title);
    span.setAttribute("data-target-note-type", item.note_type || "");
    span.setAttribute("data-target-color", item.color);
    span.setAttribute("data-target-icon", item.icon);
    span.textContent = item.title;
    return span;
  };

  // Slash-command entry point -- a block tool so it shows up in Editor.js's
  // own "/" toolbox (direct request: "should also be possible to be
  // created with the slash command"). Its render() is just the same
  // search/pick UI as the inline tool's popover; picking a result replaces
  // this placeholder block with a plain paragraph whose only content is
  // the wikilink marker (same markup the inline tool inserts), via
  // `api.blocks.insert` + `delete` since there's no smaller public API for
  // "turn this block into that one" that also changes tool type.
  function NotebookWikilinkBlock(params) {
    this.api = params.api;
    this.wrap = null;
    this.input = null;
    this.results = null;
    this.picked = false;
  }
  NotebookWikilinkBlock.toolbox = { title: "Wikilink", icon: linkIcon() };
  NotebookWikilinkBlock.prototype.render = function () {
    var self = this;
    this.wrap = document.createElement("div");
    this.wrap.className = "cdx-wikilink-picker";
    this.input = document.createElement("input");
    this.input.type = "text";
    this.input.setAttribute("aria-label", "Link to a document");
    this.input.className = "cdx-wikilink-picker-input";
    this.results = document.createElement("ul");
    this.results.className = "cdx-wikilink-picker-results";
    this.wrap.appendChild(window.CCSearchField.wrap(this.input));
    this.wrap.appendChild(this.results);
    this.input.addEventListener(
      "input",
      debounce(function () {
        self.search(self.input.value);
      }, 200)
    );
    this.input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") self.cancel();
    });
    setTimeout(function () {
      self.input.focus();
      self.search("");
    }, 0);
    return this.wrap;
  };
  NotebookWikilinkBlock.prototype.search = function (q) {
    var self = this;
    searchDocuments(q, function (items) {
      renderResultsInto(self.results, items, function (item) {
        self.pick(item);
      });
    });
  };
  // `getCurrentBlockIndex()` is only as fresh as Editor.js's own click/
  // focus bookkeeping, which a block picked via mouse click through the
  // toolbox doesn't reliably update -- confirmed live (2026-10-03, while
  // building the footnote action menu's own identical block-tool shape,
  // see the slash-command block's own `ownIndex` below
  // and [[curodav-webapp-footnote-action-menu]]): a freshly-inserted
  // placeholder block stayed marked "selected" in the DOM, yet
  // `getCurrentBlockIndex()`-based deletion silently missed it entirely --
  // no thrown error, just the wrong block (or none) removed. Deriving the
  // index from this block's own wrap element instead sidesteps that
  // bookkeeping altogether.
  NotebookWikilinkBlock.prototype.ownIndex = function () {
    var block = this.api.blocks.getBlockByElement(this.wrap);
    return block ? this.api.blocks.getBlockIndex(block.id) : this.api.blocks.getCurrentBlockIndex();
  };
  NotebookWikilinkBlock.prototype.pick = function (item) {
    this.picked = true;
    var span = document.createElement("span");
    span.className = "cdx-wikilink";
    span.contentEditable = "false";
    span.setAttribute("data-target-uid", item.uid);
    span.setAttribute("data-target-title", item.title);
    span.setAttribute("data-target-note-type", item.note_type || "");
    span.setAttribute("data-target-color", item.color);
    span.setAttribute("data-target-icon", item.icon);
    span.textContent = item.title;
    var index = this.ownIndex();
    this.api.blocks.insert("paragraph", { text: span.outerHTML + "&nbsp;" }, {}, index, true);
    this.api.blocks.delete(index + 1);
  };
  NotebookWikilinkBlock.prototype.cancel = function () {
    if (this.picked) return;
    this.picked = true;
    this.api.blocks.delete(this.ownIndex());
  };
  NotebookWikilinkBlock.prototype.save = function () {
    return {};
  };

  // "Links to" -- live, grouped by the target's note_type, same
  // document-order + de-dupe-by-target shape notebook_toc.js's heading
  // walk uses, just grouped instead of flat.
  //
  // 2026-10-03 (backlog item A, minimalist Relationships empty state): the
  // whole "Links to" section (heading + nav), not just its inner list, is
  // now hidden/shown based on whether there's anything to show -- the
  // "No links yet" placeholder this function used to render *inside* the
  // nav is gone, replaced by the one shared `#notebook-relationships-empty`
  // line updateRelationshipsEmptyState() manages below, same minimalism
  // reasoning as notebook_document.html's own comment on the markup.
  function renderRelationships(mount) {
    var outSection = document.getElementById("notebook-relationships-out-section");
    var nav = document.getElementById("notebook-relationships-out");
    if (!nav) return;
    var marks = mount.querySelectorAll(".cdx-wikilink[data-target-uid]");
    var seen = {};
    var groups = {};
    var order = [];
    marks.forEach(function (mark) {
      var uid = mark.getAttribute("data-target-uid");
      if (!uid || seen[uid]) return;
      seen[uid] = true;
      var noteType = mark.getAttribute("data-target-note-type") || "";
      if (!groups[noteType]) {
        groups[noteType] = [];
        order.push(noteType);
      }
      groups[noteType].push({
        uid: uid,
        title: mark.getAttribute("data-target-title") || uid,
        color: mark.getAttribute("data-target-color") || "gray",
        icon: mark.getAttribute("data-target-icon") || "file-text",
      });
    });
    nav.innerHTML = "";
    if (!order.length) {
      if (outSection) outSection.hidden = true;
    } else {
      if (outSection) outSection.hidden = false;
      order.forEach(function (noteType) {
        var heading = document.createElement("div");
        heading.className = "notebook-relationships-group-heading";
        heading.textContent = noteType ? noteType + "s" : "Other";
        nav.appendChild(heading);
        groups[noteType].forEach(function (item) {
          var row = document.createElement("div");
          row.className = "notebook-relationships-item";
          row.innerHTML =
            '<svg class="icon icon-sm cal-' + item.color + '" aria-hidden="true"><use href="#icon-' + item.icon + '"></use></svg>' +
            '<a href="/notebook/' + item.uid + '?' + selfLinkParams() + '">' + escapeHtml(item.title) + "</a>";
          nav.appendChild(row);
        });
      });
    }
    updateRelationshipsEmptyState();
  }

  // "Linked from" never changes client-side (server-rendered backlinks,
  // see notebook_document.html's own comment on why), so this only ever
  // needs to re-read its static `hidden` state, not recompute it.
  function updateRelationshipsEmptyState() {
    var empty = document.getElementById("notebook-relationships-empty");
    if (!empty) return;
    var outSection = document.getElementById("notebook-relationships-out-section");
    var inSection = document.getElementById("notebook-relationships-in-section");
    var outVisible = !!outSection && !outSection.hidden;
    var inVisible = !!inSection && !inSection.hidden;
    empty.hidden = outVisible || inVisible;
  }

  window.NotebookWikiLink = NotebookWikiLink;
  window.NotebookWikilinkBlock = NotebookWikilinkBlock;
  window.notebookRenderRelationships = renderRelationships;
})();
