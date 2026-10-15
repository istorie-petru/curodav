
(function () {
  const initialBody = document.getElementById("tasks-body");
  if (!initialBody) return;

  function currentBody() {
    return document.getElementById("tasks-body");
  }

  function regionUrl() {
    // Forward the page's own query string so the refreshed region honors
    // the active filters/sort/page (design §5).
    return "/tasks/regions?region=table" + (window.location.search || "");
  }

  // The status dropdown is the one inline editor: the pill repaints at once and the change is saved.
  async function saveStatus(uid, value) {
    try {
      const resp = await fetch(`/tasks/${uid}/update-field`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field: "status", value }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.error || "Could not save that change");
      }
    } catch (err) {
      window.ccToast({ message: err.message || "Could not save that change", variant: "error" });
      window.ccApi.refreshRegion(regionUrl(), "tasks-body").catch(() => {});
    }
  }

  document.addEventListener("change", (e) => {
    const target = e.target;
    if (!target || !target.matches || !target.matches("input.task-status-radio")) return;
    const trigger = currentBody().querySelector('.task-status-select[data-uid="' + target.dataset.uid + '"] .pill-select-trigger');
    if (trigger) trigger.className = "multiselect-trigger pill-select-trigger pill-" + (target.dataset.color || "gray");
    saveStatus(target.dataset.uid, target.value);
  });

  const selected = new Set();
  const bar = document.getElementById("bulk-actions-bar");
  const countEl = document.getElementById("bulk-count");
  const actionsSlot = bar ? bar.closest(".page-header-narrow-actions") : null;
  let lastClickedIdx = null;

  function checkboxRow(cb) {
    return cb.closest(".task-row");
  }

  function allCheckboxes() {
    return Array.from(currentBody().querySelectorAll(".row-select"));
  }

  function setSelected(cb, on) {
    cb.checked = on;
    const row = checkboxRow(cb);
    const uid = cb.dataset.uid;
    if (on) {
      selected.add(uid);
      if (row) row.classList.add("is-selected");
    } else {
      selected.delete(uid);
      if (row) row.classList.remove("is-selected");
    }
  }

  function updateBar() {
    if (!bar) return;
    if (selected.size > 0) {
      bar.style.display = "flex";
      countEl.textContent = `${selected.size} selected`;
      if (actionsSlot) actionsSlot.classList.add("has-visible-bulk-bar");
    } else {
      bar.style.display = "none";
      if (actionsSlot) actionsSlot.classList.remove("has-visible-bulk-bar");
      if (countEl) countEl.textContent = "";
    }
  }

  // Selection lives by uid in `selected`; after a region swap the fresh
  // checkboxes start unchecked, so re-check any that were still selected
  // and drop uids that no longer exist (deleted / moved off the page).
  function reconcileAfterSwap() {
    const present = new Set(allCheckboxes().map((cb) => cb.dataset.uid));
    Array.from(selected).forEach((uid) => {
      if (!present.has(uid)) selected.delete(uid);
    });
    allCheckboxes().forEach((cb) => {
      const on = selected.has(cb.dataset.uid);
      cb.checked = on;
      const row = checkboxRow(cb);
      if (row) row.classList.toggle("is-selected", on);
    });
    updateBar();
  }

  reconcileAfterSwap();

  document.addEventListener("click", (e) => {
    const cb = e.target.closest && e.target.closest("#tasks-body .row-select");
    if (!cb) return;
    e.preventDefault();
    const checkboxes = allCheckboxes();
    const idx = checkboxes.indexOf(cb);
    if (e.shiftKey && lastClickedIdx !== null && idx !== -1) {
      const [lo, hi] = idx < lastClickedIdx ? [idx, lastClickedIdx] : [lastClickedIdx, idx];
      const targetState = cb.checked;
      for (let i = lo; i <= hi; i++) setSelected(checkboxes[i], targetState);
    }
    // else: pointerdown below already fully applied the plain-click toggle
    // to `cb` itself (state + `.is-selected` + the Set) -- nothing left to
    // do for the single-checkbox case.
    lastClickedIdx = idx;
    updateBar();
  });

  // Drag-select across the checkbox column -- Pointer Events (mouse +
  // touch), confined to .row-select elements via elementFromPoint so a
  // drag that leaves the checkbox column (e.g. onto a pill/date cell)
  // doesn't paint those rows just because the pointer passed over them.
  let painting = false;
  let paintValue = true;

  document.addEventListener("pointerdown", (e) => {
    const cb = e.target.closest && e.target.closest("#tasks-body .row-select");
    if (!cb) return;
    painting = true;
    paintValue = !cb.checked;
    setSelected(cb, paintValue);
    lastClickedIdx = allCheckboxes().indexOf(cb);
    updateBar();
  });

  document.addEventListener("pointermove", (e) => {
    if (!painting) return;
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const cb = el && el.closest && el.closest("#tasks-body .row-select");
    if (cb && currentBody().contains(cb) && cb.checked !== paintValue) {
      setSelected(cb, paintValue);
      updateBar();
    }
  });

  document.addEventListener("pointerup", () => {
    painting = false;
  });

  document.getElementById("bulk-clear")?.addEventListener("click", () => {
    allCheckboxes().forEach((cb) => setSelected(cb, false));
    lastClickedIdx = null;
    updateBar();
  });

  async function bulkPost(action, extra) {
    const uids = Array.from(selected);
    const resp = await fetch("/tasks/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ action, uids }, extra || {})),
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.error || "bulk action failed");
    }
    return uids;
  }

  // A completed bulk mutation dispatches the same cc-entity-changed event
  // every other task mutation uses, so the single listener below refreshes
  // #tasks-body and the divider counts / sort order / empty state catch up.
  function dispatchTaskChange(action) {
    window.ccApi.dispatchChange({ type: "task", action });
  }

  document.getElementById("bulk-edit")?.addEventListener("click", () => {
    if (!selected.size || !window.CCModal) return;
    window.CCModal.open("/tasks/bulk-edit-modal?uids=" + encodeURIComponent(Array.from(selected).join(",")));
  });

  document.getElementById("bulk-delete")?.addEventListener("click", () => {
    const count = selected.size;
    if (!count) return;
    window.ccConfirmSheet({
      anchor: document.getElementById("bulk-delete"),
      message: `Delete ${count} selected item${count === 1 ? "" : "s"}? This cannot be undone.`,
      onConfirm: async () => {
        try {
          const taskUids = Array.from(selected);
          const resp = await fetch("/tasks/bulk", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "delete", uids: taskUids }),
          });
          if (!resp.ok) throw new Error("bulk delete failed");
          taskUids.forEach((uid) => {
            const row = currentBody().querySelector(`.task-row[data-uid="${uid}"]`);
            if (row) row.remove();
          });
          selected.clear();
          updateBar();
          window.ccToast({ title: "Deleted", message: `${taskUids.length} item${taskUids.length === 1 ? "" : "s"}` });
          dispatchTaskChange("delete");
        } catch (err) {
          window.ccToast({ message: "Could not delete the selected items.", variant: "error" });
        }
      },
    });
  });


  document.getElementById("bulk-list-select")?.addEventListener("change", async (e) => {
    const listPath = e.target.value;
    if (!listPath) return;
    try {
      await bulkPost("move_list", { list_path: listPath });
      window.ccToast({ title: "Moved" });
      dispatchTaskChange("move_list");
    } catch (err) {
      window.ccToast({ message: "Could not move the selected tasks.", variant: "error" });
    } finally {
      e.target.value = "";
    }
  });


  // ------------------------------------------------------------------ //
  // The page's one listener for task changes (async-CRUD design §5) --
  // every task mutation surface (modal create/edit, row delete, bulk
  // actions, command palette) dispatches cc-entity-changed; this refreshes
  // the #tasks-body region from the server. Falls back to a full reload if
  // the fragment fetch itself fails after the mutation already succeeded.
  // ------------------------------------------------------------------ //
  document.addEventListener("cc-entity-changed", (e) => {
    const detail = e.detail || {};
    if (detail.type !== "task") return;
    // Claim the event only when the region is actually on this page --
    // otherwise (task/habit edited from a calendar/timeline modal) leave it
    // unclaimed so modal.js falls back to a reload rather than going stale.
    if (!document.getElementById("tasks-body")) return;
    detail.claimed = true;
    window.ccApi
      .refreshRegion(regionUrl(), "tasks-body")
      .catch(() => window.location.reload());
  });

  document.addEventListener("cc-region-swapped", (e) => {
    if (e.detail && e.detail.id === "tasks-body") reconcileAfterSwap();
  });
})();
