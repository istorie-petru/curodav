// Habit day "amount" popup + work-sessions disclosure memory (2026-09-25,
// Peter: a clickable heatmap that's "smarter" for habits that demand more
// than one unit). Loaded app-wide (base.html) because the habit view
// modal can open over any page.
//
// Any `.habit-amount-trigger` (a day cell in the habit view modal's year
// heatmap / month calendar, or the Habits page / widget 7-day strip, for
// an amount habit) opens one small native <dialog> with a single number
// box -- the placeholder is the habit's daily target, and Enter on an
// empty box logs exactly that. 0 clears the day. Posts to the habit's
// explicit-value endpoint (/tasks/<uid>/completions), then refreshes:
// inside the view modal, the modal re-renders in place (and the page
// catches up when it closes); elsewhere, a task change event lets the
// page's own live region (#habits-body, widget cards, day grid) refresh.
(function () {
  let dialog, form, input, label, current;

  function build() {
    dialog = document.createElement("dialog");
    dialog.className = "habit-amount-dialog";
    dialog.innerHTML =
      '<form class="habit-amount-form" method="dialog">' +
      '<label class="habit-amount-label" for="habit-amount-input"></label>' +
      '<input id="habit-amount-input" type="number" name="value" min="0" max="999999" step="1" inputmode="numeric">' +
      '<div class="habit-amount-actions">' +
      '<button type="button" class="btn ghost btn-sm" data-habit-amount-cancel>Cancel</button>' +
      '<button type="submit" class="btn primary btn-sm">Save</button>' +
      "</div></form>";
    document.body.appendChild(dialog);
    form = dialog.querySelector("form");
    input = dialog.querySelector("input");
    label = dialog.querySelector("label");
    dialog.querySelector("[data-habit-amount-cancel]").addEventListener("click", () => dialog.close());
    // Escape closes just this popup, never the modal underneath
    // (modal.js listens for Escape on the document).
    dialog.addEventListener("keydown", (e) => {
      if (e.key === "Escape") e.stopPropagation();
    });
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) dialog.close(); // backdrop
    });
    form.addEventListener("submit", onSubmit);
  }

  function prettyDate(iso) {
    const d = new Date(iso + "T12:00:00");
    return isNaN(d) ? iso : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  }

  function open(trigger) {
    if (!dialog) build();
    current = trigger;
    const unit = trigger.dataset.unit || "";
    label.textContent = prettyDate(trigger.dataset.date) + (unit ? " -- " + unit : "");
    input.placeholder = trigger.dataset.target || "1";
    input.value = trigger.dataset.value || "";
    dialog.showModal();
    input.focus();
    input.select();
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (!current) return;
    const raw = input.value.trim();
    const value = raw === "" ? current.dataset.target || "1" : raw;
    const body = new FormData();
    body.append("completion_date", current.dataset.date);
    body.append("value", value);
    const inModal = !!current.closest("#modal-overlay");
    try {
      const resp = await fetch(current.dataset.url, { method: "POST", headers: { "X-Requested-With": "fetch" }, body });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.error || "Could not save that.");
      }
      dialog.close();
      if (inModal && window.CCModal) {
        window.CCModal.markChangedWith({ type: "task", action: "checkin" });
        await window.CCModal.refresh();
      } else if (!(window.ccApi && window.ccApi.dispatchChange({ type: "task", action: "checkin" }))) {
        window.location.reload();
      }
    } catch (err) {
      window.ccToast && window.ccToast({ message: err.message, variant: "error" });
    }
  }

  document.addEventListener("click", (e) => {
    const trigger = e.target.closest && e.target.closest(".habit-amount-trigger");
    if (!trigger) return;
    e.preventDefault();
    open(trigger);
  });

  // Work sessions in the habit view modal are collapsed by default; once
  // opened for a habit, keep them open across that modal's in-place
  // refreshes (a keep-open form re-renders the whole modal body).
  const openSessions = new Set();
  document.addEventListener(
    "toggle",
    (e) => {
      const el = e.target;
      if (!el.matches || !el.matches("details.habit-work-sessions")) return;
      if (el.open) openSessions.add(el.dataset.uid);
      else openSessions.delete(el.dataset.uid);
    },
    true
  );
  new MutationObserver(() => {
    if (!openSessions.size) return;
    const overlay = document.getElementById("modal-overlay");
    if (!overlay || !overlay.classList.contains("is-open")) {
      openSessions.clear(); // modal closed: collapsed again next time
      return;
    }
    document.querySelectorAll("details.habit-work-sessions:not([open])").forEach((el) => {
      if (openSessions.has(el.dataset.uid)) el.open = true;
    });
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
