// Week/Day time grid: initial scroll position + "now" line
// (2026-09-25, UI audit C-7). Before this both views always opened at
// 00:00 -- the first event of a normal day sat a full screen below the
// fold -- and nothing on the grid said what time it currently was.
//
// Two jobs, both on #week-grid (calendar_week.html) and #day-grid
// (calendar_day.html):
//
//   1. Auto-scroll: when the grid's scroller (`.time-grid-wrap`) opens at
//      scrollTop 0 and nothing restored a position, scroll so the earlier
//      of (first timed event, now if today is shown) sits one hour below
//      the sticky header. No events and not today -> 07:00, the same
//      "start of a normal day" fallback most calendar apps use.
//   2. Now-line: a `.now-line` in today's `.time-col` (the column whose
//      data-date matches the browser's own local date), repositioned every
//      minute.
//
// Region swaps: async_calendar.js (and habit_actions.js on Day) replace
// the whole #week-grid/#day-grid node after a change, which drops both the
// line and the scroll position. A childList MutationObserver on the
// region's parent notices the swap and re-runs setup; the last scrollTop
// the user had is carried over (refreshWeek already restores it itself --
// a non-zero scrollTop on the fresh node counts as "restored" and is left
// alone), so a refresh never yanks the grid back to the auto position.
(function () {
  const REGION_IDS = ["week-grid", "day-grid"];
  const PX_PER_HOUR = Number(document.body.dataset.pxPerHour || 48);
  const FALLBACK_HOUR = 7;

  function region() {
    for (const id of REGION_IDS) {
      const el = document.getElementById(id);
      if (el) return el;
    }
    return null;
  }
  if (!region()) return;

  // Planner "Hide sleep hours" (Week only): real minutes -> on-grid
  // minutes, the same transform as grid_layout.collapse_minutes, read from
  // the page's own #cc-sleep-collapse payload (absent on Day).
  let collapse = null;
  const raw = document.getElementById("cc-sleep-collapse");
  if (raw) {
    try {
      const data = JSON.parse(raw.textContent);
      if (data && data.active) collapse = [data.skip_start, data.skip_end];
    } catch (e) {
      collapse = null;
    }
  }
  function toGrid(min) {
    if (!collapse || min <= collapse[0]) return min;
    if (min >= collapse[1]) return min - (collapse[1] - collapse[0]);
    return collapse[0];
  }

  function localIso(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  function nowTopPx() {
    const d = new Date();
    return (toGrid(d.getHours() * 60 + d.getMinutes()) / 60) * PX_PER_HOUR;
  }

  function todayCol(root) {
    return root.querySelector('.time-col[data-date="' + localIso(new Date()) + '"]');
  }

  function placeNowLine() {
    const root = region();
    if (!root) return;
    const col = todayCol(root);
    root.querySelectorAll(".now-line").forEach((l) => {
      if (l.parentElement !== col) l.remove();
    });
    if (!col) return;
    let line = col.querySelector(".now-line");
    if (!line) {
      line = document.createElement("div");
      line.className = "now-line";
      line.setAttribute("aria-hidden", "true");
      col.appendChild(line);
    }
    line.style.top = nowTopPx() + "px";
  }

  let lastScrollTop = null;

  function autoScroll(root) {
    const scroller = root.querySelector(".time-grid-wrap");
    const col = root.querySelector(".time-col");
    if (!scroller || !col) return;
    scroller.addEventListener("scroll", () => {
      lastScrollTop = scroller.scrollTop;
    }, { passive: true });
    // Phones (<=720px): the grid isn't its own scroll box there (the page
    // scrolls, see style.css's main.main-calendar height rule), and
    // scrolling the whole page would push the header/nav off screen.
    if (scroller.scrollHeight <= scroller.clientHeight + 1) return;
    if (scroller.scrollTop > 0) return; // restored by the caller (refreshWeek)
    if (lastScrollTop !== null) {
      scroller.scrollTop = lastScrollTop; // a swap nobody restored (Day refresh, habit check-in)
      return;
    }
    const tops = Array.from(root.querySelectorAll(".time-col .time-event"))
      .map((el) => parseFloat(el.style.top))
      .filter((n) => !isNaN(n));
    if (todayCol(root)) tops.push(nowTopPx());
    const target = tops.length ? Math.min.apply(null, tops) - PX_PER_HOUR : (toGrid(FALLBACK_HOUR * 60) / 60) * PX_PER_HOUR;
    // .time-col's own offset inside the scroller (sticky header + all-day
    // strip + the body's half-hour top padding) minus the sticky part that
    // covers the top of the viewport, so "target" lands just below it;
    // 12px more keeps that hour's own gutter label (centered on its line)
    // from being half-hidden under the sticky strip.
    const sticky = root.querySelector(".time-grid-top");
    const colOffset = col.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
    const stickyH = sticky ? sticky.getBoundingClientRect().height : 0;
    scroller.scrollTop = Math.max(0, colOffset - stickyH + target - 12);
  }

  function setup() {
    const root = region();
    if (!root) return;
    placeNowLine();
    autoScroll(root);
  }

  setup();
  // Reposition the line on the minute boundary, then every minute.
  setTimeout(function tick() {
    placeNowLine();
    setTimeout(tick, 60000 - (Date.now() % 60000));
  }, 60000 - (Date.now() % 60000));

  const parent = region().parentElement;
  if (parent && window.MutationObserver) {
    new MutationObserver((records) => {
      for (const r of records) {
        for (const n of r.addedNodes) {
          if (n.nodeType === 1 && REGION_IDS.indexOf(n.id) !== -1) {
            setup();
            return;
          }
        }
      }
    }).observe(parent, { childList: true });
  }
})();
