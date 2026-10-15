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
    if (window.CCMultiselect && window.CCMultiselect.close) window.CCMultiselect.close();
  });

  window.CCNotebookPropertyRows = { init };
  document.addEventListener("DOMContentLoaded", function () {
    init(document);
  });
})();
