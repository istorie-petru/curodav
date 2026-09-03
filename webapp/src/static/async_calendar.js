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
      return window.ccApi.refreshRegion(weekUrl, "week-grid").then(function () {
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

  // A month/4-week/week page re-renders on task changes too (a due-date
  // drag or an allocation IS a task's scheduling; project_calendar.js's
  // own mutations dispatch type "task", same as calendar_month_drag.js's
  // task-chip drag now does).
  document.addEventListener("cc-entity-changed", function (e) {
    var detail = e.detail || {};
    if (detail.type !== "event" && detail.type !== "task") return;
    var refresher = regionEl ? refreshMonth : fourweekEl ? refreshFourweek : weekEl ? refreshWeek : null;
    if (!refresher) return;
    detail.claimed = true;
    refresher().catch(function () {
      window.location.reload();
    });
  });
})();