// Calendar async-CRUD (features/async-crud.md): after an event or task
// change elsewhere on the page (a modal create/edit/delete, the calendar
// grid's own drag-to-move, the command palette, a dashboard widget),
// re-render just this page's calendar region instead of a full reload.
//
// Two regions, loaded by whichever calendar template includes this script:
//   * Month (calendar_month.html): #month-grid, static; re-bound via
//     CCMonthGridCreate / CCMonthGridDrag.
//   * Week (calendar_week.html): #week-grid, the whole
//     .project-calendar-layout; re-bound via CCWeekGrid / CCProjectCalendar /
//     CCUnscheduledPanel. Its mutation endpoints (work-allocation create/
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
        if (window.CCUnscheduledPanel) window.CCUnscheduledPanel.init();
      });
    }
  }

  // A week page re-renders on task changes too (an allocation IS a task's
  // scheduling; project_calendar.js's own mutations dispatch type "task").
  document.addEventListener("cc-entity-changed", function (e) {
    var detail = e.detail || {};
    if (detail.type !== "event" && detail.type !== "task") return;
    var refresher = regionEl ? refreshMonth : weekEl ? refreshWeek : null;
    if (!refresher) return;
    detail.claimed = true;
    refresher().catch(function () {
      window.location.reload();
    });
  });
})();