// "Hide sleep hours in Planner" (Settings > General, 2026-09-09) client
// helper -- Week view only (templates/calendar_week.html renders the
// `#cc-sleep-collapse` JSON tag this reads; calendar_day.html never does,
// so window.CCSleepCollapse.active is simply false everywhere else and
// every call site below is a no-op there, same as time_blocks.js's own
// "absent tag -> nothing to do" pattern).
//
// The server (grid_layout.py) already collapses `[skip_start, skip_end)`
// out of every event/overlay's own top_px/height_px before rendering --
// that's the actual "cells removed" effect. What's left for the client:
// static/calendar.js's and static/project_calendar.js's drag create/move/
// resize handlers each independently convert a pixel position back into a
// real minutes-since-midnight value to save (`top / PX_PER_HOUR * 60`).
// On a collapsed grid that pixel position is already in COLLAPSED space
// (there's no DOM height for the hidden window at all), so the naive
// conversion is off by exactly the hidden window's width for anything
// below it -- e.g. collapsing 00:00-06:00 would save a 5pm drag as 11am.
// `toReal` is the fix: the exact inverse of grid_layout.collapse_minutes,
// applied to that same raw pixel-derived value before it's formatted and
// POSTed.
(function () {
  const raw = document.getElementById("cc-sleep-collapse");
  let collapse = null;
  if (raw) {
    try {
      const data = JSON.parse(raw.textContent);
      if (data && data.active) collapse = { skipStart: data.skip_start, skipEnd: data.skip_end };
    } catch (e) {
      collapse = null;
    }
  }

  // Total height (px) of the grid's hour column at a given px-per-hour --
  // 24h minus the hidden window's width, mirroring grid_layout.
  // grid_height_px's own minutes math (that function's own return value
  // also folds in the top/bottom half-hour padding via style.css's
  // `height:calc(25 * var(--hr-h))`; this one deliberately doesn't -- it
  // feeds calendar.js's/project_calendar.js's drag CLAMPS, which bound
  // movement against the grid's plain hour span, not its padded CSS box).
  function dayHeightPx(pxPerHour) {
    const totalMinutes = 24 * 60 - (collapse ? collapse.skipEnd - collapse.skipStart : 0);
    return (totalMinutes / 60) * pxPerHour;
  }

  // Inverse of grid_layout.collapse_minutes. Every collapsed-space value a
  // pointer can actually land on is either fully before the hidden window
  // (< skipStart, identity -- unaffected) or at/after the seam (>=
  // skipStart, since collapse_minutes maps skipEnd itself onto skipStart)
  // -- nothing reachable on screen ever needs collapse_minutes' own
  // "clamp to skipStart" branch, that one's only for positioning something
  // whose REAL time already falls inside the now-invisible window (e.g. a
  // leftover event scheduled before this setting existed).
  function toReal(collapsedMinutes) {
    if (!collapse || collapsedMinutes < collapse.skipStart) return collapsedMinutes;
    return collapsedMinutes + (collapse.skipEnd - collapse.skipStart);
  }

  window.CCSleepCollapse = { active: !!collapse, dayHeightPx: dayHeightPx, toReal: toReal };
})();
