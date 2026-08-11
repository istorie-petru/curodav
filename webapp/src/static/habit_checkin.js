// Dashboard Habit Check-in widget (_widget_habit_checkin.html) -- fetch-based
// instead of a full-page-reloading form submit (2026-08-01, see
// plans/webapp-action-pipelines-audit.md's "reload per click" finding).
// Checking off a habit updates just its own row; nothing else on the
// Dashboard re-renders. Same semantics as the plain-form fallback these
// forms still are if this script fails to load: a boolean habit's toggle
// endpoint flips "has an entry today" (no entry/zero -> value=1; any
// entry -> removed), so the client can predict the new state exactly
// without waiting for a response body -- POST in the background, flip
// the UI immediately, only revert + toast on an actual failure.

(function () {
  function init(root) {
    const list = (root || document).querySelector("#habit-checkin-list") || document.getElementById("habit-checkin-list");
    if (!list || list.dataset.ccWired) return;
    list.dataset.ccWired = "1";

    async function post(url, body) {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body || "",
      });
      if (!resp.ok) throw new Error("habit update failed");
    }

    list.querySelectorAll(".habit-checkin-toggle").forEach((form) => {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const row = form.closest(".habit-checkin-row");
        const btn = form.querySelector("button");
        const use = btn.querySelector("use");
        const wasDone = btn.classList.contains("is-done");
        // Optimistic -- flip immediately, the endpoint's own semantics
        // (toggle = flip "logged today or not") match this exactly.
        btn.classList.toggle("is-done", !wasDone);
        if (use) use.setAttribute("href", wasDone ? "#icon-square" : "#icon-check-square");
        btn.title = wasDone ? "Mark done today" : "Done today -- click to undo";
        try {
          await post(form.action, "");
        } catch (err) {
          // Revert on failure -- no page reload needed, we already know
          // exactly what to put back.
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
        // Build the POST body from the values *about to be* submitted --
        // read before any of them get mutated below (advancing the
        // form's own `value` input for the *next* click would otherwise
        // leak into this request if read back via `new FormData(form)`
        // after the mutation instead of captured up front).
        const entryDate = form.querySelector('input[name="entry_date"]').value;
        const body = `entry_date=${encodeURIComponent(entryDate)}&value=${encodeURIComponent(nextValue)}`;

        countEl.textContent = `${nextValue}/${target}`;
        if (resetForm) resetForm.style.display = "";
        // The button's own hidden `value` input is the *next* value the
        // server should log if clicked again -- advance it now that this
        // click has consumed the current one, same "pre-compute the next
        // state" contract routers/dashboard.py's _render_habit_checkin
        // already used for the very first (no-JS) click.
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

  window.CCHabitCheckin = { init };
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
