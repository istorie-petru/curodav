// Inline editing for the Holidays table (templates/settings_holidays.html)
// -- same shape as static/tasks_table.js: a single-field change fires
// POST /settings/holidays/{uid}/update-field instead of a full form submit,
// so editing a row never re-navigates the page. Falls back to a reload if
// the request fails, so the row never silently drifts from the server.
//
// The Calendar cell is the shared single+allow-new dropdown
// (_widget_list_multiselect.html) rather than a plain input -- each row's
// instance is named "calendar_name__{uid}" (not submitted as part of any
// <form>, purely JS-driven) so the holiday's own uid travels with the
// change event via the input's `name` instead of a DOM-position lookup,
// which would break once app.js portals the open panel out to
// #multiselect-portal (see app.js's own "Generic multi-select dropdown"
// comment for why a `.closest()` from inside an open panel can't find its
// original row anymore).

(function () {
  const table = document.getElementById("holiday-table");
  if (!table) return;

  async function updateField(uid, field, value) {
    try {
      const resp = await fetch(`/settings/holidays/${uid}/update-field`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field, value }),
      });
      if (!resp.ok) throw new Error("update failed");
      return true;
    } catch (err) {
      window.ccToast({ message: "Could not save that change. Reloading...", variant: "error", duration: 1400 });
      setTimeout(() => window.location.reload(), 1200);
      return false;
    }
  }

  table.querySelectorAll("input.inline-text, input.inline-date").forEach((input) => {
    input.addEventListener("change", async () => {
      await updateField(input.dataset.uid, input.dataset.field, input.value);
    });
  });

  // Calendar dropdown -- both the picked-existing-calendar radios and the
  // "New calendar..." free-text input share the "calendar_name__{uid}"
  // name prefix (see _widget_list_multiselect.html's ms_allow_new).
  const CALENDAR_PREFIX = "calendar_name__";
  document.addEventListener("change", async (e) => {
    const el = e.target;
    if (!(el instanceof HTMLInputElement)) return;
    if (!el.name || !el.name.startsWith(CALENDAR_PREFIX)) return;
    // Only react to inputs that belong to this table's rows -- the portal
    // is a page-wide singleton, so this listener could otherwise also see
    // an unrelated multiselect on some other page fragment.
    const uid = el.name.slice(CALENDAR_PREFIX.length);
    if (!table.querySelector(`tr[data-uid="${uid}"]`)) return;
    const value = (el.value || "").trim();
    if (!value) return;
    await updateField(uid, "calendar_name", value);
  });
})();
