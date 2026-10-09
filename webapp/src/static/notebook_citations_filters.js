// Citations Filters modal (notebook_citations_filters_modal.html,
// 2026-10-03) -- keeps the modal footer's "Apply" link in sync with
// whatever's currently picked in #citations-filters-form, since Apply has
// to be a plain `<a href>` (no `data-modal`), not a real form submit --
// see that template's own header comment for why a GET form can't submit
// itself through modal.js's generic (POST-shaped) form-submit
// interceptor. Document-level delegated listener, same "works for content
// injected into a modal with no explicit re-init call" reasoning as
// Relations' own add-row picker (modal.js's wireContent comment) -- this
// form only ever exists inside a modal, so there's nothing to wire up
// before the modal first opens anyway.
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

  // Year range "autocomplete" (2026-10-03 direct request): typing a Start
  // year while End is still blank live-fills End with the current year --
  // the same default routers/notebook.py's `_resolve_citation_year_range`
  // applies at filter time (and `citations_filters_modal` applies when
  // first rendering this page for a Start that was already set via the
  // URL), mirrored here so it's visible immediately for a Start typed
  // *after* the modal is already open, not just on load. Never the other
  // direction (clearing Start doesn't clear an End the user might have
  // deliberately typed) -- a one-way convenience, not a continuous sync.
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
