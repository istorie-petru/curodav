// Drag-to-move an event OR due-date task chip between day cells on the
// Month grid (templates/calendar_month.html). Loaded alongside
// calendar_month.js (which owns click-and-hold drag-to-CREATE on empty
// cell space); this file owns dragging an EXISTING chip (`.month-event-
// item` -- `.month-all-day` and the "event" kind of `.month-task-item`,
// or `.month-due-task-item` -- the "task" kind, a bare due-date item with
// no linked event) onto a different day cell to reschedule it.
//
// Events reuse the same JSON endpoint the Week/Day grid's own drag
// already posts to (POST /events/{uid}/reschedule, see
// static/calendar.js); tasks post to the Table/Kanban views' own inline-
// edit endpoint (POST /tasks/{uid}/update-field, field="due_at" --
// routers/tasks.py's `_UPDATABLE_FIELDS`), same call tasks_table.js's
// date-cell click-to-edit already makes, just supplying a shifted date
// instead of a picker value. Either way Month has no time axis, so the
// move only ever shifts the *date*, never the time-of-day: the dragged
// item's existing timestamp(s) are shifted by the same whole-day delta
// between the cell it was picked up from and the cell it was dropped on,
// and the drop cell's own weekday position never touches any stored
// time-of-day at all.
//
// Recurring events are deliberately excluded (no data-uid rendered for
// them by calendar_month.html): reschedule_event only ever moves a plain
// event row's own start_at/end_at, which for a recurring master would
// shift its whole series, not just the one occurrence being dragged --
// same footgun the manual-recurrence-exceptions feature exists to avoid
// elsewhere, so Month simply doesn't offer drag on those chips (a click
// still opens them normally; only the drag affordance is withheld).
//
// A short drag (a few px, effectively a click) is treated as a click and
// left alone -- same CLICK_THRESHOLD_PX pattern as calendar.js.
//
// 2026-09-08 (FullCalendar-parity interactions, slice 1 -- backend
// lane-packing + spanning-bar rendering, see documentation/plans/open.md):
// all-day events no longer render as `.month-all-day.month-event-item`
// chips inside a day cell at all -- they're now `.month-bar` spanning-bar
// elements in a separate per-week-row layer (`.month-week-bars`,
// _calendar_month_grid.html/_calendar_fourweek_grid.html), which this
// script's `.month-event-item[data-uid]` selector does NOT match.
//
// 2026-09-08 (slice 2 -- drag-move + edge-resize for bars, plus the
// pointer-follow drag ghost): the regression the paragraph above used to
// describe is fixed here. `setupBar` below retargets this same
// whole-day-shift delta logic at `.month-bar` elements (reusing
// `shiftDate`/the reschedule fetch), and adds edge-resize (drag either end
// of a bar to change just that side's date) plus a floating pointer-follow
// ghost clone for both move and resize -- `.month-bar` is absolutely
// positioned in a layer that's a SIBLING of the day cells, not their
// child, so (unlike a plain chip) it never visually moves on its own
// during a drag; the ghost is what gives the user feedback. Single-day
// timed events and due-date task chips are unaffected -- both are still
// plain `.month-event-item`/`.month-due-task-item` rows, unchanged by this
// pass, and keep their existing "lifted in place" drag treatment (no
// ghost) since neither is absolutely positioned and both already visually
// look picked-up via `.dragging`'s outline/shadow alone.

(function () {
  let items = [];
  let bars = [];
  let cells = [];
  const CLICK_THRESHOLD_PX = 4;

  // Unlike a plain `.month-event-item` chip (a normal-flow DESCENDANT of
  // the `.month-day-cell` it's a click-through for so `.closest()` used to
  // find it directly), a `.month-bar` is an absolutely-positioned SIBLING
  // of the day cells (`.month-week-bars`, a separate layer stacked on top
  // -- style.css). `elementFromPoint`/`.closest()` never finds a day-cell
  // ancestor for a bar at all.
  //
  // 2026-09-08 (slice 2 bug fix, direct report: resize-to-shrink "most of
  // the time doesn't work", resize-to-grow "sometimes needs N+1 to do N"):
  // this used to try `document.elementsFromPoint(x, y)` (the full hit-test
  // stack at that point, topmost first) and walk it for the first element
  // with a `.month-day-cell` ancestor -- since a bar being RESIZED never
  // actually changes its own on-screen box (only the separate ghost clone
  // does, see `setupBar`), the pointer spends most of a shrink drag
  // hovering a point still geometrically covered by the ORIGINAL,
  // unshrunk bar (and the tail end of a grow drag crossing back over it
  // too), so which element that stack call reports first for a given
  // pixel depended on the browser's own pointer-events/stacking
  // resolution at that exact point -- correct in principle (a
  // `pointer-events:none` layer/`none`-marked element should be excluded
  // from the stack, letting `.closest()` fall through to the real day
  // cell beneath), but evidently not reliable enough in practice to
  // pin down which day the cursor was actually over, which is exactly the
  // "off by one, sometimes silently wrong" shape of both reports.
  //
  // Replaced with a plain geometric containment test against the day
  // cells' own `getBoundingClientRect()`s -- no DOM stacking, pointer-
  // events, or "what's on top at this pixel" involved at all, just "is
  // (x, y) inside this cell's box." `cells` is a flat list of every
  // `.month-day-cell` on the grid (populated once in `init()`), so this is
  // a cheap ~42-rect scan, and it answers the ONLY question that actually
  // matters here -- which calendar day the pointer is over -- directly,
  // regardless of what any absolutely-positioned bar/ghost/handle happens
  // to be drawn on top of that same pixel.
  function cellAtPoint(x, y) {
    for (const cell of cells) {
      const r = cell.getBoundingClientRect();
      if (x >= r.left && x < r.right && y >= r.top && y < r.bottom) return cell;
    }
    return null;
  }

  function clearDropHover() {
    cells.forEach((c) => c.classList.remove("drop-hover"));
  }

  // Shifts only the date portion of an ISO timestamp ("YYYY-MM-DD" or
  // "YYYY-MM-DDTHH:MM:SS") by `deltaDays`, leaving any time-of-day suffix
  // untouched. Date math done at UTC midnight so it can't be knocked a day
  // off by the browser's local timezone.
  function shiftDate(iso, deltaDays) {
    if (!iso) return iso;
    const datePart = iso.slice(0, 10);
    const rest = iso.slice(10);
    const d = new Date(datePart + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + deltaDays);
    return d.toISOString().slice(0, 10) + rest;
  }

  // Direct follow-up request: plain event/task chips didn't get the
  // pointer-follow drag "shadow" `.month-bar`s already have (setupBar's
  // ghost, above) -- a chip just sat lifted in place (`.dragging`'s ring
  // outline) with no visual actually tracking the cursor, so a drag read
  // as "nothing is following my pointer" next to bars, which clearly do.
  // Mirrors setupBar's ghost mechanics (position:fixed clone, pointer-
  // events:none, removed on drop) rather than bar's own "can't move
  // itself" reasoning -- a chip COULD reparent itself into the hovered
  // cell like Week/Day's timed events do, but that would fight the
  // existing "re-render the whole region on drop" pattern (overflow
  // counts/"+N more" need a server recompute either way, see end()'s own
  // comment below) for no benefit over a simple clone.
  function setupItem(el) {
    let dragging = false;
    let started = false;
    let startX = 0;
    let startY = 0;
    let originCell = null;
    let itemRect = null; // the real chip's own getBoundingClientRect(), captured once at drag start
    let grabDX = 0;
    let grabDY = 0;
    let ghost = null;

    function makeGhost() {
      // A deep clone (not a manual reconstruction like setupBar's -- a
      // chip's own markup already varies by kind: color-dot + optional
      // time + title for an event/task row) keeps whatever's actually
      // inside this one without special-casing it here.
      const g = el.cloneNode(true);
      g.classList.add("month-item-ghost");
      g.style.position = "fixed";
      g.style.left = itemRect.left + "px";
      g.style.top = itemRect.top + "px";
      g.style.width = itemRect.width + "px";
      g.style.pointerEvents = "none"; // belt-and-suspenders, same reasoning as the bar ghost's own inline copy
      document.body.appendChild(g);
      return g;
    }

    function begin(e) {
      started = true;
      dragging = false;
      startX = e.clientX;
      startY = e.clientY;
      originCell = el.closest(".month-day-cell");
      // 2026-09-08 same-day bug fix, round 2: belt-and-suspenders against a
      // fast drag losing pointer events mid-gesture (same practice
      // FullCalendar's own PointerDragging follows) -- the move/end
      // listeners are already on `document` so this isn't the primary fix
      // for anything reported, but there's no reason not to have it.
      try { el.setPointerCapture(e.pointerId); } catch (err) { /* not critical */ }
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
        itemRect = el.getBoundingClientRect();
        ghost = makeGhost();
        grabDX = startX - itemRect.left;
        grabDY = startY - itemRect.top;
      }
      if (!dragging) return;
      ghost.style.left = e.clientX - grabDX + "px";
      ghost.style.top = e.clientY - grabDY + "px";
      const hovered = cellAtPoint(e.clientX, e.clientY);
      clearDropHover();
      if (hovered && hovered !== originCell) hovered.classList.add("drop-hover");
    }

    function end(e) {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      started = false;
      el.classList.remove("dragging");
      clearDropHover();
      if (ghost) {
        ghost.remove();
        ghost = null;
      }
      if (!dragging) return; // was a click -- let the href navigate normally

      const target = cellAtPoint(e.clientX, e.clientY);
      if (!target || !originCell || target === originCell) return;
      const fromDate = originCell.dataset.date;
      const toDate = target.dataset.date;
      if (!fromDate || !toDate) return;
      const deltaDays = Math.round((new Date(toDate + "T00:00:00Z") - new Date(fromDate + "T00:00:00Z")) / 86400000);
      if (!deltaDays) return;

      const uid = el.dataset.uid;
      const isTask = el.classList.contains("month-due-task-item");

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
        // async-CRUD (features/async-crud.md): the moved item now needs to
        // move between two day cells' own `rows`/overflow-count lists,
        // which the server recomputes correctly on a fresh render -- unlike
        // the Week grid's single-block top/left, there's no cheap local DOM
        // edit that keeps overflow counts and "+N more" links consistent
        // across both cells, so we re-render the whole #month-grid region
        // instead of reloading the page. The change event's listener
        // (async_calendar.js) refreshes the region and re-inits the month
        // drag/create bindings.
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

  // Shared by every `.month-bar` move/resize below -- same endpoint/shape
  // setupItem's event branch above already posts to, just factored out
  // since setupBar has three call sites (move, resize-left, resize-right)
  // instead of one.
  function postReschedule(uid, startIso, endIso) {
    fetch(`/events/${uid}/reschedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start_at: startIso, end_at: endIso || null }),
    }).then((resp) => {
      if (!resp.ok) throw new Error("reschedule failed");
      // Same whole-region refresh as setupItem's event branch -- a moved/
      // resized bar can change which week row(s) it belongs to and how
      // many lanes each affected week needs, none of which a local DOM
      // patch can safely recompute (see that branch's own comment).
      window.ccApi.dispatchChange({ type: "event", action: "move" });
    }).catch(() => {
      window.ccToast({ message: "Could not save that change.", variant: "error" });
    });
  }

  // Drag-move (grab anywhere on the bar body) + edge-resize (grab the
  // `.month-bar-resize-left`/`-right` handle, only rendered on the segment
  // that actually carries the event's real start/end -- see
  // routers/calendar.py's `_week_bars` `is_start`/`is_end`) for a
  // `.month-bar` spanning-bar element, plus the pointer-follow drag ghost
  // FullCalendar-parity slice 2 adds for both.
  //
  // A `.month-bar` is absolutely positioned in `.month-week-bars`, a layer
  // stacked ON TOP of (a sibling of, not a child of) the day cells it
  // visually spans -- unlike a plain `.month-event-item` chip, moving it
  // has no cheap "reparent into the hovered cell" trick available, and its
  // own on-screen box never changes shape during a drag on its own. The
  // ghost (a `position:fixed`, `pointer-events:none` clone) is what gives
  // the user any visual feedback at all: for a move it tracks the pointer
  // directly (offset by wherever it was grabbed, so it doesn't jump under
  // the cursor); for a resize it stays pinned to the bar's own row and
  // only its dragged edge follows the day cell currently under the
  // pointer, snapped to that cell's own on-screen left/right edge rather
  // than the raw pointer position -- the same "snap to the grid, not the
  // cursor" feel Week/Day's own `.te-resize-handle` already has (snapped
  // to 15-minute increments there; here the grid unit is a whole day).
  function setupBar(el) {
    const handleLeft = el.querySelector(".month-bar-resize-left");
    const handleRight = el.querySelector(".month-bar-resize-right");
    let started = false;
    let dragging = false;
    let mode = null; // "move" | "resize-left" | "resize-right"
    let startX = 0;
    let startY = 0;
    let originCell = null;
    let barRect = null; // the real bar's own getBoundingClientRect(), captured once at drag start
    let grabDX = 0;
    let grabDY = 0;
    let ghost = null;
    let justDragged = false; // see the click listener's own comment below

    function makeGhost() {
      // Reuses `.month-bar`'s own look (color, radius, font) by copying its
      // class list wholesale -- including its `.month-bar-lane-N`/`-col-N`/
      // `-span-N` classes, whose top/left/width rules this then overrides
      // via inline style below (inline always wins on specificity, no
      // `!important` needed). `.month-bar-ghost` itself only needs to
      // override the three properties that must NOT come from those
      // classes: `position` (`.month-bar` is `absolute`, relative to
      // `.month-week-bars`'s own offset parent -- wrong once this element
      // is reparented straight onto `<body>`, so this needs `fixed` against
      // the viewport instead, matching the viewport-relative coordinates
      // `getBoundingClientRect()` returns) and `pointer-events` (`.month-
      // bar` sets `auto`; the ghost must stay a passthrough -- `cellAtPoint`
      // no longer hit-tests the DOM at all (see its own comment), but a
      // clickable ghost floating over the grid would still be a real
      // problem on its own, e.g. swallowing a click meant for whatever's
      // underneath while the ghost briefly lingers).
      const g = document.createElement("div");
      g.className = "month-bar-ghost " + el.className;
      const label = el.querySelector(".month-bar-label");
      g.textContent = label ? label.textContent : el.textContent;
      g.style.position = "fixed";
      g.style.left = barRect.left + "px";
      g.style.top = barRect.top + "px";
      g.style.width = barRect.width + "px";
      g.style.height = barRect.height + "px";
      document.body.appendChild(g);
      return g;
    }

    function begin(e, which) {
      started = true;
      dragging = false;
      mode = which;
      startX = e.clientX;
      startY = e.clientY;
      // See setupItem's begin() for why -- same defensive capture.
      try { el.setPointerCapture(e.pointerId); } catch (err) { /* not critical */ }
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
        barRect = el.getBoundingClientRect();
        originCell = cellAtPoint(startX, startY);
        ghost = makeGhost();
        grabDX = startX - barRect.left;
        grabDY = startY - barRect.top;
      }
      if (!dragging) return;

      if (mode === "move") {
        ghost.style.left = e.clientX - grabDX + "px";
        ghost.style.top = e.clientY - grabDY + "px";
        const hovered = cellAtPoint(e.clientX, e.clientY);
        clearDropHover();
        if (hovered && hovered !== originCell) hovered.classList.add("drop-hover");
        return;
      }

      // Resize: keep testing the row of day cells the bar itself sits in
      // (barRect's own vertical center), not the raw pointer Y -- a small
      // vertical wobble while dragging horizontally along a thin bar
      // shouldn't drop the hovered cell to a different week row.
      const hovered = cellAtPoint(e.clientX, barRect.top + barRect.height / 2);
      clearDropHover();
      if (!hovered) return;
      hovered.classList.add("drop-hover");
      const cellRect = hovered.getBoundingClientRect();
      const MIN_WIDTH_PX = 24; // never let the ghost collapse to nothing while dragging past its own opposite edge
      if (mode === "resize-right") {
        const newRight = Math.max(cellRect.right, barRect.left + MIN_WIDTH_PX);
        ghost.style.width = newRight - barRect.left + "px";
      } else {
        const newLeft = Math.min(cellRect.left, barRect.left + barRect.width - MIN_WIDTH_PX);
        ghost.style.left = newLeft + "px";
        ghost.style.width = barRect.left + barRect.width - newLeft + "px";
      }
    }

    function end(e) {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      started = false;
      el.classList.remove("dragging");
      clearDropHover();
      if (ghost) {
        ghost.remove();
        ghost = null;
      }
      const finishedMode = mode;
      mode = null;
      // The subsequent native `click` event (pointerup always precedes
      // click) needs to know whether this was a real drag so it can
      // suppress the href/data-modal navigation -- checked there via
      // `justDragged` since `dragging` itself is reset to false below
      // before that click ever fires.
      justDragged = dragging;
      if (!dragging) return; // was a click -- let the href/data-modal open the event normally
      dragging = false;

      const uid = el.dataset.uid;

      if (finishedMode === "move") {
        const target = cellAtPoint(e.clientX, e.clientY);
        if (!target || !originCell || target === originCell) return;
        const fromDate = originCell.dataset.date;
        const toDate = target.dataset.date;
        if (!fromDate || !toDate) return;
        const deltaDays = Math.round((new Date(toDate + "T00:00:00Z") - new Date(fromDate + "T00:00:00Z")) / 86400000);
        if (!deltaDays) return;
        postReschedule(uid, shiftDate(el.dataset.start, deltaDays), el.dataset.end ? shiftDate(el.dataset.end, deltaDays) : null);
        return;
      }

      const target = cellAtPoint(e.clientX, barRect.top + barRect.height / 2);
      if (!target || !target.dataset.date) return;
      const newDate = target.dataset.date;
      // 2026-09-08 same-day bug fix, round 2: these two guards used to be a
      // bare `return` -- a correctly-detected resize past the event's own
      // other edge just silently did nothing, indistinguishable from a
      // missed/failed drag. Now says so, so "I dragged it and nothing
      // happened" has an answer instead of looking like a bug.
      if (finishedMode === "resize-left") {
        const newStart = newDate + el.dataset.start.slice(10);
        const endDate = (el.dataset.end || el.dataset.start).slice(0, 10);
        if (newDate > endDate) {
          window.ccToast({ message: "Can't drag the start past the event's own end.", variant: "error" });
          return;
        }
        postReschedule(uid, newStart, el.dataset.end || null);
      } else {
        const newEnd = newDate + (el.dataset.end ? el.dataset.end.slice(10) : "T23:59:00");
        const startDate = el.dataset.start.slice(0, 10);
        if (newDate < startDate) {
          window.ccToast({ message: "Can't drag the end before the event's own start.", variant: "error" });
          return;
        }
        postReschedule(uid, el.dataset.start, newEnd);
      }
    }

    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault(); // stop native text-selection/link-drag ghost while dragging
      const which = handleLeft && e.target === handleLeft ? "resize-left" : handleRight && e.target === handleRight ? "resize-right" : "move";
      begin(e, which);
    });
    el.addEventListener("click", (e) => {
      // `dragging` is already reset to false inside end() by the time this
      // native click fires (pointerup always precedes click) -- unlike
      // setupItem's simpler click guard, which fires before its own end()
      // gets a chance to reset anything. `justDragged` is end()'s own
      // one-shot flag for exactly this: true for the first click after a
      // real drag, so that click can be suppressed instead of letting the
      // href/data-modal navigate to the just-dragged event.
      if (justDragged) {
        e.preventDefault();
        justDragged = false;
      }
    });
  }

  // init() is re-invocable: async_calendar.js re-runs it after swapping in
  // a fresh #month-grid/#fourweek-grid region (async-CRUD, features/async-
  // crud.md) so the newly-rendered chips get their pointerdown bindings
  // again.
  //
  // 2026-08-31 bug fix: this selector only ever matched
  // `.month-event-item[data-uid]` -- when task-chip dragging was added
  // (end()'s `isTask` branch, posting to /tasks/{uid}/update-field), the
  // selector here was never widened to also pick up
  // `.month-due-task-item[data-uid]` (task chips carry that class, not
  // `.month-event-item`). Every task-chip drag handler that branch wrote
  // was consequently dead code -- no pointerdown listener was ever bound
  // to a task chip in the first place, so nothing dragged, on Month OR
  // 4-Week (direct report, "there should also be the capability to move
  // tasks" / "the tasks on the 4 week calendar", 2026-08-31). Selector
  // now matches either class.
  // 2026-09-08 (slice 2): also binds `.month-bar[data-uid]` -- the
  // spanning-bar elements slice 1 introduced. `cells` needs populating
  // whenever EITHER items or bars exist (previously bailed out early
  // whenever there were no plain chips, which happened to be harmless
  // before bars existed at all, but would have silently skipped binding
  // `cells` -- and so left every bar's drag/resize with no drop-hover
  // target list -- on a week with all-day events and nothing else).
  function init() {
    items = Array.from(document.querySelectorAll(".month-event-item[data-uid], .month-due-task-item[data-uid]"));
    bars = Array.from(document.querySelectorAll(".month-bar[data-uid]"));
    if (!items.length && !bars.length) return;
    cells = Array.from(document.querySelectorAll(".month-day-cell"));
    items.forEach(setupItem);
    bars.forEach(setupBar);
  }

  init();
  window.CCMonthGridDrag = { init };
})();
