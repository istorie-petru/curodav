// Date and time fields (templates/_date_time_fields.html, 2026-09-26 --
// Peter's mockup; replaces datetime_picker.js).
//
// A field is a real text box plus a small button inside it:
//   .dtf[data-dtf="date"|"time"] > input.dtf-input + button.dtf-btn + input.dtf-value (hidden)
// Typing is parsed on Enter / leaving the box ("29/09/2023", "2023-09-29",
// "29.09", "today"; "15:30", "1530", "3pm"). The button (or Alt/ArrowDown)
// opens a dropdown: a month calendar for a date, a list of times every
// 15 minutes for a time. The hidden input is what the form posts; it
// fires a bubbling `change` whenever its value changes, so existing
// listeners (the Tasks table's inline due date) keep working.
//
// A range (.dtr) is Start date+time and End date+time with an optional
// All day switch that only hides the time fields; it writes its two
// hidden inputs (start/end "YYYY-MM-DDTHH:MM", all-day T00:00..T23:59),
// keeps the duration when the start moves, and never lets the end fall
// before the start.
//
// Everything is delegated on the document, so fields that arrive later in
// a modal need no init call. The dropdown is one element on <body> with
// position:fixed, so a modal's overflow can't clip it.
(function () {
  const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const MONTH_FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

  // ---- dates ----------------------------------------------------------
  const pad = (n) => String(n).padStart(2, "0");
  const isoOf = (d) => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  function dateOf(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    if (!m) return null;
    const d = new Date(+m[1], +m[2] - 1, +m[3]);
    return d.getMonth() === +m[2] - 1 ? d : null;
  }
  function fmtDate(iso) {
    const d = dateOf(iso);
    if (!d) return "";
    return DOW[(d.getDay() + 6) % 7] + ", " + MON[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear();
  }
  function build(y, m, d) {
    if (y < 100) y += 2000;
    const dt = new Date(y, m - 1, d);
    return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d ? isoOf(dt) : null;
  }
  // "" -> "", unparseable -> null.
  function parseDate(text) {
    const t = (text || "").trim().toLowerCase();
    if (!t) return "";
    const today = new Date();
    if (t === "today" || t === "t") return isoOf(today);
    if (t === "tomorrow" || t === "tmw") return isoOf(new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1));
    if (t === "yesterday") return isoOf(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1));
    let m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(t);
    if (m) return build(+m[1], +m[2], +m[3]);
    m = /^(\d{1,2})[\/.\-\s](\d{1,2})(?:[\/.\-\s](\d{2}|\d{4}))?$/.exec(t); // day first
    if (m) return build(m[3] ? +m[3] : today.getFullYear(), +m[2], +m[1]);
    m = /^(\d{2})(\d{2})(\d{4})$/.exec(t); // 29092023
    if (m) return build(+m[3], +m[2], +m[1]);
    // The field's own display text ("Sat, Sep 26, 2026") parses back.
    m = /^(?:[a-z]{3},?\s+)?([a-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})$/.exec(t);
    if (m) {
      const mi = MON.findIndex((x) => x.toLowerCase() === m[1]);
      if (mi >= 0) return build(+m[3], mi + 1, +m[2]);
    }
    return null;
  }

  // ---- times ----------------------------------------------------------
  function fmtTime(hhmm, h12) {
    const m = /^(\d{2}):(\d{2})$/.exec(hhmm || "");
    if (!m) return "";
    if (!h12) return hhmm;
    let h = +m[1];
    const ap = h < 12 ? "AM" : "PM";
    h = h % 12 || 12;
    return h + ":" + m[2] + " " + ap;
  }
  function parseTime(text) {
    let t = (text || "").trim().toLowerCase().replace(/\s+/g, "");
    if (!t) return "";
    let ap = "";
    const apm = /(a|p)\.?m?\.?$/.exec(t);
    if (apm) {
      ap = apm[1];
      t = t.slice(0, apm.index);
    }
    let h;
    let mi = 0;
    let m = /^(\d{1,2})[:.h](\d{2})$/.exec(t);
    if (m) {
      h = +m[1];
      mi = +m[2];
    } else if ((m = /^(\d{3,4})$/.exec(t))) {
      h = +m[1].slice(0, -2);
      mi = +m[1].slice(-2);
    } else if ((m = /^(\d{1,2})$/.exec(t))) {
      h = +m[1];
    } else return null;
    if (ap) {
      if (h < 1 || h > 12) return null;
      h = (h % 12) + (ap === "p" ? 12 : 0);
    }
    if (h > 23 || mi > 59) return null;
    return pad(h) + ":" + pad(mi);
  }
  const minutes = (hhmm) => (/^\d{2}:\d{2}$/.test(hhmm || "") ? +hhmm.slice(0, 2) * 60 + +hhmm.slice(3) : null);
  const hhmmOf = (mins) => pad(Math.floor(mins / 60) % 24) + ":" + pad(mins % 60);

  // ---- a field ----------------------------------------------------------
  const kindOf = (f) => f.dataset.dtf;
  const input = (f) => f.querySelector(".dtf-input");
  const hidden = (f) => f.querySelector(".dtf-value");
  const is12h = (f) => f.dataset.dtf12h === "1";

  function display(f, value) {
    return kindOf(f) === "date" ? fmtDate(value) : fmtTime(value, is12h(f));
  }
  function withinBounds(f, iso) {
    if (kindOf(f) !== "date" || !iso) return true;
    if (f.dataset.dtfMin && iso < f.dataset.dtfMin) return false;
    if (f.dataset.dtfMax && iso > f.dataset.dtfMax) return false;
    return true;
  }
  // Sets a field's value (already normalized) and tells everyone.
  function setValue(f, value, fromRange) {
    const h = hidden(f);
    const changed = h.value !== value;
    h.value = value;
    input(f).value = display(f, value);
    f.classList.remove("is-invalid");
    if (changed) h.dispatchEvent(new Event("change", { bubbles: true }));
    const range = f.closest(".dtr");
    if (range && !fromRange) syncRange(range, f.dataset.dtrRole);
  }
  // Parses what was typed; returns false (and marks the field) if it can't.
  // An empty required field only counts as a problem on submit
  // (`forSubmit`) -- not while someone is still filling the form in.
  function commit(f, forSubmit) {
    const text = input(f).value;
    const value = kindOf(f) === "date" ? parseDate(text) : parseTime(text);
    if (value === null || !withinBounds(f, value)) {
      f.classList.add("is-invalid");
      return false;
    }
    if (value === "" && forSubmit && f.hasAttribute("data-dtf-required")) {
      f.classList.add("is-invalid");
      return false;
    }
    setValue(f, value);
    return true;
  }

  // ---- a range --------------------------------------------------------
  const part = (range, role) => range.querySelector('.dtf[data-dtr-role="' + role + '"]');
  const val = (range, role) => {
    const f = part(range, role);
    return f ? hidden(f).value : "";
  };
  const put = (range, role, value) => {
    const f = part(range, role);
    if (f && hidden(f).value !== value) setValue(f, value, true);
  };
  function addDays(iso, n) {
    const d = dateOf(iso);
    return d ? isoOf(new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)) : iso;
  }
  const stamp = (date, time) => (date ? date + "T" + (time || "00:00") : "");
  function stampMinutes(date, time) {
    const d = dateOf(date);
    const m = minutes(time) || 0;
    return d ? d.getTime() / 60000 + m : null;
  }
  function fromStampMinutes(total) {
    const d = new Date(total * 60000);
    return [isoOf(d), pad(d.getHours()) + ":" + pad(d.getMinutes())];
  }

  function syncRange(range, changedRole) {
    const allDay = range.hasAttribute("data-all-day");
    let sd = val(range, "start-date");
    let st = val(range, "start-time");
    let ed = val(range, "end-date");
    let et = val(range, "end-time");
    const prevStart = range.dataset.prevStart || "";
    // The start moved: move the end by the same amount (keep duration).
    if ((changedRole === "start-date" || changedRole === "start-time") && prevStart && sd && ed) {
      const [pd, pt] = prevStart.split("T");
      const before = stampMinutes(pd, pt);
      const now = stampMinutes(sd, st);
      const end = stampMinutes(ed, et);
      if (before !== null && now !== null && end !== null) {
        [ed, et] = fromStampMinutes(end + (now - before));
      }
    }
    if (sd && !ed) ed = sd;
    if (!allDay && sd) {
      if (!st) st = "09:00";
      if (!et) et = hhmmOf(Math.min((minutes(st) || 0) + 60, 23 * 60 + 59));
    }
    // Never let the end come before the start.
    if (sd && ed) {
      if (allDay) {
        if (ed < sd) ed = sd;
      } else {
        const s = stampMinutes(sd, st);
        if (stampMinutes(ed, et) < s) [ed, et] = fromStampMinutes(s + 60);
      }
    }
    put(range, "start-time", st);
    put(range, "end-date", ed);
    put(range, "end-time", et);
    range.dataset.prevStart = sd ? sd + "T" + (st || "00:00") : "";
    const startBox = range.querySelector(".dtr-start");
    const endBox = range.querySelector(".dtr-end");
    const startValue = allDay ? stamp(sd, "00:00") : stamp(sd, st);
    const endValue = !ed ? "" : allDay ? ed + "T23:59" : stamp(ed, et);
    for (const [box, v] of [[startBox, startValue], [endBox, endValue]]) {
      if (box && box.value !== v) {
        box.value = v;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
  }
  function initRange(range) {
    if (range.dataset.prevStart !== undefined) return;
    const sd = val(range, "start-date");
    range.dataset.prevStart = sd ? sd + "T" + (val(range, "start-time") || "00:00") : "";
  }

  // ---- the dropdown -----------------------------------------------------
  let panel = null;
  let openFor = null;
  let view = null; // calendar month on show: Date (1st of month)

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement("div");
    panel.className = "dtf-panel";
    panel.hidden = true;
    document.body.appendChild(panel);
    panel.addEventListener("mousedown", (e) => e.preventDefault()); // keep focus in the box
    panel.addEventListener("click", onPanelClick);
    panel.addEventListener("keydown", onPanelKey);
    return panel;
  }
  function place() {
    if (!openFor) return;
    const r = openFor.getBoundingClientRect();
    panel.style.minWidth = kindOf(openFor) === "time" ? Math.max(r.width, 150) + "px" : "";
    const box = panel.getBoundingClientRect();
    const vh = window.innerHeight;
    const vw = document.documentElement.clientWidth;
    let top = r.bottom + 4;
    if (top + box.height > vh - 8 && r.top - 4 - box.height > 8) top = r.top - 4 - box.height;
    const left = Math.min(Math.max(8, r.left), vw - box.width - 8);
    panel.style.top = Math.round(top) + "px";
    panel.style.left = Math.round(left) + "px";
  }
  function close(refocus) {
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    panel.innerHTML = "";
    const f = openFor;
    openFor = null;
    if (f) {
      f.classList.remove("is-open");
      if (refocus) input(f).focus();
    }
  }
  function open(f) {
    ensurePanel();
    if (openFor === f) return close(true);
    close(false);
    openFor = f;
    f.classList.add("is-open");
    panel.hidden = false;
    if (kindOf(f) === "date") {
      const cur = dateOf(hidden(f).value) || new Date();
      view = new Date(cur.getFullYear(), cur.getMonth(), 1);
      renderCalendar();
      const sel = panel.querySelector(".dtf-day.is-selected") || panel.querySelector(".dtf-day.is-today");
      if (sel) sel.focus({ preventScroll: true });
    } else {
      renderTimes();
    }
    place();
  }

  function renderCalendar() {
    const f = openFor;
    const selected = hidden(f).value;
    const today = isoOf(new Date());
    const sundayFirst = f.dataset.dtfWeekStart === "sunday";
    const first = new Date(view.getFullYear(), view.getMonth(), 1);
    const offset = sundayFirst ? first.getDay() : (first.getDay() + 6) % 7;
    const start = new Date(first.getFullYear(), first.getMonth(), 1 - offset);
    const names = sundayFirst ? ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"] : ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
    let html =
      '<div class="dtf-cal-head">' +
      '<button type="button" class="dtf-nav" data-nav="-1" aria-label="Previous month">&lsaquo;</button>' +
      '<span class="dtf-cal-title">' + MONTH_FULL[view.getMonth()] + " " + view.getFullYear() + "</span>" +
      '<button type="button" class="dtf-nav" data-nav="1" aria-label="Next month">&rsaquo;</button></div>' +
      '<div class="dtf-cal-grid" role="grid">' + names.map((n) => '<span class="dtf-dow">' + n + "</span>").join("");
    for (let i = 0; i < 42; i++) {
      const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      const iso = isoOf(d);
      const cls = ["dtf-day"];
      if (d.getMonth() !== view.getMonth()) cls.push("is-outside");
      if (iso === today) cls.push("is-today");
      if (iso === selected) cls.push("is-selected");
      const off = !withinBounds(f, iso);
      html +=
        '<button type="button" class="' + cls.join(" ") + '" data-iso="' + iso + '"' + (off ? " disabled" : "") +
        ' tabindex="' + (iso === (selected || today) ? "0" : "-1") + '" aria-label="' + fmtDate(iso) + '">' + d.getDate() + "</button>";
    }
    html += '</div><div class="dtf-cal-foot"><button type="button" class="dtf-link" data-pick="today">Today</button>';
    if (!f.hasAttribute("data-dtf-required")) html += '<button type="button" class="dtf-link" data-pick="">Clear</button>';
    html += "</div>";
    panel.className = "dtf-panel dtf-panel-date";
    panel.innerHTML = html;
  }

  function renderTimes() {
    const f = openFor;
    const selected = hidden(f).value;
    const range = f.closest(".dtr");
    // An end time on the start's day shows how long the event would be.
    let startMin = null;
    if (range && f.dataset.dtrRole === "end-time" && val(range, "end-date") === val(range, "start-date")) {
      startMin = minutes(val(range, "start-time"));
    }
    let html = '<div class="dtf-times" role="listbox">';
    for (let m = 0; m < 24 * 60; m += 15) {
      const v = hhmmOf(m);
      let extra = "";
      if (startMin !== null && m > startMin) {
        const d = m - startMin;
        const text = d < 60 ? d + " min" : Math.floor(d / 60) + " h" + (d % 60 ? " " + (d % 60) : "");
        extra = '<span class="dtf-dur">' + text + "</span>";
      }
      html +=
        '<button type="button" role="option" class="dtf-opt' + (v === selected ? " is-selected" : "") + '" data-time="' + v + '"' +
        (v === selected ? ' aria-selected="true"' : "") + ">" + fmtTime(v, is12h(f)) + extra + "</button>";
    }
    html += "</div>";
    panel.className = "dtf-panel dtf-panel-time";
    panel.innerHTML = html;
    // Scroll to the value (or the next quarter hour after it).
    const want = minutes(selected) !== null ? minutes(selected) : (startMin !== null ? startMin + 60 : 9 * 60);
    const target = panel.querySelector('[data-time="' + hhmmOf(Math.min(Math.ceil(want / 15) * 15, 23 * 60 + 45)) + '"]');
    const list = panel.querySelector(".dtf-times");
    if (target) {
      list.scrollTop = target.offsetTop - list.clientHeight / 2 + target.offsetHeight / 2;
      target.tabIndex = 0;
    }
  }

  function onPanelClick(e) {
    const f = openFor;
    if (!f) return;
    const nav = e.target.closest("[data-nav]");
    if (nav) {
      view = new Date(view.getFullYear(), view.getMonth() + +nav.dataset.nav, 1);
      renderCalendar();
      return;
    }
    const day = e.target.closest(".dtf-day");
    if (day && !day.disabled) {
      setValue(f, day.dataset.iso);
      return close(true);
    }
    const pick = e.target.closest("[data-pick]");
    if (pick) {
      const v = pick.dataset.pick === "today" ? isoOf(new Date()) : "";
      if (withinBounds(f, v)) setValue(f, v);
      return close(true);
    }
    const t = e.target.closest(".dtf-opt");
    if (t) {
      setValue(f, t.dataset.time);
      close(true);
    }
  }

  function onPanelKey(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation(); // not the modal underneath
      return close(true);
    }
    const day = e.target.closest && e.target.closest(".dtf-day");
    if (day) {
      const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
      const monthStep = { PageUp: -1, PageDown: 1 }[e.key];
      if (step || monthStep) {
        e.preventDefault();
        const d = dateOf(day.dataset.iso);
        const next = step
          ? new Date(d.getFullYear(), d.getMonth(), d.getDate() + step)
          : new Date(d.getFullYear(), d.getMonth() + monthStep, Math.min(d.getDate(), 28));
        if (next.getMonth() !== view.getMonth() || next.getFullYear() !== view.getFullYear()) {
          view = new Date(next.getFullYear(), next.getMonth(), 1);
          renderCalendar();
        }
        const b = panel.querySelector('[data-iso="' + isoOf(next) + '"]');
        if (b) b.focus();
      }
      return;
    }
    const t = e.target.closest && e.target.closest(".dtf-opt");
    if (t && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      const n = e.key === "ArrowDown" ? t.nextElementSibling : t.previousElementSibling;
      if (n) n.focus();
    }
  }

  // ---- wiring -----------------------------------------------------------
  document.addEventListener("click", (e) => {
    const btn = e.target.closest && e.target.closest(".dtf-btn");
    if (btn) {
      e.preventDefault();
      const f = btn.closest(".dtf");
      const range = f.closest(".dtr");
      if (range) initRange(range);
      commit(f);
      open(f);
      return;
    }
    if (panel && !panel.hidden && !panel.contains(e.target) && !(openFor && openFor.contains(e.target))) close(false);
  });
  document.addEventListener("focusin", (e) => {
    const f = e.target.closest && e.target.closest(".dtf");
    const range = f && f.closest(".dtr");
    if (range) initRange(range);
  });
  document.addEventListener("focusout", (e) => {
    const box = e.target;
    if (!box.classList || !box.classList.contains("dtf-input")) return;
    const f = box.closest(".dtf");
    // Moving into the open dropdown isn't leaving the field.
    if (panel && !panel.hidden && e.relatedTarget && panel.contains(e.relatedTarget)) return;
    commit(f);
  });
  document.addEventListener("keydown", (e) => {
    const box = e.target;
    if (!box.classList || !box.classList.contains("dtf-input")) return;
    const f = box.closest(".dtf");
    if (e.key === "Enter") {
      e.preventDefault(); // commit the typing, don't submit the form
      commit(f);
      close(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      commit(f);
      open(f);
      const target = panel.querySelector(".dtf-day.is-selected, .dtf-day.is-today, .dtf-opt.is-selected, .dtf-opt[tabindex='0']");
      if (target) target.focus();
    } else if (e.key === "Escape" && openFor === f) {
      e.preventDefault();
      e.stopPropagation();
      close(false);
    }
  });
  document.addEventListener("input", (e) => {
    if (e.target.classList && e.target.classList.contains("dtf-input")) e.target.closest(".dtf").classList.remove("is-invalid");
  });
  document.addEventListener("change", (e) => {
    const box = e.target;
    if (!box.classList || !box.classList.contains("dtr-allday-box")) return;
    const range = box.closest(".dtr");
    initRange(range);
    range.toggleAttribute("data-all-day", box.checked);
    syncRange(range, "all-day");
  });
  // A required date that's still empty (or a box with unparsed typing)
  // blocks the submit before any other handler sees it.
  document.addEventListener(
    "submit",
    (e) => {
      const form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      let bad = null;
      form.querySelectorAll(".dtf").forEach((f) => {
        if (!commit(f, true) && !bad) bad = f;
      });
      if (bad) {
        e.preventDefault();
        e.stopImmediatePropagation();
        input(bad).focus();
      }
    },
    true
  );
  window.addEventListener("resize", () => place());
  document.addEventListener(
    "scroll",
    (e) => {
      if (panel && !panel.hidden && !panel.contains(e.target)) place();
    },
    true
  );

  // For other scripts (holiday_date_sync.js): set a field by its hidden input.
  window.CCDateField = {
    set(hiddenInput, value) {
      const f = hiddenInput && hiddenInput.closest(".dtf");
      if (f) setValue(f, value || "");
    },
    parseDate,
    parseTime,
    fmtDate,
  };
})();
