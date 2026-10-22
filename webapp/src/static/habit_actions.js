(function () {
  let pendingFocus = null; // {regionId, action}

  function regionFor(form) {
    const page = form.closest("#habits-body");
    if (page) return { url: "/habits/regions", id: "habits-body" };
    // The calendar day view already re-renders #day-grid on any task
    // change (async_calendar.js -- keeps scroll, re-binds drag), so just
    // announce one instead of swapping it here.
    if (form.closest("#day-grid")) return { dispatch: true, id: "day-grid" };
    if (form.closest("#sec-region")) return { dispatch: true, id: "sec-region" };
    const card = form.closest(".widget-card[data-uid]");
    if (card && card.id) return { dispatch: true, id: card.id };
    return null;
  }

  async function refresh(region) {
    if (region.dispatch) {
      if (!window.ccApi.dispatchChange({ type: "task", action: "checkin" })) window.location.reload();
      return;
    }
    await window.ccApi.refreshRegion(region.url, region.id);
  }

  async function postForm(url, body) {
    const resp = await fetch(url, { method: "POST", headers: { "X-Requested-With": "fetch" }, body });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.error || "Could not save that. Try again.");
    }
  }

  function restoreFocus(regionId) {
    if (!pendingFocus || pendingFocus.regionId !== regionId) return;
    const region = document.getElementById(regionId);
    const want = pendingFocus.action;
    pendingFocus = null;
    if (!region) return;
    const form = Array.from(region.querySelectorAll("form.habit-action")).find((f) => f.getAttribute("action") === want);
    const btn = form && form.querySelector("button");
    if (!btn) return;
    btn.focus({ preventScroll: true });
    const row = btn.closest(".habit-card");
    if (row) {
      row.scrollIntoView({ block: "nearest" });
      row.classList.add("is-just-updated");
      setTimeout(() => row.classList.remove("is-just-updated"), 1200);
    }
  }

  document.addEventListener("cc-region-swapped", (e) => restoreFocus((e.detail || {}).id));

  function flipToggle(btn) {
    if (!btn || btn.classList.contains("habit-check-avoid")) return null;
    const card = btn.closest(".habit-card");
    const wasDone = btn.classList.contains("is-done");
    const apply = (done) => {
      btn.classList.toggle("is-done", done);
      btn.setAttribute("aria-pressed", done ? "true" : "false");
      if (card) card.classList.toggle("is-done-today", done);
    };
    apply(!wasDone);
    return () => apply(wasDone);
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
    // A plain done/undone toggle shows its result at once and is put back if the save fails.
    const undo = form.classList.contains("habit-toggle") ? flipToggle(btn) : null;
    if (btn && !undo) btn.disabled = true;
    try {
      await postForm(form.action, new FormData(form));
    } catch (err) {
      if (undo) undo();
      if (btn) btn.disabled = false;
      window.ccToast({ message: err.message, variant: "error" });
      return;
    }
    pendingFocus = { regionId: region.id, action: form.getAttribute("action") };
    try {
      await refresh(region);
    } catch (err) {
      window.location.reload();
    }
  });

  document.addEventListener("cc-entity-changed", (e) => {
    const detail = e.detail || {};
    if (detail.type !== "task" || !document.getElementById("habits-body")) return;
    detail.claimed = true;
    window.ccApi.refreshRegion("/habits/regions", "habits-body").catch(() => window.location.reload());
  });
})();
