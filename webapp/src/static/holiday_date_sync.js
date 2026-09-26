// holiday_edit_modal.html's Start/End date pickers (2026-09-11, direct
// request: "While adding a hollday... after setting either the start and
// end date, the other one should be automatically set the same. After the
// initial set both can be changed without any sync between them. This is
// only to make one day hollyday easier to add.").
//
// Each date is its own date field (_date_time_fields.html, 2026-09-26),
// so a pick or typed date fires a plain `change` on its own hidden input
// with no awareness of the other field. This script listens for that
// change and, only when the *other* field is still empty, fills it with
// the same date through window.CCDateField.set (date_time_fields.js). The
// second change that fires can't loop: by then both fields have a value.
//
// "the other one should be automatically set the same... after the
// initial set both can be changed without any sync" -- both fields being
// non-empty (the "initial set" already happened, one way or another) is
// exactly the condition that turns this into a no-op, so no dirty-tracking
// or one-shot flag is needed: the emptiness check itself is the guard.
(function () {
  function init(root) {
    const form = (root || document).querySelector("#holiday-form");
    if (!form) return;
    if (form.dataset.ccHolidayDateSyncWired) return;
    form.dataset.ccHolidayDateSyncWired = "1";

    const fromInput = form.querySelector('input[name="date_from"]');
    const toInput = form.querySelector('input[name="date_to"]');
    if (!fromInput || !toInput || !window.CCDateField) return;

    // 2026-09-26: the fields are _date_time_fields.html date fields now;
    // CCDateField.set updates the other one's box and hidden value.
    fromInput.addEventListener("change", () => {
      if (fromInput.value && !toInput.value) window.CCDateField.set(toInput, fromInput.value);
    });
    toInput.addEventListener("change", () => {
      if (toInput.value && !fromInput.value) window.CCDateField.set(fromInput, toInput.value);
    });
  }

  window.CCHolidayDateSync = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
