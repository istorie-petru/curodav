// Selected blocks as a group: Delete/Backspace removes them, and pressing the block's tune button
// (the grip beside it) drags all of them to a new place; release drops them. Dragging across the
// items of one list selects the whole list block. Feature notes:
// curodav-notes/documentation/features/notebook-editor.md.
(function () {
  var mount = null;
  var line = null;

  function blocks() {
    return Array.prototype.slice.call(mount.querySelectorAll(".ce-block"));
  }

  function selectedIndexes() {
    var out = [];
    blocks().forEach(function (b, i) { if (b.classList.contains("ce-block--selected")) out.push(i); });
    return out;
  }

  function checkpoint() {
    if (window.notebookUndo) window.notebookUndo.checkpoint();
  }

  function deleteSelected() {
    var editor = window.notebookEditor;
    var picked = selectedIndexes();
    if (!editor || !picked.length) return;
    checkpoint();
    if (picked.length >= blocks().length) {
      editor.blocks.clear();
      editor.blocks.insert("paragraph", { text: "" }, {}, 0, true);
    } else {
      for (var i = picked.length - 1; i >= 0; i--) editor.blocks.delete(picked[i]);
      editor.caret.setToBlock(Math.max(0, Math.min(picked[0], editor.blocks.getBlocksCount() - 1)), "start");
    }
    setTimeout(checkpoint, 80);
  }

  function dropIndex(y, picked) {
    var list = blocks();
    for (var i = 0; i < list.length; i++) {
      if (picked.indexOf(i) !== -1) continue;
      var r = list[i].getBoundingClientRect();
      if (y < r.top + r.height / 2) return i;
    }
    return list.length;
  }

  function showLine(index, picked) {
    var list = blocks();
    if (!line) {
      line = document.createElement("div");
      line.className = "nb-drop-line";
      document.body.appendChild(line);
    }
    var ref = list[Math.min(index, list.length - 1)];
    var r = ref.getBoundingClientRect();
    line.style.top = (index >= list.length ? r.bottom : r.top) + "px";
    line.style.left = r.left + "px";
    line.style.width = r.width + "px";
  }

  function moveSelected(target, picked) {
    var editor = window.notebookEditor;
    var ids = blocks().map(function (_, i) { return editor.blocks.getBlockByIndex(i).id; });
    var group = picked.map(function (i) { return ids[i]; });
    var rest = ids.filter(function (id) { return group.indexOf(id) === -1; });
    var before = ids.slice(0, target).filter(function (id) { return group.indexOf(id) === -1; }).length;
    var order = rest.slice(0, before).concat(group, rest.slice(before));
    checkpoint();
    order.forEach(function (id, to) {
      var from = editor.blocks.getBlockIndex(id);
      if (from !== to) editor.blocks.move(to, from);
    });
    setTimeout(checkpoint, 80);
  }

  // The dotted drop line (Editor.js marks the block under a dragged block with ce-block--drop-target) and
  // our own drop line must never outlive the drag: a missed dragleave, a drop outside the editor or a mouse
  // released outside the window used to leave them behind.
  function clearDropMarks() {
    document.querySelectorAll(".ce-block--drop-target").forEach(function (b) { b.classList.remove("ce-block--drop-target"); });
    if (line) { line.remove(); line = null; }
    document.body.classList.remove("nb-dragging-blocks");
  }

  function wireDropCleanup() {
    ["dragend", "drop", "mouseup", "pointerup", "touchend"].forEach(function (type) {
      document.addEventListener(type, function () { setTimeout(clearDropMarks, 0); }, true);
    });
    document.addEventListener("dragleave", function (e) {
      if (!e.relatedTarget) clearDropMarks();
    }, true);
    window.addEventListener("blur", clearDropMarks);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") clearDropMarks(); }, true);
    // While dragging over the editor only the block under the pointer keeps the mark.
    document.addEventListener("dragover", function (e) {
      var over = e.target.closest && e.target.closest(".ce-block");
      setTimeout(function () {
        document.querySelectorAll(".ce-block--drop-target").forEach(function (b) { if (b !== over) b.classList.remove("ce-block--drop-target"); });
      }, 0);
    }, true);
  }

  function wire(el) {
    mount = el;
    wireDropCleanup();
    document.addEventListener("keydown", function (e) {
      if ((e.key !== "Delete" && e.key !== "Backspace") || e.ctrlKey || e.metaKey) return;
      if (!mount.isConnected || !selectedIndexes().length) return;
      e.preventDefault();
      e.stopPropagation();
      deleteSelected();
    }, true);

    // Editor.js hides its own tune button while several blocks are selected, so a grip of the
    // same look sits beside the first selected block for as long as the selection lasts.
    var grip = null;
    function syncGrip() {
      var picked = selectedIndexes();
      if (picked.length < 2) {
        if (grip) { grip.remove(); grip = null; }
        return;
      }
      if (!grip) {
        grip = document.createElement("div");
        grip.className = "nb-multi-grip";
        grip.title = "Drag the selected blocks";
        grip.setAttribute("aria-label", "Drag the selected blocks");
        grip.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>';
        document.body.appendChild(grip);
      }
      var r = blocks()[picked[0]].getBoundingClientRect();
      grip.style.top = Math.max(r.top, 56) + "px";
      grip.style.left = Math.max(4, r.left - 34) + "px";
    }
    new MutationObserver(syncGrip).observe(el, { subtree: true, attributes: true, attributeFilter: ["class"] });
    window.addEventListener("scroll", syncGrip, true);

    var drag = null;
    document.addEventListener("mousedown", function (e) {
      var btn = e.target.closest && e.target.closest(".ce-toolbar__settings-btn, .nb-multi-grip");
      if (!btn || e.button !== 0) return;
      var picked = selectedIndexes();
      if (picked.length < 2) return;
      e.preventDefault();
      e.stopPropagation();
      drag = { picked: picked, x: e.clientX, y: e.clientY, moved: false, target: null };
    }, true);
    document.addEventListener("mousemove", function (e) {
      if (!drag) return;
      if (!e.buttons) {  // the button was released where no mouseup reaches the page
        drag = null;
        clearDropMarks();
        return;
      }
      if (!drag.moved && Math.abs(e.clientY - drag.y) + Math.abs(e.clientX - drag.x) < 4) return;
      drag.moved = true;
      document.body.classList.add("nb-dragging-blocks");
      drag.target = dropIndex(e.clientY, drag.picked);
      showLine(drag.target, drag.picked);
    });
    document.addEventListener("mouseup", function () {
      if (!drag) return;
      var done = drag;
      drag = null;
      document.body.classList.remove("nb-dragging-blocks");
      if (line) { line.remove(); line = null; }
      if (done.moved) {
        moveSelected(done.target, done.picked);
        // The click that follows a drag must not open the block menu.
        window.addEventListener("click", function stop(ev) { ev.stopPropagation(); ev.preventDefault(); }, { capture: true, once: true });
      }
    });

    // Dragging from one item of a list into another selects the whole list block.
    var from = null;
    el.addEventListener("mousedown", function (e) {
      var item = e.target.closest && e.target.closest(".cdx-list__item-content");
      from = item ? { item: item, block: item.closest(".ce-block") } : null;
    });
    el.addEventListener("mouseover", function (e) {
      if (!from || !(e.buttons & 1)) return;
      var item = e.target.closest && e.target.closest(".cdx-list__item-content");
      if (item && item !== from.item && item.closest(".ce-block") === from.block) {
        from.block.classList.add("ce-block--selected");
        window.getSelection().removeAllRanges();
        from = null;
      }
    });
    document.addEventListener("mouseup", function () { from = null; });
  }

  window.notebookWireBlockDrag = wire;
})();
