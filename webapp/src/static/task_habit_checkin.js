// Tasks > Habits check-in row (templates/tasks_habits.html) -- fetch-based
// instead of a full-page-reloading form submit, same reasoning and exact
// same shape as static/habit_checkin.js (the standalone Habits feature's
// Dashboard widget): a habit-labeled *task*'s checkbox/count+"+1" row
// posts to /tasks/{uid}/completion(s) instead of /habits/{uid}/entries,
// but the optimistic-update/revert-on-failure behavior is identical, so
// this is a close mirror of that file rather than a generalized shared
// script -- the two id/field-name differences (#task-habit-checkin-list,
// `completion_date` instead of `entry_date`) weren't worth threading
// through a config parameter for one file each.
(function () {
  function init(root) {
    const list = (root || document).querySelector("#task-habit-checkin-list") || document.getElementById("task-habit-checkin-list");
    if (!list || list.dataset.ccWired) return;
    list.dataset.ccWired = "1";

    async function post(url, body) {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body || "",
      });
      if (!resp.ok) throw new Error("habit-task update failed");
    }

    list.querySelectorAll(".habit-checkin-toggle").forEach((form) => {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const btn = form.querySelector("button");
        const use = btn.querySelector("use");
        const wasDone = btn.classList.contains("is-done");
        btn.classList.toggle("is-done", !wasDone);
        if (use) use.setAttribute("href", wasDone ? "#icon-square" : "#icon-check-square");
        btn.title = wasDone ? "Mark done today" : "Done today -- click to undo";
        try {
          await post(form.action, "");
        } catch (err) {
          btn.classList.toggle("is-done", wasDone);
          if (use) use.setAttribute("href", wasDone ? "#icon-check-square" : "#icon-square");
          window.ccToast({ message: "Could not save that. Try again.", variant: "error" });
        }
      });
    });

    list.querySelectorAll(".habit-checkin-plus").forEach((form) => {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const row = form.closest(".habit-checkin-row");
        const target = parseInt(row.dataset.target, 10) || 1;
        const countEl = row.querySelector(".habit-checkin-count");
        const resetForm = row.querySelector(".habit-checkin-reset");
        const nextValue = parseInt(form.dataset.value, 10) || 1;
        const [prevCurrent] = (countEl.textContent || "0/0").split("/").map((n) => parseInt(n, 10) || 0);
        const completionDate = form.querySelector('input[name="completion_date"]').value;
        const body = `completion_date=${encodeURIComponent(completionDate)}&value=${encodeURIComponent(nextValue)}`;

        countEl.textContent = `${nextValue}/${target}`;
        if (resetForm) resetForm.style.display = "";
        form.dataset.value = String(nextValue + 1);
        form.querySelector('input[name="value"]').value = String(nextValue + 1);

        try {
          await post(form.action, body);
        } catch (err) {
          countEl.textContent = `${prevCurrent}/${target}`;
          if (resetForm && prevCurrent === 0) resetForm.style.display = "none";
          form.dataset.value = String(nextValue);
          form.querySelector('input[name="value"]').value = String(nextValue);
          window.ccToast({ message: "Could not save that. Try again.", variant: "error" });
        }
      });
    });

    list.querySelectorAll(".habit-checkin-reset").forEach((form) => {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const row = form.closest(".habit-checkin-row");
        const target = parseInt(row.dataset.target, 10) || 1;
        const countEl = row.querySelector(".habit-checkin-count");
        const plusForm = row.querySelector(".habit-checkin-plus");
        const prevText = countEl.textContent;

        countEl.textContent = `0/${target}`;
        form.style.display = "none";
        if (plusForm) {
          plusForm.dataset.value = "1";
          plusForm.querySelector('input[name="value"]').value = "1";
        }

        try {
          await post(form.action, "");
        } catch (err) {
          countEl.textContent = prevText;
          form.style.display = "";
          window.ccToast({ message: "Could not save that. Try again.", variant: "error" });
        }
      });
    });
  }

  window.CCTaskHabitCheckin = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();

// "View full year" expand toggle (templates/tasks_habits.html, 2026-08-08
// direct feedback) -- each habit-task card renders both a half-year and a
// full-year heatmap up front (routers/tasks.py's habits_view computes
// both so this is a pure client-side swap, no extra request). Toggling
// swaps which one is visible and adds/removes `.is-expanded` on the card,
// which style.css's `.habit-card.is-expanded{grid-column:1 / -1}` uses to
// span the full grid row -- pushing whatever sibling card was sharing
// that row down to the next one. Only one card expanded at a time (same
// "opening a new one closes whatever was open" pattern as app.js's
// .multiselect) so the grid never has two full-width rows fighting for
// attention.
(function () {
  let expandedBtn = null;

  function collapse(btn) {
    const card = document.getElementById("habit-card-" + btn.dataset.uid);
    if (!card) return;
    card.classList.remove("is-expanded");
    card.querySelector(".habit-card-heatmap-full").hidden = true;
    card.querySelector(".habit-card-heatmap-half").hidden = false;
    btn.setAttribute("aria-expanded", "false");
    btn.querySelector(".habit-card-expand-label").textContent = "View full year";
    if (expandedBtn === btn) expandedBtn = null;
  }

  function expand(btn) {
    const card = document.getElementById("habit-card-" + btn.dataset.uid);
    if (!card) return;
    if (expandedBtn && expandedBtn !== btn) collapse(expandedBtn);
    card.classList.add("is-expanded");
    card.querySelector(".habit-card-heatmap-half").hidden = true;
    card.querySelector(".habit-card-heatmap-full").hidden = false;
    btn.setAttribute("aria-expanded", "true");
    btn.querySelector(".habit-card-expand-label").textContent = "View 6 months";
    expandedBtn = btn;
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".habit-card-expand-btn");
    if (!btn) return;
    if (btn.getAttribute("aria-expanded") === "true") collapse(btn);
    else expand(btn);
  });
})();
