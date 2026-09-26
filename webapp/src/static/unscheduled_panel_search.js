// "Unscheduled work" panel search box (item 11 redesign, calendar_week.html
// / _calendar_week_grid.html's `#unscheduled-search`) -- a plain client-side
// substring filter over the already-rendered `.unscheduled-task-item` rows
// (title + whatever else is in the row's text, so a project/tag pill also
// matches), no server round-trip. Deliberately this simple: the panel's own
// list is already small (routers/calendar.py's week_view only ever lists
// OPEN tasks with at least one still-unplaced session for the current
// week), so there's no pagination/query-param case to design for, unlike a
// full Tasks-table search.
//
// re-invocable init(): async_calendar.js calls this after every #week-grid
// region swap (a fresh `#unscheduled-search` node with no bound listener
// yet, same "re-bind after swap" need as project_calendar.js/
// unscheduled_panel_toggle.js's own init() calls there). Typed text is
// deliberately NOT preserved across a swap (the box just resets empty) --
// a swap only ever follows a mutation ("+"/remove-latest/schedule/
// unschedule/delete), a good moment to see the panel's full list again
// rather than staying filtered on a query that mutation may have just
// invalidated.
(function () {
  function normalize(s) {
    return (s || "").toLowerCase();
  }

  function applyFilter(input) {
    const q = normalize(input.value.trim());
    const panel = document.getElementById("unscheduled-panel");
    if (!panel) return;
    panel.querySelectorAll(".unscheduled-task-item").forEach((item) => {
      const haystack = normalize(item.dataset.taskTitle) + " " + normalize(item.textContent);
      item.style.display = !q || haystack.includes(q) ? "" : "none";
    });
  }

  function init() {
    const input = document.getElementById("unscheduled-search");
    if (!input || input.dataset.searchBound) return;
    input.dataset.searchBound = "1";
    input.addEventListener("input", () => applyFilter(input));
  }

  init();
  window.CCUnscheduledSearch = { init: init };
})();
