// Dashboard widget Source/View/Range controls (dashboard.html's Add-widget
// form and each widget's own Filters form), 2026-08-02. Briefly reworked
// 2026-08-07 (modal-input-design Phase A) from plain <select>s into a tile
// picker (Source) and segmented radio controls (View/Range); View/Range
// reverted back to plain <select>/<option> the same day after user
// feedback that segmented-radio "dropdowns" were confusing and
// inconsistent with real dropdowns elsewhere in the app. Reworked again
// the same day, follow-up round ("View/Range should look the same as
// list") -- View/Range are now single-select instances of
// _widget_list_multiselect.html's own trigger+panel component
// (`.widget-view-select`/`.widget-range-select` mark the `.multiselect`
// wrapper now, not a `<select>`), since a native `<select>`'s open-list
// chrome can never be made to look consistent with the rest of the app no
// matter what CSS is applied to the closed control. Source stays a tile
// picker (`.tile-select`, real radios); View/Range are real radio inputs
// too, just presented through the checkbox-dropdown-shaped partial in
// single-select mode, with data-source/data-has-range/data-views carried
// on each radio the same way they used to live on `<option>` elements.
//
// Two independent jobs:
//  1. Keep View limited to whatever the current Source actually offers,
//     and Range limited to whatever the current View actually uses (or
//     hide Range entirely for a View that doesn't have one at all) --
//     pure progressive enhancement. Every option stays a real, submittable
//     radio input the whole time (just hidden, never removed/disabled), so
//     a no-JS submission still works -- the server's own resolver
//     (_resolve_selection) already tolerates an inapplicable combo by
//     falling back to something sane, this only exists to stop a
//     JS-equipped user from ever *seeing* a combo that wouldn't do what
//     the labels imply.
//  2. For any form marked data-preview-url (the Add-widget form and the
//     Customize modal's Widget Builder): fetch a live, real-data preview
//     of whatever's currently selected and show it below the form,
//     debounced so typing in Title/Tags doesn't fire a request per
//     keystroke.
//
// Exposed as CCWidgetPreview.init(root) so the Customize modal can wire up
// its freshly-injected builder/edit forms (modal.js calls it after the
// modal body loads); on the normal page it self-initializes over document.

window.CCWidgetPreview = {
  init: function (root) {
    root = root || document;

    // Filters a single-select multiselect's radio rows in place: hides
    // (never removes) every `.multiselect-option` row whose radio doesn't
    // satisfy `predicate`, and -- if the currently-checked radio just
    // became invalid -- checks the first still-valid one instead (firing
    // a real `change` so app.js's own summary/close-panel handling picks
    // it up), so the field's value always reflects something actually
    // visible/choosable.
    //
    // 2026-08-08: reads the panel via window.CCMultiselect.panelFor(ms)
    // instead of `ms.querySelectorAll(".multiselect-panel input")` -- once
    // app.js's portal fix (same date) moves an opened panel out to
    // #multiselect-portal so it can render outside a clipping modal, it's
    // no longer a DOM descendant of `ms` at all, so the old scoped query
    // would silently find nothing and this function would become a no-op
    // exactly when a user was actively interacting with the field.
    function filterMsOptions(ms, predicate) {
      const panel = window.CCMultiselect && window.CCMultiselect.panelFor(ms);
      const inputs = panel ? Array.from(panel.querySelectorAll("input")) : [];
      let firstVisible = null;
      let checkedStillVisible = false;
      inputs.forEach((input) => {
        const visible = predicate(input);
        const row = input.closest(".multiselect-option");
        if (row) row.hidden = !visible;
        input.disabled = !visible;
        if (visible && firstVisible === null) firstVisible = input;
        if (visible && input.checked) checkedStillVisible = true;
      });
      if (!checkedStillVisible && firstVisible) {
        firstVisible.checked = true;
        firstVisible.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    function wireSelectForm(form) {
      const sourceGroup = form.querySelector(".widget-source-select");
      const viewMs = form.querySelector(".widget-view-select");
      const rangeMs = form.querySelector(".widget-range-select");
      const rangeField = form.querySelector(".widget-range-field");
      // "upcoming_list" is the only View whose render function
      // (_render_upcoming_events) reads config.limit at all -- Today's
      // Agenda/Weekly Overview/Mini Calendar all happened to satisfy the
      // old, looser 'events' in spec.uses check too, so Limit showed up
      // for them and visibly did nothing, which read as broken. Hiding it
      // here mirrors the server-side gate in the Filters form
      // (dashboard.html: widget.type != 'upcoming_events').
      const limitField = form.querySelector(".widget-limit-field");
      if (!sourceGroup || !viewMs || !rangeMs) return;

      // 2026-08-08: reads via window.CCMultiselect.panelFor(ms) instead of
      // `container.querySelector(...)` -- same reasoning as filterMsOptions
      // above. `sourceGroup` (the Data source tile picker) isn't a
      // `.multiselect` at all and is never portaled, so it's queried
      // directly as before; only the two multiselect-panel-backed fields
      // (View/Range) need the indirection.
      function checkedRadio(container, name) {
        return container.querySelector('input[name="' + name + '"]:checked');
      }
      function checkedMsRadio(ms, name) {
        const panel = window.CCMultiselect && window.CCMultiselect.panelFor(ms);
        return panel ? panel.querySelector('input[name="' + name + '"]:checked') : null;
      }

      function syncViewToSource() {
        const source = checkedRadio(sourceGroup, "source");
        const sourceValue = source ? source.value : null;
        filterMsOptions(viewMs, (input) => input.dataset.source === sourceValue);
      }

      function syncRangeToView() {
        const viewInput = checkedMsRadio(viewMs, "view");
        const hasRange = !!(viewInput && viewInput.dataset.hasRange);
        if (rangeField) rangeField.classList.toggle("is-hidden", !hasRange);
        if (limitField) limitField.classList.toggle("is-hidden", !viewInput || viewInput.value !== "upcoming_list");
        if (!hasRange) return;
        const viewValue = viewInput.value;
        filterMsOptions(rangeMs, (input) => (input.dataset.views || "").split(",").includes(viewValue));
      }

      // 2026-08-08: was `sourceGroup.addEventListener("change", ...)` and
      // `viewMs.addEventListener("change", syncRangeToView)` -- both relied
      // on the changed input's `change` event *bubbling up* to that
      // ancestor element. That still works for sourceGroup (tile radios
      // never move), but View/Range's radios now live inside
      // #multiselect-portal while their panel is open, outside `viewMs`'s
      // DOM subtree entirely, so a change made there would never bubble to
      // `viewMs` and this sync would silently stop firing on every real
      // interaction. Delegated on `document` instead, matched by
      // `e.target.form === form` (the native `.form` property correctly
      // resolves a control's owning form via its `form="..."` attribute --
      // _widget_list_multiselect.html's ms_form_id -- regardless of where
      // in the DOM that control currently sits) plus its `name`, so this
      // keeps working no matter which multiselect panel is or isn't
      // currently portaled.
      document.addEventListener("change", (e) => {
        if (e.target.form !== form) return;
        if (e.target.name === "source") {
          syncViewToSource();
          syncRangeToView();
        } else if (e.target.name === "view") {
          syncRangeToView();
        }
      });

      syncViewToSource();
      syncRangeToView();
    }

    root.querySelectorAll(".widget-select-form").forEach((form) => {
      // A malformed/partial form (missing a control we expect) shouldn't
      // take the whole page's script down with it -- keep every other
      // form on the page working.
      try {
        wireSelectForm(form);
      } catch (err) {
        console.error("dashboard widget form wiring failed", err);
      }
    });

    // Checkbox/radio-dropdown (task lists / calendars / labels / View /
    // Range) trigger summaries are kept in sync by app.js's own document-
    // level .widget-list-multiselect change handler (updateMsSummary) --
    // no separate copy needed here any more. That handler also covers
    // programmatic changes (filterMsOptions' own dispatched "change"
    // above) since it's a real `change` event either way.

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

    root.querySelectorAll("form.widget-filters-autosave").forEach((form) => {
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
      //
      // 2026-08-08: `change` delegated on `document` + `e.target.form ===
      // form`, not bound directly on `form` -- same reason as
      // wireSelectForm's sourceGroup/viewMs listeners above: a Labels/Task
      // lists/Calendars/View/Range checkbox or radio living inside an open
      // (portaled) multiselect panel is no longer a DOM descendant of
      // `form` at the moment it changes, so a listener bound on `form`
      // itself would never see that event. `.form` resolves correctly via
      // ms_form_id's `form="..."` attribute regardless of current DOM
      // position; `input`/typing listeners stay bound directly since text/
      // number fields are never portaled.
      document.addEventListener("change", (e) => {
        if (e.target.form !== form) return;
        dirty = true;
        autosave();
      });
      form.addEventListener("input", scheduleAutosave);
    });

    // "Done" button -- flush every pending autosave before navigating away.
    // Without this, a field changed <500ms before clicking Done would be
    // silently lost (the debounced save fires after the page has already
    // navigated). `e.preventDefault()` holds the navigation; once every
    // flush resolves, `window.location` does the actual navigate.
    const doneBtn = root.querySelector("a.btn[href='/'], a.btn[href^='/labels/']");
    if (doneBtn && doneBtn.textContent.trim().match(/Done/i)) {
      doneBtn.addEventListener("click", async (e) => {
        if (pendingFlushes.length === 0) return; // nothing to flush -- let it navigate
        e.preventDefault();
        await Promise.all(pendingFlushes.map((f) => f()));
        window.location = doneBtn.href;
      });
    }

    // --- Live preview (any form carrying data-preview-url) ---------------

    const previewForm = root.querySelector(".widget-select-form[data-preview-url]");
    const previewContent = previewForm
      ? root.querySelector("#widget-preview-content, [data-preview-content]")
      : null;
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
    // there's nothing to debounce -- refresh right away. 'input' (typing
    // in Title/Tags) is the one case worth debouncing, so a fast typist
    // doesn't fire a request per keystroke.
    //
    // 2026-08-08: delegated on `document` + `e.target.form === previewForm`
    // rather than bound on `previewForm` directly -- same bubbling problem
    // as wireSelectForm/autosave above (a portaled multiselect panel's
    // inputs aren't DOM descendants of the form while open). Registered
    // after wireSelectForm's own document-level change listener above (script
    // order = registration order for same-target/same-event listeners), so
    // by the time this runs, any auto-corrected View/Range/Limit visibility
    // is already settled and FormData will pick up the final values, not
    // the stale ones.
    document.addEventListener("change", (e) => {
      if (e.target.form === previewForm) refreshPreview();
    });
    previewForm.addEventListener("input", scheduleRefresh);
    refreshPreview();
  },
};

window.CCWidgetPreview.init(document);
