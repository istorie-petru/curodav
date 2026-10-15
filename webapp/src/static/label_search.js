(function () {
  let input;
  let list;
  let groups = [];
  let emptyState;
  let emptyQuery;

  // init() is re-invocable: labels_manage.js re-runs it after swapping in
  // a fresh #labels-body region (async-CRUD, features/async-crud.md) so the
  // newly-rendered search box and rows get bound again. The apply() closure
  // reads the module-level `input`/`groups` references, which init()
  // reassigns, so re-binding is the whole re-init.
  function init() {
    input = document.getElementById("label-search-input");
    list = document.getElementById("label-list");
    if (!input || !list) return;

    groups = Array.from(list.querySelectorAll("[data-label-group]"));
    emptyState = document.getElementById("label-search-empty");
    emptyQuery = document.getElementById("label-search-empty-query");

    input.addEventListener("input", apply);
  }

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

  init();
  window.CCLabelSearch = { init: init };
})();
