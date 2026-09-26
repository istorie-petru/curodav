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

  // 2026-09-25 (UI audit H-17): the popup opens next to the day that was
  // tapped (below it, or above when there's no room), clamped to the
  // viewport -- it used to open centred on the screen, far from the chip.
  // Set through the CSSOM (allowed under the CSP; inline style="" isn't).
  function place(trigger) {
    const r = trigger.getBoundingClientRect();
    const box = dialog.getBoundingClientRect();
    const gap = 8;
    const vw = document.documentElement.clientWidth;
    const vh = window.innerHeight;
    let top = r.bottom + gap;
    if (top + box.height > vh - gap) top = Math.max(gap, r.top - gap - box.height);
    const left = Math.min(Math.max(gap, r.left + r.width / 2 - box.width / 2), vw - box.width - gap);
    dialog.classList.add("is-anchored");
    dialog.style.top = Math.round(top) + "px";
    dialog.style.left = Math.round(left) + "px";
  }

  function open(trigger) {
    if (!dialog) build();
    current = trigger;
    const unit = trigger.dataset.unit || "";
    label.textContent = prettyDate(trigger.dataset.date) + (unit ? " \u00b7 " + unit : "");
    input.placeholder = trigger.dataset.target || "1";
    input.value = trigger.dataset.value || "";
    dialog.showModal();
    place(trigger);
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

  // 2026-09-25 (UI audit H-14): the habit form hides its build-only
  // fields (Unit, Recurrence, days, target) while Kind is "Avoid"
  // (style.css .habit-task-form.is-avoid). Delegated: the form arrives
  // in a modal after this script loaded.
  // 2026-09-26: Kind is two radio pills now, and "How often" shows only
  // its own sub-row (weekday chips / times count) via data-repeat.
  document.addEventListener("change", (e) => {
    const el = e.target;
    if (!el || !el.closest) return;
    // Dropdown radios are portaled out of the form while open (app.js),
    // so find it through their form="" attribute, not the DOM.
    const form = el.form || el.closest(".habit-task-form");
    if (!form || !form.classList.contains("habit-task-form")) return;
    if (el.name === "habit_kind") form.classList.toggle("is-avoid", el.value === "avoid");
    // Which follow-up field shows next to How often / Daily goal.
    if (el.name === "habit_repeat") form.dataset.repeat = el.value;
    if (el.name === "habit_goal") form.dataset.goal = el.value;
    if (el.name === "habit_days") daysSummary(form);
  });

  // 2026-09-26: the Habits page row's chevron opens its history panel
  // (heatmap or week/month grid + insights) under the row. Open rows are
  // remembered by uid so they stay open when #habits-body re-renders
  // after a check-in.
  const openRows = new Set();
  function setRow(btn, open) {
    const panel = document.getElementById(btn.getAttribute("aria-controls"));
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (panel) panel.hidden = !open;
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest && e.target.closest(".habit-expand");
    if (!btn) return;
    const uid = btn.closest(".habit-card").dataset.uid;
    const open = btn.getAttribute("aria-expanded") !== "true";
    if (open) openRows.add(uid);
    else openRows.delete(uid);
    setRow(btn, open);
  });
  new MutationObserver(() => {
    if (!openRows.size) return;
    document.querySelectorAll('.habit-expand[aria-expanded="false"]').forEach((btn) => {
      if (openRows.has(btn.closest(".habit-card").dataset.uid)) setRow(btn, true);
    });
  }).observe(document.documentElement, { childList: true, subtree: true });

  // The Days dropdown's trigger reads like habit_view.days_label: "Every
  // day" / "Weekdays" / "Weekends" / "Mon, Wed, Fri" / "Pick days". Runs
  // after app.js's generic "N selected" summary (same change event,
  // registered later) and once per form that appears.
  function daysSummary(form) {
    const summary = form.querySelector(".habit-days-select .ms-summary");
    if (!summary) return;
    const boxes = Array.from(document.querySelectorAll('input[name="habit_days"][form="' + form.id + '"]'));
    const on = boxes.filter((b) => b.checked).map((b) => b.value);
    const set = new Set(on);
    const same = (list) => list.length === on.length && list.every((d) => set.has(d));
    let text;
    if (!on.length) text = "Pick days";
    else if (on.length === 7) text = "Every day";
    else if (same(["MO", "TU", "WE", "TH", "FR"])) text = "Weekdays";
    else if (same(["SA", "SU"])) text = "Weekends";
    else text = boxes.filter((b) => b.checked).map((b) => b.dataset.short).join(", ");
    summary.textContent = text;
  }
  new MutationObserver(() => {
    document.querySelectorAll(".habit-task-form:not([data-days-ready])").forEach((form) => {
      form.dataset.daysReady = "1";
      daysSummary(form);
    });
  }).observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".habit-task-form").forEach(daysSummary);
  });
})();
