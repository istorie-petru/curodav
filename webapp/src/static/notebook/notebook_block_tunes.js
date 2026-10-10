// Block menu tunes for the Notebook editor: block text and background color, and Duplicate.
// Feature notes: curodav-notes/documentation/features/notebook-editor.md.
(function () {
  var COLORS = ["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "gray"];

  function dot(color, filled) {
    if (!color) return NONE_ICON;
    var fill = "var(--tag-" + color + (filled ? "-bg" : "-fg") + ")";
    return '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="' + fill + '" stroke="currentColor" stroke-width="1.2"/></svg>';
  }
  var NONE_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/></svg>';
  var COPY_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  var PALETTE_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22a10 10 0 1 1 10-10c0 3-2 4-4.5 4H15a2 2 0 0 0-1.5 3.3c.6.7.5 2.7-1.5 2.7z"/><circle cx="7.5" cy="11" r="1"/><circle cx="12" cy="7" r="1"/><circle cx="16.5" cy="11" r="1"/></svg>';

  // ---- Block color: one wrapper carrying a text color and a background color ----
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
  NotebookBlockColor.prototype.set = function (kind, color) {
    if (color) this.data[kind] = color;
    else delete this.data[kind];
    this.apply();
    if (this.block && this.block.dispatchChange) this.block.dispatchChange();
  };
  NotebookBlockColor.prototype.render = function () {
    var self = this;
    function items(kind) {
      return [{ title: "None", icon: dot("", false), onActivate: function () { self.set(kind, ""); } }].concat(
        COLORS.map(function (color) {
          return {
            title: color.charAt(0).toUpperCase() + color.slice(1),
            icon: dot(color, kind === "bg"),
            onActivate: function () { self.set(kind, color); },
          };
        })
      );
    }
    return {
      icon: PALETTE_ICON,
      title: "Color",
      toggle: "nb-block-color",
      children: {
        items: [{ title: "Text color", children: { items: items("text") } }, { title: "Background", children: { items: items("bg") } }],
      },
    };
  };
  NotebookBlockColor.prototype.save = function () {
    return { text: this.data.text || "", bg: this.data.bg || "" };
  };

  // ---- Duplicate: a copy of the block (content, alignment and color) right after it ----
  function NotebookDuplicate(params) {
    this.api = params.api;
    this.block = params.block;
  }
  NotebookDuplicate.isTune = true;
  NotebookDuplicate.prototype.render = function () {
    var self = this;
    return {
      icon: COPY_ICON,
      title: "Duplicate",
      onActivate: function () {
        self.block.save().then(function (saved) {
          if (!saved) return;
          var index = self.api.blocks.getBlockIndex(self.block.id);
          var copy = self.api.blocks.insert(saved.tool, saved.data, {}, index + 1, true);
          if (copy && saved.tunes && copy.id) self.api.blocks.update(copy.id, saved.data, saved.tunes);
        });
      },
    };
  };
  NotebookDuplicate.prototype.save = function () {
    return {};
  };

  window.NotebookBlockColor = NotebookBlockColor;
  window.NotebookDuplicate = NotebookDuplicate;
})();
