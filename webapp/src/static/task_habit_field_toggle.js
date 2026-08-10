// task_form.html's Daily target field (2026-08-08 direct feedback: "hide
// Daily target (habit tasks only) unless the label is habit or whatever
// default there is") -- only relevant once the configured habit label is
// actually applied to this task, so it stays hidden until the Labels
// field's matching checkbox is checked, live, with no page reload.
//
// Finds the habit-label checkbox by `[name="tags_labels"][value="<label>"]`
// scoped to `[form="<the task form's id>"]` -- NOT by DOM proximity to
// `#habit-target-field` (e.g. `.closest()`/`.querySelector()` from it).
// That's deliberate: the Labels field is a _widget_list_multiselect.html
// panel, and app.js's portal fix (2026-08-08) moves an *opened* panel's
// checkboxes out to #multiselect-portal, outside this field's DOM subtree
// entirely, for as long as it's open -- a proximity-based query would
// stop finding the checkbox at exactly the moment the user is looking
// right at it. The `form="..."` HTML attribute (set by
// _widget_list_multiselect.html's ms_form_id) is preserved regardless of
// where in the document the element currently sits, so both the lookup
// and the change listener (delegated on `document`, matching every other
// portal-safe listener added this same day -- see dashboard_widget_preview.js)
// stay correct no matter which panel is or isn't currently open.
(function () {
  function init(root) {
    (root || document).querySelectorAll(".habit-target-field[data-form-id]").forEach((field) => {
      if (field.dataset.ccWired) return;
      field.dataset.ccWired = "1";

      const habitLabel = field.dataset.habitLabel;
      const formId = field.dataset.formId;
      if (!habitLabel || !formId) return;

      function isChecked() {
        const selector =
          'input[name="tags_labels"][form="' + formId + '"]' +
          '[value="' + (window.CSS && CSS.escape ? CSS.escape(habitLabel) : habitLabel) + '"]';
        const input = document.querySelector(selector);
        return !!(input && input.checked);
      }

      function sync() {
        field.classList.toggle("is-hidden", !isChecked());
      }

      document.addEventListener("change", (e) => {
        if (e.target.name === "tags_labels" && e.target.form && e.target.form.id === formId) sync();
      });

      sync(); // initial state, in case the server-rendered class is ever stale (e.g. a habit_label rename mid-session)
    });
  }

  window.CCHabitFieldToggle = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
