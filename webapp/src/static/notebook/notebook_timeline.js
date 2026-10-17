// The Timeline block: a vertical timeline of any length. Each entry is a bullet on the line with its title
// on the bullet's row and the description on the line below. Both are rich text.
// Enter moves from title to description and from description to a new entry, Tab and the arrow keys move
// between entries, Alt+Up or Alt+Down moves the entry, and Backspace on an empty entry removes it.
// Feature notes: curodav-notes/documentation/features/notebook-rework/writing.md.
(function () {
  function el(tag, cls, attrs) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (attrs) for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    return e;
  }

  var COLORS = window.NotebookPalette;

  function NotebookTimeline(params) {
    this.api = params.api;
    this.readOnly = params.readOnly;
    var d = params.data || {};
    var items = Array.isArray(d.items) && d.items.length ? d.items : [{ title: "", description: "", date: "" }];
    this.data = {
      showDates: !!d.showDates,
      color: COLORS.indexOf(d.color) !== -1 ? d.color : "",
      items: items.map(function (i) {
        return { title: String(i.title || ""), description: String(i.description || ""), date: String(i.date || "") };
      }),
    };
    this.wrapper = null;
  }
  NotebookTimeline.toolbox = {
    title: "Timeline",
    icon: '<svg class="icon" aria-hidden="true"><use href="#icon-git-commit"></use></svg>',
  };
  NotebookTimeline.enableLineBreaks = true;
  // Title and description are rich text (the inline toolbar works in them); the date stays plain.
  // Nested fields do not get the inline tools' rules merged in by Editor.js, so the allowed inline markup is listed here.
  var RICH = {
    br: true, b: true, i: true, s: true, sub: true, sup: true, a: { href: true, target: true, rel: true },
    mark: { class: true }, code: { class: "inline-code" }, data: { class: true, value: true, "data-kind": true },
    span: { class: "cdx-wikilink", "data-target-uid": true, "data-target-title": true, "data-target-note-type": true, "data-target-color": true, "data-target-icon": true },
  };
  NotebookTimeline.sanitize = { items: { title: RICH, description: RICH, date: {} } };

  NotebookTimeline.prototype.field = function (cls, placeholder, text) {
    var f = el("span", cls, { contenteditable: !this.readOnly, "data-placeholder": placeholder, spellcheck: "true" });
    if (cls === "nbtl-date") f.textContent = text;
    else f.innerHTML = text;
    return f;
  };

  // A hidden date must not stay editable: Editor.js reads the first editable field to place its block buttons.
  NotebookTimeline.prototype.showDate = function (date, shown) {
    date.hidden = !shown;
    if (!this.readOnly) date.setAttribute("contenteditable", shown ? "true" : "false");
  };

  NotebookTimeline.prototype.row = function (item) {
    var row = el("div", "nbtl-item");
    var date = this.field("nbtl-date", "Date", item.date);
    this.showDate(date, this.data.showDates);
    var bullet = el("span", "nbtl-bullet", { "aria-hidden": "true" });
    var text = el("div", "nbtl-text");
    text.appendChild(this.field("nbtl-title", "Title", item.title));
    text.appendChild(this.field("nbtl-desc", "Description", item.description));
    row.appendChild(date);
    row.appendChild(bullet);
    row.appendChild(text);
    return row;
  };

  NotebookTimeline.prototype.render = function () {
    var self = this;
    var wrapper = el("div", "nbtl");
    this.wrapper = wrapper;
    this.applyLook();
    this.data.items.forEach(function (item) {
      wrapper.appendChild(self.row(item));
    });
    wrapper.addEventListener("keydown", function (e) {
      self.onKey(e);
    });
    wrapper.addEventListener("input", function () {
      self.touch();
    });
    this.wrapper = wrapper;
    return wrapper;
  };

  // Color and the date column are plain attributes and classes the stylesheet reads.
  NotebookTimeline.prototype.applyLook = function () {
    if (this.data.color) this.wrapper.setAttribute("data-color", this.data.color);
    else this.wrapper.removeAttribute("data-color");
    this.wrapper.classList.toggle("has-dates", !!this.data.showDates);
  };

  NotebookTimeline.prototype.touch = function () {
    var block = this.api.blocks.getBlockByElement ? this.api.blocks.getBlockByElement(this.wrapper) : null;
    if (block && block.dispatchChange) block.dispatchChange();
  };

  NotebookTimeline.prototype.rows = function () {
    return Array.prototype.slice.call(this.wrapper.querySelectorAll(".nbtl-item"));
  };

  function focusField(row, cls, atEnd) {
    var f = row.querySelector("." + cls);
    if (!f) return;
    f.focus();
    var range = document.createRange();
    range.selectNodeContents(f);
    range.collapse(!atEnd);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  NotebookTimeline.prototype.onKey = function (e) {
    var field = e.target.closest && e.target.closest(".nbtl-title, .nbtl-desc, .nbtl-date");
    if (!field) return;
    var row = field.closest(".nbtl-item");
    var rows = this.rows();
    var at = rows.indexOf(row);
    var cls = field.classList.contains("nbtl-title") ? "nbtl-title" : field.classList.contains("nbtl-desc") ? "nbtl-desc" : "nbtl-date";
    var undo = window.notebookUndo;
    var stop = function () { e.preventDefault(); e.stopPropagation(); };

    if (e.key === "Enter" && !e.shiftKey) {
      stop();
      if (cls !== "nbtl-desc") return focusField(row, cls === "nbtl-date" ? "nbtl-title" : "nbtl-desc", false);
      if (undo) undo.checkpoint();
      var fresh = this.row({ title: "", description: "", date: "" });
      row.after(fresh);
      focusField(fresh, "nbtl-title", false);
      this.touch();
      return;
    }
    if (e.key === "Backspace" && !field.textContent) {
      var other = row.querySelector(cls === "nbtl-title" ? ".nbtl-desc" : ".nbtl-title");
      if (cls === "nbtl-desc" || (cls === "nbtl-title" && !other.textContent)) {
        // An empty description goes back to the title; an empty entry is removed (the last one stays).
        if (cls === "nbtl-desc" && row.querySelector(".nbtl-title").textContent) {
          stop();
          return focusField(row, "nbtl-title", true);
        }
        if (rows.length > 1) {
          stop();
          if (undo) undo.checkpoint();
          var previous = rows[at - 1] || rows[at + 1];
          row.remove();
          focusField(previous, "nbtl-desc", true);
          this.touch();
        }
      }
      return;
    }
    if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      stop();
      var target = rows[e.key === "ArrowUp" ? at - 1 : at + 1];
      if (!target) return;
      if (undo) undo.checkpoint();
      if (e.key === "ArrowUp") target.before(row);
      else target.after(row);
      focusField(row, cls, true);
      this.touch();
      return;
    }
    if (e.key === "Tab") {
      var order = [];
      rows.forEach(function (r) {
        order.push([r, "nbtl-title"], [r, "nbtl-desc"]);
      });
      var here = order.findIndex(function (p) { return p[0] === row && p[1] === cls; });
      var next = order[here + (e.shiftKey ? -1 : 1)];
      if (next) {
        stop();
        focusField(next[0], next[1], false);
      }
      return;
    }
    if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !e.shiftKey && !e.altKey) {
      var neighbour = rows[e.key === "ArrowUp" ? at - 1 : at + 1];
      if (neighbour) {
        stop();
        focusField(neighbour, cls, e.key === "ArrowUp");
      } else if (window.notebookMoveToBlock && window.notebookMoveToBlock(row, e.key === "ArrowDown")) {
        stop();
      }
    }
  };

  NotebookTimeline.prototype.save = function () {
    var rich = function (f) { return f.textContent.trim() ? f.innerHTML.trim() : ""; };
    var items = this.rows().map(function (r) {
      return {
        title: rich(r.querySelector(".nbtl-title")),
        description: rich(r.querySelector(".nbtl-desc")),
        date: r.querySelector(".nbtl-date").textContent.trim(),
      };
    });
    return { showDates: this.data.showDates, color: this.data.color, items: items.length ? items : [{ title: "", description: "", date: "" }] };
  };

  NotebookTimeline.prototype.validate = function (data) {
    return data.items.some(function (i) { return i.title || i.description || i.date; });
  };

  // One row of icon buttons: the line color, then the dates switch.
  NotebookTimeline.prototype.renderSettings = function () {
    var self = this;
    var row = el("div", "nb-actions-row", { role: "group", "aria-label": "Timeline options" });
    function swatch(color, label) {
      var b = el("button", "nb-actions-btn nbtl-swatch", { type: "button", title: label, "aria-label": label + " color", "data-color": color });
      b.appendChild(el("span", "nbtl-swatch-dot"));
      b.classList.toggle("is-active", self.data.color === color);
      b.addEventListener("click", function () {
        window.notebookCommit(self.api, self.wrapper, function () {
          self.data.color = color;
          self.applyLook();
          row.querySelectorAll(".nbtl-swatch").forEach(function (x) { x.classList.toggle("is-active", x === b); });
        });
      });
      row.appendChild(b);
    }
    swatch("", "Neutral");
    COLORS.forEach(function (c) { swatch(c, c.charAt(0).toUpperCase() + c.slice(1)); });
    row.appendChild(el("span", "nb-actions-sep"));
    var dates = el("button", "nb-actions-btn", { type: "button", title: "Show dates", "aria-label": "Show dates" });
    dates.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#icon-calendar"></use></svg>';
    dates.classList.toggle("is-active", this.data.showDates);
    dates.addEventListener("click", function () {
      window.notebookCommit(self.api, self.wrapper, function () {
        self.data.showDates = !self.data.showDates;
        dates.classList.toggle("is-active", self.data.showDates);
        self.applyLook();
        self.rows().forEach(function (r) {
          self.showDate(r.querySelector(".nbtl-date"), self.data.showDates);
        });
      });
    });
    row.appendChild(dates);
    return { type: "html", element: row };
  };

  window.NotebookTimeline = NotebookTimeline;
})();
