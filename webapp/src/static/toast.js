// Generic toast/snackbar component, replacing native alert()/confirm() app-
// wide (see app.js's delete/archive handlers and modal.js's error paths).
// Native dialogs were the one thing in this app that didn't look like this
// app -- every save-error and every delete used the browser's own unstyled
// system popup, breaking the illusion the rest of the design system built.
//
// Two things live here:
//   window.ccToast(opts)         -- a dismissible message, optionally with
//                                    one action button (e.g. "Undo").
//   window.ccConfirmSheet(opts)  -- a small popover asking "are you sure"
//                                    for destructive actions that genuinely
//                                    can't be undone (cascading deletes),
//                                    styled like the rest of the app instead
//                                    of the OS's confirm() box.
//
// Toast anatomy (2026-08-16 rework): a tinted status icon chip (derived from
// `variant`, overridable via `icon`), a bold short `title` header, an
// optional short `message` body, an optional action button, and a close ✕.
// A thin `.toast-progress` bar across the bottom edge drains 100% -> 0% over
// the auto-dismiss countdown, so "how long until this goes away" is always
// visible (it freezes with the countdown while hovered). Duplicate
// suppression (a small time barrier: the same variant+title+message shown
// again within BARRIER_MS is dropped) and hover-pause (hovering a toast
// stops its countdown; leaving restarts it with a short grace so it still
// goes away on its own) were both direct feedback asks.
(function () {
  const stack = document.createElement("div");
  stack.className = "toast-stack";
  stack.setAttribute("aria-live", "polite");
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(stack));

  const VARIANT_CONFIG = {
    default: { icon: "check-circle", title: "Done" },
    error: { icon: "alert-circle", title: "Something went wrong" },
    warning: { icon: "alert-triangle", title: "Heads up" },
  };
  const BARRIER_MS = 4000;
  const HOVER_GRACE_MS = 2500;
  const recent = new Map(); // dedupe key -> last-shown timestamp

  function dedupeKey({ variant, title, message }) {
    return [variant, title, message].join("|");
  }

  function ccToast({ message, title, icon, actionLabel, onAction, duration = 4500, variant = "default" }) {
    const config = VARIANT_CONFIG[variant] || VARIANT_CONFIG.default;
    const titleText = title || config.title;
    const key = dedupeKey({ variant, title: titleText, message });
    const now = Date.now();
    if (recent.has(key) && now - recent.get(key) < BARRIER_MS) {
      return { dismiss: () => {} };
    }
    recent.set(key, now);

    const el = document.createElement("div");
    el.className = "toast" + (variant !== "default" ? " toast-" + variant : "");
    el.setAttribute("role", "status");

    const chip = document.createElement("span");
    chip.className = "toast-icon";
    chip.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#icon-' + (icon || config.icon) + '"></use></svg>';
    el.appendChild(chip);

    const content = document.createElement("span");
    content.className = "toast-content";
    const titleEl = document.createElement("span");
    titleEl.className = "toast-title";
    titleEl.textContent = titleText;
    content.appendChild(titleEl);
    if (message) {
      const bodyEl = document.createElement("span");
      bodyEl.className = "toast-body";
      bodyEl.textContent = message;
      content.appendChild(bodyEl);
    }
    el.appendChild(content);

    let dismissed = false;
    let timer = null;
    let currentRatio = 1; // bar width fraction at the start of the current arm
    let remaining = 0; // ms budget of the current arm
    let deadline = 0; // performance.now() when the current arm ends

    // Expiry bar -- drains 100% -> 0% in lockstep with the countdown below.
    const progress = document.createElement("span");
    progress.className = "toast-progress";
    progress.setAttribute("aria-hidden", "true");
    el.appendChild(progress);

    function tick() {
      const left = deadline - performance.now();
      if (left <= 0) {
        dismiss();
        return;
      }
      progress.style.transform = "scaleX(" + currentRatio * (left / remaining) + ")";
      timer = requestAnimationFrame(tick);
    }

    function clear() {
      if (timer != null) cancelAnimationFrame(timer);
      timer = null;
    }

    function dismiss() {
      if (dismissed) return;
      dismissed = true;
      clear();
      el.classList.remove("is-in");
      el.addEventListener("transitionend", () => el.remove(), { once: true });
      setTimeout(() => el.remove(), 400); // fallback if transitionend never fires
    }

    function arm(ms) {
      clear();
      remaining = Math.max(0, ms);
      if (remaining === 0) {
        dismiss();
        return;
      }
      deadline = performance.now() + remaining;
      timer = requestAnimationFrame(tick);
    }

    // Pause while hovered -- a toast under the cursor must not vanish; the
    // countdown (and the expiry bar with it) only resumes once the pointer
    // leaves, capped at a short grace so a read-at-leisure toast still
    // auto-dismisses. The bar freezes at its current width on enter and
    // continues from exactly that width on leave.
    el.addEventListener("mouseenter", () => {
      if (dismissed) return;
      const left = deadline - performance.now();
      if (left <= 0) {
        dismiss();
        return;
      }
      currentRatio = currentRatio * (left / remaining);
      remaining = left;
      clear();
    });
    el.addEventListener("mouseleave", () => {
      if (dismissed) return;
      arm(Math.min(remaining, HOVER_GRACE_MS));
    });

    if (actionLabel && onAction) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "toast-action";
      btn.textContent = actionLabel;
      btn.addEventListener("click", () => {
        onAction();
        dismiss();
      });
      el.appendChild(btn);
    }

    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss");
    close.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-x"></use></svg>';
    close.addEventListener("click", dismiss);
    el.appendChild(close);

    stack.appendChild(el);
    requestAnimationFrame(() => el.classList.add("is-in"));
    arm(duration);
    return { dismiss };
  }

  // Confirm sheet: a small anchored popover (not a full modal -- this is a
  // yes/no on one action, not a form) with a Cancel + filled-danger Confirm
  // button. Only one open at a time, closes on outside click/Escape, same
  // interaction contract as the existing .multiselect pattern in app.js.
  let openSheet = null;
  function closeSheet() {
    if (!openSheet) return;
    openSheet.remove();
    openSheet = null;
  }
  document.addEventListener("click", (e) => {
    if (openSheet && !openSheet.contains(e.target) && !e.target.closest("[data-confirm-sheet-anchor]")) {
      closeSheet();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSheet();
  });

  function ccConfirmSheet({ anchor, message, confirmLabel = "Delete", onConfirm }) {
    closeSheet();
    const sheet = document.createElement("div");
    sheet.className = "confirm-sheet";
    sheet.setAttribute("role", "alertdialog");

    const text = document.createElement("p");
    text.className = "confirm-sheet-text";
    text.textContent = message;
    sheet.appendChild(text);

    const row = document.createElement("div");
    row.className = "confirm-sheet-actions";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "btn ghost btn-sm";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", closeSheet);
    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.className = "btn danger btn-sm";
    confirmBtn.textContent = confirmLabel;
    confirmBtn.addEventListener("click", () => {
      closeSheet();
      onConfirm();
    });
    row.appendChild(cancelBtn);
    row.appendChild(confirmBtn);
    sheet.appendChild(row);

    document.body.appendChild(sheet);
    const r = anchor.getBoundingClientRect();
    const sheetW = 260;
    let left = r.left + window.scrollX;
    if (left + sheetW > window.scrollX + document.documentElement.clientWidth - 12) {
      left = window.scrollX + document.documentElement.clientWidth - sheetW - 12;
    }
    sheet.style.left = Math.max(12, left) + "px";
    sheet.style.top = r.bottom + window.scrollY + 6 + "px";
    requestAnimationFrame(() => sheet.classList.add("is-open"));
    openSheet = sheet;
    anchor.setAttribute("data-confirm-sheet-anchor", "");
  }

  window.ccToast = ccToast;
  window.ccConfirmSheet = ccConfirmSheet;
})();
