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
    const scope = form.querySelector('input[name="series_scope"]:checked');
    const rule = form.querySelector('input[name="recurrence"]');
    if (!scope || !rule) return;
    if (scope.value !== "this" && rule.value !== rule.defaultValue) {
      form.setAttribute("data-confirm-sheet", "Changing the rule rebuilds the affected events. Edits made to individual ones are lost.");
    } else {
      form.removeAttribute("data-confirm-sheet");
    }
  }, true);
})();
