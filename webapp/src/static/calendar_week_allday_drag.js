// Drag-to-move an all-day event OR due-date task chip between day columns
// on the Week grid's "All day" row (templates/_calendar_week_grid.html).
// Direct request (2026-09-03): "the user should be able, in the week view,
// to drag and drop all day events/tasks" -- until now `.allday-task` had no
// drag wiring at all (not broken, just never built): calendar.js only ever
// binds `.time-event:not(.work-allocation)`, which this row's items never
// carry.
//
// Model is deliberately the same as Month/4-Week's day-shift drag
// (static/calendar_month_drag.js), not Week's own timed-event move/resize
// (static/calendar.js): the all-day row has no time axis, only a day
// position, so a drag here only ever shifts the *date* by the whole-day
// delta between the column an item was picked up from and the column it
// was dropped on -- never a time-of-day, and there's no resize handle
// (spanning multiple days is a separate feature, not implied by "drag this
// chip to another day"). Same endpoints Month/4-Week and Week's own timed
// drag already use: POST /events/{uid}/reschedule for events, POST
// /tasks/{uid}/update-field (field="due_at") for tasks.
//
// Recurring all-day events are excluded the same way Month excludes them:
// _calendar_week_grid.html only renders data-uid/data-start/data-end for a
// non-recurring event, so a recurring one simply has no `data-uid` here and
// this script never binds it (its href still opens it normally on click).
//
// A short drag (a few px, effectively a click) is treated as a click and
// left alone -- same CLICK_THRESHOLD_PX pattern as calendar.js /
// calendar_month_drag.js.

(function () {
  let items = [];
  let cols = [];
  const CLICK_THRESHOLD_PX = 4;

  function colAtPoint(x, y) {
    const el = document.elementFromPoint(x, y);
    return el ? el.closest(".allday-col") : null;
  }

  function clearDropHover() {
    cols.forEach((c) => c.classList.remove("drop-hover"));
  }

  // Same UTC-midnight date-only shift as calendar_month_drag.js's
  // shiftDate -- avoids the browser's local timezone knocking the result a
  // day off, and leaves any time-of-day suffix on a task's due_at (rare,
  // but the field isn't guaranteed date-only) untouched.
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
    let originCol = null;

    function begin(e) {
      started = true;
      dragging = false;
      startX = e.clientX;
      startY = e.clientY;
      originCol = el.closest(".allday-col");
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
      const hovered = colAtPoint(e.clientX, e.clientY);
      clearDropHover();
      if (hovered && hovered !== originCol) hovered.classList.add("drop-hover");
    }

    function end(e) {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      started = false;
      el.classList.remove("dragging");
      clearDropHover();
      if (!dragging) return; // was a click -- let the href navigate normally

      const target = colAtPoint(e.clientX, e.clientY);
      if (!target || !originCol || target === originCol) return;
      const fromDate = originCol.dataset.date;
      const toDate = target.dataset.date;
      if (!fromDate || !toDate) return;
      const deltaDays = Math.round((new Date(toDate + "T00:00:00Z") - new Date(fromDate + "T00:00:00Z")) / 86400000);
      if (!deltaDays) return;

      const uid = el.dataset.uid;
      const isTask = el.dataset.due !== undefined;

      const request = isTask
        ? fetch(`/tasks/${uid}/update-field`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ field: "due_at", value: shiftDate(el.dataset.due, deltaDays) }),
          })
        : fetch(`/events/${uid}/reschedule`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              start_at: shiftDate(el.dataset.start, deltaDays),
              end_at: el.dataset.end ? shiftDate(el.dataset.end, deltaDays) : null,
            }),
          });

      request.then((resp) => {
        if (!resp.ok) throw new Error("reschedule failed");
        // Same reasoning as calendar_month_drag.js: the moved chip needs to
        // move between two columns' own lists (and Week's all-day row has
        // no cheap local DOM edit that keeps it consistent with the rest of
        // the region), so re-render the whole #week-grid region rather than
        // hand-patch the DOM. async_calendar.js's change listener refreshes
        // it and re-runs this script's init().
        window.ccApi.dispatchChange({ type: isTask ? "task" : "event", action: "move" });
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
  // a fresh #week-grid region (async-CRUD, features/async-crud.md) so the
  // newly-rendered chips get their pointerdown bindings again.
  function init() {
    items = Array.from(document.querySelectorAll(".allday-task[data-uid]"));
    if (!items.length) return;
    cols = Array.from(document.querySelectorAll(".allday-col"));
    items.forEach(setupItem);
  }

  init();
  window.CCWeekAllDayDrag = { init };
})();
