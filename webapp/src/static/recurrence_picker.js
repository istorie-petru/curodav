// Progressive enhancement for `<input class="recurrence-input" name="recurrence">`
// (task_form.html/event_form.html/habit_task_form.html's Recurrence field)
// into a preset picker ("Does not repeat"/"Daily"/"Weekly"/"Monthly"/
// "Yearly", each with an "Ends" sub-choice) instead of asking the user to
// type raw RRULE syntax directly -- direct feedback: "the modal window
// should prioritize drop down menus and other input methods, not just text
// input."
//
// 2026-08-14 follow-up ("remove the custom option for recurring") -- the
// free-text "Custom RRULE" escape hatch (a text input living inside the
// dropdown panel as its own row) was removed entirely; the five fixed
// presets plus their end-condition are now the only thing this UI can
// produce. An existing value that doesn't match one of the five presets
// (e.g. a hand-authored `BYDAY=...` rule, or anything Schedule/an API
// caller wrote directly) is left with **no preset radio checked** and its
// raw text shown read-only as the trigger's summary -- `sync()` only ever
// overwrites the hidden input's value once a preset radio is actually
// checked, so simply opening and closing this form can never silently
// clobber a recurrence rule this picker doesn't understand. Selecting any
// preset does replace it, same as picking a different preset always has.
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

    // "Ends" sub-panel -- only meaningful once a real preset (not "Does
    // not repeat") is selected. Direct feedback: recurrence needs a way to
    // stop besides "forever" -- "Never" (no suffix), "On date" (UNTIL=,
    // the app's existing dashed-date convention -- see parseValue's own
    // comment above), or "After N occurrences" (COUNT=).
    const endsDivider = document.createElement("div");
    endsDivider.className = "multiselect-divider";
    panel.appendChild(endsDivider);

    const endsGroup = document.createElement("div");
    endsGroup.className = "recurrence-ends-group";
    endsGroup.hidden = true; // toggled by sync() below

    const endsHeading = document.createElement("div");
    endsHeading.className = "recurrence-ends-heading";
    endsHeading.textContent = "Ends";
    endsGroup.appendChild(endsHeading);

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
      endsGroup.appendChild(label);
      return radio;
    }

    const untilInput = document.createElement("input");
    untilInput.type = "date";
    untilInput.className = "multiselect-new-input recurrence-ends-until";

    const countInput = document.createElement("input");
    countInput.type = "number";
    countInput.min = "1";
    countInput.step = "1";
    countInput.className = "multiselect-new-input recurrence-ends-count";
    countInput.placeholder = "10";

    const neverRadio = endsOption("never", "Never");
    const untilRadio = endsOption("until", "On date", untilInput);
    const countRadio = endsOption("count", "After", countInput);
    const occLabel = document.createElement("span");
    occLabel.textContent = "occurrences";
    countRadio.parentNode.appendChild(occLabel);

    if (matched && matched.value) {
      if (parsedCurrent.until) {
        untilRadio.checked = true;
        untilInput.value = parsedCurrent.until;
      } else if (parsedCurrent.count) {
        countRadio.checked = true;
        countInput.value = parsedCurrent.count;
      } else {
        neverRadio.checked = true;
      }
    } else {
      neverRadio.checked = true;
    }

    panel.appendChild(endsGroup);
    wrap.appendChild(panel);

    input.setAttribute("autocomplete", "off");
    input.style.display = "none";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    function checkedPreset() {
      return radios.find((r) => r.checked);
    }

    function endsSuffix() {
      if (untilRadio.checked && untilInput.value) return ";UNTIL=" + untilInput.value;
      if (countRadio.checked && countInput.value) return ";COUNT=" + countInput.value;
      return "";
    }

    function updateSummary() {
      const checked = checkedPreset();
      if (!checked) {
        // No preset matches the existing value (see file header comment)
        // -- shown read-only, never rewritten until a preset is picked.
        summary.textContent = currentValue || "Does not repeat";
        return;
      }
      const preset = PRESETS.find((p) => p.value === checked.value);
      let text = preset.label;
      if (preset.value) {
        if (untilRadio.checked && untilInput.value) {
          text += " until " + untilInput.value;
        } else if (countRadio.checked && countInput.value) {
          text += ", " + countInput.value + "x";
        }
      }
      summary.textContent = text;
    }

    function sync() {
      const checked = checkedPreset();
      if (checked) {
        input.value = checked.value ? checked.value + endsSuffix() : "";
      }
      // else: nothing checked (unmatched existing value) -- leave the
      // hidden input's value untouched until the user actually picks a
      // preset.
      endsGroup.hidden = !checked || !checked.value;
      updateSummary();
    }
    sync();

    radios.forEach((r) => r.addEventListener("change", sync));
    [neverRadio, untilRadio, countRadio].forEach((r) => r.addEventListener("change", sync));
    untilInput.addEventListener("focus", () => {
      untilRadio.checked = true;
      sync();
    });
    untilInput.addEventListener("input", () => {
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
