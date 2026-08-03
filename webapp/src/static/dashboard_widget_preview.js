// Dashboard widget Source/View/Range selects (dashboard.html's Add-widget
// form and each widget's own Filters form), 2026-08-02.
//
// Two independent jobs:
//  1. Keep View limited to whatever the current Source actually offers,
//     and Range limited to whatever the current View actually uses (or
//     hide Range entirely for a View that doesn't have one at all) --
//     pure progressive enhancement. Every option stays real, submittable
//     <option> elements the whole time (just hidden, never removed), so
//     a no-JS submission still works -- the server's own resolver
//     (_resolve_selection) already tolerates an inapplicable combo by
//     falling back to something sane, this only exists to stop a
//     JS-equipped user from ever *seeing* a combo that wouldn't do what
//     the labels imply.
//  2. For the Add-widget form specifically (marked with
//     data-preview-url): fetch a live, real-data preview of whatever's
//     currently selected and show it below the form, debounced so
//     typing in Title/Tags doesn't fire a request per keystroke.

(function () {
  function filterOptions(select, predicate) {
    let firstVisibleValue = null;
    let selectedStillVisible = false;
    Array.from(select.options).forEach((opt) => {
      const visible = predicate(opt);
      opt.hidden = !visible;
      if (visible && firstVisibleValue === null) firstVisibleValue = opt.value;
      if (visible && opt.value === select.value) selectedStillVisible = true;
    });
    if (!selectedStillVisible && firstVisibleValue !== null) select.value = firstVisibleValue;
  }

  function wireSelectForm(form) {
    const sourceSelect = form.querySelector(".widget-source-select");
    const viewSelect = form.querySelector(".widget-view-select");
    const rangeSelect = form.querySelector(".widget-range-select");
    const rangeField = form.querySelector(".widget-range-field");
    // "upcoming_list" is the only View whose render function
    // (_render_upcoming_events) reads config.limit at all -- Today's
    // Agenda/Weekly Overview/Mini Calendar all happened to satisfy the
    // old, looser 'events' in spec.uses check too, so Limit showed up
    // for them and visibly did nothing, which read as broken. Hiding it
    // here mirrors the server-side gate in the Filters form
    // (dashboard.html: widget.type != 'upcoming_events').
    const limitField = form.querySelector(".widget-limit-field");
    if (!sourceSelect || !viewSelect || !rangeSelect) return;

    function syncViewToSource() {
      filterOptions(viewSelect, (opt) => opt.dataset.source === sourceSelect.value);
    }

    function syncRangeToView() {
      const selectedViewOpt = viewSelect.options[viewSelect.selectedIndex];
      const hasRange = !!(selectedViewOpt && selectedViewOpt.dataset.hasRange);
      if (rangeField) rangeField.classList.toggle("is-hidden", !hasRange);
      if (limitField) limitField.classList.toggle("is-hidden", viewSelect.value !== "upcoming_list");
      if (!hasRange) return;
      const viewValue = viewSelect.value;
      filterOptions(rangeSelect, (opt) => (opt.dataset.views || "").split(",").includes(viewValue));
    }

    sourceSelect.addEventListener("change", () => {
      syncViewToSource();
      syncRangeToView();
    });
    viewSelect.addEventListener("change", syncRangeToView);

    syncViewToSource();
    syncRangeToView();
  }

  document.querySelectorAll(".widget-select-form").forEach((form) => {
    // A malformed/partial form (missing a select we expect) shouldn't
    // take the whole page's script down with it -- keep every other
    // form on the page working.
    try {
      wireSelectForm(form);
    } catch (err) {
      console.error("dashboard widget form wiring failed", err);
    }
  });

  // --- Auto-save (existing widgets' own Filters forms) ------------------
  //
  // Editing an existing widget used to need an explicit "Save filters"
  // click; if you closed the panel or hit the top "Done" button (a plain
  // link, never wired to submit anything) first, the edit was silently
  // lost. Every field now saves itself the moment it changes -- same
  // POST the form would have made on submit, just fired automatically --
  // matching the no-button, no-reload pattern the drag-to-reorder/resize
  // handles above already use. The button stays in the DOM and keeps
  // working normally; it's only hidden here once JS has actually taken
  // over, so a no-JS visit still has a real way to save.
  // Collect every autosave-wired form's flush function so the "Done"
  // button (below) can drain them all before navigating away.
  const pendingFlushes = [];

  document.querySelectorAll("form.widget-filters-autosave").forEach((form) => {
    const saveBtn = form.querySelector(".widget-save-filters-btn");
    const status = form.querySelector(".widget-save-status");
    if (!saveBtn || !status) return;
    saveBtn.classList.add("is-hidden");

    let statusFadeTimer = null;
    function setStatus(text, isError) {
      clearTimeout(statusFadeTimer);
      status.textContent = text;
      status.classList.toggle("is-error", !!isError);
      status.classList.add("is-visible");
      if (!isError) {
        statusFadeTimer = setTimeout(() => status.classList.remove("is-visible"), 1600);
      }
    }

    let autosaveDebounce = null;
    let autosaveSeq = 0;
    let dirty = false;
    let savePromise = null;
    async function autosave() {
      dirty = false;
      const seq = ++autosaveSeq;
      setStatus("Saving…", false);
      try {
        savePromise = fetch(form.action, { method: "POST", body: new FormData(form) });
        const resp = await savePromise;
        savePromise = null;
        if (seq !== autosaveSeq) return; // a newer edit already superseded this request
        if (!resp.ok) throw new Error("save failed");
        setStatus("Saved", false);
      } catch (err) {
        savePromise = null;
        if (seq !== autosaveSeq) return;
        // Surface the real button back so there's still a working path
        // forward instead of a silently stuck "couldn't save" state.
        saveBtn.classList.remove("is-hidden");
        setStatus("Couldn't save — try again", true);
      }
    }

    function scheduleAutosave() {
      dirty = true;
      clearTimeout(autosaveDebounce);
      autosaveDebounce = setTimeout(autosave, 500);
    }

    // Flush: if a debounced save is pending, fire it now and wait for it
    // (and any already-in-flight save) to finish. Called by the "Done"
    // button before navigating away so a fast change + click-Done never
    // drops the last edit.
    async function flush() {
      if (dirty) {
        clearTimeout(autosaveDebounce);
        autosave();
      }
      if (savePromise) await savePromise;
    }
    pendingFlushes.push(flush);

    // 'change' covers selects/checkboxes/radios (and number inputs on
    // blur/spinner) -- nothing left to debounce there. 'input' (typing
    // in Title/Tags) is debounced so a fast typist doesn't fire a
    // request per keystroke.
    form.addEventListener("change", () => { dirty = true; autosave(); });
    form.addEventListener("input", scheduleAutosave);
  });

  // "Done" button -- flush every pending autosave before navigating away.
  // Without this, a field changed <500ms before clicking Done would be
  // silently lost (the debounced save fires after the page has already
  // navigated). `e.preventDefault()` holds the navigation; once every
  // flush resolves, `window.location` does the actual navigate.
  const doneBtn = document.querySelector("a.btn[href='/'], a.btn[href^='/projects/groups/']");
  if (doneBtn && doneBtn.textContent.trim().match(/Done/i)) {
    doneBtn.addEventListener("click", async (e) => {
      if (pendingFlushes.length === 0) return; // nothing to flush -- let it navigate
      e.preventDefault();
      await Promise.all(pendingFlushes.map((f) => f()));
      window.location = doneBtn.href;
    });
  }

  // --- Live preview (Add-widget form only) -----------------------------

  const previewForm = document.querySelector(".widget-select-form[data-preview-url]");
  const previewContent = document.getElementById("widget-preview-content");
  if (!previewForm || !previewContent) return;

  let debounceTimer = null;
  let requestSeq = 0;

  async function refreshPreview() {
    const seq = ++requestSeq;
    try {
      const resp = await fetch(previewForm.dataset.previewUrl, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams(new FormData(previewForm)).toString(),
      });
      const html = await resp.text();
      // A slower-than-usual request finishing after a newer one already
      // landed shouldn't stomp the fresher result -- discard anything
      // that isn't the most recently *sent* request.
      if (seq === requestSeq) previewContent.innerHTML = html;
    } catch (err) {
      if (seq === requestSeq) {
        previewContent.innerHTML = '<div class="empty-state" style="padding:16px 0">Could not load preview.</div>';
      }
    }
  }

  function scheduleRefresh() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(refreshPreview, 350);
  }

  // 'change' (select/checkbox/radio commits, plus number inputs losing
  // focus or using the spinner) fires once you're done picking, so
  // there's nothing to debounce -- refresh right away. wireSelectForm's
  // own change listeners on sourceSelect/viewSelect run first (they're
  // bound directly on those elements, so they fire before this
  // bubbled/ancestor listener does), so by the time this runs, any
  // auto-corrected View/Range/Limit visibility is already settled and
  // FormData will pick up the final values, not the stale ones.
  // 'input' (typing in Title/Tags) is the one case worth debouncing, so
  // a fast typist doesn't fire a request per keystroke.
  previewForm.addEventListener("change", refreshPreview);
  previewForm.addEventListener("input", scheduleRefresh);
  refreshPreview();
})();
