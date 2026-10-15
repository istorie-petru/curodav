(function () {
  function closeAllSelects() {
    document.querySelectorAll(".notebook-sidebar-select.is-open").forEach(function (w) {
      w.classList.remove("is-open");
      var trigger = w.querySelector(".notebook-sidebar-select-trigger");
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    });
  }

  document.addEventListener("click", function (e) {
    var trigger = e.target.closest(".notebook-sidebar-select-trigger");
    if (trigger) {
      var wrap = trigger.closest(".notebook-sidebar-select");
      var wasOpen = wrap.classList.contains("is-open");
      closeAllSelects();
      if (!wasOpen) {
        wrap.classList.add("is-open");
        trigger.setAttribute("aria-expanded", "true");
      }
      return;
    }

    var option = e.target.closest(".notebook-sidebar-select-option");
    if (option) {
      var select = option.closest(".notebook-sidebar-select");
      var sidebar = option.closest(".notebook-sidebar");
      if (!select || !sidebar) return;
      var name = option.getAttribute("data-notebook-sidebar-tab");
      select.querySelectorAll(".notebook-sidebar-select-option").forEach(function (o) {
        var active = o === option;
        o.classList.toggle("active", active);
        o.setAttribute("aria-selected", String(active));
      });
      // Mirror the picked option's own icon+label onto the trigger (same
      // "trigger reflects the current pick" convention _filter_dropdown.
      // html's own `.ms-summary` already uses, just icon+text here instead
      // of a plain count/name string).
      var triggerIconEl = select.querySelector(".notebook-sidebar-select-icon");
      var triggerLabelEl = select.querySelector(".notebook-sidebar-select-label");
      var optionIcon = option.querySelector(".icon");
      if (triggerIconEl && optionIcon) triggerIconEl.innerHTML = optionIcon.outerHTML;
      if (triggerLabelEl) triggerLabelEl.textContent = option.textContent.trim();
      sidebar.querySelectorAll("[data-notebook-sidebar-panel]").forEach(function (p) {
        p.classList.toggle("is-active", p.getAttribute("data-notebook-sidebar-panel") === name);
      });
      // The plus-icon "add" button next to the dropdown (item A) -- only
      // the one matching the now-active view stays visible; views with no
      // add action (Outline, Relationships, Filters) just never have a
      // matching button to unhide.
      sidebar.querySelectorAll("[data-notebook-sidebar-add]").forEach(function (btn) {
        btn.hidden = btn.getAttribute("data-notebook-sidebar-add") !== name;
      });
      closeAllSelects();
      return;
    }

    if (!e.target.closest(".notebook-sidebar-select")) closeAllSelects();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeAllSelects();
  });

  // Collapse/expand toggle -- same `html[data-...]` + localStorage
  // mechanism the left nav's own `#sidebar-expand-toggle` uses
  // (sidebar_tree.js), applied pre-paint by base.html's inline <head>
  // script; this just has to (1) sync the button's title/aria-pressed with
  // whatever that script already applied, same as sidebar_tree.js's
  // initExpandToggle, and (2) flip it on click. One shared preference
  // across both Notebook pages (not two independent ones), so collapsing
  // it on Browse carries over to the Editor and back.
  var COLLAPSED_KEY = "commandCenterWeb.notebookSidebarCollapsed";

  function isCollapsed() {
    return document.documentElement.hasAttribute("data-notebook-sidebar-collapsed");
  }

  function setCollapsed(collapsed) {
    if (collapsed) {
      document.documentElement.setAttribute("data-notebook-sidebar-collapsed", "1");
      localStorage.setItem(COLLAPSED_KEY, "1");
    } else {
      document.documentElement.removeAttribute("data-notebook-sidebar-collapsed");
      localStorage.removeItem(COLLAPSED_KEY);
    }
    var toggle = document.getElementById("notebook-sidebar-toggle");
    if (toggle) {
      toggle.setAttribute("aria-pressed", collapsed ? "false" : "true");
      toggle.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
      toggle.setAttribute("aria-label", toggle.title);
    }
  }

  // Runs immediately (this script is `defer`, so the DOM is already parsed)
  // to correct the button's server-rendered "expanded" default against
  // whatever base.html's pre-paint script actually applied.
  setCollapsed(isCollapsed());

  document.addEventListener("click", function (e) {
    if (e.target.closest("#notebook-sidebar-toggle")) {
      setCollapsed(!isCollapsed());
    }
  });
})();
