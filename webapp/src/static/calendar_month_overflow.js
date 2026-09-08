// "+N more" overflow on Month/4-Week's day cells (templates/
// _calendar_month_grid.html / _calendar_fourweek_grid.html) -- 2026-09-09,
// FullCalendar-parity interactions slice 3 (documentation/plans/open.md).
// Previously a plain `<a href="/calendar/day/...">` link; now a `<button>`
// that pops an info toast listing the day's hidden items, each one a real
// click-through button that opens that item's own edit modal (open.md's
// own slice note picked the "actions array, keep click-through" option
// over a plain-text toast, at the cost of ccToast's actions row -- built
// for a 1-2 button Cancel/Confirm pair -- now also carrying 3+ stacked
// list items; see style.css's `.toast-overflow` for the layout that needs).
//
// The overflow items themselves are never fetched -- each day cell that
// has any renders a sibling, inert `<template class="month-overflow-data">`
// containing one `<a data-modal href="...">title</a>` per hidden item,
// built server-side (routers/calendar.py's `_month_day_cells`) with the
// exact same href logic the visible rows already use, so the two can never
// drift apart the way a second hand-written URL-builder in JS could.
//
// Single document-level delegated listener, same reasoning modal.js's own
// `[data-modal]` delegation comment gives: works across both Month and
// 4-Week, and survives async_calendar.js's region-refresh DOM swaps with
// no rebind/init() call needed (unlike calendar_month_drag.js's
// CCMonthGridDrag.init(), which re-queries live element references it
// holds onto for drag state -- this listener holds no element references
// between clicks, so there's nothing to go stale).

(function () {
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest(".month-more-link");
    if (!trigger) return;
    e.preventDefault();

    const dataEl = trigger.nextElementSibling;
    if (!dataEl || dataEl.tagName !== "TEMPLATE") return;
    const links = Array.from(dataEl.content.querySelectorAll("a[data-modal]"));
    if (!links.length) return;

    window.ccToast({
      title: links.length === 1 ? "1 more item" : links.length + " more items",
      className: "toast-overflow",
      persistent: true,
      actions: links.map((a) => ({
        label: a.textContent,
        className: "toast-overflow-item",
        onAction: () => {
          if (window.CCModal) window.CCModal.open(a.getAttribute("href"));
        },
      })),
    });
  });
})();
