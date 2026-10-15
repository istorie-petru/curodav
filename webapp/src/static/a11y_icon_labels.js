(function () {
  var NAMEABLE_TAGS = /^(BUTTON|A|LABEL|INPUT)$/;
  var SELECTOR = "[title]:not([aria-label]):not([aria-labelledby])";

  function maybeLabel(el) {
    if (!NAMEABLE_TAGS.test(el.tagName)) return;
    var text = (el.textContent || "").replace(/\s+/g, "");
    if (text.length > 0) return; // has its own visible accessible name already
    var title = el.getAttribute("title");
    if (title) el.setAttribute("aria-label", title);
  }

  function applyLabels(root) {
    if (root.nodeType !== 1 && root.nodeType !== 9) return;
    if (root.matches && root.matches(SELECTOR)) maybeLabel(root);
    if (root.querySelectorAll) {
      root.querySelectorAll(SELECTOR).forEach(maybeLabel);
    }
  }

  function init() {
    applyLabels(document);

    // Modal content (modal.js innerHTML swap), async-CRUD region refreshes
    // (async_crud.js's refreshRegion) and quick_add/command-palette inserts
    // all add nodes to the DOM without ever going through a per-feature
    // re-init hook the way this app's other modal-injected scripts do
    // (wireContent()'s window.CCWhatever.init(body) calls) -- a single
    // MutationObserver covers all of them at once, so this file needs no
    // wiring into modal.js/async_crud.js at all.
    if (!window.MutationObserver) return;
    var observer = new MutationObserver((mutations) => {
      mutations.forEach((m) => {
        m.addedNodes.forEach((node) => applyLabels(node));
      });
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
