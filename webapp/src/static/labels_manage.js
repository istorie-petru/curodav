// Labels manage page: async-CRUD region refresh (features/async-crud.md) --
// the list body is a named region that the create/edit/delete modals
// target on success.
//
// 2026-09-14 (Spaces -- labels-as-membership rework slice 2, side fix):
// this file used to also own a client-side search filter keyed on
// `#label-search-input`/`#labels-table-wrapper`'s row/Group-column text --
// dropped entirely rather than adapted, because no template has ever
// actually rendered a `#label-search-input` element (grepped the whole
// `templates/` tree -- it doesn't exist anywhere), so that whole block's
// top `if (!searchInput || !tableWrapper) return;` guard made EVERY line
// below it dead code, including the async-CRUD listener wiring at the
// bottom -- editing/creating/deleting a label through the modal has been
// silently leaving the table showing stale data ever since (no crash, no
// error, just nothing refreshing) until a manual page reload. That's a
// real, separate bug this rework's own restructuring of the exact markup
// this script touches surfaced, not something slice 2 was asked to add a
// search box to fix -- so the fix here is narrowly "make the refresh
// listener actually run," not "build the missing search feature."
(function () {
    const tableWrapper = document.getElementById("labels-table");

    if (!tableWrapper) return;

    // async-CRUD: listen for label changes and refresh the whole
    // container. 2026-09-14 slice 2: used to swap just one `<tbody>`'s
    // innerHTML (the old single flat `<table>`'s only tbody) -- now that
    // _labels_table_body.html renders one `<table>` per Space plus an
    // "Ungrouped" table (each with its own tbody), a single-tbody swap
    // can't express "a Space was renamed" or "the last label under a
    // Space was cleared, so that Space's table should show just its own
    // row again" -- those change which/how many tables exist, not just
    // which rows are inside one. Replacing the whole container's
    // innerHTML with the freshly-rendered fragment handles every case
    // uniformly, same "just re-render the region" contract the fragment
    // endpoint already provides.
    document.addEventListener("cc-entity-changed", (e) => {
        if (e.detail?.type === "label") {
            e.detail.claimed = true;
            refreshLabelsTable();
        }
    });

    // 2026-09-26 (Peter): Convert to project is a row action with a
    // confirmation toast. Same shape as a list-row delete (static/app.js):
    // the row hides at once, the toast offers Undo, and the POST is only
    // sent once the toast runs out -- then the list re-renders without
    // the label (it's on Settings > Projects now).
    document.addEventListener("submit", (e) => {
        const form = e.target;
        if (!(form instanceof HTMLFormElement) || !form.dataset.convertUndo) return;
        e.preventDefault();
        const name = form.dataset.convertUndo;
        const row = form.closest("tr");
        if (row) row.style.display = "none";
        let cancelled = false;
        const timer = setTimeout(async () => {
            if (cancelled) return;
            try {
                const resp = await fetch(form.action, { method: "POST", headers: { "X-Requested-With": "fetch" }, body: new FormData(form) });
                if (!resp.ok) throw new Error();
                refreshLabelsTable();
            } catch (err) {
                if (row) row.style.display = "";
                window.ccToast && window.ccToast({ message: "Could not convert \u201c" + name + "\u201d.", variant: "error" });
            }
        }, 4500);
        window.ccToast({
            title: "Converted to project",
            message: "\u201c" + name + "\u201d",
            actionLabel: "Undo",
            onAction: () => {
                cancelled = true;
                clearTimeout(timer);
                if (row) row.style.display = "";
            },
            duration: 4500,
        });
    });

    async function refreshLabelsTable() {
        try {
            // 2026-09-26: the same list serves Settings > Projects.
            const kind = tableWrapper.dataset.kind || "labels";
            const resp = await fetch("/settings/labels/regions?region=list&kind=" + encodeURIComponent(kind), {
                headers: { "X-Requested-With": "fetch" },
            });
            if (resp.ok) {
                tableWrapper.innerHTML = await resp.text();
            }
        } catch (err) {
            console.error("Failed to refresh labels:", err);
        }
    }
})();
