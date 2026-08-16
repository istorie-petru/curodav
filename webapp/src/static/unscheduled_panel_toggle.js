// Collapse/expand the "Unscheduled work" sidebar on the merged Week view
// (1.9 side work, templates/calendar_week.html -- direct feedback: "make
// the Unscheduled work block collapsible via a sidebar button"). Purely a
// per-device display preference, same category as timeline.js's gutter
// width -- persisted client-side only (localStorage), no server state.

(function () {
  const STORAGE_KEY = "cc-unscheduled-panel-collapsed";

  function apply(collapsed) {
    const panel = document.getElementById("unscheduled-panel");
    const toggle = document.getElementById("unscheduled-panel-toggle");
    if (!panel || !toggle) return;
    panel.classList.toggle("collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.title = collapsed ? "Expand Unscheduled work" : "Collapse Unscheduled work";
    toggle.setAttribute("aria-label", toggle.title);
  }

  // init() is re-invocable: async_calendar.js re-runs it after swapping in
  // a fresh #week-grid region (async-CRUD, features/async-crud.md) so the
  // newly-rendered collapse button gets its click binding again. apply()
  // re-queries the panel/toggle each call, so a fresh DOM is handled.
  function init() {
    const toggle = document.getElementById("unscheduled-panel-toggle");
    if (!toggle) return;
    apply(localStorage.getItem(STORAGE_KEY) === "1");
    toggle.addEventListener("click", () => {
      const panel = document.getElementById("unscheduled-panel");
      if (!panel) return;
      const collapsed = !panel.classList.contains("collapsed");
      apply(collapsed);
      localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
    });
  }

  init();
  window.CCUnscheduledPanel = { init: init };
})();
