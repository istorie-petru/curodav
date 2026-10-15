(function () {
  document.addEventListener("change", (e) => {
    const el = e.target;
    if (!el || el.name !== "page_type" || !el.form) return;
    const grid = el.form.querySelector(".label-form-grid");
    if (grid) grid.dataset.page = el.value;
  });

  // Kept for modal.js's wireContent() call; nothing to wire per render.
  window.CCLabelRolePicker = { init() {} };
})();
