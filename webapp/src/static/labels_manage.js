// Labels manage page: search filter + async-CRUD region refresh
// (features/async-crud.md) -- the list body is a named region
// that the create/edit/delete modals target on success.

(function () {
    const searchInput = document.getElementById("label-search-input");
    const tableWrapper = document.getElementById("labels-table-wrapper");
    const emptyRow = document.getElementById("empty-state-row");

    if (!searchInput || !tableWrapper) return;

    const rows = Array.from(tableWrapper.querySelectorAll("tr[data-label-name]"));

    searchInput.addEventListener("input", () => {
        const query = searchInput.value.trim().toLowerCase();
        let visibleCount = 0;

        rows.forEach((row) => {
            const name = row.getAttribute("data-label-name") || "";
            const group = row.querySelector("td:nth-child(2)")?.textContent?.toLowerCase() || "";
            const matches = name.includes(query) || group.includes(query);
            row.style.display = matches ? "" : "none";
            if (matches) visibleCount++;
        });

        const emptyMsg = tableWrapper.querySelector("#label-search-empty");
        const emptyQuery = tableWrapper.querySelector("#label-search-empty-query");
        if (emptyMsg && emptyQuery) {
            emptyMsg.hidden = visibleCount > 0 || query === "";
            emptyQuery.textContent = query;
        }

        if (emptyRow) {
            emptyRow.style.display = (rows.length === 0 && query === "") ? "" : "none";
        }
    });

    // async-CRUD: listen for label changes and refresh just the table body
    document.addEventListener("cc-entity-changed", (e) => {
        if (e.detail?.type === "label") {
            refreshLabelsBody();
        }
    });

    async function refreshLabelsBody() {
        try {
            const resp = await fetch("/settings/labels/regions?region=list", {
                headers: { "X-Requested-With": "fetch" },
            });
            if (resp.ok) {
                const html = await resp.text();
                const wrapper = document.createElement("div");
                wrapper.innerHTML = html;
                const newBody = wrapper.querySelector("tbody");
                const tbody = tableWrapper.querySelector("tbody");
                if (newBody && tbody) {
                    tbody.innerHTML = newBody.innerHTML;
                    // Re-bind search to new rows
                    rows.length = 0;
                    rows.push(...Array.from(tableWrapper.querySelectorAll("tr[data-label-name]")));
                }
            }
        } catch (err) {
            console.error("Failed to refresh labels:", err);
        }
    }
})();