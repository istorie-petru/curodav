// "+N more" overflow on Month/4-Week's day cells (templates/
// _calendar_month_grid.html / _calendar_fourweek_grid.html).
//
// History: 2026-09-09 (FullCalendar-parity interactions slice 3) turned the
// old `<a href="/calendar/day/...">` into a `<button>` that popped a
// ccToast listing the hidden titles. 2026-09-25 (UI audit C-10): that toast
// was the green success toast, bottom-right, far from the day, with no
// date and no times -- replaced by a real popover anchored on the day
// cell (a bottom sheet at <=720px), the way Google/Apple calendars do it:
//   * title = the day's date, then every row of that day (colour dot or
//     task icon, time, title), each opening its own modal through
//     modal.js's document-level [data-modal] delegation;
//   * an "Open day" link to the Day view;
//   * Esc, the close button, or a click outside closes it and focus goes
//     back to the "+N more" button; opening moves focus into it.
//
// The rows are never fetched -- each day cell with an overflow renders an
// inert `<template class="month-overflow-data">` carrying `data-title`,
// `data-day-url` and one `a.cal-pop-row` per row, built server-side with
// the same href logic as the visible rows (see that template's comment).
//
// One document-level delegated listener: works on both grids and survives
// async_calendar.js's region swaps with no re-init (it holds no element
// references between clicks except the one open popover, which closes on
// any calendar change).
(function () {
  let open = null; // { el, trigger, backdrop }

  function close(restoreFocus) {
    if (!open) return;
    const { el, trigger, backdrop } = open;
    open = null;
    el.remove();
    if (backdrop) backdrop.remove();
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("pointerdown", onOutside, true);
    if (restoreFocus && trigger && document.contains(trigger)) trigger.focus();
  }

  function onKey(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close(true);
    }
  }

  function onOutside(e) {
    if (!open) return;
    if (open.el.contains(e.target)) return;
    if (e.target.closest(".month-more-link") === open.trigger) return; // the toggle click handles it
    close(false);
  }

  function isPhone() {
    return window.matchMedia("(max-width:720px)").matches;
  }

  function position(el, anchor) {
    // Google-style: the popover sits over the day cell's own top-left,
    // widened past it, clamped inside the viewport with an 8px margin.
    const r = anchor.getBoundingClientRect();
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    const vw = document.documentElement.clientWidth;
    const vh = window.innerHeight;
    let left = r.left + (r.width - w) / 2;
    let top = r.top - 4;
    left = Math.max(8, Math.min(vw - w - 8, left));
    top = Math.max(8, Math.min(vh - h - 8, top));
    el.style.left = left + "px";
    el.style.top = top + "px";
  }

  function build(dataEl) {
    const el = document.createElement("div");
    el.className = "cal-popover";
    el.setAttribute("role", "dialog");
    const titleId = "cal-popover-title";
    el.setAttribute("aria-labelledby", titleId);

    const head = document.createElement("div");
    head.className = "cal-popover-head";
    const h = document.createElement("h2");
    h.className = "cal-popover-title";
    h.id = titleId;
    h.tabIndex = -1;
    h.textContent = dataEl.dataset.title || "";
    const x = document.createElement("button");
    x.type = "button";
    x.className = "icon-btn cal-popover-close";
    x.setAttribute("aria-label", "Close");
    x.title = "Close";
    x.textContent = "×";
    x.addEventListener("click", () => close(true));
    head.append(h, x);

    const list = document.createElement("div");
    list.className = "cal-popover-list";
    list.appendChild(dataEl.content.cloneNode(true));
    // Opening a row's modal closes the popover (modal.js handles the click).
    list.addEventListener("click", (e) => {
      if (e.target.closest("a[data-modal]")) close(false);
    });

    el.append(head, list);
    if (dataEl.dataset.dayUrl) {
      const foot = document.createElement("div");
      foot.className = "cal-popover-foot";
      const a = document.createElement("a");
      a.href = dataEl.dataset.dayUrl;
      a.className = "cal-popover-day-link";
      a.textContent = "Open day";
      foot.appendChild(a);
      el.appendChild(foot);
    }
    return el;
  }

  document.addEventListener("click", (e) => {
    const trigger = e.target.closest(".month-more-link");
    if (!trigger) return;
    e.preventDefault();
    if (open && open.trigger === trigger) {
      close(true);
      return;
    }
    close(false);

    const dataEl = trigger.nextElementSibling;
    if (!dataEl || dataEl.tagName !== "TEMPLATE") return;

    const el = build(dataEl);
    let backdrop = null;
    if (isPhone()) {
      el.classList.add("is-sheet");
      backdrop = document.createElement("div");
      backdrop.className = "cal-popover-backdrop";
      backdrop.addEventListener("click", () => close(true));
      document.body.appendChild(backdrop);
      document.body.appendChild(el);
    } else {
      document.body.appendChild(el);
      position(el, trigger.closest(".month-day-cell") || trigger);
    }
    open = { el, trigger, backdrop };
    trigger.setAttribute("aria-expanded", "true");
    const first = el.querySelector(".cal-pop-row") || el.querySelector(".cal-popover-title");
    if (first) first.focus();
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onOutside, true);
  });

  // A calendar change re-renders the grid under the popover -- its rows
  // could be stale, so just close it.
  document.addEventListener("cc-entity-changed", () => close(false));
  window.addEventListener("resize", () => {
    if (open && !open.el.classList.contains("is-sheet")) close(false);
  });
})();
