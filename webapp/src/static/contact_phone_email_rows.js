// contact_form.html's Phone/Email rows (Contacts field parity slice 2 of 6,
// plans/open.md). Purely client-side add/remove of {type, value} rows --
// nothing here talks to the server; the whole ordered list of rows posts
// together with the rest of the contact form on Save (routers/contacts.py's
// create_contact/update_contact read parallel phone_type[]/phone_value[]
// (email_type[]/email_value[]) form arrays). One delegated click listener
// per `[data-repeatable-rows-scope]` container handles both "Add" (clones a
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
(function () {
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

  function init(root) {
    (root || document).querySelectorAll("[data-repeatable-rows-scope]").forEach(wireContainer);
  }

  window.CCContactPhoneEmailRows = { init };
  document.addEventListener("DOMContentLoaded", function () {
    init(document);
  });
})();
