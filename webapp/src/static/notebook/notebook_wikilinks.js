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

  // Every way to make a wikilink opens the one picker in notebook_mentions.js, which listens for `[[`:
  // the toolbar button types `[[` for the selected text (or for the link being changed), and the slash command
  // turns its block into a paragraph holding `[[`. The picker searches notes and entries and can create new ones.
  function typeTrigger(node, editable) {
    var caret = document.createRange();
    caret.setStart(node, node.textContent.length);
    caret.collapse(true);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(caret);
    if (editable) editable.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function NotebookWikiLink(params) {
    this.api = params.api;
    this.button = null;
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
    this.button.title = "Link to a note or entry";
    this.button.setAttribute("aria-label", "Link to a note or entry");
    this.button.innerHTML = linkIcon();
    return this.button;
  };
  NotebookWikiLink.prototype.surround = function (range) {
    if (!range) return;
    var existing = this.api.selection.findParentTag("SPAN", "cdx-wikilink");
    var query = existing ? existing.getAttribute("data-target-title") || "" : range.toString().trim();
    var node = document.createTextNode("[[" + query);
    if (existing) {
      existing.replaceWith(node);
    } else {
      range.deleteContents();
      range.insertNode(node);
    }
    var editable = node.parentElement && node.parentElement.closest("[contenteditable=true]");
    typeTrigger(node, editable);
  };
  NotebookWikiLink.prototype.checkState = function () {
    var marker = this.api.selection.findParentTag("SPAN", "cdx-wikilink");
    if (this.button) this.button.classList.toggle(this.api.styles.inlineToolButtonActive, !!marker);
    return false;
  };

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s || "";
    return div.innerHTML;
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

  // The slash command: the block turns into a paragraph that already holds `[[`, so the picker opens at once.
  function NotebookWikilinkBlock(params) {
    this.api = params.api;
    this.wrap = null;
  }
  NotebookWikilinkBlock.toolbox = { title: "Wikilink", icon: linkIcon() };
  NotebookWikilinkBlock.prototype.render = function () {
    var self = this;
    this.wrap = document.createElement("div");
    setTimeout(function () {
      var found = self.api.blocks.getBlockByElement(self.wrap);
      var index = found ? self.api.blocks.getBlockIndex(found.id) : self.api.blocks.getCurrentBlockIndex();
      self.api.blocks.insert("paragraph", { text: "[[" }, {}, index, true);
      self.api.blocks.delete(index + 1);
      setTimeout(function () {
        var holder = self.api.blocks.getBlockByIndex(index);
        var editable = holder && holder.holder.querySelector("[contenteditable=true]");
        if (!editable) return;
        editable.focus();
        var node = editable.firstChild;
        if (node && node.nodeType === Node.TEXT_NODE) typeTrigger(node, editable);
      }, 0);
    }, 0);
    return this.wrap;
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
