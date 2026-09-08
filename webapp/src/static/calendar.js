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
// POST /events/{uid}/reschedule, then `window.ccApi.dispatchChange` fires
// the app-wide `cc-entity-changed` event (async-CRUD,
// features/async-crud.md) -- async_calendar.js re-fetches the whole
// #week-grid/#day-grid region and swaps it in, which re-runs
// grid_layout.layout_day server-side. That's deliberate, not just "reuse
// the existing plumbing": this is also the fix for a direct bug report --
// two overlapping events (each rendered at half-width by layout_day) where
// dragging one so it no longer overlaps left BOTH stuck at their old
// width, because `left_pct`/`width_pct` are baked into the HTML once at
// render time and this handler used to only ever touch `top`/`height`
// (and, on success, patch the `.te-time` label text) -- never the lane
// layout of the event just moved OR the one it used to overlap with,
// which a client-side patch can't fix without duplicating layout_day's
// packing algorithm in JS. Every other calendar drag path (month/day-cell
// drag, all-day-row drag, work-allocation drag) already dispatches this
// same event on success; this handler was the one holdout still patching
// DOM by hand instead.
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
//
// FullCalendar-parity slice 4 (2026-09-09): a move-mode drag (not resize --
// crossing rows mid-resize makes no sense) can now also be dropped onto
// Week's "All day" row (`.allday-col`, templates/_calendar_week_grid.html),
// the other half of the cross-boundary move calendar_week_allday_drag.js's
// own setupItem() implements for the reverse direction. Deliberately does
// NOT reparent the dragged element into the all-day row's normal-flow DOM
// mid-drag (it's an absolutely-positioned `.time-event`, the all-day row is
// plain flow -- reprojecting it correctly there is exactly what the full
// #week-grid region refresh on a successful drop already does server-side,
// same "let the server re-render" reasoning every other calendar drag path
// in this app already follows for lane/lay-out-affecting moves). While
// hovering the all-day row this handler skips its own top/column-tracking
// logic entirely -- the element's on-screen top/height stay wherever they
// last were, which is fine since a successful drop replaces the whole
// region a moment later anyway.

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
    let dropAllDayCol = null; // set while hovering an .allday-col mid-move (slice 4)

    function begin(e, isResize) {
      mode = isResize ? "resize" : "move";
      dragged = false;
      dropAllDayCol = null;
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
        // Slice 4: check the all-day row FIRST -- if the pointer (not the
        // dragged element's own clamped-to-column box, which can never
        // reach up there) is over an `.allday-col`, this drag is a
        // cross-boundary move-to-all-day candidate. Skip the normal
        // top/column tracking entirely while hovering it (see this file's
        // own header comment for why) and just track which column would
        // receive the drop.
        const alldayCols = Array.from(document.querySelectorAll(".allday-col"));
        let hoverAllDay = null;
        for (const c of alldayCols) {
          const r = c.getBoundingClientRect();
          if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
            hoverAllDay = c;
            break;
          }
        }
        alldayCols.forEach((c) => c.classList.toggle("drop-hover", c === hoverAllDay));
        if (hoverAllDay) {
          dropAllDayCol = hoverAllDay;
          document.querySelectorAll(".time-col.drop-hover").forEach((c) => c.classList.remove("drop-hover"));
          return;
        }
        dropAllDayCol = null;

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
      const wasResize = mode === "resize";
      mode = null;
      el.classList.remove("dragging");
      document.querySelectorAll(".time-col.drop-hover").forEach((c) => c.classList.remove("drop-hover"));
      document.querySelectorAll(".allday-col.drop-hover").forEach((c) => c.classList.remove("drop-hover"));
      if (!dragged) return; // was a click -- let the href navigate normally

      // Slice 4: dropped on the all-day row instead of a time slot -- flip
      // to all_day, drop the time-of-day, reuse the same reschedule
      // endpoint (its own comment covers the new optional `all_day` field).
      // Never reached for a resize (dropAllDayCol is only ever set inside
      // the mode === "move" branch of move() above).
      if (!wasResize && dropAllDayCol) {
        // Week's `.allday-col` carries its own `data-date`; Day's doesn't
        // (there's only ever one column, so no per-column date to disambiguate)
        // -- fall back to the time-col the event started in, which is
        // necessarily the same day on a single-day Day view.
        const day = dropAllDayCol.dataset.date || (startCol && startCol.dataset.date);
        dropAllDayCol = null;
        if (day) {
          const uid = el.dataset.uid;
          fetch(`/events/${uid}/reschedule`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ start_at: `${day}T00:00:00`, end_at: null, all_day: true }),
          }).then((resp) => {
            if (!resp.ok) throw new Error("reschedule failed");
            window.ccApi.dispatchChange({ type: "event", action: "move", uid: uid });
          }).catch(() => {
            el.style.top = origTop + "px";
            el.style.height = origHeight + "px";
            window.ccToast({ message: "Could not save that move. Reverted.", variant: "error" });
          });
          return;
        }
        // No date to attribute the drop to (shouldn't happen given the
        // startCol fallback above, but fall through to the normal timed
        // reschedule below rather than silently drop the move) --
        // `top`/`height`/`currentCol` are still whatever they last were
        // before the all-day-row hover branch in move() took over.
      }

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

      // Optimistic during the drag itself, same as Kanban's drag-and-drop
      // (tasks_board.js) -- the position on screen is already correct the
      // instant the pointer is released (that's what the whole drag was
      // doing), so there's no visible flash waiting on the network before
      // the block appears to land. On success, though, dispatch the
      // app-wide change event instead of patching this one element by
      // hand: async_calendar.js's listener re-fetches the whole
      // #week-grid/#day-grid region, which re-runs grid_layout.layout_day
      // server-side and so fixes up `left_pct`/`width_pct` for every event
      // in the column -- not just this one's label -- covering both the
      // dragged event and whatever it used to (or now does) overlap with.
      // Only revert (back to the exact day/top/height this drag started
      // from) and reload on an actual failure, so the one case that still
      // does a full reload is also the one case where the user needs to
      // see the server's real, authoritative state rather than trust the
      // optimistic guess.
      fetch(`/events/${uid}/reschedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start_at: `${day}T${minutesToHHMMSS(startMin)}`,
          end_at: `${day}T${minutesToHHMMSS(endMin)}`,
        }),
      }).then((resp) => {
        if (!resp.ok) throw new Error("reschedule failed");
        window.ccApi.dispatchChange({ type: "event", action: "move", uid: uid });
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
  //
  // init() is re-invocable: async_calendar.js re-runs it after swapping in
  // a fresh #week-grid region (async-CRUD, features/async-crud.md) so the
  // newly-rendered event blocks and create-cols get bound again. It must
  // only ever run over fresh DOM (the region swap guarantees that) --
  // running it twice on the same elements would double-attach handlers.
  function init() {
    document.querySelectorAll(".time-event:not(.work-allocation)").forEach(setupEvent);
    document.querySelectorAll(".calendar-create-col").forEach(setupCreateCol);
  }

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

  // (A `minutesToDisplayTime` 12-hour-format helper used to live here,
  // feeding the drag-resize handler's `.te-time` label patch below. That
  // patch is gone now -- a successful move/resize dispatches the app-wide
  // change event instead, so async_calendar.js's region refresh
  // re-renders the label server-side, honoring 12h/24h the same way the
  // rest of the page's `fmt_time` filter already does. Removed rather
  // than left dead.)

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
  function setupCreateCol(col) {
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
  }

  init();
  window.CCWeekGrid = { init: init };
})();
