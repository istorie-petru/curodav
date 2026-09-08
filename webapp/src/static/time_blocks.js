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
      title: "Heads up",
      message: `This overlaps ${kindLabel}${hit.label ? ` (${hit.label})` : ""}.`,
      variant: "warning",
      duration: 3500,
    });
  }

  window.ccTimeBlocks = { findOverlap, warnIfOverlapping };
})();
