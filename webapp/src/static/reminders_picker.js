(function () {
  const enhanced = new WeakSet();

  const PRESETS = [
    { minutes: 0, label: "At start time" },
    { minutes: 5, label: "5 minutes before" },
    { minutes: 10, label: "10 minutes before" },
    { minutes: 30, label: "30 minutes before" },
    { minutes: 60, label: "1 hour before" },
    { minutes: 1440, label: "1 day before" },
  ];
  const PRESET_MINUTES = new Set(PRESETS.map((p) => p.minutes));

  function parseMinutes(raw) {
    return (raw || "")
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s !== "" && /^-?\d+$/.test(s))
      .map((s) => parseInt(s, 10));
  }

  function enhance(input) {
    if (enhanced.has(input)) return;
    enhanced.add(input);

    const values = parseMinutes(input.value);
    const presetSelected = new Set(values.filter((v) => PRESET_MINUTES.has(v)));
    const customValues = values.filter((v) => !PRESET_MINUTES.has(v));

    const wrap = document.createElement("div");
    wrap.className = "multiselect widget-list-multiselect reminders-picker";
    wrap.setAttribute("data-ms", "");
    wrap.setAttribute("data-ms-mode", "select");
    wrap.setAttribute("data-ms-label", "reminders");
    input.parentNode.insertBefore(wrap, input);

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "multiselect-trigger ms-trigger";
    trigger.setAttribute("aria-haspopup", "true");
    trigger.setAttribute("aria-expanded", "false");
    trigger.innerHTML =
      '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-bell"></use></svg>' +
      '<span class="ms-summary"></span>' +
      '<span class="filter-caret"><svg class="icon icon-sm" aria-hidden="true"><use href="#icon-chevron-down"></use></svg></span>';
    wrap.appendChild(trigger);
    const summary = trigger.querySelector(".ms-summary");

    const panel = document.createElement("div");
    panel.className = "multiselect-panel ms-panel";
    wrap.appendChild(panel);

    const checkboxes = [];
    PRESETS.forEach((p) => {
      const label = document.createElement("label");
      label.className = "multiselect-option";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = String(p.minutes);
      cb.checked = presetSelected.has(p.minutes);
      label.appendChild(cb);
      const span = document.createElement("span");
      span.textContent = p.label;
      label.appendChild(span);
      panel.appendChild(label);
      checkboxes.push(cb);
    });

    // "Other minutes" escape hatch -- same idea as _widget_list_multiselect
    // .html's "+ New label" row: one extra row at the bottom of the same
    // panel rather than a separate control below it.
    const customRow = document.createElement("label");
    customRow.className = "multiselect-option multiselect-new-option";
    const customInput = document.createElement("input");
    customInput.type = "text";
    customInput.className = "multiselect-new-input reminders-custom-input";
    customInput.setAttribute("aria-label", "Other minutes before, comma-separated");
    customInput.value = customValues.join(", ");
    customRow.appendChild(customInput);
    panel.appendChild(customRow);

    input.setAttribute("autocomplete", "off");
    input.style.display = "none";
    wrap.appendChild(input);

    function updateSummary() {
      const checked = checkboxes.filter((cb) => cb.checked).length;
      summary.textContent = checked === 0 ? "No reminders" : checked + " selected";
    }

    function sync() {
      const chosen = checkboxes.filter((cb) => cb.checked).map((cb) => cb.value);
      const custom = customInput.value
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s !== "" && /^-?\d+$/.test(s));
      input.value = chosen.concat(custom).join(", ");
      updateSummary();
    }
    sync();

    checkboxes.forEach((cb) => cb.addEventListener("change", sync));
    customInput.addEventListener("input", sync);
  }

  function scan(root) {
    (root.querySelectorAll ? root.querySelectorAll("input.reminders-input") : []).forEach(enhance);
    if (root.matches && root.matches("input.reminders-input")) enhance(root);
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
