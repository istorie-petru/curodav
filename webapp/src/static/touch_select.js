// Touch devices: no row checkboxes. A long press on a row starts selection, then taps toggle rows until
// the selection is cleared. It drives the existing .row-select checkboxes, so bulk_select.js and
// tasks_table.js keep owning the selection, the bar and the actions. Feature notes: features/mobile-touch.md.
(function () {
  var HOLD_MS = 450;
  var MOVE_PX = 10;
  var ROW = "tr, .contact-row-wrap";
  var timer = null;
  var start = null;
  var justSelected = false;
  var toggling = false;

  function rowCheckbox(target) {
    var row = target.closest && target.closest(ROW);
    return row ? row.querySelector(".row-select") : null;
  }

  function toggle(cb) {
    toggling = true;
    cb.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerType: "mouse" }));
    cb.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    document.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    toggling = false;
  }

  function sync() {
    document.body.classList.toggle("touch-selecting", !!document.querySelector(".row-select:checked"));
  }

  function cancel() {
    clearTimeout(timer);
    timer = null;
    start = null;
  }

  document.addEventListener("pointerdown", function (e) {
    if (e.pointerType !== "touch" || e.target.closest(".bulk-actions-bar")) return;
    var cb = rowCheckbox(e.target);
    if (!cb) return;
    start = { x: e.clientX, y: e.clientY };
    timer = setTimeout(function () {
      timer = null;
      if (!cb.checked) toggle(cb);
      justSelected = true;
      if (navigator.vibrate) navigator.vibrate(10);
      sync();
    }, HOLD_MS);
  });

  document.addEventListener("pointermove", function (e) {
    if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > MOVE_PX) cancel();
  });
  ["pointerup", "pointercancel", "scroll"].forEach(function (name) {
    document.addEventListener(name, cancel, true);
  });

  // The press that started a selection must not also open the row; later taps toggle while selecting.
  document.addEventListener("click", function (e) {
    if (toggling) return;
    if (e.target.closest(".bulk-actions-bar")) {
      setTimeout(sync, 0);
      return;
    }
    if (justSelected) {
      justSelected = false;
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    if (!document.body.classList.contains("touch-selecting")) return;
    var cb = rowCheckbox(e.target);
    if (!cb) return;
    e.preventDefault();
    e.stopPropagation();
    toggle(cb);
    sync();
  }, true);

  document.addEventListener("contextmenu", function (e) {
    if (e.pointerType === "touch" && rowCheckbox(e.target)) e.preventDefault();
  });
})();
