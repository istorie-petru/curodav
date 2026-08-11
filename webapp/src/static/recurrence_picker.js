// Progressive enhancement for `<input class="recurrence-input" name="recurrence">`
// (task_form.html/event_form.html/habit_task_form.html's Recurrence field)
// into a preset picker ("Does not repeat"/"Daily"/"Weekly"/"Monthly"/
// "Yearly"/a custom RRULE) instead of asking the user to type raw RRULE
// syntax directly -- direct feedback: "the modal window should prioritize
// drop down menus and other input methods, not just text input."
//
// 2026-08-08 follow-up ("integrate the dropdown menu with the text input
// one") -- the custom-RRULE escape hatch used to be a second element
// entirely: a raw text input that appeared/disappeared *below* the
// dropdown depending on which radio was checked. Reworked into the same
// "one extra row at the bottom of the same panel" shape
// reminders_picker.js's own "Other minutes" row already uses (which
// itself follows _widget_list_multiselect.html's "+ New label" row) --
// there is only ever one visible control now (the dropdown), with the
// custom-value text field living *inside* its panel as the last option
// instead of a second, separately-positioned element. Typing into that
// field is itself what selects "Custom" -- no separate radio click
// needed first, same "typing is the action" affordance the "+ New label"
// row already has.
//
// The underlying real `<input name="recurrence">` is permanently hidden
// (not conditionally shown/hidden the way it used to be) and keeps its
// name/value contract exactly as-is -- neither routers/tasks.py's
// create_task/update_task nor routers/calendar.py's create_event/
// update_event do any server-side parsing of it beyond passing it
// straight through, so this is entirely a client-side swap.
//
// Same "scan on DOMContentLoaded + MutationObserver for modal-injected
// content" convention as tag_input.js (read that file's own comment for
// why a MutationObserver is needed at all: modal.js injects fetched
// fragments via `body.innerHTML = ...`, which never executes a `<script>`
// tag inside that HTML). Still works with no JS at all -- it's just a
// plain (hidden-only-by-CSS-that-never-loaded) text input in that case.
(function () {
  const enhanced = new WeakSet();
  let uid = 0;

  const PRESETS = [
    { value: "", label: "Does not repeat" },
    { value: "FREQ=DAILY", label: "Daily" },
    { value: "FREQ=WEEKLY", label: "Weekly" },
    { value: "FREQ=MONTHLY", label: "Monthly" },
    { value: "FREQ=YEARLY", label: "Yearly" },
  ];

  function enhance(input) {
    if (enhanced.has(input)) return;
    enhanced.add(input);
    uid += 1;
    const radioName = "recurrence-preset-" + uid; // group only, never submitted

    const currentValue = input.value || "";
    const matched = PRESETS.find((p) => p.value === currentValue);

    const wrap = document.createElement("div");
    wrap.className = "multiselect widget-list-multiselect recurrence-preset-select";
    wrap.setAttribute("data-ms", "");
    wrap.setAttribute("data-ms-mode", "single");
    wrap.setAttribute("data-ms-label", "recurrence");

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "multiselect-trigger ms-trigger";
    trigger.setAttribute("aria-haspopup", "true");
    trigger.setAttribute("aria-expanded", "false");
    const summary = document.createElement("span");
    summary.className = "ms-summary";
    trigger.appendChild(summary);
    const caret = document.createElement("span");
    caret.className = "filter-caret";
    caret.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-chevron-down"></use></svg>';
    trigger.appendChild(caret);
    wrap.appendChild(trigger);

    const panel = document.createElement("div");
    panel.className = "multiselect-panel ms-panel";

    const radios = [];
    PRESETS.forEach((p) => {
      const label = document.createElement("label");
      label.className = "multiselect-option";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = radioName;
      radio.value = p.value;
      if (matched && p.value === matched.value) radio.checked = true;
      const span = document.createElement("span");
      span.textContent = p.label;
      label.appendChild(radio);
      label.appendChild(span);
      panel.appendChild(label);
      radios.push(radio);
    });

    // Custom RRULE row -- integrated into the panel itself (see file
    // header comment) instead of a second element below the dropdown.
    // Its own radio is visually part of the row but never needs a
    // separate click: focusing or typing into the text field selects it
    // automatically (see the "focus"/"input" listeners below).
    const customRow = document.createElement("label");
    customRow.className = "multiselect-option multiselect-new-option";
    const customRadio = document.createElement("input");
    customRadio.type = "radio";
    customRadio.name = radioName;
    customRadio.value = "__custom__";
    customRow.appendChild(customRadio);
    const customInput = document.createElement("input");
    customInput.type = "text";
    customInput.className = "multiselect-new-input recurrence-custom-input";
    customInput.placeholder = "Custom (e.g. FREQ=WEEKLY;BYDAY=MO,WE)";
    if (!matched && currentValue) {
      customRadio.checked = true;
      customInput.value = currentValue;
    }
    customRow.appendChild(customInput);
    panel.appendChild(customRow);
    wrap.appendChild(panel);

    input.setAttribute("autocomplete", "off");
    input.style.display = "none";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    function checkedPreset() {
      return radios.find((r) => r.checked);
    }

    function updateSummary() {
      if (customRadio.checked) {
        summary.textContent = customInput.value.trim() ? customInput.value.trim() : "Custom";
        return;
      }
      const checked = checkedPreset();
      const preset = checked && PRESETS.find((p) => p.value === checked.value);
      summary.textContent = preset ? preset.label : "Does not repeat";
    }

    function sync() {
      input.value = customRadio.checked ? customInput.value.trim() : (checkedPreset() || {}).value || "";
      updateSummary();
    }
    sync();

    radios.forEach((r) => r.addEventListener("change", sync));
    customInput.addEventListener("focus", () => {
      customRadio.checked = true;
      sync();
    });
    customInput.addEventListener("input", () => {
      customRadio.checked = true;
      sync();
    });
  }

  function scan(root) {
    (root.querySelectorAll ? root.querySelectorAll("input.recurrence-input") : []).forEach(enhance);
    if (root.matches && root.matches("input.recurrence-input")) enhance(root);
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
