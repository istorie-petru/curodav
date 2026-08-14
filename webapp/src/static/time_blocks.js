// Sleep Time / Leisure Time scheduling warning (Settings > Sleep & Leisure
// Time) -- shared by static/calendar.js (ordinary event drag-create/move/
// resize) and static/project_calendar.js (work-allocation drag-create/
// move) on the Week/Day views. Purely advisory: this only ever shows a
// toast, it never blocks a save -- a time block is guidance ("this time is
// normally protected"), not a hard constraint anything else in the app
// enforces.
//
// Reads its data from a page-local <script type="application/json"
// id="cc-time-blocks"> tag (calendar_week.html/calendar_day.html) --
// absent on any page that doesn't render one (Month, /week planning, the
// project Week Calendar), so every function here is a silent no-op there
// instead of a hard dependency those pages would otherwise need to grow.

(function () {
  const el = document.getElementById("cc-time-blocks");
  let BLOCKS = [];
  if (el) {
    try {
      BLOCKS = JSON.parse(el.textContent || "[]");
    } catch (err) {
      BLOCKS = [];
    }
  }

  const WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

  function weekdayName(dateStr) {
    // UTC midnight, same "don't let the browser's local timezone shift
    // the calendar date" reasoning static/calendar_month_drag.js's own
    // shiftDate uses.
    return WEEKDAY_NAMES[new Date(dateStr + "T00:00:00Z").getUTCDay()];
  }

  // First block ({kind, label, days, start_min, end_min}) that overlaps
  // `dateStr`'s [startMin, endMin) range, or null. Half-open interval
  // comparison, same convention grid_layout.py's own overlap math uses.
  function findOverlap(dateStr, startMin, endMin) {
    if (!BLOCKS.length || !dateStr) return null;
    const day = weekdayName(dateStr);
    for (const b of BLOCKS) {
      if (!b.days.includes(day)) continue;
      if (startMin < b.end_min && endMin > b.start_min) return b;
    }
    return null;
  }

  // Shows the warning toast if `dateStr`/[startMin,endMin) overlaps a
  // configured block; a silent no-op otherwise (including when no blocks
  // are configured at all, or toast.js hasn't loaded).
  function warnIfOverlapping(dateStr, startMin, endMin) {
    const hit = findOverlap(dateStr, startMin, endMin);
    if (!hit || !window.ccToast) return;
    const kindLabel = hit.kind === "sleep" ? "Sleep Time" : "Leisure Time";
    window.ccToast({
      message: `Heads up: this overlaps ${kindLabel}${hit.label ? ` (${hit.label})` : ""}.`,
      variant: "warning",
      duration: 3500,
    });
  }

  window.ccTimeBlocks = { findOverlap, warnIfOverlapping };

  // ------------------------------------------------------------------ //
  // Initial scroll: never open the Week/Day grid scrolled to an hour
  // marked as Sleep Time (direct feedback: "if sleep from 00-06 AM, the
  // week/day views should start from 6 AM, not 12 AM"). Looks at every
  // visible day column's own date -- Week has up to 7, Day has 1 -- and,
  // if ANY of them has a Sleep block covering midnight (start_min <= 0 <
  // end_min), scrolls down to clear the LATEST such block's end time, so
  // no visible day's sleep hours sit at the very top. A no-op when no
  // Sleep block covers midnight on any visible day -- the grid opens at
  // the top exactly as before this existed. Leisure Time is deliberately
  // excluded here -- the feedback named Sleep specifically, and a Leisure
  // block is never long/early enough to be "the start of the day" the way
  // a night's sleep is.
  // ------------------------------------------------------------------ //
  const wrap = document.querySelector(".time-grid-wrap");
  const bodyEl = document.querySelector(".time-grid-body");
  const dayCols = Array.from(document.querySelectorAll(".time-col[data-date]"));
  if (wrap && bodyEl && dayCols.length && BLOCKS.length) {
    let clearMin = null;
    dayCols.forEach((col) => {
      const dateStr = col.dataset.date;
      if (!dateStr) return;
      const day = weekdayName(dateStr);
      BLOCKS.forEach((b) => {
        if (b.kind !== "sleep" || !b.days.includes(day)) return;
        if (b.start_min <= 0 && b.end_min > 0) {
          clearMin = clearMin === null ? b.end_min : Math.max(clearMin, b.end_min);
        }
      });
    });
    if (clearMin !== null) {
      const pxPerHour = Number(document.body.dataset.pxPerHour || 48);
      // .time-grid-body's own top padding is half an hour (style.css) --
      // the same offset the hour gutter labels and every event already
      // render at -- and .time-grid-top/.time-grid-head sit sticky ABOVE
      // it in normal flow, so measuring the body's real rendered offset
      // (rather than assuming a fixed header height) keeps this correct
      // even if that header's own height ever changes.
      const bodyOffset = bodyEl.getBoundingClientRect().top - wrap.getBoundingClientRect().top + wrap.scrollTop;
      wrap.scrollTop = Math.max(0, bodyOffset + pxPerHour * 0.5 + (clearMin / 60) * pxPerHour);
    }
  }
})();
