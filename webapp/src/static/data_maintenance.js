/* Data & Maintenance page + its two remaining dialogs (2026-08-26 redesign;
 * 2026-09-09: the reset-database dialog was replaced by a confirm toast,
 * see below).
 *
 * Progressive enhancement for the export/import dialogs -- both work
 * without this script: the export dialog's Download submits a plain GET
 * form (data-modal-get keeps modal.js's POST interceptor out of the way);
 * the import dialog is a plain multipart form. What JS adds there is the
 * live "Includes: ..." export preview, the drag-and-drop affordance with a
 * "Detected: ..." preview before anything is uploaded, and gating Import on
 * a recognizable file.
 *
 * "Reset database (purge all)" is the one exception, JS-only end to end:
 * it's a plain <button>, not a link to a real page, and opens a
 * ccConfirmSheet (static/toast.js) carrying the DELETE ALL typed-phrase
 * gate -- with no JS there's nothing to click through to at all. Same
 * tradeoff the old modal already had in practice (its submit button shipped
 * server-disabled and only this script could ever arm it), just made
 * explicit now that there's no page underneath it either.
 *
 * Page-local: only settings_data_maintenance.html loads it -- but the two
 * dialogs' markup (export_modal.html / import_modal.html) is injected into
 * the modal overlay AFTER this script has long since run, so every listener
 * binds by event delegation at the document level and works no matter when
 * the markup appears.
 */
(function () {
  "use strict";

  function closest(el, selector) {
    return el && el.closest ? el.closest(selector) : null;
  }

  // ---- ?note=/?error= banner -> toast (2026-09-09 direct request) --------
  //
  // Every action on this page (Backup now, Verify, Restore, Compact &
  // reindex, sync retention/cleanup, purge completed, integrity check...)
  // redirects back here with a message in the query string rather than a
  // fetch-based response -- deliberate progressive enhancement, see this
  // file's own header comment, so those routes stay plain form posts that
  // work with no JS at all. settings_data_maintenance.html renders that
  // message as a static `[data-dm-flash]` banner as its no-JS fallback.
  // When ccToast IS available, this fires the same message as a floating
  // toast instead -- the notification style every delete/archive elsewhere
  // in the app already uses (app.js) -- then removes the banner and strips
  // note/error from the URL so a refresh or share link doesn't repeat it.
  // Runs once, at load; nothing on this page adds a new flash banner later
  // without a full page redirect, so there's no delegated case to cover.
  document.addEventListener("DOMContentLoaded", function () {
    var flashes = document.querySelectorAll("[data-dm-flash]");
    if (!flashes.length) return;
    if (window.ccToast) {
      flashes.forEach(function (el) {
        window.ccToast({
          message: el.textContent.trim(),
          variant: el.getAttribute("data-dm-flash") === "error" ? "error" : "default",
        });
        el.remove();
      });
    }
    if (window.history && window.history.replaceState) {
      var url = new URL(window.location.href);
      url.searchParams.delete("note");
      url.searchParams.delete("error");
      window.history.replaceState({}, document.title, url.pathname + url.search + url.hash);
    }
  });

  // ---- Export dialog: live "Includes: N Events, N Tasks, N Contacts" ----
  //
  // Each <option> carries its own server-rendered phrase in
  // data-dm-preview; this composes it with the format's packaging note, so
  // the wording lives in one place (the template).

  function refreshExportHint(scope) {
    var typeSelect = scope.querySelector("[data-dm-type]");
    var formatSelect = scope.querySelector("[data-dm-format]");
    var hint = scope.querySelector("[data-dm-hint]");
    if (!typeSelect || !hint) return;
    var opt = typeSelect.selectedOptions[0];
    if (!opt) return;
    var parts = [opt.dataset.dmPreview || ""];
    if (typeSelect.value === "labels") {
      parts.push("labels always export as .json.");
    } else if (typeSelect.value === "all") {
      parts.push(formatSelect && formatSelect.value === "csv"
        ? "one .zip of spreadsheets."
        : "one .zip bundle (.ics/.vcf).");
    } else {
      parts.push(formatSelect && formatSelect.value === "csv"
        ? "opens in any spreadsheet app."
        : "opens in any calendar or contacts app.");
    }
    hint.textContent = parts.filter(Boolean).join(" \u00b7 ");
    if (formatSelect) {
      var labelsPicked = typeSelect.value === "labels";
      formatSelect.disabled = labelsPicked;
      formatSelect.title = labelsPicked ? "Labels always export as .json" : "";
    }
  }

  // ---- Import dialog: detection preview -----------------------------------
  //
  // Mirrors routers/export.py's server-side sniff (vCard / iCalendar / this
  // app's own CSV shapes / JSON backup) so the user sees what will happen
  // before submitting -- cheap text scanning, not a real parser: the server
  // is still the authority, this is only the preview.

  function pluralize(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

  function detectCsv(text) {
    // Same recognition rule as routers/export.py::_csv_kind: only this
    // app's own three export header rows count as CSV.
    var firstLine = (text.split(/\r?\n/, 1)[0] || "").trim();
    if (!firstLine) return null;
    var cells = firstLine.split(",").map(function (c) { return c.trim().toLowerCase(); });
    var shapes = {
      tasks: ["uid", "title", "status", "due", "importance", "urgency", "tags"],
      events: ["uid", "title", "start", "end", "all day", "location", "meeting url", "tags"],
      contacts: ["uid", "name", "organization", "phone", "email", "address", "tags"]
    };
    var names = Object.keys(shapes);
    for (var i = 0; i < names.length; i++) {
      if (cells.length === shapes[names[i]].length &&
          shapes[names[i]].every(function (h, j) { return h === cells[j]; })) {
        return { kind: "csv", detail: names[i] + ".csv spreadsheet" };
      }
    }
    return null;
  }

  function detect(text) {
    var head = text.replace(/^[\ufeff\s]+/, "").slice(0, 64).toUpperCase();
    var near = text.slice(0, 4096).toUpperCase();
    if (head.indexOf("BEGIN:VCARD") === 0) {
      return { kind: "contacts", detail: pluralize((text.match(/BEGIN:VCARD/g) || []).length, "contact") };
    }
    if (head.indexOf("BEGIN:VCALENDAR") === 0 || near.indexOf("BEGIN:VCALENDAR") !== -1) {
      var events = (text.match(/BEGIN:VEVENT/g) || []).length;
      var tasks = (text.match(/BEGIN:VTODO/g) || []).length;
      return { kind: "ics", detail: pluralize(events, "event") + ", " + pluralize(tasks, "task") };
    }
    var found = detectCsv(text);
    if (found) return found;
    try {
      var data = JSON.parse(text);
      if (data && typeof data === "object" &&
          ["events", "tasks", "contacts", "labels", "object_labels"].some(function (k) { return Array.isArray(data[k]); })) {
        return {
          kind: "json",
          detail: "Full backup (JSON) -- " + pluralize((data.events || []).length, "event") +
            ", " + pluralize((data.tasks || []).length, "task") +
            ", " + pluralize((data.contacts || []).length, "contact"),
        };
      }
    } catch (err) { /* fall through */ }
    return null;
  }

  function setStatus(form, message, isError) {
    var status = form && form.querySelector("[data-dm-status]");
    if (!status) return;
    status.textContent = message;
    status.classList.toggle("dm-status-error", !!isError);
    status.hidden = !message;
  }

  function previewFile(input) {
    var form = input.closest("form");
    // 2026-08-30 (modal-footer-consistency fix): the Import button moved
    // from inside this <form> into the shared modal footer (a sibling,
    // linked back to the form only via its `form="import-form"`
    // attribute) -- form.querySelector can't see it there since that only
    // searches DOM descendants, so this looks it up by the stable id
    // import_modal.html's footer_primary_id now gives it instead.
    var submitBtn = document.getElementById("import-submit-btn");
    var file = input.files && input.files[0];
    if (!file) {
      setStatus(form, "", false);
      if (submitBtn) submitBtn.disabled = false;
      return;
    }
    file.text().then(function (text) {
      var found = detect(text);
      if (found) {
        setStatus(form, "Detected: " + found.detail + " (" + found.kind.toUpperCase() + "). Ready to import.", false);
        if (submitBtn) submitBtn.disabled = false;
      } else {
        setStatus(form, "Unrecognized file -- use an .ics calendar, .vcf contacts, .csv from this app's own export, or a data.json backup.", true);
        if (submitBtn) submitBtn.disabled = true;
      }
    });
  }

  // ---- Delegated bindings (dialogs inject after load) ---------------------

  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t.matches) return;
    if (t.matches("[data-dm-type],[data-dm-format]")) {
      var root = closest(t, "[data-dm-export-root]") || document;
      refreshExportHint(root);
    } else if (t.matches("[data-dm-file]")) {
      previewFile(t);
    }
  });

  // Drag-and-drop onto the dropzone label; the input itself stays the real
  // field so a dropped file submits exactly like a picked one. dragover has
  // to keep preventDefault()ing for a drop to be allowed at all, which is
  // why enter/over and leave/drop are separate delegated pairs.
  ["dragenter", "dragover"].forEach(function (evt) {
    document.addEventListener(evt, function (e) {
      var zone = closest(e.target, "[data-dm-dropzone]");
      if (!zone) return;
      e.preventDefault();
      zone.classList.add("is-dragover");
    });
  });
  ["dragleave", "drop"].forEach(function (evt) {
    document.addEventListener(evt, function (e) {
      var zone = closest(e.target, "[data-dm-dropzone]");
      if (!zone) return;
      e.preventDefault();
      zone.classList.remove("is-dragover");
    });
  });
  document.addEventListener("drop", function (e) {
    var zone = closest(e.target, "[data-dm-dropzone]");
    if (!zone) return;
    var form = zone.closest("form");
    var input = form && form.querySelector("[data-dm-file]");
    var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (!input || !file) return;
    try {
      var dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
    } catch (err) {
      return; // ancient browser without DataTransfer: picker still works
    }
    previewFile(input);
  });

  // ---- Reset database (purge all): confirm-toast + typed DELETE ALL gate --
  //
  // 2026-09-09 direct request: the standalone confirmation modal
  // (purge_modal.html) is gone -- "Reset database (purge all)" in the
  // Database card's menu now opens a persistent confirm toast
  // (ccConfirmSheet's `typedConfirm` option, static/toast.js) instead of
  // navigating to a page. Same bar as the old modal: the Permanently
  // Delete button starts disabled and only arms once the input reads
  // exactly "DELETE ALL" -- see toast.js for the arm/disarm wiring itself,
  // this just supplies the message/phrase and does the actual POST once
  // confirmed. Backups are never touched by this -- purge_all_data (db.py)
  // only clears this app's own SQLite tables; backup-*.json files live on
  // disk in a separate directory purge-all never reads from.
  document.addEventListener("click", function (e) {
    var btn = closest(e.target, '[data-action="purge-all"]');
    if (!btn) return;
    window.ccConfirmSheet({
      anchor: btn,
      message: "Deletes every task, event, contact, label, habit, and published list. Backups are kept.",
      // confirmLabel omitted -- ccConfirmSheet's own default ("Delete") is
      // exactly what every other confirm toast in the app already uses.
      typedConfirm: { matchValue: "DELETE ALL" },
      onConfirm: function () {
        fetch("/settings/purge-all", { method: "POST", headers: { "X-Requested-With": "fetch" } })
          .then(function (resp) {
            if (!resp.ok) throw new Error("purge failed");
            window.location.reload(); // also carries a forced re-login if auth is enabled
          })
          .catch(function () {
            window.ccToast({ message: "Could not reset the database. Try again.", variant: "error" });
          });
      },
    });
  });

  // "Force sync" (originally moved off settings_data_maintenance.html's own
  // inline <script> 2026-09-07, audit-fixes-2.0.md item 11 -- CSP
  // `'unsafe-inline'` elimination) was removed outright 2026-09-09: it only
  // ever worked by calling window.CCOfflineSync.syncNow(), defined by
  // static/offline_sync_client.js, which was deleted along with the rest of
  // the client-side Offline Mode feature (direct request, "purge it"). No
  // client engine means no way to force a push/pull round -- the button
  // could only ever show "Sync engine not available" now, so the template's
  // own button and this file's forceSyncFromServer/click-delegation were
  // both removed rather than left as a guaranteed-broken control. See
  // templates/settings_data_maintenance.html's own comment at the same spot.
})();
