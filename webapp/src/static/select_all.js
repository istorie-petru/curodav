// Header checkbox of a table: selects or clears every visible row checkbox by driving them the way a click does,
// so bulk_select.js and tasks_table.js keep owning the selection and the bulk bar.
(function () {
  function rowBoxes(all) {
    const scope = all.closest("table") || document;
    return Array.from(scope.querySelectorAll("tbody .row-select")).filter((cb) => cb.offsetParent !== null);
  }

  function toggle(cb) {
    cb.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerType: "mouse" }));
    cb.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    document.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
  }

  function sync() {
    document.querySelectorAll(".select-all").forEach((all) => {
      const boxes = rowBoxes(all);
      const n = boxes.filter((cb) => cb.checked).length;
      all.checked = boxes.length > 0 && n === boxes.length;
      all.indeterminate = n > 0 && n < boxes.length;
    });
  }

  document.addEventListener("click", (e) => {
    const all = e.target.closest && e.target.closest(".select-all");
    if (all) {
      const on = all.checked;
      rowBoxes(all).forEach((cb) => {
        if (cb.checked !== on) toggle(cb);
      });
    }
    sync();
  });
  document.addEventListener("cc-region-refreshed", sync);
})();
