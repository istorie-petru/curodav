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
//   rowSelector      -- (2026-09-14, contacts_list.html) CSS selector for
//                       "the whole selectable row" a checkbox belongs to,
//                       toggled `.is-selected` for styling -- default "tr"
//                       (every existing caller is a real `<table>`).
//                       Contacts' card-list rows aren't `<tr>`s, so that
//                       caller passes ".contact-row-wrap" (the div wrapping
//                       each checkbox + the row's own `<a>`, see
//                       _contacts_body.html's own comment on why the row
//                       needed restructuring for this).
// })
//
// Re-init safety (2026-09-14): contacts_list.html calls init() again after
// every async-CRUD region swap of its container (a fresh server-rendered
// fragment, so the previous `table`/`bar` element references + their
// document-level pointermove/pointerup drag-paint listeners are orphaned
// otherwise -- no existing caller re-initialized on the same page before
// this, so nothing tore old listeners down). `instances` tracks one
// teardown function per `tableId`; a second init() for the same id runs
// the previous instance's teardown first so orphaned listeners don't pile
// up release after release.
(function () {
  const instances = {};

  function init(cfg) {
    const table = document.getElementById(cfg.tableId);
    const bar = document.getElementById(cfg.barId);
    const countEl = cfg.countId ? document.getElementById(cfg.countId) : null;
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
    //
    // 2026-09-15 bugfix (direct report: "clicking works, but it
    // immediately deselects -- happens on any page", i.e. every
    // CCBulkSelect caller -- Holidays/Labels/Time Blocks/Contacts alike --
    // not just Contacts; this handler and the pointerdown one below are
    // unchanged from the original 2026-08-29 implementation, so this was a
    // pre-existing bug surfaced by testing the new Contacts caller, not
    // something the Contacts change introduced). Root cause: the
    // pointerdown handler below already calls `setSelected(cb, paintValue)`
    // -- flipping `cb.checked` itself -- so that a real press-and-drag
    // paints the row the drag *started* on, not just the ones the pointer
    // crosses afterward. But the browser doesn't know that already
    // happened: when the matching `click` fires right after (mouseup on
    // the same element, the plain-click case, not a drag), its own native
    // activation behavior toggles `checked` a SECOND time -- right back to
    // whatever it was *before* the pointerdown. Net effect on an ordinary,
    // no-drag click: the box visibly flips checked, then the trailing
    // native click flips it straight back to unchecked -- reads as "it
    // immediately deselects," and always did, for every table this module
    // has ever driven; a real multi-row drag just never exercised this
    // path (mouseup lands on a different element, so no `click` ever
    // fires on the origin checkbox to conflict with pointerdown's own
    // change). `e.preventDefault()` here blocks that native toggle -- a
    // checkbox's default click behavior can be canceled from a `click`
    // listener (not from `pointerdown`/`mousedown`, which was tried first
    // and confirmed via a real Chrome/Puppeteer click -- not just a
    // synthetic `.click()` call, which never exercises the native
    // pointerdown-then-click sequence at all -- that canceling pointerdown
    // does NOT suppress the later click's own default action). With the
    // native toggle suppressed, pointerdown's `setSelected` call is the
    // sole source of truth for `cb.checked` in both the plain-click and
    // drag cases, and this handler only needs to run the shift-range logic
    // off of whatever state pointerdown already established.
    table.addEventListener("click", (e) => {
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
    instances[cfg.tableId] = function teardown() {
      document.removeEventListener("pointermove", onDocPointerMove);
      document.removeEventListener("pointerup", onDocPointerUp);
    };

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
