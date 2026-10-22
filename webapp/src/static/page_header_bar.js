// The page header region: publishes its height as --hdr-h (the sidebar and page sit beneath it) and moves page
// controls that do not fit on the strip's line into a ... menu.
(function () {
  var DESKTOP = window.matchMedia("(min-width: 721px)");

  function setup(region) {
    var strip = region.querySelector(".page-header-narrow");
    var actions = strip && strip.querySelector(".page-header-narrow-actions");
    var more = null;
    var panel = null;
    var moved = [];

    function publish() {
      if (!DESKTOP.matches) return;
      var root = document.documentElement.style;
      root.setProperty("--hdr-h", strip.getBoundingClientRect().height + "px");
      root.setProperty("--hdr-total", region.getBoundingClientRect().height + "px");
    }

    function closePanel() { if (panel) panel.hidden = true; }

    function ensureMore() {
      if (more) return;
      more = document.createElement("button");
      more.type = "button";
      more.className = "icon-btn page-header-more";
      more.title = "More";
      more.setAttribute("aria-label", "More");
      more.setAttribute("aria-haspopup", "true");
      more.textContent = "\u22ef";
      panel = document.createElement("div");
      panel.className = "page-header-more-panel";
      panel.hidden = true;
      document.body.appendChild(panel);
      more.addEventListener("click", function (e) {
        e.stopPropagation();
        panel.hidden = !panel.hidden;
        if (!panel.hidden) {
          var r = more.getBoundingClientRect();
          panel.style.top = r.bottom + 4 + "px";
          panel.style.right = Math.max(8, window.innerWidth - r.right) + "px";
        }
      });
      document.addEventListener("click", function (e) {
        if (panel && !panel.hidden && !panel.contains(e.target) && !e.target.closest(".multiselect-panel, .action-menu-panel, .dtp-panel")) closePanel();
      });
      document.addEventListener("keydown", function (e) { if (e.key === "Escape") closePanel(); });
    }

    function fit() {
      if (!actions) { publish(); return; }
      moved.slice().reverse().forEach(function (node) { actions.insertBefore(node, more); });
      moved = [];
      if (more) { more.remove(); closePanel(); }
      if (DESKTOP.matches) {
        var kids = Array.prototype.filter.call(actions.children, function (c) { return getComputedStyle(c).display !== "none"; });
        var guard = kids.length;
        while (guard-- > 0 && strip.scrollWidth > strip.clientWidth + 1 && kids.length) {
          ensureMore();
          if (!more.parentNode) actions.appendChild(more);
          var last = kids.pop();
          if (last.id === "notebook-sidebar-toggle") { last = kids.pop(); if (!last) break; }
          moved.unshift(last);
          panel.insertBefore(last, panel.firstChild);
        }
      }
      publish();
    }

    var queued = false;
    function schedule() {
      if (queued) return;
      queued = true;
      requestAnimationFrame(function () { queued = false; fit(); });
    }
    new ResizeObserver(schedule).observe(region);
    new ResizeObserver(schedule).observe(strip);
    window.addEventListener("resize", schedule);
    DESKTOP.addEventListener("change", schedule);
    fit();
  }

  function init() {
    var region = document.querySelector(".page-header-region");
    if (region) setup(region);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
