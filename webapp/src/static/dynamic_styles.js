// Generic `data-style` -> CSSOM applier (2026-09-07, audit-fixes-2.0.md
// item 11 -- CSP `'unsafe-inline'` elimination dropped `'unsafe-inline'`
// from style-src too, which blocks every `style="..."` HTML attribute, not
// just `<style>` tags). A handful of elements across the app need a value
// that's genuinely per-request/per-row computed (calendar grid event
// top/height/left/width, a label/Space's accent color, a project's percent-
// complete progress bar) -- values that can't become a fixed CSS class
// (they vary) and can't become a nonced `<style>` tag (nonces don't cover
// attributes). The standard CSP-strict technique for this is: render the
// computed value(s) into a `data-*` attribute instead of `style=`, then set
// them via the CSSOM (`element.style.setProperty(...)`) from JS -- a CSSOM
// write is not restricted by style-src at all (only `<style>` elements and
// `style=` attributes are), regardless of nonce.
//
// `data-style` mimics the `style="..."` syntax it replaces exactly
// (semicolon-separated `prop:value` declarations, including custom
// properties like `--hr-h:48px`) so converting a call site is a mechanical
// `style="..."` -> `data-style="..."` rename with no template logic
// change -- see _calendar_day_grid.html/_calendar_week_grid.html/
// _detail_cover.html/_widget_spaces_projects.html for the call sites this
// replaced. Setting arbitrary-looking CSS text via `setProperty` cannot
// execute script (unlike the old IE `expression()` CSS hack, and modern
// browsers don't run script from `url()` values either) -- this is safe
// even though the values are server-computed from row data.
//
// Global + MutationObserver, same convention as a11y_icon_labels.js --
// covers async-CRUD region refreshes (async_crud.js), modal-injected
// content, and quick_add/command-palette inserts with no per-feature
// re-init hook needed.
(function () {
  function applyStyle(el) {
    var raw = el.getAttribute("data-style");
    if (!raw) return;
    raw.split(";").forEach(function (decl) {
      var idx = decl.indexOf(":");
      if (idx === -1) return;
      var prop = decl.slice(0, idx).trim();
      var value = decl.slice(idx + 1).trim();
      if (!prop || !value) return;
      el.style.setProperty(prop, value);
    });
  }

  function applyAll(root) {
    if (root.nodeType !== 1 && root.nodeType !== 9) return;
    if (root.matches && root.matches("[data-style]")) applyStyle(root);
    if (root.querySelectorAll) {
      root.querySelectorAll("[data-style]").forEach(applyStyle);
    }
  }

  function init() {
    applyAll(document);

    if (!window.MutationObserver) return;
    var observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (m) {
        m.addedNodes.forEach(function (node) {
          applyAll(node);
        });
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
