// Drag-to-move an event chip between day cells on the Month grid
// (templates/calendar_month.html). Loaded alongside calendar_month.js
// (which owns click-and-hold drag-to-CREATE on empty cell space); this
// file owns dragging an EXISTING event chip (`.month-event-item` --
// `.month-all-day` and the "event" kind of `.month-task-item`) onto a
// different day cell to reschedule it. Task chips (due-date items, the
// "task" kind of `.month-task-item`, no `.month-event-item` class) are
// left alone -- only events move here.
//
// Reuses the same JSON endpoint the Week/Day grid's own drag already
// posts to (POST /events/{uid}/reschedule, see static/calendar.js) --
// Month has no time axis, so the move only ever shifts the *date*, never
// the time-of-day: the dragged event's existing start/end timestamps are
// shifted by the same whole-day delta between the cell it was picked up
// from and the cell it was dropped on, and the drop cell's own weekday
// position never touches the stored time-of-day at all.
//
// Recurring events are deliberately excluded (no data-uid rendered for
// them by calendar_month.html): reschedule_event only ever moves a plain
// event row's own start_at/end_at, which for a recurring master would
// shift its whole series, not just the one occurrence being dragged --
// same footgun the manual-recurrence-exceptions feature exists to avoid
// elsewhere, so Month simply doesn't offer drag on those chips (a click
// still opens them normally; only the drag affordance is withheld).
//
// A short drag (a few px, effectively a click) is treated as a click and
// left alone -- same CLICK_THRESHOLD_PX pattern as calendar.js.

(function () {
  let items = [];
  let cells = [];
  const CLICK_THRESHOLD_PX = 4;

  function cellAtPoint(x, y) {
    const el = document.elementFromPoint(x, y);
    return el ? el.closest(".month-day-cell") : null;
  }

  function clearDropHover() {
    cells.forEach((c) => c.classList.remove("drop-hover"));
  }

  // Shifts only the date portion of an ISO timestamp ("YYYY-MM-DD" or
  // "YYYY-MM-DDTHH:MM:SS") by `deltaDays`, leaving any time-of-day suffix
  // untouched. Date math done at UTC midnight so it can't be knocked a day
  // off by the browser's local timezone.
  function shiftDate(iso, deltaDays) {
    if (!iso) return iso;
    const datePart = iso.slice(0, 10);
    const rest = iso.slice(10);
    const d = new Date(datePart + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + deltaDays);
    return d.toISOString().slice(0, 10) + rest;
  }

  function setupItem(el) {
    let dragging = false;
    let started = false;
    let startX = 0;
    let startY = 0;
    let originCell = null;

    function begin(e) {
      started = true;
      dragging = false;
      startX = e.clientX;
      startY = e.clientY;
      originCell = el.closest(".month-day-cell");
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", end);
    }

    function move(e) {
      if (!started) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (!dragging && (Math.abs(dx) > CLICK_THRESHOLD_PX || Math.abs(dy) > CLICK_THRESHOLD_PX)) {
        dragging = true;
        el.classList.add("dragging");
      }
      if (!dragging) return;
      const hovered = cellAtPoint(e.clientX, e.clientY);
      clearDropHover();
      if (hovered && hovered !== originCell) hovered.classList.add("drop-hover");
    }

    function end(e) {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      started = false;
      el.classList.remove("dragging");
      clearDropHover();
      if (!dragging) return; // was a click -- let the href navigate normally

      const target = cellAtPoint(e.clientX, e.clientY);
      if (!target || !originCell || target === originCell) return;
      const fromDate = originCell.dataset.date;
      const toDate = target.dataset.date;
      if (!fromDate || !toDate) return;
      const deltaDays = Math.round((new Date(toDate + "T00:00:00Z") - new Date(fromDate + "T00:00:00Z")) / 86400000);
      if (!deltaDays) return;

      const uid = el.dataset.uid;
      const newStart = shiftDate(el.dataset.start, deltaDays);
      const newEnd = el.dataset.end ? shiftDate(el.dataset.end, deltaDays) : "";

      fetch(`/events/${uid}/reschedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start_at: newStart, end_at: newEnd || null }),
      }).then((resp) => {
        if (!resp.ok) throw new Error("reschedule failed");
        // async-CRUD (features/async-crud.md): the moved event now needs to
        // move between two day cells' own `rows`/overflow-count lists,
        // which the server recomputes correctly on a fresh render -- unlike
        // the Week grid's single-block top/left, there's no cheap local DOM
        // edit that keeps overflow counts and "+N more" links consistent
        // across both cells, so we re-render the whole #month-grid region
        // instead of reloading the page. The change event's listener
        // (async_calendar.js) refreshes the region and re-inits the month
        // drag/create bindings.
        window.ccApi.dispatchChange({ type: "event", action: "move" });
      }).catch(() => {
        window.ccToast({ message: "Could not save that move.", variant: "error" });
      });
    }

    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault(); // stop native text-selection/link-drag ghost while dragging
      begin(e);
    });
    el.addEventListener("click", (e) => {
      if (dragging) {
        e.preventDefault();
        dragging = false;
      }
    });
  }

  // init() is re-invocable: async_calendar.js re-runs it after swapping in
  // a fresh #month-grid region (async-CRUD, features/async-crud.md) so the
  // newly-rendered event chips get their pointerdown bindings again.
  function init() {
    items = Array.from(document.querySelectorAll(".month-event-item[data-uid]"));
    if (!items.length) return;
    cells = Array.from(document.querySelectorAll(".month-day-cell"));
    items.forEach(setupItem);
  }

  init();
  window.CCMonthGridDrag = { init };
})();
