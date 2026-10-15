(function () {
  const enhanced = new WeakSet();
  let uid = 0;

  const PRESETS = [
    { value: "", label: "Does not repeat" },
    { value: "FREQ=DAILY", label: "Daily" },
    { value: "FREQ=WEEKLY", label: "Weekly" },
    { value: "FREQ=WEEKLY;INTERVAL=2", label: "Every 2 weeks" },
    { value: "FREQ=MONTHLY", label: "Monthly" },
    { value: "FREQ=YEARLY", label: "Yearly" },
  ];

  // The app's `UNTIL=YYYY-MM-DD` dashed-date convention (see
  // ical_rows.py::_normalize_rrule, which converts it to a proper
  // RFC 5545 compact date only at export time) -- splitting the stored
  // string on ";" and pulling UNTIL=/COUNT= out lets a preset's "Ends"
  // state round-trip through the same plain-text `recurrence` field
  // custom RRULEs already use, with no server-side parsing added.
  function parseValue(value) {
    const parts = (value || "").split(";").filter(Boolean);
    let until = "";
    let count = "";
    const baseParts = [];
    parts.forEach((part) => {
      if (/^UNTIL=/i.test(part)) {
        until = part.slice(6);
      } else if (/^COUNT=/i.test(part)) {
        count = part.slice(6);
      } else {
        baseParts.push(part);
      }
    });
    return { base: baseParts.join(";"), until: until, count: count };
  }

  function enhance(input) {
    if (enhanced.has(input)) return;
    enhanced.add(input);
    uid += 1;
    const radioName = "recurrence-preset-" + uid; // group only, never submitted
    const endsRadioName = "recurrence-ends-" + uid; // group only, never submitted

    const currentValue = input.value || "";
    const parsedCurrent = parseValue(currentValue);
    const matched = PRESETS.find((p) => p.value === parsedCurrent.base);

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

    wrap.appendChild(panel);

    const endsWrap = document.createElement("div");
    endsWrap.className = "multiselect widget-list-multiselect recurrence-ends-select";
    endsWrap.setAttribute("data-ms", "");
    endsWrap.setAttribute("data-ms-mode", "single");
    endsWrap.setAttribute("data-ms-label", "ends");
    endsWrap.hidden = true; // toggled by sync() below

    const endsTrigger = document.createElement("button");
    endsTrigger.type = "button";
    endsTrigger.className = "multiselect-trigger ms-trigger";
    endsTrigger.setAttribute("aria-haspopup", "true");
    endsTrigger.setAttribute("aria-expanded", "false");
    const endsSummary = document.createElement("span");
    endsSummary.className = "ms-summary";
    endsTrigger.appendChild(endsSummary);
    const endsCaret = document.createElement("span");
    endsCaret.className = "filter-caret";
    endsCaret.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-chevron-down"></use></svg>';
    endsTrigger.appendChild(endsCaret);
    endsWrap.appendChild(endsTrigger);

    const endsPanel = document.createElement("div");
    endsPanel.className = "multiselect-panel ms-panel";
    endsWrap.appendChild(endsPanel);

    function endsOption(value, labelText, extraNode) {
      const label = document.createElement("label");
      label.className = "multiselect-option recurrence-ends-option";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = endsRadioName;
      radio.value = value;
      label.appendChild(radio);
      const span = document.createElement("span");
      span.textContent = labelText;
      label.appendChild(span);
      if (extraNode) label.appendChild(extraNode);
      endsPanel.appendChild(label);
      return radio;
    }

    const untilField = document.createElement("div");
    untilField.className = "dtf dtf-date dtf--compact recurrence-ends-until";
    untilField.dataset.dtf = "date";
    untilField.dataset.dtfWeekStart = document.body.dataset.weekStart || "monday";
    untilField.innerHTML =
      '<input type="text" class="dtf-input" autocomplete="off" spellcheck="false" aria-label="Ends on">' +
      '<button type="button" class="dtf-btn" tabindex="-1" aria-label="Choose end date"><svg class="icon icon-sm" aria-hidden="true"><use href="#icon-chevron-down"></use></svg></button>' +
      '<input type="hidden" class="dtf-value" value="">';
    const untilInput = untilField.querySelector(".dtf-value");
    const untilText = untilField.querySelector(".dtf-input");

    const countInput = document.createElement("input");
    countInput.type = "number";
    countInput.min = "1";
    countInput.step = "1";
    countInput.className = "multiselect-new-input recurrence-ends-count";
    countInput.setAttribute("aria-label", "Occurrences");

    const neverRadio = endsOption("never", "Never");
    const deadlineRadio = endsOption("deadline", "At project\u2019s deadline");
    const deadlineOption = deadlineRadio.parentNode;
    const form = input.closest("form");
    const projectRadios = () => (form && form.elements["project"] ? Array.from(form.elements["project"]).filter((r) => r.type === "radio") : []);
    function projectDeadline() {
      const checked = projectRadios().find((r) => r.checked);
      return checked && checked.dataset.deadline ? checked.dataset.deadline : "";
    }
    const untilRadio = endsOption("until", "On date", untilField);
    const countRadio = endsOption("count", "After", countInput);
    const occLabel = document.createElement("span");
    occLabel.textContent = "occurrences";
    countRadio.parentNode.appendChild(occLabel);

    if (matched && matched.value) {
      if (parsedCurrent.until && parsedCurrent.until === projectDeadline()) {
        deadlineRadio.checked = true;
      } else if (parsedCurrent.until) {
        untilRadio.checked = true;
        untilInput.value = parsedCurrent.until;
        if (window.CCDateField) untilText.value = window.CCDateField.fmtDate(parsedCurrent.until);
      } else if (parsedCurrent.count) {
        countRadio.checked = true;
        countInput.value = parsedCurrent.count;
      } else {
        neverRadio.checked = true;
      }
    } else {
      neverRadio.checked = true;
    }

    const originalParent = input.parentNode;
    input.setAttribute("autocomplete", "off");
    input.style.display = "none";
    const row = document.createElement("div");
    row.className = "recurrence-preset-row";
    row.appendChild(wrap);
    row.appendChild(endsWrap);
    originalParent.insertBefore(row, input);
    wrap.appendChild(input);

    const fieldGrid = originalParent.closest(".field-grid") || originalParent.parentNode;
    const holidayFields = fieldGrid ? fieldGrid.querySelectorAll(".holiday-field") : [];

    function checkedPreset() {
      return radios.find((r) => r.checked);
    }

    function isRecurring() {
      const checked = checkedPreset();
      return checked ? !!checked.value : !!currentValue;
    }

    function endsSuffix() {
      if (deadlineRadio.checked && projectDeadline()) return ";UNTIL=" + projectDeadline();
      if (untilRadio.checked && untilInput.value) return ";UNTIL=" + untilInput.value;
      if (countRadio.checked && countInput.value) return ";COUNT=" + countInput.value;
      return "";
    }

    function updateEndsSummary() {
      if (deadlineRadio.checked && projectDeadline()) {
        endsSummary.textContent = "Ends at project\u2019s deadline";
        return;
      }
      if (untilRadio.checked && untilInput.value) {
        endsSummary.textContent = "Ends " + (window.CCDateField ? window.CCDateField.fmtDate(untilInput.value) : untilInput.value);
      } else if (countRadio.checked && countInput.value) {
        endsSummary.textContent = "Ends after " + countInput.value + (countInput.value === "1" ? " occurrence" : " occurrences");
      } else {
        endsSummary.textContent = "Never ends";
      }
    }

    function updateSummary() {
      const checked = checkedPreset();
      if (!checked) {
        // No preset matches the existing value (see file header comment)
        // -- shown read-only, never rewritten until a preset is picked.
        summary.textContent = currentValue || "Does not repeat";
        return;
      }
      summary.textContent = PRESETS.find((p) => p.value === checked.value).label;
    }

    function sync() {
      // The deadline option exists only while the chosen project has one.
      deadlineOption.hidden = !projectDeadline();
      if (deadlineRadio.checked && !projectDeadline()) neverRadio.checked = true;
      const checked = checkedPreset();
      if (checked) {
        input.value = checked.value ? checked.value + endsSuffix() : "";
      }
      // else: nothing checked (unmatched existing value) -- leave the
      // hidden input's value untouched until the user actually picks a
      // preset.
      endsWrap.hidden = !checked || !checked.value;
      holidayFields.forEach((el) => { el.hidden = !isRecurring(); });
      updateSummary();
      updateEndsSummary();
    }
    sync();

    projectRadios().forEach((r) => r.addEventListener("change", sync));
    radios.forEach((r) => r.addEventListener("change", sync));
    [neverRadio, deadlineRadio, untilRadio, countRadio].forEach((r) => r.addEventListener("change", sync));
    untilText.addEventListener("focus", () => {
      untilRadio.checked = true;
      sync();
    });
    untilInput.addEventListener("change", () => {
      untilRadio.checked = true;
      sync();
    });
    countInput.addEventListener("focus", () => {
      countRadio.checked = true;
      sync();
    });
    countInput.addEventListener("input", () => {
      countRadio.checked = true;
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
