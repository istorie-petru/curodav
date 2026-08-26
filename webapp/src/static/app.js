// Minimal progressive enhancement -- every CRUD action works as a plain
// HTML form submit with no JS at all. This file adds: the Settings >
// Appearance theme control and a delete confirmation.
//
// The theme itself is now applied by a blocking inline script in
// base.html's <head>, before first paint -- doing it here (bottom of
// <body>, after DOMContentLoaded) used to cause a flash of the wrong
// theme on every load for anyone whose stored/OS preference was dark.
// This block only has to stay in sync with whatever the head script
// already applied: read `data-theme` off <html> (already correct) to
// render the active choice, and apply changes as the user picks them.

(function () {
  const THEME_KEY = "commandCenterWeb.theme";
  const mql = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  // 2026-08-11: the tabbar's #btnTheme icon button is gone (see
  // base.html's removal note) -- Settings > Appearance's System/Light/Dark
  // segmented choice is the only theme control left, so this block no
  // longer has to keep a one-click flip button in sync with it.
  //
  // The control is a three-way System/Light/Dark segmented choice, not an
  // on/off switch -- a switch can only ever represent two states, so
  // "follow the OS" (the actual out-of-the-box behavior, computed once by
  // base.html's inline <head> script from prefers-color-scheme whenever
  // localStorage has nothing stored yet) became permanently unreachable
  // the instant anyone touched the old switch even once. "System" isn't a
  // third stored value -- it's the *absence* of a stored value, same
  // meaning the inline head script already gives that absence; picking
  // "System" here just clears the key instead of writing one, and a live
  // prefers-color-scheme listener keeps the page in sync if the OS theme
  // changes while "System" is active and the tab stays open.
  const segmented = document.getElementById("themeSegmented");

  function osPrefersDark() {
    return !!(mql && mql.matches);
  }

  function storedChoice() {
    // "system" | "light" | "dark" -- whatever's actually in localStorage,
    // defaulting to "system" (no key at all) rather than guessing.
    const stored = localStorage.getItem(THEME_KEY);
    return stored === "dark" || stored === "light" ? stored : "system";
  }

  function effectiveTheme(choice) {
    return choice === "system" ? (osPrefersDark() ? "dark" : "light") : choice;
  }

  function render() {
    const choice = storedChoice();
    if (effectiveTheme(choice) === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
    if (segmented) {
      segmented.querySelectorAll("[data-theme-choice]").forEach((btn) => {
        const isActive = btn.getAttribute("data-theme-choice") === choice;
        btn.classList.toggle("active", isActive);
        btn.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }
  }

  render();

  function setChoice(choice) {
    if (choice === "system") {
      localStorage.removeItem(THEME_KEY);
    } else {
      localStorage.setItem(THEME_KEY, choice);
    }
    render();
  }

  if (segmented) {
    segmented.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-theme-choice]");
      if (btn) setChoice(btn.getAttribute("data-theme-choice"));
    });
  }
  if (mql && mql.addEventListener) {
    mql.addEventListener("change", () => {
      if (storedChoice() === "system") render();
    });
  }

  window.CCTheme = { apply: (t) => setChoice(t), current: () => effectiveTheme(storedChoice()), choice: storedChoice };
})();

// Tabbar now scrolls horizontally on narrow viewports (style.css) -- if
// the active tab (e.g. Contacts, last in the list) starts scrolled out of
// view, the user would land on a page with no visible indication of
// where they are. `block` stays "nearest" (vertical no-op, .tabbar
// doesn't scroll vertically) and `inline: "center"` centers the active
// tab horizontally instead of just nudging it to the edge.
document.addEventListener("DOMContentLoaded", () => {
  const activeTab = document.querySelector(".tabbar .tab-btn.active");
  if (activeTab) activeTab.scrollIntoView({ block: "nearest", inline: "center" });
});

// Delete/archive handling -- replaces the old blanket
// `confirm("Delete this item?")` on every form posting to a "/delete" URL
// (and each template's own more specific `onsubmit="return confirm(...)"`,
// now removed from those templates) with three tiers, chosen per form via
// a data attribute:
//
//   data-archive-undo="Label" + data-unarchive-url="/x/{uid}/unarchive"
//     Archiving is already fully reversible server-side (every archived
//     type has a real unarchive endpoint) -- submit for real right away,
//     no confirmation needed, then offer a true Undo that calls the real
//     unarchive endpoint. No client-side trickery, no data ever at risk.
//
//   data-delete-undo="Label"
//     Cheap, non-cascading deletes (a dashboard widget, one checklist
//     item, a task/schedule-class row) where losing it costs the user
//     nothing to redo by hand. Optimistically hides the row and *delays*
//     the actual network request behind the toast's timer -- clicking Undo
//     just cancels the pending request and un-hides the row, so nothing is
//     sent at all if the user changes their mind. Deliberate tradeoff: if
//     the tab closes or the user navigates away inside that window, the
//     delete never happens either -- a safe failure mode (nothing
//     destructive occurs without the user having seen it through), not a
//     bug.
//
//     Adding data-delete-undo-redirect="/some/list" switches to the
//     detail/view/edit-modal form of the same control (event_form.html,
//     task_detail.html, schedule_class_form.html, ...): there's no row to
//     hide, so no undo window is offered -- the delete goes out immediately
//     and, once it lands, the page behind a modal is reloaded (or the page
//     navigates to the redirect on a standalone page) so the removed object
//     isn't left showing on stale markup.
//
//   (no data attribute, but action still matches "/delete")
//     Falls back to a generic confirm-sheet -- covers every delete form
//     that doesn't opt into one of the above, so nothing loses its safety
//     net just for not being explicitly wired up.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;

  if (form.hasAttribute("data-archive-undo")) {
    event.preventDefault();
    const label = form.getAttribute("data-archive-undo") || "Item";
    const unarchiveUrl = form.getAttribute("data-unarchive-url");
    const row = form.closest("[data-undo-row]") || form.closest("tr, .kanban-card, .card, .calendar-row, .contact-row");
    fetch(form.action, { method: "POST", body: new FormData(form) })
      .then((r) => {
        if (!r.ok) throw new Error("archive failed");
        if (row) row.style.display = "none";
        window.ccToast({
          title: "Archived",
          message: `"${label}"`,
          actionLabel: unarchiveUrl ? "Undo" : undefined,
          onAction: unarchiveUrl
            ? () => {
                fetch(unarchiveUrl, { method: "POST" }).then(() => {
                  if (row) row.style.display = "";
                  else window.location.reload();
                });
              }
            : undefined,
        });
      })
      .catch(() => window.ccToast({ message: `Could not archive "${label}". Try again.`, variant: "error" }));
    return;
  }

  if (form.hasAttribute("data-delete-undo")) {
    event.preventDefault();
    const label = form.getAttribute("data-delete-undo") || "Item";
    const row = form.closest("[data-undo-row]") || form.closest("tr, .kanban-card, .card, .calendar-row, .contact-row, .checklist-row, .widget-card");
    if (row) row.style.display = "none";
    // Detail/view/edit-modal delete (task_detail.html, the event/task/
    // contact/class forms opened as a modal or standalone page, not a list
    // row) -- no `row` to hide in place, so there's nothing an undo window
    // could restore; delete for real right away. `data-delete-undo-redirect`
    // marks these: from a modal, close it and reload the page it was opened
    // over once the delete lands; on a standalone page, follow the redirect
    // once the delete lands. `inModal` must be captured before closeModal()
    // drops the overlay's .is-open class.
    const redirect = form.getAttribute("data-delete-undo-redirect");
    const inModal = !!(window.CCModal && document.getElementById("modal-overlay").classList.contains("is-open"));

    if (redirect) {
      if (inModal) window.CCModal.close();
      fetch(form.action, { method: "POST", headers: { "X-Requested-With": "fetch" }, body: new FormData(form) })
        .then(() => {
          // async-CRUD (features/async-crud.md): a form marked data-cc-change
          // opts out of the reload -- the page the modal was opened over
          // refreshes just its own region on the cc-entity-changed event. If
          // no surface listener claims it (no live region here), fall back
          // to a reload/navigate so the page can't go stale.
          const changeType = form.getAttribute("data-cc-change");
          if (inModal && changeType && window.ccApi && window.ccApi.dispatchChange) {
            if (!window.ccApi.dispatchChange({ type: changeType, action: "delete" })) {
              window.location.reload();
            }
          } else if (inModal) window.location.reload();
          else window.location.href = redirect;
        })
        .catch(() => {
          // Best-effort: the modal is already closed; a failed delete just
          // means the object reappears on next reload rather than silently
          // vanishing forever.
        });
      return;
    }

    // List-row delete: optimistic hide + undo toast + delayed background
    // fetch so Undo can cancel it before anything is sent.
    let cancelled = false;
    const timer = setTimeout(() => {
      if (cancelled) return;
      fetch(form.action, { method: "POST", headers: { "X-Requested-With": "fetch" }, body: new FormData(form) })
        .then(() => {
          // Tell the page's region (e.g. #tasks-body) to re-render now the
          // delete is confirmed, so divider counts / pagers / empty states
          // catch up -- only when the form opted in via data-cc-change.
          const changeType = form.getAttribute("data-cc-change");
          if (changeType) {
            document.dispatchEvent(
              new CustomEvent("cc-entity-changed", {
                detail: { type: changeType, action: "delete" },
              })
            );
          }
        })
        .catch(() => {
          // Best-effort: the row is already hidden client-side; a failed
          // background delete just means it'll reappear on next reload
          // rather than silently vanishing forever.
        });
    }, 4500);
    window.ccToast({
      title: "Deleted",
      message: `"${label}"`,
      actionLabel: "Undo",
      onAction: () => {
        cancelled = true;
        clearTimeout(timer);
        if (row) row.style.display = "";
      },
      duration: 4500,
    });
    return;
  }

  if (form.action.includes("/delete") && !form.hasAttribute("data-confirm-sheet") && !form.dataset.confirmed) {
    event.preventDefault();
    const submitter = event.submitter || form.querySelector('button[type="submit"], button:not([type])');
    window.ccConfirmSheet({
      anchor: submitter || form,
      message: "Delete this item? This cannot be undone.",
      onConfirm: () => {
        form.dataset.confirmed = "1";
        form.requestSubmit ? form.requestSubmit(submitter) : form.submit();
      },
    });
  }
});

// Mobile FAB -- clones whatever [data-fab] element exists in the page's
// own toolbar (each page's real "+New X" button already carries the
// right href/data-modal, so this reads from it instead of hardcoding a
// second copy of every page's create URL here). CSS hides the result on
// anything wider than the mobile breakpoint, so this always runs, not
// just below some JS-side width check -- one fewer thing to keep in sync
// with the CSS breakpoint.
document.addEventListener("DOMContentLoaded", () => {
  const source = document.querySelector("[data-fab]");
  if (!source) return;
  const fab = document.createElement("a");
  fab.className = "fab";
  fab.href = source.getAttribute("href") || "#";
  const modalTarget = source.getAttribute("data-modal");
  if (modalTarget !== null) fab.setAttribute("data-modal", modalTarget || fab.href);
  fab.setAttribute("aria-label", (source.textContent || "New").trim());
  fab.title = (source.textContent || "New").trim();
  fab.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#icon-plus"></use></svg>';
  document.body.appendChild(fab);
});

// data-confirm-sheet="message" -- the explicit version of the fallback
// above, for forms that need a more specific message than the generic
// one (cascading deletes: a database's columns/rows, a habit's whole
// logged history, a tag everywhere it's used). Handled as a capturing
// click on the submit button rather than a submit-event branch above,
// so the confirm sheet can read its own message text via the attribute
// before anything about the form's action matters.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  const message = form.getAttribute("data-confirm-sheet");
  if (!message || form.dataset.confirmed) return;
  event.preventDefault();
  const submitter = event.submitter || form.querySelector('button[type="submit"], button:not([type])');
  window.ccConfirmSheet({
    anchor: submitter || form,
    message,
    onConfirm: () => {
      form.dataset.confirmed = "1";
      form.requestSubmit ? form.requestSubmit(submitter) : form.submit();
    },
  });
});

// Generic multi-select dropdown -- e.g. Calendar's "which calendars are
// visible" toggle (_calendar_nav.html), where more than one option can be
// active at once, so a single <select> (which only ever picks one) isn't
// the right control -- unlike the Tasks/Contacts list/status filters
// (tasks_list.html etc.), which really are "pick exactly one" and use a
// plain <select> instead of this.
//
// Markup contract: `.multiselect` wraps a `.multiselect-trigger` button
// and a `.multiselect-panel`. Clicking the trigger toggles the panel;
// clicking anywhere outside, or pressing Escape, closes it. Each option
// inside the panel is free to be whatever it needs to be (here: a
// same-origin `<form>` per checkbox that submits itself on change, since
// visibility-toggling is already a real server-side POST, not client
// state) -- this script only owns open/close, not what's inside.
//
// 2026-08-08 direct feedback ("this drop down menus should be able to
// exit the modal window, not be masked inside it, always [available]") --
// the "always lives directly in the page" assumption above turned out to
// be wrong: task_form/event_form/contact_form/habit_form/the widget
// builder all render this inside `.modal-body`, which clips overflow same
// as modal.js's color/icon popovers do, so the panel was getting visually
// cut off or overlapping other modal content instead of just scrolling
// internally. Same portal technique as modal.js's openPopover/
// closeOpenPopover now: on open, move the panel itself into
// #multiselect-portal (base.html, a fixed-position layer outside any
// modal) and position it with `position:fixed` against its trigger; on
// close, move it back to exactly where it came from. Each option input
// carries a `form="..."` attribute (_widget_list_multiselect.html's
// ms_form_id) so it stays part of its real `<form>` even while reparented
// outside it -- otherwise the browser silently drops a moved form control
// from its form's submission.
(function () {
  const portal = document.getElementById("multiselect-portal");
  let openPanel = null; // { panel, trigger, anchor, nextSibling }

  function position(panel, trigger) {
    const rect = trigger.getBoundingClientRect();
    panel.style.minWidth = rect.width + "px";
    const panelRect = panel.getBoundingClientRect();
    let left = rect.left;
    let top = rect.bottom + 6;
    if (left + panelRect.width > window.innerWidth - 8) {
      left = Math.max(8, window.innerWidth - panelRect.width - 8);
    }
    if (top + panelRect.height > window.innerHeight - 8) {
      top = rect.top - panelRect.height - 6; // flip above the trigger instead
    }
    panel.style.left = left + "px";
    panel.style.top = top + "px";
  }

  function closeOpenPanel() {
    if (!openPanel) return;
    const { panel, anchor, nextSibling } = openPanel;
    panel.classList.remove("is-open");
    // The wrapper keeps a mirror class too so a trigger's chevron/caret can
    // flip while its panel is open -- the panel itself is portaled out to
    // #multiselect-portal at that point, so a `.multiselect:has(.panel.is-
    // open)` selector can never see it from the wrapper.
    anchor.classList.remove("is-open");
    panel.style.left = panel.style.top = panel.style.minWidth = "";
    // Move it back to exactly where it started -- insertBefore(node, null)
    // is the same as appendChild, so a null nextSibling (it was already
    // the last child) still lands in the right place.
    anchor.insertBefore(panel, nextSibling);
    openPanel = null;
  }

  function openPanelFor(trigger, panel) {
    const anchor = panel.parentElement;
    const nextSibling = panel.nextSibling;
    if (!portal) {
      // No portal container on the page (shouldn't happen -- it's in
      // base.html -- but degrade to the old in-place behavior rather than
      // silently doing nothing if it's ever missing).
      panel.classList.add("is-open");
      anchor.classList.add("is-open");
      openPanel = { panel, trigger, anchor, nextSibling };
      return;
    }
    portal.appendChild(panel);
    panel.classList.add("is-open");
    anchor.classList.add("is-open");
    position(panel, trigger);
    openPanel = { panel, trigger, anchor, nextSibling };
  }

  // Finds the `.multiselect-panel` belonging to a given `.multiselect`
  // wrapper regardless of whether it's currently sitting in its normal
  // spot (never opened yet, or closed again) or portaled out to
  // #multiselect-portal (currently open). Only one panel is ever portaled
  // at a time (opening a new one always closes whatever was open first),
  // so "the currently portaled panel, if its remembered anchor is this
  // wrapper" is an unambiguous fallback. Exposed as window.CCMultiselect
  // so other scripts that need to reach into a panel's actual `<input>`s
  // (dashboard_widget_preview.js's Source->View->Range filtering) don't
  // have to duplicate this lookup or, worse, assume the panel is still a
  // plain DOM descendant of its wrapper the way a `.querySelector` would.
  function resolvePanel(wrapper) {
    if (!wrapper) return null;
    return wrapper.querySelector(".multiselect-panel") || (openPanel && openPanel.anchor === wrapper ? openPanel.panel : null);
  }
  window.CCMultiselect = { panelFor: resolvePanel };

  document.addEventListener("click", (e) => {
    const trigger = e.target.closest(".multiselect-trigger");
    if (trigger) {
      const wrapper = trigger.closest(".multiselect");
      const panel = resolvePanel(wrapper);
      if (!panel) return;
      if (openPanel && openPanel.panel === panel) {
        closeOpenPanel();
      } else {
        closeOpenPanel();
        openPanelFor(trigger, panel);
      }
      return;
    }
    if (openPanel && !openPanel.panel.contains(e.target)) {
      closeOpenPanel();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeOpenPanel();
  });

  window.addEventListener("resize", () => {
    if (openPanel) position(openPanel.panel, openPanel.trigger);
  });

  // Keep each .widget-list-multiselect's trigger summary ("All"/"N
  // selected"/"No labels") in sync with its checkboxes (2026-08-07,
  // modal-input-design Phase B -- generalized here, out of
  // dashboard_widget_preview.js, so every page reusing
  // _widget_list_multiselect.html gets this for free, not just the widget
  // builder's own .widget-select-form). data-ms-mode is set by the
  // template: "filter" (default, unchanged widget-builder behavior --
  // empty or fully-checked both read "All"), "select" (task_form/
  // event_form/contact_form/habit_form/tasks_list.html's Labels pickers --
  // empty reads "No <label>", never collapses to "All"), or "single"
  // (2026-08-07, widget builder's View/Range -- a single-select mode of
  // the same partial, radios instead of checkboxes, summary is just the
  // checked option's own label text).
  function updateMsSummary(ms) {
    const summary = ms.querySelector(".ms-summary");
    if (!summary) return;
    // The trigger (and its .ms-summary) never moves, but the panel -- and
    // every radio/checkbox inside it -- does once opened (portaled to
    // #multiselect-portal). `resolvePanel(ms)` finds it either way instead
    // of assuming it's still a plain descendant of `ms`.
    const panel = resolvePanel(ms);
    const mode = ms.dataset.msMode || "filter";
    if (mode === "single") {
      const checked = panel ? panel.querySelector('input[type="radio"]:checked') : null;
      const row = checked ? checked.closest(".multiselect-option") : null;
      const label = row ? row.querySelector("span:last-child") : null;
      summary.textContent = label ? label.textContent : "Select";
      return;
    }
    const boxes = panel ? panel.querySelectorAll('input[type="checkbox"]') : [];
    const checked = Array.from(boxes).filter((b) => b.checked).length;
    if (mode === "select") {
      summary.textContent = checked === 0 ? "No " + (ms.dataset.msLabel || "selection") : checked + " selected";
    } else {
      summary.textContent = checked === 0 || checked === boxes.length ? "All" : checked + " selected";
    }
  }
  // Resolves the `.widget-list-multiselect` wrapper an input belongs to --
  // a plain `.closest()` from the input only works while its panel is
  // still in its original spot in the DOM. Once opened, the panel (and
  // every input inside it) lives in #multiselect-portal instead, outside
  // the wrapper entirely, so `.closest()` from inside it would find
  // nothing; fall back to the currently-open panel's remembered anchor in
  // that case.
  function wrapperFor(input) {
    return input.closest(".widget-list-multiselect") || (openPanel && openPanel.panel.contains(input) ? openPanel.anchor : null);
  }

  document.addEventListener("change", (e) => {
    const ms = wrapperFor(e.target);
    if (!ms) return;
    updateMsSummary(ms);
    // Single-select (View/Range/the reworked Priority/Status): picking an
    // option is a complete choice, not one tick among several -- close
    // the panel right away instead of staying open for more picks like
    // the multiselect does.
    if (ms.dataset.msMode === "single" && e.target.type === "radio" && openPanel && openPanel.anchor === ms) {
      closeOpenPanel();
    }
  });
  document.querySelectorAll(".widget-list-multiselect").forEach(updateMsSummary);
})();

// Dashboard masonry layout (dashboard.html's #dashboard-grid, both edit
// and view mode -- 2026-08-02) -- a plain `display:grid` 6-column grid
// sizes every *row* to its tallest occupant, so a short widget next to a
// tall one always left dead space under itself instead of letting
// whatever comes next start right where it actually ends. This computes
// real positions instead: each card still claims a `data-span` out of 6
// virtual columns (third=2/half=3/two_thirds=4/full=6, unchanged from
// before), but its top is wherever those columns are *actually* free,
// tracked per-column as cards are placed in DOM order -- the standard
// "skyline" packing masonry libraries use, just handwritten here since
// the dependency isn't worth it for one grid on one page.
//
// Runs unconditionally (not gated behind edit mode -- unlike every other
// dashboard grid script below) because the gaps this fixes are exactly
// as visible just looking at the dashboard as they are while rearranging
// it. A MutationObserver on the grid re-runs it automatically after
// anything that changes a card's size or order (drag reorder's
// insertBefore, resize's data-span writes, a delete-undo hide/unhide) --
// deliberately not threaded as an explicit call through every one of
// those scripts individually, since that list would only grow and be
// easy to miss one of. rAF-coalesced so a burst of mutations in one
// frame (e.g. every pointermove during a drag) still only computes
// layout once per frame.
(function () {
  const grid = document.getElementById("dashboard-grid");
  if (!grid) return;

  const MOBILE_BREAKPOINT = 720; // matches every other collapsing layout in this app
  const GAP = 16; // var(--space-4) -- see style.css's design tokens

  function cardIsVisible(card) {
    // data-delete-undo (app.js's generic delete handler, used on every
    // widget delete form) hides a row by setting display:none directly,
    // no page reload -- an already-hidden card shouldn't still claim
    // column space it no longer occupies on screen.
    return card.style.display !== "none";
  }

  // Skyline packing (shared by the dry-run and the real pass below) --
  // takes a column count and returns, for each card in order, which
  // column it starts in and how tall each column's skyline was left. Pure
  // index math, no pixel sizes or DOM involved, so it's cheap to run
  // twice: once just to find out how many of the `cols` virtual columns
  // this particular set of cards actually ends up touching, and again for
  // real once that number is known (see effectiveCols below).
  function packColumns(cards, cols) {
    const colHeights = new Array(cols).fill(0);
    const placements = [];
    let maxTouched = 0;
    cards.forEach((card) => {
      const span = Math.min(cols, Math.max(1, parseInt(card.dataset.span, 10) || cols));
      let bestStart = 0;
      let bestTop = Infinity;
      for (let start = 0; start <= cols - span; start++) {
        const top = Math.max(...colHeights.slice(start, start + span));
        if (top < bestTop) {
          bestTop = top;
          bestStart = start;
        }
      }
      // Real height isn't known yet in the dry run (no DOM writes happen
      // here), so column-height bookkeeping uses a placeholder of 1 per
      // card -- enough to make the skyline algorithm's "shortest column"
      // choice keep behaving the same way run to run, without needing to
      // duplicate the real bottom/GAP math from the pixel pass below.
      for (let i = bestStart; i < bestStart + span; i++) colHeights[i] += 1;
      maxTouched = Math.max(maxTouched, bestStart + span);
      placements.push({ card, span, bestStart });
    });
    return { placements, maxTouched };
  }

  function layout() {
    const cards = Array.from(grid.children).filter((el) => el.classList.contains("widget-card") && cardIsVisible(el));
    if (!cards.length) {
      grid.style.height = "";
      return;
    }
    const containerWidth = grid.clientWidth;
    const maxCols = window.innerWidth <= MOBILE_BREAKPOINT ? 1 : 6;
    // 2026-08-08 direct feedback ("weird permanent empty space on the
    // right, widgets crowded") -- a dashboard with only a couple of
    // widgets (e.g. two half/third-width cards, 5 of 6 virtual columns
    // claimed) always reserved the full 6-column width regardless, so the
    // one never-touched column sat there as dead space on the right
    // forever, and every card's own pixel width was computed against a
    // colWidth one column narrower than the space actually available.
    // Fix: a cheap dry run (packColumns, pure index math, no DOM) using
    // the full 6 columns first, just to find out how many columns this
    // actual set of cards ends up touching -- then the real pass below
    // uses THAT as its column count, so colWidth (and therefore every
    // card's width) is computed against the space genuinely in use, not
    // an assumed max. A dashboard with enough widgets to fill all 6
    // columns anyway sees no change at all (effectiveCols === maxCols).
    const dryRun = packColumns(cards, maxCols);
    const cols = Math.max(1, dryRun.maxTouched);
    const colWidth = (containerWidth - GAP * (cols - 1)) / cols;
    const colHeights = new Array(cols).fill(0);
    let maxBottom = 0;

    cards.forEach((card) => {
      const span = Math.min(cols, Math.max(1, parseInt(card.dataset.span, 10) || cols));
      // Skyline packing: among every valid starting column for this
      // card's width, pick whichever leaves the least wasted space --
      // the one where the tallest column it would span is shortest.
      let bestStart = 0;
      let bestTop = Infinity;
      for (let start = 0; start <= cols - span; start++) {
        const top = Math.max(...colHeights.slice(start, start + span));
        if (top < bestTop) {
          bestTop = top;
          bestStart = start;
        }
      }
      const left = bestStart * (colWidth + GAP);
      const width = span * colWidth + (span - 1) * GAP;
      card.style.left = `${left}px`;
      card.style.top = `${bestTop}px`;
      card.style.width = `${width}px`;
      // Reading offsetHeight here forces the browser to actually apply
      // the width change above before measuring -- necessary since a
      // narrower/wider card reflows its own text and can change height,
      // and the next card's placement depends on that real height, not
      // whatever height it had at its old width.
      const bottom = bestTop + card.offsetHeight;
      maxBottom = Math.max(maxBottom, bottom);
      // GAP is added here, not to `bottom` itself -- `bottom` (the real
      // edge of this card) is what maxBottom/grid.style.height below
      // needs, but the *next* card stacked under this one in the same
      // column has to start GAP further down than that, or they touch
      // with zero space between them (this was missing entirely at
      // first: horizontal neighbors got GAP from the `left` formula
      // below, but two cards landing in the same column stacked
      // vertically had nothing enforcing space between them at all).
      for (let i = bestStart; i < bestStart + span; i++) colHeights[i] = bottom + GAP;
    });

    grid.style.height = `${maxBottom}px`;
  }

  let rafId = null;
  function scheduleLayout() {
    if (rafId) return;
    rafId = requestAnimationFrame(() => {
      rafId = null;
      layout();
    });
  }

  new MutationObserver(scheduleLayout).observe(grid, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["style", "class", "data-span"],
  });

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(layout, 150);
  });

  layout();
})();

// Dashboard widget drag-to-reorder (dashboard.html, edit mode only) --
// replaces the old move-up/move-down buttons, which cost one full page
// reload per single-step move. Pointer Events (mouse + touch in one
// listener), same optimistic-drag-then-background-POST shape as Kanban's
// drag-and-drop (tasks_board.js) -- the widget grid is 2D (spans of 1-6
// out of 6 columns, more than one widget per row), so instead of Kanban's
// simpler "which column" hit-test, this finds whichever widget card is
// actually under the pointer and inserts before/after it depending on
// which half of that card's box the pointer is in.
(function () {
  const grid = document.getElementById("dashboard-grid");
  if (!grid || !grid.classList.contains("is-editing")) return;

  const DRAG_THRESHOLD = 6;
  // Stacking's drop zone (2026-08-02) -- the outer EDGE_ZONE fraction of
  // whichever single axis reorder already uses (x when the target's in
  // your row, y otherwise -- see reorderPreview) reorders before/after;
  // everything else, the middle 1 - 2*EDGE_ZONE, stacks. This used to
  // require BOTH x *and* y to land in a 40%-wide center band at once --
  // a small box in the exact middle of the card, awkward to actually hit
  // while dragging from a handle that sits up in the corner. Checking
  // only the one axis that already matters for that drop makes "stack"
  // the easy, generous default (the whole middle of the card) and
  // "reorder" the deliberate, narrower gesture (near an edge) instead.
  const EDGE_ZONE = 0.2;
  let dragCard = null;
  let dragPointerId = null;
  let startX = 0;
  let startY = 0;
  let dragging = false;
  let stackTargetEl = null;

  function cardAtPoint(x, y) {
    dragCard.style.visibility = "hidden";
    const el = document.elementFromPoint(x, y);
    dragCard.style.visibility = "";
    return el ? el.closest(".widget-card") : null;
  }

  function setStackTarget(el) {
    if (stackTargetEl === el) return;
    if (stackTargetEl) stackTargetEl.classList.remove("is-stack-target");
    stackTargetEl = el;
    if (stackTargetEl) stackTargetEl.classList.add("is-stack-target");
  }

  function reorderPreview(x, y) {
    const target = cardAtPoint(x, y);
    if (!target || target === dragCard) {
      setStackTarget(null);
      return;
    }
    const r = target.getBoundingClientRect();
    // The grid has more than one card per row (widths vary: third/half/
    // two_thirds/full), so this can't just compare y against the
    // target's vertical midpoint -- that only ever answers "above or
    // below", which is why dragging rightward within the same row used
    // to silently do nothing (the target "below" test was never true
    // for a card beside you) while dragging leftward happened to work
    // (you were dropping into the row above). If the pointer is within
    // the target's own row band, decide left/right off its horizontal
    // position instead; only fall back to above/below once the pointer
    // has actually left that row.
    const sameRow = y >= r.top && y <= r.bottom;
    const frac = sameRow ? (x - r.left) / r.width : (y - r.top) / r.height;

    // A drop-onto-stack target can't itself be the card currently being
    // dragged, and dragging a stack container itself is reorder-only
    // (stacks can't be stacked -- see stack_widget's own 400 for that,
    // matched here so the highlight never promises something the drop
    // would then reject).
    const canStackOnto = !dragCard.classList.contains("widget-stack");
    if (canStackOnto && frac > EDGE_ZONE && frac < 1 - EDGE_ZONE) {
      setStackTarget(target);
      return;
    }
    setStackTarget(null);
    const before = frac < 0.5;
    target.parentElement.insertBefore(dragCard, before ? target : target.nextSibling);
  }

  // Takes the dropped card element itself, not just its uid -- endDrag
  // below nulls out the `dragCard` closure variable *before* calling
  // this (so a stray pointer event arriving during the await can't
  // still see a stale in-progress drag), which used to mean this
  // function's own `dragCard.previousElementSibling` read `null`'s
  // sibling and threw on every single drop, silently, inside the
  // pointerup handler -- the reorder never actually reached the server,
  // no error surfaced anywhere, it just looked like dragging did
  // nothing. Passing the already-captured element sidesteps that
  // entirely.
  async function persistOrder(card) {
    const afterEl = card.previousElementSibling;
    const afterUid = afterEl && afterEl.classList.contains("widget-card") ? afterEl.dataset.uid : "";
    try {
      const resp = await fetch(`/dashboard/widgets/${card.dataset.uid}/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: `after_uid=${encodeURIComponent(afterUid)}`,
      });
      if (!resp.ok) throw new Error("reorder failed");
    } catch (err) {
      window.ccToast({ message: "Could not save the new order. Reloading...", variant: "error", duration: 1400 });
      setTimeout(() => window.location.reload(), 1200);
    }
  }

  async function persistStack(uid, targetUid) {
    // Unlike reorder/resize, stacking changes the actual card structure
    // (a brand-new stack container wrapping two nested widgets, or an
    // existing one gaining a member) -- rebuilding that in JS would mean
    // duplicating the whole widget_inner macro's HTML client-side. A
    // reload is the honest option here rather than a half-right DOM
    // patch that doesn't actually look like what the Filters panel/
    // resize handle/delete button expect the page to look like next.
    try {
      const resp = await fetch(`/dashboard/widgets/${uid}/stack-onto`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: `target_uid=${encodeURIComponent(targetUid)}`,
      });
      if (!resp.ok) throw new Error("stack failed");
      window.location.reload();
    } catch (err) {
      window.ccToast({ message: "Could not stack that widget. Try again.", variant: "error", duration: 2200 });
    }
  }

  function endDrag(e) {
    if (!dragCard || e.pointerId !== dragPointerId) return;
    const card = dragCard;
    const wasDragging = dragging;
    const targetEl = stackTargetEl;
    card.classList.remove("is-dragging");
    setStackTarget(null);
    dragCard = null;
    dragging = false;
    dragPointerId = null;
    if (!wasDragging) return;
    if (targetEl) {
      persistStack(card.dataset.uid, targetEl.dataset.uid);
    } else {
      persistOrder(card);
    }
  }

  grid.querySelectorAll(".widget-drag-handle").forEach((handle) => {
    handle.addEventListener("pointerdown", (e) => {
      if (e.button !== undefined && e.button !== 0) return;
      dragCard = handle.closest(".widget-card");
      if (!dragCard) return;
      dragPointerId = e.pointerId;
      startX = e.clientX;
      startY = e.clientY;
      dragging = false;
      // Capture on the grid itself, not the handle. reorderPreview()
      // relocates dragCard (and the handle inside it) elsewhere in the
      // DOM every time the pointer crosses into another card -- browsers
      // treat that detach+reattach as the captured element having left
      // the document and silently drop capture, which fired
      // "lostpointercapture" mid-drag and made the card deselect itself
      // the instant you moved it. The grid element is never itself
      // moved, so capturing there survives every reorder.
      grid.setPointerCapture(e.pointerId);
    });
  });

  grid.addEventListener("pointermove", (e) => {
    if (!dragCard || e.pointerId !== dragPointerId) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (!dragging) {
      if (Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;
      dragging = true;
      dragCard.classList.add("is-dragging");
    }
    reorderPreview(e.clientX, e.clientY);
  });

  grid.addEventListener("pointerup", endDrag);
  grid.addEventListener("pointercancel", endDrag);
  // Belt-and-suspenders: if capture is ever lost for a reason other than
  // pointerup/pointercancel, this still guarantees the card doesn't get
  // stuck at 50% opacity forever. endDrag() is idempotent (guarded on
  // dragCard being non-null), so this can't double-fire persistOrder
  // alongside a normal pointerup.
  grid.addEventListener("lostpointercapture", endDrag);
})();

// Reordering *within* a stack (2026-08-02) -- deliberately a separate,
// simpler script from the top-level grid drag above rather than
// generalizing that one further: stack members aren't wrapped in
// .widget-card (only the stack container itself is), so the "find
// whichever card is under the pointer" 2D hit-test above doesn't apply
// here at all -- this is a plain single-column vertical list, closer to
// Kanban's own card-within-column reorder than the top-level grid drag.
// One handler covers every stack on the page; each stack scopes its own
// drag to its own .widget-stack-item children, so dragging in one stack
// can never reorder into a different one (moving a widget *between*
// stacks isn't supported by dragging -- Unstack, then stack it onto the
// other one).
(function () {
  const stacks = document.querySelectorAll(".dashboard-grid.is-editing .widget-stack");
  if (!stacks.length) return;

  const DRAG_THRESHOLD = 6;

  stacks.forEach((stack) => {
    let dragItem = null;
    let dragPointerId = null;
    let startX = 0;
    let startY = 0;
    let dragging = false;

    function itemAtPoint(y) {
      dragItem.style.visibility = "hidden";
      const el = document.elementFromPoint(stack.getBoundingClientRect().left + 1, y);
      dragItem.style.visibility = "";
      return el ? el.closest(".widget-stack-item") : null;
    }

    function reorderPreview(y) {
      const target = itemAtPoint(y);
      if (!target || target === dragItem || !stack.contains(target)) return;
      const r = target.getBoundingClientRect();
      const before = y < r.top + r.height / 2;
      target.parentElement.insertBefore(dragItem, before ? target : target.nextSibling);
    }

    // Takes the dropped item element itself, not just its uid -- same
    // bug as the top-level grid drag had (see its own persistOrder's
    // comment): endDrag nulls the `dragItem` closure variable *before*
    // calling this, so reading `dragItem.previousElementSibling` in here
    // was reading null's sibling and throwing on every single drop,
    // silently, inside the pointerup handler -- the reorder never
    // actually reached the server. Passing the already-captured element
    // sidesteps that.
    async function persistOrder(item) {
      const afterEl = item.previousElementSibling;
      const afterUid = afterEl && afterEl.classList.contains("widget-stack-item") ? afterEl.dataset.uid : "";
      try {
        const resp = await fetch(`/dashboard/widgets/${item.dataset.uid}/reorder`, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: `after_uid=${encodeURIComponent(afterUid)}`,
        });
        if (!resp.ok) throw new Error("reorder failed");
      } catch (err) {
        window.ccToast({ message: "Could not save the new order. Reloading...", variant: "error", duration: 1400 });
        setTimeout(() => window.location.reload(), 1200);
      }
    }

    function endDrag(e) {
      if (!dragItem || e.pointerId !== dragPointerId) return;
      const item = dragItem;
      const wasDragging = dragging;
      item.classList.remove("is-dragging");
      dragItem = null;
      dragging = false;
      dragPointerId = null;
      if (wasDragging) persistOrder(item);
    }

    stack.querySelectorAll(".widget-stack-drag-handle").forEach((handle) => {
      handle.addEventListener("pointerdown", (e) => {
        if (e.button !== undefined && e.button !== 0) return;
        dragItem = handle.closest(".widget-stack-item");
        if (!dragItem) return;
        dragPointerId = e.pointerId;
        startX = e.clientX;
        startY = e.clientY;
        dragging = false;
        // Same lesson as the top-level grid drag above: capture on
        // `stack` (never itself relocated) rather than the handle
        // (relocated by reorderPreview's insertBefore on every crossing),
        // so capture survives every reorder instead of silently
        // releasing mid-drag.
        stack.setPointerCapture(e.pointerId);
      });
    });

    stack.addEventListener("pointermove", (e) => {
      if (!dragItem || e.pointerId !== dragPointerId) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (!dragging) {
        if (Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;
        dragging = true;
        dragItem.classList.add("is-dragging");
      }
      reorderPreview(e.clientY);
    });

    stack.addEventListener("pointerup", endDrag);
    stack.addEventListener("pointercancel", endDrag);
    stack.addEventListener("lostpointercapture", endDrag);
  });
})();

// Manual width picker / drag-to-resize-width (2026-08-02) removed
// 2026-08-07 per direct feedback: "auto-fit by content" -- a widget's
// width is now always just its type's own default_width (or, for a
// stack, the stack's own stored config -- see routers/dashboard.py's
// _widget_width), no manual override. There is no more
// .widget-resize-handle element and no more
// /dashboard/widgets/{uid}/resize endpoint to POST to. The masonry
// layout function above still reads each card's data-span attribute and
// does skyline packing exactly as before -- it never cared whether
// data-span came from a manual choice or an automatic default, so it
// needed no changes here.

// Manual height editor / drag-to-resize-height (2026-08-02) removed
// 2026-08-07 per direct feedback -- a widget's height is now just "how
// much content it is", no scrollbar, unless it goes over a max height
// (a single flat CSS max-height on .widget-content, see style.css).
// There is no more .widget-resize-handle-vertical element and no more
// /dashboard/widgets/{uid}/resize-height endpoint to POST to.

// Banner upload auto-compression (2026-08-10, banner_editor.html) -- the
// upload tab's file input calls this on change instead of submitting the
// original file. A phone camera hands back a 4-8MB image that then gets
// stored base64 in app_meta and served on every page load; this resizes it
// in the browser before the form ever posts, so what reaches the server
// (and later the network on every visit) is a ~2400px WebP/JPEG at a
// fraction of the bytes. No-JS / unsupported browsers skip the resize and
// submit the original -- the 8MB server cap is still the real guard, this
// is a best-effort size reduction. Animated GIFs are deliberately left
// alone (re-encoding them would flatten the animation into a static frame).
window.CCBannerUpload = {
  onFile(input) {
    const form = input.form;
    const file = input.files && input.files[0];
    const bail = () => form && form.requestSubmit();
    if (!file || !file.type.startsWith("image/") || file.type === "image/gif" || !window.DataTransfer) return bail();
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onerror = () => { URL.revokeObjectURL(url); bail(); };
    img.onload = () => {
      // Max long edge, matching the editor's own "about 2400x480px" guidance
      // (2x for retina). Never upscales; small images stay untouched.
      const MAX = 2400;
      const scale = Math.min(1, MAX / Math.max(img.naturalWidth, img.naturalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
      const ctx = canvas.getContext("2d");
      // White underneath transparent pixels (PNG) so the JPEG fallback
      // doesn't turn transparency black; WebP keeps alpha when supported.
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      const webp = canvas.toDataURL("image/webp").indexOf("data:image/webp") === 0;
      const outType = webp ? "image/webp" : "image/jpeg";
      canvas.toBlob((blob) => {
        if (blob && blob.size < file.size) {
          const dt = new DataTransfer();
          dt.items.add(new File([blob], webp ? "banner.webp" : "banner.jpg", { type: outType }));
          input.files = dt.files;
        }
        form && form.requestSubmit();
      }, outType, 0.82);
    };
    img.src = url;
  },
};

// Action menu (three-dot dropdown for status cards) -- lightweight,
// accessible dropdown that closes on outside click/Escape/scroll and
// supports keyboard navigation. On open the panel is DETACHED to
// document.body (the same portal technique #color-popover /
// #multiselect-portal use): .status-card:hover carries a transform, and
// a transformed ancestor becomes the containing block for position:fixed
// descendants -- a panel left inside the card would be positioned
// relative to the card and teleport as hover toggles, and its clicks
// would still bubble into the wrapping <a>. At body level there is no
// transformed ancestor, so fixed coordinates mean the real viewport.
(function () {
  let activeMenu = null; // { trigger, panel } -- at most one open at a time

  function closeMenu() {
    if (!activeMenu) return;
    const { panel, trigger } = activeMenu;
    panel.classList.remove("is-open");
    // Return the panel to where the template put it.
    if (panel.__ccHome && panel.__ccHome.parent && panel.__ccHome.parent.isConnected) {
      panel.__ccHome.parent.insertBefore(panel, panel.__ccHome.next);
    }
    trigger.setAttribute("aria-expanded", "false");
    activeMenu = null;
  }

  function showMenu(menu) {
    closeMenu();
    const { trigger, panel } = menu;
    if (!panel.__ccHome) {
      panel.__ccHome = { parent: panel.parentNode, next: panel.nextSibling };
    }
    document.body.appendChild(panel);

    // Measure while invisible -- display:none has no box -- then clamp to
    // the viewport and reveal in one place.
    panel.classList.add("is-open");
    panel.style.visibility = "hidden";
    const rect = trigger.getBoundingClientRect();
    const pr = panel.getBoundingClientRect();
    let left = rect.right - pr.width;
    let top = rect.bottom + 4;
    left = Math.max(8, Math.min(left, window.innerWidth - pr.width - 8));
    if (top + pr.height > window.innerHeight - 8) {
      top = Math.max(8, rect.top - pr.height - 4);
      panel.dataset.side = "top";
    } else {
      panel.dataset.side = "bottom";
    }
    panel.style.left = left + "px";
    panel.style.top = top + "px";
    panel.style.visibility = "";

    trigger.setAttribute("aria-expanded", "true");
    activeMenu = menu;
  }

  function handleKeydown(e, menu) {
    const items = Array.from(menu.panel.querySelectorAll(".action-menu-item"));
    const currentIndex = items.indexOf(document.activeElement);
    if (e.key === "Escape") {
      e.preventDefault();
      closeMenu();
      menu.trigger.focus();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      (items[currentIndex + 1] || items[0])?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      (items[currentIndex - 1] || items[items.length - 1])?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      items[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      items[items.length - 1]?.focus();
    }
  }

  document.addEventListener("click", (e) => {
    if (!activeMenu) return;
    if (activeMenu.panel.contains(e.target) || activeMenu.trigger.contains(e.target)) return;
    closeMenu();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Tab") closeMenu();
  });

  // A fixed panel doesn't follow page scroll -- closing on any scroll
  // beats leaving it stranded next to content that has moved on.
  document.addEventListener("scroll", () => closeMenu(), true);

  function initActionMenus() {
    document.querySelectorAll(".action-menu").forEach((root) => {
      if (root.dataset.menuBound) return; // idempotent across pagereveal
      root.dataset.menuBound = "1";
      const trigger = root.querySelector(".action-menu-trigger");
      const panel = root.querySelector(".action-menu-panel");
      if (!trigger || !panel) return;

      trigger.setAttribute("aria-haspopup", "true");
      trigger.setAttribute("aria-expanded", "false");

      const menu = { trigger, panel }; // ONE stable identity -- the toggle
      // below compares object identity, so a per-click literal would never
      // match activeMenu and the menu could open but never close.
      trigger.addEventListener("click", (e) => {
        e.preventDefault(); // keep the wrapping status-card <a> from navigating
        e.stopPropagation();
        if (activeMenu === menu) closeMenu();
        else showMenu(menu);
      }, true);

      panel.addEventListener("keydown", (e) => handleKeydown(e, { trigger, panel }));

      // Any action closes the menu -- including plain anchor items (the
      // Export…/Import…/Restore a file…/Reset database dialog triggers),
      // which otherwise stayed open behind the opened modal overlay. The
      // click still completes: closing only re-homes the panel, the
      // activated item keeps working.
      panel.addEventListener("click", () => closeMenu());

      panel.querySelectorAll("form").forEach((form) => {
        form.addEventListener("submit", () => closeMenu());
      });
    });
  }

  document.addEventListener("DOMContentLoaded", initActionMenus);
  // Cross-document view transitions swap page content without a reload --
  // pagereveal fires as the new page's content becomes live.
  document.addEventListener("pagereveal", initActionMenus);
  window.CCActionMenu = { close: closeMenu, init: initActionMenus };
})();
