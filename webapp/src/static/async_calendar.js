// Calendar async-CRUD (features/async-crud.md): after an event or task
// change elsewhere on the page (a modal create/edit/delete, the month
// grid's own drag-to-move, the command palette, a dashboard widget),
// re-render just this page's calendar region instead of a full reload.
//
// Currently only the Month view (calendar_month.html) has a clean region
// (the static #month-grid; Week/Day grids carry per-block drag bindings
// and are a documented follow-up). Loaded via each calendar template's
// extra_scripts. Claims the change event only when the region is actually
// on this page (the ccApi.claimed protocol); on a refresh failure it
// falls back to a reload so the page converges to server truth.
(function () {
  var regionEl = document.getElementById("month-grid");
  if (!regionEl) return;

  var regionUrl =
    "/calendar/regions?region=month&year=" +
    encodeURIComponent(regionEl.dataset.year || "") +
    "&month=" +
    encodeURIComponent(regionEl.dataset.month || "");
  var label = regionEl.dataset.label || "";
  if (label) regionUrl += "&label=" + encodeURIComponent(label);

  function refresh() {
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

  document.addEventListener("cc-entity-changed", function (e) {
    var detail = e.detail || {};
    if (detail.type !== "event" && detail.type !== "task") return;
    detail.claimed = true;
    refresh().catch(function () {
      window.location.reload();
    });
  });
})();