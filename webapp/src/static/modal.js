// Generic modal: opens a server-rendered page's `#modal-target` fragment
// in a dialog instead of navigating to it, and submits any form inside via
// fetch instead of a full page load.
//
// Deliberately does NOT duplicate any form markup -- it fetches the exact
// same URL a full-page link would (e.g. /events/new?date=...), so
// event_form.html/schedule_class_form.html/calendars_list.html stay the
// single source of truth for those fields, prefill logic, and validation.
//
// Two submit behaviors, chosen per-form:
//  - Default: a "primary" action (Save on an event/task/contact/class
//    form) -- on success, close the modal and reload the underlying page.
//    This is "I'm done, complete the action."
//  - `data-modal-keep-open` on the <form>: an incremental tweak inside an
//    ongoing management panel (calendars_list.html's per-row color/name
//    changes, delete, add) -- on success, re-fetch the modal's own URL
//    and refresh just its content in place, WITHOUT closing. The modal
//    only actually reloads the underlying page once the user explicitly
//    closes it (X, Escape, backdrop click) -- and only if something
//    inside actually changed, via `pendingReload`. This is what "modals
//    shouldn't exit while you're doing something in them" means in
//    practice: picking a color is one tweak in a session that might
//    include several, not a "finish and leave" action.
//
// Usage: any element with `data-modal="/some/url"` opens that URL as a
// modal on click instead of following its href. Elements with
// `data-modal-cancel` close the modal instead of whatever they'd
// otherwise do (a "Cancel"/"Back" link that would normally navigate).

(function () {
    const overlay = document.getElementById("modal-overlay");
    const dialog = document.getElementById("modal-dialog");
    const header = document.getElementById("modal-header");
    const body = document.getElementById("modal-body");
    const footer = document.getElementById("modal-footer");
    const closeBtn = document.getElementById("modal-close");
    const colorPopover = document.getElementById("color-popover");
    const iconPopover = document.getElementById("icon-popover");
    if (!overlay || !body) return;

  let currentUrl = null;
  let pendingReload = false;

  // --- Generic swatch/emoji picker popover -----------------------------
  // .color-picker (calendars_list.html, schedule_export.html, projects_
  // manage.html) and .icon-picker (projects_manage.html, 2026-08-02) are
  // both a trigger button + a grid of radios in a "dropdown" <div> that
  // starts out hidden right next to it. Opening either *moves* that grid
  // into a single shared floating popover element (#color-popover /
  // #icon-popover, both siblings of #modal-overlay in base.html, not
  // descendants) and positions it with `position: fixed` next to the
  // trigger -- the only way for it to render outside a modal's own box,
  // since .modal/.modal-body both clip any descendant that visually
  // overflows them no matter what position value it has (and it's needed
  // even outside a modal, e.g. on the plain Projects settings page,
  // wherever the trigger sits near a scrolling/clipping ancestor). Each
  // radio inside carries a `form="..."` attribute pointing back at its
  // real <form> by id, because moving a form control outside its <form>
  // ancestor in the DOM otherwise silently resets its form owner and
  // drops it from that form's submission.
  //
  // `openPicker` tracks whichever one (color or icon) is currently open,
  // remembering which popover element and trigger class it belongs to so
  // close/outside-click logic doesn't need to know which kind it is.
  let openPicker = null; // {picker, popover, triggerClass}

  function closeOpenPopover() {
    if (!openPicker) return;
    const { picker, popover, triggerClass } = openPicker;
    const dropdown = popover.firstElementChild;
    if (dropdown) picker.appendChild(dropdown); // move back home
    popover.classList.remove("is-open");
    const trigger = picker.querySelector("." + triggerClass);
    if (trigger) trigger.classList.remove("is-active");
    openPicker = null;
  }

  function openPopover(picker, popover, triggerClass, dropdownClass) {
    if (openPicker && openPicker.picker === picker) return;
    closeOpenPopover();
    const trigger = picker.querySelector("." + triggerClass);
    const dropdown = picker.querySelector("." + dropdownClass);
    if (!trigger || !dropdown) return;
    popover.appendChild(dropdown);
    popover.classList.add("is-open");
    const rect = trigger.getBoundingClientRect();
    const popRect = popover.getBoundingClientRect();
    let top = rect.bottom + 6;
    let left = rect.left;
    if (left + popRect.width > window.innerWidth - 8) {
      left = Math.max(8, window.innerWidth - popRect.width - 8);
    }
    if (top + popRect.height > window.innerHeight - 8) {
      top = rect.top - popRect.height - 6; // flip above the trigger instead
    }
    popover.style.top = top + "px";
    popover.style.left = left + "px";
    trigger.classList.add("is-active");
    openPicker = { picker, popover, triggerClass };
  }

  // Binds every `.pickerClass` found under `root` -- called once for the
  // whole `document` at boot (so pickers on a plain full page, e.g.
  // projects_manage.html, work with no modal involved at all) and again
  // for just the modal's own `#modal-body` inside wireContent() below
  // whenever modal content is (re)rendered. These two call sites never
  // overlap (modal-body starts empty and is only ever populated by JS,
  // never present in the document at boot), so there's no risk of
  // double-binding the same element twice.
  function wireSwatchPickers(root, { pickerClass, triggerClass, dropdownClass, popover, onPick }) {
    root.querySelectorAll("." + pickerClass).forEach((picker) => {
      const trigger = picker.querySelector("." + triggerClass);
      const dropdown = picker.querySelector("." + dropdownClass);
      if (!trigger || !dropdown) return;
      const autosubmit = picker.hasAttribute("data-autosubmit");

      trigger.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (openPicker && openPicker.picker === picker) {
          closeOpenPopover();
        } else {
          openPopover(picker, popover, triggerClass, dropdownClass);
        }
      });

      dropdown.querySelectorAll('input[type="radio"]').forEach((radio) => {
        radio.addEventListener("change", () => {
          if (onPick) onPick(trigger, radio);
          closeOpenPopover();
          if (autosubmit && radio.form) radio.form.requestSubmit();
        });
      });
    });
  }

  function wireColorPickers(root) {
    if (!colorPopover) return;
    wireSwatchPickers(root, {
      pickerClass: "color-picker",
      triggerClass: "color-swatch-current",
      dropdownClass: "color-dropdown",
      popover: colorPopover,
      onPick: (trigger, radio) => {
        trigger.className = "color-swatch-current cal-" + radio.value;
      },
    });
  }

  // Icon picker (2026-08-02, Projects manage page; revised same day to
  // draw from the app's own icon library instead of a one-off emoji set
  // -- "the same logic as the color picker one"). Each radio's value is
  // a key into templates/_icons_sprite.html (e.g. "folder", "activity"),
  // same sprite deps.py's `icon()` Jinja helper already draws from
  // server-side -- picking one rebuilds the trigger's content as the
  // exact same `<svg class="icon ..."><use href="#icon-NAME"></use></svg>`
  // markup that helper renders, referencing the one inline sprite
  // already present in the page (base.html includes it once), not a
  // duplicated copy. Empty selection (the "no icon" option) falls back
  // to the same "folder" icon every unset-icon project already shows
  // elsewhere in the app (projects_manage.html, project_merge.html,
  // _widget_project_preview.html).
  function wireIconPickers(root) {
    if (!iconPopover) return;
    wireSwatchPickers(root, {
      pickerClass: "icon-picker",
      triggerClass: "icon-picker-current",
      dropdownClass: "icon-dropdown",
      popover: iconPopover,
      onPick: (trigger, radio) => {
        const name = radio.value || "folder";
        trigger.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#icon-' + name + '"></use></svg>';
      },
    });
  }

   function closeModal() {
     closeOpenPopover();
     overlay.classList.remove("is-open");
     body.innerHTML = "";
     if (header) header.innerHTML = "";
     if (footer) footer.innerHTML = "";
     currentUrl = null;
     if (pendingReload) {
       pendingReload = false;
       window.location.reload();
     }
   }

   function injectModalContent(html) {
     const doc = new DOMParser().parseFromString(html, "text/html");
     const fragment = doc.getElementById("modal-target");
     if (!fragment) return null;
     const inner = fragment.innerHTML;
     const temp = document.createElement("div");
     temp.innerHTML = inner;
     const hasSections = temp.querySelector(".modal-header, .modal-body, .modal-footer");
     if (hasSections) {
       if (header) {
         const h = temp.querySelector(".modal-header");
         header.innerHTML = h ? h.innerHTML : "";
         header.style.display = h ? "" : "none";
       }
       if (body) {
         const b = temp.querySelector(".modal-body");
         body.innerHTML = b ? b.innerHTML : (inner);
         body.style.display = b ? "" : "none";
       }
       if (footer) {
         const f = temp.querySelector(".modal-footer");
         footer.innerHTML = f ? f.innerHTML : "";
         footer.style.display = f ? "" : "none";
       }
     } else {
       if (header) { header.innerHTML = ""; header.style.display = "none"; }
       if (body) body.innerHTML = inner;
       if (footer) { footer.innerHTML = ""; footer.style.display = "none"; }
     }
     return fragment;
   }

   async function refreshModalContent() {
     if (!currentUrl) return;
     closeOpenPopover(); // its "home" element is about to be replaced
     const resp = await fetch(currentUrl);
     const html = await resp.text();
     const fragment = injectModalContent(html);
     if (!fragment) return;
     wireContent();
     stabilizeHeight(fragment);
     animateContentSwap();
   }

   function wireContent() {
     body.querySelectorAll("[data-modal-cancel]").forEach((el) => {
       el.addEventListener("click", (e) => {
         e.preventDefault();
         closeModal();
       });
     });
     if (footer) {
       footer.querySelectorAll("[data-modal-cancel]").forEach((el) => {
         el.addEventListener("click", (e) => {
           e.preventDefault();
           closeModal();
         });
       });
     }

    // Contact photo cropper (contact_form.html) -- same re-init reasoning.
    if (window.CCAvatarCropper) window.CCAvatarCropper.init(body);
    // task_form.html's Daily target visibility -- same re-init reasoning.
    if (window.CCHabitFieldToggle) window.CCHabitFieldToggle.init(body);
    // label_edit_modal.html's Role picker (Space/Project date-field
    // reveal + switch-away confirm) -- same re-init reasoning.
    if (window.CCLabelRolePicker) window.CCLabelRolePicker.init(body);
    // Relations cards' add-row picker (1.2 side work, static/
    // command_palette.js) needs no re-init call here -- its entry points
    // are document-level delegated listeners, which already cover content
    // injected via this innerHTML swap without a wireContent() hook.
    // Merged task/event quick-add modal (quick_add.html, 2026-08-10) --
    // tab switch between the two create-forms + retargeting the footer
    // Save button's `form` attribute. Same re-init reasoning.
    if (window.CCQuickAdd) window.CCQuickAdd.init(body);

    // Single-circle color picker / emoji icon picker: click the trigger to
    // open the floating palette (see wireSwatchPickers/openPopover above).
    // Picking a value updates the visible trigger immediately, closes the
    // popover, and -- only for pickers marked `data-autosubmit`
    // (calendars_list.html's/projects_manage.html's per-row edit forms) --
    // submits the form right away, the same as changing the name field
    // does. The "new calendar"/"new project" forms deliberately don't
    // autosubmit: color/icon is just one field alongside a name that
    // still needs typing.
    wireColorPickers(body);
    wireIconPickers(body);

    // Widget Builder (dashboard_customize.html): add-widget form + live
    // preview live inside the modal, injected via innerHTML like Schedule's
    // widgets. CCWidgetPreview.init wires the Source/View/Range controls
    // and the live preview for both the builder and each edit form. The
    // builder form itself is a plain add-and-close form now (2026-08-07,
    // "Add widget should be the only button") -- it has no data-builder
    // any more, so it falls straight through to the generic form handler
    // below like any other modal form.
    if (window.CCWidgetPreview) window.CCWidgetPreview.init(body);

    body.querySelectorAll("form").forEach((form) => {
      // data-modal-get forms (a search box) are handled by their own
      // document-level listener below instead -- this per-form handler
      // assumes a POST-and-fetch shape (method: form.method || "POST",
      // sends a body), which is meaningless for a GET request and would
      // throw trying to attach a body to one. Skip entirely rather than
      // let both handlers fight over the same submit.
      if (form.hasAttribute("data-modal-get")) return;
      let submitting = false;
      const keepOpen = form.hasAttribute("data-modal-keep-open");
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        // Forms inside a modal submit via this handler directly (not the
        // document-level delegated one in app.js -- this listener is
        // attached straight to the form and runs before that one ever
        // sees the event), so a data-confirm-sheet form in here (e.g.
        // tags_manage.html's "Delete everywhere") needs its own check
        // here rather than relying on app.js's fallback, or the delete
        // would fire immediately with no confirmation at all.
        const confirmMsg = form.getAttribute("data-confirm-sheet");
        if (confirmMsg && !form.dataset.confirmed) {
          window.ccConfirmSheet({
            anchor: e.submitter || form,
            message: confirmMsg,
            onConfirm: () => {
              form.dataset.confirmed = "1";
              form.requestSubmit(e.submitter);
            },
          });
          return;
        }
        // Guards against a double-submit (e.g. Enter in a text field and a
        // near-simultaneous click on Save both firing "submit" before the
        // button's disabled state takes effect) sending two create
        // requests -- belt-and-suspenders alongside the server-side fix
        // for the same race (caldav_bridge.py's save_event_row/
        // save_task_row now retry-as-update on a 409 from the CalDAV
        // server, whatever caused the duplicate).
        if (submitting) return;
        submitting = true;
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.classList.add("is-loading");
        }
        try {
          const resp = await fetch(form.action, {
            method: form.method || "POST",
            body: new FormData(form),
          });
          if (resp.ok) {
            if (keepOpen) {
              pendingReload = true;
              await refreshModalContent(); // re-render in place, modal stays open
            } else {
              closeModal();
              window.location.reload();
            }
          } else {
            const text = await resp.text().catch(() => "");
            window.ccToast({ message: "Could not save: " + text.slice(0, 150), variant: "error" });
            submitting = false;
            if (submitBtn) {
              submitBtn.disabled = false;
              submitBtn.classList.remove("is-loading");
            }
          }
        } catch (err) {
          window.ccToast({ message: "Could not save -- network error. Please try again.", variant: "error" });
          submitting = false;
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.classList.remove("is-loading");
          }
        }
      });
    });
  }

  // 2026-08-08 view<->edit merge (see _modal_footer.html, and the
  // modal-stable-height marker the event/task/contact detail + form
  // templates carry): the dialog keeps one fixed width/height for a
  // detail-view/edit-form pair, and the header/body/footer cross-fade in
  // place when the modal navigates between the two states (or refreshes
  // via refreshModalContent) instead of hard-replacing.
  function stabilizeHeight(fragment) {
    if (!dialog) return;
    const stable = fragment && fragment.classList &&
      fragment.classList.contains("modal-stable-height");
    dialog.classList.toggle("is-stable-height", !!stable);
  }
  function animateContentSwap() {
    if (!dialog) return;
    dialog.classList.remove("is-swapped");
    void dialog.offsetWidth; // restart the animation cleanly
    dialog.classList.add("is-swapped");
  }

   async function openModal(url, trigger) {
     const wasOpen = overlay.classList.contains("is-open");
     if (trigger) trigger.classList.add("is-loading");
     let html;
     try {
       const resp = await fetch(url);
       html = await resp.text();
     } catch (err) {
       window.location.href = url; // offline/network failure -- fall back to a normal navigation
       return;
     } finally {
       if (trigger) trigger.classList.remove("is-loading");
     }
     const fragment = injectModalContent(html);
     if (!fragment) {
       // The page didn't opt into modal rendering (no #modal-target) --
       // don't guess, just navigate normally.
       window.location.href = url;
       return;
     }
     currentUrl = url;
     pendingReload = false;
     overlay.classList.add("is-open");
     // Size variant (2026-08-01) -- most modals (a field-grid form) are
     // fine at the default width, but a few (Schedule's Blocks table/week
     // grid, 9+ columns wide) need real room or they force a horizontal
     // scrollbar inside a modal that's already narrower than the content
     // wants. `data-modal-size="wide"` on the *trigger* link (not
     // hardcoded to a URL) is what the opening page decides, same as
     // data-modal/data-fab already work -- see _calendar_nav.html's
     // Schedule button. Reset on every open (not just when going wide) so
     // a wide modal doesn't stay wide once you navigate to a normal one
     // inside it (e.g. Schedule -> New block).
     if (dialog) {
       const size = trigger ? trigger.getAttribute("data-modal-size") : null;
       dialog.classList.toggle("is-wide", size === "wide");
     }
     // Show/hide the modal header based on whether the fragment
     // populated it -- the close button stays visible regardless
     // so the user always has an escape route.
     if (header) header.style.display = header.innerHTML.trim() ? "" : "none";
     if (footer) footer.style.display = footer.innerHTML.trim() ? "" : "none";
     wireContent();
     stabilizeHeight(fragment);
     if (wasOpen) animateContentSwap();
     const firstInput = body.querySelector("input, select, textarea");
     if (firstInput) firstInput.focus();
   }

  document.addEventListener("click", (e) => {
    // Event blocks on the Calendar time-grid (calendar.js) are both
    // `[data-modal]` links AND drag targets -- their own click handler
    // already calls
    // preventDefault() when a click turns out to have been a real drag,
    // specifically to stop the "open this" navigation from firing. This
    // listener runs after that one (bubble order: element before
    // document), so respecting defaultPrevented here is what stops a
    // completed drag from *also* popping the edit modal open.
    if (e.defaultPrevented) return;
    const trigger = e.target.closest("[data-modal]");
    if (!trigger) return;
    e.preventDefault();
    // Loading feedback (style.css's .is-loading) between tap and the
    // modal actually appearing -- previously nothing acknowledged the
    // click at all until the fetch resolved, which read as a dead tap on
    // a slow connection.
    openModal(trigger.getAttribute("data-modal") || trigger.getAttribute("href"), trigger);
  });

  // GET forms (a search box) inside the modal -- not something the click
  // delegation above covers at all, so without this a plain Enter-to-
  // search would submit as a normal navigation and silently kick the
  // user out of the modal (schedule_classes.html's search bar is the
  // first real case of this). Opt-in via `data-modal-get` rather than
  // handling every GET form generically, same "the page decides, not a
  // blanket rule" reasoning as data-modal/data-modal-size.
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-modal-get")) return;
    e.preventDefault();
    const params = new URLSearchParams(new FormData(form));
    const query = params.toString();
    openModal(form.action + (query ? "?" + query : ""), form);
  });

  // Click-outside-to-close for the color/icon popover -- a real
  // dropdown/menu convention, and needed here since it's no longer a
  // native <details> (which only toggles via its own trigger). Runs on
  // `mousedown` rather than `click` so it fires before a subsequent
  // click-based handler elsewhere (e.g. re-opening a different picker)
  // sees a stale state.
  document.addEventListener("mousedown", (e) => {
    if (!openPicker) return;
    if (openPicker.popover.contains(e.target)) return;
    const trigger = openPicker.picker.querySelector("." + openPicker.triggerClass);
    if (trigger && trigger.contains(e.target)) return;
    closeOpenPopover();
  });
  window.addEventListener("resize", closeOpenPopover);
  // Closes the popover when the page (or any scrollable ancestor of the
  // trigger) scrolls out from under it -- `position:fixed` means it would
  // otherwise stay pinned to the old viewport coordinates while the
  // trigger it's supposed to be anchored to visibly moves away.
  //
  // 2026-08-08 bug fix: `scroll` doesn't bubble, so `true` (capture) is
  // the only way for a single `window` listener to hear scroll events
  // from ANY scrollable descendant at all -- but that includes the
  // popover's own internal icon grid (.icon-popover has `overflow-y:auto`
  // + a fixed max-height, since the full icon set is ~70 options, far
  // more than fit without scrolling). Every scroll event was closing the
  // very popover the user was in the middle of scrolling through --
  // reported as "scrolling breaks it," and it did: literally un-openable
  // for long enough to actually browse the icon list, since any scroll
  // attempt closed it before a second one could register. Mirrors the
  // mousedown handler's own click-outside check just above: a scroll
  // whose target is the open popover itself (or something inside it)
  // isn't "the page scrolled out from under the trigger," so it's not a
  // close signal.
  window.addEventListener(
    "scroll",
    (e) => {
      if (openPicker && openPicker.popover.contains(e.target)) return;
      closeOpenPopover();
    },
    true
  );

  if (closeBtn) closeBtn.addEventListener("click", closeModal);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && openPicker) {
      closeOpenPopover();
      return;
    }
    if (e.key === "Escape" && overlay.classList.contains("is-open")) closeModal();
  });

  // Wire up any color/icon pickers already present on a plain full page
  // (2026-08-02, projects_manage.html -- not every page with a picker is
  // opened as a modal). Modal-injected content is wired separately, every
  // time it's (re)rendered, via wireContent() above.
  wireColorPickers(document);
  wireIconPickers(document);

  // Drag-down-to-dismiss for the mobile bottom-sheet form of .modal (see
  // style.css's max-width:720px block) -- Pointer Events rather than
  // mouse/touch separately, since this is a new gesture (not a port of an
  // existing mouse-only handler) and Pointer Events cover mouse, touch,
  // and pen with one listener. Only the handle bar is a drag target, not
  // the whole sheet, so it doesn't fight scrolling within .modal-body.
  const handle = document.getElementById("modal-handle");
  if (dialog && handle) {
    let dragging = false;
    let startY = 0;
    let currentY = 0;

    handle.addEventListener("pointerdown", (e) => {
      dragging = true;
      startY = e.clientY;
      currentY = 0;
      dialog.style.transition = "none";
      handle.setPointerCapture(e.pointerId);
    });
    handle.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      currentY = Math.max(0, e.clientY - startY);
      dialog.style.transform = `translateY(${currentY}px)`;
    });
    function endDrag() {
      if (!dragging) return;
      dragging = false;
      dialog.style.transition = "";
      dialog.style.transform = "";
      // Past ~90px of drag, treat it as an intentional dismiss rather
      // than a small accidental nudge -- matches the "flick past a
      // threshold" feel of native iOS/Material sheets.
      if (currentY > 90) closeModal();
    }
    handle.addEventListener("pointerup", endDrag);
    handle.addEventListener("pointercancel", endDrag);
  }

  window.CCModal = {
    open: openModal,
    close: closeModal,
    // markChanged() flags the modal as having unsaved page state so
    // closing (X/Escape/backdrop) reloads the underlying page; refresh()
    // re-fetches the modal's own URL and re-renders it in place without
    // closing -- used by data-modal-keep-open forms (e.g. calendars_list.
    // html's per-row edits). No longer used by the Customize modal's own
    // builder form (2026-08-07 removal of dashboard_widget_builder.js's
    // stay-open flow) -- that form is a plain add-and-close form now.
    markChanged: function () {
      pendingReload = true;
    },
    refresh: function () {
      return refreshModalContent();
    },
  };
})();
