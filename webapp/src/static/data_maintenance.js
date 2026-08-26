/* Data & Maintenance page + its three dialogs (2026-08-26 redesign).
 *
 * Progressive enhancement only -- every surface works without this script:
 * the reset-database dialog's submit button ships disabled from the server
 * and only this script can arm it; the export dialog's Download submits a
 * plain GET form (data-modal-get keeps modal.js's POST interceptor out of
 * the way); the import dialog is a plain multipart form. What JS adds is
 * the live "Includes: ..." export preview, the drag-and-drop affordance
 * with a "Detected: ..." preview before anything is uploaded, gating
 * Import on a recognizable file, and the DELETE ALL typed-phrase gate.
 *
 * Page-local: only settings_data_maintenance.html loads it -- but ALL
 * three dialogs' markup (purge_modal.html / export_modal.html /
 * import_modal.html) is injected into the modal overlay AFTER this script
 * has long since run, so every listener binds by event delegation at the
 * document level and works no matter when the markup appears.
 */
(function () {
  "use strict";

  function closest(el, selector) {
    return el && el.closest ? el.closest(selector) : null;
  }

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
    var submitBtn = form && form.querySelector("[data-dm-submit]");
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

  // ---- Reset-database dialog: the DELETE ALL gate -------------------------
  //
  // The submit button renders disabled straight from the server; typing the
  // exact phrase arms it (and typing anything else disarms it again). That
  // typed phrase IS the check -- there is no second confirm popover on top.

  document.addEventListener("input", function (e) {
    var phrase = e.target;
    if (!phrase.matches || !phrase.matches("[data-purge-phrase]")) return;
    var form = phrase.closest("form");
    var btn = form && form.querySelector("[data-purge-btn]");
    if (!btn) return;
    var armed = phrase.value === "DELETE ALL";
    btn.disabled = !armed;
    phrase.classList.toggle("is-armed", armed);
  });
})();
