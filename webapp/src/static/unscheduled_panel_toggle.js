// Collapse/expand the "Unscheduled work" panel on the merged Week view
// (1.9 side work, templates/calendar_week.html -- direct feedback: "make
// the Unscheduled work block collapsible via a sidebar button"). Purely a
// per-device display preference, same category as timeline.js's gutter
// width -- persisted client-side only (localStorage), no server state.
//
// 2026-09-26 (item 11 redesign): briefly had a second trigger in the
// page's own narrow-header actions row alongside the panel's own header
// button, both sharing `.unscheduled-panel-toggle-btn`. Reverted
// 2026-09-27 (direct feedback) -- back to just the one in-panel button
// (`#unscheduled-panel-toggle`), though `apply()`/`init()` below still
// operate on `.unscheduled-panel-toggle-btn` generically rather than that
// specific id, so a second trigger could come back without touching this
// file again.

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
