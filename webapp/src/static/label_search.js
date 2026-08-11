// Labels manage page search (2026-08-08 Settings redesign; markup updated
// to a real <table> the same day, see labels_manage.html's own comment) --
// filters the already-rendered rows client-side, same "no round trip for a
// page this size" reasoning as app.js's multiselect summaries. Each group
// is a <tbody data-label-group> starting with a divider row
// (data-label-group-header, "Ungrouped"/parent name) followed by that
// group's label rows (data-label-row) -- the divider hides itself too once
// every row in that tbody is filtered out, so an empty group doesn't sit
// there as a bare heading over nothing.
(function () {
  const input = document.getElementById("label-search-input");
  const table = document.getElementById("label-table");
  if (!input || !table) return;

  const groups = Array.from(table.querySelectorAll("tbody[data-label-group]"));
  const emptyState = document.getElementById("label-search-empty");
  const emptyQuery = document.getElementById("label-search-empty-query");

  function apply() {
    const q = input.value.trim().toLowerCase();
    let anyVisible = false;
    groups.forEach((tbody) => {
      const header = tbody.querySelector("[data-label-group-header]");
      let groupHasVisibleRow = false;
      tbody.querySelectorAll("[data-label-row]").forEach((row) => {
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
