// Inline editing for the Tasks table view (templates/tasks_list.html) --
// status is a `.multiselect` radio-checkbox dropdown styled to look like a
// colored pill trigger (pill-select-trigger, see style.css; 2026-08-29,
// STATE.md backlog item 9 -- was a native <select> before that), labels is
// a `.multiselect` checkbox dropdown over the row's own tag pills (new the
// same slice -- previously read-only), due date is the shared themed date
// picker (datetime_picker.js, date mode) whose Clear/day-pick fires a
// `change` on the same hidden input contract this file listens for, and
// title is a double-click-to-edit cell (static/inline_edit.js).
// (Importance/Urgency used to be inline-editable
// pill-selects too -- side work, post-1.1, removed them: both are purely
// computed now, rendered as read-only .pill-static spans instead, see
// _task_row.html.) Changing any of them fires a single-field
// PATCH-ish call to POST /tasks/{uid}/update-field (routers/tasks.py)
// instead of a full form submit, so editing a row never re-navigates the
// page or loses scroll position -- only the edited cell's own pill color
// (or, for Labels, its own pill list) updates in place; everything else on
// the page is left alone.
//
// Deliberately does NOT reload the page on success (unlike modal.js's
// create/edit forms) -- a full reload after every dropdown change would
// make the table feel like a page of static links rather than an editable
// grid. It only reloads if the request actually fails, so the row falls
// back to whatever's on the server rather than silently drifting from it.
//
// async-CRUD (features/async-crud.md): all interaction here is delegated
// at the document level against #tasks-body rather than bound to the rows
// present at load, because a mutation-triggered cc-entity-changed event
// causes ccApi.refreshRegion() to swap the whole #tasks-body in place --
// delegated listeners keep working across the swap, and the bulk-selection
// state is reconciled to the fresh rows. The page's one listener for task
// changes lives here too.
//
// Two separate `<table>`s live inside #tasks-body (2026-08-29, STATE.md
// backlog item 9 follow-up: "habits should be a separate table at the end
// of the normal tasks table, with its own header row") -- `#task-table`
// (Project/Unassigned/Completed) and `#habits-table` (the Habits group,
// _habit_row.html), each with its own <thead> since the two row shapes
// don't share every column. Bulk-select and the delegated inline-edit
// listeners below are scoped to `#tasks-body` as a whole, not either table
// specifically, so a selection (and the shared bulk-actions-bar) can span
// both -- exactly the "Habits rows join the same #task-table selection"
// contract STATE.md backlog item 1 already established, just against a
// wrapper that now contains two tables instead of one.
//
// A caveat shared by the Status/Labels dropdowns: static/app.js's generic
// `.multiselect` handling portals an open panel out to #multiselect-portal,
// so a checkbox/radio inside it is no longer a DOM descendant of its
// `.task-status-select`/`.task-labels-select` wrapper while open -- this
// file locates the *trigger* (which never moves) by the row's own `data-
// uid` via `currentBody().querySelector(...)` instead of `closest()`
// from the changed input, same reasoning static/app.js's own `wrapperFor`
// helper documents.

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

  async function updateField(uid, field, value) {
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

  // Same contract as updateField above, but for a standalone Habit
  // *entity* row (kind="entity", _habit_row.html) -- that uid lives in the
  // `habits` table, not `tasks`, so it needs routers/habits.py's own
  // update-field endpoint instead. A habit-labeled *task* row (kind="task")
  // still goes through updateField/`/tasks/...` like any other task.
  async function updateHabitField(uid, field, value) {
    try {
      const resp = await fetch(`/habits/${uid}/update-field`, {
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

  // Inline status-pill / labels / due-date / title changes -- delegated so
  // they survive a region swap. These stay optimistic with NO region
  // refresh (the design's explicit choice): a swap after every dropdown
  // change would lose the table's scroll/focus for no benefit.
  document.addEventListener("change", (e) => {
    const target = e.target;
    if (!target || !target.matches) return;
    if (target.matches("#tasks-body input.task-status-radio")) {
      const uid = target.dataset.uid;
      const color = target.dataset.color || "gray";
      const trigger = currentBody().querySelector('.task-status-select[data-uid="' + uid + '"] .pill-select-trigger');
      // Optimistic: repaint the pill color/text immediately, don't wait on
      // the network round-trip. (app.js's own `change` listener already
      // updates the trigger's `.ms-summary` text and closes the panel --
      // single-select mode -- this only owns the color class app.js
      // doesn't know about.)
      if (trigger) trigger.className = "multiselect-trigger pill-select-trigger pill-" + color;
      updateField(uid, target.dataset.field, target.value);
    } else if (target.matches("#tasks-body input.task-label-checkbox")) {
      const uid = target.dataset.uid;
      const panel = target.closest(".multiselect-panel");
      const checked = panel
        ? Array.from(panel.querySelectorAll(".task-label-checkbox:checked")).map((cb) => cb.value)
        : [];
      const trigger = currentBody().querySelector('.task-labels-select[data-uid="' + uid + '"] .cell-tags');
      if (trigger) {
        trigger.innerHTML = checked.length
          ? checked.map((name) => '<span class="cell-tag tag-blue">' + escapeHtml(name) + "</span>").join("")
          : '<span class="ms-summary text-muted">No labels</span>';
      }
      updateField(uid, "tags", checked);
    } else if (target.matches("#tasks-body input.inline-date")) {
      updateField(target.dataset.uid, target.dataset.field, target.value);
    }
  });

  // Title double-click-to-edit (static/inline_edit.js) has no wrapping
  // `<form>` to post through -- it dispatches this generic commit event
  // instead (see that file's own comment on why), which this table is the
  // one page-level owner of persisting via the same update-field endpoint
  // every other inline edit here uses. Works for both tables: a plain task
  // row's title (`#task-table`) and, since STATE.md backlog item 9's
  // follow-up ("support inline editing for habit title too"), a Habits-
  // group row's title (`#habits-table`) -- `cell.dataset.kind` (carried by
  // both row kinds' title cell, mirroring the row-select checkbox's own
  // `data-kind`) is what decides which endpoint owns the uid.
  document.addEventListener("cc-inline-edit-commit", (e) => {
    const cell = e.target;
    if (!cell || !cell.matches || !cell.matches("#tasks-body [data-inline-edit]")) return;
    const uid = cell.dataset.uid;
    const field = e.detail && e.detail.field;
    if (!uid || !field) return;
    if (cell.dataset.kind === "entity") {
      updateHabitField(uid, field, e.detail.value);
    } else {
      updateField(uid, field, e.detail.value);
    }
  });

  // Small HTML-escape for the label pills' optimistic rebuild above --
  // tag names come from the row's own known `tag_names` list (server-
  // rendered checkbox values), not free-typed user input, but this is
  // cheap insurance against a label name containing HTML-significant
  // characters rendering as markup instead of text.
  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

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
  let lastClickedIdx = null;

  function checkboxRow(cb) {
    return cb.closest("tr");
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
    } else {
      bar.style.display = "none";
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

  // Row-select checkbox clicks -- delegated (document) so they survive a
  // region swap; the checkbox list is re-queried per interaction so
  // shift-click range selection indexes the live rows.
  document.addEventListener("click", (e) => {
    const cb = e.target.closest && e.target.closest("#tasks-body .row-select");
    if (!cb) return;
    const checkboxes = allCheckboxes();
    const idx = checkboxes.indexOf(cb);
    if (e.shiftKey && lastClickedIdx !== null && idx !== -1) {
      const [lo, hi] = idx < lastClickedIdx ? [idx, lastClickedIdx] : [lastClickedIdx, idx];
      const targetState = cb.checked;
      for (let i = lo; i <= hi; i++) setSelected(checkboxes[i], targetState);
    } else {
      setSelected(cb, cb.checked);
    }
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

  // 2026-08-29 (STATE.md backlog item 1): a selected row may be a plain
  // task OR a Habits-group row (_habit_row.html's checkbox now carries
  // `data-kind`, "task" for a habit-labeled task, "entity" for a
  // standalone Habit -- see routers/tasks.py's _habit_group_items). Only
  // "delete" needs to know the difference -- status/tag bulk actions stay
  // task-uid-only (bulkPost's plain `Array.from(selected)`), harmlessly
  // no-op-ing on any habit-entity uid mixed in (db.get_task returns None
  // for it, same "skip unknown uid" behavior every bulk_action branch
  // already has).
  function selectedByKind() {
    const taskUids = [];
    const habitUids = [];
    allCheckboxes().forEach((cb) => {
      if (!selected.has(cb.dataset.uid)) return;
      (cb.dataset.kind === "entity" ? habitUids : taskUids).push(cb.dataset.uid);
    });
    return { taskUids, habitUids };
  }

  document.getElementById("bulk-delete")?.addEventListener("click", () => {
    const count = selected.size;
    if (!count) return;
    window.ccConfirmSheet({
      anchor: document.getElementById("bulk-delete"),
      message: `Delete ${count} selected item${count === 1 ? "" : "s"}? This cannot be undone.`,
      onConfirm: async () => {
        try {
          const { taskUids, habitUids } = selectedByKind();
          const resp = await fetch("/tasks/bulk", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "delete", uids: taskUids, habit_uids: habitUids }),
          });
          if (!resp.ok) throw new Error("bulk delete failed");
          const allUids = taskUids.concat(habitUids);
          allUids.forEach((uid) => {
            const row = currentBody().querySelector(`tr[data-uid="${uid}"]`);
            if (row) row.remove();
          });
          selected.clear();
          updateBar();
          window.ccToast({ title: "Deleted", message: `${allUids.length} item${allUids.length === 1 ? "" : "s"}` });
          dispatchTaskChange("delete");
        } catch (err) {
          window.ccToast({ message: "Could not delete the selected items.", variant: "error" });
        }
      },
    });
  });

  document.getElementById("bulk-status-select")?.addEventListener("change", async (e) => {
    const status = e.target.value;
    if (!status) return;
    try {
      await bulkPost("status", { status });
      window.ccToast({ title: "Status updated", message: "Reloading to show the new sort order..." });
      dispatchTaskChange("status");
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
      window.ccToast({ title: "Moved", message: "Reloading..." });
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
        window.ccToast({ title: `Label${tags.length === 1 ? "" : "s"} ${mode === "add" ? "added" : "removed"}`, message: tags.join(", ") });
        dispatchTaskChange("tag");
      })
      .catch(() => window.ccToast({ message: "Could not update labels for the selected tasks.", variant: "error" }));
  }
  document.getElementById("bulk-tag-add")?.addEventListener("click", () => bulkTag("add"));
  document.getElementById("bulk-tag-remove")?.addEventListener("click", () => bulkTag("remove"));

  // ------------------------------------------------------------------ //
  // The page's one listener for task changes (async-CRUD design §5) --
  // every task mutation surface (modal create/edit, row delete, bulk
  // actions, command palette) dispatches cc-entity-changed; this refreshes
  // the #tasks-body region from the server. Falls back to a full reload if
  // the fragment fetch itself fails after the mutation already succeeded.
  //
  // Also claims "habit" changes (2026-08-28 fix): the Habits group renders
  // as part of this same #tasks-body region (`_tasks_body.html`'s
  // `grp.kind == 'habits'` block, since /habits was retired the same day in
  // favor of "the Tasks table's Habits group, this form's real home now" --
  // see plans/STATE.md). habit_form.html's edit/create form still dispatches
  // `data-cc-change="habit"` (habits.js's own listener, unchanged, still
  // covers /habits/{uid}'s standalone detail page), but nothing on the Tasks
  // page ever claimed that type, so modal.js's dispatchChange() always came
  // back unclaimed here and fell back to a full `window.location.reload()`
  // -- reported directly ("editing habits force a page refresh"). Reusing
  // the exact same table-region refresh as an ordinary task edit fixes it
  // the same way.
  // ------------------------------------------------------------------ //
  document.addEventListener("cc-entity-changed", (e) => {
    const detail = e.detail || {};
    if (detail.type !== "task" && detail.type !== "habit") return;
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
