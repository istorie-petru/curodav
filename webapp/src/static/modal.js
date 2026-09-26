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
    // 2026-09-08 direct report: a form rejected with FastAPI's 422 (e.g. a
    // required field missing) surfaced its raw JSON validation body --
    // `{"detail":[{"type":"missing","loc":["body","date_from"],...}]}` --
    // straight into the error toast, truncated at 150 characters. Turns a
    // real (if now mostly-preventable, see datetime_picker.js's own
    // required-field guard) server rejection into something unreadable.
    // Recognizes FastAPI/Pydantic's own `detail: [{type, loc, msg}, ...]`
    // shape specifically and renders each entry as "<field>: <msg>";
    // anything else (a plain-text 500, an HTML error page, a detail string)
    // falls back to the raw text exactly as before.
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

    // 2026-09-17 (design-system unification pass, shared spec at
    // /home/peter/Claude/Projects/DESIGN_SYSTEM.md) -- friendlyErrorMessage
    // above turns a 422 into one readable toast line, but a toast still
    // doesn't tell you *which* input on a long form (task/event/contact)
    // is wrong. applyFieldErrors marks each error against its actual
    // field (a red border + a .field-error line right under it, style.css)
    // and focuses the first one, falling back to the toast only for
    // whatever doesn't match a visible input (a nested/array loc path with
    // no single form field to point at).
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
  let pendingReload = false;
  // Habits H3 (2026-09-24): when every keep-open form that changed
  // something carried data-cc-change, closing the modal dispatches that
  // change (the page refreshes just its own live region) instead of a
  // full reload. Any keep-open form without it forces the reload.
  let pendingChange = null;
  let pendingForceReload = false;

   function closeModal() {
     overlay.classList.remove("is-open");
     // 2026-09-08 bugfix (direct report, confirmed live: the persistent
     // mobile bottom bar -- Menu/Home/Search, base.html's .mobile-tabbar
     // -- sat at a higher z-index than the modal overlay and covered the
     // open dialog's own footer buttons on every phone-width viewport.
     // style.css's body.modal-open rule hides that bar for as long as
     // this class is present; removed here on every close path (X,
     // Escape, backdrop click -- all of which call this function) so it
     // never gets stuck hidden.
     document.body.classList.remove("modal-open");
     body.innerHTML = "";
     if (header) header.innerHTML = "";
     if (footer) footer.innerHTML = "";
     currentUrl = null;
     if (pendingReload) {
       pendingReload = false;
       const change = pendingForceReload ? null : pendingChange;
       pendingChange = null;
       pendingForceReload = false;
       if (!(change && window.ccApi && window.ccApi.dispatchChange && window.ccApi.dispatchChange(change))) {
         window.location.reload();
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
    // 2026-09-12 bugfix (direct report, "the banner upload still doesn't
    // work"): banner_editor.html's Upload control has lived in
    // #modal-footer (not #modal-body) since the 2026-09-08 "Remove/Upload
    // move into the footer" slice (_modal_footer.html's footer_extra_html
    // escape hatch) -- but this init call, and the form-submit-intercept
    // loop below, only ever scanned `body`. CCAvatarCropper.init(body)
    // never found `.banner-upload-input` in the footer, so selecting a
    // file never opened the crop editor and nothing ever called
    // form.requestSubmit() -- the upload form just sat there with a file
    // chosen and no way to submit it. Also init on `footer` so a banner
    // upload (and any future footer_extra_html file input) gets wired the
    // same as a body one.
    if (window.CCAvatarCropper) {
      window.CCAvatarCropper.init(body);
      if (footer) window.CCAvatarCropper.init(footer);
    }
    // contact_form.html's Phone/Email add/remove rows (Contacts field
    // parity slice 2 of 6) -- same re-init reasoning.
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
    // Relations cards' add-row picker (1.2 side work, static/
    // command_palette.js) needs no re-init call here -- its entry points
    // are document-level delegated listeners, which already cover content
    // injected via this innerHTML swap without a wireContent() hook.
    // Merged task/event quick-add modal (quick_add.html, 2026-08-10) --
    // tab switch between the two create-forms + retargeting the footer
    // Save button's `form` attribute. Same re-init reasoning.
    if (window.CCQuickAdd) window.CCQuickAdd.init(body);

    // Widget Builder (dashboard_customize.html): add-widget form + live
    // preview live inside the modal, injected via innerHTML like Schedule's
    // widgets. CCWidgetPreview.init wires the Source/View/Range controls
    // and the live preview for both the builder and each edit form. The
    // builder form itself is a plain add-and-close form now (2026-08-07,
    // "Add widget should be the only button") -- it has no data-builder
    // any more, so it falls straight through to the generic form handler
    // below like any other modal form.
    if (window.CCWidgetPreview) window.CCWidgetPreview.init(body);

    // 2026-09-12 bugfix (same report as the CCAvatarCropper.init call
    // above): this used to be `body.querySelectorAll("form").forEach(...)`
    // only -- a footer_extra_html form (banner_editor.html's Upload/Remove,
    // the only current user) lives in #modal-footer, a sibling of
    // #modal-body, so it was never wired here either. Upload has no submit
    // button of its own (the crop editor's Apply is what calls
    // form.requestSubmit() once wiring above is fixed), so with neither fix
    // applied a chosen file had literally no path to actually submit.
    // Factored into a named function so the same per-form wiring applies to
    // both `body` and `footer` forms without duplicating the whole handler.
    const wireForm = (form) => {
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
            headers: { "X-Requested-With": "fetch" },
            body: new FormData(form),
          });
          if (resp.ok) {
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
              // 2026-09-25 (group/label rename): a form marked
              // data-follow-redirect goes where the server redirected when
              // that's a different page. Renaming the group or label whose
              // page is open would otherwise reload the old URL, which no
              // longer exists (it lands on the labels list). Same page ->
              // falls through to the normal refresh below.
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
                  window.location.reload();
                }
              } else {
                window.location.reload();
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

  // 2026-08-30 (direct feedback): min-height tiers -- see style.css's
  // .modal-height-md/.modal-height-lg comment. Same "fragment states its
  // own shape, JS mirrors the marker onto the persistent .modal dialog"
  // pattern stabilizeHeight above already uses (#modal-target is swapped
  // out on every navigation; the dialog element wrapping it isn't).
  function applyHeightTier(fragment) {
    if (!dialog) return;
    const isMd = fragment && fragment.classList && fragment.classList.contains("modal-height-md");
    const isLg = fragment && fragment.classList && fragment.classList.contains("modal-height-lg");
    dialog.classList.toggle("is-height-md", !!isMd && !isLg);
    dialog.classList.toggle("is-height-lg", !!isLg);
  }
  // 2026-09-09 (direct follow-up, "the mobile handle should sit on top
  // of the banner") -- style.css's `.modal.has-cover .modal-handle` rule
  // floats the drag handle over a cover image instead of its own row
  // above a plain header; this is what decides whether that rule is
  // live. Same "fragment states its own shape, JS mirrors the marker
  // onto the persistent dialog" pattern stabilizeHeight/applyHeightTier
  // above use, just detected by content (`.detail-cover-wrap` inside the
  // now-populated #modal-header) rather than a marker class on
  // #modal-target itself -- the cover only sometimes renders even within
  // one template (banner_editor.html's `{% if banner %}`), so a static
  // class on the outer fragment wouldn't track that.
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
     applyHeightTier(fragment);
     applyCoverHandle();
     if (wasOpen) animateContentSwap();
     // data-no-autofocus (habits H3): a view modal's secondary inputs
     // (the habit detail's "Log a day" form) shouldn't grab focus -- and
     // scroll the modal / raise a phone keyboard -- on open.
     const firstInput = body.querySelector("input:not([data-no-autofocus]), select:not([data-no-autofocus]), textarea:not([data-no-autofocus])");
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

  if (closeBtn) closeBtn.addEventListener("click", closeModal);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });

  // Keyboard focus trap (audit-fixes-2.0.md #4, full-app-audit-2026-09-07.md
  // finding #2, WCAG 2.1.2/2.4.3) -- Escape-to-close already existed below,
  // but nothing stopped Tab/Shift+Tab from walking focus straight out of an
  // open modal into the page behind it. `dialog` (#modal-dialog) is the
  // fixed element that wraps header/body/footer across every open/refresh/
  // navigate cycle (see stabilizeHeight's comment above), so querying it
  // fresh on every keydown -- rather than caching a focusable list at open
  // time -- stays correct across refreshModalContent()/form navigation
  // swapping #modal-body's content underneath it.
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
    if (e.key === "Escape" && overlay.classList.contains("is-open")) closeModal();
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
      pendingForceReload = true;
    },
    // 2026-09-25 (static/habit_day.js): like markChanged, but closing
    // dispatches `change` (the page refreshes its live region) instead
    // of a full reload -- same as a keep-open form with data-cc-change.
    markChangedWith: function (change) {
      pendingReload = true;
      pendingChange = change;
    },
    refresh: function () {
      return refreshModalContent();
    },
  };
})();
