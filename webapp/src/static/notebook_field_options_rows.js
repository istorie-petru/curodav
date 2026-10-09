// Settings > Notebook field edit modal (2026-10-02,
// templates/notebook_field_edit_modal.html /
// templates/_notebook_field_option_row.html):
//
// 1. Type -> Options visibility. Same `data-page`/label_role_picker.js
//    idiom the label form's Page/Sections switch already uses -- a
//    change listener on the Type field's radios (ms_mode="single", see
//    _widget_list_multiselect.html) sets `data-field-type` on the
//    enclosing `.notebook-field-form-grid`, driving style.css's
//    `[data-field-type]` show/hide of `.notebook-field-options-field`.
//
// 2. Option rows' color/icon proxy sync. Each row's Look picker
//    (_look_picker.html, reused unchanged) uses row-scoped radio names
//    (`option_color_radio__{row_key}` / `option_icon_radio__{row_key}`)
//    instead of the shared `option_color`/`option_icon` the form actually
//    needs to submit -- same "many independent pickers, one shared
//    submitted name" problem notebook_properties_rows.js already solved
//    for the property-key picker, generalized to two proxies. Unlike that
//    file's radio->proxy sync, this derives the proxy id from the radio's
//    OWN name (row_key is the suffix after the `__`) instead of a
//    `data-proxy-target` attribute -- avoids touching the shared
//    look_picker macro's markup at all.
//
// 3. Add/remove rows, same `data-repeatable-add`/`data-repeatable-remove`/
//    `<template>` idiom as notebook_properties_rows.js, but this file's
//    own clone rewriting: a cloned row carries THREE separate ids that all
//    share the same baked-in "tmpl" placeholder (the look_picker trigger's
//    id, its "-label" id, and the two hidden proxies' ids) plus two radio
//    group names -- simplest correct fix is one textual
//    s/tmpl/{token}/g over the template's serialized HTML before it's
//    parsed back into real DOM nodes, rather than visiting each attribute
//    individually. Safe here specifically because "tmpl" is this file's
//    own naming convention, never real user-facing text (a value/color/
//    icon the user actually picks can't contain it as a standalone token
//    in these particular attributes).
(function () {
  let cloneCounter = 0;

  function wireContainer(container) {
    if (container.dataset.ccWired) return;
    container.dataset.ccWired = "1";

    container.addEventListener("click", function (e) {
      const addBtn = e.target.closest("[data-repeatable-add]");
      if (addBtn) {
        e.preventDefault();
        const rows = document.getElementById(addBtn.getAttribute("data-repeatable-add"));
        const tmpl = document.getElementById(addBtn.getAttribute("data-repeatable-template"));
        if (rows && tmpl) {
          cloneCounter += 1;
          const token = "c" + cloneCounter;
          const wrapper = document.createElement("div");
          wrapper.innerHTML = tmpl.innerHTML.replace(/tmpl/g, token);
          const row = wrapper.firstElementChild;
          if (row) {
            rows.appendChild(row);
            const valueInput = row.querySelector('input[name="option_value"]');
            if (valueInput) valueInput.focus();
          }
        }
        return;
      }
      const removeBtn = e.target.closest("[data-repeatable-remove]");
      if (removeBtn) {
        e.preventDefault();
        const row = removeBtn.closest(".notebook-field-option-row");
        if (row) row.remove();
      }
    });
  }

  function init(root) {
    (root || document).querySelectorAll(".notebook-field-options-field").forEach(wireContainer);
  }

  // Type radio -> grid dataset, delegated on the document (not a listener
  // on the <form> itself): same reason label_role_picker.js's Page switch
  // is document-delegated -- the Type field's panel (ms_mode="single",
  // _widget_list_multiselect.html) is portaled to #multiselect-portal
  // while open (static/app.js), so its radios carry `form="notebook-field-
  // form"` for submission purposes but are NOT DOM descendants of that
  // `<form>` at the moment they're picked -- a `change` listener attached
  // to the form element itself would never see the event, since DOM event
  // bubbling follows the actual tree, not the `form` attribute's logical
  // association.
  document.addEventListener("change", function (e) {
    if (!e.target.matches || !e.target.matches('input[name="type"]')) return;
    if (!e.target.form) return;
    const grid = e.target.form.querySelector(".notebook-field-form-grid");
    if (grid) grid.dataset.fieldType = e.target.value;
  });

  // Row-scoped radio -> shared proxy sync, delegated on the document (same
  // reasoning as notebook_properties_rows.js's own delegated listener --
  // the Look picker's panel is portaled out to #multiselect-portal while
  // open, so a plain ancestor lookup from the radio can't find anything
  // useful anyway; going straight from the radio's own name is simplest).
  document.addEventListener("change", function (e) {
    const name = e.target.name;
    if (!name) return;
    let proxyId = null;
    if (name.indexOf("option_color_radio__") === 0) {
      proxyId = "field-option-color-proxy-" + name.slice("option_color_radio__".length);
    } else if (name.indexOf("option_icon_radio__") === 0) {
      proxyId = "field-option-icon-proxy-" + name.slice("option_icon_radio__".length);
    }
    if (!proxyId) return;
    const proxy = document.getElementById(proxyId);
    if (proxy) proxy.value = e.target.value;
  });

  window.CCNotebookFieldOptionRows = { init };
  document.addEventListener("DOMContentLoaded", function () {
    init(document);
  });
})();
