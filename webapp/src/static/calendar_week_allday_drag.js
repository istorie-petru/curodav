
(function () {
  let items = [];
  let cols = [];
  let timeCols = [];
  const CLICK_THRESHOLD_PX = 4;
  const PX_PER_HOUR = Number(document.body.dataset.pxPerHour || 48);
  const SNAP_MINUTES = 15;
  const SNAP_PX = (PX_PER_HOUR / 60) * SNAP_MINUTES;
  const DAY_HEIGHT_PX = 24 * PX_PER_HOUR;
  const DEFAULT_DURATION_MINUTES = 60;

  function snap(px) {
    return Math.round(px / SNAP_PX) * SNAP_PX;
  }

  function minutesToHHMMSS(totalMinutes) {
    totalMinutes = Math.max(0, Math.min(24 * 60 - 1, totalMinutes));
    const h = Math.floor(totalMinutes / 60);
    const m = totalMinutes % 60;
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") + ":00";
  }

  // Returns { type: "allday", el } | { type: "timed", el } | null -- the
  // union of both drop-target kinds a row item can now land on.
  // 2026-09-25 (spanning bars): a `.allday-bar` lives in its own layer over
  // the columns, not inside one, so a point over any bar (including the one
  // being dragged) is resolved to the day column under that X instead.
  function colAtX(x) {
    return cols.find((c) => {
      const r = c.getBoundingClientRect();
      return x >= r.left && x < r.right;
    }) || null;
  }

  function dropTargetAtPoint(x, y) {
    const el = document.elementFromPoint(x, y);
    if (!el) return null;
    if (el.closest(".week-allday-bars")) {
      const col = colAtX(x);
      return col ? { type: "allday", el: col } : null;
    }
    const allday = el.closest(".allday-col");
    if (allday) return { type: "allday", el: allday };
    const timed = el.closest(".time-col");
    if (timed) return { type: "timed", el: timed };
    return null;
  }

  function clearDropHover() {
    cols.forEach((c) => c.classList.remove("drop-hover"));
    timeCols.forEach((c) => c.classList.remove("drop-hover"));
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
    const isTask = el.dataset.due !== undefined;

    function begin(e) {
      started = true;
      dragging = false;
      startX = e.clientX;
      startY = e.clientY;
      // A bar spans several days: the day grabbed is the one under the
      // pointer, and the drop shifts start AND end by the same delta.
      originCol = el.closest(".allday-col") || colAtX(e.clientX);
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
      const hovered = dropTargetAtPoint(e.clientX, e.clientY);
      clearDropHover();
      // A task chip has no timed-grid equivalent -- never highlight one as
      // a valid drop for it (matches end()'s own isTask guard below).
      if (!hovered) return;
      if (hovered.type === "allday" && hovered.el !== originCol) {
        hovered.el.classList.add("drop-hover");
      } else if (hovered.type === "timed" && !isTask) {
        hovered.el.classList.add("drop-hover");
      }
    }

    function end(e) {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      started = false;
      el.classList.remove("dragging");
      clearDropHover();
      if (!dragging) return; // was a click -- let the href navigate normally

      const target = dropTargetAtPoint(e.clientX, e.clientY);
      if (!target) return;

      if (target.type === "timed") {
        if (isTask) return; // no timed equivalent for a task's due date
        endDropOnTimedGrid(target.el, e);
        return;
      }

      // target.type === "allday" -- the original same-row, whole-day-shift
      // move this script has always done.
      const toCol = target.el;
      if (!originCol || toCol === originCol) return;
      const fromDate = originCol.dataset.date;
      const toDate = toCol.dataset.date;
      if (!fromDate || !toDate) return;
      const deltaDays = Math.round((new Date(toDate + "T00:00:00Z") - new Date(fromDate + "T00:00:00Z")) / 86400000);
      if (!deltaDays) return;

      const uid = el.dataset.uid;

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

    // Cross-boundary drop: an all-day event dragged down onto the timed
    // grid. Picks a start time from the drop's Y position within the
    // target time-col (same offset-from-column-top model calendar.js's own
    // setupCreateCol/setupEvent already use), preserves the event's
    // original duration if it had a real one (multi-hour all-day events are
    // rare but not impossible -- data-start/data-end are both real
    // timestamps here), defaulting to DEFAULT_DURATION_MINUTES otherwise.
    function endDropOnTimedGrid(timeCol, e) {
      const uid = el.dataset.uid;
      const day = timeCol.dataset.date;
      if (!uid || !day) return;

      const rawY = e.clientY - timeCol.getBoundingClientRect().top;
      const snappedPx = Math.max(0, Math.min(DAY_HEIGHT_PX - SNAP_PX, snap(rawY)));
      const startMin = Math.round((snappedPx / PX_PER_HOUR) * 60);

      let durationMin = DEFAULT_DURATION_MINUTES;
      if (el.dataset.start && el.dataset.end) {
        const startMs = Date.parse(el.dataset.start);
        const endMs = Date.parse(el.dataset.end);
        if (!Number.isNaN(startMs) && !Number.isNaN(endMs) && endMs > startMs) {
          const diffMin = Math.round((endMs - startMs) / 60000);
          if (diffMin > 0 && diffMin < 24 * 60) durationMin = diffMin;
        }
      }
      const endMin = Math.min(24 * 60 - 1, startMin + durationMin);

      fetch(`/events/${uid}/reschedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start_at: `${day}T${minutesToHHMMSS(startMin)}`,
          end_at: `${day}T${minutesToHHMMSS(endMin)}`,
          all_day: false,
        }),
      }).then((resp) => {
        if (!resp.ok) throw new Error("reschedule failed");
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
  // a fresh #week-grid region (async-CRUD, features/async-crud.md) so the
  // newly-rendered chips get their pointerdown bindings again.
  function init() {
    items = Array.from(document.querySelectorAll(".allday-task[data-uid], .allday-bar[data-uid]"));
    if (!items.length) return;
    cols = Array.from(document.querySelectorAll(".allday-col"));
    timeCols = Array.from(document.querySelectorAll(".time-col"));
    items.forEach(setupItem);
  }

  init();
  window.CCWeekAllDayDrag = { init };
})();
