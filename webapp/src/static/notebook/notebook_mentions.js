// Mentions in the Notebook editor: typing `@` picks a contact, `$` a task or event, `:` an icon.
// A pick becomes an inline chip, a <data class="cdx-mention"> element that opens the item when
// clicked. Works in any text block and in table cells. In a table formula the pick is inserted as
// quoted text instead, so it can be joined into a result. Feature notes:
// curodav-notes/documentation/features/notebook-editor.md.
(function () {
  var KINDS = {
    "@": { kind: "contact", endpoint: "contact", icon: "user" },
    "$": { kind: "item", endpoint: "item", icon: "check-square" },
    ":": { kind: "icon", endpoint: "icon", icon: "smile" },
  };
  var TRIGGER = /(^|[\s (])([@$:])([\w-]{0,30})$/;
  var URLS = { contact: "/contacts/", task: "/tasks/", event: "/events/" };

  function icon(name) {
    return '<svg class="icon" aria-hidden="true"><use href="#icon-' + name + '"></use></svg>';
  }

  // ---- The inline tool: its button types "@"; its sanitize rule keeps the chips on save ----
  function NotebookMention(params) {
    this.api = params.api;
    this.button = null;
  }
  NotebookMention.isInline = true;
  NotebookMention.title = "Mention";
  NotebookMention.sanitize = { data: { class: true, value: true, "data-kind": true } };
  NotebookMention.prototype.render = function () {
    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.classList.add(this.api.styles.inlineToolButton);
    this.button.title = "Mention a contact, task or event";
    this.button.setAttribute("aria-label", "Mention");
    this.button.textContent = "@";
    return this.button;
  };
  NotebookMention.prototype.surround = function (range) {
    if (!range) return;
    var at = range.cloneRange();
    at.collapse(false);
    var node = document.createTextNode("@");
    at.insertNode(node);
    var caret = document.createRange();
    caret.setStart(node, 1);
    caret.collapse(true);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(caret);
    var editable = node.parentElement && node.parentElement.closest("[contenteditable=true]");
    if (editable) editable.dispatchEvent(new Event("input", { bubbles: true }));
  };
  NotebookMention.prototype.checkState = function () {
    return false;
  };

  // ---- The picker -------------------------------------------------------------------------
  var state = null; // {trigger, node, start, editable, items, index, entry, token}
  var popup = null;

  function closePicker() {
    if (state && state.entry) window.NotebookFloating.release(state.entry);
    if (popup) popup.remove();
    popup = null;
    state = null;
  }

  function context(target) {
    var editable = target.closest && target.closest("[contenteditable=true]");
    if (!editable || editable.closest(".cdx-code, pre, .cdx-footnote-list")) return null;
    var sel = window.getSelection();
    if (!sel.rangeCount || !sel.isCollapsed) return null;
    var node = sel.anchorNode;
    if (!node || node.nodeType !== Node.TEXT_NODE || !editable.contains(node)) return null;
    var before = node.textContent.slice(0, sel.anchorOffset);
    var m = TRIGGER.exec(before);
    if (!m) return null;
    return { editable: editable, node: node, trigger: m[2], query: m[3], start: before.length - m[3].length - 1 };
  }

  function caretRect(node, offset) {
    var r = document.createRange();
    r.setStart(node, Math.max(0, offset - 1));
    r.setEnd(node, offset);
    var rect = r.getBoundingClientRect();
    if (!rect.width && !rect.height) rect = node.parentElement.getBoundingClientRect();
    return rect;
  }

  function onInput(e) {
    var ctx = context(e.target);
    if (!ctx) {
      closePicker();
      return;
    }
    if (!state || state.node !== ctx.node || state.start !== ctx.start || state.trigger !== ctx.trigger) {
      closePicker();
      state = { trigger: ctx.trigger, node: ctx.node, start: ctx.start, editable: ctx.editable, items: [], index: 0, entry: null, token: 0 };
      popup = document.createElement("div");
      popup.className = "cdx-mention-popup";
      popup.setAttribute("role", "listbox");
      document.body.appendChild(popup);
      state.entry = window.NotebookFloating.open(popup, function () {
        popup.remove();
        popup = null;
        state = null;
      });
    }
    state.query = ctx.query;
    fetchItems();
  }

  function fetchItems() {
    var current = state;
    var token = ++current.token;
    var cfg = KINDS[current.trigger];
    fetch("/notebook/mentions?kind=" + cfg.endpoint + "&q=" + encodeURIComponent(current.query), { headers: { Accept: "application/json" } })
      .then(function (resp) { return resp.ok ? resp.json() : []; })
      .catch(function () { return []; })
      .then(function (items) {
        if (state !== current || token !== current.token) return;
        current.items = items;
        current.index = 0;
        renderPicker();
      });
  }

  function renderPicker() {
    if (!popup || !state) return;
    popup.innerHTML = "";
    if (!state.items.length) {
      var empty = document.createElement("div");
      empty.className = "cdx-mention-empty";
      empty.textContent = "No matches";
      popup.appendChild(empty);
    }
    state.items.forEach(function (item, i) {
      var row = document.createElement("button");
      row.type = "button";
      row.setAttribute("role", "option");
      row.className = "cdx-mention-row" + (i === state.index ? " is-active" : "");
      var glyph = item.kind === "icon" ? item.name : item.kind === "contact" ? "user" : item.kind === "event" ? "calendar" : "check-square";
      row.innerHTML = '<span class="cdx-mention-row-icon">' + icon(glyph) + "</span>";
      var label = document.createElement("span");
      label.className = "cdx-mention-row-label";
      label.textContent = item.title;
      row.appendChild(label);
      if (item.subtitle) {
        var sub = document.createElement("span");
        sub.className = "cdx-mention-row-sub";
        sub.textContent = item.subtitle;
        row.appendChild(sub);
      }
      row.addEventListener("mousedown", function (e) { e.preventDefault(); });
      row.addEventListener("click", function () { pick(item); });
      popup.appendChild(row);
    });
    var rect = caretRect(state.node, state.start + 1 + state.query.length);
    var width = popup.offsetWidth, height = popup.offsetHeight;
    var left = Math.min(Math.max(8, rect.left), window.innerWidth - width - 8);
    var top = rect.bottom + 6;
    if (top + height > window.innerHeight - 8) top = Math.max(8, rect.top - height - 6);
    popup.style.left = left + "px";
    popup.style.top = top + "px";
  }

  function chipFor(item) {
    var chip = document.createElement("data");
    chip.className = "cdx-mention" + (item.kind === "icon" ? " cdx-mention-icon" : "");
    chip.setAttribute("data-kind", item.kind);
    chip.setAttribute("value", item.kind === "icon" ? "icon:" + item.name : item.kind + ":" + item.uid);
    chip.contentEditable = "false";
    if (item.kind === "icon") chip.innerHTML = icon(item.name);
    else chip.textContent = item.title;
    return chip;
  }

  function pick(item) {
    var current = state;
    if (!current) return;
    var undo = window.notebookUndo;
    if (undo) undo.checkpoint();
    var node = current.node;
    var end = current.start + 1 + current.query.length;
    var range = document.createRange();
    range.setStart(node, current.start);
    range.setEnd(node, Math.min(end, node.textContent.length));
    range.deleteContents();
    var inFormula = current.editable.classList.contains("nbt-cell") && current.editable.textContent.charAt(0) === "=";
    var inserted;
    if (inFormula) {
      var text = item.kind === "icon" ? item.name : item.title;
      inserted = document.createTextNode('"' + text.replace(/"/g, '""') + '"');
      range.insertNode(inserted);
    } else {
      inserted = chipFor(item);
      range.insertNode(inserted);
      var space = document.createTextNode(" ");
      inserted.after(space);
      inserted = space;
    }
    var caret = document.createRange();
    caret.setStartAfter(inserted);
    caret.collapse(true);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(caret);
    var editable = current.editable;
    closePicker();
    editable.dispatchEvent(new Event("input", { bubbles: true }));
    if (undo) setTimeout(function () { undo.checkpoint(); }, 80);
  }

  function onKeydown(e) {
    if (!state || !popup) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!state.items.length) return;
      e.preventDefault();
      e.stopPropagation();
      state.index = (state.index + (e.key === "ArrowDown" ? 1 : state.items.length - 1)) % state.items.length;
      renderPicker();
    } else if ((e.key === "Enter" || e.key === "Tab") && state.items.length) {
      e.preventDefault();
      e.stopPropagation();
      pick(state.items[state.index]);
    } else if (e.key === "Escape") {
      closePicker();
    }
  }

  // ---- Chips: made read-only, icons drawn, clicks open the item ------------------------------
  function decorate(root) {
    root.querySelectorAll("data.cdx-mention").forEach(function (chip) {
      if (chip.contentEditable !== "false") chip.contentEditable = "false";
      if (chip.classList.contains("cdx-mention-icon") && !chip.firstChild) {
        var name = (chip.getAttribute("value") || "").replace(/^icon:/, "");
        if (name) chip.innerHTML = icon(name);
      }
    });
  }

  function wire(mount) {
    mount.addEventListener("input", onInput);
    mount.addEventListener("keydown", onKeydown, true);
    mount.addEventListener("click", function (e) {
      var chip = e.target.closest && e.target.closest("data.cdx-mention");
      if (!chip) return;
      var value = (chip.getAttribute("value") || "").split(":");
      var url = URLS[value[0]];
      if (!url || !value[1]) return;
      e.preventDefault();
      if (window.CCModal) window.CCModal.open(url + encodeURIComponent(value[1]));
    });
    var scheduled = false;
    new MutationObserver(function () {
      if (scheduled) return;
      scheduled = true;
      setTimeout(function () {
        scheduled = false;
        decorate(mount);
      }, 30);
    }).observe(mount, { childList: true, subtree: true });
    decorate(mount);
  }

  window.NotebookMention = NotebookMention;
  window.notebookWireMentions = wire;
})();
