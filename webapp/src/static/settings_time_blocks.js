// Inline editing for the Sleep Time / Leisure Time tables
// (templates/settings_time_blocks.html) -- same shape as
// static/settings_holidays.js: a single-field change fires POST
// /settings/time-blocks/{uid}/update-field instead of a full form submit.
// Falls back to a reload if the request fails, so a row never silently
// drifts from the server.
//
// The Days cell is the shared filter-mode multiselect
// (_widget_list_multiselect.html) rather than a plain input -- each row's
// checkbox group is named "days__{uid}" (not submitted as part of any
// <form>, purely JS-driven), same "uid travels via the input's own name"
// reasoning settings_holidays.js's Calendar dropdown already uses (a
// `.closest()` lookup breaks once app.js portals the open panel out to
// #multiselect-portal).

(function () {
  const tables = [document.getElementById("sleep-block-table"), document.getElementById("leisure-block-table")].filter(Boolean);
  if (!tables.length) return;

  async function updateField(uid, field, value) {
    try {
      const resp = await fetch(`/settings/time-blocks/${uid}/update-field`, {
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

  function rowExists(uid) {
    return tables.some((t) => t.querySelector(`tr[data-uid="${uid}"]`));
  }

  tables.forEach((table) => {
    table.querySelectorAll("input.inline-text, input.inline-time").forEach((input) => {
      input.addEventListener("change", async () => {
        await updateField(input.dataset.uid, input.dataset.field, input.value);
      });
    });
  });

  // Days checkboxes -- "days__{uid}" name prefix, one group per row.
  // Every checkbox in the group shares the name, so on any change this
  // collects the full set of currently-checked days for that uid and
  // sends them as one comma-joined string (the update-field endpoint's
  // "days" field takes a string, not a JSON array -- one request shape
  // for every field, see routers/settings.py::update_time_block_field).
  const DAYS_PREFIX = "days__";
  document.addEventListener("change", async (e) => {
    const el = e.target;
    if (!(el instanceof HTMLInputElement) || el.type !== "checkbox") return;
    if (!el.name || !el.name.startsWith(DAYS_PREFIX)) return;
    const uid = el.name.slice(DAYS_PREFIX.length);
    if (!rowExists(uid)) return;
    const checked = Array.from(document.querySelectorAll(`input[name="${el.name}"]:checked`)).map((i) => i.value);
    await updateField(uid, "days", checked.join(","));
  });
})();
