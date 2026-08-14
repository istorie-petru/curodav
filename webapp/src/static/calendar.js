// Drag-to-move and drag-to-resize for the Week/Day time grid
// (templates/calendar_week.html, calendar_day.html). Loaded only on those
// pages (see the <script> tag at the bottom of each) -- if there's no
// `.time-col` on the page this is a silent no-op.
//
// Interaction model: pointerdown on a `.time-event` starts a move; pointerdown
// specifically on its `.te-resize-handle` starts a resize instead. Both
// snap to 15-minute increments while dragging (live, not just on release --
// desktop's Week/Day grid had a bug once where it *looked* snapped during
// the drag but only actually snapped on release, see features/calendar.md's
// 2026-07-19 fix; this avoids repeating that by snapping the displayed
// position on every mousemove, not just at the end). On release, the new
// time (and day column, for a cross-day move in the week view) is saved via
// POST /events/{uid}/reschedule, then the page reloads -- simplest way to
// guarantee the reload reflects whatever the server actually persisted
// (including a server-side conflict/validation outcome), rather than
// trusting the client's optimistic position.
//
// move/up listeners are attached to `document`, not the dragged
// element itself, for the drag's duration -- earlier used
// `setPointerCapture` + element-level pointermove/pointerup instead, which
// turned out to not reliably deliver move events once the cursor left the
// element's own box (confirmed with a real headless-browser test: the
// element never even gained its "dragging" class despite a 96px move).
// Document-level listeners are the standard, more robust drag pattern and
// don't depend on capture semantics working perfectly.
//
// A short drag (a few px, effectively a click) is treated as a click and
// left alone, so the event's normal href (open its edit form) still works.

(function () {
  const grid = document.querySelector(".time-col");
  if (!grid) return;

  const PX_PER_HOUR = Number(document.body.dataset.pxPerHour || 48);
  const SNAP_MINUTES = 15;
  const SNAP_PX = (PX_PER_HOUR / 60) * SNAP_MINUTES;
  const DAY_HEIGHT_PX = 24 * PX_PER_HOUR;
  const CLICK_THRESHOLD_PX = 4;

  function snap(px) {
    return Math.round(px / SNAP_PX) * SNAP_PX;
  }

  function minutesToHHMMSS(totalMinutes) {
    totalMinutes = Math.max(0, Math.min(24 * 60 - 1, totalMinutes));
    const h = Math.floor(totalMinutes / 60);
    const m = totalMinutes % 60;
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") + ":00";
  }

  function setupEvent(el) {
    const handle = el.querySelector(".te-resize-handle");
    let mode = null; // "move" | "resize"
    let startX = 0;
    let startY = 0;
    let origTop = 0;
    let origHeight = 0;
    let currentCol = el.closest(".time-col");
    let startCol = currentCol; // the column to revert to if the save fails
    let dragged = false;

    function begin(e, isResize) {
      mode = isResize ? "resize" : "move";
      dragged = false;
      startX = e.clientX;
      startY = e.clientY;
      origTop = parseFloat(el.style.top) || 0;
      origHeight = parseFloat(el.style.height) || SNAP_PX;
      currentCol = el.closest(".time-col");
      startCol = currentCol;
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", end);
    }

    function move(e) {
      if (!mode) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (!dragged && (Math.abs(dx) > CLICK_THRESHOLD_PX || Math.abs(dy) > CLICK_THRESHOLD_PX)) {
        dragged = true;
        el.classList.add("dragging");
      }
      if (!dragged) return;

      if (mode === "move") {
        let newTop = snap(origTop + dy);
        newTop = Math.max(0, Math.min(DAY_HEIGHT_PX - origHeight, newTop));
        el.style.top = newTop + "px";

        // Which column is the *cursor* over -- NOT the dragged element's
        // own bounding box. `el.style.left`/`width` are percentages set
        // once at render time and this code never touches them, so the
        // element's on-screen horizontal position never actually changes
        // during the drag; checking against its own rect meant this could
        // never detect a column change at all (confirmed live: dragging
        // across columns produced zero drop-hover highlights, ever). Using
        // the real mouse X against each column's rect is what the block
        // visually "snapping" into a new column on crossing its boundary
        // actually requires.
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

    function end(e) {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      if (!mode) return;
      mode = null;
      el.classList.remove("dragging");
      document.querySelectorAll(".time-col.drop-hover").forEach((c) => c.classList.remove("drop-hover"));
      if (!dragged) return; // was a click -- let the href navigate normally

      const top = parseFloat(el.style.top) || 0;
      const height = parseFloat(el.style.height) || SNAP_PX;
      const startMin = Math.round((top / PX_PER_HOUR) * 60);
      const endMin = Math.round(((top + height) / PX_PER_HOUR) * 60);
      const day = currentCol.dataset.date;
      const uid = el.dataset.uid;
      const droppedCol = currentCol;

      // Sleep Time / Leisure Time warning (static/time_blocks.js) -- purely
      // advisory, fired alongside the save below rather than gating it; a
      // no-op if the page has no configured blocks or the script didn't load.
      if (window.ccTimeBlocks) window.ccTimeBlocks.warnIfOverlapping(day, startMin, endMin);

      // Optimistic, same as Kanban's drag-and-drop (tasks_board.js) --
      // the position on screen is already correct the instant the pointer
      // is released (that's what the whole drag was doing), so a reload
      // on *every* successful save was throwing away a fluid interaction
      // with a jarring full-page flash at the very last step. Only revert
      // (back to the exact day/top/height this drag started from) and
      // reload on an actual failure, so the one case that still reloads
      // is also the one case where the user needs to see the server's
      // real, authoritative state rather than trust the optimistic guess.
      fetch(`/events/${uid}/reschedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start_at: `${day}T${minutesToHHMMSS(startMin)}`,
          end_at: `${day}T${minutesToHHMMSS(endMin)}`,
        }),
      }).then((resp) => {
        if (!resp.ok) throw new Error("reschedule failed");
        // The block's position already reflects the new time (that's what
        // the drag just did) -- but its *label* is still server-rendered
        // text from before the drag (e.g. "14:00-15:00"), and nothing
        // reloads the page anymore to refresh it. Update it directly so
        // the visible time doesn't silently go stale after a successful
        // move. `.te-time` can appear twice on Day view (time range +
        // location) -- the time range is always the first one.
        const timeEl = el.querySelector(".te-time");
        if (timeEl) timeEl.textContent = `${minutesToDisplayTime(startMin)}–${minutesToDisplayTime(endMin)}`;
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
      begin(e, handle && e.target === handle);
    });
    el.addEventListener("click", (e) => {
      if (dragged) {
        e.preventDefault();
        dragged = false;
      }
    });
  }

  // :not(.work-allocation) -- on the merged Week view (1.9 side work,
  // templates/calendar_week.html) static/project_calendar.js also runs on
  // this page and owns every `.work-allocation` block's own pointerdown
  // (move/resize/delete-to-unschedule, plus click-to-open-task). Without
  // this exclusion both scripts would attach a competing pointerdown
  // handler to the same element.
  document.querySelectorAll(".time-event:not(.work-allocation)").forEach(setupEvent);

  // ---------------------------------------------------------------- //
  // Hover-preview + click / click-drag-release to CREATE a new event on
  // empty grid space -- same interaction as the Schedule grid
  // (static/schedule_grid.js), 30-minute snap here since this is a
  // general calendar rather than a class timetable. A plain click
  // previews/creates a 1-hour event; pressing and dragging before
  // releasing extends the ghost to a custom length. Releasing navigates
  // to the New Event form with date/start_time/end_time prefilled.
  // ---------------------------------------------------------------- //

  const CREATE_SNAP_MINUTES = 30;
  const CREATE_SNAP_PX = (PX_PER_HOUR / 60) * CREATE_SNAP_MINUTES;

  function snapCreate(px) {
    return Math.round(px / CREATE_SNAP_PX) * CREATE_SNAP_PX;
  }

  function minutesToHHMM(totalMinutes) {
    totalMinutes = Math.max(0, Math.min(24 * 60 - 1, totalMinutes));
    const h = Math.floor(totalMinutes / 60);
    const m = totalMinutes % 60;
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0");
  }

  // 2026-08-08 -- display-only counterpart to minutesToHHMM above:
  // respects the "24-hour time" Settings > General preference (deps.py's
  // time_format(), exposed here via base.html's `data-time-format` body
  // attribute, same pattern as `data-px-per-hour`) for the drag-resize
  // preview *label* text. Deliberately a separate function, not a
  // TIME_FORMAT branch added to minutesToHHMM itself -- that function's
  // output also feeds `start_time`/`end_time` prefill values for the New
  // Event redirect (see setupCreateCol below), which a native
  // `<input type="time">` requires in plain 24-hour "HH:MM" regardless of
  // this display preference; branching the one function by format would
  // have silently broken that prefill whenever "12-hour time" was on.
  const TIME_FORMAT = document.body.dataset.timeFormat || "24h";
  function minutesToDisplayTime(totalMinutes) {
    if (TIME_FORMAT !== "12h") return minutesToHHMM(totalMinutes);
    totalMinutes = Math.max(0, Math.min(24 * 60 - 1, totalMinutes));
    const h = Math.floor(totalMinutes / 60);
    const m = totalMinutes % 60;
    const period = h < 12 ? "AM" : "PM";
    const h12 = h % 12 || 12;
    return h12 + ":" + String(m).padStart(2, "0") + " " + period;
  }

  // Deliberately NOT given `touch-action:none` the way .time-event/
  // .timeline-bar are -- those are small, unambiguous drag targets, but
  // this create-col *is* the day/week grid's own scrollable area. Forcing
  // touch-action:none here would trade away the ability to scroll the
  // grid by touch at all in exchange for drag-to-create, which is a worse
  // deal than what it replaces. A plain tap still creates a default
  // 1-hour event on touch (no ambiguity, so the browser never treats a
  // stationary tap as a scroll gesture) -- only the "drag to pick a
  // custom length" refinement stays mouse-only, since touch genuinely
  // can't do both a scroll and a drag-create on the same surface at once.
  document.querySelectorAll(".calendar-create-col").forEach((col) => {
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

    // pointermove (not mousemove) doubles as both the hover-preview (fires
    // on mouse movement even with no button pressed -- touch has no such
    // phase, so touch simply never triggers this branch until a finger is
    // actually down, which is the correct touch behavior: no hover
    // preview, but the drag-to-create gesture below still works
    // identically once pressed) and the live drag-update while `creating`.
    col.addEventListener("pointermove", (e) => {
      // On the merged Week view (1.9 side work) these columns also carry
      // `.project-calendar-col` -- static/project_calendar.js sets
      // `window.__ccGridDragActive` while it owns an active drag (an
      // unscheduled task being dragged onto the grid, or an existing block
      // being moved/resized). Without this check, this hover-preview
      // ghost -- always 30 minutes tall, this file's own click-to-create
      // default -- rendered on top of that drag and looked like the drop
      // would create a 30-minute block, when the actual result is always
      // DEFAULT_BLOCK_MINUTES (60) -- direct feedback, confirmed live.
      if (window.__ccGridDragActive) {
        ghost.style.display = "none";
        return;
      }
      if (e.target !== col) {
        if (!creating) ghost.style.display = "none";
        return;
      }
      const raw = offsetY(e);
      if (creating) {
        const current = snapCreate(raw);
        const top = Math.min(createStartPx, current);
        const bottom = Math.max(createStartPx, current) + CREATE_SNAP_PX;
        showGhost(top, Math.max(CREATE_SNAP_PX, bottom - top));
      } else {
        let top = snapCreate(raw);
        top = Math.max(0, Math.min(DAY_HEIGHT_PX - CREATE_SNAP_PX, top));
        showGhost(top, CREATE_SNAP_PX);
      }
    });

    col.addEventListener("pointerleave", () => {
      if (!creating) ghost.style.display = "none";
    });

    col.addEventListener("pointerdown", (e) => {
      if (window.__ccGridDragActive || e.target !== col || e.button !== 0) return;
      creating = true;
      createStartPx = snapCreate(offsetY(e));
      showGhost(createStartPx, CREATE_SNAP_PX);
    });

    function finishCreate() {
      if (!creating) return;
      creating = false;
      const top = parseFloat(ghost.style.top) || 0;
      const height = parseFloat(ghost.style.height) || CREATE_SNAP_PX;
      ghost.style.display = "none";
      const startMin = Math.round((top / PX_PER_HOUR) * 60);
      const endMin = Math.round(((top + height) / PX_PER_HOUR) * 60);
      const date = col.dataset.date;
      const params = new URLSearchParams({
        date,
        start_time: minutesToHHMM(startMin),
        end_time: minutesToHHMM(endMin),
      });
      const url = `/events/new?${params.toString()}`;
      if (window.CCModal) window.CCModal.open(url);
      else window.location.href = url; // modal.js failed to load -- don't strand the user
    }

    col.addEventListener("pointerup", finishCreate);
    document.addEventListener("pointerup", () => {
      if (creating) finishCreate();
    });
    document.addEventListener("pointercancel", () => {
      creating = false;
      ghost.style.display = "none";
    });
  });
})();
