// Timeline (Gantt) view interactions (templates/tasks_timeline.html),
// Phase 11 -- port of desktop's `TimelineCanvas` mouse handling
// (features/tasks/timeline_view.py). The layout itself (which row/column
// each element sits in) is computed server-side (timeline_layout.py,
// mirroring desktop's _assign_swimlanes/_compute_range/_bar_rect exactly)
// and rendered as plain positioned DOM elements; this file only handles
// the interactive part -- dragging -- the same split calendar.js /
// grid_layout.py already use for the Week/Day calendar grid.
//
// Every drag here snaps to whole DAYS (not desktop's Day/Week zoom
// distinction -- see timeline_layout.py's module docstring: this port
// has one zoom level, matching desktop's own final state after Day/Month
// zoom were both removed and only "Week zoom" -- day-granularity bars in
// a calendar-aligned window -- remained).
//
// One deliberate UI adaptation from desktop: desktop requires a
// double-click to open a task (a single click starts a drag in a Qt
// canvas with no separate "click" gesture). This app opens every other
// object card with a single click + data-modal; a genuine drag still
// calls preventDefault on the resulting click (same `dragged` flag
// pattern calendar.js's `.time-event` already uses), so a single
// no-movement click opens the task and a press-and-drag reschedules it,
// consistent with how the rest of this app already distinguishes the two.

(function () {
  const canvas = document.getElementById("timeline-canvas");
  if (!canvas) return;

  const DAY_WIDTH = 24;
  const ROW_HEIGHT = 36;
  const HANDLE_WIDTH = 10;
  const CLICK_THRESHOLD_PX = 4;
  const GUTTER_MIN = 60;
  const GUTTER_MAX = 280;
  const GUTTER_STORAGE_KEY = "cc-timeline-gutter-width";

  function isoDate(d) {
    return d.toISOString().slice(0, 10);
  }
  function addDays(iso, n) {
    const d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return isoDate(d);
  }
  function dayDiff(isoA, isoB) {
    const a = new Date(isoA + "T00:00:00Z");
    const b = new Date(isoB + "T00:00:00Z");
    return Math.round((b - a) / 86400000);
  }

  function reload() {
    window.location.reload();
  }

  // ------------------------------------------------------------------ //
  // Gutter column resize -- drag the boundary; persisted client-side
  // only (localStorage), since it's a pure per-device display preference,
  // same category as the calendar's per-device calendar-visibility
  // toggle. Everything else's position is `calc(var(--gutter-w) + Xpx)`
  // (see style.css), so changing one CSS custom property reflows the
  // entire grid instantly with no per-element recomputation needed.
  // ------------------------------------------------------------------ //

  const sep = document.getElementById("timeline-gutter-sep");
  const savedGutter = parseInt(localStorage.getItem(GUTTER_STORAGE_KEY) || "", 10);
  if (savedGutter && savedGutter >= GUTTER_MIN && savedGutter <= GUTTER_MAX) {
    canvas.style.setProperty("--gutter-w", savedGutter + "px");
  }

  // Pointer Events throughout this file (not mouse-only) -- a touch drag
  // does exactly the same thing a mouse drag does here (resize a column,
  // move/resize a bar, drag out a create-range), so there's no reduced-
  // functionality fallback needed, just the same logic driven by an event
  // that also fires for touch/pen. `setPointerCapture` is what makes a
  // finger sliding off the original element (easy on a small touch
  // target) keep delivering move/up events to it anyway, same as the
  // mouse version got "for free" from tracking on `document` instead.
  if (sep) {
    let resizing = false;
    let startX = 0;
    let startWidth = 0;

    sep.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      resizing = true;
      startX = e.clientX;
      startWidth = parseInt(getComputedStyle(canvas).getPropertyValue("--gutter-w"), 10) || 92;
      sep.classList.add("is-resizing");
      sep.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    sep.addEventListener("pointermove", (e) => {
      if (!resizing) return;
      const w = Math.max(GUTTER_MIN, Math.min(GUTTER_MAX, startWidth + (e.clientX - startX)));
      canvas.style.setProperty("--gutter-w", w + "px");
    });
    function endGutterResize() {
      if (!resizing) return;
      resizing = false;
      sep.classList.remove("is-resizing");
      const w = parseInt(getComputedStyle(canvas).getPropertyValue("--gutter-w"), 10);
      localStorage.setItem(GUTTER_STORAGE_KEY, String(w));
    }
    sep.addEventListener("pointerup", endGutterResize);
    sep.addEventListener("pointercancel", endGutterResize);
  }

  // ------------------------------------------------------------------ //
  // Bar drag: move (reschedule, horizontal + vertical-row-pick) and
  // resize (either edge). Hit-testing which mode a press starts in is
  // done in JS from the raw click position, mirroring desktop's
  // `_hit_test` exactly -- including the narrow-bar midpoint split (a
  // bar wider than HANDLE_WIDTH*2 has clear left-handle/right-handle/
  // move zones; a narrower one splits at its own midpoint instead, so a
  // click near the right edge of a short bar is never misread as the
  // left handle just because both handle zones overlap).
  // ------------------------------------------------------------------ //

  function setupBar(bar) {
    const uid = bar.dataset.uid;
    let mode = null; // "move" | "resize_left" | "resize_right"
    let dragged = false;
    let startClientX = 0;
    let startClientY = 0;
    let origLeft = 0;
    let origTop = 0;
    let origWidth = 0;
    let startAt = bar.dataset.start;
    let dueAt = bar.dataset.due;
    // Bug fix ported verbatim from desktop (2026-07-20): a task with no
    // explicit start_at falls back to due_at as its displayed start (see
    // timeline_layout.py's _task_dates, same fallback as _bar_rect on the
    // desktop side). Resizing from the right must freeze that resolved
    // start_at the instant ANY resize begins -- otherwise, since the
    // fallback re-resolves from due_at on every re-render, growing due_at
    // via a right-drag would silently drag start_at along with it and
    // both edges would walk forward together, indistinguishable from a
    // move. This is exactly what start_at/dueAt above already capture
    // (from the rendered data-start, which is already due_at-as-fallback
    // when unset) -- freezing simply means never re-reading it from a
    // fresh fallback mid-drag, only from these captured locals.

    function hitTest(clientX) {
      const rect = bar.getBoundingClientRect();
      const localX = clientX - rect.left;
      const width = rect.width;
      if (width <= HANDLE_WIDTH * 2) {
        return localX < width / 2 ? "resize_left" : "resize_right";
      }
      if (localX <= HANDLE_WIDTH) return "resize_left";
      if (width - localX <= HANDLE_WIDTH) return "resize_right";
      return "move";
    }

    bar.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      mode = hitTest(e.clientX);
      dragged = false;
      startClientX = e.clientX;
      startClientY = e.clientY;
      origLeft = bar.offsetLeft;
      origTop = bar.offsetTop;
      origWidth = bar.offsetWidth;
      startAt = bar.dataset.start;
      dueAt = bar.dataset.due;
      bar.setPointerCapture(e.pointerId);
      e.preventDefault();
    });

    function move(e) {
      if (!mode) return;
      const dx = e.clientX - startClientX;
      const dy = e.clientY - startClientY;
      if (!dragged && (Math.abs(dx) > CLICK_THRESHOLD_PX || Math.abs(dy) > CLICK_THRESHOLD_PX)) {
        dragged = true;
        bar.classList.add("is-dragging");
      }
      if (!dragged) return;

      const deltaDays = Math.round(dx / DAY_WIDTH);

      if (mode === "move") {
        // Horizontal: shift by whole days, day-snapped live (not just on
        // release) -- same "snap while dragging, not only at the end" bar
        // desktop's own history sets for this exact interaction.
        const newLeftPx = origLeft + deltaDays * DAY_WIDTH;
        bar.style.left = newLeftPx + "px";
        // Vertical: smooth per-pixel follow while dragging (row
        // reassignment itself only happens on release, via a full
        // server-side re-layout -- see mouseup below), matching
        // desktop's _drag_y_offset/_bar_rect split exactly.
        bar.style.top = origTop + dy + "px";
      } else if (mode === "resize_left") {
        const newLeftPx = Math.max(0, origLeft + deltaDays * DAY_WIDTH);
        const newWidth = origLeft + origWidth - newLeftPx;
        if (newWidth >= DAY_WIDTH) {
          bar.style.left = newLeftPx + "px";
          bar.style.width = newWidth + "px";
        }
      } else if (mode === "resize_right") {
        const newWidth = Math.max(DAY_WIDTH, origWidth + deltaDays * DAY_WIDTH);
        bar.style.width = newWidth + "px";
      }
    }

    async function up(e) {
      if (!mode) return;
      const finishedMode = mode;
      mode = null;
      bar.classList.remove("is-dragging");
      if (!dragged) return; // a plain click -- let it fall through to data-modal

      const deltaDaysFinal = Math.round((e.clientX - startClientX) / DAY_WIDTH);
      const deltaRows = Math.round((e.clientY - startClientY) / ROW_HEIGHT);

      if (finishedMode === "move") {
        const newStart = addDays(startAt, deltaDaysFinal);
        const duration = dayDiff(startAt, dueAt);
        const newDue = addDays(newStart, duration);
        await fetch(`/tasks/${uid}/timeline-reschedule`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ start_at: newStart, due_at: newDue }),
        }).catch(() => {});
        if (deltaRows !== 0) {
          // A vertical drag can only ever move a task within its OWN
          // label's swimlane block -- never hit-test the DOM for whatever
          // happens to be under the cursor (which could be a different
          // label's rows entirely). Same formula as desktop's
          // mouseReleaseEvent: original local lane + row delta, clamped
          // to a handful of rows past the block's current size so a
          // stray huge drag can't pin the task hundreds of rows away by
          // accident, while still allowing deliberately opening a few
          // empty rows for visual grouping.
          const origLocalIdx = parseInt(bar.dataset.localIdx, 10) || 0;
          const groupLanes = parseInt(bar.dataset.groupLanes, 10) || 1;
          let targetLocal = origLocalIdx + deltaRows;
          targetLocal = Math.max(0, Math.min(targetLocal, groupLanes + 4));
          await fetch(`/tasks/${uid}/timeline-lane`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ lane: targetLocal }),
          }).catch(() => {});
        }
      } else if (finishedMode === "resize_left") {
        const newStart = addDays(startAt, deltaDaysFinal);
        if (dayDiff(newStart, dueAt) >= 0) {
          await fetch(`/tasks/${uid}/timeline-reschedule`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ start_at: newStart, due_at: dueAt }),
          }).catch(() => {});
        }
      } else if (finishedMode === "resize_right") {
        const newDue = addDays(dueAt, deltaDaysFinal);
        if (dayDiff(startAt, newDue) >= 0) {
          await fetch(`/tasks/${uid}/timeline-reschedule`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ start_at: startAt, due_at: newDue }),
          }).catch(() => {});
        }
      }
      reload();
    }

    bar.addEventListener("pointermove", move);
    bar.addEventListener("pointerup", up);
    bar.addEventListener("pointercancel", up);

    bar.addEventListener("click", (e) => {
      if (dragged) {
        e.preventDefault();
        dragged = false;
      }
    });
  }

  document.querySelectorAll(".timeline-bar").forEach(setupBar);

  // ------------------------------------------------------------------ //
  // Click-and-drag-to-create on empty grid space -- port of desktop's
  // click-create (mousePressEvent/mouseMoveEvent/_finish_create_drag).
  // A plain click (no drag) still creates a 1-day task, same as desktop.
  // ------------------------------------------------------------------ //

  const ghost = document.getElementById("timeline-create-ghost");
  let creating = false;
  let createLabel = "";
  let createLocalIdx = 0;
  let createRowTopPx = 0;
  let createStartIso = null;
  let createEndIso = null;
  let timelineStart = null; // set below from the canvas's first row-target lookup via data attr on <body>? -- see init.

  // The server renders absolute day offsets, not dates, on each element;
  // reconstructing "which date is under this x" needs the visible
  // range's start date, which we stash on the canvas itself.
  const startIso = canvas.dataset.start;

  function xToDayIndex(clientX) {
    const rect = canvas.getBoundingClientRect();
    const gutterW = parseInt(getComputedStyle(canvas).getPropertyValue("--gutter-w"), 10) || 92;
    const localX = clientX - rect.left - gutterW;
    return Math.max(0, Math.floor(localX / DAY_WIDTH));
  }

  document.querySelectorAll(".timeline-row-target").forEach((target) => {
    target.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || !startIso) return;
      creating = true;
      createLabel = target.dataset.label || "";
      createLocalIdx = parseInt(target.dataset.localIdx, 10);
      createRowTopPx = target.offsetTop;
      createStartIso = addDays(startIso, xToDayIndex(e.clientX));
      createEndIso = createStartIso;
      showGhost();
      target.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
  });

  function showGhost() {
    if (!ghost) return;
    const from = createStartIso <= createEndIso ? createStartIso : createEndIso;
    const to = createStartIso <= createEndIso ? createEndIso : createStartIso;
    const dayFrom = dayDiff(startIso, from);
    const dayTo = dayDiff(startIso, to) + 1;
    ghost.style.left = `calc(var(--gutter-w) + ${dayFrom * DAY_WIDTH}px)`;
    ghost.style.width = (dayTo - dayFrom) * DAY_WIDTH + "px";
    ghost.style.top = createRowTopPx + "px";
    ghost.style.height = ROW_HEIGHT + "px";
    ghost.style.display = "block";
  }

  document.addEventListener("pointermove", (e) => {
    if (!creating) return;
    createEndIso = addDays(startIso, xToDayIndex(e.clientX));
    showGhost();
  });

  document.addEventListener("pointerup", async () => {
    if (!creating) return;
    creating = false;
    if (ghost) ghost.style.display = "none";
    const from = createStartIso <= createEndIso ? createStartIso : createEndIso;
    const to = createStartIso <= createEndIso ? createEndIso : createStartIso;
    const resp = await fetch("/tasks/timeline/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: createLabel, start_at: from, due_at: to, local_idx: createLocalIdx }),
    }).catch(() => null);
    if (resp) reload();
  });

  document.addEventListener("pointercancel", () => {
    creating = false;
    if (ghost) ghost.style.display = "none";
  });
})();
