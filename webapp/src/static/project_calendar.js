// Project Week Calendar (1.4 slice 3, templates/project_calendar.html) --
// two interactions on top of the same time-grid geometry calendar.js
// already lays out server-side (grid_layout.py):
//
// 1. Drag an "unscheduled task" list item onto a `.project-calendar-col`
//    to create a work allocation there (default 1-hour block, snapped to
//    30 minutes) -- native HTML5 drag-and-drop (dragstart/dragover/drop),
//    not the pointer-capture system below, since this is a distinct
//    element being dropped onto the grid rather than a block already on
//    it being repositioned.
// 2. Drag an existing `.work-allocation` block to move it, or its
//    `.te-resize-handle` to resize it -- same pointer-based drag model as
//    static/calendar.js's Week/Day grid (pointerdown/pointermove/pointerup
//    on `document`, 15-minute snap), but on release this submits a plain
//    hidden form to routers/projects.py::move_allocation (a form-POST +
//    redirect, matching every other action on this page) instead of that
//    file's JSON/fetch `/events/{uid}/reschedule` contract -- the page
//    reloads either way, so there's no reason to duplicate the more
//    complex optimistic-update/revert logic that route's own JS needs.
//
// Both interactions submit a real form and let the resulting redirect
// reload the page -- the simplest way to guarantee what's shown always
// matches whatever the server actually persisted (including a rejected
// drop, e.g. a task that doesn't belong to this project), same reasoning
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

  // ------------------------------------------------------------------ //
  // 1. Drag an unscheduled task onto the grid -> create a work allocation
  // ------------------------------------------------------------------ //

  document.querySelectorAll(".unscheduled-task-item").forEach((item) => {
    item.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", item.dataset.taskUid);
      e.dataTransfer.effectAllowed = "copy";
    });
  });

  document.querySelectorAll(".project-calendar-col").forEach((col) => {
    col.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      col.classList.add("drop-hover");
    });
    col.addEventListener("dragleave", () => col.classList.remove("drop-hover"));
    col.addEventListener("drop", (e) => {
      e.preventDefault();
      col.classList.remove("drop-hover");
      const taskUid = e.dataTransfer.getData("text/plain");
      if (!taskUid) return;
      const rect = col.getBoundingClientRect();
      const rawTop = e.clientY - rect.top;
      const startPx = Math.max(0, Math.min(DAY_HEIGHT_PX - CREATE_SNAP_PX, snap(rawTop, CREATE_SNAP_PX)));
      const startMin = Math.round((startPx / PX_PER_HOUR) * 60);
      const endMin = startMin + DEFAULT_BLOCK_MINUTES;
      const day = col.dataset.date;
      submitForm(cfg.createUrl, {
        task_uid: taskUid,
        start_at: `${day}T${minutesToHHMMSS(startMin)}`,
        end_at: `${day}T${minutesToHHMMSS(endMin)}`,
        date_: cfg.weekDate,
      });
    });
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
    let currentCol = el.closest(".project-calendar-col");
    let dragged = false;
    const CLICK_THRESHOLD_PX = 4;

    function begin(e, isResize) {
      mode = isResize ? "resize" : "move";
      dragged = false;
      startX = e.clientX;
      startY = e.clientY;
      origTop = parseFloat(el.style.top) || 0;
      origHeight = parseFloat(el.style.height) || SNAP_PX;
      currentCol = el.closest(".project-calendar-col");
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
        let newTop = snap(origTop + dy, SNAP_PX);
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
      } else {
        let newHeight = snap(origHeight + dy, SNAP_PX);
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
      document.querySelectorAll(".project-calendar-col.drop-hover").forEach((c) => c.classList.remove("drop-hover"));
      if (!dragged) return; // was a click -- let the title link/delete button work normally

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
