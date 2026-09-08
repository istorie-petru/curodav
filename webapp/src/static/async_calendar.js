// Calendar async-CRUD (features/async-crud.md): after an event or task
// change elsewhere on the page (a modal create/edit/delete, the calendar
// grid's own drag-to-move, the command palette, a dashboard widget),
// re-render just this page's calendar region instead of a full reload.
//
// Three regions, loaded by whichever calendar template includes this
// script:
//   * Month (calendar_month.html): #month-grid, static; re-bound via
//     CCMonthGridCreate / CCMonthGridDrag.
//   * 4-Week (calendar_fourweek.html): #fourweek-grid -- same grid shape
//     and the same two re-bind hooks as Month (2026-08-31: split out of
//     calendar_fourweek.html's own former inline markup, which had no
//     region at all -- a drag's POST landed fine server-side but nothing
//     on screen ever reflected it, since nothing here claimed the change
//     event for that page; see _calendar_fourweek_grid.html's comment).
//   * Week (calendar_week.html): #week-grid, the whole
//     .project-calendar-layout; re-bound via CCWeekGrid / CCProjectCalendar /
//     CCWeekAllDayDrag / CCUnscheduledPanel. Its mutation endpoints (work-allocation create/
//     move/delete in project_calendar.js) POST through ccApi with
//     change.type "task" and dispatch this same event, so the refreshed
//     region is also what moves the dragged block out from under the
//     pointer -- the swapped-in DOM replaces the stale one the drag was
//     mutating.
//   * Day (calendar_day.html): #day-grid -- added alongside the fix for
//     the direct bug report "two events overlap, I move one, they still
//     show half-width" (calendar.js's `.time-event` drag handler now
//     dispatches type "event" on a successful move/resize instead of only
//     patching the `.te-time` label in place). Day had no region at all
//     before this -- a Day-view drag had nothing to refresh and stayed
//     stale until a real page load. Re-bound the same way Week's
//     `.time-event`/create-col bindings are, via CCWeekGrid.init()
//     (calendar.js's shared init: it queries generically, not by page, so
//     it works unmodified here).
//
// Claims the change event only when a region is actually on this page (the
// ccApi.claimed protocol); on a refresh failure it falls back to a reload so
// the page converges to server truth.
(function () {
  var regionEl = document.getElementById("month-grid");
  if (regionEl) {
    var regionUrl =
      "/calendar/regions?region=month&year=" +
      encodeURIComponent(regionEl.dataset.year || "") +
      "&month=" +
      encodeURIComponent(regionEl.dataset.month || "");
    var label = regionEl.dataset.label || "";
    if (label) regionUrl += "&label=" + encodeURIComponent(label);

    function refreshMonth() {
      return window.ccApi.refreshRegion(regionUrl, "month-grid").then(function () {
        regionEl = document.getElementById("month-grid");
        // Re-bind the freshly-rendered grid's interactions -- the month
        // drag/create scripts bind per-element at load, so a swapped-in
        // region needs their init re-run. Both are idempotent over fresh
        // DOM (they re-query their own collections each call).
        if (window.CCMonthGridCreate) window.CCMonthGridCreate.init();
        if (window.CCMonthGridDrag) window.CCMonthGridDrag.init();
      });
    }
  }

  var fourweekEl = document.getElementById("fourweek-grid");
  if (fourweekEl) {
    var fourweekUrl = "/calendar/regions?region=fourweek&date_=" + encodeURIComponent(fourweekEl.dataset.date || "");
    if (fourweekEl.dataset.label) fourweekUrl += "&label=" + encodeURIComponent(fourweekEl.dataset.label);

    function refreshFourweek() {
      return window.ccApi.refreshRegion(fourweekUrl, "fourweek-grid").then(function () {
        fourweekEl = document.getElementById("fourweek-grid");
        // Same create/drag scripts as Month re-bind here -- they query by
        // class name only (.month-day-cell, .month-event-item[data-uid]),
        // never by a container id, so they work unmodified on this grid.
        if (window.CCMonthGridCreate) window.CCMonthGridCreate.init();
        if (window.CCMonthGridDrag) window.CCMonthGridDrag.init();
      });
    }
  }

  var weekEl = document.getElementById("week-grid");
  if (weekEl) {
    var weekUrl = "/calendar/regions?region=week&date_=" + encodeURIComponent(weekEl.dataset.date || "");
    if (weekEl.dataset.label) weekUrl += "&label=" + encodeURIComponent(weekEl.dataset.label);

    function refreshWeek() {
      // `refreshRegion` does `current.replaceWith(fragment)` -- a wholesale
      // node swap of #week-grid. `.time-grid-wrap` (the actual
      // `overflow-y:auto` scroll container, style.css) is a child of that
      // swapped element, so the fresh node starts at `scrollTop: 0`,
      // discarding whatever position the user had scrolled to. Capture it
      // before the swap and restore it on the new node after.
      var oldScroller = weekEl.querySelector(".time-grid-wrap");
      var scrollTop = oldScroller ? oldScroller.scrollTop : null;
      return window.ccApi.refreshRegion(weekUrl, "week-grid").then(function () {
        weekEl = document.getElementById("week-grid");
        if (scrollTop !== null && weekEl) {
          var newScroller = weekEl.querySelector(".time-grid-wrap");
          if (newScroller) newScroller.scrollTop = scrollTop;
        }
        // Re-bind the swapped-in grid: ordinary events + drag-to-create
        // (calendar.js), work-allocation blocks + unscheduled-task drag
        // source (project_calendar.js), sidebar collapse (toggle script).
        // All re-query their own elements/scroll container per init call.
        if (window.CCWeekGrid) window.CCWeekGrid.init();
        if (window.CCProjectCalendar) window.CCProjectCalendar.init();
        if (window.CCWeekAllDayDrag) window.CCWeekAllDayDrag.init();
        if (window.CCUnscheduledPanel) window.CCUnscheduledPanel.init();
      });
    }
  }

  var dayEl = document.getElementById("day-grid");
  if (dayEl) {
    var dayUrl = "/calendar/regions?region=day&date_=" + encodeURIComponent(dayEl.dataset.date || "");
    if (dayEl.dataset.label) dayUrl += "&label=" + encodeURIComponent(dayEl.dataset.label);

    function refreshDay() {
      return window.ccApi.refreshRegion(dayUrl, "day-grid").then(function () {
        dayEl = document.getElementById("day-grid");
        // Same shared init as Week's ordinary events + drag-to-create --
        // Day never loads project_calendar.js/CCWeekAllDayDrag/
        // CCUnscheduledPanel (no work-allocation blocks or unscheduled
        // panel on this page), so only the one re-bind applies here.
        if (window.CCWeekGrid) window.CCWeekGrid.init();
      });
    }
  }

  // A month/4-week/week/day page re-renders on task changes too (a due-date
  // drag or an allocation IS a task's scheduling; project_calendar.js's
  // own mutations dispatch type "task", same as calendar_month_drag.js's
  // task-chip drag now does).
  document.addEventListener("cc-entity-changed", function (e) {
    var detail = e.detail || {};
    if (detail.type !== "event" && detail.type !== "task") return;
    var refresher = regionEl ? refreshMonth : fourweekEl ? refreshFourweek : weekEl ? refreshWeek : dayEl ? refreshDay : null;
    if (!refresher) return;
    detail.claimed = true;
    refresher().catch(function () {
      window.location.reload();
    });
  });
})();