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
    function friendlyErrorMessage(text) {
      try {
        const body = JSON.parse(text);
        if (Array.isArray(body && body.detail)) {
          const msgs = body.detail.map((d) => {
            const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : null;
            return field ? field + ": " + d.msg : d.msg;
          });
          if (msgs.length) return msgs.join("; ").slice(0, 150);
        } else if (typeof (body && body.detail) === "string") {
          return body.detail.slice(0, 150);
        }
      } catch (err) {
        // Not JSON -- fall through to the raw-text fallback below.
      }
      return text.slice(0, 150);
    }

    function clearFieldErrors(form) {
      form.querySelectorAll(".field.has-error").forEach((f) => f.classList.remove("has-error"));
      form.querySelectorAll(".field-error").forEach((e) => e.remove());
    }

    // Returns the messages that had no matching input (still need the
    // toast), or null if `text` isn't the FastAPI/Pydantic detail shape at
    // all (caller falls back to the unchanged raw-text toast in that case).
    function applyFieldErrors(form, text) {
      clearFieldErrors(form);
      let detail;
      try {
        const body = JSON.parse(text);
        detail = Array.isArray(body && body.detail) ? body.detail : null;
      } catch (err) {
        return null;
      }
      if (!detail) return null;
      const unmatched = [];
      let firstInvalid = null;
      for (const d of detail) {
        const fieldName = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : null;
        const input = fieldName ? form.querySelector(`[name="${CSS.escape(String(fieldName))}"]`) : null;
        const field = input ? input.closest(".field") : null;
        if (!field) {
          unmatched.push(fieldName ? fieldName + ": " + d.msg : d.msg);
          continue;
        }
        field.classList.add("has-error");
        const hint = document.createElement("span");
        hint.className = "field-error";
        hint.textContent = d.msg;
        field.appendChild(hint);
        if (!firstInvalid) firstInvalid = input;
      }
      if (firstInvalid) firstInvalid.focus();
      return unmatched;
    }

    const overlay = document.getElementById("modal-overlay");
    const dialog = document.getElementById("modal-dialog");
    const header = document.getElementById("modal-header");
    const body = document.getElementById("modal-body");
    const footer = document.getElementById("modal-footer");
    const closeBtn = document.getElementById("modal-close");
    if (!overlay || !body) return;

  let currentUrl = null;
  // Back stack: the modals visited before the current one, so Escape and
  // Cancel can walk back to the original window like a browser does.
  const modalStack = [];
  let pendingReload = false;
  let pendingChange = null;
  let pendingForceReload = false;
  let customCloseHandler = null;

   function closeModal() {
     // A modal that owns a buffer record (a new contact's draft) names the
     // URL that drops it; Save has already turned it into a real record by
     // the time it closes, so the server leaves a saved record alone.
     const discard = overlay.querySelector("[data-discard-url]");
     if (discard) {
       fetch(discard.getAttribute("data-discard-url"), { method: "POST", keepalive: true });
     }
     if (customCloseHandler) {
       const handler = customCloseHandler;
       customCloseHandler = null;
       handler();
     }
     overlay.classList.remove("is-open");
     document.body.classList.remove("modal-open");
     body.innerHTML = "";
     if (header) header.innerHTML = "";
     if (footer) footer.innerHTML = "";
     currentUrl = null;
     modalStack.length = 0;
     if (pendingReload) {
       pendingReload = false;
       const change = pendingForceReload ? null : pendingChange;
       pendingChange = null;
       pendingForceReload = false;
       if (!(change && window.ccApi && window.ccApi.dispatchChange && window.ccApi.dispatchChange(change))) {
         refreshPage();
       }
     }
   }

   // 2026-09-24 (CSP fix): a modal URL returns a full page, and its
   // base.html head carries `<style nonce="...">` with *that response's*
   // nonce. DOMParser's document inherits this page's CSP, so parsing it
   // logged a style-src-elem violation on every modal open. Those <style>
   // blocks could never apply here anyway (wrong nonce; the accent rule is
   // already live from this page's own head), so strip them before parsing
   // rather than loosening the policy.
   const STYLE_BLOCK_RE = /<style\b[^>]*>[\s\S]*?<\/style\s*>/gi;

   function injectModalContent(html) {
     const doc = new DOMParser().parseFromString(html.replace(STYLE_BLOCK_RE, ""), "text/html");
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
     const resp = await fetch(currentUrl);
     const html = await resp.text();
     const fragment = injectModalContent(html);
     if (!fragment) return;
     wireContent();
     stabilizeHeight(fragment);
     applyHeightTier(fragment);
     applyCoverHandle();
     animateContentSwap();
   }

   // The first visible text field gets focus, so the user can type straight away.
  // Re-renders the page's smart regions in place; a page without any is reloaded.
  function refreshPage() {
    if (!window.ccSmartRefresh) return window.location.reload();
    window.ccSmartRefresh().then((done) => { if (!done) window.location.reload(); });
  }

  function focusFirstField(root) {
    const fields = root.querySelectorAll(
      "input:not([data-no-autofocus]):not([type=hidden]):not([type=radio]):not([type=checkbox]), textarea:not([data-no-autofocus])"
    );
    for (const el of fields) {
      if (el.disabled || el.readOnly || !el.getClientRects().length) continue;
      el.focus();
      return;
    }
  }

  function wireContent() {
    // Lets a page script (e.g. push_settings.js) set itself up on content
    // that was injected after the page loaded.
    document.dispatchEvent(new CustomEvent("cc-modal-content"));
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

    if (window.CCAvatarCropper) {
      window.CCAvatarCropper.init(body);
      if (footer) window.CCAvatarCropper.init(footer);
    }
    if (window.CCContactPhoneEmailRows) window.CCContactPhoneEmailRows.init(body);
    // task_form.html's Daily target visibility -- same re-init reasoning.
    if (window.CCHabitFieldToggle) window.CCHabitFieldToggle.init(body);
    // label_edit_modal.html's Role picker (Space/Project date-field
    // reveal + switch-away confirm) -- same re-init reasoning.
    if (window.CCLabelRolePicker) window.CCLabelRolePicker.init(body);
    // label_form_modal.html's Space/Project checkbox toggles -- same
    // re-init reasoning.
    if (window.CCLabelFormPicker) window.CCLabelFormPicker.init(body);
    // _event_form_fields.html's Format field (clears the other field's
    // value on switch) -- same re-init reasoning.
    if (window.CCEventFormatToggle) window.CCEventFormatToggle.init(body);
    // holiday_edit_modal.html's Start/End date auto-sync -- same re-init
    // reasoning.
    if (window.CCHolidayDateSync) window.CCHolidayDateSync.init(body);
    // notebook_properties_modal.html's Properties add/remove rows -- same
    // re-init reasoning.
    if (window.CCNotebookPropertyRows) window.CCNotebookPropertyRows.init(body);
    // notebook_field_edit_modal.html's Type toggle + Options add/remove
    // rows -- same re-init reasoning.
    if (window.CCNotebookFieldOptionRows) window.CCNotebookFieldOptionRows.init(body);
    if (window.CCQuickAdd) window.CCQuickAdd.init(body);

    if (window.CCWidgetPreview) window.CCWidgetPreview.init(body);

    const wireForm = (form) => {
      // data-modal-get forms (a search box) are handled by their own
      // document-level listener below instead -- this per-form handler
      // assumes a POST-and-fetch shape (method: form.method || "POST",
      // sends a body), which is meaningless for a GET request and would
      // throw trying to attach a body to one. Skip entirely rather than
      // let both handlers fight over the same submit.
      if (form.hasAttribute("data-modal-get")) return;
      let submitting = false;
      const keepOpen = form.hasAttribute("data-modal-keep-open") || !!form.closest("[data-keep-open]");
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
            headers: { "X-Requested-With": "fetch" },
            body: new FormData(form),
          });
          if (resp.ok) {
            // A handler that answers a fetch with `redirect(...?note=/?error=)`
            // (the settings pages) reports through a toast, since the
            // redirected page itself is never shown here.
            if (resp.redirected) {
              const q = new URL(resp.url, window.location.href).searchParams;
              if (q.get("error")) window.ccToast({ message: q.get("error"), variant: "error" });
              else if (q.get("note")) window.ccToast({ message: q.get("note") });
            }
            if (keepOpen) {
              pendingReload = true;
              const keepChange = form.getAttribute("data-cc-change");
              if (keepChange) {
                pendingChange = { type: keepChange, action: form.getAttribute("data-cc-action") || "edit" };
              } else {
                pendingForceReload = true;
              }
              await refreshModalContent(); // re-render in place, modal stays open
            } else {
              closeModal();
              if (form.hasAttribute("data-follow-redirect") && resp.redirected) {
                const dest = new URL(resp.url, window.location.href);
                if (dest.origin === window.location.origin && dest.pathname !== window.location.pathname) {
                  window.location.href = dest.pathname + dest.search;
                  return;
                }
              }
              // async-CRUD (features/async-crud.md): a form marked
              // data-cc-change opts out of the full-page reload -- on
              // success we dispatch a document-level cc-entity-changed event
              // and let the page underneath refresh just its own region.
              // If no surface listener claims the event (this page has no
              // live region for that entity type), fall back to a reload so
              // the page can't silently go stale.
              const changeType = form.getAttribute("data-cc-change");
              const changeAction = form.getAttribute("data-cc-action") || "edit";
              if (changeType && window.ccApi && window.ccApi.dispatchChange) {
                if (!window.ccApi.dispatchChange({ type: changeType, action: changeAction })) {
                  refreshPage();
                }
              } else {
                refreshPage();
              }
            }
          } else {
            const text = await resp.text().catch(() => "");
            const unmatched = applyFieldErrors(form, text);
            if (unmatched === null) {
              window.ccToast({ message: "Could not save: " + friendlyErrorMessage(text), variant: "error" });
            } else if (unmatched.length) {
              window.ccToast({ message: "Could not save: " + unmatched.join("; ").slice(0, 150), variant: "error" });
            }
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
    };
    body.querySelectorAll("form").forEach(wireForm);
    if (footer) footer.querySelectorAll("form").forEach(wireForm);
  }

  function stabilizeHeight(fragment) {
    if (!dialog) return;
    const stable = fragment && fragment.classList &&
      fragment.classList.contains("modal-stable-height");
    dialog.classList.toggle("is-stable-height", !!stable);
  }

  function applyHeightTier(fragment) {
    if (!dialog) return;
    const isMd = fragment && fragment.classList && fragment.classList.contains("modal-height-md");
    const isLg = fragment && fragment.classList && fragment.classList.contains("modal-height-lg");
    dialog.classList.toggle("is-height-md", !!isMd && !isLg);
    dialog.classList.toggle("is-height-lg", !!isLg);
  }
  function applyCoverHandle() {
    if (!dialog || !header) return;
    dialog.classList.toggle("has-cover", !!header.querySelector(".detail-cover-wrap"));
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
     const endBusy = window.ccBusy ? window.ccBusy.begin() : null;
     try {
       html = await (window.ccPrefetch ? window.ccPrefetch.text(url) : fetch(url).then((resp) => resp.text()));
     } catch (err) {
       window.location.href = url; // offline/network failure -- fall back to a normal navigation
       return;
     } finally {
       if (endBusy) endBusy();
       if (trigger) trigger.classList.remove("is-loading");
     }
     const fragment = injectModalContent(html);
     if (!fragment) {
       // The page didn't opt into modal rendering (no #modal-target) --
       // don't guess, just navigate normally.
       window.location.href = url;
       return;
     }
     if (wasOpen && currentUrl && url !== currentUrl) {
       // Returning to the modal below this one pops it; anything else pushes.
       if (modalStack.length && modalStack[modalStack.length - 1] === url) modalStack.pop();
       else modalStack.push(currentUrl);
     }
     currentUrl = url;
     // Navigating inside an already-open modal (e.g. a habit's month
     // arrows) keeps any change made earlier in it pending for close.
     if (!wasOpen) {
       pendingReload = false;
       pendingChange = null;
       pendingForceReload = false;
     }
     overlay.classList.add("is-open");
     // See closeModal()'s own comment -- style.css hides the mobile
     // bottom bar (.mobile-tabbar) for as long as this class is present,
     // so it can't sit on top of the open dialog's footer.
     document.body.classList.add("modal-open");
     if (dialog) {
       const size = trigger ? trigger.getAttribute("data-modal-size") : null;
       dialog.classList.toggle("is-wide", size === "wide" || !!(body && body.querySelector("[data-modal-wide]")));
     }
     // Show/hide the modal header based on whether the fragment
     // populated it -- the close button stays visible regardless
     // so the user always has an escape route.
     if (header) header.style.display = header.innerHTML.trim() ? "" : "none";
     if (footer) footer.style.display = footer.innerHTML.trim() ? "" : "none";
     wireContent();
     stabilizeHeight(fragment);
     applyHeightTier(fragment);
     applyCoverHandle();
     if (wasOpen) animateContentSwap();
     // data-no-autofocus (habits H3): a view modal's secondary inputs
     // (the habit detail's "Log a day" form) shouldn't grab focus -- and
     // scroll the modal / raise a phone keyboard -- on open.
     focusFirstField(body);
   }

   function buildFooter(primary) {
     const frag = document.createDocumentFragment();
     function button(cls, icon, label, onClick) {
       const b = document.createElement("button");
       b.type = "button";
       b.className = "btn " + cls;
       b.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="#icon-' + icon + '"></use></svg> ';
       b.appendChild(document.createTextNode(label));
       b.addEventListener("click", onClick);
       return b;
     }
     frag.appendChild(button("ghost", "chevron-left", "Cancel", closeModal));
     const spacer = document.createElement("span");
     spacer.className = "spacer";
     frag.appendChild(spacer);
     if (primary) frag.appendChild(button("primary", primary.icon || "check-square", primary.label, primary.onClick));
     return frag;
   }

   function openCustomModal(opts) {
     if (!opts || !opts.bodyNode) return;
     // An already-open modal (shouldn't normally happen -- callers open
     // this for a single focused picker, not stacked on top of another
     // modal) is closed first so its own onClose still runs rather than
     // being silently dropped by the overwrite below.
     if (overlay.classList.contains("is-open")) closeModal();
     customCloseHandler = opts.onClose || null;
     if (header) {
       header.innerHTML = "";
       if (opts.title) {
         const h1 = document.createElement("h1");
         h1.textContent = opts.title;
         header.appendChild(h1);
         header.style.display = "";
       } else {
         header.style.display = "none";
       }
     }
     body.innerHTML = "";
     body.appendChild(opts.bodyNode);
     body.style.display = "";
     if (footer) {
       footer.innerHTML = "";
       if (opts.footerNode) {
         footer.appendChild(opts.footerNode);
         footer.style.display = "";
       } else {
         footer.style.display = "none";
       }
     }
     currentUrl = null;
     pendingReload = false;
     pendingChange = null;
     pendingForceReload = false;
     overlay.classList.add("is-open");
     document.body.classList.add("modal-open");
     if (dialog) dialog.classList.toggle("is-wide", opts.size === "wide");
     stabilizeHeight(null);
     applyHeightTier(null);
     applyCoverHandle();
     focusFirstField(body);
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

  if (closeBtn) closeBtn.addEventListener("click", closeModal);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });

  const FOCUSABLE_SELECTOR = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled]):not([type=hidden])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");

  function getFocusableElements() {
    if (!dialog) return [];
    return Array.prototype.filter.call(
      dialog.querySelectorAll(FOCUSABLE_SELECTOR),
      (el) => el.offsetParent !== null // skip hidden (display:none) elements
    );
  }

  function trapTabKey(e) {
    if (!overlay.classList.contains("is-open") || !dialog) return;
    const focusable = getFocusableElements();
    if (focusable.length === 0) {
      e.preventDefault();
      dialog.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (e.shiftKey) {
      // Shift+Tab off the first focusable (or from outside the dialog
      // entirely, e.g. focus landed on the overlay backdrop) wraps to last.
      if (active === first || !dialog.contains(active)) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (active === last || !dialog.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.classList.contains("is-open")) {
      if (modalStack.length) openModal(modalStack[modalStack.length - 1], null);
      else closeModal();
    }
    if (e.key === "Tab" && overlay.classList.contains("is-open")) trapTabKey(e);
  });

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
    // The open modal now lives at `url` (a form whose GET created its own
    // record, so going back must reopen that record, not make a new one).
    setUrl: function (url) {
      currentUrl = url;
    },
    openCustom: openCustomModal,
    footer: buildFooter,
    close: closeModal,
    markChanged: function () {
      pendingReload = true;
      pendingForceReload = true;
    },
    markChangedWith: function (change) {
      pendingReload = true;
      pendingChange = change;
    },
    refresh: function () {
      return refreshModalContent();
    },
  };
})();
