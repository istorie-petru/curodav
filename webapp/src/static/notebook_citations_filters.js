(function () {
  function syncApplyHref(form) {
    const apply = document.getElementById("citations-filters-apply");
    if (!apply) return;
    const params = new URLSearchParams(new FormData(form));
    const query = params.toString();
    apply.setAttribute("href", "/notebook/citations" + (query ? "?" + query : ""));
  }

  document.addEventListener("change", (e) => {
    const form = e.target.form; // works even portaled -- resolves via the input's own `form="..."` attribute, not DOM ancestry (see _widget_list_multiselect.html's own comment on this)
    if (form && form.id === "citations-filters-form") syncApplyHref(form);
  });

  document.addEventListener("input", (e) => {
    if (e.target.id !== "citations-filter-year-from") return;
    const yearTo = document.getElementById("citations-filter-year-to");
    if (yearTo && !yearTo.value && e.target.value) {
      yearTo.value = String(new Date().getFullYear());
    }
    const form = e.target.form;
    if (form && form.id === "citations-filters-form") syncApplyHref(form);
  });
})();
