// Inline editing for the Tasks table view (templates/tasks_list.html) --
// status renders as a native <select> element styled to look like a
// colored pill (pill-select, see style.css), due date as a plain
// <input type="date">. (Importance/Urgency used to be inline-editable
// pill-selects too -- side work, post-1.1, removed them: both are purely
// computed now, rendered as read-only .pill-static spans instead, see
// _task_row.html.) Changing any of them fires a single-field
// PATCH-ish call to POST /tasks/{uid}/update-field (routers/tasks.py)
// instead of a full form submit, so editing a row never re-navigates the
// page or loses scroll position -- only the edited cell's own pill color
// updates in place; everything else on the page is left alone.
//
// Deliberately does NOT reload the page on success (unlike modal.js's
// create/edit forms) -- a full reload after every dropdown change would
// make the table feel like a page of static links rather than an editable
// grid. It only reloads if the request actually fails, so the row falls
// back to whatever's on the server rather than silently drifting from it.

(function () {
  const table = document.getElementById("task-table");
  if (!table) return;

  async function updateField(uid, field, value, el) {
    try {
      const resp = await fetch(`/tasks/${uid}/update-field`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field, value }),
      });
      if (!resp.ok) throw new Error("update failed");
      return true;
    } catch (err) {
      window.ccToast({ message: "Could not save that change. Reloading...", variant: "error", duration: 1400 });
      setTimeout(() => window.location.reload(), 1200);
      return false;
    }
  }

  table.querySelectorAll("select.pill-select").forEach((select) => {
    select.addEventListener("change", async () => {
      const uid = select.dataset.uid;
      const field = select.dataset.field;
      const opt = select.options[select.selectedIndex];
      const color = opt.dataset.color || "gray";
      // Optimistic: repaint the pill color immediately, don't wait on the
      // network round-trip -- the field is a single native <select>, so
      // there's no separate "editor" to close first the way a Qt
      // QComboBox-in-a-delegate needs.
      select.className = "pill-select pill-" + color;
      await updateField(uid, field, opt.value, select);
    });
  });

  table.querySelectorAll("input.inline-date").forEach((input) => {
    input.addEventListener("change", async () => {
      await updateField(input.dataset.uid, input.dataset.field, input.value, input);
    });
  });

  // ------------------------------------------------------------------ //
  // Bulk select + bulk actions, 2026-08-01 -- see
  // plans/webapp-action-pipelines-audit.md's "no bulk select/bulk action
  // anywhere in Tasks" finding. Two ways to build a selection, both
  // standard spreadsheet/file-manager conventions:
  //   - Shift-click a checkbox: selects every row between the last
  //     checkbox you clicked (plain, no shift) and this one.
  //   - Press-and-drag across the checkbox column: "paints" every row
  //     the pointer crosses to match whatever the first row's new state
  //     is (deselecting if it started checked, selecting otherwise) --
  //     confined to the checkbox column specifically, not the whole row,
  //     so it can't be triggered by an incidental drag over a pill/date
  //     cell that's actually a click on those controls.
  // ------------------------------------------------------------------ //

  const selected = new Set();
  const bar = document.getElementById("bulk-actions-bar");
  const countEl = document.getElementById("bulk-count");
  const checkboxes = Array.from(table.querySelectorAll(".row-select"));
  let lastClickedIdx = null;

  function checkboxRow(cb) {
    return cb.closest("tr");
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
    } else {
      bar.style.display = "none";
    }
  }

  checkboxes.forEach((cb, idx) => {
    cb.addEventListener("click", (e) => {
      if (e.shiftKey && lastClickedIdx !== null) {
        const [lo, hi] = idx < lastClickedIdx ? [idx, lastClickedIdx] : [lastClickedIdx, idx];
        const targetState = cb.checked;
        for (let i = lo; i <= hi; i++) setSelected(checkboxes[i], targetState);
      } else {
        setSelected(cb, cb.checked);
      }
      lastClickedIdx = idx;
      updateBar();
    });
  });

  // Drag-select across the checkbox column -- Pointer Events (mouse +
  // touch), confined to .row-select elements via elementFromPoint so a
  // drag that leaves the checkbox column (e.g. onto a pill/date cell)
  // doesn't paint those rows just because the pointer passed over them.
  let painting = false;
  let paintValue = true;

  table.addEventListener("pointerdown", (e) => {
    const cb = e.target.closest(".row-select");
    if (!cb) return;
    painting = true;
    paintValue = !cb.checked;
    setSelected(cb, paintValue);
    lastClickedIdx = checkboxes.indexOf(cb);
    updateBar();
  });

  document.addEventListener("pointermove", (e) => {
    if (!painting) return;
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const cb = el && el.closest && el.closest(".row-select");
    if (cb && checkboxes.includes(cb) && cb.checked !== paintValue) {
      setSelected(cb, paintValue);
      updateBar();
    }
  });

  document.addEventListener("pointerup", () => {
    painting = false;
  });

  document.getElementById("bulk-clear")?.addEventListener("click", () => {
    checkboxes.forEach((cb) => setSelected(cb, false));
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

  document.getElementById("bulk-delete")?.addEventListener("click", () => {
    const count = selected.size;
    if (!count) return;
    window.ccConfirmSheet({
      anchor: document.getElementById("bulk-delete"),
      message: `Delete ${count} selected task${count === 1 ? "" : "s"}? This cannot be undone.`,
      onConfirm: async () => {
        try {
          const uids = await bulkPost("delete");
          uids.forEach((uid) => {
            const row = table.querySelector(`tr[data-uid="${uid}"]`);
            if (row) row.remove();
          });
          selected.clear();
          updateBar();
          window.ccToast({ message: `Deleted ${uids.length} task${uids.length === 1 ? "" : "s"}` });
        } catch (err) {
          window.ccToast({ message: "Could not delete the selected tasks.", variant: "error" });
        }
      },
    });
  });

  document.getElementById("bulk-status-select")?.addEventListener("change", async (e) => {
    const status = e.target.value;
    if (!status) return;
    try {
      await bulkPost("status", { status });
      window.ccToast({ message: "Status updated. Reloading to show the new sort order..." });
      window.location.reload();
    } catch (err) {
      window.ccToast({ message: "Could not update status for the selected tasks.", variant: "error" });
    } finally {
      e.target.value = "";
    }
  });

  document.getElementById("bulk-list-select")?.addEventListener("change", async (e) => {
    const listPath = e.target.value;
    if (!listPath) return;
    try {
      await bulkPost("move_list", { list_path: listPath });
      window.ccToast({ message: "Moved. Reloading..." });
      window.location.reload();
    } catch (err) {
      window.ccToast({ message: "Could not move the selected tasks.", variant: "error" });
    } finally {
      e.target.value = "";
    }
  });

  // Labels picker is now a chip multiselect (2026-08-07, modal-input-design
  // Phase B) instead of a typed-with-datalist text input -- reads whichever
  // "bulk_tag_names" checkboxes are ticked (there's no <form> wrapping
  // #bulk-tag-picker, so these are just plain checkboxes with a shared
  // name attribute, read directly rather than via FormData) and sends them
  // all through in one request. /tasks/bulk's "tag" action already looped
  // per-uid; it now also loops per-tag (see routers/tasks.py's bulk_action),
  // so Add/Remove's existing "apply this labels change to every selected
  // row" semantics are unchanged, just no longer limited to one label at a
  // time.
  function bulkTag(mode) {
    const tags = Array.from(document.querySelectorAll('#bulk-tag-picker input[name="bulk_tag_names"]:checked')).map((cb) => cb.value);
    if (!tags.length) return;
    bulkPost("tag", { tags, mode })
      .then(() => {
        window.ccToast({ message: `Label${tags.length === 1 ? "" : "s"} ${mode === "add" ? "added" : "removed"}. Reloading...` });
        window.location.reload();
      })
      .catch(() => window.ccToast({ message: "Could not update labels for the selected tasks.", variant: "error" }));
  }
  document.getElementById("bulk-tag-add")?.addEventListener("click", () => bulkTag("add"));
  document.getElementById("bulk-tag-remove")?.addEventListener("click", () => bulkTag("remove"));
})();
