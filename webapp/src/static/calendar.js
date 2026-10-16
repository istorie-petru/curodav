
(function () {
  const grid = document.querySelector(".time-col");
  if (!grid) return;

  const PX_PER_HOUR = Number(document.body.dataset.pxPerHour || 48);
  const SNAP_MINUTES = 15;
  const SNAP_PX = (PX_PER_HOUR / 60) * SNAP_MINUTES;
  // "Hide sleep hours in Planner" (static/sleep_collapse.js, Week view
  // only -- undefined on Day, where both fall back to the plain 24h
  // behavior this file always had). DAY_HEIGHT_PX shrinks to match the
  // grid's own collapsed height so drag clamping can't push an event past
  // the bottom of the now-shorter column; toRealMin converts a final
  // pixel-derived minutes value back to the real clock time it represents
  // before it's saved -- see that file's own header comment for why this
  // is necessary, not optional, once a window's been collapsed out.
  const DAY_HEIGHT_PX = window.CCSleepCollapse ? window.CCSleepCollapse.dayHeightPx(PX_PER_HOUR) : 24 * PX_PER_HOUR;
  const toRealMin = window.CCSleepCollapse ? window.CCSleepCollapse.toReal : (m) => m;
  const CLICK_THRESHOLD_PX = 4;
  const HOLD_MS = 250; // touch: hold this long before a move starts
  const HOLD_SLOP_PX = 8; // touch: finger travel that counts as a scroll, not a hold

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
      if (!wasResize && dropAllDayCol && el.dataset.occurrence) {
        dropAllDayCol = null;
        el.style.top = origTop + "px";
        el.style.height = origHeight + "px";
        if (currentCol !== startCol) startCol.appendChild(el);
        window.ccToast({ message: "A repeating event cannot be dragged to all day. Open it to edit.", variant: "error" });
        return;
      }
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
      const startMin = toRealMin(Math.round((top / PX_PER_HOUR) * 60));
      const endMin = toRealMin(Math.round(((top + height) / PX_PER_HOUR) * 60));
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
      const startAt = `${day}T${minutesToHHMMSS(startMin)}`;
      const endAt = `${day}T${minutesToHHMMSS(endMin)}`;
      const occurrence = el.dataset.occurrence;
      // A repeating event moves only the occurrence that was dragged; the toast offers the later ones too.
      const request = occurrence
        ? fetch(`/events/${uid}/occurrences/move`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" },
            body: new URLSearchParams({ occurrence_date: occurrence, start_at: startAt, end_at: endAt }),
          })
        : fetch(`/events/${uid}/reschedule`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ start_at: startAt, end_at: endAt }),
          });
      request.then((resp) => {
        if (!resp.ok) throw new Error("reschedule failed");
        window.ccApi.dispatchChange({ type: "event", action: "move", uid: uid });
        if (!el.dataset.series) return;
        // A repeating event moves only the occurrence that was dragged; the toast offers the later ones too.
        const fromStart = el.dataset.start;
        window.ccToast({
          message: "Moved this event only.",
          actionLabel: "Move all future ones",
          duration: 10000,
          onAction: () => {
            fetch(`/events/${uid}/move-following`, {
              method: "POST",
              headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "fetch" },
              body: new URLSearchParams({ from_start: fromStart, start_at: startAt }),
            }).then((r) => {
              if (!r.ok) return; // nothing to offer or show: the later events simply stay where they are
              window.ccApi.dispatchChange({ type: "event", action: "move", uid: uid });
              window.ccToast({ message: "Moved this and all future events." });
            }).catch(() => {});
          },
        });
      }).catch(() => {
        el.style.top = origTop + "px";
        el.style.height = origHeight + "px";
        if (droppedCol !== startCol) startCol.appendChild(el);
        currentCol = startCol;
        window.ccToast({ message: "Could not save that move. Reverted.", variant: "error" });
      });
    }

    // Touch: a short hold (HOLD_MS) arms the move so a swipe over an event
    // still scrolls the grid; after arming, touchmove is cancelled so the
    // finger drags the block instead.
    let holdTimer = null;
    let armed = false;
    function cancelHold() {
      clearTimeout(holdTimer);
      holdTimer = null;
      document.removeEventListener("pointermove", holdMove);
      document.removeEventListener("pointerup", cancelHold);
      document.removeEventListener("pointercancel", cancelHold);
    }
    let holdX = 0;
    let holdY = 0;
    function holdMove(e) {
      if (Math.abs(e.clientX - holdX) > HOLD_SLOP_PX || Math.abs(e.clientY - holdY) > HOLD_SLOP_PX) cancelHold();
    }
    el.addEventListener("touchmove", (e) => {
      if (armed && e.cancelable) e.preventDefault();
    }, { passive: false });
    el.addEventListener("pointerup", () => { armed = false; });
    el.addEventListener("pointercancel", () => { armed = false; });
    el.addEventListener("contextmenu", (e) => { if (armed || holdTimer) e.preventDefault(); });

    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      if (e.pointerType === "touch") {
        holdX = e.clientX;
        holdY = e.clientY;
        const isResize = handle && e.target === handle;
        document.addEventListener("pointermove", holdMove);
        document.addEventListener("pointerup", cancelHold);
        document.addEventListener("pointercancel", cancelHold);
        holdTimer = setTimeout(() => {
          cancelHold();
          armed = true;
          if (navigator.vibrate) navigator.vibrate(10);
          el.classList.add("dragging");
          begin({ clientX: holdX, clientY: holdY }, isResize);
        }, HOLD_MS);
        return;
      }
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
      const startMin = toRealMin(Math.round((top / PX_PER_HOUR) * 60));
      const endMin = toRealMin(Math.round(((top + height) / PX_PER_HOUR) * 60));
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
