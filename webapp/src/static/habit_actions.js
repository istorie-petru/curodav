// Habit check-ins wherever a habit row renders (habits H2 page, H4
// Dashboard widget) -- every check-in / day toggle is a plain POST form
// (`form.habit-action`, the no-JS fallback). This submits it with fetch
// and re-renders the region it sits in from the server, so streaks and
// the to-do order are always the server's own numbers:
//   - on /habits: #habits-body from /habits/regions
//   - in a Dashboard/label-page widget: that .widget-card from
//     /dashboard/widgets/<uid>
//   - in the calendar day view (H7): a task change event, which
//     async_calendar.js answers by re-rendering #day-grid
// Also re-renders /habits after a habit is created/edited/deleted in a
// modal (cc-entity-changed, type "task"); widget cards already get that
// from async_crud.js (the widget declares uses: tasks).
//
// 2026-09-25 (UI audit):
//   - H-04: a 4xx's own `error` text is shown ("The pause must end on or
//     after its start.") instead of a generic "Could not save that".
//   - H-05: the tapped control gets focus back after the region re-renders
//     (matched by its form action, which is unique per habit/day), and its
//     row flashes briefly so a row that moved between To do / On track is
//     easy to find again.
//   - Flesh-out 9: a check-in / day toggle whose form carries data-undo-*
//     (the day's value before the tap) shows an "Undo" toast that posts
//     that value back to /tasks/<uid>/completions (0 clears the day). A
//     +1 on an amount habit has no toast: 8 taps would mean 8 toasts, and
//     the amount popup already corrects a count.
(function () {
  let pendingFocus = null; // {regionId, action}

  function regionFor(form) {
    const page = form.closest("#habits-body");
    if (page) return { url: "/habits/regions", id: "habits-body" };
    // The calendar day view already re-renders #day-grid on any task
    // change (async_calendar.js -- keeps scroll, re-binds drag), so just
    // announce one instead of swapping it here.
    if (form.closest("#day-grid")) return { dispatch: true, id: "day-grid" };
    const card = form.closest(".widget-card[data-uid]");
    if (card && card.id) return { url: "/dashboard/widgets/" + card.dataset.uid, id: card.id };
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

  function offerUndo(form, region) {
    const url = form.dataset.undoUrl;
    if (!url || !window.ccToast) return;
    const body = new FormData();
    body.append("completion_date", form.dataset.undoDate);
    body.append("value", form.dataset.undoValue || "0");
    window.ccToast({
      title: form.dataset.undoMessage || "Saved",
      icon: "check-circle",
      actions: [
        {
          label: "Undo",
          onAction: async () => {
            try {
              await postForm(url, body);
              await refresh(region);
            } catch (err) {
              window.ccToast({ message: err.message, variant: "error" });
            }
          },
        },
      ],
    });
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
      await postForm(form.action, new FormData(form));
    } catch (err) {
      if (btn) btn.disabled = false;
      window.ccToast({ message: err.message, variant: "error" });
      return;
    }
    pendingFocus = { regionId: region.id, action: form.getAttribute("action") };
    offerUndo(form, region);
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
