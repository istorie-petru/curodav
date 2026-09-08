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
//   - a panel with a month calendar (range mode only) and, below it, a pair
//     of small hour:minute "chips" -- Start / End -- portaled out to
//     #multiselect-portal on open so it escapes any modal's clipping, the
//     same technique app.js's .multiselect handling already uses.
//
// 2026-09-03 rework (direct feedback, after a round of mockups: a scrolling
// 24-row hour list felt bulky and capped at whole hours, a click-drag hour
// grid/timeline-slider/preset-chip concepts were all rejected as
// "counterintuitive," and a plain typed HH:MM text field was rejected as
// "too much input needed" -- the one that landed was the narrowest of the
// bunch: keep the single-column calendar-sized panel, represent Start/End as
// two small chips under it, and edit a chip like a native time input's own
// segments -- one of "hour"/"minute" highlighted at a time, arrow keys
// nudge it in place, typing digits jumps straight to a value). This
// replaces the old click/click-to-pick, click-and-drag 24-row hour grid
// entirely -- see git history for that version. Consequences of the
// rework, all direct feedback too:
//   - No Apply button anywhere (range or time mode) -- every edit (a day
//     click, an hour/minute nudge, a typed digit) commits straight to the
//     hidden inputs immediately, the same "auto-commit" contract "date"
//     mode already had. There is nothing left to Apply.
//   - Clear moves out of the footer (which no longer exists) and into the
//     panel header as an icon-only button next to the month-nav arrows --
//     exactly `date` mode's own existing `.dtp-clear-nav` treatment,
//     because that's now what "Clear" means everywhere this component
//     appears, not just in date mode. Still hidden whenever `submit` is
//     set (was already the case; a submit-mode picker's caller -- e.g. a
//     work session's set-times form -- has no "empty" state to clear back
//     to).
//   - Minutes are a real, independently editable segment now, not the
//     derived "keep the original minute unless you change hour" trick the
//     old whole-hour-snapped grid needed to avoid silently mangling a
//     half-hour value -- state carries `startMinute`/`endMinute` outright.
//
// Modes (data-dtp-mode):
//   "range" (default) -- date + start/end hour:minute chips, writes
//                        "YYYY-MM-DDTHH:MM".
//   "time"            -- hour:minute chips only (a weekly Sleep/Leisure
//                        block has no date), writes "HH:MM".
//   "date"            -- a single date only, written "YYYY-MM-DD" -- the
//                        native <input type="date"> contract, added
//                        2026-08-17 so every native date input in the app
//                        (Holiday From/To, project Start/End, task
//                        due/start, habit entry date) pops the themed
//                        panel instead of the browser's own unstylable
//                        calendar.
// data-dtp-submit="1" makes the enclosing <form> submit itself as soon as
// the panel closes with a complete, actually-edited value (see `dirty`
// below) -- the Work-sessions card's per-session set-times form, and
// event_detail.html's "Move this occurrence" range, both rely on this.
// data-dtp-12h="1" edits/labels the hour segment in 12-hour form (a third
// AM/PM segment appears alongside hour/minute), honoring the Settings >
// General time-format preference the server passes down (deps.py's
// fmt_time). data-dtp-max="YYYY-MM-DD" disables every day after that bound
// (the habit check-in's entry date, which was a native
// <input type="date" max="today">).
//
// Committing (any edit) or clearing also fires a `change` event on the
// start hidden input -- the same event the replaced native input produced
// -- so the Tasks table's inline due-date cell (tasks_table.js) keeps
// saving the single-field update without any picker-specific wiring.
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
// month arrow it sits beside). 2026-09-03: range mode now shares this same
// header Clear (see above) -- time mode, which has no calendar/header,
// grows a minimal one-row header of its own just to hold it.
//
// Mouse: click a day, or a specific hour/minute segment inside a chip (that
// segment becomes the active one). Keyboard: Tab to the trigger, Enter
// opens; in the calendar Arrow keys move the focused day and Enter selects;
// on a chip Arrow Up/Down nudge the active segment, Arrow Left/Right move
// which segment is active (and cycle through hour/minute/AM-PM in 12h
// mode), digits type a value directly and auto-advance after two digits.
// Escape or an outside click closes.
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

  function clampWrap(n, max) {
    return ((n % max) + max) % max;
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

  // 24h "HH:MM", or 12h "H:MM AM/PM" -- used for the trigger's own label,
  // not for the chip segments themselves (those always show plain digits;
  // see renderHourRow's use of displayHour/displayAmpm).
  function fmtHourMin(hour, minute, use12h) {
    if (!use12h) return pad2(hour) + ":" + pad2(minute);
    const h = hour % 12 || 12;
    return h + ":" + pad2(minute) + (hour < 12 ? " AM" : " PM");
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
      startHour: null, startMinute: null,
      endHour: null, endMinute: null,
      // Set on any real edit while the panel is open, cleared on open --
      // lets a submit-mode picker (Work sessions' set-times, event_detail's
      // "Move this occurrence") tell "the user changed something and closed"
      // from "the user just opened it to look, then clicked away," so
      // opening/closing without editing never re-submits the form.
      dirty: false,
    };

    // Prefill from whatever the hidden inputs already hold.
    const ps = mode === "time" ? parseTime(startInput.value) : mode === "date" ? parseDateOnly(startInput.value) : parseRange(startInput.value);
    const pe = mode === "time" ? parseTime(endInput.value) : mode === "range" ? parseRange(endInput.value) : null;
    if (ps) {
      if (mode !== "date") {
        state.startHour = ps.hour;
        state.startMinute = ps.minute;
      }
      if (mode !== "time") state.date = dateKey(ps.year, ps.month, ps.day);
    }
    if (pe) {
      state.endHour = pe.hour;
      state.endMinute = pe.minute;
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
      const start = state.startHour !== null ? fmtHourMin(state.startHour, state.startMinute || 0, use12h) : null;
      const end = state.endHour !== null ? fmtHourMin(state.endHour, state.endMinute || 0, use12h) : null;
      if (start === null || end === null) return placeholder;
      if (mode === "time") return start + "–" + end;
      if (!state.date) return placeholder;
      return fmtDate(state.date) + " · " + start + "–" + end;
    }

    function updateTrigger() {
      value.textContent = labelText();
      // Clear any "you tried to submit this empty" flag (see the
      // document-level submit guard at the bottom of this file) the moment
      // the value actually changes -- covers picking a date, clearing, or
      // completing a chip edit, whichever the caller's mode supports.
      trigger.classList.remove("dtp-trigger-invalid");
    }

    // ------------------------------------------------------------------ //
    // Rendering the panel body
    // ------------------------------------------------------------------ //
    function renderPanel() {
      panel.innerHTML = "";
      if (mode === "range") {
        renderCalendar(panel);
        renderHourRow(panel);
      } else if (mode === "date") {
        renderCalendar(panel);
      } else {
        renderTimeHeader(panel);
        renderHourRow(panel);
      }

      if (mode !== "time") {
        // Focus the selected (or today's) day so arrow-key navigation works
        // immediately after opening.
        const focusKey = state.date || dateKey(state.viewYear, state.viewMonth, Math.min(todayInView(), daysInMonth(state.viewYear, state.viewMonth)));
        const target = panel.querySelector('.dtp-day[data-date="' + focusKey + '"]');
        if (target) target.focus();
      } else if (chips.start) {
        chips.start.el.focus();
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

      // Date and range modes both auto-commit on every edit (see this
      // file's header comment) and neither has a footer any more, so
      // Clear lives here, icon-only, next to the month-nav arrows --
      // `.dtp-clear-nav` (style.css) adds a left border + margin for
      // "visible separation, not crowded against" the Next-month arrow it
      // sits beside. Hidden in submit mode, same as before: a submit-mode
      // picker's caller has no "empty" state worth clearing back to.
      if ((mode === "date" || mode === "range") && !submit) {
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
            // Range mode: the date is one part of a still-editable value --
            // commit it live (so a picker that already has hours filled in
            // updates its saved value right away) but keep the panel open,
            // same as any other single-segment edit.
            state.dirty = true;
            commitLive();
            renderPanel();
          }
        });
        grid.appendChild(btn);
      }

      host.appendChild(head);
      host.appendChild(weekdays);
      host.appendChild(grid);
    }

    // Time mode has no calendar, so it gets its own minimal one-row header
    // just to hold the Clear button in the same place every other mode
    // keeps it.
    function renderTimeHeader(host) {
      const head = document.createElement("div");
      head.className = "dtp-panel-head";
      const title = document.createElement("span");
      title.className = "dtp-panel-title";
      title.textContent = "Hours";
      head.appendChild(title);
      if (!submit) {
        const clearNav = document.createElement("button");
        clearNav.type = "button";
        clearNav.className = "icon-btn dtp-clear-nav";
        clearNav.setAttribute("aria-label", "Clear");
        clearNav.title = "Clear";
        clearNav.innerHTML = ICON.x;
        clearNav.addEventListener("click", clearSelection);
        head.appendChild(clearNav);
      }
      host.appendChild(head);
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

    // ------------------------------------------------------------------ //
    // Hour:minute chips (2026-09-03 rework -- replaces the old scrolling/
    // click-drag 24-row hour grid). Each of Start/End is one small
    // focusable chip with a "hour" and "minute" segment (plus "ampm" in
    // 12h mode); exactly one segment is "active" at a time, shown with a
    // highlight, and only while that chip has real DOM focus -- so the
    // highlight is never stale once focus moves elsewhere. The chip
    // elements themselves are built once per renderPanel() call and then
    // only *mutated* (text + class changes) on every key press --
    // rebuilding them on every arrow-key tap would drop focus and break
    // repeated key presses, the same reason the old grid's click-drag used
    // a targeted `paintHours()` instead of a full re-render.
    // ------------------------------------------------------------------ //
    let chips = {}; // { start: {el, hourSeg, minSeg, ampmSeg}, end: {...} }
    let chipEdit = {}; // { start: {seg, buffer, bufferTimer}, end: {...} }

    function segList() {
      return use12h ? ["hour", "min", "ampm"] : ["hour", "min"];
    }

    function displayHour(h) {
      if (h === null) return "--";
      if (!use12h) return pad2(h);
      return String(h % 12 || 12);
    }

    function displayMinute(m) {
      return m === null ? "--" : pad2(m);
    }

    function displayAmpm(h) {
      return h === null ? "--" : h < 12 ? "AM" : "PM";
    }

    // First interaction with an unset chip needs a starting value: default
    // to "now" (rounded to the hour) for Start, or Start's own value for
    // End (so nudging End from blank starts right next to Start instead of
    // at an unrelated default) -- both are just starting points, not
    // constraints; every segment stays independently editable afterward.
    function ensureVal(role) {
      if (state[role + "Hour"] !== null) return;
      if (role === "end" && state.startHour !== null) {
        state.endHour = state.startHour;
        state.endMinute = state.startMinute;
      } else {
        const n = new Date();
        state[role + "Hour"] = n.getHours();
        state[role + "Minute"] = 0;
      }
    }

    function adjustSeg(role, seg, delta) {
      ensureVal(role);
      state.dirty = true;
      if (seg === "hour") {
        state[role + "Hour"] = clampWrap(state[role + "Hour"] + delta, 24);
      } else if (seg === "min") {
        state[role + "Minute"] = clampWrap(state[role + "Minute"] + delta, 60);
      } else if (seg === "ampm") {
        state[role + "Hour"] = clampWrap(state[role + "Hour"] + 12, 24);
      }
      commitLive();
      paintChips();
    }

    function typeDigit(role, seg, digit) {
      const ed = chipEdit[role];
      ensureVal(role);
      state.dirty = true;
      clearTimeout(ed.bufferTimer);
      ed.buffer += digit;
      let n = parseInt(ed.buffer, 10);
      const max = seg === "hour" ? (use12h ? 12 : 23) : seg === "min" ? 59 : null;
      if (max !== null && n > max) {
        ed.buffer = digit;
        n = parseInt(digit, 10);
      }
      if (seg === "hour") {
        if (use12h) {
          const isPM = state[role + "Hour"] >= 12;
          state[role + "Hour"] = (n % 12) + (isPM ? 12 : 0);
        } else {
          state[role + "Hour"] = n;
        }
      } else if (seg === "min") {
        state[role + "Minute"] = n;
      }
      commitLive();
      if (ed.buffer.length >= 2) {
        ed.buffer = "";
        if (seg === "hour") ed.seg = "min";
        paintChips();
      } else {
        ed.bufferTimer = setTimeout(() => { ed.buffer = ""; }, 700);
        paintChips();
      }
    }

    function buildChip(role) {
      const el = document.createElement("div");
      el.className = "dtp-hour-chip";
      el.tabIndex = 0;
      el.setAttribute("role", "group");
      el.setAttribute("aria-label", (role === "start" ? "Start" : "End") + " time");

      const hourSeg = document.createElement("span");
      hourSeg.className = "dtp-hour-seg";
      hourSeg.dataset.seg = "hour";
      const colon = document.createElement("span");
      colon.className = "dtp-hour-colon";
      colon.textContent = ":";
      const minSeg = document.createElement("span");
      minSeg.className = "dtp-hour-seg";
      minSeg.dataset.seg = "min";
      el.appendChild(hourSeg);
      el.appendChild(colon);
      el.appendChild(minSeg);

      let ampmSeg = null;
      if (use12h) {
        ampmSeg = document.createElement("span");
        ampmSeg.className = "dtp-hour-seg dtp-hour-seg-ampm";
        ampmSeg.dataset.seg = "ampm";
        el.appendChild(ampmSeg);
      }

      chips[role] = { el, hourSeg, minSeg, ampmSeg };
      chipEdit[role] = { seg: "hour", buffer: "", bufferTimer: null };

      el.addEventListener("mousedown", (e) => {
        const segEl = e.target.closest(".dtp-hour-seg");
        if (segEl) chipEdit[role].seg = segEl.dataset.seg;
      });
      el.addEventListener("focus", () => paintChips());
      el.addEventListener("blur", () => {
        chipEdit[role].buffer = "";
        paintChips();
      });
      el.addEventListener("keydown", (e) => onChipKeydown(e, role));
      return el;
    }

    function onChipKeydown(e, role) {
      const ed = chipEdit[role];
      const segs = segList();
      if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        adjustSeg(role, ed.seg, e.key === "ArrowUp" ? 1 : -1);
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const idx = segs.indexOf(ed.seg);
        const nextIdx = e.key === "ArrowLeft" ? Math.max(0, idx - 1) : Math.min(segs.length - 1, idx + 1);
        ed.seg = segs[nextIdx];
        ed.buffer = "";
        paintChips();
      } else if (e.key === "Enter") {
        e.preventDefault();
        close();
        trigger.focus();
      } else if (e.key === "Backspace") {
        e.preventDefault();
        ed.buffer = "";
        state.dirty = true;
        if (ed.seg === "hour") state[role + "Hour"] = null;
        else if (ed.seg === "min") state[role + "Minute"] = null;
        commitLive();
        paintChips();
      } else if (ed.seg === "ampm" && (e.key === "a" || e.key === "A" || e.key === "p" || e.key === "P")) {
        e.preventDefault();
        ensureVal(role);
        state.dirty = true;
        const wantPM = e.key === "p" || e.key === "P";
        const isPM = state[role + "Hour"] >= 12;
        if (wantPM !== isPM) state[role + "Hour"] = clampWrap(state[role + "Hour"] + 12, 24);
        commitLive();
        paintChips();
      } else if (/^[0-9]$/.test(e.key) && ed.seg !== "ampm") {
        e.preventDefault();
        typeDigit(role, ed.seg, e.key);
      }
    }

    function paintChips() {
      ["start", "end"].forEach((role) => {
        const c = chips[role];
        if (!c) return;
        const h = state[role + "Hour"];
        const m = state[role + "Minute"];
        c.hourSeg.textContent = displayHour(h);
        c.minSeg.textContent = displayMinute(m);
        if (c.ampmSeg) c.ampmSeg.textContent = displayAmpm(h);
        const focused = document.activeElement === c.el;
        const ed = chipEdit[role];
        c.hourSeg.classList.toggle("is-active", focused && ed.seg === "hour");
        c.minSeg.classList.toggle("is-active", focused && ed.seg === "min");
        if (c.ampmSeg) c.ampmSeg.classList.toggle("is-active", focused && ed.seg === "ampm");
        c.el.classList.toggle("is-focused", focused);
      });
    }

    function renderHourRow(host) {
      const row = document.createElement("div");
      row.className = "dtp-hour-row";
      chips = {};
      chipEdit = {};
      row.appendChild(buildChip("start"));
      const sep = document.createElement("span");
      sep.className = "dtp-hour-sep";
      sep.textContent = "–";
      row.appendChild(sep);
      row.appendChild(buildChip("end"));
      host.appendChild(row);
      paintChips();
    }

    // Shared by the header's icon-only Clear (date/range/time) -- resets
    // everything and commits the empty value. `endInput` may not exist at
    // all in date mode (_datetime_picker.html only renders the one hidden
    // input then), so this guards it.
    function clearSelection() {
      state.date = null;
      state.startHour = null;
      state.startMinute = null;
      state.endHour = null;
      state.endMinute = null;
      startInput.value = "";
      if (endInput) endInput.value = "";
      updateTrigger();
      commitChange();
      close();
    }

    // ------------------------------------------------------------------ //
    // Commit
    // ------------------------------------------------------------------ //
    function haveCompleteValue() {
      if (mode === "range") return !!state.date && state.startHour !== null && state.endHour !== null;
      if (mode === "time") return state.startHour !== null && state.endHour !== null;
      return !!state.date;
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

    // Range/time modes' live-commit path (2026-09-03) -- every chip edit
    // calls this directly instead of waiting for an Apply click that no
    // longer exists. Writes whatever is currently complete to the hidden
    // inputs and updates the trigger label; leaves the panel open (unlike
    // date mode's applySelection(), which both commits and closes on a
    // single day pick) since a chip edit is one segment of a value the
    // user is very likely still adjusting.
    function commitLive() {
      if (!haveCompleteValue()) {
        updateTrigger();
        return;
      }
      if (mode === "range") {
        startInput.value = state.date + "T" + pad2(state.startHour) + ":" + pad2(state.startMinute || 0);
        endInput.value = state.date + "T" + pad2(state.endHour) + ":" + pad2(state.endMinute || 0);
      } else if (mode === "time") {
        startInput.value = pad2(state.startHour) + ":" + pad2(state.startMinute || 0);
        endInput.value = pad2(state.endHour) + ":" + pad2(state.endMinute || 0);
      }
      updateTrigger();
      commitChange();
    }

    // Date mode only now -- range/time commit live (commitLive above) as
    // each segment is edited, so they never call this.
    function applySelection() {
      if (!state.date) return;
      startInput.value = state.date;
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
      state.dirty = false;
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
          // Range/time + submit (Work sessions' set-times, event_detail's
          // "Move this occurrence"): there's no Apply button left to post
          // the form, so closing a panel that was actually edited into a
          // complete value is what posts it now -- `dirty` (reset on open,
          // set on any real edit) keeps a no-op open-then-close from
          // silently re-submitting unchanged values.
          if (submit && mode !== "date" && state.dirty && haveCompleteValue()) {
            const form = container.closest("form");
            if (form) form.requestSubmit();
          }
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
    // Chip keydowns are handled by onChipKeydown (attached per-chip in
    // buildChip) rather than here.
    panel.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
        trigger.focus();
        return;
      }
      const day = e.target.closest(".dtp-day");
      if (!day) return;
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
        if (mode === "range") {
          state.dirty = true;
          commitLive();
        }
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

  // ------------------------------------------------------------------ //
  // Required-field guard (2026-09-08 direct report: a holiday could be
  // submitted with no dates at all, producing a raw 422 from the server --
  // FastAPI's "field required" -- surfaced to the user as an unreadable
  // JSON blob by modal.js's generic error toast). Root cause: this
  // component's hidden inputs carry `required` (see the macro's own doc
  // comment, _datetime_picker.html), but `input[type="hidden"]` is
  // explicitly barred from constraint validation by the HTML spec -- the
  // browser never enforced it, on this or any other `required` picker in
  // the app (event "Move this occurrence", habit check-in's entry date).
  //
  // A capturing, document-level `submit` listener (registered once here,
  // not per-form) is what makes this actually block: capture-phase
  // listeners on an ancestor (document) run before target-phase listeners
  // attached directly to the form itself, which is where both modal.js's
  // fetch-based handler and a plain native submit start -- so this always
  // gets first look, regardless of which page/modal wired the form or in
  // what order.
  //
  // Reads the hidden input's live `.value` straight off the DOM rather than
  // this file's own per-instance `state` (a closure inside `enhance()`,
  // not reachable from here) -- range/time modes' `commitLive()` only ever
  // writes both the start and end hidden inputs together once a value is
  // actually complete, so an empty *required* start input already implies
  // an incomplete picker without needing the end input's own value too.
  document.addEventListener(
    "submit",
    (e) => {
      const form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      const pickers = form.querySelectorAll(".dtp[data-dtp]");
      for (const container of pickers) {
        const startInput = container.querySelector('input[type="hidden"]');
        if (!startInput || !startInput.hasAttribute("required")) continue;
        if (startInput.value) continue;
        e.preventDefault();
        e.stopImmediatePropagation();
        const trigger = container.querySelector(".dtp-trigger");
        if (trigger) {
          trigger.classList.add("dtp-trigger-invalid");
          trigger.scrollIntoView({ block: "nearest" });
          trigger.click(); // opens the panel so the fix is one click away
        }
        if (window.ccToast) {
          window.ccToast({ message: "Pick a date before saving.", variant: "error" });
        }
        return;
      }
    },
    true,
  );
})();
