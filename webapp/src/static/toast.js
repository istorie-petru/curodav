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

  function ccToast({ message, title, icon, className, actions, actionLabel, onAction, duration = 4500, variant = "default", persistent = false, typedConfirm }) {
    const config = VARIANT_CONFIG[variant] || VARIANT_CONFIG.default;
    const phrase = window.ccPhrase || ((t) => t);
    message = phrase(message);
    title = phrase(title);
    const titleText = title || config.title;
    const key = dedupeKey({ variant, title: titleText, message });
    const now = Date.now();
    if (!persistent && recent.has(key) && now - recent.get(key) < BARRIER_MS) {
      return { dismiss: () => {}, set: () => false, isAlive: () => false };
    }
    if (!persistent) recent.set(key, now);

    const el = document.createElement("div");
    el.className = "toast" + (variant !== "default" ? " toast-" + variant : "") + (className ? " " + className : "");
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
    const bodyEl = document.createElement("span");
    bodyEl.className = "toast-body";
    bodyEl.hidden = !message;
    bodyEl.textContent = message || "";
    content.appendChild(bodyEl);

    let typedInput = null;
    if (typedConfirm) {
      const typedWrap = document.createElement("span");
      typedWrap.className = "toast-typed-confirm";
      typedInput = document.createElement("input");
      typedInput.type = "text";
      typedInput.className = "toast-typed-input";
      typedInput.autocomplete = "off";
      typedInput.spellcheck = false;
      typedInput.placeholder = typedConfirm.placeholder || typedConfirm.matchValue;
      typedInput.setAttribute(
        "aria-label",
        typedConfirm.ariaLabel || ('Type "' + typedConfirm.matchValue + '" to confirm')
      );
      typedWrap.appendChild(typedInput);
      content.appendChild(typedWrap);
    }

    let gatedButtons = [];
    if (actions && actions.length) {
      const row = document.createElement("span");
      row.className = "toast-actions";
      actions.forEach((a) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "toast-action" + (a.className ? " " + a.className : "");
        btn.textContent = a.label;
        if (a.gated) {
          btn.disabled = true;
          gatedButtons.push(btn);
        }
        btn.addEventListener("click", () => {
          if (btn.disabled) return;
          if (a.onAction) a.onAction();
          dismiss();
        });
        row.appendChild(btn);
      });
      content.appendChild(row);
    }
    el.appendChild(content);

    if (typedConfirm && typedInput) {
      typedInput.addEventListener("input", () => {
        const armed = typedInput.value === typedConfirm.matchValue;
        gatedButtons.forEach((btn) => { btn.disabled = !armed; });
        typedInput.classList.toggle("is-armed", armed);
      });
      typedInput.addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        const armedBtn = gatedButtons.find((btn) => !btn.disabled);
        if (armedBtn) armedBtn.click();
      });
      requestAnimationFrame(() => typedInput.focus());
    }

    let dismissed = false;
    let timer = null;
    let currentRatio = 1; // bar width fraction at the start of the current arm
    let remaining = 0; // ms budget of the current arm
    let deadline = 0; // performance.now() when the current arm ends

    // Expiry bar -- drains 100% -> 0% in lockstep with the countdown below.
    // Skipped for persistent toasts (no countdown to track, see arm below).
    let progress = null;
    if (!persistent) {
      progress = document.createElement("span");
      progress.className = "toast-progress";
      progress.setAttribute("aria-hidden", "true");
      el.appendChild(progress);
    }

    function tick() {
      const left = deadline - performance.now();
      if (left <= 0) {
        dismiss();
        return;
      }
      if (progress) progress.style.transform = "scaleX(" + currentRatio * (left / remaining) + ")";
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
    // continues from exactly that width on leave. Persistent toasts have no
    // countdown, so hover-pause is a no-op and the handlers are skipped.
    if (!persistent) {
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

    // In-place content update -- used by persistent status toasts
    // (offline_status.js's sync indicator) to change what the toast says
    // without flashing a fresh element in and out on every status change.
    // Returns false if the toast has already been dismissed (the caller
    // should then create a new one rather than assume the old is live).
    function set(newOpts) {
      if (dismissed) return false;
      const cfg = VARIANT_CONFIG[newOpts.variant] || VARIANT_CONFIG.default;
      el.classList.remove("toast-error", "toast-warning", "toast-default");
      if (newOpts.variant && newOpts.variant !== "default") el.classList.add("toast-" + newOpts.variant);
      chip.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#icon-' + (newOpts.icon || cfg.icon) + '"></use></svg>';
      titleEl.textContent = newOpts.title || cfg.title;
      if (newOpts.message) {
        bodyEl.textContent = newOpts.message;
        bodyEl.hidden = false;
      } else {
        bodyEl.hidden = true;
      }
      return true;
    }

    if (!persistent) arm(duration);
    return { dismiss, set, isAlive: () => !dismissed };
  }

  // Confirm sheet: the "are you sure?" prompt for destructive actions that
  // genuinely can't be undone (cascading deletes), rendered as a persistent
  // toast in the bottom-right stack -- same look as every other toast, so a
  // confirmation reads as part of the app's normal notification language
  // rather than a button-anchored popover. One at a time; Cancel (or Escape
  // or the toast's own ✕) dismisses without running onConfirm, the
  // filled-danger button runs it. The `anchor` param is kept for API
  // compatibility with every existing caller but no longer positions
  // anything (the toast lives in the stack).
  let openConfirm = null;
  function closeConfirm() {
    if (!openConfirm) return;
    openConfirm.dismiss();
    openConfirm = null;
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && openConfirm) closeConfirm();
  });

  function ccConfirmSheet({ anchor, message, confirmLabel = "Delete", onConfirm, typedConfirm }) {
    closeConfirm();
    openConfirm = ccToast({
      title: "Please confirm",
      message,
      variant: "error",
      persistent: true,
      className: "toast-confirm" + (typedConfirm ? " toast-confirm-typed" : ""),
      typedConfirm,
      actions: [
        { label: "Cancel", className: "toast-confirm-cancel", onAction: () => {} },
        { label: confirmLabel, className: "toast-confirm-ok", onAction: onConfirm, gated: !!typedConfirm },
      ],
    });
    if (!openConfirm || !openConfirm.isAlive()) openConfirm = null;
  }

  // The script-built twin of the empty_state macro: same classes, same markup.
  function ccEmptyState(title, tag) {
    const el = document.createElement(tag || "div");
    el.className = "empty-state empty-state-compact";
    const text = document.createElement("div");
    text.className = "empty-state-title";
    text.textContent = title;
    el.appendChild(text);
    return el;
  }

  window.ccToast = ccToast;
  window.ccConfirmSheet = ccConfirmSheet;
  window.ccEmptyState = ccEmptyState;

  // A redirect carries its message as ?note= / ?error=; the template renders it
  // as a [data-dm-flash] banner (the no-JS fallback) and this turns it into a toast.
  function flashToToast() {
    const flashes = document.querySelectorAll("[data-dm-flash]");
    if (!flashes.length) return;
    flashes.forEach((el) => {
      ccToast({
        message: el.textContent.trim(),
        variant: el.getAttribute("data-dm-flash") === "error" ? "error" : "default",
      });
      el.remove();
    });
    if (window.history && window.history.replaceState) {
      const url = new URL(window.location.href);
      url.searchParams.delete("note");
      url.searchParams.delete("error");
      window.history.replaceState({}, document.title, url.pathname + url.search + url.hash);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", flashToToast);
  else flashToToast();
})();
