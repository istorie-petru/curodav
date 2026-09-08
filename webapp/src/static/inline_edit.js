// Notion-style click-to-edit table cells -- generic, not tied to any one
// page or field. 2026-08-28 direct feedback on the Habits group's check-in
// counter: "how in notion we see a table with just text... once you click
// two times on an element it becomes editable in a non-discrete way."
//
// Contract: any element carrying `data-inline-edit` renders as plain text
// (no visible input chrome) until double-clicked (or Enter/Space while
// focused, for keyboard users who can't double-click). At that point its
// text content is swapped for a real `<input>` in place, focused and
// pre-selected -- `type="number"` by default, or `type="text"` when
// `data-type="text"` is set (2026-08-29, STATE.md backlog item 9, the
// Tasks table's Title column). Enter or blur commits: a number is clamped
// to `data-min`/`data-max` (mirrors whatever the server clamps to --
// advisory only, see the field's own server-side clamp for the real
// bound); text is just trimmed, and an empty result reverts instead of
// saving (a blank title/value is never a valid commit). The committed
// value is written back into the cell's own text, then persisted one of
// two ways depending on what's around the cell:
//   - inside a `<form>` with a matching hidden `name="<data-field or
//     'value'>"` input (the Habits check-in count's own contract): the
//     hidden input is updated and the form is submitted via
//     `requestSubmit()`, which async_crud.js's existing global
//     `[data-cc-change]` submit listener picks up like any other form.
//   - no such form (e.g. the Tasks table's Title cell, which lives in a
//     plain `<td>` next to unrelated per-row forms, not inside one built
//     for this): a `cc-inline-edit-commit` CustomEvent is dispatched on
//     the cell instead (bubbles, `detail: {field, value}`), leaving
//     *this* file with no opinion on how the value actually gets saved --
//     the page that owns the table (tasks_table.js) listens for it and
//     posts through whatever endpoint makes sense there (its existing
//     fetch-based update-field call, the same one status/due_at use).
// Escape cancels and restores whatever text was there before, no commit.
//
// Delegated at the document level (dblclick/keydown), not bound per-cell
// at load, so it keeps working after a region swap (async_crud.js's
// refreshRegion) replaces the table's rows with fresh markup -- same
// delegation convention as tasks_table.js's own inline-editing listeners.
//
// `data-inline-edit-linked` (2026-08-29, same backlog item): an editable
// cell that is ALSO a `data-modal` link (the Title cell -- single click
// opens the task, double-click renames it) needs the two told apart on
// the exact same element. The trouble: a double-click fires `click`,
// `click`, then `dblclick` as three separate events, and modal.js's own
// `click` listener (document, bubble phase) would act on the very FIRST
// of those `click`s and open the modal before the second click -- let
// alone `dblclick` -- ever happens; there's no "undo" once that fetch has
// started. The fix mirrors how calendar.js already tells a real click
// apart from the tail end of a drag on the same `[data-modal]` element
// (see modal.js's own comment): intercept in the CAPTURE phase (which,
// unlike bubble-phase listeners, is guaranteed to run before modal.js's
// regardless of script load order), call `preventDefault()` so modal.js's
// `if (e.defaultPrevented) return` guard skips it, and open the modal
// *ourselves* after a short delay -- long enough for a second click to
// arrive and cancel it, in which case the `dblclick` handler below takes
// over instead.
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
