// One rule for every floating menu and bar in the Notebook editor (table selection bar, table menus,
// endnote menus): a floating element closes on a click or tap outside it, on Escape, and whenever
// another floating element opens. A submenu counts as part of its parent, so opening it keeps the
// parent open. Elements register with open() and say how to close themselves.
// Rule text: curodav-notes/documentation/rules/frontend-conventions.md.
(function () {
  var stack = [];

  function inside(entry, target) {
    return entry.el.contains(target) || (entry.opener && entry.opener.contains(target));
  }

  function ancestors(entry) {
    var set = [];
    for (var e = entry; e; e = e.parent) set.push(e);
    return set;
  }

  function closeEntry(entry) {
    var i = stack.indexOf(entry);
    if (i !== -1) stack.splice(i, 1);
    try {
      entry.close();
    } catch (err) {
      /* a close handler that fails must not keep the rest open */
    }
  }

  function closeAll(keep) {
    stack.slice().forEach(function (entry) {
      if (!keep || keep.indexOf(entry) === -1) closeEntry(entry);
    });
  }

  // Registers a floating element. `parent` is the entry it was opened from, if any; `opener` is the
  // button that opened it, which counts as inside so clicking it again can toggle the element.
  function open(el, close, parent, opener) {
    var entry = { el: el, close: close, parent: parent || null, opener: opener || null };
    closeAll(ancestors(entry));
    stack.push(entry);
    return entry;
  }

  function release(entry) {
    var i = stack.indexOf(entry);
    if (i !== -1) stack.splice(i, 1);
  }

  function outside(e) {
    if (!stack.length) return;
    var target = e.target;
    var hit = stack.filter(function (entry) { return inside(entry, target); });
    if (!hit.length) {
      closeAll();
      return;
    }
    // A press inside one entry closes every entry that is not part of its chain.
    closeAll(ancestors(hit[hit.length - 1]));
  }

  document.addEventListener("pointerdown", outside, true);
  document.addEventListener("mousedown", outside, true);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeAll();
  }, true);
  window.addEventListener("blur", function () { closeAll(); });

  window.NotebookFloating = { open: open, release: release, closeAll: closeAll };
})();
