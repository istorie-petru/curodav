// notebook_properties_modal.html's Properties rows (2026-10-02, curodav-
// notes/documentation/plans/architecture-notes-module-2026-09-29.md §4 +
// STATE.md) -- client-side add/remove of {key, value} rows, nothing here
// talks to the server; the whole ordered list posts together with the
// rest of the properties form on Save (routers/notebook.py's
// update_document_properties reads parallel property_key[]/
// property_value[] form arrays). Same `data-repeatable-add`/
// `data-repeatable-remove` idiom contact_phone_email_rows.js established,
// but not that script itself, and not its `data-repeatable-rows-scope`
// attribute either -- scoped via its own `data-notebook-properties-scope`
// attribute so this script's listener and contacts' never both try to
// claim the same container (see notebook_properties_modal.html's own
// comment on that div).
//
// 2026-10-02 (direct request, "use a drop down similar to the labels
// one"): the key cell is now _notebook_property_key_picker.html's
// row-scoped dropdown+hidden-proxy, not a plain text input -- this file
// also owns that picker's two behaviors, same spirit as
// contact_phone_email_rows.js owning contact_type_picker's:
//   1. Keep each row's hidden proxy (`name="property_key"`, the thing
//      that actually submits) in sync with whichever radio is checked OR
//      whatever's typed in that row's free-text "new" input.
//   2. Rewrite a cloned `<template>` row's baked-in "tmpl" placeholder
//      (row-scoped radio name + proxy id + data-proxy-target) to a fresh,
//      page-lifetime-unique token, so clicking "+ Add property" more than
//      once doesn't produce two rows whose radios/proxies collide.
(function () {
  let cloneCounter = 0;

  function rewriteClonedPropertyKeyPicker(root) {
    // The hidden proxy is a sibling of `.notebook-property-key-select`,
    // not a descendant of it (see _notebook_property_key_picker.html's
    // macro: the `.multiselect` wrapper and the `<input type="hidden">`
    // are two separate top-level elements the macro emits) -- found by
    // its real submitted name instead of DOM position, simpler than a
    // `~` sibling-combinator query and correct regardless of exactly
    // where the macro places it relative to its wrapper.
    const proxy = root.querySelector('input[name="property_key"]');
    if (!proxy) return; // not every repeatable row has one (none currently don't, but stay defensive)
    cloneCounter += 1;
    const token = "c" + cloneCounter;
    const proxyId = "property-key-proxy-" + token;
    const msId = "property-key-ms-" + token;
    proxy.id = proxyId;
    const wrapper = root.querySelector(".notebook-property-key-select");
    if (wrapper) wrapper.id = msId;
    root.querySelectorAll(".notebook-property-key-radio").forEach(function (radio) {
      radio.name = "property_key_radio__" + token;
      radio.dataset.proxyTarget = proxyId;
    });
    const newInput = root.querySelector(".notebook-property-key-new");
    if (newInput) {
      newInput.dataset.proxyTarget = proxyId;
      newInput.dataset.msTarget = msId;
    }
  }

  function wireContainer(container) {
    if (container.dataset.ccWired) return;
    container.dataset.ccWired = "1";

    container.addEventListener("click", function (e) {
      const addBtn = e.target.closest("[data-repeatable-add]");
      if (addBtn) {
        e.preventDefault();
        const rows = document.getElementById(addBtn.getAttribute("data-repeatable-add"));
        const tmpl = document.getElementById(addBtn.getAttribute("data-repeatable-template"));
        if (rows && tmpl && tmpl.content) {
          const clone = tmpl.content.cloneNode(true);
          rewriteClonedPropertyKeyPicker(clone);
          rows.appendChild(clone);
          const newInput = rows.lastElementChild ? rows.lastElementChild.querySelector("input") : null;
          if (newInput) newInput.focus();
        }
        return;
      }
      const removeBtn = e.target.closest("[data-repeatable-remove]");
      if (removeBtn) {
        e.preventDefault();
        const row = removeBtn.closest(".notebook-property-row");
        if (row) row.remove();
      }
    });
  }

  function init(root) {
    (root || document).querySelectorAll("[data-notebook-properties-scope]").forEach(wireContainer);
  }

  // Radio pick -> proxy sync, same lookup-by-id shape (not `.closest(...)`)
  // as contact_phone_email_rows.js's own sync listener -- app.js's shared
  // multiselect portal moves an OPEN `.multiselect-panel` (the checked
  // radio included) out to `#multiselect-portal` while the user is
  // picking, so ancestry-based lookup would fail at exactly that moment.
  document.addEventListener("change", function (e) {
    if (!e.target.matches || !e.target.matches(".notebook-property-key-radio")) return;
    const targetId = e.target.dataset.proxyTarget;
    const proxy = targetId ? document.getElementById(targetId) : null;
    if (proxy) proxy.value = e.target.value;
  });

  // Free-text "new property name" -> proxy sync, live on every keystroke
  // (not just on Enter/blur) -- Save must capture whatever's typed even if
  // the user never presses Enter at all, same as
  // _widget_list_multiselect.html's own ms_allow_new text input (a real
  // named form field there, always "successful" whether touched or not;
  // here the proxy plays that role instead). Also clears any checked
  // radio in the same panel so the UI doesn't show both a picked option
  // and typed text as if both applied.
  document.addEventListener("input", function (e) {
    if (!e.target.matches || !e.target.matches(".notebook-property-key-new")) return;
    const targetId = e.target.dataset.proxyTarget;
    const proxy = targetId ? document.getElementById(targetId) : null;
    if (!proxy) return;
    proxy.value = e.target.value;
    const panel = e.target.closest(".multiselect-panel");
    const checked = panel ? panel.querySelector(".notebook-property-key-radio:checked") : null;
    if (checked) checked.checked = false;
  });

  // 2026-10-02 direct bugfix ("pressing enter should not also close the
  // modal, but should first of all save the value and keep the modal
  // open") -- this row's own equivalent of app.js's shared "New label..."
  // Enter handler, not a reuse of it: that handler creates a brand-new
  // radio/checkbox sharing the picker's real submitted name, which would
  // put every row's "new key" pick into ONE shared `property_key` radio
  // group instead of this row's own (see this picker's own template
  // comment for why row-scoping exists at all) -- the same conflict a
  // shared `data-repeatable-rows-scope` attribute would have caused,
  // just one layer further in. Deliberately a different input class
  // (`.notebook-property-key-new`, not `.multiselect-new-input`) so that
  // shared handler never fires on it in the first place. The proxy is
  // already kept live-synced by the `input` listener above, so Enter here
  // only needs to stop the browser's native "Enter submits the form"
  // behavior (the actual bug) and give the same "visibly committed"
  // feedback picking a radio gets (trigger summary text updates, same as
  // app.js's updateMsSummary does after its own new-item add).
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;
    if (!e.target.matches || !e.target.matches(".notebook-property-key-new")) return;
    e.preventDefault();
    const value = e.target.value.trim();
    if (!value) return;
    // `data-ms-target` (id lookup), not `e.target.closest(".multiselect")`
    // -- that `.closest()` fails here the same way app.js's own
    // `ms.querySelector('input[type="checkbox"], input[type="radio"]')`
    // did (same bugfix, same root cause): while the user is actively
    // typing in this row's panel, the panel -- this input included -- is
    // portaled to #multiselect-portal, outside its `.multiselect` wrapper
    // entirely, so no ancestor-based lookup from the input can reach the
    // wrapper any more. See _notebook_property_key_picker.html's own
    // comment on `ms_id` for the full reasoning.
    const msId = e.target.dataset.msTarget;
    const ms = msId ? document.getElementById(msId) : null;
    const summary = ms ? ms.querySelector(".ms-summary") : null;
    if (summary) summary.textContent = value;
    // Close the panel right away, same as app.js's own single-mode
    // Enter-commit does (its own follow-up fix, 2026-10-02: "doesn't look
    // like the first Enter did anything" without this) -- via the real
    // closure-private `closeOpenPanel`, exposed on `window.CCMultiselect`
    // specifically so this separate script doesn't have to fake the same
    // effect itself and risk leaving app.js's own `openPanel` bookkeeping
    // out of sync with what's actually on screen.
    if (window.CCMultiselect && window.CCMultiselect.close) window.CCMultiselect.close();
  });

  window.CCNotebookPropertyRows = { init };
  document.addEventListener("DOMContentLoaded", function () {
    init(document);
  });
})();
