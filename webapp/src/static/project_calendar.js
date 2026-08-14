// Project Week Calendar (1.4 slice 3, templates/project_calendar.html) --
// two interactions on top of the same time-grid geometry calendar.js
// already lays out server-side (grid_layout.py):
//
// 1. Drag an "unscheduled task" list item onto a `.project-calendar-col`
//    to create a work allocation there (default 1-hour block, snapped to
//    30 minutes) -- a POINTER-based drag (pointerdown/pointermove/pointerup,
//    a fixed-position ghost clone of the item follows the cursor, the hovered
//    column lights up, and near the grid's top/bottom edge it auto-scrolls
//    so a tall grid is fully reachable), NOT the native HTML5 drag-and-drop
//    this page used to use -- native DnD is unreliable on touch and doesn't
//    let a drag survive scrolling. Same drop math as before: the time is
//    read from the pointer's Y relative to the column's rect (viewport-
//    relative, so it stays correct while the grid auto-scrolls) and a plain
//    hidden form submits to routers/projects.py::create_allocation.
// 2. Drag an existing `.work-allocation` block to move it, or its
//    `.te-resize-handle` to resize it -- same pointer-based drag model as
//    static/calendar.js's Week/Day grid (pointerdown/pointermove/pointerup
//    on `document`, 15-minute snap), but on release this submits a plain
//    hidden form to routers/projects.py::move_allocation (a form-POST +
//    redirect, matching every other action on this page) instead of that
//    file's JSON/fetch `/events/{uid}/reschedule` contract -- the page
//    reloads either way, so there's no reason to duplicate the more complex
//    optimistic-update/revert logic that route's own JS needs. A move is
//    scroll-aware: if the grid auto-scrolls mid-drag (edge scroll below),
//    the block keeps the pointer's intended time instead of staying put
//    while the content slides under it. A pointercancel (interruption,
//    lost capture) reverts the block to where it was and submits nothing.
// 3. (Optional, config-driven) Drag a `.work-allocation` block off the
//    grid and onto the "Unscheduled work" panel to UNSCHEDULE it -- the
//    inverse of interaction 1. Set `window.PROJECT_CALENDAR.deleteUrlBase`
//    (the allocation-delete endpoint base) and `unscheduleDropSelector`
//    (a CSS selector for the unscheduled panel) to enable it; while the
//    drag is over that panel the block highlights it, and releasing there
//    submits the delete form instead of the move form. Releasing anywhere
//    else keeps the normal move/resize behavior. The "delete" endpoint
//    doesn't actually delete the session -- it clears this ONE session's
//    start/end back to undated (`db.unschedule_work_allocation`), so the
//    reload shows the task back on the panel at the SAME session count it
//    already had (just one more of them now undated), never fewer.
// 4. (Optional, config-driven) A plain click on a `.work-allocation`
//    block's own body (not its title link, not the delete button, not a
//    drag, not the resize handle) opens the block's task VIEW modal -- so
//    reaching the task needs no smaller click target. Set
//    `window.PROJECT_CALENDAR.taskUrlBase` (e.g. "/tasks/") to enable it;
//    the block's `data-task-uid` is appended. The block's `.te-name` title
//    link carries the same href, so the whole block is one target.
//
// All of these submit a real form and let the resulting redirect reload
// the page -- the simplest way to guarantee what's shown always matches
// whatever the server actually persisted (including a rejected drop, e.g.
// a task that doesn't belong to this project), same reasoning
// static/calendar.js documents for its own revert-on-failure path.

(function () {
  const cfg = window.PROJECT_CALENDAR;
  if (!cfg) return;

  const PX_PER_HOUR = Number(document.body.dataset.pxPerHour || 48);
  const SNAP_MINUTES = 15;
  const SNAP_PX = (PX_PER_HOUR / 60) * SNAP_MINUTES;
  const DAY_HEIGHT_PX = 24 * PX_PER_HOUR;
  const CREATE_SNAP_MINUTES = 30;
  const CREATE_SNAP_PX = (PX_PER_HOUR / 60) * CREATE_SNAP_MINUTES;
  const DEFAULT_BLOCK_MINUTES = 60;
  const DRAG_THRESHOLD_PX = 4;
  // Edge auto-scroll (interaction 1 & 2): while the pointer is within this
  // many px of the scrollable grid's top/bottom, scroll it this many px per
  // animation frame -- so a drop or a move can reach any time on a grid
  // taller than the screen without the drag dying partway.
  const SCROLL_EDGE_PX = 48;
  const SCROLL_STEP_PX = 10;

  function snap(px, unit) {
    return Math.round(px / unit) * unit;
  }

  function minutesToHHMMSS(totalMinutes) {
    totalMinutes = Math.max(0, Math.min(24 * 60 - 1, totalMinutes));
    const h = Math.floor(totalMinutes / 60);
    const m = totalMinutes % 60;
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") + ":00";
  }

  function submitForm(action, fields) {
    const form = document.createElement("form");
    form.method = "post";
    form.action = action;
    form.style.display = "none";
    Object.entries(fields).forEach(([name, value]) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      form.appendChild(input);
    });
    document.body.appendChild(form);
    form.submit();
  }

  // The planning grids' scroll container. Auto-scroll reads its viewport
  // rect for the edge test and scrolls it by .scrollTop.
  const scroller = document.querySelector(".time-grid-wrap");

  // Shared edge auto-scroll for both drag systems. requestAnimationFrame
  // loop only while the pointer is inside an edge band; stopping (or a
  // pointer leaving the band) cancels it.
  let scrollLoop = 0;
  let scrollDir = 0;
  function edgeScroll(e) {
    if (!scroller) return;
    const r = scroller.getBoundingClientRect();
    if (e.clientY < r.top + SCROLL_EDGE_PX) {
      scrollDir = -SCROLL_STEP_PX;
    } else if (e.clientY > r.bottom - SCROLL_EDGE_PX) {
      scrollDir = SCROLL_STEP_PX;
    } else {
      scrollDir = 0;
    }
    if (scrollDir && !scrollLoop) {
      scrollLoop = requestAnimationFrame(function tick() {
        if (scrollDir) scroller.scrollTop += scrollDir;
        scrollLoop = scrollDir ? requestAnimationFrame(tick) : 0;
      });
    }
  }
  function stopEdgeScroll() {
    scrollDir = 0;
    if (scrollLoop) {
      cancelAnimationFrame(scrollLoop);
      scrollLoop = 0;
    }
  }

  // ------------------------------------------------------------------ //
  // 1. Drag an unscheduled task onto the grid -> create a work allocation
  // ------------------------------------------------------------------ //

  document.querySelectorAll(".unscheduled-task-item").forEach((item) => {
    let drag = null; // active create-drag state, or null when idle

    function begin(e) {
      // The −/+ stepper forms live inside the item; a pointerdown on them
      // is a button press, not the start of a drag -- let it click through.
      if (e.button !== 0) return;
      if (e.target.closest(".unscheduled-stepper")) return;
      e.preventDefault();
      const ghost = item.cloneNode(true);
      ghost.classList.add("drag-ghost");
      document.body.appendChild(ghost);
      item.classList.add("item-dragging");
      drag = { startX: e.clientX, startY: e.clientY, ghost, hoverCol: null, dragged: false };
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", end);
      document.addEventListener("pointercancel", cancel);
    }

    function move(e) {
      if (!drag) return;
      const dx = e.clientX - drag.startX;
      const dy = e.clientY - drag.startY;
      if (!drag.dragged && (Math.abs(dx) > DRAG_THRESHOLD_PX || Math.abs(dy) > DRAG_THRESHOLD_PX)) {
        drag.dragged = true;
        drag.ghost.style.display = "block";
      }
      if (!drag.dragged) return;
      drag.ghost.style.left = e.clientX + 12 + "px";
      drag.ghost.style.top = e.clientY + 12 + "px";
      const cols = Array.from(document.querySelectorAll(".project-calendar-col"));
      let hover = null;
      for (const col of cols) {
        const r = col.getBoundingClientRect();
        if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
          hover = col;
          break;
        }
      }
      cols.forEach((c) => c.classList.toggle("drop-hover", c === hover));
      drag.hoverCol = hover;
      edgeScroll(e);
    }

    function finish() {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      document.removeEventListener("pointercancel", cancel);
      stopEdgeScroll();
      if (drag) {
        drag.ghost.parentNode.removeChild(drag.ghost);
        item.classList.remove("item-dragging");
        document.querySelectorAll(".project-calendar-col.drop-hover").forEach((c) => c.classList.remove("drop-hover"));
        drag = null;
      }
    }

    function end(e) {
      const wasDrag = drag && drag.dragged;
      const col = drag && drag.hoverCol;
      finish();
      if (!wasDrag || !col) return; // a click (not a drop)
      // Time from the pointer's Y relative to the hovered column's rect.
      // getBoundingClientRect is viewport-relative, so this stays correct
      // even if the grid auto-scrolled during the drag.
      const rect = col.getBoundingClientRect();
      const rawTop = e.clientY - rect.top;
      const startPx = Math.max(0, Math.min(DAY_HEIGHT_PX - CREATE_SNAP_PX, snap(rawTop, CREATE_SNAP_PX)));
      const startMin = Math.round((startPx / PX_PER_HOUR) * 60);
      const endMin = startMin + DEFAULT_BLOCK_MINUTES;
      const day = col.dataset.date;
      submitForm(cfg.createUrl, {
        task_uid: item.dataset.taskUid,
        start_at: `${day}T${minutesToHHMMSS(startMin)}`,
        end_at: `${day}T${minutesToHHMMSS(endMin)}`,
        date_: cfg.weekDate,
      });
    }

    function cancel() {
      finish(); // interruption: drop everything, submit nothing
    }

    item.addEventListener("pointerdown", begin);
  });

  // ------------------------------------------------------------------ //
  // 2. Move / resize an existing work-allocation block
  // ------------------------------------------------------------------ //

  function setupBlock(el) {
    const handle = el.querySelector(".te-resize-handle");
    let mode = null; // "move" | "resize"
    let startX = 0;
    let startY = 0;
    let origTop = 0;
    let origHeight = 0;
    let origCol = null;
    let scrollStart = 0;
    let currentCol = el.closest(".project-calendar-col");
    let dragged = false;
    let overUnscheduled = false; // drag is hovering the unscheduled-work panel
    // Optional config (see the header comment): a delete endpoint base +
    // selector for the panel that a moved block can be dropped on to
    // unschedule it. Either one missing disables interaction 3 entirely.
    const unscheduleTarget = cfg.unscheduleDropSelector ? document.querySelector(cfg.unscheduleDropSelector) : null;
    // Optional config (see the header comment): a click on the block's own
    // body opens its task's view modal (interaction 4). Missing/absent
    // disables it entirely.
    const taskUrlBase = cfg.taskUrlBase;

    function begin(e, isResize) {
      mode = isResize ? "resize" : "move";
      dragged = false;
      overUnscheduled = false;
      startX = e.clientX;
      startY = e.clientY;
      origTop = parseFloat(el.style.top) || 0;
      origHeight = parseFloat(el.style.height) || SNAP_PX;
      origCol = el.closest(".project-calendar-col");
      currentCol = origCol;
      scrollStart = scroller ? scroller.scrollTop : 0;
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", end);
      document.addEventListener("pointercancel", cancel);
    }

    function move(e) {
      if (!mode) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      // How much the grid has scrolled since the drag began -- a move's
      // target time must track the pointer's intent *through* that scroll,
      // not against a frozen start position (see header comment).
      const scrollDelta = scroller ? scroller.scrollTop - scrollStart : 0;
      if (!dragged && (Math.abs(dx) > DRAG_THRESHOLD_PX || Math.abs(dy) > DRAG_THRESHOLD_PX)) {
        dragged = true;
        el.classList.add("dragging");
      }
      if (!dragged) return;

      if (mode === "move") {
        let newTop = snap(origTop + dy + scrollDelta, SNAP_PX);
        newTop = Math.max(0, Math.min(DAY_HEIGHT_PX - origHeight, newTop));
        el.style.top = newTop + "px";

        const cols = Array.from(document.querySelectorAll(".project-calendar-col"));
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

        // Unschedule-drop detection (interaction 3): if the pointer is over
        // the unscheduled-work panel, highlight it instead of a column. The
        // block itself is clamped inside its own column by the math above,
        // so this is purely a hover signal + release-target check -- on
        // release over the panel, end() submits the delete form.
        if (unscheduleTarget) {
          const r = unscheduleTarget.getBoundingClientRect();
          const inside =
            e.clientX >= r.left && e.clientX <= r.right &&
            e.clientY >= r.top && e.clientY <= r.bottom;
          overUnscheduled = inside;
          unscheduleTarget.classList.toggle("unschedule-drop-hover", inside);
        }
      } else {
        let newHeight = snap(origHeight + dy, SNAP_PX);
        newHeight = Math.max(SNAP_PX, Math.min(DAY_HEIGHT_PX - origTop, newHeight));
        el.style.height = newHeight + "px";
      }
      edgeScroll(e);
    }

    function cleanup() {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      document.removeEventListener("pointercancel", cancel);
      stopEdgeScroll();
      el.classList.remove("dragging");
      document.querySelectorAll(".project-calendar-col.drop-hover").forEach((c) => c.classList.remove("drop-hover"));
      if (unscheduleTarget) unscheduleTarget.classList.remove("unschedule-drop-hover");
    }

    function cancel() {
      // pointercancel (interruption / lost capture): put the block back
      // where the drag began and submit nothing -- never half-commit a move.
      if (mode) {
        el.style.top = origTop + "px";
        el.style.height = origHeight + "px";
        if (el.closest(".project-calendar-col") !== origCol) origCol.appendChild(el);
      }
      cleanup();
      mode = null;
    }

    function end() {
      if (!mode) return;
      const wasResize = mode === "resize";
      const wasDragged = dragged;
      const wasOverUnscheduled = overUnscheduled;
      cleanup();
      mode = null;
      if (!wasDragged) {
        // A click, not a drag. Let the title link and the delete button
        // work normally (their pointerdowns never reach begin()); a click
        // on the block's own body opens its task's view modal instead of
        // doing nothing, when configured (interaction 4). A click that
        // started on the resize handle is mode "resize" -- still no
        // navigation, so the handle stays a pure drag affordance.
        if (!wasResize && taskUrlBase && el.dataset.taskUid) {
          const url = taskUrlBase + el.dataset.taskUid;
          if (window.CCModal) {
            window.CCModal.open(url, el);
          } else {
            window.location.href = url;
          }
        }
        return;
      }

      // Released over the unscheduled-work panel -> unschedule this one
      // block (clears its start/end back to undated, doesn't delete it --
      // see routers/*.py's delete_allocation), so the reload shows the task
      // back in the "Unscheduled work" list at the SAME session count.
      if (wasOverUnscheduled && cfg.deleteUrlBase) {
        submitForm(cfg.deleteUrlBase + el.dataset.uid + "/delete", {
          date_: cfg.weekDate,
        });
        return;
      }

      const top = parseFloat(el.style.top) || 0;
      const height = parseFloat(el.style.height) || SNAP_PX;
      const startMin = Math.round((top / PX_PER_HOUR) * 60);
      const endMin = Math.round(((top + height) / PX_PER_HOUR) * 60);
      const day = currentCol.dataset.date;
      const uid = el.dataset.uid;
      submitForm(cfg.moveUrlBase + uid + "/move", {
        start_at: `${day}T${minutesToHHMMSS(startMin)}`,
        end_at: `${day}T${minutesToHHMMSS(endMin)}`,
        date_: cfg.weekDate,
      });
    }

    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      if (e.target.closest(".work-allocation-delete") || e.target.closest(".te-name")) return;
      e.preventDefault();
      begin(e, handle && e.target === handle);
    });
  }

  document.querySelectorAll(".work-allocation").forEach(setupBlock);
})();