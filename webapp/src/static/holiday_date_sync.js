(function () {
  function init(root) {
    const form = (root || document).querySelector("#holiday-form");
    if (!form) return;
    if (form.dataset.ccHolidayDateSyncWired) return;
    form.dataset.ccHolidayDateSyncWired = "1";

    const fromInput = form.querySelector('input[name="date_from"]');
    const toInput = form.querySelector('input[name="date_to"]');
    if (!fromInput || !toInput || !window.CCDateField) return;

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
