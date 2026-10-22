(function () {
  const EXPANDED_KEY = "commandCenterWeb.sidebarExpanded";
  const CHILD_KEY_PREFIX = "commandCenterWeb.sidebarTreeOpen."; // + space name

  function isExpanded() {
    return document.documentElement.hasAttribute("data-sidebar-expanded");
  }

  function setExpanded(expanded) {
    if (expanded) {
      document.documentElement.setAttribute("data-sidebar-expanded", "1");
      localStorage.setItem(EXPANDED_KEY, "1");
    } else {
      document.documentElement.removeAttribute("data-sidebar-expanded");
      localStorage.removeItem(EXPANDED_KEY);
    }
    document.querySelectorAll("#sidebar-expand-toggle, [data-sidebar-toggle]").forEach((toggle) => {
      toggle.setAttribute("aria-pressed", expanded ? "true" : "false");
      toggle.title = expanded ? "Collapse sidebar" : "Expand sidebar";
      toggle.setAttribute("aria-label", toggle.title);
    });
    window.dispatchEvent(new Event("resize"));
    setTimeout(() => window.dispatchEvent(new Event("resize")), 180);
  }

  function initExpandToggle() {
    // Sync the buttons' own state with what the head script already
    // applied -- this file loads after that inline script has run.
    setExpanded(isExpanded());
    document.querySelectorAll("#sidebar-expand-toggle, [data-sidebar-toggle]").forEach((toggle) => {
      if (toggle.dataset.bound) return;
      toggle.dataset.bound = "1";
      toggle.addEventListener("click", () => setExpanded(!isExpanded()));
    });
  }

  // Per-space project-tree toggles. A space with no stored preference keeps
  // whatever the server rendered (open only when one of its own children is
  // the active page, see base.html) -- localStorage only overrides that
  // once the user has actually clicked a chevron for that space.
  function initTreeToggles() {
    document.querySelectorAll(".sidebar-tree-item.has-children").forEach((item) => {
      const toggleBtn = item.querySelector(".sidebar-tree-toggle");
      if (!toggleBtn || toggleBtn.dataset.bound) return;
      toggleBtn.dataset.bound = "1";
      const spaceName = item.dataset.spaceName || "";
      const stored = spaceName ? localStorage.getItem(CHILD_KEY_PREFIX + spaceName) : null;
      if (stored === "1") toggleBtn.setAttribute("aria-expanded", "true");
      else if (stored === "0") toggleBtn.setAttribute("aria-expanded", "false");
      // stored === null: no override, keep the server-rendered default.

      toggleBtn.addEventListener("click", () => {
        const nowOpen = toggleBtn.getAttribute("aria-expanded") !== "true";
        toggleBtn.setAttribute("aria-expanded", nowOpen ? "true" : "false");
        if (spaceName) localStorage.setItem(CHILD_KEY_PREFIX + spaceName, nowOpen ? "1" : "0");
      });
    });
  }

  function init() {
    initExpandToggle();
    initTreeToggles();
  }

  document.addEventListener("DOMContentLoaded", init);
  // Cross-document view transitions (see base.html's no-cdt note) can
  // re-run without a fresh DOMContentLoaded on some navigations -- the
  // dataset.bound guards above make re-running init() harmless/idempotent.
  document.addEventListener("pagereveal", init);
})();
