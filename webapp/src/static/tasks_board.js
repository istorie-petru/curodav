// Kanban drag-and-drop (templates/project_detail.html's `#kanban-board` --
// originally templates/tasks_board.html, a standalone global Tasks Kanban
// page deleted in the 2026-08-28 rework; this file was left orphaned,
// included nowhere, until project_detail.html's own later Kanban
// reimplementation picked the same `.kanban-*` markup/CSS back up.
// Re-wired here, unchanged, 2026-09-10 (audit-fixes-2.1.md direct bug
// report: "The kanban board for tasks doesn't allow for tasks to be drag
// and dropped") -- project_detail.html's markup already matched this
// file's selectors exactly (`#kanban-board`, `.kanban-column[data-status]`,
// `.kanban-cards[data-status]`, `.kanban-card[data-uid]`), so the only
// missing piece was the `<script>` include itself.) Pointer Events rather
// than the native HTML5 Drag and Drop API this used to use.
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
//
// 2026-09-13 (direct request, "easier drag and drop -- drag a card from any
// point, drop anywhere in the column, even on its header"): dragging from
// any point on the card was already true -- pointerdown below is bound to
// the whole `.kanban-card`, not a handle -- so the only real gap was the
// drop side. `columnAtPoint` used to resolve `.closest(".kanban-cards")`,
// and `.kanban-column-head` is a SIBLING of `.kanban-cards` (not inside
// it, see project_detail.html's markup) -- so a pointer over the header
// resolved to nothing and a drop there was a silent no-op. Now resolves
// `.closest(".kanban-column")` instead (covers the header too), and
// `endDrag` looks up that column's own `.kanban-cards` child as the actual
// append target -- `.kanban-column` itself also wraps the header, so
// appending straight into it would put the card outside the card list.
//
// 2026-09-13 (direct request, "anywhere I click kanban-card to be able to
// drag and drop it, also a double click anywhere on kanban-card should open
// it, keep the click title to open modal window"): drag-from-anywhere was
// already true (see the 09-10 note above -- pointerdown is bound to the
// whole card, not a handle). What was missing was open-from-anywhere on
// DOUBLE click while leaving the single click on `.kanban-card-title` alone.
// Rather than duplicating modal.js's open logic, dblclick here just
// re-dispatches a plain "click" at the card's own title link -- that bubbles
// to document and modal.js's existing `[data-modal]` delegated listener
// picks it up exactly as if the title had been clicked directly. Skipped
// when the dblclick itself landed on `[data-modal]` (the title) since the
// browser already delivered two real clicks there, each already opening the
// modal on its own; re-dispatching a third would just reopen it.

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
      const fromCards = card.closest(".kanban-cards");
      const column = hoverColumn; // .kanban-column -- may have been dropped on its header
      const toCards = column.querySelector(".kanban-cards");
      const newStatus = column.dataset.status;
      const uid = card.dataset.uid;

      if (toCards && fromCards !== toCards) {
        const emptyEl = toCards.querySelector(".kanban-empty");
        if (emptyEl) emptyEl.remove();
        toCards.appendChild(card); // always append into the column's card list, even when dropped on its header
        updateCounts();
        if (fromCards && !fromCards.querySelector(".kanban-card")) {
          const empty = document.createElement("div");
          empty.className = "kanban-empty";
          empty.textContent = "No tasks";
          fromCards.appendChild(empty);
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
