// Notebook table: a first-party Editor.js block tool that replaces the vendored table. It reads
// the vendored tool's saved data ({withHeadings, content}) unchanged, and adds merged cells, a
// header column, formulas, per-column alignment, sorting and cell colors. The pure logic lives in
// notebook_table_model.js. Feature notes: curodav-notes/documentation/features/notebook-tables.md.
(function () {
  var M = window.NotebookTableModel;
  if (!M) return;

  var COLORS = window.NotebookPalette;

  function svg(paths) {
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + "</svg>";
  }
  var ICONS = {
    table: svg('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 4v16M15 4v16"/>'),
    row: svg('<rect x="3" y="4" width="18" height="6" rx="1"/><path d="M3 15h18M3 19h18"/>'),
    col: svg('<rect x="4" y="3" width="6" height="18" rx="1"/><path d="M15 3v18M19 3v18"/>'),
    refs: svg('<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>'),
    dense: svg('<path d="M4 6h16M4 10h16M4 14h16M4 18h16"/>'),
    stripes: svg('<rect x="3" y="4" width="18" height="4" /><rect x="3" y="12" width="18" height="4"/>'),
    copy: svg('<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'),
    more: svg('<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'),
    insertBefore: svg('<path d="M12 5v14M5 12h14"/>'),
    trash: svg('<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/>'),
    alignAuto: svg('<path d="M4 6h16M4 12h10M4 18h13"/><path d="m19 14 2 2-2 2"/>'),
    alignLeft: svg('<line x1="21" y1="6" x2="3" y2="6"/><line x1="15" y1="12" x2="3" y2="12"/><line x1="17" y1="18" x2="3" y2="18"/>'),
    alignCenter: svg('<line x1="21" y1="6" x2="3" y2="6"/><line x1="17" y1="12" x2="7" y2="12"/><line x1="19" y1="18" x2="5" y2="18"/>'),
    alignRight: svg('<line x1="21" y1="6" x2="3" y2="6"/><line x1="21" y1="12" x2="9" y2="12"/><line x1="21" y1="18" x2="7" y2="18"/>'),
    sortAsc: svg('<path d="M11 5h4M11 9h7M11 13h10"/><path d="m3 8 4-4 4 4M7 4v16"/>'),
    sortDesc: svg('<path d="M11 5h10M11 9h7M11 13h4"/><path d="m3 16 4 4 4-4M7 20V4"/>'),
    left: svg('<path d="m15 18-6-6 6-6"/>'),
    right: svg('<path d="m9 18 6-6-6-6"/>'),
    up: svg('<path d="m18 15-6-6-6 6"/>'),
    down: svg('<path d="m6 9 6 6 6-6"/>'),
    merge: svg('<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/><path d="M8 12h8M12 8v8"/>'),
    split: svg('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M12 3v18"/>'),
    palette: svg('<path d="M12 22a10 10 0 1 1 10-10c0 3-2 4-4.5 4H15a2 2 0 0 0-1.5 3.3c.6.7.5 2.7-1.5 2.7z"/><circle cx="7.5" cy="11" r="1"/><circle cx="12" cy="7" r="1"/><circle cx="16.5" cy="11" r="1"/>'),
    clear: svg('<path d="m7 21-4.3-4.3a1 1 0 0 1 0-1.4l9.6-9.6a1 1 0 0 1 1.4 0l5.6 5.6a1 1 0 0 1 0 1.4L13 21"/><path d="M22 21H7"/>'),
    csv: svg('<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h8"/>'),
    markdown: svg('<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 15V9l3 3 3-3v6M17 9v6m0 0-2-2m2 2 2-2"/>'),
    textColor: svg('<path d="M4 20h16"/><path d="m6 16 6-12 6 12"/><path d="M8 12h8"/>'),
    fill: svg('<path d="m19 11-8-8-8.6 8.6a2 2 0 0 0 0 2.8l5.2 5.2c.8.8 2 .8 2.8 0L19 11z"/><path d="m5 2 5 5"/><path d="M2 13h15"/><path d="M22 20a2 2 0 1 1-4 0c0-1.6 1.7-2.4 2-4 .3 1.6 2 2.4 2 4z"/>'),
    none: svg('<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>'),
  };

  function colorDot(color, kind) {
    if (!color) return ICONS.none;
    var fill = "var(--tag-" + color + (kind === "bg" ? "-bg" : "-fg") + ")";
    return '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="' + fill + '" stroke="currentColor" stroke-width="1.2"/></svg>';
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function NotebookTable(params) {
    var data = params.data || {};
    this.api = params.api;
    this.block = params.block;
    this.readOnly = !!params.readOnly;
    var content = Array.isArray(data.content) && data.content.length ? clone(data.content) : [["", ""], ["", ""]];
    var cols = M.colCount(content);
    content = content.map(function (row) {
      var copy = row.slice();
      while (copy.length < cols) copy.push("");
      return copy;
    });
    this.model = { content: content, merges: clone(data.merges || []), align: clone(data.align || {}), colors: clone(data.colors || {}) };
    this.opts = {
      withHeadings: !!data.withHeadings,
      headerColumn: !!data.headerColumn,
      dense: !!data.dense,
      striped: !!data.striped,
      showRefs: !!data.showRefs,
    };
    this.wrapper = null;
    this.table = null;
    this.sel = null;
    this.anchor = null;
    this.refreshTimer = null;
    this.numericCols = null;
    this.point = null;
    this.menuEntries = [];
    this.barEntry = null;
    this.bar = null;
  }
  NotebookTable.toolbox = { title: "Table", icon: ICONS.table };
  NotebookTable.isReadOnlySupported = true;
  NotebookTable.enableLineBreaks = false;
  // Cell text may carry the inline formatting the toolbar allows; the rest is plain data.
  NotebookTable.sanitize = {
    content: {},
    withHeadings: false,
    headerColumn: false,
    dense: false,
    striped: false,
    showRefs: false,
    merges: false,
    align: false,
    colors: false,
  };

  NotebookTable.prototype.render = function () {
    this.wrapper = document.createElement("div");
    this.wrapper.className = "nbt";
    this.build();
    this.wire();
    return this.wrapper;
  };

  NotebookTable.prototype.rendered = function () {
    this.refresh();
  };

  NotebookTable.prototype.save = function () {
    this.syncFromDom();
    var out = {
      withHeadings: this.opts.withHeadings,
      content: clone(this.model.content),
    };
    if (this.opts.headerColumn) out.headerColumn = true;
    if (this.opts.dense) out.dense = true;
    if (this.opts.striped) out.striped = true;
    if (this.opts.showRefs) out.showRefs = true;
    if (this.model.merges.length) out.merges = clone(this.model.merges);
    if (Object.keys(this.model.align).length) out.align = clone(this.model.align);
    if (Object.keys(this.model.colors).length) out.colors = clone(this.model.colors);
    return out;
  };

  // ---- Building the grid -------------------------------------------------------------
  NotebookTable.prototype.build = function () {
    var self = this;
    var model = this.model;
    var covered = M.coveredMap(model.merges);
    this.wrapper.classList.toggle("is-dense", this.opts.dense);
    this.wrapper.classList.toggle("is-striped", this.opts.striped);
    this.wrapper.classList.toggle("show-refs", this.opts.showRefs);
    this.wrapper.classList.toggle("has-head", this.opts.withHeadings);
    this.numericCols = null;
    this.wrapper.innerHTML = "";

    var scroll = document.createElement("div");
    scroll.className = "nbt-scroll";
    var table = document.createElement("table");
    table.className = "nbt-table";
    var body = document.createElement("tbody");
    model.content.forEach(function (row, r) {
      var tr = document.createElement("tr");
      row.forEach(function (raw, c) {
        if (covered[r + "," + c]) return;
        var td = document.createElement("td");
        td.dataset.r = r;
        td.dataset.c = c;
        var merge = M.mergeAt(model.merges, r, c);
        if (merge) {
          if (merge.rs > 1) td.rowSpan = merge.rs;
          if (merge.cs > 1) td.colSpan = merge.cs;
        }
        if ((self.opts.withHeadings && r === 0) || (self.opts.headerColumn && c === 0)) td.classList.add("nbt-head");
        var cell = document.createElement("div");
        cell.className = "nbt-cell";
        cell.contentEditable = self.readOnly ? "false" : "true";
        cell.spellcheck = false;
        cell.innerHTML = raw;
        td.appendChild(cell);
        if (r === 0) td.appendChild(self.grip("col", c));
        if (c === 0) td.appendChild(self.grip("row", r));
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    scroll.appendChild(table);
    this.wrapper.appendChild(scroll);
    this.table = table;
    if (!this.readOnly) {
      this.wrapper.appendChild(this.edge("row"));
      this.wrapper.appendChild(this.edge("col"));
    }
    this.refresh();
  };

  NotebookTable.prototype.grip = function (kind, index) {
    var g = document.createElement("button");
    g.type = "button";
    g.className = "nbt-grip nbt-grip-" + kind;
    g.tabIndex = -1;
    g.contentEditable = "false";
    g.dataset.index = index;
    g.textContent = kind === "col" ? M.colName(index) : String(index + 1);
    g.title = (kind === "col" ? "Column " : "Row ") + g.textContent;
    g.setAttribute("aria-label", (kind === "col" ? "Column " : "Row ") + g.textContent + " actions");
    return g;
  };

  // A thin strip on the bottom and right edge that widens into an icon on hover.
  NotebookTable.prototype.edge = function (kind) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "nbt-edge nbt-edge-" + kind;
    b.tabIndex = -1;
    b.title = kind === "row" ? "Add row" : "Add column";
    b.setAttribute("aria-label", b.title);
    b.innerHTML = ICONS.insertBefore;
    return b;
  };

  NotebookTable.prototype.cellAt = function (r, c) {
    var td = this.table && this.table.querySelector('td[data-r="' + r + '"][data-c="' + c + '"]');
    return td ? td.querySelector(".nbt-cell") : null;
  };

  NotebookTable.prototype.position = function (cell) {
    var td = cell.closest("td");
    return { r: Number(td.dataset.r), c: Number(td.dataset.c) };
  };

  // ---- Keeping the model and the DOM in step ---------------------------------------------
  NotebookTable.prototype.syncFromDom = function () {
    if (!this.table) return;
    var self = this;
    this.table.querySelectorAll("td").forEach(function (td) {
      var pos = { r: Number(td.dataset.r), c: Number(td.dataset.c) };
      var cell = td.querySelector(".nbt-cell");
      var focused = document.activeElement === cell;
      var current = self.model.content[pos.r][pos.c];
      if (M.isFormula(current)) {
        // A formula cell shows its value; only a real edit (text that is not that value) replaces it.
        if (!focused || M.stripHtml(cell.innerHTML) === cell.dataset.display) return;
      }
      var html = cell.innerHTML;
      if (html === "<br>") html = "";
      self.model.content[pos.r][pos.c] = html;
    });
  };

  // Shows computed values, marks numeric columns, applies alignment and colors.
  NotebookTable.prototype.refresh = function () {
    if (!this.table) return;
    var self = this;
    var values;
    try {
      values = M.evaluate(this.model.content, this.model.merges);
    } catch (e) {
      return;
    }
    var first = this.opts.withHeadings ? 1 : 0;
    // Automatic alignment is decided when the table is built and when a cell is left, not while
    // typing, so it does not flip as a number is half typed. The header column never right-aligns.
    if (!this.numericCols) {
      this.numericCols = {};
      for (var c = 0; c < M.colCount(this.model.content); c++) {
        this.numericCols[c] = !(this.opts.headerColumn && c === 0) && M.isNumericColumn(values, c, first);
      }
    }
    var numeric = this.numericCols;
    this.table.querySelectorAll("td").forEach(function (td) {
      var r = Number(td.dataset.r), c = Number(td.dataset.c);
      var cell = td.querySelector(".nbt-cell");
      var raw = self.model.content[r][c];
      var computed = values[r][c];
      var focused = document.activeElement === cell;
      var formula = M.isFormula(raw);
      td.classList.toggle("nbt-formula", formula);
      td.classList.toggle("nbt-err", !!(computed && computed.err));
      if (computed && computed.err) td.title = computed.err;
      else if (formula) td.title = M.stripHtml(raw);
      else td.removeAttribute("title");
      if (formula) cell.dataset.display = computed.text;
      else delete cell.dataset.display;
      if (formula && !focused && cell.textContent !== computed.text) cell.textContent = computed.text;
      var align = self.model.align[c];
      var effective = align || (numeric[c] && !(r < first) ? "right" : "");
      if (effective) td.dataset.align = effective;
      else td.removeAttribute("data-align");
      var color = self.model.colors[r + "," + c];
      cell.removeAttribute("data-tc");
      cell.removeAttribute("data-bg");
      if (color && color.text) cell.dataset.tc = color.text;
      if (color && color.bg) td.dataset.bg = color.bg;
      else td.removeAttribute("data-bg");
    });
    this.updateSelectionClasses();
  };

  NotebookTable.prototype.scheduleRefresh = function () {
    var self = this;
    clearTimeout(this.refreshTimer);
    this.refreshTimer = setTimeout(function () {
      self.syncFromDom();
      self.refresh();
    }, 150);
  };

  NotebookTable.prototype.changed = function () {
    if (this.block && this.block.dispatchChange) this.block.dispatchChange();
  };

  // Applies a structural change, rebuilds the grid and keeps the caret near where it was.
  NotebookTable.prototype.apply = function (next, focus) {
    this.syncFromDom();
    this.model.content = next.content;
    this.model.merges = next.merges;
    this.model.align = next.align;
    this.model.colors = next.colors;
    this.clearSelection();
    this.build();
    this.changed();
    if (focus) this.focusCell(focus.r, focus.c);
  };

  NotebookTable.prototype.focusCell = function (r, c, atEnd) {
    var rows = this.model.content.length;
    r = Math.max(0, Math.min(r, rows - 1));
    c = Math.max(0, Math.min(c, M.colCount(this.model.content) - 1));
    var merges = this.model.merges;
    for (var i = 0; i < merges.length; i++) {
      var m = merges[i];
      if (r >= m.r && r < m.r + m.rs && c >= m.c && c < m.c + m.cs) { r = m.r; c = m.c; break; }
    }
    var cell = this.cellAt(r, c);
    if (!cell) return;
    cell.focus();
    var range = document.createRange();
    range.selectNodeContents(cell);
    range.collapse(!atEnd);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  };

  // ---- Selection of a rectangle of cells ---------------------------------------------------
  NotebookTable.prototype.clearSelection = function () {
    this.sel = null;
    this.anchor = null;
    this.hideBar();
    this.updateSelectionClasses();
  };

  NotebookTable.prototype.setSelection = function (a, b) {
    var r1 = Math.min(a.r, b.r), r2 = Math.max(a.r, b.r), c1 = Math.min(a.c, b.c), c2 = Math.max(a.c, b.c);
    var grew = true;
    while (grew) {
      grew = false;
      this.model.merges.forEach(function (m) {
        if (!(m.r + m.rs - 1 < r1 || m.r > r2 || m.c + m.cs - 1 < c1 || m.c > c2)) {
          var nr1 = Math.min(r1, m.r), nr2 = Math.max(r2, m.r + m.rs - 1);
          var nc1 = Math.min(c1, m.c), nc2 = Math.max(c2, m.c + m.cs - 1);
          if (nr1 !== r1 || nr2 !== r2 || nc1 !== c1 || nc2 !== c2) { r1 = nr1; r2 = nr2; c1 = nc1; c2 = nc2; grew = true; }
        }
      });
    }
    this.sel = { r1: r1, c1: c1, r2: r2, c2: c2 };
    this.updateSelectionClasses();
    this.showBar();
  };

  // A selected rectangle is drawn as one outline around the whole block of cells, not per cell.
  NotebookTable.prototype.updateSelectionClasses = function () {
    var sel = this.sel;
    if (!this.table) return;
    var scroll = this.table.closest(".nbt-scroll");
    var box = scroll && scroll.querySelector(".nbt-selection");
    if (!sel || (sel.r1 === sel.r2 && sel.c1 === sel.c2 && !M.mergeAt(this.model.merges, sel.r1, sel.c1))) {
      if (box) box.remove();
      this.wrapper.classList.remove("has-selection");
      return;
    }
    this.wrapper.classList.add("has-selection");
    var tds = Array.prototype.slice.call(this.table.querySelectorAll("td")).filter(function (td) {
      var r = Number(td.dataset.r), c = Number(td.dataset.c);
      return r >= sel.r1 && r <= sel.r2 && c >= sel.c1 && c <= sel.c2;
    });
    if (!tds.length) return;
    var left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    tds.forEach(function (td) {
      var rect = td.getBoundingClientRect();
      left = Math.min(left, rect.left);
      top = Math.min(top, rect.top);
      right = Math.max(right, rect.right);
      bottom = Math.max(bottom, rect.bottom);
    });
    if (!box) {
      box = document.createElement("div");
      box.className = "nbt-selection";
      box.setAttribute("aria-hidden", "true");
      scroll.appendChild(box);
    }
    var origin = scroll.getBoundingClientRect();
    box.style.left = left - origin.left + scroll.scrollLeft - 1 + "px";
    box.style.top = top - origin.top + scroll.scrollTop - 1 + "px";
    box.style.width = right - left + 1 + "px";
    box.style.height = bottom - top + 1 + "px";
  };

  window.addEventListener("resize", function () {
    var tables = document.querySelectorAll(".nbt");
    tables.forEach(function (el) { el.dispatchEvent(new Event("nbt-relayout")); });
  });

  NotebookTable.prototype.hideBar = function () {
    if (this.bar) {
      if (this.barEntry) window.NotebookFloating.release(this.barEntry);
      this.bar.remove();
      this.bar = null;
      this.barEntry = null;
    }
  };

  // The selection bar: shown only while a rectangle of cells is selected, with icon buttons.
  NotebookTable.prototype.showBar = function () {
    var self = this;
    this.hideBar();
    var sel = this.sel;
    if (!sel || (sel.r1 === sel.r2 && sel.c1 === sel.c2 && !M.mergeAt(this.model.merges, sel.r1, sel.c1))) return;
    var bar = document.createElement("div");
    bar.className = "nbt-bar";
    bar.contentEditable = "false";
    var hasMerge = this.model.merges.some(function (m) {
      return !(m.r + m.rs - 1 < sel.r1 || m.r > sel.r2 || m.c + m.cs - 1 < sel.c1 || m.c > sel.c2);
    });
    function btn(label, icon, onClick) {
      var b = document.createElement("button");
      b.type = "button";
      b.title = label;
      b.setAttribute("aria-label", label);
      b.innerHTML = icon;
      b.addEventListener("mousedown", function (e) { e.preventDefault(); });
      b.addEventListener("click", onClick);
      bar.appendChild(b);
      return b;
    }
    if (sel.r1 !== sel.r2 || sel.c1 !== sel.c2) {
      btn("Merge cells", ICONS.merge, function () {
        self.syncFromDom();
        self.apply(Object.assign({}, self.model, { merges: M.merge(self.model.merges, sel.r1, sel.c1, sel.r2, sel.c2) }), { r: sel.r1, c: sel.c1 });
      });
    }
    if (hasMerge) {
      btn("Split cells", ICONS.split, function () {
        self.apply(Object.assign({}, self.model, { merges: M.split(self.model.merges, sel.r1, sel.c1, sel.r2, sel.c2) }), { r: sel.r1, c: sel.c1 });
      });
    }
    var colorBtn = btn("Color", ICONS.palette, function () {
      self.openMenu(colorBtn, self.colorItems());
    });
    btn("Clear cells", ICONS.clear, function () {
      self.syncFromDom();
      for (var r = sel.r1; r <= sel.r2; r++) {
        for (var c = sel.c1; c <= sel.c2; c++) self.model.content[r][c] = "";
      }
      self.build();
      self.changed();
    });
    this.wrapper.appendChild(bar);
    this.bar = bar;
    this.barEntry = window.NotebookFloating.open(bar, function () { self.clearSelection(); });
    var first = this.table.querySelector('td[data-r="' + sel.r1 + '"][data-c="' + sel.c1 + '"]');
    if (first) {
      var box = this.wrapper.getBoundingClientRect();
      var rect = first.getBoundingClientRect();
      bar.style.top = Math.max(0, rect.top - box.top - 38) + "px";
      bar.style.left = Math.max(0, rect.left - box.left) + "px";
    }
  };

  NotebookTable.prototype.colorItems = function () {
    var self = this;
    var sel = this.sel;
    function paint(kind, color) {
      if (!sel) return;
      for (var r = sel.r1; r <= sel.r2; r++) {
        for (var c = sel.c1; c <= sel.c2; c++) {
          var key = r + "," + c;
          var entry = Object.assign({}, self.model.colors[key]);
          if (color) entry[kind] = color;
          else delete entry[kind];
          if (entry.text || entry.bg) self.model.colors[key] = entry;
          else delete self.model.colors[key];
        }
      }
      self.clearSelection();
      self.refresh();
      self.changed();
    }
    function list(kind) {
      return [{ label: "None", icon: colorDot("", kind), onClick: function () { paint(kind, ""); } }].concat(
        COLORS.map(function (color) {
          return { label: color.charAt(0).toUpperCase() + color.slice(1), icon: colorDot(color, kind), onClick: function () { paint(kind, color); } };
        })
      );
    }
    return [
      { label: "Text color", icon: ICONS.textColor, children: list("text") },
      { label: "Background", icon: ICONS.fill, children: list("bg") },
    ];
  };

  // ---- Small menus for grips and the selection bar ------------------------------------------
  NotebookTable.prototype.closeMenu = function () {
    var self = this;
    document.querySelectorAll(".nbt-menu").forEach(function (m) {
      if (m._entry) window.NotebookFloating.release(m._entry);
      m.remove();
    });
  };

  NotebookTable.prototype.openMenu = function (anchor, items, level, bar, below) {
    var self = this;
    level = level || 0;
    var existing = this.menuEntries[level];
    if (existing && existing.opener === anchor && document.body.contains(existing.el)) {
      this.closeMenu();
      return;
    }
    document.querySelectorAll(".nbt-menu").forEach(function (m) {
      if (Number(m.dataset.level) >= level) {
        if (m._entry) window.NotebookFloating.release(m._entry);
        m.remove();
      }
    });
    var menu = document.createElement("div");
    menu.className = "nbt-menu" + (bar ? " nbt-menu-bar" : "");
    menu.dataset.level = level;
    menu.setAttribute("role", "menu");
    items.forEach(function (item) {
      if (item.sep) {
        var sep = document.createElement("span");
        sep.className = "nb-actions-sep";
        menu.appendChild(sep);
        return;
      }
      if (item.heading) {
        var h = document.createElement("div");
        h.className = "nbt-menu-heading";
        h.textContent = item.heading;
        menu.appendChild(h);
        return;
      }
      var b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "menuitem");
      var icon = document.createElement("span");
      icon.className = "nbt-menu-icon";
      icon.innerHTML = item.icon || "";
      b.appendChild(icon);
      if (bar) {
        b.title = item.disabled && item.hint ? item.hint : item.label;
        b.setAttribute("aria-label", item.label);
      } else {
        var label = document.createElement("span");
        label.className = "nbt-menu-label";
        label.textContent = item.label;
        b.appendChild(label);
      }
      if (item.children) {
        var chev = document.createElement("span");
        chev.className = "nbt-menu-chevron";
        chev.innerHTML = bar ? ICONS.down : ICONS.right;
        b.appendChild(chev);
      }
      if (item.active) b.classList.add("is-active");
      if (item.disabled) {
        b.disabled = true;
        if (item.hint && !bar) b.title = item.hint;
      } else if (item.children) {
        b.addEventListener("click", function () {
          self.openMenu(b, item.children, level + 1, false, bar);
        });
      } else {
        b.addEventListener("click", function () {
          self.closeMenu();
          item.onClick();
        });
      }
      menu.appendChild(b);
    });
    var rect = anchor.getBoundingClientRect();
    menu.style.position = "fixed";
    document.body.appendChild(menu);
    var parent = level ? self.menuEntries[level - 1] : (anchor.closest(".nbt-bar") ? self.barEntry : null);
    menu._entry = window.NotebookFloating.open(menu, function () {
      menu.remove();
    }, parent, anchor);
    self.menuEntries = (self.menuEntries || []).slice(0, level);
    self.menuEntries[level] = menu._entry;
    var width = menu.offsetWidth;
    var height = menu.offsetHeight;
    var side = level && !below;
    var left = side ? rect.right + 4 : rect.left;
    var top = side ? rect.top - 4 : rect.bottom + 4;
    if (left + width > window.innerWidth - 8) left = side ? rect.left - width - 4 : window.innerWidth - width - 8;
    if (top + height > window.innerHeight - 8) top = Math.max(8, window.innerHeight - height - 8);
    menu.style.left = Math.max(8, left) + "px";
    menu.style.top = top + "px";
  };

  NotebookTable.prototype.columnItems = function (c) {
    var self = this;
    var model = this.model;
    var cols = M.colCount(model.content);
    var align = model.align[c] || "";
    var isHeaderColumn = this.opts.headerColumn && c === 0;
    function setAlign(value) {
      return function () {
        var next = Object.assign({}, model.align);
        if (value) next[c] = value;
        else delete next[c];
        model.align = next;
        self.numericCols = null;
        self.refresh();
        self.changed();
      };
    }
    function reorder(to) {
      self.syncFromDom();
      var content = model.content.map(function (row) {
        var copy = row.slice();
        var cell = copy.splice(c, 1)[0];
        copy.splice(to, 0, cell);
        return copy;
      });
      self.apply({ content: content, merges: [], align: {}, colors: {} }, { r: 0, c: to });
    }
    var sortable = M.canSort(model) && !isHeaderColumn;
    var hint = isHeaderColumn
      ? "The header column labels the rows, so it is not sorted."
      : "Sorting is off while the table has merged cells or formulas.";
    function sortBy(dir) {
      return function () {
        self.syncFromDom();
        var values = M.evaluate(model.content, model.merges);
        var order = M.sortedOrder(values, c, dir, self.opts.withHeadings ? 1 : 0);
        var content = order.map(function (r) { return model.content[r]; });
        self.apply({ content: content, merges: model.merges, align: model.align, colors: {} }, { r: 0, c: c });
      };
    }
    var moveHint = "Moving is off while the table has merged cells.";
    function alignIcon(v) { return v === "left" ? ICONS.alignLeft : v === "center" ? ICONS.alignCenter : v === "right" ? ICONS.alignRight : ICONS.alignAuto; }
    return [
      { label: "Insert", icon: ICONS.insertBefore, children: [
        { label: "Insert column left", icon: ICONS.left, onClick: function () { self.syncFromDom(); self.apply(M.insertCol(model, c), { r: 0, c: c }); } },
        { label: "Insert column right", icon: ICONS.right, onClick: function () { self.syncFromDom(); self.apply(M.insertCol(model, c + 1), { r: 0, c: c + 1 }); } },
      ] },
      { label: "Align", icon: alignIcon(align), children: [
        { label: "Automatic", icon: ICONS.alignAuto, active: !align, onClick: setAlign("") },
        { label: "Left", icon: ICONS.alignLeft, active: align === "left", onClick: setAlign("left") },
        { label: "Center", icon: ICONS.alignCenter, active: align === "center", onClick: setAlign("center") },
        { label: "Right", icon: ICONS.alignRight, active: align === "right", onClick: setAlign("right") },
      ] },
      { label: "Sort", icon: ICONS.sortAsc, disabled: !sortable, hint: hint, children: [
        { label: "Sort ascending", icon: ICONS.sortAsc, onClick: sortBy("asc") },
        { label: "Sort descending", icon: ICONS.sortDesc, onClick: sortBy("desc") },
      ] },
      { sep: true },
      { label: "Move left", icon: ICONS.left, disabled: c === 0 || !!model.merges.length, hint: moveHint, onClick: function () { reorder(c - 1); } },
      { label: "Move right", icon: ICONS.right, disabled: c >= cols - 1 || !!model.merges.length, hint: moveHint, onClick: function () { reorder(c + 1); } },
      { sep: true },
      { label: "Delete column", icon: ICONS.trash, disabled: cols <= 1, onClick: function () { self.syncFromDom(); self.apply(M.deleteCol(model, c), { r: 0, c: Math.max(0, c - 1) }); } },
    ];
  };

  NotebookTable.prototype.rowItems = function (r) {
    var self = this;
    var model = this.model;
    var rows = model.content.length;
    function reorder(to) {
      self.syncFromDom();
      var content = model.content.slice();
      var row = content.splice(r, 1)[0];
      content.splice(to, 0, row);
      self.apply({ content: content, merges: [], align: model.align, colors: {} }, { r: to, c: 0 });
    }
    var moveHint = "Moving is off while the table has merged cells.";
    return [
      { label: "Insert", icon: ICONS.insertBefore, children: [
        { label: "Insert row above", icon: ICONS.up, onClick: function () { self.syncFromDom(); self.apply(M.insertRow(model, r), { r: r, c: 0 }); } },
        { label: "Insert row below", icon: ICONS.down, onClick: function () { self.syncFromDom(); self.apply(M.insertRow(model, r + 1), { r: r + 1, c: 0 }); } },
      ] },
      { sep: true },
      { label: "Move up", icon: ICONS.up, disabled: r === 0 || !!model.merges.length, hint: moveHint, onClick: function () { reorder(r - 1); } },
      { label: "Move down", icon: ICONS.down, disabled: r >= rows - 1 || !!model.merges.length, hint: moveHint, onClick: function () { reorder(r + 1); } },
      { sep: true },
      { label: "Delete row", icon: ICONS.trash, disabled: rows <= 1, onClick: function () { self.syncFromDom(); self.apply(M.deleteRow(model, r), { r: Math.max(0, r - 1), c: 0 }); } },
    ];
  };

  // ---- Events ------------------------------------------------------------------------------
  NotebookTable.prototype.wire = function () {
    var self = this;
    var w = this.wrapper;

    w.addEventListener("nbt-relayout", function () { self.updateSelectionClasses(); });

    w.addEventListener("focusin", function (e) {
      var cell = e.target.closest && e.target.closest(".nbt-cell");
      if (!cell) return;
      var pos = self.position(cell);
      var raw = self.model.content[pos.r][pos.c];
      if (M.isFormula(raw)) {
        lockWidth(cell);
        if (cell.textContent !== M.stripHtml(raw)) cell.textContent = M.stripHtml(raw);
      }
    });

    w.addEventListener("focusout", function (e) {
      var cell = e.target.closest && e.target.closest(".nbt-cell");
      if (!cell) return;
      unlockWidth(cell);
      setTimeout(function () {
        self.syncFromDom();
        var pos = self.position(cell);
        var raw = M.stripHtml(cell.innerHTML);
        if (raw.charAt(0) === "=") self.model.content[pos.r][pos.c] = raw;
        self.numericCols = null;
        self.refresh();
      }, 0);
    });

    w.addEventListener("input", function (e) {
      var cell = e.target.closest && e.target.closest(".nbt-cell");
      if (!cell) return;
      var pos = self.position(cell);
      var text = M.stripHtml(cell.innerHTML);
      if (text.charAt(0) === "=") lockWidth(cell);
      self.model.content[pos.r][pos.c] = text.charAt(0) === "=" ? text : cell.innerHTML;
      self.scheduleRefresh();
    });

    w.addEventListener("keydown", function (e) {
      var cell = e.target.closest && e.target.closest(".nbt-cell");
      if (!cell) return;
      var pos = self.position(cell);
      var rows = self.model.content.length;
      var cols = M.colCount(self.model.content);
      if (e.key === "Tab") {
        e.preventDefault();
        var c = pos.c + (e.shiftKey ? -1 : 1), r = pos.r;
        if (c < 0) { r -= 1; c = cols - 1; }
        if (c >= cols) { r += 1; c = 0; }
        if (r >= rows) {
          self.syncFromDom();
          self.apply(M.insertRow(self.model, rows), { r: rows, c: 0 });
        } else if (r >= 0) {
          self.focusCell(r, c);
        }
      } else if (e.key === "Enter") {
        e.preventDefault();
        e.stopPropagation();
        if (e.shiftKey) return;
        // Enter confirms the cell and moves down; in the last row it just confirms.
        if (pos.r + 1 < rows) self.focusCell(pos.r + 1, pos.c);
        else self.focusCell(pos.r, pos.c, true);
      } else if (e.altKey && e.key.indexOf("Arrow") === 0) {
        e.preventDefault();
        var dr = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
        var dc = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        var nr = Math.max(0, Math.min(rows - 1, pos.r + dr)), nc = Math.max(0, Math.min(cols - 1, pos.c + dc));
        self.focusCell(nr, nc, dc < 0 || dr < 0);
      } else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !e.shiftKey) {
        var down = e.key === "ArrowDown";
        if (edgeOf(cell, down ? "end" : "start") && (down ? pos.r + 1 < rows : pos.r > 0)) {
          e.preventDefault();
          self.focusCell(pos.r + (down ? 1 : -1), pos.c, down ? false : true);
        } else if (edgeOf(cell, down ? "end" : "start") && window.notebookMoveToBlock) {
          // Past the last row (or before the first) the caret leaves the table for the next or previous block.
          if (window.notebookMoveToBlock(cell, down)) e.preventDefault();
        }
      } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        var right = e.key === "ArrowRight";
        if (edgeOf(cell, right ? "end" : "start") && (right ? pos.c + 1 < cols : pos.c > 0)) {
          e.preventDefault();
          self.focusCell(pos.r, pos.c + (right ? 1 : -1), !right);
        }
      } else if (e.key === "Escape") {
        self.clearSelection();
        self.closeMenu();
      }
    }, true);

    // Rectangle selection: drag across cells, or Shift+click to extend.
    var dragging = false;
    var pointing = false;
    w.addEventListener("mousedown", function (e) {
      if (e.target.closest(".nbt-bar, .nbt-grip, .nbt-edge")) return;
      var cell = e.target.closest(".nbt-cell");
      if (!cell) { self.clearSelection(); return; }
      var pos = self.position(cell);
      // While a formula is being typed, clicking or dragging over cells inserts their reference.
      var active = document.activeElement;
      if (active && active !== cell && active.classList && active.classList.contains("nbt-cell") && w.contains(active) && self.canPoint(active)) {
        e.preventDefault();
        self.startPoint(active, pos);
        pointing = true;
        return;
      }
      if (e.shiftKey && self.anchor) {
        e.preventDefault();
        self.setSelection(self.anchor, pos);
        return;
      }
      self.anchor = pos;
      self.clearSelection();
      self.anchor = pos;
      dragging = true;
    });
    w.addEventListener("mouseover", function (e) {
      if (pointing) {
        var over = e.target.closest && e.target.closest(".nbt-cell");
        if (over && self.point) self.setPointRef(self.point.anchor, self.position(over));
        return;
      }
      if (!dragging) return;
      var cell = e.target.closest && e.target.closest(".nbt-cell");
      if (!cell) return;
      var pos = self.position(cell);
      if (pos.r === self.anchor.r && pos.c === self.anchor.c && !self.sel) return;
      window.getSelection().removeAllRanges();
      self.setSelection(self.anchor, pos);
    });
    document.addEventListener("mouseup", function () { dragging = false; pointing = false; });

    w.addEventListener("click", function (e) {
      var grip = e.target.closest(".nbt-grip");
      if (grip) {
        var index = Number(grip.dataset.index);
        self.openMenu(grip, grip.classList.contains("nbt-grip-col") ? self.columnItems(index) : self.rowItems(index), 0, true);
        return;
      }
      var edge = e.target.closest(".nbt-edge");
      if (edge) {
        self.syncFromDom();
        if (edge.classList.contains("nbt-edge-row")) {
          self.apply(M.insertRow(self.model, self.model.content.length), { r: self.model.content.length, c: 0 });
        } else {
          var cols = M.colCount(self.model.content);
          self.apply(M.insertCol(self.model, cols), { r: 0, c: cols });
        }
      }
    });

    // Pasting a spreadsheet range or a markdown table fills the grid from the focused cell.
    w.addEventListener("paste", function (e) {
      var cell = e.target.closest && e.target.closest(".nbt-cell");
      if (!cell || !e.clipboardData) return;
      var text = e.clipboardData.getData("text/plain");
      if (!text) return;
      var grid = M.markdownTableToGrid(text);
      if (!grid && M.looksLikeTsv(text)) grid = M.tsvToGrid(text);
      e.preventDefault();
      e.stopPropagation();
      if (!grid) {
        var plain = text.replace(/\s*\n\s*/g, " ");
        document.execCommand("insertText", false, plain);
        return;
      }
      var pos = self.position(cell);
      self.syncFromDom();
      var content = clone(self.model.content);
      var cols = M.colCount(content);
      grid.forEach(function (row, dr) {
        while (content.length <= pos.r + dr) content.push(new Array(cols).fill(""));
        row.forEach(function (value, dc) {
          while (M.colCount(content) <= pos.c + dc) content.forEach(function (line) { line.push(""); });
          content[pos.r + dr][pos.c + dc] = value;
        });
      });
      self.apply({ content: content, merges: self.model.merges, align: self.model.align, colors: self.model.colors }, { r: pos.r, c: pos.c });
    }, true);

    // The selection and its bar are short-lived: typing, Escape, an action, or the pointer leaving
    // the table (with no menu open) ends them.
    var leaveTimer = null;
    w.addEventListener("mouseleave", function () {
      if (!self.sel) return;
      clearTimeout(leaveTimer);
      leaveTimer = setTimeout(function () {
        if (!document.querySelector(".nbt-menu")) self.clearSelection();
      }, 700);
    });
    w.addEventListener("mouseenter", function () {
      clearTimeout(leaveTimer);
    });
    w.addEventListener("keydown", function (e) {
      if (self.sel && !e.ctrlKey && !e.metaKey && !["Shift", "Control", "Alt", "Meta"].includes(e.key)) self.clearSelection();
    }, true);

    // Copying a selected rectangle, or the whole table when its block is selected, gives Markdown.
    document.addEventListener("copy", function (e) {
      if (!w.isConnected) return;
      var blockSelected = !!w.closest(".ce-block--selected");
      var textSelected = window.getSelection().toString().length > 0 && !self.sel && !blockSelected;
      if (textSelected || (!self.sel && !blockSelected)) return;
      self.syncFromDom();
      var values = M.evaluate(self.model.content, self.model.merges);
      var rows = values;
      if (self.sel) {
        rows = values.slice(self.sel.r1, self.sel.r2 + 1).map(function (row) {
          return row.slice(self.sel.c1, self.sel.c2 + 1);
        });
      }
      e.preventDefault();
      e.clipboardData.setData("text/plain", M.toMarkdown(rows));
    });
  };

  // A formula being edited is often longer than its column; it scrolls inside the cell instead of
  // widening the table.
  function lockWidth(cell) {
    if (cell.dataset.locked) return;
    var td = cell.closest("td");
    cell.dataset.locked = "1";
    cell.style.maxWidth = td.offsetWidth + "px";
    cell.style.whiteSpace = "nowrap";
    cell.style.overflowX = "auto";
  }

  function unlockWidth(cell) {
    if (!cell.dataset.locked) return;
    delete cell.dataset.locked;
    cell.style.maxWidth = "";
    cell.style.whiteSpace = "";
    cell.style.overflowX = "";
  }

  // True when the caret sits at the very start or end of a cell's text.
  function edgeOf(cell, which) {
    var sel = window.getSelection();
    if (!sel.rangeCount || !sel.isCollapsed) return false;
    var probe = document.createRange();
    probe.selectNodeContents(cell);
    probe.collapse(which === "start");
    var range = sel.getRangeAt(0);
    return range.compareBoundaryPoints(Range.START_TO_START, probe) === 0 || edgeByText(cell, range, which);
  }

  function edgeByText(cell, range, which) {
    var pre = document.createRange();
    pre.selectNodeContents(cell);
    if (which === "start") pre.setEnd(range.startContainer, range.startOffset);
    else pre.setStart(range.endContainer, range.endOffset);
    return pre.toString().length === 0;
  }

  // ---- Pointing at cells while typing a formula -----------------------------------------------
  function caretOffset(cell) {
    var sel = window.getSelection();
    if (!sel.rangeCount) return cell.textContent.length;
    var pre = document.createRange();
    pre.selectNodeContents(cell);
    pre.setEnd(sel.getRangeAt(0).endContainer, sel.getRangeAt(0).endOffset);
    return pre.toString().length;
  }

  function setCaretOffset(cell, offset) {
    var node = cell.firstChild;
    var range = document.createRange();
    if (node) range.setStart(node, Math.min(offset, node.textContent.length));
    else range.setStart(cell, 0);
    range.collapse(true);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  // A reference may be inserted right after "=", an operator, "(" or ",", or in place of one just pointed at.
  NotebookTable.prototype.canPoint = function (cell) {
    var text = cell.textContent;
    if (text.charAt(0) !== "=") return false;
    var caret = caretOffset(cell);
    if (this.point && this.point.cell === cell && this.point.end === caret) return true;
    return "=+-*/(,:&<>".indexOf(text.charAt(caret - 1)) !== -1 && caret > 0;
  };

  NotebookTable.prototype.startPoint = function (cell, pos) {
    this.clearSelection();
    var text = cell.textContent;
    var caret = caretOffset(cell);
    var start = this.point && this.point.cell === cell && this.point.end === caret ? this.point.start : caret;
    var tail = this.point && this.point.cell === cell && this.point.end === caret ? this.point.tail : text.slice(caret);
    this.point = { cell: cell, start: start, end: start, head: text.slice(0, start), tail: tail, anchor: pos };
    this.setPointRef(pos, pos);
  };

  NotebookTable.prototype.setPointRef = function (a, b) {
    var point = this.point;
    if (!point) return;
    var r1 = Math.min(a.r, b.r), r2 = Math.max(a.r, b.r), c1 = Math.min(a.c, b.c), c2 = Math.max(a.c, b.c);
    var ref = r1 === r2 && c1 === c2 ? M.refText(r1, c1) : M.refText(r1, c1) + ":" + M.refText(r2, c2);
    point.cell.textContent = point.head + ref + point.tail;
    point.end = point.head.length + ref.length;
    setCaretOffset(point.cell, point.end);
    point.cell.dispatchEvent(new Event("input", { bubbles: true }));
  };

  // ---- Block menu --------------------------------------------------------------------------
  NotebookTable.prototype.renderSettings = function () {
    var self = this;
    function toggle(title, icon, key) {
      return {
        icon: icon,
        title: title,
        isActive: !!self.opts[key],
        closeOnActivate: true,
        onActivate: function () {
          self.syncFromDom();
          self.opts[key] = !self.opts[key];
          self.numericCols = null;
          self.build();
          self.changed();
        },
      };
    }
    function copy(title, icon, make, done) {
      return {
        icon: icon,
        title: title,
        closeOnActivate: true,
        onActivate: function () {
          self.syncFromDom();
          var values = M.evaluate(self.model.content, self.model.merges);
          navigator.clipboard.writeText(make(values)).then(function () {
            window.ccToast({ message: done });
          });
        },
      };
    }
    var bar = document.createElement("div");
    bar.className = "nb-actions-row";
    function tool(title, icon, active, onClick) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "nb-actions-btn";
      b.title = title;
      b.setAttribute("aria-label", title);
      b.innerHTML = icon;
      b.classList.toggle("is-active", !!active);
      b.addEventListener("click", onClick);
      bar.appendChild(b);
    }
    function flip(key) {
      return function () {
        self.syncFromDom();
        self.opts[key] = !self.opts[key];
        self.numericCols = null;
        self.build();
        self.changed();
        bar.querySelectorAll("button[data-opt]").forEach(function (x) { x.classList.toggle("is-active", !!self.opts[x.dataset.opt]); });
      };
    }
    [["Header row", ICONS.row, "withHeadings"], ["Header column", ICONS.col, "headerColumn"], ["Show cell references", ICONS.refs, "showRefs"],
      ["Compact", ICONS.dense, "dense"], ["Striped rows", ICONS.stripes, "striped"]].forEach(function (t) {
      tool(t[0], t[1], self.opts[t[2]], flip(t[2]));
      bar.lastChild.dataset.opt = t[2];
    });
    var sep = document.createElement("span");
    sep.className = "nb-actions-sep";
    bar.appendChild(sep);
    // Markdown is what copying the selected block gives, so it leads; CSV is an export and goes last.
    function copyTool(title, icon, make, done) {
      tool(title, icon, false, function () {
        self.syncFromDom();
        navigator.clipboard.writeText(make(M.evaluate(self.model.content, self.model.merges))).then(function () {
          window.ccToast({ message: done });
        });
      });
    }
    copyTool("Copy as Markdown", ICONS.markdown, M.toMarkdown, "Copied as Markdown");
    copyTool("Export as CSV", ICONS.csv, M.toCsv, "Copied as CSV");
    return [{ type: "html", element: bar }];
  };

  window.NotebookTable = NotebookTable;
})();
