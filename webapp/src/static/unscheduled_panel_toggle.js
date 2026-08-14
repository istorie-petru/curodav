// Collapse/expand the "Unscheduled work" sidebar on the merged Week view
// (1.9 side work, templates/calendar_week.html -- direct feedback: "make
// the Unscheduled work block collapsible via a sidebar button"). Purely a
// per-device display preference, same category as timeline.js's gutter
// width -- persisted client-side only (localStorage), no server state.

(function () {
  const panel = document.getElementById("unscheduled-panel");
  const toggle = document.getElementById("unscheduled-panel-toggle");
  if (!panel || !toggle) return;

  const STORAGE_KEY = "cc-unscheduled-panel-collapsed";

  function apply(collapsed) {
    panel.classList.toggle("collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.title = collapsed ? "Expand Unscheduled work" : "Collapse Unscheduled work";
    toggle.setAttribute("aria-label", toggle.title);
  }

  apply(localStorage.getItem(STORAGE_KEY) === "1");

  toggle.addEventListener("click", () => {
    const collapsed = !panel.classList.contains("collapsed");
    apply(collapsed);
    localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
  });
})();
