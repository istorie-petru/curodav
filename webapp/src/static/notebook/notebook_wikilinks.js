(function () {
  function linkIcon() {
    return '<svg class="icon" aria-hidden="true"><use href="#icon-link"></use></svg>';
  }

  function mountUid() {
    var mount = document.getElementById("notebook-editor");
    return mount ? mount.getAttribute("data-uid") : "";
  }

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
    var url = "/notebook/link-search?kinds=doc&q=" + encodeURIComponent(query || "") + "&exclude=" + encodeURIComponent(mountUid());
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
      ul.appendChild(window.ccEmptyState("No matching documents", "li"));
      return;
    }
    items.forEach(function (item, i) {
      var li = document.createElement("li");
      li.className = "cdx-wikilink-picker-result" + (i === 0 ? " is-active" : "");
      li.innerHTML =
        '<svg class="icon icon-sm cal-' + item.color + '" aria-hidden="true"><use href="#icon-' + item.icon + '"></use></svg>' +
        "<span>" + escapeHtml(item.title) + "</span>" +
        (item.subtitle ? '<span class="cdx-wikilink-picker-sub">' + escapeHtml(item.subtitle) + "</span>" : "");
      li.addEventListener("click", function () {
        onPick(item);
      });
      ul.appendChild(li);
    });
  }

  // Up and Down move through the results and Enter picks the highlighted one.
  function wirePickerKeys(input, ul) {
    input.addEventListener("keydown", function (e) {
      var rows = Array.prototype.slice.call(ul.querySelectorAll(".cdx-wikilink-picker-result"));
      if (!rows.length) return;
      var at = rows.findIndex(function (r) { return r.classList.contains("is-active"); });
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        e.stopPropagation();
        rows.forEach(function (r) { r.classList.remove("is-active"); });
        var next = (Math.max(at, 0) + (e.key === "ArrowDown" ? 1 : rows.length - 1)) % rows.length;
        rows[next].classList.add("is-active");
        rows[next].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") {
        e.preventDefault();
        e.stopPropagation();
        (rows[at] || rows[0]).click();
      }
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
    wirePickerKeys(this.input, this.results);
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
    wirePickerKeys(this.input, this.results);
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
