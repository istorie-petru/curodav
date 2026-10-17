// Block menu tunes for the Notebook editor: block text and background color, and the Duplicate, Move and Delete row.
// Feature notes: curodav-notes/documentation/features/notebook-editor.md.
(function () {
  var COPY_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  var PALETTE_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22a10 10 0 1 1 10-10c0 3-2 4-4.5 4H15a2 2 0 0 0-1.5 3.3c.6.7.5 2.7-1.5 2.7z"/><circle cx="7.5" cy="11" r="1"/><circle cx="12" cy="7" r="1"/><circle cx="16.5" cy="11" r="1"/></svg>';

  // ---- Block color ----
  // In a rich text block (paragraph, heading, quote, callout, list) it does what selecting all the text and
  // using the inline Color tool does: one <mark> around each editable's content. Other blocks (table, code,
  // image) keep a wrapper carrying a text and a background color. Both use the inline tool's swatch grid.
  var TEXT_BLOCKS = ["paragraph", "header", "quote", "callout", "list"];
  var KIND_OF = { tc: "text", hl: "bg" };

  function editablesOf(holder) {
    return Array.prototype.slice.call(holder.querySelectorAll('[contenteditable="true"]'));
  }

  function wholeMark(el) {
    var only = el.childNodes.length === 1 ? el.firstChild : null;
    return only && only.nodeType === Node.ELEMENT_NODE && only.tagName === "MARK" ? only : null;
  }

  function colorElement(el, kind, color) {
    var prefix = "nb-" + kind + "-";
    el.querySelectorAll("mark").forEach(function (mark) {
      mark.className = mark.className.split(/\s+/).filter(function (c) { return c && c.indexOf(prefix) !== 0; }).join(" ");
      if (!/\bnb-(tc|hl)-/.test(mark.className)) {
        while (mark.firstChild) mark.parentNode.insertBefore(mark.firstChild, mark);
        mark.remove();
      }
    });
    el.normalize();
    if (!color || !el.firstChild) return;
    var mark = wholeMark(el);
    if (!mark) {
      mark = document.createElement("mark");
      while (el.firstChild) mark.appendChild(el.firstChild);
      el.appendChild(mark);
    }
    mark.classList.add(prefix + color);
  }

  function NotebookBlockColor(params) {
    this.data = params.data || {};
    this.block = params.block;
    this.wrapper = null;
  }
  NotebookBlockColor.isTune = true;
  NotebookBlockColor.prototype.wrap = function (content) {
    this.wrapper = document.createElement("div");
    this.wrapper.className = "nb-block-color";
    this.apply();
    this.wrapper.appendChild(content);
    return this.wrapper;
  };
  NotebookBlockColor.prototype.apply = function () {
    if (!this.wrapper) return;
    ["text", "bg"].forEach(function (kind) {
      var attr = "data-" + kind;
      if (this.data[kind]) this.wrapper.setAttribute(attr, this.data[kind]);
      else this.wrapper.removeAttribute(attr);
    }, this);
  };
  NotebookBlockColor.prototype.isText = function () {
    return !!(this.block && TEXT_BLOCKS.indexOf(this.block.name) !== -1 && this.block.holder);
  };
  NotebookBlockColor.prototype.isActive = function (kind, color) {
    if (!this.isText()) return color ? this.data[KIND_OF[kind]] === color : !this.data[KIND_OF[kind]];
    var first = editablesOf(this.block.holder)[0];
    var mark = first && wholeMark(first);
    if (!color) return !mark || !new RegExp("\\bnb-" + kind + "-").test(mark.className);
    return !!mark && mark.classList.contains("nb-" + kind + "-" + color);
  };
  NotebookBlockColor.prototype.set = function (kind, color) {
    var undo = window.notebookUndo;
    if (undo) undo.checkpoint();
    if (this.isText()) {
      delete this.data[KIND_OF[kind]];
      this.apply();
      editablesOf(this.block.holder).forEach(function (el) { colorElement(el, kind, color); });
      var mount = document.getElementById("notebook-editor");
      if (mount) mount.dispatchEvent(new Event("input", { bubbles: true }));
    } else {
      if (color) this.data[KIND_OF[kind]] = color;
      else delete this.data[KIND_OF[kind]];
      this.apply();
    }
    if (this.block && this.block.dispatchChange) this.block.dispatchChange();
    if (undo) setTimeout(function () { undo.checkpoint(); }, 80);
  };
  NotebookBlockColor.prototype.render = function () {
    var self = this;
    var panel = window.NotebookColorPanel(
      function (kind, color) { self.set(kind, color); },
      function (kind, color) { return self.isActive(kind, color); }
    );
    return {
      icon: PALETTE_ICON,
      title: "Color",
      toggle: "nb-block-color",
      children: { items: [{ type: "html", element: panel }] },
    };
  };
  NotebookBlockColor.prototype.save = function () {
    return { text: this.data.text || "", bg: this.data.bg || "" };
  };

  // ---- Block actions: duplicate, move up, move down and delete as one row of icon buttons ----
  // Replaces the list items Editor.js adds for move and delete (hidden in notebook_inline.css).
  var UP_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m18 15-6-6-6 6"/></svg>';
  var DOWN_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
  var TRASH_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>';

  function NotebookDuplicate(params) {
    this.api = params.api;
    this.block = params.block;
  }
  NotebookDuplicate.isTune = true;
  NotebookDuplicate.prototype.render = function () {
    var self = this;
    var api = this.api;
    var row = document.createElement("div");
    row.className = "nb-actions-row";
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", "Block actions");
    function index() {
      return api.blocks.getBlockIndex(self.block.id);
    }
    function tool(title, icon, disabled, onClick, danger) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "nb-actions-btn" + (danger ? " is-danger" : "");
      b.title = title;
      b.setAttribute("aria-label", title);
      b.innerHTML = icon;
      b.disabled = !!disabled;
      b.addEventListener("click", function () {
        var undo = window.notebookUndo;
        if (undo) undo.checkpoint();
        onClick();
        api.toolbar.close();
        if (undo) setTimeout(function () { undo.checkpoint(); }, 80);
      });
      row.appendChild(b);
    }
    var at = index();
    var count = api.blocks.getBlocksCount();
    tool("Duplicate", COPY_ICON, false, function () {
      self.block.save().then(function (saved) {
        if (!saved) return;
        var copy = api.blocks.insert(saved.tool, saved.data, {}, index() + 1, true);
        if (copy && saved.tunes && copy.id) api.blocks.update(copy.id, saved.data, saved.tunes);
      });
    });
    tool("Move up", UP_ICON, at <= 0, function () { api.blocks.move(at - 1, at); });
    tool("Move down", DOWN_ICON, at >= count - 1, function () { api.blocks.move(at + 1, at); });
    tool("Delete", TRASH_ICON, false, function () { api.blocks.delete(index()); }, true);
    return { type: "html", element: row };
  };
  NotebookDuplicate.prototype.save = function () {
    return {};
  };

  window.NotebookBlockColor = NotebookBlockColor;
  window.NotebookDuplicate = NotebookDuplicate;
})();
