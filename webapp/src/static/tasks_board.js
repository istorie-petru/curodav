
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
    return el ? el.closest(".kanban-column") : null;
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

  async function persistMove(uid, newStatus, card, fromCards) {
    try {
      const resp = await fetch(`/tasks/${uid}/update-field`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field: "status", value: newStatus }),
      });
      if (!resp.ok) throw new Error("move failed");
    } catch (err) {
      window.ccToast({ message: "Could not save that move", variant: "error" });
      if (fromCards) {
        const empty = fromCards.querySelector(".empty-state");
        if (empty) empty.remove();
        fromCards.appendChild(card);
        updateCounts();
        board.querySelectorAll(".kanban-cards").forEach((cards) => {
          if (!cards.querySelector(".kanban-card") && !cards.querySelector(".empty-state")) {
            cards.appendChild(window.ccEmptyState("No tasks"));
          }
        });
      }
    }
  }

  function endDrag(card, drop) {
    card.classList.remove("dragging");
    card.style.transform = "";
    card.releasePointerCapture && card.hasPointerCapture && card.releasePointerCapture(dragPointerId);
    if (hoverColumn) hoverColumn.classList.remove("drop-hover");

    if (drop && hoverColumn) {
      const fromCards = card.closest(".kanban-cards");
      const column = hoverColumn; // .kanban-column -- may have been dropped on its header
      const toCards = column.querySelector(".kanban-cards");
      const newStatus = column.dataset.status;
      const uid = card.dataset.uid;

      if (toCards && fromCards !== toCards) {
        const emptyEl = toCards.querySelector(".empty-state");
        if (emptyEl) emptyEl.remove();
        toCards.appendChild(card); // always append into the column's card list, even when dropped on its header
        updateCounts();
        if (fromCards && !fromCards.querySelector(".kanban-card")) {
          fromCards.appendChild(window.ccEmptyState("No tasks"));
        }
        persistMove(uid, newStatus, card, fromCards);
      }
    }

    dragCard = null;
    dragging = false;
    hoverColumn = null;
  }

  let dragPointerId = null;

  board.querySelectorAll(".kanban-card").forEach((card) => {
    card.style.touchAction = "pan-y"; // let vertical scroll through until a drag actually starts

    // Backstop for the banner `<img>`/title `<a>` (draggable="false" in
    // project_detail.html already covers this) -- if either one is ever
    // reached without that attribute (a stray copy-paste of the card
    // markup, say), this stops the browser's native HTML5 drag from
    // hijacking the press before pointerdown's own drag logic ever sees it.
    card.addEventListener("dragstart", (e) => e.preventDefault());

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

    card.addEventListener("dblclick", (e) => {
      if (e.target.closest("[data-modal]")) return; // title's own two real clicks already opened it
      const link = card.querySelector(".kanban-card-title");
      if (!link) return;
      e.preventDefault();
      link.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });
  });
})();
