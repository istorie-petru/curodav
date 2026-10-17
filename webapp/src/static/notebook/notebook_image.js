// Figure block for the Notebook editor (replaces the vendored SimpleImage): one or more images in a grid, a
// caption and source line, optional figure numbering. In the note the figure is read-only; the text, the
// grid and the images are edited in the block's Edit figure menu. The mouse drags the right edge to resize
// the figure and drags a picture onto another to reorder. Pictures are downscaled in the browser and kept in the
// image store (db/notebook.py); the note holds only their URL. Feature notes: curodav-notes/documentation/features/notebook-editor.md.
(function () {
  var MAX_IMAGES = 12;
  var MAX_COLUMNS = 4;
  var MIN_WIDTH = 20;
  var STEP = 5;
  var MAX_EDGE = 1600;
  var KEEP_BYTES = 400000;
    var TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"];

  function icon(name) {
    return '<svg class="icon" aria-hidden="true"><use href="#icon-' + name + '"></use></svg>';
  }

  function el(tag, cls, attrs) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (attrs) for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    return e;
  }

  function clamp(n, lo, hi) {
    return Math.max(lo, Math.min(hi, n));
  }

  function toast(message) {
    if (window.ccToast) window.ccToast({ message: message, variant: "error" });
  }

  // ---- Reading a picked file: validate, downscale, upload to the image store, return its URL ----
  function upload(blob) {
    return fetch("/notebook/images", { method: "POST", headers: { "X-Requested-With": "fetch" }, body: blob })
      .then(function (resp) {
        return resp.json().then(function (body) {
          if (!resp.ok) throw new Error(body.error || "The image could not be saved");
          return body.url;
        });
      });
  }

  function readFile(file) {
    return new Promise(function (resolve, reject) {
      if (TYPES.indexOf(file.type) === -1) return reject(new Error("Only JPEG, PNG, GIF and WebP images can be added"));
      var reader = new FileReader();
      reader.onerror = function () { reject(new Error("The image could not be read")); };
      reader.onload = function () {
        var img = new Image();
        img.onerror = function () { reject(new Error("The image could not be read")); };
        img.onload = function () {
          var longest = Math.max(img.naturalWidth, img.naturalHeight);
          var animated = file.type === "image/gif";
          if (animated || (longest <= MAX_EDGE && file.size <= KEEP_BYTES)) return upload(file).then(resolve, reject);
          var scale = Math.min(1, MAX_EDGE / longest);
          var canvas = document.createElement("canvas");
          canvas.width = Math.round(img.naturalWidth * scale);
          canvas.height = Math.round(img.naturalHeight * scale);
          canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
          canvas.toBlob(function (blob) {
            if (!blob) return reject(new Error("The image could not be read"));
            upload(blob).then(resolve, reject);
          }, "image/webp", 0.8);
        };
        img.src = reader.result;
      };
      reader.readAsDataURL(file);
    });
  }

  function altFromName(name) {
    return String(name || "").replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ").trim();
  }

  function pickFiles(multiple) {
    return new Promise(function (resolve) {
      var input = document.createElement("input");
      input.type = "file";
      input.accept = TYPES.join(",");
      input.multiple = !!multiple;
      input.addEventListener("change", function () { resolve(Array.prototype.slice.call(input.files || [])); });
      input.click();
    });
  }

  // Numbers the figures that ask for it, in document order.
  function renumber(root) {
    var n = 0;
    (root || document).querySelectorAll(".nb-fig").forEach(function (fig) {
      var label = fig.querySelector(".nb-fig__label");
      if (fig.getAttribute("data-numbered") === "true") {
        n += 1;
        label.textContent = "Figure " + n + ".";
        label.hidden = false;
      } else {
        label.textContent = "";
        label.hidden = true;
      }
    });
  }
  window.notebookRenumberFigures = renumber;

  function NotebookImage(params) {
    this.api = params.api;
    this.block = params.block;
    this.readOnly = params.readOnly;
    var d = params.data || {};
    var images = Array.isArray(d.images) ? d.images : d.url ? [{ src: d.url, alt: d.caption || "" }] : [];
    this.data = {
      images: images
        .filter(function (i) { return i && i.src; })
        .map(function (i) { return { src: String(i.src), alt: String(i.alt || "") }; }),
      columns: clamp(parseInt(d.columns, 10) || 1, 1, MAX_COLUMNS),
      width: clamp(parseInt(d.width, 10) || (d.stretched === false ? 60 : 100), MIN_WIDTH, 100),
      caption: String(d.caption || ""),
      credit: String(d.credit || ""),
      numbered: d.numbered === undefined ? false : !!d.numbered,
    };
    this.fig = null;
    this.panel = null;
  }
  NotebookImage.toolbox = { title: "Figure", icon: icon("image") };
  NotebookImage.sanitize = {};
  NotebookImage.prototype.willSelect = function () {};

  NotebookImage.prototype.undo = function () {
    return window.notebookUndo;
  };

  // One change = one undo step: close the history before, record the new state after.
  NotebookImage.prototype.change = function (mutate) {
    var undo = this.undo();
    if (undo) undo.checkpoint();
    mutate();
    this.paint();
    if (this.block && this.block.dispatchChange) this.block.dispatchChange();
    if (undo) setTimeout(function () { undo.checkpoint(); }, 80);
  };

  NotebookImage.prototype.render = function () {
    var self = this;
    this.fig = el("figure", "nb-fig");
    this.grid = el("div", "nb-fig__grid");
    this.empty = el("div", "nb-fig__empty");
    var add = el("button", "nb-fig__add", { type: "button" });
    add.innerHTML = icon("image") + "<span>Add images</span>";
    add.addEventListener("click", function () { self.addImages(); });
    this.empty.appendChild(add);
    this.handle = el("button", "nb-fig__handle", { type: "button", title: "Resize figure", "aria-label": "Resize figure" });
    this.handle.addEventListener("pointerdown", function (e) { self.startResize(e); });
    this.handle.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      var next = clamp(self.data.width + (e.key === "ArrowRight" ? STEP : -STEP), MIN_WIDTH, 100);
      if (next !== self.data.width) self.change(function () { self.data.width = next; });
    });
    this.cap = el("figcaption", "nb-fig__caption");
    this.label = el("span", "nb-fig__label");
    this.capText = el("span", "nb-fig__text");
    this.credit = el("span", "nb-fig__credit");
    this.cap.appendChild(this.label);
    this.cap.appendChild(this.capText);
    this.cap.appendChild(this.credit);
    this.fig.appendChild(this.grid);
    this.fig.appendChild(this.empty);
    this.fig.appendChild(this.handle);
    this.fig.appendChild(this.cap);
    this.fig.addEventListener("dragover", function (e) {
      if (self.dragFrom == null) return;
      e.preventDefault();
    });
    this.paint();
    return this.fig;
  };

  NotebookImage.prototype.paint = function () {
    var self = this;
    var d = this.data;
    var count = d.images.length;
    this.fig.setAttribute("data-numbered", d.numbered ? "true" : "false");
    this.fig.style.setProperty("--nb-fig-w", d.width + "%");
    this.fig.style.setProperty("--nb-fig-cols", String(Math.min(d.columns, Math.max(count, 1))));
    this.grid.hidden = !count;
    this.empty.hidden = !!count;
    this.handle.hidden = !count;
    var sig = this.signature();
    if (this.paintedSig === sig) return this.paintText();
    this.paintedSig = sig;
    this.grid.textContent = "";
    d.images.forEach(function (image, i) {
      var tile = el("div", "nb-fig__tile", { draggable: count > 1 ? "true" : "false" });
      var img = el("img", "nb-fig__img", { src: image.src, alt: image.alt, draggable: "false", loading: "lazy", decoding: "async" });
      tile.appendChild(img);
      tile.addEventListener("dragstart", function (e) {
        self.dragFrom = i;
        tile.classList.add("is-dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", "");
        e.stopPropagation();
      });
      tile.addEventListener("dragend", function () {
        self.dragFrom = null;
        self.grid.querySelectorAll(".is-over, .is-dragging").forEach(function (t) { t.classList.remove("is-over", "is-dragging"); });
      });
      tile.addEventListener("dragover", function (e) {
        if (self.dragFrom == null) return;
        e.preventDefault();
        tile.classList.add("is-over");
      });
      tile.addEventListener("dragleave", function () { tile.classList.remove("is-over"); });
      tile.addEventListener("drop", function (e) {
        if (self.dragFrom == null) return;
        e.preventDefault();
        e.stopPropagation();
        var from = self.dragFrom;
        self.dragFrom = null;
        if (from !== i) self.change(function () { d.images.splice(i, 0, d.images.splice(from, 1)[0]); });
      });
      self.grid.appendChild(tile);
    });
    this.paintText();
  };

  // Text, numbering and menu state change often; the pictures are only rebuilt when the images themselves change.
  NotebookImage.prototype.paintText = function () {
    var d = this.data;
    this.capText.textContent = d.caption;
    this.credit.textContent = d.credit;
    this.cap.hidden = !d.caption && !d.credit && !d.numbered;
    renumber(this.fig.closest("#notebook-editor") || document);
    if (this.panel) this.syncPanel();
  };

  NotebookImage.prototype.addImages = function (files) {
    var self = this;
    var room = MAX_IMAGES - this.data.images.length;
    if (room <= 0) return toast("A figure holds up to " + MAX_IMAGES + " images");
    var go = function (list) {
      if (!list.length) return;
      if (list.length > room) toast("Only the first " + room + " images were added");
      Promise.all(list.slice(0, room).map(function (f) {
        return readFile(f).then(function (src) { return { src: src, alt: altFromName(f.name) }; }, function (err) { toast(err.message); return null; });
      })).then(function (added) {
        added = added.filter(Boolean);
        if (!added.length) return;
        self.change(function () {
          self.data.images = self.data.images.concat(added);
          if (self.data.images.length > 1 && self.data.columns === 1 && added.length === self.data.images.length) {
            self.data.columns = Math.min(self.data.images.length, MAX_COLUMNS);
          }
        });
      });
    };
    if (files) go(files);
    else pickFiles(true).then(go);
  };

  NotebookImage.prototype.startResize = function (e) {
    var self = this;
    e.preventDefault();
    var holder = this.fig.parentElement;
    var span = holder.getBoundingClientRect().width;
    var left = this.fig.getBoundingClientRect().left;
    var start = this.data.width;
    var undo = this.undo();
    if (undo) undo.checkpoint();
    this.fig.classList.add("is-resizing");
    this.handle.setPointerCapture(e.pointerId);
    function move(ev) {
      var next = clamp(Math.round(((ev.clientX - left) / span) * 100 / STEP) * STEP, MIN_WIDTH, 100);
      self.data.width = next;
      self.fig.style.setProperty("--nb-fig-w", next + "%");
    }
    function up(ev) {
      self.handle.removeEventListener("pointermove", move);
      self.handle.removeEventListener("pointerup", up);
      self.handle.removeEventListener("pointercancel", up);
      if (self.handle.hasPointerCapture(ev.pointerId)) self.handle.releasePointerCapture(ev.pointerId);
      self.fig.classList.remove("is-resizing");
      if (self.data.width !== start) {
        if (self.block && self.block.dispatchChange) self.block.dispatchChange();
        if (undo) setTimeout(function () { undo.checkpoint(); }, 80);
      }
    }
    this.handle.addEventListener("pointermove", move);
    this.handle.addEventListener("pointerup", up);
    this.handle.addEventListener("pointercancel", up);
  };

  // ---- The Edit figure menu ----
  function field(labelText, control) {
    var wrap = el("div", "nb-fig-menu__field");
    var label = el("label", "nb-fig-menu__label");
    label.textContent = labelText;
    var id = "nb-fig-" + Math.random().toString(36).slice(2, 9);
    control.id = id;
    label.setAttribute("for", id);
    wrap.appendChild(label);
    wrap.appendChild(control);
    return wrap;
  }

  NotebookImage.prototype.textField = function (labelText, key, tag) {
    var self = this;
    var input = el(tag, "nb-fig-menu__input", tag === "textarea" ? { rows: "3" } : { type: "text" });
    input.value = this.data[key];
    var committed = input.value;
    input.addEventListener("focus", function () { committed = input.value; });
    input.addEventListener("input", function () {
      self.data[key] = input.value;
      self.paint();
    });
    input.addEventListener("change", function () {
      if (input.value === committed) return;
      var now = input.value;
      self.data[key] = committed;
      self.change(function () { self.data[key] = now; });
      committed = now;
    });
    return field(labelText, input);
  };

  NotebookImage.prototype.buildPanel = function () {
    var self = this;
    var panel = el("div", "nb-fig-menu");
    this.panel = panel;

    panel.appendChild(this.textField("Caption", "caption", "textarea"));
    panel.appendChild(this.textField("Source or credit", "credit", "input"));

    var number = el("div", "nb-fig-menu__switch");
    var sw = el("span", "switch");
    var box = el("input", null, { type: "checkbox", role: "switch" });
    sw.appendChild(box);
    sw.appendChild(el("span", "slider"));
    box.checked = this.data.numbered;
    box.addEventListener("change", function () { self.change(function () { self.data.numbered = box.checked; }); });
    number.appendChild(sw);
    var numberLabel = el("label", "nb-fig-menu__label");
    numberLabel.textContent = "Number this figure";
    var numberId = "nb-fig-" + Math.random().toString(36).slice(2, 9);
    box.id = numberId;
    numberLabel.setAttribute("for", numberId);
    number.appendChild(numberLabel);
    this.numberBox = box;
    panel.appendChild(number);

    var cols = el("div", "nb-fig-menu__field");
    var colsLabel = el("span", "nb-fig-menu__label");
    colsLabel.textContent = "Columns";
    cols.appendChild(colsLabel);
    var row = el("div", "nb-fig-menu__cols", { role: "group", "aria-label": "Columns" });
    for (var c = 1; c <= MAX_COLUMNS; c++) {
      (function (n) {
        var b = el("button", "cdx-settings-button nb-fig-menu__col", { type: "button", "data-cols": String(n) });
        b.textContent = String(n);
        b.addEventListener("click", function () { self.change(function () { self.data.columns = n; }); });
        row.appendChild(b);
      })(c);
    }
    cols.appendChild(row);
    this.colsRow = row;
    panel.appendChild(cols);

    this.list = el("div", "nb-fig-menu__images");
    panel.appendChild(this.list);

    var add = el("button", "cdx-settings-button nb-fig-menu__addbtn", { type: "button" });
    add.innerHTML = icon("plus") + "<span>Add images</span>";
    add.addEventListener("click", function () { self.addImages(); });
    panel.appendChild(add);
    this.syncPanel();
    return panel;
  };

  // Keeps the menu's column buttons and per-image rows in step with the data without rebuilding the text fields.
  NotebookImage.prototype.syncPanel = function () {
    var self = this;
    var d = this.data;
    this.numberBox.checked = d.numbered;
    this.colsRow.querySelectorAll("button").forEach(function (b) {
      b.classList.toggle("is-active", parseInt(b.getAttribute("data-cols"), 10) === d.columns);
    });
    if (this.list.childElementCount === d.images.length && this.list.getAttribute("data-built") === this.signature()) return;
    this.list.textContent = "";
    this.list.setAttribute("data-built", this.signature());
    d.images.forEach(function (image, i) {
      var row = el("div", "nb-fig-menu__image");
      var thumb = el("img", "nb-fig-menu__thumb", { src: image.src, alt: "" });
      var input = el("input", "nb-fig-menu__input", { type: "text" });
      input.value = image.alt;
      var committed = input.value;
      input.addEventListener("focus", function () { committed = input.value; });
      input.addEventListener("input", function () {
        image.alt = input.value;
        var img = self.grid.children[i] && self.grid.children[i].querySelector("img");
        if (img) img.alt = input.value;
      });
      input.addEventListener("change", function () {
        if (input.value === committed) return;
        var now = input.value;
        image.alt = committed;
        self.change(function () { image.alt = now; });
        committed = now;
      });
      var remove = el("button", "icon-btn nb-fig-menu__remove", { type: "button", title: "Remove image", "aria-label": "Remove image " + (i + 1) });
      remove.innerHTML = icon("trash");
      remove.addEventListener("click", function () { self.change(function () { d.images.splice(i, 1); }); });
      var wrap = field("Description of image " + (i + 1), input);
      wrap.classList.add("nb-fig-menu__grow");
      row.appendChild(thumb);
      row.appendChild(wrap);
      row.appendChild(remove);
      self.list.appendChild(row);
    });
  };

  NotebookImage.prototype.signature = function () {
    return this.data.images.map(function (i) { return i.src.length + ":" + i.src.slice(-12); }).join("|");
  };

  NotebookImage.prototype.renderSettings = function () {
    var self = this;
    return [
      {
        icon: icon("edit"),
        title: "Edit figure",
        toggle: "nb-fig-edit",
        children: { items: [{ type: "html", element: self.buildPanel() }] },
      },
    ];
  };

  NotebookImage.prototype.save = function () {
    var d = this.data;
    return {
      images: d.images.map(function (i) { return { src: i.src, alt: i.alt }; }),
      columns: d.columns,
      width: d.width,
      caption: d.caption.trim(),
      credit: d.credit.trim(),
      numbered: d.numbered,
    };
  };
  NotebookImage.prototype.validate = function (saved) {
    return saved.images.length > 0;
  };

  // Image files pasted or dropped on the editor become a figure.
  NotebookImage.pasteConfig = { files: { mimeTypes: TYPES } };
  NotebookImage.prototype.onPaste = function (event) {
    if (event.type !== "file" || !event.detail.file) return;
    this.addImages([event.detail.file]);
  };

  window.NotebookImage = NotebookImage;
})();
