// Kanban status changes -- templates/project_detail.html.
//
// Click-based, not drag-and-drop, by direct choice when this page's Kanban
// board was scoped (2026-08-30): each card carries a plain `.pill-select`
// (a native <select> styled as a pill -- see _task_row.html's own comment
// on that being this app's pre-multiselect status control) rather than the
// pointer-drag interaction the old, retired global Kanban
// (static/tasks_board.js) used. Picking a new status POSTs through the
// same POST /tasks/{uid}/update-field endpoint (`field=status`) every
// other status control in this app already uses -- see that route's own
// docstring (routers/tasks.py::update_field), which names this file
// alongside tasks_table.js as its two callers. On success, the card moves
// to its new column in the DOM (optimistic-after-confirm, not
// optimistic-before -- a Kanban card moving instantly on select is fine,
// waiting for the POST first avoids the card appearing to "stick" in the
// wrong column if the save fails). Reverts (reloads) only on a network/
// server failure, same failure handling as tasks_table.js/tasks_board.js.

(function () {
  const board = document.getElementById("kanban-board");
  if (!board) return;

  let statusColors = {};
  try {
    statusColors = JSON.parse(board.dataset.statusColors || "{}");
  } catch (err) {
    statusColors = {};
  }

  function updateCounts() {
    board.querySelectorAll(".kanban-column").forEach((col) => {
      const count = col.querySelectorAll(".kanban-card").length;
      const countEl = col.querySelector(".kanban-count");
      if (countEl) countEl.textContent = String(count);
    });
  }

  function recolor(select, status) {
    Object.values(statusColors).forEach((color) => select.classList.remove("pill-" + color));
    const color = statusColors[status];
    if (color) select.classList.add("pill-" + color);
  }

  board.querySelectorAll(".kanban-status-select").forEach((select) => {
    select.addEventListener("change", async () => {
      const card = select.closest(".kanban-card");
      const uid = select.dataset.uid;
      const previousStatus = card.dataset.status;
      const newStatus = select.value;
      if (newStatus === previousStatus) return;

      try {
        const resp = await fetch(`/tasks/${uid}/update-field`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ field: "status", value: newStatus }),
        });
        if (!resp.ok) throw new Error("update failed");
      } catch (err) {
        select.value = previousStatus;
        window.ccToast({ message: "Could not save that change. Reloading...", variant: "error", duration: 1400 });
        setTimeout(() => window.location.reload(), 1200);
        return;
      }

      const fromColumn = card.closest(".kanban-cards");
      const toColumn = board.querySelector('.kanban-cards[data-status="' + newStatus + '"]');
      card.dataset.status = newStatus;
      recolor(select, newStatus);

      if (toColumn && toColumn !== fromColumn) {
        const emptyEl = toColumn.querySelector(".kanban-empty");
        if (emptyEl) emptyEl.remove();
        toColumn.appendChild(card);
        updateCounts();
        if (fromColumn && !fromColumn.querySelector(".kanban-card")) {
          const empty = document.createElement("div");
          empty.className = "kanban-empty";
          empty.textContent = "No tasks";
          fromColumn.appendChild(empty);
        }
      }
    });
  });
})();
