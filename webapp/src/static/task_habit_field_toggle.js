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
