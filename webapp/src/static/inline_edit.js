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
    const isText = cell.dataset.type === "text";

    const input = document.createElement("input");
    input.type = isText ? "text" : "number";
    // `--text` modifier (style.css) widens/left-aligns the input instead
    // of the number variant's narrow, centered fixed width -- a title
    // needs room to actually type in, not just show a couple of digits.
    input.className = "inline-edit-input" + (isText ? " inline-edit-input--text" : "");
    if (!isText) {
      if (cell.dataset.min !== undefined) input.min = cell.dataset.min;
      if (cell.dataset.max !== undefined) input.max = cell.dataset.max;
      input.step = "1";
      input.inputMode = "numeric";
    }
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
        const value = isText ? input.value.trim() : clamp(cell, input.value);
        if (isText && !value) {
          // A blank title is never a valid commit -- revert instead,
          // same "don't silently write nothing" rule the number side
          // gets for free from clamp()'s own min bound.
          cell.textContent = originalText;
          delete cell.dataset.editing;
          return;
        }
        cell.textContent = String(value);
        const form = cell.closest("form");
        const hidden = form && form.querySelector('input[type="hidden"][name="' + (cell.dataset.field || "value") + '"]');
        if (hidden) {
          if (hidden.value !== String(value)) {
            hidden.value = String(value);
            form.requestSubmit();
          }
        } else {
          cell.dispatchEvent(
            new CustomEvent("cc-inline-edit-commit", {
              bubbles: true,
              detail: { field: cell.dataset.field || "value", value },
            })
          );
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
  // its tabindex) -- double-click has no keyboard analog otherwise. Not
  // for a `data-inline-edit-linked` cell (the Title link): Enter's native
  // role there is "activate the link" (open the modal), same as any other
  // link -- overriding it to enter edit mode instead would be surprising
  // for a keyboard user and has no equivalent "double-Enter" gesture to
  // fall back to for opening it. That link's own synthetic click (below)
  // still opens the modal on Enter, just via the same short delay a real
  // click gets.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const cell = e.target.closest && e.target.closest("[data-inline-edit]");
    if (!cell || cell.dataset.editing || e.target !== cell) return;
    if (cell.hasAttribute("data-inline-edit-linked")) return;
    e.preventDefault();
    enterEditMode(cell);
  });

  // ------------------------------------------------------------------ //
  // data-inline-edit-linked: click vs. double-click disambiguation for a
  // cell that is both a data-modal link and inline-editable (see header
  // comment above).
  // ------------------------------------------------------------------ //
  const OPEN_DELAY_MS = 280;
  const pendingOpen = new WeakMap(); // element -> setTimeout id

  document.addEventListener(
    "click",
    (e) => {
      const link = e.target.closest && e.target.closest("[data-inline-edit-linked]");
      if (!link) return;
      // Always block the link's own default navigation -- opening (if it
      // turns out to be a single click, not the first half of a
      // double-click) happens explicitly below instead, and while
      // actively editing this just needs to let the click land in the
      // input for cursor placement without also navigating.
      e.preventDefault();
      if (link.dataset.editing) return;
      if (pendingOpen.has(link)) {
        // Second click of a double-click: cancel the deferred open, the
        // dblclick handler above (already registered on the same
        // `[data-inline-edit]` element) takes it from here.
        clearTimeout(pendingOpen.get(link));
        pendingOpen.delete(link);
        return;
      }
      const timeoutId = setTimeout(() => {
        pendingOpen.delete(link);
        if (window.CCModal) {
          window.CCModal.open(link.getAttribute("data-modal") || link.getAttribute("href"), link);
        }
      }, OPEN_DELAY_MS);
      pendingOpen.set(link, timeoutId);
    },
    true // capture -- see header comment for why this must run before modal.js's own bubble-phase click listener
  );
})();
