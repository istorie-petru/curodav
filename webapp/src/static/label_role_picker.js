(function () {
  document.addEventListener("change", (e) => {
    const el = e.target;
    if (!el || el.name !== "page_type" || !el.form) return;
    const grid = el.form.querySelector(".label-form-grid");
    if (grid) grid.dataset.page = el.value;
  });

  // Tags rows of the label form: Add clones the template, Remove hides a saved row (the server deletes it) or drops a new one.
  document.addEventListener("click", (e) => {
    const add = e.target.closest && e.target.closest("[data-tag-add]");
    const del = e.target.closest && e.target.closest("[data-tag-remove]");
    if (add) {
      const field = add.closest(".label-tags-field");
      const list = field.querySelector(".label-tags-list");
      const i = parseInt(list.dataset.next, 10);
      list.dataset.next = String(i + 1);
      list.insertAdjacentHTML("beforeend", field.querySelector(".label-tag-template").innerHTML.replaceAll("__i__", String(i)));
      const input = list.lastElementChild.querySelector('input[type="text"]');
      if (input) input.focus();
    } else if (del) {
      const row = del.closest(".label-tag-row");
      const old = row.querySelector('input[name^="tag_old_"]');
      if (old && old.value) {
        row.querySelector('input[name^="tag_del_"]').value = "1";
        row.hidden = true;
      } else {
        row.remove();
      }
    }
  });

  // Kept for modal.js's wireContent() call; nothing to wire per render.
  window.CCLabelRolePicker = { init() {} };
})();
