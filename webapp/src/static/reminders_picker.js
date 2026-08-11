// Progressive enhancement for `<input class="reminders-input"
// name="reminders">` (event_form.html only -- tasks have no reminders
// field) into a themed checkbox-dropdown for common presets instead of a
// raw comma-separated-minutes text field. routers/calendar.py's
// create_event/update_event parse this purely as
// `[int(m) for m in reminders.split(",") if m.strip().isdigit()]`, with no
// other validation, so -- same as recurrence_picker.js -- this is entirely
// a client-side swap: the underlying `<input name="reminders">` keeps its
// name/value contract exactly as-is, just populated by checkboxes (plus a
// small "other minutes" escape hatch for any existing value that doesn't
// match a preset) instead of typed directly.
//
// 2026-08-07 follow-up ("view, range, priority, reminders should be real
// drop downs") -- Reminders is genuinely multi-select (you can pick "10
// minutes before" AND "1 day before" at once), so it can't become a
// single-value native <select> like View/Range/Priority did; instead this
// now builds the exact same `.multiselect`/`.multiselect-trigger`/
// `.multiselect-panel` dropdown-panel markup _widget_list_multiselect.html
// uses for Labels/Task lists/Calendars (reusing `.widget-list-multiselect`
// gets it the same trigger sizing as a real <select> for free, see that
// class's own comment in style.css) instead of a flat inline row of
// checkboxes. app.js's generic .multiselect
// script (open/close on trigger click, close on outside click/Escape) is
// delegated off `document`, and its own summary-sync listener is delegated
// off `.widget-list-multiselect` too, so both automatically pick up this
// dynamically-injected panel with no extra wiring -- only the *initial*
// summary text (before any user interaction) is set here directly, since
// app.js's own one-time init pass runs at DOMContentLoaded, before this
// enhancement exists yet.
//
// Same "scan on DOMContentLoaded + MutationObserver for modal-injected
// content" convention as tag_input.js/recurrence_picker.js.
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
    customInput.placeholder = "Other minutes before (comma-separated)";
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
