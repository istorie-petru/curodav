// Labels manage page search (2026-08-08 Settings redesign; generalized
// 2026-08-15 when labels_manage.html's markup changed from a <table> to a
// plain <div> list, and again the same day when Spaces became real group
// headers -- side work, direct feedback: "the table should be transformed
// into a simple list" / "the spaces list should be displayed differently
// and all their children be always in their group"). Filters the
// already-rendered rows client-side, same "no round trip for a page this
// size" reasoning as app.js's multiselect summaries.
//
// Each group is a `[data-label-group]`. Its header is either a Space's own
// row (which is ALSO a `[data-label-row]`, carrying both attributes at
// once -- routers/labels.py::manage_labels' Space groups) or a plain text
// "Ungrouped" divider with no `data-label-name` of its own. Two passes:
//   1. every `[data-label-row]:not([data-label-group-header])` (a group's
//      ordinary/child rows) hides/shows on its own name match, same as
//      before.
//   2. the header shows if EITHER its own name matches (so searching a
//      Space's own name keeps that Space's row visible even if none of
//      its children match) OR any child in its group matched in pass 1 --
//      a Space with a matching child should still show as context for
//      that child, not disappear along with an unrelated non-match on its
//      own name.
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
      let groupMatches = false;

      const headerNameMatches = !q || (header && (header.getAttribute("data-label-name") || "").includes(q));
      if (headerNameMatches) groupMatches = true;

      group.querySelectorAll("[data-label-row]:not([data-label-group-header])").forEach((row) => {
        const match = !q || (row.getAttribute("data-label-name") || "").includes(q);
        row.style.display = match ? "" : "none";
        if (match) groupMatches = true;
      });

      if (header) header.style.display = groupMatches ? "" : "none";
      if (groupMatches) anyVisible = true;
    });
    if (emptyState) {
      emptyState.hidden = anyVisible || !q;
      if (emptyQuery) emptyQuery.textContent = q;
    }
  }

  input.addEventListener("input", apply);
})();
