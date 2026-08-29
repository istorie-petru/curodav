// Generic checkbox-based bulk-select + "Delete selected" bar for
// table-like list surfaces (2026-08-29, STATE.md backlog item 1, direct
// request: "bulk actions on tables... Tasks first, since it's the
// precedent; then Habits, Contacts, Labels, Holidays, Time blocks, etc.
// wherever a table exists"). static/tasks_table.js is that precedent and
// keeps its own bespoke implementation unchanged (it has richer per-
// domain bulk actions -- status/tag -- plus async-CRUD region-swap
// reconciliation neither Labels/Holidays/Time blocks need, since those
// pages are still plain full-reload-on-mutation surfaces); this module
// factors out just the reusable selection mechanics -- checkbox tracking,
// shift-click range select, press-and-drag "paint" across the checkbox
// column, the bar's show/hide/count -- for every other simple settings
// table's "Delete selected" bar. Habit rows inside the Tasks table are a
// third case, deliberately NOT wired to this module -- they share the
// Tasks page's own `#task-table`/bulk-actions-bar and selection Set, see
// static/tasks_table.js's own comment on habit-row deletion.
//
// window.CCBulkSelect.init({
//   tableId          -- id of the table (or any container) whose
//                       `.row-select` checkboxes this instance owns --
//                       scopes every query so two independent instances
//                       on one page (e.g. Sleep Time + Leisure Time) never
//                       see each other's checkboxes or drag-paint into
//                       each other.
//   barId            -- id of this instance's own bulk-actions-bar
//                       (same `.bulk-actions-bar` markup/CSS Tasks uses,
//                       hidden via `style="display:none"` until a row is
//                       selected).
//   countId          -- id of the "<span class=bulk-count>" inside the bar.
//   clearId          -- id of the bar's "Clear" button.
//   deleteButtonId   -- id of the bar's "Delete" button.
//   deleteUrl        -- fetch() target for the bulk delete POST, always
//                       sent as JSON `{uids: [...]}`.
//   itemLabel        -- singular noun for confirm/toast copy, e.g. "label".
//   confirmMessage   -- optional `(count) => string` overriding the
//                       default "Delete N selected X(s)? This cannot be
//                       undone." (Labels' bulk delete is really "clear
//                       usage," not an irreversible row delete, so it
//                       supplies its own wording -- see
//                       labels_manage.html.)
// })
(function () {
  function init(cfg) {
    const table = document.getElementById(cfg.tableId);
    const bar = document.getElementById(cfg.barId);
    const countEl = cfg.countId ? document.getElementById(cfg.countId) : null;
    if (!table || !bar) return;

    const selected = new Set();
    let lastClickedIdx = null;

    function checkboxes() {
      return Array.from(table.querySelectorAll(".row-select"));
    }
    function rowFor(cb) {
      return cb.closest("tr");
    }
    function setSelected(cb, on) {
      cb.checked = on;
      const row = rowFor(cb);
      if (on) {
        selected.add(cb.dataset.uid);
        if (row) row.classList.add("is-selected");
      } else {
        selected.delete(cb.dataset.uid);
        if (row) row.classList.remove("is-selected");
      }
    }
    function updateBar() {
      if (selected.size > 0) {
        bar.style.display = "flex";
        if (countEl) countEl.textContent = `${selected.size} selected`;
      } else {
        bar.style.display = "none";
      }
    }

    // Click (plain or shift-range) -- scoped to this table so a second
    // CCBulkSelect instance elsewhere on the page doesn't also react.
    table.addEventListener("click", (e) => {
      const cb = e.target.closest && e.target.closest(".row-select");
      if (!cb) return;
      const boxes = checkboxes();
      const idx = boxes.indexOf(cb);
      if (e.shiftKey && lastClickedIdx !== null && idx !== -1) {
        const [lo, hi] = idx < lastClickedIdx ? [idx, lastClickedIdx] : [lastClickedIdx, idx];
        const targetState = cb.checked;
        for (let i = lo; i <= hi; i++) setSelected(boxes[i], targetState);
      } else {
        setSelected(cb, cb.checked);
      }
      lastClickedIdx = idx;
      updateBar();
    });

    // Drag-paint across the checkbox column -- pointermove is document-
    // level (a fast drag can outrun the table's own bounds for a frame),
    // but every target is re-checked against `table.contains(cb)` so it
    // can never paint another instance's rows.
    let painting = false;
    let paintValue = true;
    table.addEventListener("pointerdown", (e) => {
      const cb = e.target.closest && e.target.closest(".row-select");
      if (!cb) return;
      painting = true;
      paintValue = !cb.checked;
      setSelected(cb, paintValue);
      lastClickedIdx = checkboxes().indexOf(cb);
      updateBar();
    });
    document.addEventListener("pointermove", (e) => {
      if (!painting) return;
      const el = document.elementFromPoint(e.clientX, e.clientY);
      const cb = el && el.closest && el.closest(".row-select");
      if (cb && table.contains(cb) && cb.checked !== paintValue) {
        setSelected(cb, paintValue);
        updateBar();
      }
    });
    document.addEventListener("pointerup", () => {
      painting = false;
    });

    if (cfg.clearId) {
      document.getElementById(cfg.clearId)?.addEventListener("click", () => {
        checkboxes().forEach((cb) => setSelected(cb, false));
        lastClickedIdx = null;
        updateBar();
      });
    }

    if (cfg.deleteButtonId && cfg.deleteUrl) {
      document.getElementById(cfg.deleteButtonId)?.addEventListener("click", () => {
        const count = selected.size;
        if (!count) return;
        const label = cfg.itemLabel || "item";
        const message = cfg.confirmMessage
          ? cfg.confirmMessage(count)
          : `Delete ${count} selected ${label}${count === 1 ? "" : "s"}? This cannot be undone.`;
        window.ccConfirmSheet({
          anchor: document.getElementById(cfg.deleteButtonId),
          message: message,
          onConfirm: async () => {
            const uids = Array.from(selected);
            try {
              const resp = await fetch(cfg.deleteUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ uids }),
              });
              if (!resp.ok) throw new Error("bulk delete failed");
              window.ccToast({ title: "Deleted", message: `${uids.length} ${label}${uids.length === 1 ? "" : "s"}` });
              window.location.reload();
            } catch (err) {
              window.ccToast({ message: `Could not update the selected ${label}s.`, variant: "error" });
            }
          },
        });
      });
    }
  }

  window.CCBulkSelect = { init };
})();
