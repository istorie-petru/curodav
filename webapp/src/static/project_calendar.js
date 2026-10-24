
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
      // Item 11 redesign: the row now carries its own "+"/"..." controls
      // (`.unscheduled-row-actions`, _unscheduled_task_item.html) -- a
      // pointerdown there must fall through untouched (native button
      // click/form submit), not be swallowed into a drag-start, same
      // "let this one child's own click through" carve-out setupBlock's
      // own pointerdown handler already has for `.work-allocation-delete`
      // below.
      if (e.target.closest(".unscheduled-row-actions")) return;
      e.preventDefault();
      setSheet(false);
      const ghost = item.cloneNode(true);
      ghost.classList.add("drag-ghost");
      document.body.appendChild(ghost);
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

    // Touch: a long press arms the drag (a short swipe still scrolls the sheet); mouse and pen start at once.
    item.addEventListener("pointerdown", (e) => { if (e.pointerType !== "touch") begin(e); });
    if (window.CCTouchHold) {
      window.CCTouchHold.bind(item, (p) => begin({ button: 0, target: item, preventDefault() {}, clientX: p.clientX, clientY: p.clientY }));
    }
  }

  // Phone planner: the Unscheduled work list is a sheet rising from the bottom bar (CSS hides it on desktop).
  function setSheet(open) {
    const panel = document.getElementById("unscheduled-panel");
    const handle = document.getElementById("planner-sheet-handle");
    if (panel) panel.classList.toggle("is-open", open);
    if (handle) handle.setAttribute("aria-expanded", open ? "true" : "false");
  }
  document.addEventListener("click", (e) => {
    const panel = document.getElementById("unscheduled-panel");
    if (!panel) return;
    if (e.target.closest("#planner-sheet-handle")) setSheet(!panel.classList.contains("is-open"));
    else if (e.target.closest("#planner-sheet-close")) setSheet(false);
    else if (panel.classList.contains("is-open") && !panel.contains(e.target)) setSheet(false);
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
    // Item 11 redesign: the unscheduled row's own "+" (add another session)
    // and "..." menu's "Remove latest session" -- same async-crud
    // interception as the work-allocation delete form just above (a plain
    // submit would 303-reload the whole page; routers/tasks.py's
    // add_work_allocation/remove_latest_work_allocation are dual-mode for
    // exactly this). Both already carry a `next` hidden field/fields dict
    // from the template, but postAction only needs `date_` -- the server
    // route's own redirect fallback (unused here) is what actually reads
    // `next`.
    document.querySelectorAll(".unscheduled-add-session-form").forEach((form) => {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        postAction(form.action, { date_: cfg.weekDate }, "create");
      });
    });
    document.querySelectorAll(".unscheduled-remove-latest-form").forEach((form) => {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        postAction(form.action, { date_: cfg.weekDate }, "unschedule");
      });
    });
    // The row's own "..." kebab (_action_menu.html, static/app.js's shared
    // .action-menu convention) needs the same re-bind-after-swap treatment
    // every other interactive element in this region gets.
    if (window.CCActionMenu) window.CCActionMenu.init();
  }

  init();
  window.CCProjectCalendar = { init: init };
})();