// Notebook settings: one table card, a view dropdown switches between Entry types and Frontmatter fields,
// the search box filters the visible rows, and the add button follows the view.
(function () {
  const box = document.getElementById("nb-tables");
  if (!box) return;
  const form = document.getElementById("nb-view-form");
  const search = document.getElementById("nb-table-search");
  const views = {
    "entry-types": { table: "nb-table-entry-types" },
    fields: { table: "nb-table-fields" },
  };
  let view = "entry-types";

  function filter() {
    const q = (search.value || "").trim().toLowerCase();
    document.querySelectorAll("#" + views[view].table + " tbody tr").forEach((row) => {
      row.hidden = !!q && !row.textContent.toLowerCase().includes(q);
    });
  }

  function show(next) {
    if (!views[next]) return;
    view = next;
    box.dataset.view = view;
    Object.keys(views).forEach((k) => { document.getElementById(views[k].table).hidden = k !== view; });
    box.querySelectorAll("[data-nb-add]").forEach((a) => { a.hidden = a.dataset.nbAdd !== view; });
    filter();
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const picked = new FormData(form).get("view");
    if (picked) show(picked);
  });
  search.addEventListener("input", filter);
})();
