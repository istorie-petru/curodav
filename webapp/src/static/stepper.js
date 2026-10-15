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
