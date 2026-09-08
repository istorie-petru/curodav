// label_form_modal.html's Role control (side work, 2026-08-15 direct
// feedback: "becoming a project should be mutually exclusive to a space --
// selected via a fancy dropdown menu. Spaces or project settings appear
// only after being selected"), reworked 2026-09-09 (direct request, twice):
// first into a plain native <select>, then into the same radio-backed
// custom dropdown _widget_list_multiselect.html/static/app.js already
// render/wire everywhere else (.multiselect/.multiselect-trigger/
// .multiselect-panel) -- app.js's own global handlers already own that
// control's open/close, portal-out-of-the-modal, and trigger-summary-text
// jobs, so this file's two jobs stay exactly the same as before, just
// reading the checked radio's value instead of a <select>'s:
//
//  1. Show the Project start/end date fields only while "Project" is the
//     selected option -- `hidden` toggled on `.label-project-fields`, no
//     server round trip, same "reveal on selection" idiom
//     task_habit_field_toggle.js already established for this app's forms.
//
//  2. Warn before actually losing something. `data-warn-role` (set by
//     routers/labels.py::edit_label_modal) is the ORIGINAL role only if
//     that role has real data worth confirming before dropping -- an
//     existing Project always (its dates/lifecycle), a Space only if it
//     has child labels grouped under it (routers/labels.py's has_children)
//     -- otherwise it's empty. Whenever the live selection differs from
//     data-original-role AND data-original-role matches data-warn-role,
//     this sets `data-confirm-sheet` on the whole edit form so app.js's/
//     modal.js's existing confirm-sheet handling (see modal.js's own
//     comment on why a modal form must check this itself) intercepts
//     Save with a warning. Selecting back to the original role removes
//     the attribute again -- Save should only ever ask about a change
//     that's actually about to happen, never about unrelated field edits
//     (color, icon, ...) on a form that also happens to contain this
//     control.
//
// Radios are captured into a plain array at init, not re-queried from
// `wrap` on every sync -- static/app.js's multiselect handling portals the
// open `.multiselect-panel` (and every radio inside it) out to
// #multiselect-portal while open, so `wrap.querySelector(...)` would find
// nothing at that point even though the wrapping `.field` itself (`wrap`,
// what this script actually walks up from) never moves. Element
// references captured up front stay valid wherever the node currently
// lives in the DOM.
(function () {
  function init(root) {
    (root || document).querySelectorAll(".label-role-picker[data-original-role]").forEach((wrap) => {
      if (wrap.dataset.ccWired) return;
      wrap.dataset.ccWired = "1";

      const originalRole = wrap.dataset.originalRole || "none";
      const warnRole = wrap.dataset.warnRole || "";
      const radios = Array.from(wrap.querySelectorAll('input[name="role"]'));
      const form = wrap.closest("form");
      const fields = form ? form.querySelector(".label-project-fields") : null;

      const MESSAGES = {
        project:
          "Switching away from Project removes its start/end period and lifecycle tracking. The label and everything tagged with it stay exactly as they are.",
        space:
          "This label generates a Space page other labels are grouped under. Switching away removes that page; the child labels and their own data are untouched.",
      };

      function selectedRole() {
        const checked = radios.find((r) => r.checked);
        return checked ? checked.value : originalRole;
      }

      function sync() {
        const value = selectedRole();
        if (fields) fields.hidden = value !== "project";
        if (!form) return;
        if (value !== originalRole && warnRole && warnRole === originalRole) {
          form.setAttribute("data-confirm-sheet", MESSAGES[warnRole]);
        } else {
          form.removeAttribute("data-confirm-sheet");
        }
      }

      radios.forEach((radio) => radio.addEventListener("change", sync));
      sync(); // initial state -- date fields' hidden attribute is already
              // server-rendered to match, this just covers a stale/cached
              // fragment and keeps the two code paths honest with each other.
    });
  }

  window.CCLabelRolePicker = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
