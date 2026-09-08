// Icon-only accessible names (audit-fixes-2.0.md slice 5, documentation/
// reports/full-app-audit-2026-09-07.md finding: "icon-only buttons relying
// on `title` alone with no `aria-label`" -- row-delete buttons, Edit/Delete
// icon links across settings pages, swatch pickers, work-session/relation
// remove buttons, etc.). `title` alone gives icon-only controls a *hover*
// label but is an unreliable accessible-name source (some AT/browser combos
// don't expose it at all), and the audit found ~20 call sites relying on it
// with no `aria-label` fallback.
//
// Landed as one shared, global default instead of hand-editing every call
// site (the audit's own suggestion) -- this app already has one icon-button
// idiom (`.icon-btn` is the sole icon-button class app-wide, see the audit's
// UI-consistency section) but the bare `title`-only pattern also shows up on
// several non-`.icon-btn` elements (`.icon-picker-current`,
// `.color-swatch-current`, `.checklist-check`, `.checklist-delete`, the
// icon/color swatch `<label>`s), so this scans for the underlying pattern
// (a `[title]` with no accessible name of its own and no visible text)
// rather than one specific class -- it also means any future icon-only
// control gets a correct name for free, with nothing to remember to add.
//
// Elements with real visible text (e.g. _calendar_week_grid.html's all-day
// task links, which render an icon *and* the title as text) are left alone
// -- their accessible name already comes from that text, and overwriting it
// with just the `title` string would make it *less* accurate (WCAG 2.5.3
// wants any visible label text to remain part of the accessible name), not
// more.
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
