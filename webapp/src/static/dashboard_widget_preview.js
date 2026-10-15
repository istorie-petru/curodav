
window.CCWidgetPreview = {
  init: function (root) {
    root = root || document;

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
      const limitField = form.querySelector(".widget-limit-field");
      const showField = form.querySelector(".widget-show-field");
      const styleField = form.querySelector(".widget-style-field");
      const scopeField = form.querySelector(".widget-scope-field");
      if (!sourceGroup || !viewMs || !rangeMs) return;

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
        if (limitField) limitField.classList.toggle("is-hidden", !(viewInput && viewInput.dataset.hasLimit));
        if (showField) showField.classList.toggle("is-hidden", !viewInput || viewInput.value !== "agenda_view");
        if (styleField) styleField.classList.toggle("is-hidden", !viewInput || viewInput.value !== "spaces_projects_view");
        if (scopeField) scopeField.classList.toggle("is-hidden", !viewInput || viewInput.value !== "spaces_projects_view");
        if (!hasRange) return;
        const viewValue = viewInput.value;
        filterMsOptions(rangeMs, (input) => (input.dataset.views || "").split(",").includes(viewValue));
      }

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
    // One forced refreshRegion call per autosave-wired widget, run again
    // after every flush lands (see the Done handler below) -- belt-and-
    // suspenders against a mid-session refreshRegion call that silently
    // failed (autosave()'s own refresh is best-effort, `.catch(() => {})`,
    // with no retry).
    const pendingRefreshes = [];

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

      const uidMatch = String(form.action || "").match(/\/dashboard\/widgets\/([^/]+)\/edit/);
      const widgetUid = uidMatch ? uidMatch[1] : null;

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
          // Refresh the real card behind the modal so a Width/Style/Title/
          // Labels change is visible the moment the modal closes, not just
          // after a reload. Best-effort: a failed refresh here shouldn't
          // turn an already-successful save into an error state (the save
          // itself already succeeded -- only the live preview of it
          // didn't refresh), so this is deliberately not awaited into the
          // try/catch's error branch above.
          if (widgetUid && window.ccApi) {
            window.ccApi.refreshRegion("/dashboard/widgets/" + widgetUid, "widget-" + widgetUid).catch(() => {});
          }
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
      if (widgetUid) {
        pendingRefreshes.push(() =>
          window.ccApi ? window.ccApi.refreshRegion("/dashboard/widgets/" + widgetUid, "widget-" + widgetUid) : Promise.resolve()
        );
      }

      document.addEventListener("change", (e) => {
        if (e.target.form !== form) return;
        dirty = true;
        autosave();
      });
      form.addEventListener("input", scheduleAutosave);
    });

    const doneBtn = root.querySelector("[data-modal-cancel]");
    if (doneBtn) {
      doneBtn.addEventListener(
        "click",
        () => {
          if (pendingFlushes.length === 0) return;
          Promise.all(pendingFlushes.map((f) => f())).then(() => {
            // Belt-and-suspenders: force one more refresh per autosave-
            // wired widget after every pending save has landed, so a
            // silently-swallowed mid-session refreshRegion failure doesn't
            // leave the card stale after the modal's already gone and the
            // user has no more "Saving…"/"Couldn't save" status text to
            // notice it by.
            pendingRefreshes.forEach((r) => r().catch(() => {}));
          });
        },
        // Capture, before modal.js's own listener (wired the same way,
        // also on click) runs closeModal() -- both fire on the same click,
        // registration order on the same phase isn't guaranteed to put
        // this one first otherwise, and the flush/refresh here doesn't
        // need to block the close either way (best-effort, same as every
        // individual autosave's own refresh).
        true
      );
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
          previewContent.replaceChildren(window.ccEmptyState("Could not load preview"));
        }
      }
    }

    function scheduleRefresh() {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(refreshPreview, 350);
    }

    document.addEventListener("change", (e) => {
      if (e.target.form === previewForm) refreshPreview();
    });
    previewForm.addEventListener("input", scheduleRefresh);
    refreshPreview();
  },
};

window.CCWidgetPreview.init(document);
