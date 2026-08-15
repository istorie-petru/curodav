// _event_form_fields.html's Format field (2026-08-15, "Event format for
// simple events") -- picking In person/Online reveals only that field via
// plain CSS (#event-form:has(#event_format_in_person:checked), style.css),
// no JS needed for visibility. This script only clears the *other* field's
// value on switch, so a hidden stale value (e.g. a Meeting URL typed in
// before switching to In person) can't silently resubmit and leave both
// columns populated -- Format is derived from which field is non-empty
// (_event_form_fields.html's own comment), so two non-empty fields would
// make that derivation ambiguous the next time the form loads.
//
// Location/Meeting URL are direct descendants of the same <form> as the
// Format radios (not portalled out like _widget_list_multiselect.html's
// panels), so a plain form.querySelector() is enough -- no need for the
// form="..." attribute lookup task_habit_field_toggle.js needs for its
// portal-safe case.
(function () {
  function init(root) {
    (root || document).querySelectorAll(".event-format-segmented").forEach((segmented) => {
      if (segmented.dataset.ccWired) return;
      segmented.dataset.ccWired = "1";

      const form = segmented.closest("form");
      if (!form) return;

      segmented.querySelectorAll('input[type="radio"]').forEach((radio) => {
        radio.addEventListener("change", () => {
          if (!radio.checked) return;
          const otherName = radio.value === "in_person" ? "meeting_url" : "location";
          const otherInput = form.querySelector('[name="' + otherName + '"]');
          if (otherInput) otherInput.value = "";
        });
      });
    });
  }

  window.CCEventFormatToggle = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
