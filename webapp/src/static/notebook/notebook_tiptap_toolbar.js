// The Notebook editor's toolbar (Tiptap editor): formatting, block type, inserts, and a second row for whatever is
// at the cursor (quote or timeline colour, callout type, table rows and columns, figure layout, link, text colour).
(function () {
  var COLORS = window.NotebookPalette || ["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "gray"];
  var CALLOUT_COLORS = { note: "blue", tip: "green", warning: "yellow", danger: "red", important: "purple" };
  var MAX_EDGE = 1600;
  var IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"];

  function el(tag, cls, attrs) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (attrs) for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    return e;
  }

  var glyphs = {};
  var CODE_LANGUAGES = [["plaintext", "Plain text"], ["javascript", "JavaScript"], ["typescript", "TypeScript"], ["python", "Python"], ["bash", "Bash / Shell"], ["json", "JSON"], ["yaml", "YAML"], ["sql", "SQL"], ["markup", "HTML / XML"], ["css", "CSS"], ["c", "C"], ["go", "Go"], ["markdown", "Markdown"]];

  function iconGlyph(name) {
    return '<span class="nbtb-glyph" aria-hidden="true">' + (glyphs[name] || "") + "</span>";
  }

  function toast(message) {
    if (window.ccToast) window.ccToast({ message: message, variant: "error" });
  }

  // Pictures are downscaled in the browser and kept in the image store; the note holds only the URL.
  function uploadImage(file) {
    return new Promise(function (resolve, reject) {
      if (IMAGE_TYPES.indexOf(file.type) === -1) return reject(new Error("Only JPEG, PNG, GIF and WebP images can be added"));
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error("The image could not be read")); };
      img.onload = function () {
        URL.revokeObjectURL(url);
        var longest = Math.max(img.naturalWidth, img.naturalHeight);
        function send(blob) {
          fetch("/notebook/images", { method: "POST", headers: { "X-Requested-With": "fetch" }, body: blob })
            .then(function (resp) { return resp.json().then(function (body) { if (!resp.ok) throw new Error(body.error || "The image could not be saved"); return body.url; }); })
            .then(resolve, reject);
        }
        if (file.type === "image/gif" || (longest <= MAX_EDGE && file.size <= 400000)) return send(file);
        var scale = Math.min(1, MAX_EDGE / longest);
        var canvas = document.createElement("canvas");
        canvas.width = Math.round(img.naturalWidth * scale);
        canvas.height = Math.round(img.naturalHeight * scale);
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(function (blob) { return blob ? send(blob) : reject(new Error("The image could not be read")); }, file.type === "image/png" ? "image/png" : "image/jpeg", 0.85);
      };
      img.src = url;
    });
  }

  function build(editor, mount, hooks) {
    try { glyphs = JSON.parse(mount.dataset.toolbarIcons || "{}"); } catch (e) { glyphs = {}; }
    var root = el("div", "nbtb");
    var rowOne = el("div", "nbtb-row");
    var rowTwo = el("div", "nbtb-row nbtb-context");
    var rowThree = el("div", "nbtb-row nbtb-context");
    rowTwo.hidden = true;
    rowThree.hidden = true;
    root.appendChild(rowOne);
    root.appendChild(rowTwo);
    root.appendChild(rowThree);
    var bar = document.querySelector(".page-header-rows");
    if (bar) bar.appendChild(root);
    else mount.parentNode.insertBefore(root, mount);
    var mode = null; // "link" | "color" | null
    var lastSig = "";
    var buttons = [];
    var files = el("input", null, { type: "file", accept: IMAGE_TYPES.join(","), multiple: "multiple", hidden: "hidden" });
    root.appendChild(files);

    function chain() { return editor.chain().focus(); }

    function button(parent, name, label, run, active) {
      var b = el("button", "icon-btn nbtb-btn", { type: "button", title: label, "aria-label": label });
      b.innerHTML = iconGlyph(name);
      b.addEventListener("mousedown", function (e) { e.preventDefault(); });
      b.addEventListener("click", run);
      parent.appendChild(b);
      if (active) buttons.push({ b: b, active: active });
      return b;
    }

    function text(parent, label, run, cls) {
      var b = el("button", "nbtb-text " + (cls || ""), { type: "button" });
      b.textContent = label;
      b.addEventListener("mousedown", function (e) { e.preventDefault(); });
      b.addEventListener("click", run);
      parent.appendChild(b);
      return b;
    }

    function group(parent) {
      var g = el("span", "nbtb-group");
      parent.appendChild(g);
      return g;
    }

    var menuCount = 0;

    function menuShell(triggerHtml, label, cls) {
      var wrap = el("div", "multiselect widget-list-multiselect nbtb-menu " + (cls || ""), { "data-ms": "", "data-ms-mode": "single", "data-ms-label": label });
      var trigger = el("button", "multiselect-trigger ms-trigger", { type: "button", "aria-haspopup": "true", "aria-expanded": "false", title: label, "aria-label": label });
      trigger.innerHTML = triggerHtml;
      trigger.addEventListener("mousedown", function (e) { e.preventDefault(); });
      var panel = el("div", "multiselect-panel ms-panel" + (cls === "nbtb-actions" ? " nbtb-panel-actions" : ""));
      wrap.appendChild(trigger);
      wrap.appendChild(panel);
      return { wrap: wrap, trigger: trigger, panel: panel, name: "nbtb-menu-" + (++menuCount) };
    }

    function option(shell, glyph, label, value) {
      var row = el("label", "multiselect-option");
      var radio = el("input", null, { type: "radio", name: shell.name, value: value });
      row.appendChild(radio);
      if (glyph) {
        var g = el("span", "nbtb-glyph");
        g.textContent = glyphs[glyph] || "";
        row.appendChild(g);
      }
      var span = el("span");
      span.textContent = label;
      row.appendChild(span);
      shell.panel.appendChild(row);
      return radio;
    }

    // The app's own single-choice dropdown, filled in by hand: the choice shows in the trigger.
    function dropdown(parent, label, items, onPick) {
      var shell = menuShell('<span class="ms-summary"></span><span class="filter-caret">' + iconGlyph("chevron-down") + "</span>", label, "filter-dropdown");
      shell.trigger.classList.add("filter-dropdown-trigger");
      var summary = shell.trigger.querySelector(".ms-summary");
      var radios = {};
      items.forEach(function (item) {
        var radio = option(shell, null, item[1], item[0]);
        radios[item[0]] = { radio: radio, label: item[1] };
        radio.addEventListener("change", function () { summary.textContent = item[1]; onPick(item[0]); });
      });
      parent.appendChild(shell.wrap);
      return {
        set: function (value) {
          var hit = radios[value];
          if (!hit) { summary.textContent = value; return; }
          hit.radio.checked = true;
          summary.textContent = hit.label;
        },
      };
    }

    // A button that opens a list of actions (nothing stays selected).
    function actionMenu(parent, glyph, label, items) {
      var shell = menuShell(iconGlyph(glyph), label, "nbtb-actions");
      shell.trigger.classList.add("icon-btn", "nbtb-btn");
      items.forEach(function (item) {
        var radio = option(shell, item[0], item[1], item[1]);
        radio.addEventListener("change", function () { radio.checked = false; setTimeout(item[2], 30); });
      });
      parent.appendChild(shell.wrap);
      return shell;
    }

    var STYLES = [
      ["paragraph", "Paragraph", function () { chain().setParagraph().run(); }],
      ["h1", "Heading 1", function () { chain().setHeading({ level: 1 }).run(); }],
      ["h2", "Heading 2", function () { chain().setHeading({ level: 2 }).run(); }],
      ["h3", "Heading 3", function () { chain().setHeading({ level: 3 }).run(); }],
      ["h4", "Heading 4", function () { chain().setHeading({ level: 4 }).run(); }],
      ["h5", "Heading 5", function () { chain().setHeading({ level: 5 }).run(); }],
      ["quote", "Quote", function () { chain().toggleBlockquote().run(); }],
      ["code", "Code block", function () { chain().toggleCodeBlock().run(); }],
    ];
    var blockSelect = null;

    var history = group(rowOne);
    button(history, "undo-2", "Undo", function () { chain().undo().run(); });
    button(history, "redo-2", "Redo", function () { chain().redo().run(); });
    blockSelect = dropdown(rowOne, "Text style", STYLES, function (value) {
      STYLES.forEach(function (s) { if (s[0] === value) s[2](); });
    });
    var marks = group(rowOne);
    button(marks, "bold", "Bold", function () { chain().toggleBold().run(); }, function () { return editor.isActive("bold"); });
    button(marks, "italic", "Italic", function () { chain().toggleItalic().run(); }, function () { return editor.isActive("italic"); });
    button(marks, "underline", "Underline", function () { chain().toggleUnderline().run(); }, function () { return editor.isActive("underline"); });
    button(marks, "strikethrough", "Strikethrough", function () { chain().toggleStrike().run(); }, function () { return editor.isActive("strike"); });
    button(marks, "code", "Inline code", function () { chain().toggleCode().run(); }, function () { return editor.isActive("code"); });
    button(marks, "subscript", "Subscript", function () { chain().toggleSubscript().run(); }, function () { return editor.isActive("subscript"); });
    button(marks, "superscript", "Superscript", function () { chain().toggleSuperscript().run(); }, function () { return editor.isActive("superscript"); });
    button(marks, "brackets", "Link to a note or entry", function () {
      chain().run();
      document.execCommand("insertText", false, "[[");
    });
    button(marks, "link", "Link", function () { mode = mode === "link" ? null : "link"; lastSig = ""; paintContext(); }, function () { return editor.isActive("link"); });
    button(marks, "palette", "Text colour", function () { mode = mode === "color" ? null : "color"; lastSig = ""; paintContext(); }, function () { return editor.isActive("textColor"); });
    button(marks, "eraser", "Clear formatting", function () { chain().unsetAllMarks().run(); });
    var lists = group(rowOne);
    button(lists, "list", "Bulleted list", function () { chain().toggleBulletList().run(); }, function () { return editor.isActive("bulletList"); });
    button(lists, "list-ordered", "Numbered list", function () { chain().toggleOrderedList().run(); }, function () { return editor.isActive("orderedList"); });
    button(lists, "list-checks", "Checklist", function () { chain().toggleTaskList().run(); }, function () { return editor.isActive("taskList"); });
    actionMenu(rowOne, "plus", "Add", [
      ["megaphone", "Callout", function () { chain().insertContent({ type: "callout", attrs: { type: "note" }, content: [{ type: "calloutTitle" }, { type: "calloutMessage" }] }).run(); }],
      ["git-commit-vertical", "Timeline", function () { chain().insertContent({ type: "timeline", content: [{ type: "timelineItem", content: [{ type: "timelineDate" }, { type: "timelineTitle" }, { type: "timelineDescription" }] }] }).run(); }],
      ["quote", "Quote", function () { chain().toggleBlockquote().run(); }],
      ["braces", "Code block", function () { chain().toggleCodeBlock().run(); }],
      ["minus", "Divider", function () { chain().setHorizontalRule().run(); }],
      ["table", "Table", function () { chain().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(); }],
      ["image", "Figure", function () { files.click(); }],
      ["hash", "Endnote", function () { hooks.insertEndnote(); }],
    ]);
    function topBlock() {
      var $from = editor.state.selection.$from;
      return $from.depth < 1 ? null : { index: $from.index(0), node: $from.node(1), pos: $from.before(1) };
    }

    function moveBlock(step) {
      var at = topBlock();
      var doc = editor.state.doc;
      if (!at || at.index + step < 0 || at.index + step >= doc.childCount) return;
      var other = doc.child(at.index + step);
      var start = at.pos;
      var tr = editor.state.tr;
      if (step < 0) {
        tr.delete(start, start + at.node.nodeSize).insert(start - other.nodeSize, at.node);
        tr.setSelection(editor.state.selection.constructor.near(tr.doc.resolve(start - other.nodeSize + 1)));
      } else {
        tr.insert(start + at.node.nodeSize + other.nodeSize, at.node).delete(start, start + at.node.nodeSize);
        tr.setSelection(editor.state.selection.constructor.near(tr.doc.resolve(start + other.nodeSize + 1)));
      }
      editor.view.dispatch(tr.scrollIntoView());
      editor.view.focus();
    }

    actionMenu(rowOne, "ellipsis", "Block actions", [
      ["arrow-up", "Move up", function () { moveBlock(-1); }],
      ["arrow-down", "Move down", function () { moveBlock(1); }],
      ["copy", "Duplicate", function () {
        var at = topBlock();
        if (at) chain().insertContentAt(at.pos + at.node.nodeSize, at.node.toJSON()).run();
      }],
      ["trash-2", "Delete block", function () {
        var at = topBlock();
        if (at) chain().deleteRange({ from: at.pos, to: at.pos + at.node.nodeSize }).run();
      }],
    ]);

    function addImages(list) {
      var picked = Array.prototype.slice.call(list).filter(function (f) { return f.type.indexOf("image/") === 0; });
      if (!picked.length) return;
      Promise.all(picked.map(uploadImage)).then(function (urls) {
        var images = urls.map(function (src) { return { src: src, alt: "" }; });
        var selected = figureNode();
        if (selected) {
          var data = Object.assign({}, selected.attrs.data);
          data.images = (data.images || []).concat(images).slice(0, 12);
          chain().updateAttributes("figure", { data: data }).run();
        } else {
          chain().insertContent({ type: "figure", attrs: { data: { images: images.slice(0, 12), columns: Math.min(images.length, 4), width: 100, caption: "", credit: "", numbered: false } } }).run();
        }
      }, function (err) { toast(err.message); });
    }
    files.addEventListener("change", function () { addImages(files.files); files.value = ""; });
    mount.addEventListener("paste", function (e) {
      var items = (e.clipboardData && e.clipboardData.files) || [];
      if (items.length && Array.prototype.some.call(items, function (f) { return f.type.indexOf("image/") === 0; })) {
        e.preventDefault();
        addImages(items);
      }
    }, true);
    mount.addEventListener("drop", function (e) {
      var dropped = (e.dataTransfer && e.dataTransfer.files) || [];
      if (dropped.length && Array.prototype.some.call(dropped, function (f) { return f.type.indexOf("image/") === 0; })) {
        e.preventDefault();
        addImages(dropped);
      }
    }, true);

    function ancestor(names) {
      var $from = editor.state.selection.$from;
      for (var d = $from.depth; d > 0; d--) {
        var node = $from.node(d);
        if (names.indexOf(node.type.name) !== -1) return node;
      }
      return null;
    }

    function figureNode() {
      var sel = editor.state.selection;
      return sel.node && sel.node.type.name === "figure" ? sel.node : null;
    }

    function swatches(parent, kind, onPick, current) {
      COLORS.forEach(function (color) {
        var b = el("button", "nb-color-swatch", { type: "button", "data-color": color, title: color, "aria-label": color });
        if (color === current) b.classList.add("nb-color-swatch--active");
        b.addEventListener("mousedown", function (e) { e.preventDefault(); });
        b.addEventListener("click", function () { onPick(color); });
        parent.appendChild(b);
      });
    }

    function field(parent, label, value, onInput) {
      var wrap = el("label", "nbtb-field");
      var span = el("span");
      span.textContent = label;
      var input = el("input", "nbtb-input", { type: "text", value: value || "" });
      input.addEventListener("input", function () { onInput(input.value); });
      wrap.appendChild(span);
      wrap.appendChild(input);
      parent.appendChild(wrap);
      return input;
    }

    function paintMode() {
      rowThree.replaceChildren();
      rowThree.hidden = true;
      if (mode === "link") {
        rowThree.hidden = false;
        var url = field(rowThree, "Link", (editor.getAttributes("link").href || ""), function () {});
        var apply = function () {
          var href = url.value.trim();
          if (href) chain().extendMarkRange("link").setLink({ href: href }).run();
          else chain().extendMarkRange("link").unsetLink().run();
          mode = null;
          lastSig = "";
          paintContext();
        };
        url.addEventListener("keydown", function (e) {
          if (e.key === "Enter") { e.preventDefault(); apply(); }
          if (e.key === "Escape") { e.preventDefault(); mode = null; lastSig = ""; paintContext(); editor.view.focus(); }
        });
        text(rowThree, "Apply", apply);
        text(rowThree, "Remove", function () { chain().extendMarkRange("link").unsetLink().run(); mode = null; lastSig = ""; paintContext(); });
        setTimeout(function () { url.focus(); }, 0);
      } else if (mode === "color") {
        rowThree.hidden = false;
        [["tc", "Text"], ["hl", "Highlight"]].forEach(function (kind) {
          var label = el("span", "nbtb-label");
          label.textContent = kind[1];
          rowThree.appendChild(label);
          swatches(rowThree, kind[0], function (color) { chain().setMark("textColor", { class: "nb-" + kind[0] + "-" + color }).run(); });
        });
        text(rowThree, "None", function () { chain().unsetMark("textColor").run(); });
      }
    }

    function paintContext() {
      paintMode();
      rowTwo.replaceChildren();
      rowTwo.hidden = true;
      var show = function () { rowTwo.hidden = false; };
      var codeBlock = ancestor(["codeBlock"]);
      if (codeBlock) {
        show();
        dropdown(rowTwo, "Language", CODE_LANGUAGES, function (value) { chain().updateAttributes("codeBlock", { language: value }).run(); }).set(codeBlock.attrs.language || "plaintext");
        return;
      }
      var figure = figureNode();
      if (figure) {
        show();
        var data = figure.attrs.data || {};
        var set = function (patch) { chain().updateAttributes("figure", { data: Object.assign({}, data, patch) }).run(); };
        var label = el("span", "nbtb-label");
        label.textContent = "Columns";
        rowTwo.appendChild(label);
        [1, 2, 3, 4].forEach(function (n) { text(rowTwo, String(n), function () { set({ columns: n }); }, (data.columns || 1) === n ? "is-active" : ""); });
        text(rowTwo, "Narrower", function () { set({ width: Math.max(20, (data.width || 100) - 10) }); });
        text(rowTwo, "Wider", function () { set({ width: Math.min(100, (data.width || 100) + 10) }); });
        text(rowTwo, data.numbered ? "Numbered" : "Not numbered", function () { set({ numbered: !data.numbered }); }, data.numbered ? "is-active" : "");
        text(rowTwo, "Add pictures", function () { files.click(); });
        field(rowTwo, "Caption", (data.caption || "").replace(/<[^>]+>/g, ""), function (v) { set({ caption: v }); });
        field(rowTwo, "Source", (data.credit || "").replace(/<[^>]+>/g, ""), function (v) { set({ credit: v }); });
        return;
      }
      var callout = ancestor(["callout"]);
      if (callout) {
        show();
        Object.keys(CALLOUT_COLORS).forEach(function (type) {
          var b = el("button", "nb-type-swatch nb-color-swatch", { type: "button", "data-color": CALLOUT_COLORS[type], title: type, "aria-label": type });
          if (callout.attrs.type === type) b.classList.add("nb-color-swatch--active");
          b.addEventListener("mousedown", function (e) { e.preventDefault(); });
          b.addEventListener("click", function () { chain().updateAttributes("callout", { type: type }).run(); });
          rowTwo.appendChild(b);
        });
        text(rowTwo, callout.attrs.hideTitle ? "Show title" : "Hide title", function () { chain().updateAttributes("callout", { hideTitle: !callout.attrs.hideTitle }).run(); });
        return;
      }
      var timeline = ancestor(["timeline"]);
      var quote = ancestor(["blockquote"]);
      if (timeline || quote) {
        show();
        var name = timeline ? "timeline" : "blockquote";
        var node = timeline || quote;
        swatches(rowTwo, "color", function (color) { chain().updateAttributes(name, { color: color }).run(); }, node.attrs.color);
        if (quote && !timeline && !quote.lastChild.type.name.match(/quoteCaption/)) {
          text(rowTwo, "Add source", function () {
            var $from = editor.state.selection.$from;
            for (var d = $from.depth; d > 0; d--) {
              if ($from.node(d).type.name !== "blockquote") continue;
              var end = $from.end(d);
              chain().insertContentAt(end, { type: "quoteCaption" }).setTextSelection(end + 1).run();
              return;
            }
          });
        }
        if (timeline) text(rowTwo, timeline.attrs.showDates ? "Hide dates" : "Show dates", function () { chain().updateAttributes("timeline", { showDates: !timeline.attrs.showDates }).run(); });
        return;
      }
      if (ancestor(["table"])) {
        show();
        actionMenu(rowTwo, "table-properties", "Table", [
          ["plus", "Row above", function () { chain().addRowBefore().run(); }], ["plus", "Row below", function () { chain().addRowAfter().run(); }], ["trash-2", "Delete row", function () { chain().deleteRow().run(); }],
          ["plus", "Column left", function () { chain().addColumnBefore().run(); }], ["plus", "Column right", function () { chain().addColumnAfter().run(); }], ["trash-2", "Delete column", function () { chain().deleteColumn().run(); }],
          ["table", "Header row", function () { chain().toggleHeaderRow().run(); }], ["trash-2", "Delete table", function () { chain().deleteTable().run(); }],
        ]);
      }
    }

    function refresh() {
      buttons.forEach(function (item) { item.b.classList.toggle("is-active", !!item.active()); });
      var value = "paragraph";
      if (editor.isActive("heading")) value = "h" + editor.getAttributes("heading").level;
      else if (editor.isActive("blockquote")) value = "quote";
      else if (editor.isActive("codeBlock")) value = "code";
      blockSelect.set(value);
      if (mode === "link" || document.querySelector(".multiselect-panel.is-open")) return;
      var sel = editor.state.selection;
      var sig = [mode, sel.node ? sel.node.type.name + JSON.stringify(sel.node.attrs) : ""];
      for (var d = sel.$from.depth; d > 0; d--) sig.push(sel.$from.node(d).type.name + JSON.stringify(sel.$from.node(d).attrs));
      sig = sig.join("|");
      if (sig === lastSig) return;
      lastSig = sig;
      paintContext();
    }
    editor.on("selectionUpdate", refresh);
    editor.on("transaction", function () { if (!root.contains(document.activeElement)) refresh(); });
    refresh();
  }

  window.NotebookTiptapToolbar = { build: build };
})();
