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
//    1b. (2026-09-10, audit-fixes-2.1.md direct request, superseded same
//    day -- see end()'s own comment) A plain click on the same list item --
//    released with no drag past DRAG_THRESHOLD_PX -- opens the task's view
//    modal, same as interaction 4 does for a placed `.work-allocation`
//    block. Adding another undated session now happens from that modal's
//    own Work sessions card (its "+" button), not from a click on this
//    panel.
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
  // "Hide sleep hours in Planner" (static/sleep_collapse.js) -- same
  // collapsed-height clamp and pixel->real-minute fix as static/
  // calendar.js's identical constants, see that file's own comment.
  const DAY_HEIGHT_PX = window.CCSleepCollapse ? window.CCSleepCollapse.dayHeightPx(PX_PER_HOUR) : 24 * PX_PER_HOUR;
  const toRealMin = window.CCSleepCollapse ? window.CCSleepCollapse.toReal : (m) => m;
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

  // async-CRUD (features/async-crud.md): work-allocation create/move/
  // delete used to submit a real hidden <form> and let the 303 redirect
  // reload the whole page. Now they POST through ccApi (X-Requested-With:
  // fetch -> the mutation endpoint returns JSON) and dispatch the change
  // event; the week view's listener (async_calendar.js) re-renders the
  // #week-grid region and re-inits these bindings instead of reloading.
  // `change.type` is "task" -- an allocation is a task's scheduling, and
  // the week grid re-renders from the task/event tables together.
  function postAction(action, fields, actionName) {
    const body = new FormData();
    Object.entries(fields).forEach(([name, value]) => body.append(name, value));
    window.ccApi
      .post(action, body, { change: { type: "task", action: actionName } })
      .catch((err) => {
        window.ccToast({ message: err.message || "Could not save that change.", variant: "error" });
      });
  }

  // The planning grids' scroll container. Auto-scroll reads its viewport
  // rect for the edge test and scrolls it by .scrollTop. `let`, re-queried
  // by init() -- a region swap detaches the old .time-grid-wrap.
  let scroller = document.querySelector(".time-grid-wrap");

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

  function setupUnscheduledItem(item) {
    let drag = null; // active create-drag state, or null when idle

    function begin(e) {
      if (e.button !== 0) return;
      e.preventDefault();
      const ghost = item.cloneNode(true);
      ghost.classList.add("drag-ghost");
      document.body.appendChild(ghost);
      // The actual drop target preview: a real grid-anchored box, always
      // DEFAULT_BLOCK_MINUTES tall (the block a drop actually creates --
      // see end()'s own identical snap/height math) -- NOT the 30-minute
      // CREATE_SNAP_PX the drop *position* snaps to. Reuses calendar.js's
      // own `.schedule-ghost` look for visual consistency. Direct feedback
      // (2026-08-14, after the merged Week view started also loading
      // calendar.js): calendar.js's own hover-preview ghost is 30 minutes
      // tall (its own click-to-create default) and was rendering on top of
      // this drag since the merged grid columns now carry
      // `.calendar-create-col` too -- see the `window.__ccGridDragActive`
      // suppression below and calendar.js's own check of it.
      const slotGhost = document.createElement("div");
      slotGhost.className = "schedule-ghost";
      slotGhost.style.display = "none";
      item.classList.add("item-dragging");
      drag = { startX: e.clientX, startY: e.clientY, ghost, slotGhost, hoverCol: null, dragged: false };
      window.__ccGridDragActive = true;
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
      if (hover) {
        if (drag.slotGhost.parentNode !== hover) hover.appendChild(drag.slotGhost);
        const r = hover.getBoundingClientRect();
        const rawTop = e.clientY - r.top;
        const startPx = Math.max(0, Math.min(DAY_HEIGHT_PX - CREATE_SNAP_PX, snap(rawTop, CREATE_SNAP_PX)));
        const blockPx = (PX_PER_HOUR / 60) * DEFAULT_BLOCK_MINUTES;
        drag.slotGhost.style.top = startPx + "px";
        drag.slotGhost.style.height = blockPx + "px";
        drag.slotGhost.style.display = "block";
      } else {
        drag.slotGhost.style.display = "none";
      }
      edgeScroll(e);
    }

    function finish() {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      document.removeEventListener("pointercancel", cancel);
      stopEdgeScroll();
      window.__ccGridDragActive = false;
      if (drag) {
        drag.ghost.parentNode.removeChild(drag.ghost);
        if (drag.slotGhost.parentNode) drag.slotGhost.parentNode.removeChild(drag.slotGhost);
        item.classList.remove("item-dragging");
        document.querySelectorAll(".project-calendar-col.drop-hover").forEach((c) => c.classList.remove("drop-hover"));
        drag = null;
      }
    }

    function end(e) {
      const wasDrag = drag && drag.dragged;
      const col = drag && drag.hoverCol;
      finish();
      if (!wasDrag) {
        // A plain click (no drag past DRAG_THRESHOLD_PX) -- audit-
        // fixes-2.1.md (2026-09-10, direct request, second pass same day):
        // "for any pill inside it, the user could click it and open the
        // task view modal window." This item briefly (same session, same
        // day) used a plain click to add one more undated session instead
        // -- that conflicted with this later, more specific request for
        // the same gesture, so per direct decision the click-to-add
        // behavior is gone: opening the task modal wins, and adding a
        // session now happens from the modal's own Work sessions card
        // ("+" button, `_task_work_allocations.html`) instead. Same
        // taskUrlBase + CCModal convention interaction 4 already uses for
        // a placed `.work-allocation` block's click-to-open.
        if (cfg.taskUrlBase && item.dataset.taskUid) {
          const url = cfg.taskUrlBase + item.dataset.taskUid;
          if (window.CCModal) {
            window.CCModal.open(url, item);
          } else {
            window.location.href = url;
          }
        }
        return;
      }
      if (!col) return; // a drag that ended off any column -- drop nothing
      // Time from the pointer's Y relative to the hovered column's rect.
      // getBoundingClientRect is viewport-relative, so this stays correct
      // even if the grid auto-scrolled during the drag. Same snap as the
      // slot-preview ghost in move() above, so what was shown is exactly
      // what gets created.
      const rect = col.getBoundingClientRect();
      const rawTop = e.clientY - rect.top;
      const startPx = Math.max(0, Math.min(DAY_HEIGHT_PX - CREATE_SNAP_PX, snap(rawTop, CREATE_SNAP_PX)));
      const startMin = toRealMin(Math.round((startPx / PX_PER_HOUR) * 60));
      const endMin = startMin + DEFAULT_BLOCK_MINUTES;
      const day = col.dataset.date;
      // Sleep Time / Leisure Time warning (static/time_blocks.js) -- see
      // calendar.js's identical call for the full rationale; a no-op when
      // the page renders no cc-time-blocks tag (only calendar_week.html/
      // calendar_day.html do -- /week and the project Week Calendar don't).
      if (window.ccTimeBlocks) window.ccTimeBlocks.warnIfOverlapping(day, startMin, endMin);
      postAction(cfg.createUrl, {
        task_uid: item.dataset.taskUid,
        start_at: `${day}T${minutesToHHMMSS(startMin)}`,
        end_at: `${day}T${minutesToHHMMSS(endMin)}`,
        date_: cfg.weekDate,
      }, "create");
    }

    function cancel() {
      finish(); // interruption: drop everything, submit nothing
    }

    item.addEventListener("pointerdown", begin);
  }

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
        // See interaction 1's own begin()/finish() for why -- calendar.js's
        // 30-minute hover-preview ghost must not render while a block is
        // being moved/resized across the merged Week view's grid either.
        window.__ccGridDragActive = true;
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
      window.__ccGridDragActive = false;
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
      // see routers/*.py's delete_allocation), so the region refresh shows
      // the task back in the "Unscheduled work" list at the SAME session
      // count.
      if (wasOverUnscheduled && cfg.deleteUrlBase) {
        postAction(cfg.deleteUrlBase + el.dataset.uid + "/delete", {
          date_: cfg.weekDate,
        }, "unschedule");
        return;
      }

      const top = parseFloat(el.style.top) || 0;
      const height = parseFloat(el.style.height) || SNAP_PX;
      const startMin = toRealMin(Math.round((top / PX_PER_HOUR) * 60));
      const endMin = toRealMin(Math.round(((top + height) / PX_PER_HOUR) * 60));
      const day = currentCol.dataset.date;
      const uid = el.dataset.uid;
      if (window.ccTimeBlocks) window.ccTimeBlocks.warnIfOverlapping(day, startMin, endMin);
      postAction(cfg.moveUrlBase + uid + "/move", {
        start_at: `${day}T${minutesToHHMMSS(startMin)}`,
        end_at: `${day}T${minutesToHHMMSS(endMin)}`,
        date_: cfg.weekDate,
      }, "move");
    }

    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      // The `.te-name` title is a plain span now, not a nested <a> (direct
      // feedback: "why can't the whole div be a link and moved at the same
      // time" -- a real <a> couldn't wrap the delete <form>/<button>
      // anyway), so there's no native link click to preserve here anymore
      // -- the whole block, title included, is one uniform drag target,
      // same as an ordinary .time-event. Only the delete button still
      // needs to let its own click through untouched.
      if (e.target.closest(".work-allocation-delete")) return;
      e.preventDefault();
      begin(e, handle && e.target === handle);
    });
  }

  // init() is re-invocable: async_calendar.js re-runs it after swapping in
  // a fresh #week-grid region (async-CRUD, features/async-crud.md) so the
  // newly-rendered unscheduled-task items and work-allocation blocks get
  // their pointerdown bindings again, and the scroll container is re-read
  // (a swap detaches the old one). Must only ever run over fresh DOM --
  // running twice on the same elements would double-attach handlers.
  // The per-block "unschedule" X button posts the same endpoint as the
  // drag-onto-panel gesture, so it gets the same async treatment -- without
  // intercepting here, its native submit would 303-reload the whole page,
  // breaking the async week grid's no-reload contract (features/
  // async-crud.md). data-confirmed="1" already exempts it from app.js's
  // generic "/delete" confirm sheet, so only this interception + the region
  // refresh is left.
  function init() {
    scroller = document.querySelector(".time-grid-wrap");
    document.querySelectorAll(".unscheduled-task-item").forEach(setupUnscheduledItem);
    document.querySelectorAll(".work-allocation").forEach(setupBlock);
    document.querySelectorAll(".work-allocation-delete").forEach((form) => {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        postAction(form.action, { date_: cfg.weekDate }, "unschedule");
      });
    });
  }

  init();
  window.CCProjectCalendar = { init: init };
})();