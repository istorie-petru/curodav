// Habit check-ins wherever a habit row renders (habits H2 page, H4
// Dashboard widget) -- every check-in / day toggle is a plain POST form
// (`form.habit-action`, the no-JS fallback). This submits it with fetch
// and re-renders the region it sits in from the server, so streaks and
// the to-do order are always the server's own numbers:
//   - on /habits: #habits-body from /habits/regions
//   - in a Dashboard/label-page widget: that .widget-card from
//     /dashboard/widgets/<uid>
// Also re-renders /habits after a habit is created/edited/deleted in a
// modal (cc-entity-changed, type "task"); widget cards already get that
// from async_crud.js (the widget declares uses: tasks).
(function () {
  function regionFor(form) {
    const page = form.closest("#habits-body");
    if (page) return { url: "/habits/regions", id: "habits-body" };
    const card = form.closest(".widget-card[data-uid]");
    if (card && card.id) return { url: "/dashboard/widgets/" + card.dataset.uid, id: card.id };
    return null;
  }

  document.addEventListener("submit", async (e) => {
    const form = e.target;
    if (!form.matches || !form.matches("form.habit-action")) return;
    // The widget builder's live preview renders real rows -- a click there
    // must not post (or navigate away from the builder).
    if (form.closest(".widget-preview-content, .widget-preview-card")) {
      e.preventDefault();
      return;
    }
    const region = regionFor(form);
    if (!region) return; // not in a live region -- plain form post
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
      await window.ccApi.refreshRegion(region.url, region.id);
    } catch (err) {
      if (btn) btn.disabled = false;
      window.ccToast({ message: "Could not save that. Try again.", variant: "error" });
    }
  });

  document.addEventListener("cc-entity-changed", (e) => {
    const detail = e.detail || {};
    if (detail.type !== "task" || !document.getElementById("habits-body")) return;
    detail.claimed = true;
    window.ccApi.refreshRegion("/habits/regions", "habits-body").catch(() => window.location.reload());
  });
})();
