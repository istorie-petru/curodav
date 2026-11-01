// The page header region: publishes its height as --hdr-h (the sidebar and page sit beneath it) and moves page
// controls that do not fit on the strip's line (beside the title, on phones) into a ... menu.
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
      {
        // Desktop: the whole strip is one line. Phones: the strip wraps (views get their own row), so only the
        // controls beside the title must fit their own box.
        var box = DESKTOP.matches ? strip : actions;
        // Squeezed means something overflows or a title is already cut short; spacing goes before anything moves.
        var squeezed = function () {
          if (box.scrollWidth > box.clientWidth + 1) return true;
          return Array.prototype.some.call(strip.querySelectorAll("*"), function (el) {
            return el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).textOverflow === "ellipsis";
          });
        };
        strip.classList.remove("is-tight");
        if (squeezed()) strip.classList.add("is-tight");
        var kids = Array.prototype.filter.call(actions.children, function (c) { return getComputedStyle(c).display !== "none"; });
        var guard = kids.length;
        while (guard-- > 0 && box.scrollWidth > box.clientWidth + 1 && kids.length) {
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

// The header's back arrow returns to the view the user came from (page, view mode, filters, scroll) via real history;
// its href, the parent page, is only the fallback for a fresh tab or an arrival from outside the app.
(function () {
  var SKIP = /^\/(login|setup|logout)(\/|$)/;
  document.addEventListener("click", function (e) {
    var back = e.target.closest && e.target.closest(".page-header-narrow-back");
    if (!back || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var ref;
    try { ref = new URL(document.referrer); } catch (err) { return; }
    if (ref.origin !== location.origin || SKIP.test(ref.pathname) || history.length < 2) return;
    if (ref.pathname + ref.search === location.pathname + location.search) return;
    e.preventDefault();
    history.back();
  });
})();
