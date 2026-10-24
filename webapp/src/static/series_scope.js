/* Event form of a repeating event: the rule and the weekend/holiday policy belong to the series, so they are only
   editable when "Apply changes to" is not "This event". */
(function () {
  document.addEventListener("change", (e) => {
    const input = e.target;
    if (!(input instanceof HTMLInputElement) || input.name !== "series_scope" || !input.checked) return;
    const form = input.closest("form");
    if (!form) return;
    const locked = input.value === "this";
    form.querySelectorAll("[data-series-only]").forEach((el) => {
      el.toggleAttribute("inert", locked);
    });
  });

  // A changed rule rebuilds the rows it covers, which drops hand edits on them: ask first.
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    const scope = form.querySelector('input[name="series_scope"]:checked, input[type="hidden"][name="series_scope"]');
    const rule = form.querySelector('input[name="recurrence"]');
    if (!scope || !rule) return;
    if (scope.value !== "this" && rule.value !== rule.defaultValue) {
      form.setAttribute("data-confirm-sheet", "Changing the rule rebuilds the affected events. Edits made to individual ones are lost.");
    } else {
      form.removeAttribute("data-confirm-sheet");
    }
  }, true);

  // Split edit window: the main button saves this event; once a rule field changes it saves the series instead.
  function syncMain(form) {
    const rules = form.querySelector("[data-series-rules]");
    const main = document.querySelector("[data-split-main]");
    const scope = form.querySelector('input[type="hidden"][name="series_scope"]');
    if (!rules || !main || !scope) return;
    const dirty = Array.from(rules.querySelectorAll("input, select, textarea")).some((el) => {
      const now = el.type === "checkbox" || el.type === "radio" ? String(el.checked) : el.value;
      return el.dataset.base !== undefined && el.dataset.base !== now;
    });
    scope.value = dirty ? "all" : "this";
    const label = main.querySelector(".btn-split-label");
    if (!main.dataset.labelThis && label) main.dataset.labelThis = label.textContent;
    if (label) label.textContent = dirty ? main.dataset.labelAlt : main.dataset.labelThis;
  }
  // The values before the first touch are the baseline a "changed rule" is measured from.
  ["pointerdown", "focusin"].forEach((type) => document.addEventListener(type, (e) => {
    const rules = e.target.closest && e.target.closest("[data-series-rules]");
    if (!rules || rules.dataset.baseTaken) return;
    rules.dataset.baseTaken = "1";
    rules.querySelectorAll("input, select, textarea").forEach((el) => {
      el.dataset.base = el.type === "checkbox" || el.type === "radio" ? String(el.checked) : el.value;
    });
  }, true));
  ["input", "change"].forEach((type) => document.addEventListener(type, (e) => {
    const form = e.target.closest && e.target.closest("form");
    if (e.target.closest && e.target.closest("[data-series-rules]") && form) syncMain(form);
  }));
})();
