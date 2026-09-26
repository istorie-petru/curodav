// Collapse/expand the "Unscheduled work" panel on the merged Week view
// (1.9 side work, templates/calendar_week.html -- direct feedback: "make
// the Unscheduled work block collapsible via a sidebar button"). Purely a
// per-device display preference, same category as timeline.js's gutter
// width -- persisted client-side only (localStorage), no server state.
//
// 2026-09-26 (item 11 redesign): a SECOND trigger was added to the page's
// own narrow-header actions row (calendar_week.html's own "[>>]" button,
// `#unscheduled-panel-toggle-header` -- outside the async-refreshed
// #week-grid region, so it survives a region swap without needing
// re-init) alongside the panel's original header button
// (`#unscheduled-panel-toggle`, inside the region). Both now share the
// `.unscheduled-panel-toggle-btn` class and drive the exact same
// panel/localStorage state -- clicking either one collapses/expands the
// same panel and updates both buttons' title/aria-expanded in lockstep.

(function () {
  const STORAGE_KEY = "cc-unscheduled-panel-collapsed";

  function apply(collapsed) {
    const panel = document.getElementById("unscheduled-panel");
    const toggles = document.querySelectorAll(".unscheduled-panel-toggle-btn");
    if (!panel || !toggles.length) return;
    panel.classList.toggle("collapsed", collapsed);
    toggles.forEach((toggle) => {
      toggle.setAttribute("aria-expanded", String(!collapsed));
      toggle.title = collapsed ? "Expand Unscheduled work" : "Collapse Unscheduled work";
      toggle.setAttribute("aria-label", toggle.title);
    });
  }

  // init() is re-invocable: async_calendar.js re-runs it after swapping in
  // a fresh #week-grid region (async-CRUD, features/async-crud.md) so the
  // newly-rendered in-panel toggle button gets its click binding again --
  // `dataset.toggleBound` keeps that idempotent per-element (the header
  // button lives outside the swapped region, so it's only ever bound
  // once, on the initial page load).
  function init() {
    const toggles = document.querySelectorAll(".unscheduled-panel-toggle-btn");
    if (!toggles.length) return;
    apply(localStorage.getItem(STORAGE_KEY) === "1");
    toggles.forEach((toggle) => {
      if (toggle.dataset.toggleBound) return;
      toggle.dataset.toggleBound = "1";
      toggle.addEventListener("click", () => {
        const panel = document.getElementById("unscheduled-panel");
        if (!panel) return;
        const collapsed = !panel.classList.contains("collapsed");
        apply(collapsed);
        localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
      });
    });
  }

  init();
  window.CCUnscheduledPanel = { init: init };
})();
