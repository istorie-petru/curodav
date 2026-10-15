(function () {
  const instances = {};

  function init(cfg) {
    const table = document.getElementById(cfg.tableId);
    const bar = document.getElementById(cfg.barId);
    const countEl = cfg.countId ? document.getElementById(cfg.countId) : null;
    const actionsSlot = bar ? bar.closest(".page-header-narrow-actions") : null;
    if (instances[cfg.tableId]) {
      instances[cfg.tableId]();
      delete instances[cfg.tableId];
    }
    if (!table || !bar) return;
    const rowSelector = cfg.rowSelector || "tr";

    const selected = new Set();
    let lastClickedIdx = null;

    function checkboxes() {
      return Array.from(table.querySelectorAll(".row-select"));
    }
    function rowFor(cb) {
      return cb.closest(rowSelector);
    }

    checkboxes().forEach((cb) => {
      cb.checked = false;
      const row = rowFor(cb);
      if (row) row.classList.remove("is-selected");
    });
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
        if (actionsSlot) actionsSlot.classList.add("has-visible-bulk-bar");
      } else {
        bar.style.display = "none";
        if (actionsSlot) actionsSlot.classList.remove("has-visible-bulk-bar");
        if (countEl) countEl.textContent = "";
      }
    }

    function onTableClick(e) {
      const cb = e.target.closest && e.target.closest(".row-select");
      if (!cb) return;
      e.preventDefault();
      const boxes = checkboxes();
      const idx = boxes.indexOf(cb);
      if (e.shiftKey && lastClickedIdx !== null && idx !== -1) {
        const [lo, hi] = idx < lastClickedIdx ? [idx, lastClickedIdx] : [lastClickedIdx, idx];
        const targetState = cb.checked;
        for (let i = lo; i <= hi; i++) setSelected(boxes[i], targetState);
      }
      // else: pointerdown below already fully applied the plain-click
      // toggle to `cb` itself (state + `.is-selected` + the Set) -- no
      // second setSelected(cb, cb.checked) needed here, and reapplying it
      // would just be redundant, not harmful, but there's nothing left to
      // do for the single-checkbox case.
      lastClickedIdx = idx;
      updateBar();
    }
    table.addEventListener("click", onTableClick);

    // Drag-paint across the checkbox column -- pointermove is document-
    // level (a fast drag can outrun the table's own bounds for a frame),
    // but every target is re-checked against `table.contains(cb)` so it
    // can never paint another instance's rows.
    let painting = false;
    let paintValue = true;
    function onTablePointerDown(e) {
      const cb = e.target.closest && e.target.closest(".row-select");
      if (!cb) return;
      painting = true;
      paintValue = !cb.checked;
      setSelected(cb, paintValue);
      lastClickedIdx = checkboxes().indexOf(cb);
      updateBar();
    }
    table.addEventListener("pointerdown", onTablePointerDown);
    // Named (not inline) so teardown() below can remove exactly these two
    // document-level listeners on re-init, instead of leaking one more
    // pair of orphaned listeners (closed over the previous, now-detached
    // `table`) every time this tableId's container gets swapped out.
    function onDocPointerMove(e) {
      if (!painting) return;
      const el = document.elementFromPoint(e.clientX, e.clientY);
      const cb = el && el.closest && el.closest(".row-select");
      if (cb && table.contains(cb) && cb.checked !== paintValue) {
        setSelected(cb, paintValue);
        updateBar();
      }
    }
    function onDocPointerUp() {
      painting = false;
    }
    document.addEventListener("pointermove", onDocPointerMove);
    document.addEventListener("pointerup", onDocPointerUp);
    // The bar's buttons outlive a region swap, so a re-init must unbind the
    // previous instance's click handlers or each one would fire twice.
    const unbinders = [];
    function bindButton(id, handler) {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("click", handler);
      unbinders.push(() => el.removeEventListener("click", handler));
    }
    instances[cfg.tableId] = function teardown() {
      // The table itself can outlive a re-init (Taxonomy & Data swaps only its rows), so its own listeners go too.
      table.removeEventListener("click", onTableClick);
      table.removeEventListener("pointerdown", onTablePointerDown);
      document.removeEventListener("pointermove", onDocPointerMove);
      document.removeEventListener("pointerup", onDocPointerUp);
      unbinders.forEach((off) => off());
    };
    updateBar();

    if (cfg.clearId) {
      bindButton(cfg.clearId, () => {
        checkboxes().forEach((cb) => setSelected(cb, false));
        lastClickedIdx = null;
        updateBar();
      });
    }

    if (cfg.mergeButtonId && cfg.mergeModalUrl) {
      bindButton(cfg.mergeButtonId, () => {
        const label = cfg.itemLabel || "item";
        if (selected.size < 2) {
          window.ccToast({ message: `Select at least 2 ${label}s to merge.`, variant: "error" });
          return;
        }
        const uids = Array.from(selected);
        const url = cfg.mergeModalUrl + "?uids=" + encodeURIComponent(uids.join(","));
        if (window.CCModal) window.CCModal.open(url);
      });
    }

    if (cfg.editButtonId && cfg.editModalUrl) {
      bindButton(cfg.editButtonId, () => {
        if (!selected.size) return;
        const url = cfg.editModalUrl + "?uids=" + encodeURIComponent(Array.from(selected).join(","));
        if (window.CCModal) window.CCModal.open(url);
      });
    }

    if (cfg.deleteButtonId && cfg.deleteUrl) {
      bindButton(cfg.deleteButtonId, () => {
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
              const claimed =
                cfg.changeType && window.ccApi && window.ccApi.dispatchChange
                  ? window.ccApi.dispatchChange({ type: cfg.changeType, action: "delete" })
                  : false;
              if (!claimed) window.location.reload();
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
