// Notion-style click-to-edit table cells -- generic, not tied to any one
// page or field. 2026-08-28 direct feedback on the Habits group's check-in
// counter: "how in notion we see a table with just text... once you click
// two times on an element it becomes editable in a non-discrete way."
//
// Contract: any element carrying `data-inline-edit` renders as plain text
// (no visible input chrome) until double-clicked (or Enter/Space while
// focused, for keyboard users who can't double-click). At that point its
// text content is swapped for a real `<input type="number">` in place,
// focused and pre-selected. Enter or blur commits: the number is clamped
// to `data-min`/`data-max` (mirrors whatever the server clamps to --
// advisory only, see the field's own server-side clamp for the real
// bound), written back into the cell's own text, copied into the nearest
// `<form>`'s hidden `value` input, and the form is submitted via
// `requestSubmit()` -- which async_crud.js's existing global
// `[data-cc-change]` submit listener picks up exactly like any other
// form on the page, so this file adds no new network path of its own.
// Escape cancels and restores whatever text was there before, no submit.
//
// Delegated at the document level (dblclick/keydown), not bound per-cell
// at load, so it keeps working after a region swap (async_crud.js's
// refreshRegion) replaces the table's rows with fresh markup -- same
// delegation convention as tasks_table.js's own inline-editing listeners.

(function () {
  function clamp(cell, rawValue) {
    let value = parseInt(rawValue, 10);
    if (Number.isNaN(value)) value = 0;
    if (cell.dataset.min !== undefined) value = Math.max(Number(cell.dataset.min), value);
    if (cell.dataset.max !== undefined) value = Math.min(Number(cell.dataset.max), value);
    return value;
  }

  function enterEditMode(cell) {
    if (cell.dataset.editing) return;
    cell.dataset.editing = "1";
    const originalText = cell.textContent;

    const input = document.createElement("input");
    input.type = "number";
    input.className = "inline-edit-input";
    if (cell.dataset.min !== undefined) input.min = cell.dataset.min;
    if (cell.dataset.max !== undefined) input.max = cell.dataset.max;
    input.step = "1";
    input.inputMode = "numeric";
    input.value = originalText.trim();

    cell.textContent = "";
    cell.appendChild(input);
    input.focus();
    input.select();

    let settled = false;
    function finish(shouldSave) {
      if (settled) return;
      settled = true;
      if (shouldSave) {
        const value = clamp(cell, input.value);
        cell.textContent = String(value);
        const form = cell.closest("form");
        const hidden = form && form.querySelector('input[type="hidden"][name="' + (cell.dataset.field || "value") + '"]');
        if (hidden && hidden.value !== String(value)) {
          hidden.value = String(value);
          form.requestSubmit();
        }
      } else {
        cell.textContent = originalText;
      }
      delete cell.dataset.editing;
    }

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        finish(true);
      } else if (e.key === "Escape") {
        e.preventDefault();
        finish(false);
      }
    });
    // Commit on blur too (clicking away, tabbing off) -- Notion does the
    // same: there's no separate "cancel" affordance besides Escape, losing
    // focus any other way saves.
    input.addEventListener("blur", () => finish(true));
    // The double-click that opened this input shouldn't also register as
    // a click on whatever's underneath once the input exists.
    input.addEventListener("click", (e) => e.stopPropagation());
  }

  document.addEventListener("dblclick", (e) => {
    const cell = e.target.closest && e.target.closest("[data-inline-edit]");
    if (!cell || cell.dataset.editing) return;
    e.preventDefault();
    enterEditMode(cell);
  });

  // Keyboard equivalent (Enter/Space while the cell itself is focused via
  // its tabindex) -- double-click has no keyboard analog otherwise.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const cell = e.target.closest && e.target.closest("[data-inline-edit]");
    if (!cell || cell.dataset.editing || e.target !== cell) return;
    e.preventDefault();
    enterEditMode(cell);
  });
})();
