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
    // What the caret is in (table, timeline, callout, link, color) is shown on the same row as the other editing choices.
    var rowTwo = el("div", "nbtb-context");
    var rowThree = el("div", "nbtb-context");
    rowTwo.hidden = true;
    rowThree.hidden = true;
    root.appendChild(rowOne);
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

    // An icon button for the controls of what the caret is in; `on` marks it as switched on.
    function ibtn(parent, name, label, run, on) {
      var b = button(parent, name, label, run);
      if (on) b.classList.add("is-active");
      return b;
    }

    // A color chosen from a list, with the current one shown on the button.
    function colorMenu(parent, label, current, onPick, withNone) {
      var items = (withNone ? [["", "No color"]] : []).concat(COLORS.map(function (c) { return [c, c.charAt(0).toUpperCase() + c.slice(1)]; }));
      dropdown(parent, label, items, onPick).set(current === undefined ? label : current);
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
    function toggleList(name, toggle) {
      return function () { if (editor.isActive(name)) chain().unwrapList().run(); else chain()[toggle]().run(); };
    }
    button(lists, "list", "Bulleted list", toggleList("bulletList", "toggleBulletList"), function () { return editor.isActive("bulletList"); });
    button(lists, "list-ordered", "Numbered list", toggleList("orderedList", "toggleOrderedList"), function () { return editor.isActive("orderedList"); });
    button(lists, "list-checks", "Checklist", toggleList("taskList", "toggleTaskList"), function () { return editor.isActive("taskList"); });
    // Blocks are added from the slash menu in the editor; the editor tells the toolbar about the two that need its helpers.
    editor.view.dom.addEventListener("nb-add-figure", function () { files.click(); });
    editor.view.dom.addEventListener("nb-add-endnote", function () { hooks.insertEndnote(); });
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
        ibtn(rowThree, "check", "Apply link", apply);
        ibtn(rowThree, "unlink", "Remove link", function () { chain().extendMarkRange("link").unsetLink().run(); mode = null; lastSig = ""; paintContext(); });
        setTimeout(function () { url.focus(); }, 0);
      } else if (mode === "color") {
        rowThree.hidden = false;
        [["tc", "Text color"], ["hl", "Highlight"]].forEach(function (kind) {
          colorMenu(rowThree, kind[1], undefined, function (color) { chain().setMark("textColor", { class: "nb-" + kind[0] + "-" + color }).run(); });
        });
        ibtn(rowThree, "eraser", "No color", function () { chain().unsetMark("textColor").run(); });
      }
    }

    function layoutContext() {
      contextBreak.hidden = true;
      if (!root.classList.contains("has-context") || window.innerWidth <= 720) return;
      var own = Array.prototype.filter.call(rowOne.children, function (c) { return !c.hidden && c !== contextBreak && !c.classList.contains("nbtb-context") && c.offsetParent; });
      var ctx = Array.prototype.slice.call(rowTwo.children).concat(Array.prototype.slice.call(rowThree.children)).filter(function (c) { return c.offsetParent; });
      if (!own.length || !ctx.length) return;
      var first = own[0].getBoundingClientRect().top;
      var wrapped = ctx.some(function (c) { return c.getBoundingClientRect().top > first + 4; });
      contextBreak.hidden = !wrapped;
    }
    window.addEventListener("resize", layoutContext);
    if (window.ResizeObserver) new ResizeObserver(layoutContext).observe(rowOne);

    function paintContext() {
      paintContextRows();
      root.classList.toggle("has-context", !rowTwo.hidden || !rowThree.hidden);
      layoutContext();
      setTimeout(layoutContext, 60);
    }

    function paintContextRows() {
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
        ibtn(rowTwo, "minus", "Narrower", function () { set({ width: Math.max(20, (data.width || 100) - 10) }); });
        ibtn(rowTwo, "plus", "Wider", function () { set({ width: Math.min(100, (data.width || 100) + 10) }); });
        ibtn(rowTwo, "hash", data.numbered ? "Numbered figure" : "Not numbered", function () { set({ numbered: !data.numbered }); }, data.numbered);
        ibtn(rowTwo, "image", "Add pictures", function () { files.click(); });
        field(rowTwo, "Caption", (data.caption || "").replace(/<[^>]+>/g, ""), function (v) { set({ caption: v }); });
        field(rowTwo, "Source", (data.credit || "").replace(/<[^>]+>/g, ""), function (v) { set({ credit: v }); });
        return;
      }
      var callout = ancestor(["callout"]);
      if (callout) {
        show();
        dropdown(rowTwo, "Callout type", Object.keys(CALLOUT_COLORS).map(function (t) { return [t, t.charAt(0).toUpperCase() + t.slice(1)]; }), function (type) {
          chain().updateAttributes("callout", { type: type }).run();
        }).set(callout.attrs.type);
        ibtn(rowTwo, callout.attrs.hideTitle ? "eye-off" : "eye", callout.attrs.hideTitle ? "Show title" : "Hide title", function () { chain().updateAttributes("callout", { hideTitle: !callout.attrs.hideTitle }).run(); });
        return;
      }
      var timeline = ancestor(["timeline"]);
      var quote = ancestor(["blockquote"]);
      if (timeline || quote) {
        show();
        var name = timeline ? "timeline" : "blockquote";
        var node = timeline || quote;
        colorMenu(rowTwo, "Color", node.attrs.color || "", function (color) { chain().updateAttributes(name, { color: color }).run(); }, !!timeline);
        if (quote && !timeline && !quote.lastChild.type.name.match(/quoteCaption/)) {
          ibtn(rowTwo, "message-square-plus", "Add source", function () {
            var $from = editor.state.selection.$from;
            for (var d = $from.depth; d > 0; d--) {
              if ($from.node(d).type.name !== "blockquote") continue;
              var end = $from.end(d);
              chain().insertContentAt(end, { type: "quoteCaption" }).setTextSelection(end + 1).run();
              return;
            }
          });
        }
        if (timeline) {
          ibtn(rowTwo, timeline.attrs.showDates ? "calendar-off" : "calendar", timeline.attrs.showDates ? "Hide dates" : "Show dates", function () { chain().updateAttributes("timeline", { showDates: !timeline.attrs.showDates }).run(); });
          var itemDepth = 0;
          for (var td = editor.state.selection.$from.depth; td > 0; td--) if (editor.state.selection.$from.node(td).type.name === "timelineItem") { itemDepth = td; break; }
          var hasDescription = itemDepth && editor.state.selection.$from.node(itemDepth).childCount > 2;
          var items = group(rowTwo);
          var addEntry = ibtn(items, "plus", "Add a new entry to the timeline", function () { chain().timelineAddItem().run(); });
          addEntry.classList.add("nbtb-labeled");
          addEntry.appendChild(document.createTextNode("Entry"));
          ibtn(items, "list-minus", "Delete this entry", function () { chain().timelineDeleteItem().run(); });
          ibtn(items, "arrow-up", "Move this entry up", function () { chain().timelineMoveItem(-1).run(); });
          ibtn(items, "arrow-down", "Move this entry down", function () { chain().timelineMoveItem(1).run(); });
          if (itemDepth) ibtn(items, "align-left", hasDescription ? "Remove description" : "Add description", function () { chain().timelineToggleDescription().run(); }, hasDescription);
          ibtn(rowTwo, "trash-2", "Delete timeline", function () { chain().deleteNode("timeline").run(); });
        }
        return;
      }
      if (ancestor(["table"])) {
        show();
        var rowsGroup = group(rowTwo);
        ibtn(rowsGroup, "between-vertical-start", "Row above", function () { chain().addRowBefore().run(); });
        ibtn(rowsGroup, "between-vertical-end", "Row below", function () { chain().addRowAfter().run(); });
        ibtn(rowsGroup, "list-minus", "Delete row", function () { chain().deleteRow().run(); });
        var colsGroup = group(rowTwo);
        ibtn(colsGroup, "between-horizontal-start", "Column left", function () { chain().addColumnBefore().run(); });
        ibtn(colsGroup, "between-horizontal-end", "Column right", function () { chain().addColumnAfter().run(); });
        ibtn(colsGroup, "square-minus", "Delete column", function () { chain().deleteColumn().run(); });
        var alignGroup = group(rowTwo);
        ibtn(alignGroup, "align-left", "Align column left", function () { chain().alignColumn("left").run(); });
        ibtn(alignGroup, "align-center", "Align column center", function () { chain().alignColumn("center").run(); });
        ibtn(alignGroup, "align-right", "Align column right", function () { chain().alignColumn("right").run(); });
        ibtn(rowTwo, "panel-top", "Header row", function () { chain().toggleHeaderRow().run(); });
        ibtn(rowTwo, "trash-2", "Delete table", function () { chain().deleteTable().run(); });
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
      for (var d = sel.$from.depth; d > 0; d--) sig.push(sel.$from.node(d).type.name + JSON.stringify(sel.$from.node(d).attrs) + (sel.$from.node(d).type.name === "timelineItem" ? sel.$from.node(d).childCount : ""));
      sig = sig.join("|");
      if (sig === lastSig) return;
      lastSig = sig;
      paintContext();
    }
    // The context controls follow the other icons; when they would not all fit on the row they start a second row.
    var contextBreak = el("span", "nbtb-break");
    contextBreak.hidden = true;
    rowOne.appendChild(contextBreak);
    rowOne.appendChild(rowTwo);
    rowOne.appendChild(rowThree);
    // On phones only the controls of what the caret is in show; this button brings the rest back.
    var more = button(rowOne, "pilcrow", "Show all formatting", function () { root.classList.toggle("show-all"); });
    more.classList.add("nbtb-more");
    editor.view.dom.addEventListener("nb-open-link", function () { mode = "link"; lastSig = ""; paintContext(); });
    editor.on("selectionUpdate", refresh);
    editor.on("transaction", function () { if (!root.contains(document.activeElement)) refresh(); });
    refresh();
  }

  window.NotebookTiptapToolbar = { build: build };
})();
