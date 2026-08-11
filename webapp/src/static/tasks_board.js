// Kanban drag-and-drop (templates/tasks_board.html) -- Pointer Events
// rather than the native HTML5 Drag and Drop API this used to use.
//
// HTML5 DnD (`draggable`, `dragstart`/`dragover`/`drop`) never fires on
// touch at all in iOS/Android browsers -- on a phone, every card here was
// simply stuck, full stop, no matter how the rest of the page adapted to
// mobile. Pointer Events unify mouse/touch/pen behind one API and can
// reproduce exactly the same coarse "which column is the card over right
// now" signal HTML5 DnD's dragover gave for free -- via elementFromPoint
// against each pointermove instead -- so this is a like-for-like swap in
// capability, not a reduced-functionality fallback for touch.
//
// A small movement threshold before a drag actually "starts" is what lets
// a plain tap still open the card's detail link -- without it, every tap
// would register as a zero-distance drag and the pointerup handler would
// have to guess whether to treat it as a click.
//
// On drop: move the card in the DOM immediately (optimistic), then persist
// via the same POST /tasks/{uid}/update-field endpoint the table view's
// inline status pill uses (field=status) -- one endpoint, two UIs. Reverts
// (reloads) only on a network/server failure, same failure handling as
// tasks_table.js.

(function () {
  const board = document.getElementById("kanban-board");
  if (!board) return;

  const DRAG_THRESHOLD = 6; // px of movement before a press becomes a drag, not a tap

  let dragCard = null;
  let startX = 0;
  let startY = 0;
  let dragging = false;
  let hoverColumn = null;

  function columnAtPoint(x, y) {
    dragCard.style.visibility = "hidden"; // don't let the dragged card itself be the hit result
    const el = document.elementFromPoint(x, y);
    dragCard.style.visibility = "";
    return el ? el.closest(".kanban-cards") : null;
  }

  function setHoverColumn(column) {
    if (hoverColumn === column) return;
    if (hoverColumn) hoverColumn.classList.remove("drop-hover");
    hoverColumn = column;
    if (hoverColumn) hoverColumn.classList.add("drop-hover");
  }

  function updateCounts() {
    board.querySelectorAll(".kanban-column").forEach((col) => {
      const count = col.querySelectorAll(".kanban-card").length;
      const countEl = col.querySelector(".kanban-count");
      if (countEl) countEl.textContent = String(count);
    });
  }

  async function persistMove(uid, newStatus) {
    try {
      const resp = await fetch(`/tasks/${uid}/update-field`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field: "status", value: newStatus }),
      });
      if (!resp.ok) throw new Error("move failed");
    } catch (err) {
      window.ccToast({ message: "Could not save that move. Reloading...", variant: "error", duration: 1400 });
      setTimeout(() => window.location.reload(), 1200);
    }
  }

  function endDrag(card, drop) {
    card.classList.remove("dragging");
    card.style.transform = "";
    card.releasePointerCapture && card.hasPointerCapture && card.releasePointerCapture(dragPointerId);
    if (hoverColumn) hoverColumn.classList.remove("drop-hover");

    if (drop && hoverColumn) {
      const fromColumn = card.closest(".kanban-cards");
      const column = hoverColumn;
      const newStatus = column.dataset.status;
      const uid = card.dataset.uid;

      if (fromColumn !== column) {
        const emptyEl = column.querySelector(".kanban-empty");
        if (emptyEl) emptyEl.remove();
        column.appendChild(card);
        updateCounts();
        if (fromColumn && !fromColumn.querySelector(".kanban-card")) {
          const empty = document.createElement("div");
          empty.className = "kanban-empty";
          empty.textContent = "No tasks";
          fromColumn.appendChild(empty);
        }
        persistMove(uid, newStatus);
      }
    }

    dragCard = null;
    dragging = false;
    hoverColumn = null;
  }

  let dragPointerId = null;

  board.querySelectorAll(".kanban-card").forEach((card) => {
    card.style.touchAction = "pan-y"; // let vertical scroll through until a drag actually starts

    card.addEventListener("pointerdown", (e) => {
      if (e.button !== undefined && e.button !== 0) return; // left-click / primary touch only
      dragCard = card;
      dragPointerId = e.pointerId;
      startX = e.clientX;
      startY = e.clientY;
      dragging = false;
    });

    card.addEventListener("pointermove", (e) => {
      if (!dragCard || dragCard !== card || e.pointerId !== dragPointerId) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;

      if (!dragging) {
        if (Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;
        dragging = true;
        card.classList.add("dragging");
        card.setPointerCapture(dragPointerId);
        card.style.touchAction = "none"; // now that a drag is confirmed, stop the page from also scrolling
      }

      card.style.transform = `translate(${dx}px, ${dy}px)`;
      setHoverColumn(columnAtPoint(e.clientX, e.clientY));
    });

    card.addEventListener("pointerup", (e) => {
      if (!dragCard || dragCard !== card || e.pointerId !== dragPointerId) return;
      const wasDragging = dragging;
      if (wasDragging) {
        // A real drag ending on top of the card's own title link would
        // otherwise also fire that link's click right after (same
        // "suppress the click that follows a completed drag" pattern
        // calendar.js/schedule_grid.js use for the time-grid) -- without
        // this, dropping a card could also pop its detail modal open.
        const suppressClick = (ce) => {
          ce.preventDefault();
          ce.stopPropagation();
        };
        card.addEventListener("click", suppressClick, { capture: true, once: true });
        setTimeout(() => card.removeEventListener("click", suppressClick, { capture: true }), 0);
      }
      endDrag(card, wasDragging);
      card.style.touchAction = "pan-y";
    });

    card.addEventListener("pointercancel", () => {
      if (dragCard !== card) return;
      endDrag(card, false);
      card.style.touchAction = "pan-y";
    });
  });
})();
