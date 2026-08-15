// Labels manage page search (2026-08-08 Settings redesign; generalized
// 2026-08-15 when labels_manage.html's markup changed from a <table> to a
// plain <div> list -- side work, direct feedback: "the table should be
// transformed into a simple list"). Filters the already-rendered rows
// client-side, same "no round trip for a page this size" reasoning as
// app.js's multiselect summaries. Each group is a `[data-label-group]`
// starting with a `[data-label-group-header]` divider followed by that
// group's `[data-label-row]` rows -- the divider hides itself too once
// every row in that group is filtered out, so an empty group doesn't sit
// there as a bare heading over nothing. Selectors are plain attribute
// selectors, not tag-specific (`table`/`tbody`), so this same logic covers
// both the old table markup and the new div-list markup unchanged -- only
// the container id (`label-list`, was `label-table`) needed updating.
(function () {
  const input = document.getElementById("label-search-input");
  const list = document.getElementById("label-list");
  if (!input || !list) return;

  const groups = Array.from(list.querySelectorAll("[data-label-group]"));
  const emptyState = document.getElementById("label-search-empty");
  const emptyQuery = document.getElementById("label-search-empty-query");

  function apply() {
    const q = input.value.trim().toLowerCase();
    let anyVisible = false;
    groups.forEach((group) => {
      const header = group.querySelector("[data-label-group-header]");
      let groupHasVisibleRow = false;
      group.querySelectorAll("[data-label-row]").forEach((row) => {
        const match = !q || (row.getAttribute("data-label-name") || "").includes(q);
        row.style.display = match ? "" : "none";
        if (match) {
          groupHasVisibleRow = true;
          anyVisible = true;
        }
      });
      if (header) header.style.display = groupHasVisibleRow ? "" : "none";
    });
    if (emptyState) {
      emptyState.hidden = anyVisible || !q;
      if (emptyQuery) emptyQuery.textContent = q;
    }
  }

  input.addEventListener("input", apply);
})();
