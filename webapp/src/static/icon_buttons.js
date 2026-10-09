// Icon + label buttons in page headers and toolbars show only the icon, with
// the label kept as tooltip and accessible name (frontend-conventions.md,
// Buttons). Wrapping the label text lets CSS hide it without touching every
// template; modal footers keep their labels.
(function () {
  var SCOPE = ".page-header-narrow-actions, .bulk-actions-bar";
  var BUTTON = ".btn:not(.btn-keep-label)";

  function collapse(btn) {
    if (btn.dataset.iconOnly || !btn.querySelector(".icon")) return;
    var text = (btn.textContent || "").replace(/\s+/g, " ").trim();
    if (!text) return;
    btn.dataset.iconOnly = "1";
    if (!btn.hasAttribute("title")) btn.setAttribute("title", text);
    if (!btn.hasAttribute("aria-label")) btn.setAttribute("aria-label", text);
    Array.from(btn.childNodes).forEach(function (node) {
      if (node.nodeType === 3 && node.textContent.trim()) {
        var span = document.createElement("span");
        span.className = "btn-label";
        node.parentNode.replaceChild(span, node);
        span.textContent = node.textContent.trim();
      }
    });
    btn.classList.add("btn-icon-only");
  }

  function apply(root) {
    if (!root.querySelectorAll) return;
    root.querySelectorAll(SCOPE).forEach(function (scope) {
      scope.querySelectorAll(BUTTON).forEach(collapse);
    });
    var scope = root.closest && root.closest(SCOPE);
    if (scope && root.matches && root.matches(BUTTON)) collapse(root);
  }

  apply(document);
  if (!window.MutationObserver) return;
  new MutationObserver(function (mutations) {
    mutations.forEach(function (m) {
      m.addedNodes.forEach(function (n) { if (n.nodeType === 1) apply(n); });
    });
  }).observe(document.body, { childList: true, subtree: true });
})();
