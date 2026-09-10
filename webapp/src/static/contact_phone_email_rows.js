// contact_form.html's Phone/Email/Website/Address/Social rows (Contacts
// field parity slices 2/3/5/6, plans/open.md). Purely client-side
// add/remove of {type, value...} rows -- nothing here talks to the server;
// the whole ordered list of rows posts together with the rest of the
// contact form on Save (routers/contacts.py's create_contact/update_contact
// read parallel phone_type[]/phone_value[] (email_type[]/email_value[],
// etc) form arrays). One delegated click listener per
// `[data-repeatable-rows-scope]` container handles both "Add" (clones a
// <template> row into the target list) and "Remove" (drops the clicked
// row's own .contact-multi-row) -- new rows need no separate wiring since
// the listener lives on the container, not the individual row/button.
//
// Same wireContent() re-init idiom as label_role_picker.js/
// task_habit_field_toggle.js: `init(root)` is safe to call again against
// content injected via modal.js's innerHTML swap (a `data-cc-wired` marker
// on the container prevents double-binding the listener on the *same* DOM
// node -- a fresh modal fetch always produces fresh container nodes, so
// this only actually matters if init() is ever called twice against the
// same still-live root, which doesn't happen today but costs nothing to
// guard against, same defensive habit every other *_wired script here
// already has).
//
// 2026-09-10 (audit-fixes-2.1.md, "Contacts edit modal window doesn't use
// the custom drop down menus"): each row's type field is now
// _contact_type_picker.html's macro instead of a plain <select> -- see that
// file's own header comment for the full "why a row-scoped radio name +
// hidden proxy input" rationale. Two things this script owns as a result:
//   1. `rewriteClonedTypePicker` -- a `<template>`'s baked-in placeholder
//      radio name/proxy id (row_key="tmpl") would collide if "Add" is
//      clicked more than once (two clones of the same template = two
//      identical ids/names), so every clone gets a freshly unique token
//      (a page-lifetime counter is enough -- these ids only need to be
//      unique within this one page load, never round-tripped anywhere).
//   2. The `.contact-type-radio` -> `.contact-type-proxy` sync listener --
//      the picker's own trigger-summary sync is already generic
//      (static/app.js's document-level `change` listener, same as every
//      other `.widget-list-multiselect`), but keeping the hidden proxy
//      input (the thing that actually submits under the real field name)
//      in sync with whichever radio is checked is specific to this
//      repeatable-row use case, so it lives here. Looked up by `id`
//      (`data-proxy-target`), not `.closest(".contact-multi-row")`,
//      because app.js's shared multiselect portal moves an OPEN
//      `.multiselect-panel` (the checked radio included) out to
//      `#multiselect-portal`, outside the row entirely, while the panel is
//      open -- ancestry-based lookup would fail at exactly the moment a
//      pick happens.
(function () {
  let cloneCounter = 0;

  function rewriteClonedTypePicker(root) {
    const proxy = root.querySelector(".contact-type-proxy");
    const radios = root.querySelectorAll(".contact-type-radio");
    if (!proxy || !radios.length) return; // not every repeatable row has one (none currently don't, but stay defensive)
    cloneCounter += 1;
    const base = proxy.getAttribute("name"); // e.g. "phone_type" -- the real submitted field name, never rewritten
    const token = "c" + cloneCounter;
    const proxyId = base + "-proxy-" + token;
    proxy.id = proxyId;
    radios.forEach(function (radio) {
      const fieldName = radio.dataset.proxyName || base;
      radio.name = fieldName + "__" + token;
      radio.dataset.proxyTarget = proxyId;
    });
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
          rewriteClonedTypePicker(clone);
          rows.appendChild(clone);
          const newInput = rows.lastElementChild ? rows.lastElementChild.querySelector("input") : null;
          if (newInput) newInput.focus();
        }
        return;
      }
      const removeBtn = e.target.closest("[data-repeatable-remove]");
      if (removeBtn) {
        e.preventDefault();
        const row = removeBtn.closest(".contact-multi-row");
        if (row) row.remove();
      }
    });
  }

  // Delegated at document level (same reasoning as static/app.js's own
  // multiselect handling) so it works for both server-rendered rows and
  // rows added later via the clone path above, and keeps working after a
  // radio's own panel gets portaled out to #multiselect-portal mid-pick.
  document.addEventListener("change", function (e) {
    if (!e.target.matches || !e.target.matches(".contact-type-radio")) return;
    const targetId = e.target.dataset.proxyTarget;
    const proxy = targetId ? document.getElementById(targetId) : null;
    if (proxy) proxy.value = e.target.value;
  });

  function init(root) {
    (root || document).querySelectorAll("[data-repeatable-rows-scope]").forEach(wireContainer);
  }

  window.CCContactPhoneEmailRows = { init };
  document.addEventListener("DOMContentLoaded", function () {
    init(document);
  });
})();
