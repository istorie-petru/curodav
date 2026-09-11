// holiday_edit_modal.html's Start/End date pickers (2026-09-11, direct
// request: "While adding a hollday... after setting either the start and
// end date, the other one should be automatically set the same. After the
// initial set both can be changed without any sync between them. This is
// only to make one day hollyday easier to add.").
//
// Each date is its own `.dtp[data-dtp-mode="date"]` instance
// (_datetime_picker.html), so picking one fires a plain `change` event on
// its own hidden input (datetime_picker.js's commitChange()) with no
// awareness of the other field. This script listens for that change and,
// only when the *other* field is still empty, fills it with the same date
// via the small `dtpSetDate` hook datetime_picker.js's enhance() exposes on
// each `.dtp` container -- that hook updates the other picker's own hidden
// input + visible trigger label the same way a real pick would, without
// dispatching another change event (so there's no risk of this listener
// re-triggering itself back and forth).
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
    if (!fromInput || !toInput) return;

    const fromContainer = fromInput.closest(".dtp");
    const toContainer = toInput.closest(".dtp");
    if (!fromContainer || !toContainer) return;

    fromInput.addEventListener("change", () => {
      if (fromInput.value && !toInput.value && toContainer.dtpSetDate) {
        toContainer.dtpSetDate(fromInput.value);
      }
    });
    toInput.addEventListener("change", () => {
      if (toInput.value && !fromInput.value && fromContainer.dtpSetDate) {
        fromContainer.dtpSetDate(toInput.value);
      }
    });
  }

  window.CCHolidayDateSync = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
