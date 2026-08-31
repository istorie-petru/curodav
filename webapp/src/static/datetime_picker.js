// Shared date+time (or time-only) range picker (2026-08-17 direct
// feedback: "create a way to add dates, and hours, more easily ... practical,
// keyboard and mouse friendly, something for easy hour select"). Enhances a
// `.dtp` container (templates/_datetime_picker.html) holding two hidden
// inputs -- a start and an end -- whose name/value contract is exactly what
// the native `<input type="datetime-local">` / `<input type="time">` this
// replaces produced, so every server-side form handler is untouched.
//
// It renders:
//   - a trigger button (the current range, or a placeholder) -- keyboard
//     accessible (Tab + Enter/Space to open), same trigger+panel shape as
//     the app's other dropdown pickers;
//   - a panel with a month calendar (range mode only) and a column of 24
//     clickable hour rows ("like the Week grid"), portaled out to
//     #multiselect-portal on open so it escapes any modal's clipping, the
//     same technique app.js's .multiselect handling already uses.
//
// Hour selection is whole-hour granularity -- the deliberate trade of "easy
// hour select" (a "14:30" event reopened here shows 14:00). To keep that
// from silently mangling an existing half-hour value, the original minutes
// are remembered: re-saving the same hour keeps them, moving to a new hour
// resets to :00.
//
// Modes (data-dtp-mode):
//   "range" (default) -- date + start/end hours, writes "YYYY-MM-DDTHH:MM".
//   "time"            -- hours only (a weekly Sleep/Leisure block has no
//                        date), writes "HH:MM".
//   "date"            -- a single date only, written "YYYY-MM-DD" -- the
//                        native <input type="date"> contract, added
//                        2026-08-17 so every native date input in the app
//                        (Holiday From/To, project Start/End, task
//                        due/start, habit entry date) pops the themed
//                        panel instead of the browser's own unstylable
//                        calendar.
// data-dtp-submit="1" makes Apply submit the enclosing <form> immediately
// (the Work-sessions card's per-session set-times form) instead of just
// filling values for a later Save. data-dtp-12h="1" labels the hour grid in
// 12-hour form, honoring the Settings > General time-format preference the
// server passes down (deps.py's fmt_time). data-dtp-max="YYYY-MM-DD"
// disables every day after that bound (the habit check-in's entry date,
// which was a native <input type="date" max="today">).
//
// Committing (Apply) or clearing also fires a `change` event on the start
// hidden input -- the same event the replaced native input produced -- so
// the Tasks table's inline due-date cell (tasks_table.js) keeps saving the
// single-field update without any picker-specific wiring.
//
// "date" mode's footer (2026-08-29, STATE.md backlog item 9, "remove the
// Apply button entirely; Clear button loses its text label, becomes
// icon-only") -- picking a day in this mode already auto-commits
// (applySelection() runs straight from the day's own click/Enter handler,
// see renderCalendar/the panel keydown handler below), so Apply's footer
// button was already unreachable in normal use, just dead markup sitting
// there. Date mode now renders no footer at all; Clear moves up into the
// calendar header instead, next to the month prev/next arrows, as an
// icon-only button (`.dtp-clear-nav`, styled with a left border + margin
// in style.css for "visible separation, not crowded against" the next-
// month arrow it sits beside). Range/time mode's footer (Apply text +
// Clear text, or just Apply when `submit` is set) is unchanged -- neither
// of those modes auto-commits on a single pick, so Apply still earns its
// keep there.
//
// Mouse: click a day; click an hour to start a range, click again to end it
// (an earlier second click swaps so start is always first), or press and
// drag across hours. Keyboard: Tab to the trigger, Enter opens; in the
// calendar Arrow keys move the focused day and Enter selects; in the hour
// grid Arrow Up/Down move and Enter sets start/end. Escape or an outside
// click closes.
//
// Same "scan on DOMContentLoaded + MutationObserver" convention as
// reminders_picker.js / recurrence_picker.js so modal-injected content
// (task_form.html / event_form.html opened via data-modal) gets enhanced too.
(function () {
  const enhanced = new WeakSet();
  let openInst = null; // { container, trigger, panel }

  // ------------------------------------------------------------------ //
  // Small date/time helpers
  // ------------------------------------------------------------------ //
  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  // "YYYY-MM-DDTHH:MM" (or longer, e.g. a full ISO timestamp) -> parsed or null
  function parseRange(v) {
    if (!v) return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(v);
    if (!m) return null;
    return { year: +m[1], month: +m[2], day: +m[3], hour: +m[4], minute: +m[5] };
  }

  // "HH:MM" -> parsed or null
  function parseTime(v) {
    if (!v) return null;
    const m = /^(\d{2}):(\d{2})/.exec(v);
    if (!m) return null;
    return { hour: +m[1], minute: +m[2] };
  }

  // "YYYY-MM-DD" (date mode, the native <input type="date"> contract) ->
  // parsed or null
  function parseDateOnly(v) {
    if (!v) return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
    if (!m) return null;
    return { year: +m[1], month: +m[2], day: +m[3] };
  }

  function dateKey(year, month, day) {
    return year + "-" + pad2(month) + "-" + pad2(day);
  }

  function parseDateKey(key) {
    const [y, m, d] = key.split("-").map(Number);
    return { year: y, month: m, day: d };
  }

  function addDays(dt, n) {
    const d = new Date(dt);
    d.setDate(d.getDate() + n);
    return d;
  }

  function monthLabel(year, month) {
    return new Date(year, month - 1, 1).toLocaleString("en-GB", { month: "long", year: "numeric" });
  }

  // Monday-first, matching the app's own mini-calendar (M T W T F S S).
  function firstDayOfWeekOffset(year, month) {
    return (new Date(year, month - 1, 1).getDay() + 6) % 7;
  }

  function daysInMonth(year, month) {
    return new Date(year, month, 0).getDate();
  }

  function isToday(key) {
    const n = new Date();
    return key === dateKey(n.getFullYear(), n.getMonth() + 1, n.getDate());
  }

  function fmtHour(hour, use12h) {
    if (!use12h) return pad2(hour) + ":00";
    const h = hour % 12 || 12;
    return h + (hour < 12 ? " AM" : " PM");
  }

  function fmtDate(key, compact) {
    if (!key) return "";
    const { year, month, day } = parseDateKey(key);
    const d = new Date(year, month - 1, day);
    // 2026-08-30 (direct feedback, Tasks table: "the date seems a bit too
    // long, too hard to read") -- `.dtp--compact` (the Tasks table's Date
    // cell and the Work sessions card, the only two current callers) drops
    // the weekday ("Fri, ") entirely and only prints the year when it
    // isn't the current one -- "4 Sep" reads at a glance in a dense table
    // row/column the way "Fri, 4 Sept 2026" doesn't. Every other `.dtp`
    // caller (event/task/holiday forms, ...) is unaffected -- they don't
    // carry the compact class, so they keep the fuller weekday+year format
    // a form field has room for.
    if (compact) {
      const opts = { day: "numeric", month: "short" };
      if (year !== new Date().getFullYear()) opts.year = "numeric";
      return d.toLocaleDateString("en-GB", opts);
    }
    return d.toLocaleDateString("en-GB", {
      weekday: "short", day: "numeric", month: "short", year: "numeric",
    });
  }

  const ICON = {
    chevron:
      '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-chevron-down"></use></svg>',
    left:
      '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-chevron-left"></use></svg>',
    right:
      '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-chevron-right"></use></svg>',
    x: '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-x"></use></svg>',
    check:
      '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-check-square"></use></svg>',
  };

  // ------------------------------------------------------------------ //
  // Per-instance enhancement
  // ------------------------------------------------------------------ //
  function enhance(container) {
    if (enhanced.has(container)) return;
    enhanced.add(container);

    const rawMode = container.getAttribute("data-dtp-mode");
    const mode = rawMode === "date" || rawMode === "time" ? rawMode : "range";
    const submit = container.getAttribute("data-dtp-submit") === "1";
    const use12h = container.getAttribute("data-dtp-12h") === "1";
    // Optional upper bound "YYYY-MM-DD" (the habit check-in's entry date
    // was a native <input type="date" max="today">; future dates must not
    // be pickable there).
    const maxDate = container.getAttribute("data-dtp-max") || "";
    const compact = container.classList.contains("dtp--compact");
    const inputs = container.querySelectorAll('input[type="hidden"]');
    const startInput = inputs[0];
    const endInput = inputs[1];
    if (!startInput) return;
    if (mode !== "date" && !endInput) return;

    const placeholder =
      mode === "time" ? "Set hours…" : mode === "date" ? "Pick a date…" : "Set time…";

    const state = {
      mode, submit, use12h, placeholder,
      date: null, // "YYYY-MM-DD" (range and date modes)
      viewYear: null, viewMonth: null, // calendar month being shown
      startHour: null, endHour: null,
      origStart: { hour: null, minute: null },
      origEnd: { hour: null, minute: null },
    };

    // Prefill from whatever the hidden inputs already hold.
    const ps = mode === "time" ? parseTime(startInput.value) : mode === "date" ? parseDateOnly(startInput.value) : parseRange(startInput.value);
    const pe = mode === "time" ? parseTime(endInput.value) : mode === "range" ? parseRange(endInput.value) : null;
    if (ps) {
      if (mode !== "date") {
        state.startHour = ps.hour;
        state.origStart = { hour: ps.hour, minute: ps.minute };
      }
      if (mode !== "time") state.date = dateKey(ps.year, ps.month, ps.day);
    }
    if (pe) {
      state.endHour = pe.hour;
      state.origEnd = { hour: pe.hour, minute: pe.minute };
    }
    if (mode !== "time") {
      const base = ps ? { y: ps.year, m: ps.month } : null;
      const n = new Date();
      state.viewYear = base ? base.y : n.getFullYear();
      state.viewMonth = base ? base.m : n.getMonth() + 1;
    }

    // --- trigger ---
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "dtp-trigger";
    trigger.setAttribute("aria-haspopup", "true");
    trigger.setAttribute("aria-expanded", "false");
    const value = document.createElement("span");
    value.className = "dtp-value";
    const caret = document.createElement("span");
    caret.className = "filter-caret";
    caret.innerHTML = ICON.chevron;
    trigger.appendChild(value);
    trigger.appendChild(caret);
    container.insertBefore(trigger, startInput);

    // --- panel ---
    const panel = document.createElement("div");
    panel.className = "dtp-panel dtp-panel--" + mode;
    container.appendChild(panel);

    function labelText() {
      if (mode === "date") return state.date ? fmtDate(state.date, compact) : placeholder;
      const start = state.startHour !== null ? fmtHour(state.startHour, use12h) : null;
      const end = state.endHour !== null ? fmtHour(state.endHour, use12h) : null;
      if (start === null || end === null) return placeholder;
      if (mode === "time") return start + "\u2013" + end;
      if (!state.date) return placeholder;
      return fmtDate(state.date) + " \u00b7 " + start + "\u2013" + end;
    }

    function updateTrigger() {
      value.textContent = labelText();
    }

    // ------------------------------------------------------------------ //
    // Rendering the panel body
    // ------------------------------------------------------------------ //
    function renderPanel() {
      panel.innerHTML = "";
      if (mode === "range") {
        const calCol = document.createElement("div");
        calCol.className = "dtp-col";
        renderCalendar(calCol);
        const hourCol = document.createElement("div");
        hourCol.className = "dtp-col";
        renderHours(hourCol);
        panel.appendChild(calCol);
        panel.appendChild(hourCol);
      } else if (mode === "date") {
        renderCalendar(panel);
      } else {
        renderHours(panel);
      }
      // Date mode's "Clear" lives in the calendar header now (renderCalendar
      // appends it there) and has no Apply at all -- see this file's header
      // comment. Range/time keep the full footer.
      if (mode !== "date") renderFooter();

      if (mode !== "time") {
        // Focus the selected (or today's) day so arrow-key navigation works
        // immediately after opening.
        const focusKey = state.date || dateKey(state.viewYear, state.viewMonth, Math.min(todayInView(), daysInMonth(state.viewYear, state.viewMonth)));
        const target = panel.querySelector('.dtp-day[data-date="' + focusKey + '"]');
        if (target) target.focus();
      } else {
        const target = panel.querySelector(".dtp-hour.is-start") || panel.querySelector(".dtp-hour");
        if (target) target.focus();
      }
    }

    function todayInView() {
      const n = new Date();
      if (n.getFullYear() === state.viewYear && n.getMonth() + 1 === state.viewMonth) return n.getDate();
      return 1;
    }

    function isDisabledDay(key) {
      return maxDate !== "" && key > maxDate;
    }

    function renderCalendar(host) {
      const head = document.createElement("div");
      head.className = "dtp-panel-head";
      const prev = document.createElement("button");
      prev.type = "button";
      prev.className = "icon-btn dtp-month-nav";
      prev.setAttribute("aria-label", "Previous month");
      prev.innerHTML = ICON.left;
      const title = document.createElement("span");
      title.className = "dtp-panel-title";
      title.textContent = monthLabel(state.viewYear, state.viewMonth);
      const next = document.createElement("button");
      next.type = "button";
      next.className = "icon-btn dtp-month-nav";
      next.setAttribute("aria-label", "Next month");
      next.innerHTML = ICON.right;
      head.appendChild(prev);
      head.appendChild(title);
      head.appendChild(next);

      prev.addEventListener("click", () => shiftMonth(-1));
      next.addEventListener("click", () => shiftMonth(1));

      // Date mode only (2026-08-29, STATE.md backlog item 9): Apply is
      // gone entirely (a day click already auto-commits, see below), so
      // Clear is the only footer action left -- moved up here, icon-only,
      // next to the month-nav arrows instead of sitting alone in an
      // otherwise-empty footer. `.dtp-clear-nav` (style.css) adds a
      // left border + margin for "visible separation, not crowded
      // against" the Next-month arrow it sits beside.
      if (mode === "date" && !submit) {
        const clearNav = document.createElement("button");
        clearNav.type = "button";
        clearNav.className = "icon-btn dtp-clear-nav";
        clearNav.setAttribute("aria-label", "Clear date");
        clearNav.title = "Clear";
        clearNav.innerHTML = ICON.x;
        clearNav.addEventListener("click", clearSelection);
        head.appendChild(clearNav);
      }

      const weekdays = document.createElement("div");
      weekdays.className = "mini-cal-weekdays";
      for (const wd of ["M", "T", "W", "T", "F", "S", "S"]) {
        const s = document.createElement("span");
        s.textContent = wd;
        weekdays.appendChild(s);
      }

      const grid = document.createElement("div");
      grid.className = "dtp-cal-grid";
      const offset = firstDayOfWeekOffset(state.viewYear, state.viewMonth);
      const dim = daysInMonth(state.viewYear, state.viewMonth);
      for (let i = 0; i < 42; i++) {
        const dayNum = i - offset + 1;
        if (dayNum < 1 || dayNum > dim) {
          const blank = document.createElement("span");
          blank.className = "dtp-day is-blank";
          grid.appendChild(blank);
          continue;
        }
        const key = dateKey(state.viewYear, state.viewMonth, dayNum);
        const disabled = isDisabledDay(key);
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "dtp-day";
        if (disabled) btn.classList.add("is-disabled");
        if (isToday(key)) btn.classList.add("is-today");
        if (key === state.date) btn.classList.add("is-selected");
        btn.dataset.date = key;
        btn.textContent = String(dayNum);
        btn.addEventListener("click", () => {
          if (disabled) return;
          state.date = key;
          if (mode === "date") {
            // Date mode: auto-commit on selection (like native <input type="date">)
            applySelection();
          } else {
            renderPanel();
          }
        });
        grid.appendChild(btn);
      }

      host.appendChild(head);
      host.appendChild(weekdays);
      host.appendChild(grid);
    }

    function shiftMonth(delta) {
      let m = state.viewMonth + delta;
      let y = state.viewYear;
      if (m < 1) { m = 12; y -= 1; }
      if (m > 12) { m = 1; y += 1; }
      state.viewYear = y;
      state.viewMonth = m;
      renderPanel();
    }

    let hoursGrid = null;

    function renderHours(host) {
      const title = document.createElement("div");
      title.className = "dtp-hours-title";
      title.textContent = mode === "time" ? "Hours" : "Hours on this day";
      const grid = document.createElement("div");
      grid.className = "dtp-hours";
      hoursGrid = grid;

      for (let h = 0; h < 24; h++) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "dtp-hour";
        btn.dataset.hour = String(h);
        btn.textContent = fmtHour(h, use12h);
        grid.appendChild(btn);
      }
      paintHours(grid);
      attachHourDrag(grid);
      host.appendChild(title);
      host.appendChild(grid);
    }

    function paintHours(grid) {
      const buttons = grid.querySelectorAll(".dtp-hour");
      buttons.forEach((btn) => {
        const h = parseInt(btn.dataset.hour, 10);
        btn.classList.toggle("is-start", state.startHour === h);
        btn.classList.toggle("is-end", state.endHour === h);
        btn.classList.toggle(
          "in-range",
          state.startHour !== null &&
            state.endHour !== null &&
            h > Math.min(state.startHour, state.endHour) &&
            h < Math.max(state.startHour, state.endHour)
        );
      });
    }

    function pickHour(h) {
      // Click-click: first click is the start, second is the end (an earlier
      // second click swaps so start stays first); a third click restarts.
      if (state.startHour === null) {
        state.startHour = h;
        state.endHour = null;
      } else if (state.endHour === null) {
        if (h < state.startHour) {
          state.endHour = state.startHour;
          state.startHour = h;
        } else {
          state.endHour = h;
        }
        // Auto-commit when both start and end are selected (range/time mode)
        if (hoursGrid) paintHours(hoursGrid);
        if (mode !== "date") {
          applySelection();
          return;
        }
      } else {
        state.startHour = h;
        state.endHour = null;
      }
      if (hoursGrid) paintHours(hoursGrid);
    }

    function attachHourDrag(grid) {
      // Pointer drag and plain click both start here: pointerdown applies the
      // same pick rule a click would (so a click with no drag is one pick,
      // and dragging simply extends the end as the pointer moves). No separate
      // click listener is attached to the hour buttons -- pointerdown + a
      // pointerup would otherwise fire a click too and double-pick.
      let dragging = false;
      grid.addEventListener("pointerdown", (e) => {
        const btn = e.target.closest(".dtp-hour");
        if (!btn) return;
        dragging = true;
        pickHour(parseInt(btn.dataset.hour, 10));
      });
      document.addEventListener("pointermove", (e) => {
        if (!dragging) return;
        const btn = e.target.closest(".dtp-hour");
        if (!btn) return;
        const h = parseInt(btn.dataset.hour, 10);
        if (h === state.startHour) return;
        state.endHour = h;
        paintHours(grid);
      });
      document.addEventListener("pointerup", () => {
        dragging = false;
      });
    }

    // Shared by the footer's Clear button (range/time) and the calendar
    // header's icon-only Clear (date, see renderCalendar) -- resets
    // everything and commits the empty value, same as before this was
    // split across two call sites. `endInput` may not exist at all in date
    // mode (_datetime_picker.html only renders the one hidden input then),
    // so this guards it rather than assuming it's always there the way the
    // pre-split code did.
    function clearSelection() {
      state.date = null;
      state.startHour = null;
      state.endHour = null;
      startInput.value = "";
      if (endInput) endInput.value = "";
      updateTrigger();
      commitChange();
      close();
    }

    function renderFooter() {
      const footer = document.createElement("div");
      footer.className = "dtp-panel-footer";

      if (!submit) {
        const clear = document.createElement("button");
        clear.type = "button";
        clear.className = "btn outlined btn-sm";
        clear.innerHTML = ICON.x + "Clear";
        clear.addEventListener("click", clearSelection);
        footer.appendChild(clear);
      }

      const apply = document.createElement("button");
      apply.type = "button";
      apply.className = "btn primary btn-sm";
      apply.innerHTML = ICON.check + "Apply";
      apply.addEventListener("click", applySelection);
      footer.appendChild(apply);

      panel.appendChild(footer);
    }

    // ------------------------------------------------------------------ //
    // Commit
    // ------------------------------------------------------------------ //
    function minuteFor(hour, orig) {
      return hour === orig.hour ? orig.minute : 0;
    }

    // Fires the same change event the native input this picker replaces
    // did, so change-driven handlers that were wired to it keep working
    // (the Tasks table's inline due-date cell -- tasks_table.js's delegated
    // `#task-table input.inline-date` listener reads the hidden input's
    // value and posts the single-field update). Harmless for plain form
    // fields, which have no such listeners.
    function commitChange() {
      startInput.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function applySelection() {
      if (mode === "date") {
        if (!state.date) return;
        startInput.value = state.date;
        updateTrigger();
        commitChange();
        close();
        if (submit) {
          const form = container.closest("form");
          if (form) form.requestSubmit();
        }
        return;
      }
      const haveRange = state.startHour !== null && state.endHour !== null;
      if (mode === "range" && (!state.date || !haveRange)) return;
      if (mode === "time" && !haveRange) return;

      const startMin = minuteFor(state.startHour, state.origStart);
      const endMin = minuteFor(state.endHour, state.origEnd);
      if (mode === "time") {
        startInput.value = pad2(state.startHour) + ":" + pad2(startMin);
        endInput.value = pad2(state.endHour) + ":" + pad2(endMin);
      } else {
        startInput.value = state.date + "T" + pad2(state.startHour) + ":" + pad2(startMin);
        endInput.value = state.date + "T" + pad2(state.endHour) + ":" + pad2(endMin);
      }
      updateTrigger();
      commitChange();
      close();
      if (submit) {
        const form = container.closest("form");
        if (form) form.requestSubmit();
      }
    }

    // ------------------------------------------------------------------ //
    // Open / close / position (portal to #multiselect-portal like app.js's
    // own .multiselect handling, so a panel inside a modal never clips)
    // ------------------------------------------------------------------ //
    function position() {
      const rect = trigger.getBoundingClientRect();
      panel.style.minWidth = Math.max(rect.width, 250) + "px";
      const panelRect = panel.getBoundingClientRect();
      let left = rect.left;
      let top = rect.bottom + 6;
      if (left + panelRect.width > window.innerWidth - 8) {
        left = Math.max(8, window.innerWidth - panelRect.width - 8);
      }
      if (top + panelRect.height > window.innerHeight - 8) {
        top = rect.top - panelRect.height - 6; // flip above the trigger
      }
      panel.style.left = left + "px";
      panel.style.top = top + "px";
    }

    function open() {
      if (openInst && openInst.container === container) {
        close();
        return;
      }
      if (openInst) openInst.close();
      const pt = document.getElementById("multiselect-portal");
      if (pt) pt.appendChild(panel);
      panel.classList.add("is-open");
      trigger.classList.add("is-open");
      trigger.setAttribute("aria-expanded", "true");
      renderPanel();
      position();
      openInst = {
        container, trigger, panel, position,
        close: () => {
          panel.classList.remove("is-open");
          trigger.classList.remove("is-open");
          trigger.setAttribute("aria-expanded", "false");
          panel.style.left = panel.style.top = panel.style.minWidth = "";
          container.appendChild(panel);
        },
      };
    }

    function close() {
      if (openInst && openInst.container === container) {
        openInst.close();
        openInst = null;
      }
    }

    trigger.addEventListener("click", open);

    // Keyboard navigation inside the panel: arrows move, Enter selects.
    panel.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
        trigger.focus();
        return;
      }
      const day = e.target.closest(".dtp-day");
      const hour = e.target.closest(".dtp-hour");
      if (day) {
        const { year, month, day: d } = parseDateKey(day.dataset.date);
        let moved = null;
        if (e.key === "ArrowLeft") moved = addDays(new Date(year, month - 1, d), -1);
        else if (e.key === "ArrowRight") moved = addDays(new Date(year, month - 1, d), 1);
        else if (e.key === "ArrowUp") moved = addDays(new Date(year, month - 1, d), -7);
        else if (e.key === "ArrowDown") moved = addDays(new Date(year, month - 1, d), 7);
        else if (e.key === "Enter" || e.key === " ") {
          if (day.classList.contains("is-disabled")) {
            e.preventDefault();
            return;
          }
          state.date = day.dataset.date;
          renderPanel();
          e.preventDefault();
          return;
        }
        if (moved) {
          e.preventDefault();
          const ky = dateKey(moved.getFullYear(), moved.getMonth() + 1, moved.getDate());
          if (moved.getFullYear() !== state.viewYear || moved.getMonth() + 1 !== state.viewMonth) {
            state.viewYear = moved.getFullYear();
            state.viewMonth = moved.getMonth() + 1;
            renderPanel();
          }
          const target = panel.querySelector('.dtp-day[data-date="' + ky + '"]');
          if (target) target.focus();
        }
      } else if (hour) {
        if (e.key === "ArrowUp" || e.key === "ArrowDown") {
          e.preventDefault();
          const delta = e.key === "ArrowUp" ? -1 : 1;
          const all = Array.from(panel.querySelectorAll(".dtp-hour"));
          const idx = all.indexOf(hour);
          const next = all[Math.min(Math.max(idx + delta, 0), all.length - 1)];
          if (next) next.focus();
        } else if (e.key === "Enter" || e.key === " ") {
          pickHour(parseInt(hour.dataset.hour, 10));
          e.preventDefault();
        }
      }
    });

    updateTrigger();
  }

  function scan(root) {
    (root.querySelectorAll ? root.querySelectorAll(".dtp[data-dtp]") : []).forEach(enhance);
    if (root.matches && root.matches(".dtp[data-dtp]")) enhance(root);
  }

  document.addEventListener("DOMContentLoaded", () => scan(document));

  new MutationObserver((mutations) => {
    for (const m of mutations) {
      m.addedNodes.forEach((node) => {
        if (node.nodeType === 1) scan(node);
      });
    }
  }).observe(document.documentElement, { childList: true, subtree: true });

  // Outside click closes whatever is open; resize keeps it anchored.
  //
  // Reads e.composedPath() rather than walking .closest()/.contains() off
  // e.target: a month-nav arrow's own click handler (shiftMonth ->
  // renderPanel) runs first (target-phase listeners fire before the event
  // bubbles up to document) and does `panel.innerHTML = ""`, which
  // detaches the very button that was clicked. By the time this bubbled
  // listener ran, `openInst.panel.contains(e.target)` was checking a
  // *detached* node against the live panel and always got `false` --
  // read as an outside click, so the whole picker closed itself on every
  // month-arrow click. composedPath() is captured at dispatch time,
  // before any of that DOM mutation, so it still lists the panel as an
  // ancestor of the click even after the click handler detaches the node.
  document.addEventListener("click", (e) => {
    if (!openInst) return;
    const path = e.composedPath ? e.composedPath() : [e.target];
    const hitTrigger = path.find((n) => n.classList && n.classList.contains("dtp-trigger"));
    if (hitTrigger && openInst.container.contains(hitTrigger)) return;
    if (path.includes(openInst.panel)) return;
    openInst.close();
    openInst = null;
  });

  window.addEventListener("resize", () => {
    if (openInst) openInst.position();
  });
})();