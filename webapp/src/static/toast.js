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
(function () {
  const stack = document.createElement("div");
  stack.className = "toast-stack";
  stack.setAttribute("aria-live", "polite");
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(stack));

  function ccToast({ message, actionLabel, onAction, duration = 4500, variant = "default" }) {
    const el = document.createElement("div");
    el.className = "toast" + (variant !== "default" ? " toast-" + variant : "");

    const msg = document.createElement("span");
    msg.className = "toast-message";
    msg.textContent = message;
    el.appendChild(msg);

    let dismissed = false;
    let timer;
    function dismiss() {
      if (dismissed) return;
      dismissed = true;
      clearTimeout(timer);
      el.classList.remove("is-in");
      el.addEventListener("transitionend", () => el.remove(), { once: true });
      setTimeout(() => el.remove(), 400); // fallback if transitionend never fires
    }

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
    timer = setTimeout(dismiss, duration);
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
