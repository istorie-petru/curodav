// Click-and-hold drag-to-create in the month grid (templates/
// calendar_month.html), Phase 10 of the projects/tags rework -- the one
// calendar view that had NO create-by-dragging interaction at all before
// this (Week/Day already have it via the `.calendar-create-col` handler
// in calendar.js; Schedule has its own equivalent in schedule_grid.js).
// Month view has no time axis, so a "drag" here spans whole days, not
// hours: press down on an empty day cell, drag across other day cells
// (in either direction), release to open the New Event form prefilled as
// an all-day event spanning the pressed-to-released date range.
//
// Deliberately does NOT preventDefault/hijack anything on the day-number
// link or an event/task chip inside a cell -- the handler only starts a
// selection when the mousedown target is the cell itself (empty space),
// same "only the bare container, not any child" rule
// `.calendar-create-col`'s handler in calendar.js already uses for the
// identical reason (so existing links keep working normally).
//
// A press-and-release on the SAME cell with no drag is treated as a
// same-day quick-add (a 1-day range) rather than requiring a real drag
// for the common "just add something today" case -- "click and hold" in
// the feature request covers both a deliberate multi-day drag and a
// plain click on empty space.

(function () {
  let cells = [];
  let anchorCell = null;
  let selecting = false;

  function cellsBetween(a, b) {
    const ai = cells.indexOf(a);
    const bi = cells.indexOf(b);
    if (ai === -1 || bi === -1) return [];
    const [lo, hi] = ai <= bi ? [ai, bi] : [bi, ai];
    return cells.slice(lo, hi + 1);
  }

  function clearHighlight() {
    cells.forEach((c) => c.classList.remove("is-selecting"));
  }

  function highlight(anchor, current) {
    clearHighlight();
    cellsBetween(anchor, current).forEach((c) => c.classList.add("is-selecting"));
  }

  function cellAtPoint(x, y) {
    const el = document.elementFromPoint(x, y);
    return el ? el.closest(".month-day-cell") : null;
  }

  // Pointer Events, not mouse-only -- but deliberately no touch-action:none
  // on the cells (unlike .time-event/.timeline-bar elsewhere): the month
  // grid is the page's own scrollable content on a short phone screen, and
  // trading that scroll away for a multi-day drag-select would cost more
  // than it gives back. A plain tap (no real movement) still works
  // identically on touch -- same-day quick-add, no scroll ambiguity since
  // a stationary tap never triggers the browser's own scroll gesture --
  // only the "drag across days" refinement stays mouse-primary.
  //
  // init() is re-invocable: async_calendar.js re-runs it after swapping in
  // a fresh #month-grid region (async-CRUD, features/async-crud.md) so the
  // newly-rendered cells get their pointerdown bindings again.
  function init() {
    cells = Array.from(document.querySelectorAll(".month-day-cell"));
    if (!cells.length) return;
    cells.forEach((cell) => {
      cell.addEventListener("pointerdown", (e) => {
        if (e.target !== cell || e.button !== 0) return;
        selecting = true;
        anchorCell = cell;
        highlight(cell, cell);
      });
    });
  }

  init();
  window.CCMonthGridCreate = { init };

  document.addEventListener("pointermove", (e) => {
    if (!selecting || !anchorCell) return;
    const hovered = cellAtPoint(e.clientX, e.clientY);
    if (hovered) highlight(anchorCell, hovered);
  });

  document.addEventListener("pointerup", (e) => {
    if (!selecting || !anchorCell) return;
    selecting = false;
    const released = cellAtPoint(e.clientX, e.clientY) || anchorCell;
    clearHighlight();

    const startDate = anchorCell.dataset.date;
    const endDate = released.dataset.date;
    if (!startDate || !endDate) {
      anchorCell = null;
      return;
    }
    // Order-independent -- a drag from a later day back to an earlier one
    // (dragging "up and to the left" in the grid) is just as valid as the
    // forward direction.
    const [from, to] = startDate <= endDate ? [startDate, endDate] : [endDate, startDate];
    anchorCell = null;

    const params = new URLSearchParams({ date: from, end_date: to });
    const url = `/events/new?${params.toString()}`;
    if (window.CCModal) window.CCModal.open(url);
    else window.location.href = url; // modal.js failed to load -- don't strand the user
  });

  document.addEventListener("pointercancel", () => {
    selecting = false;
    anchorCell = null;
    clearHighlight();
  });
})();
