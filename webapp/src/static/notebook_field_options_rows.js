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
