// Notebook inline text tools (Phase H): strikethrough, combined text and
// highlight color, the More menu (subscript, superscript, alignment) and
// remove formatting, plus the alignment block tune. Same inline-tool shape
// as notebook_footnotes.js: render() button, surround(range), checkState().
// Feature notes: curodav-notes/documentation/features/notebook-editor.md.
(function () {
  var COLORS = ["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "gray"];
  var FORMAT_TAGS = ["B", "STRONG", "I", "EM", "U", "S", "MARK", "CODE", "SUB", "SUP", "A"];
  var KEEP_CLASSES = ["cdx-footnote-ref", "cdx-wikilink"];

  function svg(paths) {
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + "</svg>";
  }
  var ICONS = {
    code: svg('<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>'),
    strike: svg('<path d="M16 4H9a3 3 0 0 0-2.83 4"/><path d="M14 12a4 4 0 0 1 0 8H6"/><line x1="4" y1="12" x2="20" y2="12"/>'),
    color: svg('<path d="M4 20h16"/><path d="m6 16 6-12 6 12"/><path d="M8 12h8"/>'),
    more: svg('<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'),
    clear: svg('<path d="m7 21-4.3-4.3a1 1 0 0 1 0-1.4l9.6-9.6a1 1 0 0 1 1.4 0l5.6 5.6a1 1 0 0 1 0 1.4L13 21"/><path d="M22 21H7"/><path d="m5 11 9 9"/>'),
    sub: svg('<path d="m4 5 8 8"/><path d="m12 5-8 8"/><path d="M20 19h-4c0-1.5.44-2 1.5-2.5S20 15.33 20 14c0-.47-.17-.93-.48-1.29a2.11 2.11 0 0 0-2.62-.44c-.42.24-.74.62-.9 1.07"/>'),
    sup: svg('<path d="m4 19 8-8"/><path d="m12 19-8-8"/><path d="M20 12h-4c0-1.5.442-2 1.5-2.5S20 8.334 20 7.002c0-.472-.17-.93-.484-1.29a2.105 2.105 0 0 0-2.617-.436c-.42.239-.738.614-.899 1.06"/>'),
    left: svg('<line x1="21" y1="6" x2="3" y2="6"/><line x1="15" y1="12" x2="3" y2="12"/><line x1="17" y1="18" x2="3" y2="18"/>'),
    center: svg('<line x1="21" y1="6" x2="3" y2="6"/><line x1="17" y1="12" x2="7" y2="12"/><line x1="19" y1="18" x2="5" y2="18"/>'),
    right: svg('<line x1="21" y1="6" x2="3" y2="6"/><line x1="21" y1="12" x2="9" y2="12"/><line x1="21" y1="18" x2="7" y2="18"/>'),
  };

  function button(api, html, title) {
    var b = document.createElement("button");
    b.type = "button";
    b.classList.add(api.styles.inlineToolButton);
    b.innerHTML = html;
    b.title = title;
    b.setAttribute("aria-label", title);
    return b;
  }

  function unwrap(el) {
    var parent = el.parentNode;
    if (!parent) return;
    while (el.firstChild) parent.insertBefore(el.firstChild, el);
    parent.removeChild(el);
    parent.normalize();
  }

  function wrapSelection(range, tag, className) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    el.appendChild(range.extractContents());
    range.insertNode(el);
    return el;
  }

  function reselect(el) {
    var sel = window.getSelection();
    var r = document.createRange();
    r.selectNodeContents(el);
    sel.removeAllRanges();
    sel.addRange(r);
  }

  // ---- Inline code (replaces the vendored tool, which only applied once per
  // toolbar opening; this one toggles on any selection, any number of times).
  function NotebookInlineCode(params) {
    this.api = params.api;
    this.button = null;
  }
  NotebookInlineCode.isInline = true;
  NotebookInlineCode.title = "Inline code";
  NotebookInlineCode.sanitize = { code: { class: "inline-code" } };
  NotebookInlineCode.shortcut = "CMD+E";
  NotebookInlineCode.prototype.render = function () {
    this.button = button(this.api, ICONS.code, "Inline code");
    return this.button;
  };
  NotebookInlineCode.prototype.surround = function (range) {
    if (!range) return;
    var existing = this.api.selection.findParentTag("CODE", "inline-code");
    if (existing) {
      unwrap(existing);
      return;
    }
    reselect(wrapSelection(range, "CODE", "inline-code"));
  };
  NotebookInlineCode.prototype.checkState = function () {
    var on = !!this.api.selection.findParentTag("CODE", "inline-code");
    this.button.classList.toggle(this.api.styles.inlineToolButtonActive, on);
    return on;
  };

  // ---- Strikethrough ------------------------------------------------
  function NotebookStrike(params) {
    this.api = params.api;
    this.button = null;
  }
  NotebookStrike.isInline = true;
  NotebookStrike.title = "Strikethrough";
  NotebookStrike.sanitize = { s: {} };
  NotebookStrike.prototype.render = function () {
    this.button = button(this.api, ICONS.strike, "Strikethrough");
    return this.button;
  };
  NotebookStrike.prototype.surround = function (range) {
    if (!range) return;
    var existing = this.api.selection.findParentTag("S");
    if (existing) {
      unwrap(existing);
      return;
    }
    reselect(wrapSelection(range, "S"));
  };
  NotebookStrike.prototype.checkState = function () {
    var on = !!this.api.selection.findParentTag("S");
    this.button.classList.toggle(this.api.styles.inlineToolButtonActive, on);
    return on;
  };
  NotebookStrike.shortcut = "CMD+SHIFT+X";

  // ---- Text and highlight color (one tool, one <mark>) --------------
  function NotebookColor(params) {
    this.api = params.api;
    this.button = null;
    this.panel = null;
    this.current = null;
  }
  NotebookColor.isInline = true;
  NotebookColor.title = "Color";
  NotebookColor.sanitize = { mark: { class: true } };
  NotebookColor.prototype.render = function () {
    this.button = button(this.api, ICONS.color, "Text and highlight color");
    return this.button;
  };
  NotebookColor.prototype.renderActions = function () {
    var self = this;
    this.panel = document.createElement("div");
    this.panel.className = "nb-color-panel";
    [["tc", "Text color"], ["hl", "Background"]].forEach(function (row) {
      var wrap = document.createElement("div");
      wrap.className = "nb-color-row";
      var label = document.createElement("span");
      label.className = "nb-color-label";
      label.textContent = row[1];
      wrap.appendChild(label);
      [""].concat(COLORS).forEach(function (color) {
        var sw = document.createElement("button");
        sw.type = "button";
        sw.className = "nb-swatch nb-swatch-" + row[0] + (color ? " nb-" + row[0] + "-" + color : " is-none");
        sw.setAttribute("data-kind", row[0]);
        sw.setAttribute("data-color", color);
        sw.setAttribute("aria-label", row[1] + " " + (color || "none"));
        sw.title = color || "None";
        sw.textContent = row[0] === "tc" ? "A" : "";
        sw.addEventListener("mousedown", function (e) {
          e.preventDefault();
        });
        sw.addEventListener("click", function () {
          self.pick(row[0], color);
        });
        wrap.appendChild(sw);
      });
      self.panel.appendChild(wrap);
    });
    return this.panel;
  };
  NotebookColor.prototype.pick = function (kind, color) {
    var mark = this.api.selection.findParentTag("MARK") || this.current;
    if (!mark) {
      var sel = window.getSelection();
      if (!color || !sel.rangeCount || sel.getRangeAt(0).collapsed) return;
      mark = wrapSelection(sel.getRangeAt(0), "MARK");
      reselect(mark);
    }
    this.current = mark;
    mark.className = mark.className.split(/\s+/).filter(function (c) {
      return c && c.indexOf("nb-" + kind + "-") !== 0;
    }).concat(color ? ["nb-" + kind + "-" + color] : []).join(" ");
    if (!/\bnb-(tc|hl)-/.test(mark.className)) {
      unwrap(mark);
      this.current = null;
    }
    this.refresh();
    this.notify();
  };
  NotebookColor.prototype.notify = function () {
    var mount = document.getElementById("notebook-editor");
    if (mount) mount.dispatchEvent(new Event("input", { bubbles: true }));
  };
  NotebookColor.prototype.refresh = function () {
    var mark = this.current;
    if (!this.panel) return;
    this.panel.querySelectorAll(".nb-swatch").forEach(function (sw) {
      var kind = sw.getAttribute("data-kind");
      var color = sw.getAttribute("data-color");
      var has = color
        ? !!mark && mark.classList.contains("nb-" + kind + "-" + color)
        : !mark || !new RegExp("\\bnb-" + kind + "-").test(mark.className);
      sw.classList.toggle("is-active", has);
    });
  };
  // Editor.js opens and closes the nested panel itself when the button is
  // clicked; it is open from the start when the selection is already colored.
  NotebookColor.prototype.surround = function () {};
  NotebookColor.prototype.checkState = function () {
    var mark = this.api.selection.findParentTag("MARK");
    this.current = mark || null;
    this.button.classList.toggle(this.api.styles.inlineToolButtonActive, !!mark);
    this.refresh();
    return !!mark;
  };

  // ---- More menu: subscript, superscript, alignment -----------------
  function currentBlockWrapper() {
    var sel = window.getSelection();
    var node = sel && sel.anchorNode;
    var el = node && (node.nodeType === Node.TEXT_NODE ? node.parentElement : node);
    return el && el.closest ? el.closest(".nb-align") : null;
  }

  // The toolbar's tool instances are recreated every time it opens, so the
  // "keep the More panel open after an action" flag lives here. It clears on
  // a click outside the toolbar, Escape, or a collapsed selection.
  var moreKeepOpen = false;
  document.addEventListener("mousedown", function (e) {
    if (moreKeepOpen && !e.target.closest(".ce-inline-toolbar")) moreKeepOpen = false;
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") moreKeepOpen = false;
  });
  document.addEventListener("selectionchange", function () {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed) moreKeepOpen = false;
  });

  // The enclosing <sub>/<sup> of the selection, ignoring endnote markers.
  function findScript(tag) {
    var sel = window.getSelection();
    var node = sel && sel.anchorNode;
    var el = node && (node.nodeType === Node.TEXT_NODE ? node.parentElement : node);
    var found = el && el.closest ? el.closest(tag.toLowerCase()) : null;
    return found && !found.classList.contains("cdx-footnote-ref") ? found : null;
  }

  function NotebookMore(params) {
    this.api = params.api;
    this.button = null;
    this.panel = null;
  }
  NotebookMore.isInline = true;
  NotebookMore.title = "More";
  // <sup> is already allowed by the endnote tool's sanitize rule; redefining it here would replace that rule.
  NotebookMore.sanitize = { sub: {} };
  NotebookMore.prototype.render = function () {
    this.button = button(this.api, ICONS.more, "More formatting");
    return this.button;
  };
  NotebookMore.prototype.renderActions = function () {
    var self = this;
    this.panel = document.createElement("div");
    this.panel.className = "nb-more-panel";
    [
      ["sub", ICONS.sub, "Subscript"],
      ["sup", ICONS.sup, "Superscript"],
      ["left", ICONS.left, "Align left"],
      ["center", ICONS.center, "Align center"],
      ["right", ICONS.right, "Align right"],
    ].forEach(function (item) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "nb-more-item";
      b.innerHTML = item[1];
      b.title = item[2];
      b.setAttribute("aria-label", item[2]);
      b.setAttribute("data-action", item[0]);
      b.addEventListener("mousedown", function (e) {
        e.preventDefault();
      });
      b.addEventListener("click", function () {
        self.run(item[0]);
      });
      self.panel.appendChild(b);
    });
    return this.panel;
  };
  NotebookMore.prototype.run = function (action) {
    moreKeepOpen = true;
    if (action === "left" || action === "center" || action === "right") {
      var wrap = currentBlockWrapper();
      if (wrap) {
        wrap.setAttribute("data-align", action);
        var editor = window.notebookEditor;
        var block = editor && editor.blocks.getBlockByElement(wrap);
        if (block && block.dispatchChange) block.dispatchChange();
      }
      this.markState();
      return;
    }
    var sel = window.getSelection();
    if (!sel.rangeCount) return;
    var tag = action === "sub" ? "SUB" : "SUP";
    var existing = findScript(tag);
    if (existing) {
      unwrap(existing);
    } else {
      var other = findScript(tag === "SUB" ? "SUP" : "SUB");
      if (other) {
        var swapped = document.createElement(tag);
        while (other.firstChild) swapped.appendChild(other.firstChild);
        other.parentNode.replaceChild(swapped, other);
        reselect(swapped);
      } else {
        reselect(wrapSelection(sel.getRangeAt(0), tag));
      }
    }
    this.markState();
  };
  NotebookMore.prototype.markState = function () {
    if (!this.panel) return;
    var wrap = currentBlockWrapper();
    var align = (wrap && wrap.getAttribute("data-align")) || "left";
    var sub = !!findScript("SUB");
    var sup = !!findScript("SUP");
    this.panel.querySelectorAll(".nb-more-item").forEach(function (b) {
      var a = b.getAttribute("data-action");
      b.classList.toggle("is-active", a === align || (a === "sub" && sub) || (a === "sup" && sup));
    });
  };
  NotebookMore.prototype.surround = function () {};
  // After an action the toolbar rebuilds around the new selection; keep the
  // panel open so several actions can be applied in a row.
  NotebookMore.prototype.checkState = function () {
    this.markState();
    return moreKeepOpen;
  };

  // ---- Remove formatting --------------------------------------------
  function NotebookClearFormat(params) {
    this.api = params.api;
  }
  NotebookClearFormat.isInline = true;
  NotebookClearFormat.title = "Remove formatting";
  NotebookClearFormat.prototype.render = function () {
    return button(this.api, ICONS.clear, "Remove formatting");
  };
  NotebookClearFormat.prototype.surround = function (range) {
    if (!range || range.collapsed) return;
    var fragment = range.extractContents();
    stripFormatting(fragment);
    var last = fragment.lastChild;
    var first = fragment.firstChild;
    range.insertNode(fragment);
    if (first && last) {
      var sel = window.getSelection();
      var r = document.createRange();
      r.setStartBefore(first);
      r.setEndAfter(last);
      sel.removeAllRanges();
      sel.addRange(r);
    }
  };
  NotebookClearFormat.prototype.checkState = function () {
    return false;
  };

  // Unwraps every formatting element in `root`, keeping markers (endnotes,
  // wikilinks) and any non-formatting content as they are.
  function stripFormatting(root) {
    var nodes = Array.prototype.slice.call(root.querySelectorAll(FORMAT_TAGS.join(",").toLowerCase()));
    nodes.forEach(function (el) {
      var keep = KEEP_CLASSES.some(function (c) {
        return el.classList.contains(c);
      });
      if (!keep) unwrap(el);
    });
  }

  // ---- Alignment block tune ------------------------------------------
  function NotebookAlignTune(params) {
    this.api = params.api;
    this.block = params.block;
    this.data = (params.data && params.data.align) || "left";
    this.wrapper = null;
  }
  NotebookAlignTune.isTune = true;
  NotebookAlignTune.prototype.wrap = function (content) {
    this.wrapper = document.createElement("div");
    this.wrapper.className = "nb-align";
    this.wrapper.setAttribute("data-align", this.data);
    this.wrapper.appendChild(content);
    return this.wrapper;
  };
  NotebookAlignTune.prototype.render = function () {
    var self = this;
    return ["left", "center", "right"].map(function (align) {
      return {
        icon: ICONS[align],
        title: "Align " + align,
        onActivate: function () {
          self.data = align;
          if (self.wrapper) self.wrapper.setAttribute("data-align", align);
          if (self.block && self.block.dispatchChange) self.block.dispatchChange();
        },
        isActive: self.wrapper ? self.wrapper.getAttribute("data-align") === align : self.data === align,
        closeOnActivate: true,
        toggle: "nb-align",
      };
    });
  };
  NotebookAlignTune.prototype.save = function () {
    return { align: (this.wrapper && this.wrapper.getAttribute("data-align")) || this.data };
  };

  window.NotebookInlineCode = NotebookInlineCode;
  window.NotebookStrike = NotebookStrike;
  window.NotebookColor = NotebookColor;
  window.NotebookMore = NotebookMore;
  window.NotebookClearFormat = NotebookClearFormat;
  window.NotebookAlignTune = NotebookAlignTune;
  window.notebookStripFormatting = stripFormatting;
})();
