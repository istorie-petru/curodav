// Schedule's weekly grid (templates/schedule_classes.html, ?view=calendar):
// two mouse interactions on top of the same time-grid markup Calendar's
// Week/Day views use.
//
// 1. Hover-preview + click / click-drag-release to CREATE a class: moving
//    the mouse over empty grid space shows a faint snapped ghost block
//    (a plain click previews/creates a 1-hour slot; pressing and dragging
//    before releasing extends the ghost to a custom length). Releasing
//    navigates to the New Class form with day/start_time/end_time
//    prefilled -- matches the reference "Uni Schedule" app's own
//    hover-preview-then-click(-drag) behavior this feature was modeled on.
// 2. Drag-to-move / drag-to-resize an EXISTING class, same mechanics as
//    calendar.js's Week/Day grid, but snapped to the hour (matching the
//    reference app's "everything snaps to the hour" for a class
//    timetable) and saved via POST /schedule/classes/{uid}/reposition.
//
// Both snap live during the drag and add `.time-col.drop-hover` /
// `.time-event.dragging` for a visibly "grounded" cue rather than the
// block looking like it's floating disconnected above the table.
//
// Exposed as window.CCScheduleGrid.init(root), not a bare top-level IIFE
// -- same reason as schedule_table.js (2026-08-01, Schedule became a
// modal opened from Calendar): a modal's content is injected via
// innerHTML, which never executes embedded <script> tags and never
// re-runs a script that already finished on the *original* page. Loaded
// globally (base.html) and re-invoked from modal.js's wireContent()
// after every injection, same fix as schedule_table.js.

(function () {
  const PX_PER_HOUR = Number(document.body.dataset.pxPerHour || 48);
  const SNAP_MINUTES = 60; // whole-hour snap, matching the reference app
  const SNAP_PX = (PX_PER_HOUR / 60) * SNAP_MINUTES;
  const DAY_HEIGHT_PX = 24 * PX_PER_HOUR;
  const CLICK_THRESHOLD_PX = 4;

  function snap(px) {
    return Math.round(px / SNAP_PX) * SNAP_PX;
  }

  function minutesToHHMM(totalMinutes) {
    totalMinutes = Math.max(0, Math.min(24 * 60 - 1, totalMinutes));
    const h = Math.floor(totalMinutes / 60);
    const m = totalMinutes % 60;
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0");
  }

  function setupCreateCol(col) {
    if (col.dataset.ccWired) return;
    col.dataset.ccWired = "1";

    const ghost = document.createElement("div");
    ghost.className = "schedule-ghost";
    ghost.style.display = "none";
    col.appendChild(ghost);

    let creating = false;
    let createStartPx = 0;

    function offsetY(e) {
      return e.clientY - col.getBoundingClientRect().top;
    }

    function showGhost(topPx, heightPx) {
      ghost.style.display = "block";
      ghost.style.top = topPx + "px";
      ghost.style.height = heightPx + "px";
    }

    // pointermove, not mousemove -- same reasoning as calendar.js's
    // identical create-col handling: fires on mouse hover exactly like
    // mousemove did, and also drives the live drag-update once `creating`
    // is true, but touch (no hover phase) simply never triggers the
    // preview branch until actually pressed, which is correct.
    col.addEventListener("pointermove", (e) => {
      // Only preview when hovering truly empty space -- if the pointer is
      // over an existing .time-event (or its resize handle), that
      // element's own drag handling takes over instead.
      if (e.target !== col) {
        if (!creating) ghost.style.display = "none";
        return;
      }
      const raw = offsetY(e);
      if (creating) {
        const current = snap(raw);
        const top = Math.min(createStartPx, current);
        const bottom = Math.max(createStartPx, current) + SNAP_PX;
        showGhost(top, Math.max(SNAP_PX, bottom - top));
      } else {
        let top = snap(raw);
        top = Math.max(0, Math.min(DAY_HEIGHT_PX - SNAP_PX, top));
        showGhost(top, SNAP_PX);
      }
    });

    col.addEventListener("pointerleave", () => {
      if (!creating) ghost.style.display = "none";
    });

    // Deliberately no touch-action:none here -- same tradeoff as
    // calendar.js's create-col: this *is* the grid's scrollable area, and
    // trading away touch-scroll for drag-to-create would be a worse deal.
    // A plain tap still creates a default slot.
    col.addEventListener("pointerdown", (e) => {
      if (e.target !== col || e.button !== 0) return;
      creating = true;
      createStartPx = snap(offsetY(e));
      showGhost(createStartPx, SNAP_PX);
    });

    function finishCreate() {
      if (!creating) return;
      creating = false;
      const top = parseFloat(ghost.style.top) || 0;
      const height = parseFloat(ghost.style.height) || SNAP_PX;
      ghost.style.display = "none";
      const startMin = Math.round((top / PX_PER_HOUR) * 60);
      const endMin = Math.round(((top + height) / PX_PER_HOUR) * 60);
      const day = col.dataset.day;
      const params = new URLSearchParams({
        day,
        start_time: minutesToHHMM(startMin),
        end_time: minutesToHHMM(endMin),
      });
      const url = `/schedule/classes/new?${params.toString()}`;
      if (window.CCModal) window.CCModal.open(url);
      else window.location.href = url; // modal.js failed to load -- don't strand the user
    }

    col.addEventListener("pointerup", finishCreate);
    // Releasing outside the column (dragged past its edge) should still
    // commit the create, same as the reference app's calendar drag.
    document.addEventListener("pointerup", () => {
      if (creating) finishCreate();
    });
    document.addEventListener("pointercancel", () => {
      creating = false;
      ghost.style.display = "none";
    });
  }

  function setupEvent(el) {
    if (el.dataset.ccWired) return;
    el.dataset.ccWired = "1";

    const handle = el.querySelector(".te-resize-handle");
    let mode = null; // "move" | "resize"
    let startY = 0;
    let origTop = 0;
    let origHeight = 0;
    let currentCol = el.closest(".time-col");
    let startCol = currentCol; // the column to revert to if the save fails
    let dragged = false;

    function begin(e, isResize) {
      mode = isResize ? "resize" : "move";
      dragged = false;
      startY = e.clientY;
      origTop = parseFloat(el.style.top) || 0;
      origHeight = parseFloat(el.style.height) || SNAP_PX;
      currentCol = el.closest(".time-col");
      startCol = currentCol;
      // Document-level listeners, not setPointerCapture + element-level
      // pointermove -- confirmed via a real headless-browser test that the
      // capture approach silently failed to deliver move events once the
      // cursor left the element's own box. See calendar.js's header
      // comment for the full explanation; same fix applied here.
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", end);
    }

    function move(e) {
      if (!mode) return;
      const dy = e.clientY - startY;
      if (!dragged && Math.abs(dy) > CLICK_THRESHOLD_PX) {
        dragged = true;
        el.classList.add("dragging");
      }
      if (!dragged) return;

      if (mode === "move") {
        let newTop = snap(origTop + dy);
        newTop = Math.max(0, Math.min(DAY_HEIGHT_PX - origHeight, newTop));
        el.style.top = newTop + "px";

        // Use the cursor's real X, not the dragged element's own rect --
        // el.style.left/width are static percentages this code never
        // updates, so the element's on-screen X never moves and checking
        // against it could never detect a day-column change. Same bug/fix
        // as calendar.js's move().
        const cols = Array.from(document.querySelectorAll(".time-col"));
        let hoverCol = currentCol;
        for (const col of cols) {
          const r = col.getBoundingClientRect();
          if (e.clientX >= r.left && e.clientX <= r.right) {
            hoverCol = col;
            break;
          }
        }
        cols.forEach((c) => c.classList.toggle("drop-hover", c === hoverCol && c !== currentCol));
        if (hoverCol !== currentCol) {
          hoverCol.appendChild(el);
          currentCol = hoverCol;
        }
      } else {
        let newHeight = snap(origHeight + dy);
        newHeight = Math.max(SNAP_PX, Math.min(DAY_HEIGHT_PX - origTop, newHeight));
        el.style.height = newHeight + "px";
      }
    }

    function end() {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      if (!mode) return;
      mode = null;
      el.classList.remove("dragging");
      document.querySelectorAll(".time-col.drop-hover").forEach((c) => c.classList.remove("drop-hover"));
      if (!dragged) return;

      const top = parseFloat(el.style.top) || 0;
      const height = parseFloat(el.style.height) || SNAP_PX;
      const startMin = Math.round((top / PX_PER_HOUR) * 60);
      const endMin = Math.round(((top + height) / PX_PER_HOUR) * 60);
      const day = currentCol.dataset.day;
      const uid = el.dataset.uid;
      const droppedCol = currentCol;

      // Optimistic, same as calendar.js's identical drag and Kanban's
      // drag-and-drop -- reload only on an actual failure, not on every
      // successful drop (see calendar.js's end() for the full reasoning).
      fetch(`/schedule/classes/${uid}/reposition`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          day,
          start_time: minutesToHHMM(startMin),
          end_time: minutesToHHMM(endMin),
        }),
      }).then((resp) => {
        if (!resp.ok) throw new Error("reposition failed");
        // Same "position updated, label didn't" fix as calendar.js's
        // identical drag -- see its end() for the full reasoning.
        const timeEl = el.querySelector(".te-time");
        if (timeEl) timeEl.textContent = `${minutesToHHMM(startMin)}–${minutesToHHMM(endMin)}`;
      }).catch(() => {
        el.style.top = origTop + "px";
        el.style.height = origHeight + "px";
        if (droppedCol !== startCol) startCol.appendChild(el);
        currentCol = startCol;
        window.ccToast({ message: "Could not save that move. Reverted.", variant: "error" });
      });
    }

    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault(); // stop native text-selection/link-drag ghost while dragging
      e.stopPropagation(); // don't let the column's own pointerdown start a create-drag underneath
      begin(e, handle && e.target === handle);
    });
    el.addEventListener("click", (e) => {
      if (dragged) {
        e.preventDefault();
        dragged = false;
      }
    });
  }

  function init(root) {
    const scope = root || document;
    scope.querySelectorAll(".schedule-create-col").forEach(setupCreateCol);
    scope.querySelectorAll(".time-event").forEach(setupEvent);
  }

  window.CCScheduleGrid = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
