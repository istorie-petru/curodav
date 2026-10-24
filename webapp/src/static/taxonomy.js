// Labels, groups, projects and holidays settings pages: reloads the rows
// after a change and binds the bulk bar to the page's view.
(function () {
    const box = document.getElementById("taxonomy-table");
    if (!box) return;
    const body = document.getElementById("taxonomy-body");
    let view = box.dataset.view || "labels";

    function bindBulk() {
        const base = { tableId: "taxonomy-table" };
        if (view === "labels" || view === "projects") {
            const noun = view === "projects" ? "project" : "label";
            window.CCBulkSelect.init(Object.assign(base, {
                barId: "labels-bulk-bar", countId: "labels-bulk-count", clearId: "labels-bulk-clear",
                deleteButtonId: "labels-bulk-delete", deleteUrl: "/settings/labels/bulk-delete", changeType: "label",
                editButtonId: "labels-bulk-edit", editModalUrl: "/settings/labels/bulk-edit-modal",
                mergeButtonId: "labels-bulk-merge", mergeModalUrl: "/settings/labels/bulk-merge-modal",
                itemLabel: noun,
                confirmMessage: (n) => "Delete " + n + " selected " + noun + (n === 1 ? "" : "s") + "? This removes " + (n === 1 ? "it" : "them") + " from every object that carries " + (n === 1 ? "it" : "them") + " and from this list.",
            }));
        } else if (view === "holidays") {
            window.CCBulkSelect.init(Object.assign(base, {
                barId: "holidays-bulk-bar", countId: "holidays-bulk-count", clearId: "holidays-bulk-clear",
                deleteButtonId: "holidays-bulk-delete", deleteUrl: "/settings/holidays/bulk-delete", itemLabel: "holiday",
            }));
        } else if (view === "time_blocks") {
            window.CCBulkSelect.init(Object.assign(base, {
                barId: "time-blocks-bulk-bar", countId: "time-blocks-bulk-count", clearId: "time-blocks-bulk-clear",
                deleteButtonId: "time-blocks-bulk-delete", deleteUrl: "/settings/time-blocks/bulk-delete", itemLabel: "time block",
            }));
        } else {
            window.CCBulkSelect.init(Object.assign(base, { barId: "none" }));
        }
    }

    async function load(next) {
        try {
            const resp = await fetch("/settings/taxonomy/rows?view=" + encodeURIComponent(next), { headers: { "X-Requested-With": "fetch" } });
            if (!resp.ok) throw new Error();
            const data = await resp.json();
            view = data.view;
            box.dataset.view = view;
            body.innerHTML = data.rows;
            data.headers.forEach((text, i) => {
                const th = document.getElementById("taxonomy-th-" + i);
                if (th) th.textContent = text;
            });
            if (next !== data.view || location.pathname !== data.url) history.replaceState(null, "", data.url);
            bindBulk();
        } catch (err) {
            window.ccToast && window.ccToast({ message: "Could not load this view.", variant: "error" });
        }
    }


    document.addEventListener("cc-entity-changed", (e) => {
        const type = e.detail && e.detail.type;
        if (type !== "label" && type !== "group") return;
        e.detail.claimed = true;
        load(view);
    });

    // Convert to project and Archive/Unarchive: the row hides or the toast
    // offers Undo; nothing is sent for Convert until the toast runs out.
    document.addEventListener("submit", (e) => {
        const f = e.target;
        if (!(f instanceof HTMLFormElement)) return;
        if (f.dataset.convertUndo) {
            e.preventDefault();
            const name = f.dataset.convertUndo;
            const row = f.closest("tr");
            if (row) row.style.display = "none";
            let cancelled = false;
            const timer = setTimeout(async () => {
                if (cancelled) return;
                try {
                    const resp = await fetch(f.action, { method: "POST", headers: { "X-Requested-With": "fetch" }, body: new FormData(f) });
                    if (!resp.ok) throw new Error();
                    load(view);
                } catch (err) {
                    if (row) row.style.display = "";
                    window.ccToast && window.ccToast({ message: "Could not convert “" + name + "”.", variant: "error" });
                }
            }, 4500);
            window.ccToast({
                title: "Converted to project", message: "“" + name + "”", actionLabel: "Undo", duration: 4500,
                onAction: () => { cancelled = true; clearTimeout(timer); if (row) row.style.display = ""; },
            });
        } else if (f.dataset.rowToggle) {
            e.preventDefault();
            const name = f.dataset.rowName;
            fetch(f.action, { method: "POST", headers: { "X-Requested-With": "fetch" } })
                .then((r) => {
                    if (!r.ok) throw new Error();
                    load(view);
                    window.ccToast({
                        title: f.dataset.rowToggle, message: "“" + name + "”", actionLabel: "Undo",
                        onAction: () => fetch(f.dataset.undoUrl, { method: "POST", headers: { "X-Requested-With": "fetch" } }).then(() => load(view)),
                    });
                })
                .catch(() => window.ccToast({ message: "Could not update “" + name + "”.", variant: "error" }));
        }
    });

    document.addEventListener("DOMContentLoaded", bindBulk);
    if (document.readyState !== "loading") bindBulk();
})();
