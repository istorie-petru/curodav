// Habits page (habits H2, 2026-09-24) -- every check-in / day toggle on
// #habits-body is a plain POST form (the no-JS fallback); this submits it
// with fetch and re-renders the region from /habits/regions, so streaks,
// the To do / On track split and the 7-day strip are always the server's
// own numbers, never a client-side guess. Also re-renders after a habit is
// created/edited/deleted in a modal (cc-entity-changed, type "task").
(function () {
  const REGION_URL = "/habits/regions";

  function refresh() {
    return window.ccApi.refreshRegion(REGION_URL, "habits-body");
  }

  document.addEventListener("submit", async (e) => {
    const form = e.target;
    if (!form.matches || !form.matches("#habits-body form.habit-action")) return;
    e.preventDefault();
    const btn = form.querySelector("button");
    if (btn) btn.disabled = true;
    try {
      const resp = await fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "fetch" },
        body: new FormData(form),
      });
      if (!resp.ok) throw new Error("habit update failed");
      await refresh();
    } catch (err) {
      if (btn) btn.disabled = false;
      window.ccToast({ message: "Could not save that. Try again.", variant: "error" });
    }
  });

  document.addEventListener("cc-entity-changed", (e) => {
    const detail = e.detail || {};
    if (detail.type !== "task" || !document.getElementById("habits-body")) return;
    detail.claimed = true;
    refresh().catch(() => window.location.reload());
  });
})();
