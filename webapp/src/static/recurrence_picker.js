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
// 2026-08-15 follow-up ("just implement odd week, even week recurrence for
// events") -- a "Weekly" recurrence now has its own "Repeats" sub-dropdown
// (Every week / Every 2 weeks, odd weeks / Every 2 weeks, even weeks),
// visible only while the Weekly preset is selected, same shape as the
// "Ends" dropdown right below it. There's no ODD/EVEN keyword in RFC 5545
// -- an every-2-weeks RRULE (`INTERVAL=2`) already alternates weeks all by
// itself, and *which* weeks (odd/even ISO week number) is entirely
// determined by whichever week the event's own `start_at` falls in --
// exactly how schedule.py's `event_parity` already derives a class's
// odd/even label from a real event, never a separately stored field (see
// that module's own docstring). So picking "odd weeks" here does two
// things: it writes the same `INTERVAL=2` onto the hidden recurrence input,
// and it snaps the sibling `start_at`(/`end_at`) field forward by 7 days if
// its current date doesn't already fall in an odd ISO week -- otherwise
// "odd weeks" starting on an even week would silently mean "even weeks."
// Reused by both event and task forms (both have a `start_at` field);
// harmless no-op on any other form the picker also enhances (habit_task_
// form.html) since the parity snap just does nothing without a sibling
// `start_at` input to read/write.
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
    let interval2 = false;
    const baseParts = [];
    parts.forEach((part) => {
      if (/^UNTIL=/i.test(part)) {
        until = part.slice(6);
      } else if (/^COUNT=/i.test(part)) {
        count = part.slice(6);
      } else if (/^INTERVAL=2$/i.test(part)) {
        interval2 = true;
      } else {
        baseParts.push(part);
      }
    });
    return { base: baseParts.join(";"), until: until, count: count, interval2: interval2 };
  }

  // ISO-8601 week number parity ('odd'/'even') -- mirrors schedule.py's
  // `iso_week_parity` (Python's `date.isocalendar()[1] % 2`) exactly, so a
  // date picked here and the same date read back through schedule.py agree
  // on which weeks it's "odd"/"even" in.
  function isoWeekParity(dateStr) {
    if (!dateStr || dateStr.length < 10) return null;
    const [y, m, d] = dateStr.slice(0, 10).split("-").map(Number);
    if (!y || !m || !d) return null;
    const date = new Date(Date.UTC(y, m - 1, d));
    const dayNum = date.getUTCDay() || 7; // Mon=1..Sun=7
    date.setUTCDate(date.getUTCDate() + 4 - dayNum); // nearest Thursday
    const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
    const weekNo = Math.ceil(((date - yearStart) / 86400000 + 1) / 7);
    return weekNo % 2 === 1 ? "odd" : "even";
  }

  // Shifts a `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM` string by `days` calendar
  // days, keeping whatever time-of-day suffix it already had.
  function shiftDateStr(dateStr, days) {
    if (!dateStr || dateStr.length < 10) return dateStr;
    const datePart = dateStr.slice(0, 10);
    const rest = dateStr.slice(10);
    const [y, m, d] = datePart.split("-").map(Number);
    const dt = new Date(Date.UTC(y, m - 1, d));
    dt.setUTCDate(dt.getUTCDate() + days);
    const ny = dt.getUTCFullYear();
    const nm = String(dt.getUTCMonth() + 1).padStart(2, "0");
    const nd = String(dt.getUTCDate()).padStart(2, "0");
    return `${ny}-${nm}-${nd}${rest}`;
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

    // "Ends" -- its own separate dropdown (same `.multiselect` markup
    // contract as `wrap` above, so app.js's generic multiselect click/
    // portal/position handling picks it up for free) rather than a
    // sub-panel nested inside the FREQ dropdown -- direct feedback ("could
    // we make ends another drop down menu?"). Only meaningful once a real
    // preset (not "Does not repeat") is selected -- hidden entirely
    // otherwise. "Never" (no suffix), "On date" (UNTIL=, the app's
    // existing dashed-date convention -- see parseValue's own comment
    // above), or "After N occurrences" (COUNT=).
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

    // "Repeats" -- odd/even-week parity, only meaningful for the Weekly
    // preset (see file header comment). Own dropdown, same shape as
    // "Ends" right above -- direct feedback established that pattern for
    // any secondary recurrence choice ("could we make ends another drop
    // down menu?").
    const parityRadioName = "recurrence-parity-" + uid; // group only, never submitted
    const parityWrap = document.createElement("div");
    parityWrap.className = "multiselect widget-list-multiselect recurrence-parity-select";
    parityWrap.setAttribute("data-ms", "");
    parityWrap.setAttribute("data-ms-mode", "single");
    parityWrap.setAttribute("data-ms-label", "repeats");
    parityWrap.hidden = true; // toggled by sync() below

    const parityTrigger = document.createElement("button");
    parityTrigger.type = "button";
    parityTrigger.className = "multiselect-trigger ms-trigger";
    parityTrigger.setAttribute("aria-haspopup", "true");
    parityTrigger.setAttribute("aria-expanded", "false");
    const paritySummary = document.createElement("span");
    paritySummary.className = "ms-summary";
    parityTrigger.appendChild(paritySummary);
    const parityCaret = document.createElement("span");
    parityCaret.className = "filter-caret";
    parityCaret.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-chevron-down"></use></svg>';
    parityTrigger.appendChild(parityCaret);
    parityWrap.appendChild(parityTrigger);

    const parityPanel = document.createElement("div");
    parityPanel.className = "multiselect-panel ms-panel";
    parityWrap.appendChild(parityPanel);

    const PARITY_OPTIONS = [
      { value: "", label: "Every week" },
      { value: "odd", label: "Every 2 weeks (odd weeks)" },
      { value: "even", label: "Every 2 weeks (even weeks)" },
    ];
    const parityRadios = [];
    PARITY_OPTIONS.forEach((opt) => {
      const label = document.createElement("label");
      label.className = "multiselect-option";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = parityRadioName;
      radio.value = opt.value;
      label.appendChild(radio);
      const span = document.createElement("span");
      span.textContent = opt.label;
      label.appendChild(span);
      parityPanel.appendChild(label);
      parityRadios.push(radio);
    });

    // Initial parity radio: if the stored recurrence already carries
    // INTERVAL=2, the sibling start_at field's own ISO week tells us which
    // of odd/even it currently reads as (schedule.py's `event_parity`
    // computes the exact same thing off a real event) -- default to "odd"
    // only if there's no start_at value yet to read (a blank new-event
    // form).
    const formEl = input.closest("form");
    const startInputEl = formEl ? formEl.querySelector('[name="start_at"]') : null;
    if (parsedCurrent.interval2) {
      const currentParity = startInputEl ? isoWeekParity(startInputEl.value) : null;
      const want = currentParity || "odd";
      const r = parityRadios.find((r) => r.value === want);
      if (r) r.checked = true;
    } else {
      parityRadios[0].checked = true;
    }

    // Both dropdowns are siblings of the same original parent -- insert
    // `endsWrap` before `input` (still a plain child of that parent at
    // this point) so it lands right after `wrap`, *then* move `input`
    // inside `wrap` last (see the header comment: `input` stays the
    // permanent, hidden source of truth either dropdown writes into).
    const originalParent = input.parentNode;
    input.setAttribute("autocomplete", "off");
    input.style.display = "none";
    originalParent.insertBefore(wrap, input);
    originalParent.insertBefore(parityWrap, input);
    originalParent.insertBefore(endsWrap, input);
    wrap.appendChild(input);

    // Holiday calendar / exclude Saturday / exclude Sunday (event forms
    // only -- _event_form_fields.html's `.holiday-field`s) only mean
    // anything once this event actually repeats -- direct feedback ("make
    // the holiday selector for events to appear only if the event is
    // recurring"). task_form.html/habit_task_form.html's recurrence field
    // has no such siblings, so this is just an empty NodeList there.
    const fieldGrid = originalParent.closest(".field-grid") || originalParent.parentNode;
    const holidayFields = fieldGrid ? fieldGrid.querySelectorAll(".holiday-field") : [];

    function checkedPreset() {
      return radios.find((r) => r.checked);
    }

    function checkedParity() {
      return parityRadios.find((r) => r.checked);
    }

    function isRecurring() {
      const checked = checkedPreset();
      return checked ? !!checked.value : !!currentValue;
    }

    // The stored base value: the checked preset as-is, except Weekly +
    // an odd/even parity choice adds `INTERVAL=2` (see file header
    // comment -- odd vs. even itself is never stored, only implied by
    // start_at's own ISO week).
    function baseValue() {
      const checked = checkedPreset();
      if (!checked) return null;
      if (checked.value === "FREQ=WEEKLY") {
        const parity = checkedParity();
        return parity && parity.value ? "FREQ=WEEKLY;INTERVAL=2" : "FREQ=WEEKLY";
      }
      return checked.value;
    }

    function endsSuffix() {
      if (untilRadio.checked && untilInput.value) return ";UNTIL=" + untilInput.value;
      if (countRadio.checked && countInput.value) return ";COUNT=" + countInput.value;
      return "";
    }

    // Keeps start_at (and end_at, by the same day delta) glued to whichever
    // ISO-week parity was just picked -- "odd weeks" starting on an even
    // week would otherwise silently mean "even weeks" the moment it's read
    // back (see file header comment).
    function applyParitySnap() {
      const parity = checkedParity();
      if (!parity || !parity.value || !startInputEl || !startInputEl.value) return;
      const current = isoWeekParity(startInputEl.value);
      if (current && current !== parity.value) {
        startInputEl.value = shiftDateStr(startInputEl.value, 7);
        const endInputEl = formEl.querySelector('[name="end_at"]');
        if (endInputEl && endInputEl.value) {
          endInputEl.value = shiftDateStr(endInputEl.value, 7);
        }
      }
    }

    function updateEndsSummary() {
      if (untilRadio.checked && untilInput.value) {
        endsSummary.textContent = "Ends " + untilInput.value;
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

    function updateParitySummary() {
      const parity = checkedParity();
      paritySummary.textContent = (parity && PARITY_OPTIONS.find((o) => o.value === parity.value).label) || "Every week";
    }

    function sync() {
      const checked = checkedPreset();
      if (checked) {
        const base = baseValue();
        input.value = base ? base + endsSuffix() : "";
      }
      // else: nothing checked (unmatched existing value) -- leave the
      // hidden input's value untouched until the user actually picks a
      // preset.
      endsWrap.hidden = !checked || !checked.value;
      parityWrap.hidden = !checked || checked.value !== "FREQ=WEEKLY";
      holidayFields.forEach((el) => { el.hidden = !isRecurring(); });
      updateSummary();
      updateEndsSummary();
      updateParitySummary();
    }
    sync();

    radios.forEach((r) => r.addEventListener("change", sync));
    parityRadios.forEach((r) => r.addEventListener("change", () => {
      applyParitySnap();
      sync();
    }));
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
