// Relations cards' add row (2026-08-09, _task_relations.html/
// _event_relations.html) -- one <select> serves both "link an existing
// object" and "create a new one": picking the "＋ New event…"/"＋ New
// task…" sentinel value (`__new__`) reveals the sibling title input; any
// other selection (or none) hides and clears it, so the add form can only
// ever POST a new_title when the user actually chose to create something
// new. Server-side (routers/tasks.py's add_task_relation, routers/
// calendar.py's add_event_relation) ignores new_title unless target_uid
// is exactly "__new__" anyway -- this is pure UX affordance, not a
// correctness check. Wired for both plain full pages and modal-injected
// content via modal.js's wireContent (see that file's CC* init pattern).*/
(function () {
  function init(root) {
    (root || document).querySelectorAll(".relations-add-form").forEach((form) => {
      if (form.dataset.ccWired) return;
      form.dataset.ccWired = "1";

      const select = form.querySelector(".relations-picker");
      const title = form.querySelector(".relations-new-title");
      if (!select || !title) return;

      function sync() {
        const isNew = select.value === "__new__";
        title.style.display = isNew ? "" : "none";
        title.disabled = !isNew;
        if (!isNew) title.value = "";
      }

      select.addEventListener("change", sync);
      sync(); // initial state (server renders it hidden/disabled)
    });
  }

  window.CCRelationPicker = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
