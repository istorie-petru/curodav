// The label form's Page / Sections switch (templates/_label_form_fields.html).
//
// 2026-09-26 (Peter): the Role picker this file was named after is gone
// (labels and projects are separate; a label becomes a project only via
// the edit modal's Convert action), and the page modules are dropdowns.
// Page = Sections shows the Sections checkbox dropdown half width next
// to it; Page = Widget dashboard hides it (style.css
// .label-form-grid[data-page]). The Page radios are portaled out of the
// form while their panel is open (static/app.js), so the form is found
// through each radio's form="" attribute. Delegated on the document: the
// form arrives inside a modal after this script loaded.
(function () {
  document.addEventListener("change", (e) => {
    const el = e.target;
    if (!el || el.name !== "has_dashboard" || !el.form) return;
    const grid = el.form.querySelector(".label-form-grid");
    if (grid) grid.dataset.page = el.value === "1" ? "dashboard" : "sections";
  });

  // Kept for modal.js's wireContent() call; nothing to wire per render.
  window.CCLabelRolePicker = { init() {} };
})();
