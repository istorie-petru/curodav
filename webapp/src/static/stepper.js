// Progressive enhancement for `.stepper` (a `<input type="number">` flanked
// by a `.stepper-dec`/`.stepper-inc` button pair -- see the widget
// builder's Limit field, _widget_builder_fields.html/_widget_edit_form.html,
// 2026-08-07 modal-input-design Phase A) into a click-to-adjust control.
//
// The `<input type="number">` stays the real, only submitted field --
// clicking a button just nudges its `.value` by the input's own `step`
// (default 1), clamped to `min`/`max` when present, then fires input/
// change so anything listening to the field (dashboard_widget_preview.js's
// live preview, an autosave form) reacts the same as if the number had
// been typed or adjusted via the input's own native spinner. With no JS
// at all, the buttons just don't do anything -- the plain number input
// underneath (and its native browser spinner, only hidden here via CSS)
// is still a completely working way to set the value.
//
// Same "scan on DOMContentLoaded + MutationObserver for modal-injected
// content" convention as tag_input.js/recurrence_picker.js (see either of
// their own comments for why a MutationObserver is needed at all: modal.js
// injects fetched fragments via `body.innerHTML = ...`, which never
// executes a `<script>` tag inside that HTML).
(function () {
  const enhanced = new WeakSet();

  function step(input, direction) {
    const min = input.min !== "" ? parseFloat(input.min) : -Infinity;
    const max = input.max !== "" ? parseFloat(input.max) : Infinity;
    const amount = input.step && input.step !== "any" ? parseFloat(input.step) : 1;
    let value = parseFloat(input.value);
    if (Number.isNaN(value)) value = direction > 0 ? Math.max(min, 0) : (min !== -Infinity ? min : 0);
    value += direction * amount;
    if (value < min) value = min;
    if (value > max) value = max;
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function enhance(stepperEl) {
    if (enhanced.has(stepperEl)) return;
    enhanced.add(stepperEl);
    const input = stepperEl.querySelector('input[type="number"]');
    const dec = stepperEl.querySelector(".stepper-dec");
    const inc = stepperEl.querySelector(".stepper-inc");
    if (!input || !dec || !inc) return;
    dec.addEventListener("click", () => step(input, -1));
    inc.addEventListener("click", () => step(input, 1));
  }

  function scan(root) {
    if (root.querySelectorAll) root.querySelectorAll(".stepper").forEach(enhance);
    if (root.matches && root.matches(".stepper")) enhance(root);
  }

  document.addEventListener("DOMContentLoaded", () => scan(document));

  new MutationObserver((mutations) => {
    for (const m of mutations) {
      m.addedNodes.forEach((node) => {
        if (node.nodeType === 1) scan(node);
      });
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
