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
//
// 2026-09-09, slice 6 of the "FullCalendar-parity interactions" arc: also
// wires up AJAX prev/next navigation (4-Week and Week only -- Month's own
// page route is retired, see routers/calendar.py's calendar_root_redirect
// docstring, so there's no reachable page to wire nav clicks on for it).
// `bindCalNav` below is the shared helper both regions call.
(function () {
  // Shared prev/next AJAX-nav wiring for a region that has `.cal-nav-prev`/
  // `.cal-nav-next` <a> links and a `#cal-nav-label` span in its page header
  // (calendar_fourweek.html / calendar_week.html). `refreshFn(dateVal)` must
  // return the same kind of promise `ccApi.refreshRegion` does, resolving
  // after the region's DOM has been swapped in for `dateVal`.
  //
  // The plain <a href> on each link stays the real, bookmarkable URL (also
  // this function's no-JS fallback and its own failure fallback) --
  // clicking just intercepts it into a region-fragment fetch instead of a
  // full page load. After a swap, the freshly-rendered region's own
  // data-label-text/data-prev/data-next (set server-side, same request-
  // scoped `label_text`/`prev_*`/`next_*` values the full page would have
  // used) drive the visible label and the two links' *next* href -- no
  // second round-trip needed to know what "the week after this one" is.
  // `history.pushState` keeps the URL bar (and therefore bookmarks) in
  // sync; the `popstate` listener makes the browser's own Back/Forward
  // buttons drive the same fetch-and-swap instead of just changing the
  // address bar with nothing on screen reacting to it.
  function bindCalNav(gridId, pageBase, refreshFn) {
    var prevLink = document.querySelector(".cal-nav-prev");
    var nextLink = document.querySelector(".cal-nav-next");
    var labelEl = document.getElementById("cal-nav-label");
    if (!prevLink && !nextLink) return;

    function applyDataset() {
      var gridEl = document.getElementById(gridId);
      if (!gridEl) return;
      var lq = gridEl.dataset.label ? "&label=" + encodeURIComponent(gridEl.dataset.label) : "";
      if (prevLink && gridEl.dataset.prev) prevLink.href = pageBase + "?date_=" + gridEl.dataset.prev + lq;
      if (nextLink && gridEl.dataset.next) nextLink.href = pageBase + "?date_=" + gridEl.dataset.next + lq;
      if (labelEl && gridEl.dataset.labelText) {
        labelEl.textContent = gridEl.dataset.labelText;
        document.title = gridEl.dataset.labelText + " - Calendar";
      }
    }

    function go(dateVal, push) {
      refreshFn(dateVal)
        .then(function () {
          applyDataset();
          if (push) {
            var gridEl = document.getElementById(gridId);
            var lq = gridEl && gridEl.dataset.label ? "&label=" + encodeURIComponent(gridEl.dataset.label) : "";
            window.history.pushState({ calNavDate: dateVal }, "", pageBase + "?date_=" + dateVal + lq);
          }
        })
        .catch(function () {
          // Same "converge to server truth" fallback every other refresh
          // failure in this file already takes -- a real navigation always
          // gets the user to a correct page even if the AJAX path failed.
          window.location.href = pageBase + "?date_=" + dateVal;
        });
    }

    if (prevLink) {
      prevLink.addEventListener("click", function (e) {
        e.preventDefault();
        var url = new URL(prevLink.href, window.location.origin);
        go(url.searchParams.get("date_") || "", true);
      });
    }
    if (nextLink) {
      nextLink.addEventListener("click", function (e) {
        e.preventDefault();
        var url = new URL(nextLink.href, window.location.origin);
        go(url.searchParams.get("date_") || "", true);
      });
    }
    window.addEventListener("popstate", function () {
      var params = new URLSearchParams(window.location.search);
      go(params.get("date_") || "", false);
    });
  }

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
    // `dateVal`: optional override for a prev/next nav fetch (bindCalNav
    // below) -- defaults to the region's own current data-date, same as
    // before this param existed, for the mutation-refresh call site
    // (cc-entity-changed listener at the bottom of this file).
    function refreshFourweek(dateVal) {
      var d = dateVal != null ? dateVal : fourweekEl.dataset.date || "";
      var url = "/calendar/regions?region=fourweek&date_=" + encodeURIComponent(d);
      if (fourweekEl.dataset.label) url += "&label=" + encodeURIComponent(fourweekEl.dataset.label);
      return window.ccApi.refreshRegion(url, "fourweek-grid").then(function () {
        fourweekEl = document.getElementById("fourweek-grid");
        // Same create/drag scripts as Month re-bind here -- they query by
        // class name only (.month-day-cell, .month-event-item[data-uid]),
        // never by a container id, so they work unmodified on this grid.
        if (window.CCMonthGridCreate) window.CCMonthGridCreate.init();
        if (window.CCMonthGridDrag) window.CCMonthGridDrag.init();
      });
    }
    bindCalNav("fourweek-grid", "/calendar/fourweek", refreshFourweek);
  }

  var weekEl = document.getElementById("week-grid");
  if (weekEl) {
    // `dateVal`: optional override for a prev/next nav fetch (bindCalNav
    // below) -- defaults to the region's own current data-date, same as
    // before this param existed, for the mutation-refresh call site
    // (cc-entity-changed listener at the bottom of this file). Kept the
    // scroll-preserve behavior for a nav call too, not just a mutation
    // refresh -- carrying the same time-of-day scroll position over when
    // paging to a different week is a reasonable "stay where I was
    // looking" default, not just an artifact of this being one function.
    function refreshWeek(dateVal) {
      var d = dateVal != null ? dateVal : weekEl.dataset.date || "";
      var url = "/calendar/regions?region=week&date_=" + encodeURIComponent(d);
      if (weekEl.dataset.label) url += "&label=" + encodeURIComponent(weekEl.dataset.label);
      // `refreshRegion` does `current.replaceWith(fragment)` -- a wholesale
      // node swap of #week-grid. `.time-grid-wrap` (the actual
      // `overflow-y:auto` scroll container, style.css) is a child of that
      // swapped element, so the fresh node starts at `scrollTop: 0`,
      // discarding whatever position the user had scrolled to. Capture it
      // before the swap and restore it on the new node after.
      var oldScroller = weekEl.querySelector(".time-grid-wrap");
      var scrollTop = oldScroller ? oldScroller.scrollTop : null;
      return window.ccApi.refreshRegion(url, "week-grid").then(function () {
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
    bindCalNav("week-grid", "/calendar/week", refreshWeek);
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