/* Data & Maintenance page enhancements (2026-08-26 redesign).
 *
 * Progressive enhancement only -- every section works without this script:
 * both Export/Import panes are plain forms and pane switching is CSS (:has()
 * on the segmented radio); the reset-database dialog's submit button ships
 * disabled from the server and only this script can arm it. What JS adds is
 * the live "Includes: ..." export preview, the drag-and-drop affordance with
 * a "Detected: ..." preview before anything is uploaded, gating Import on a
 * recognizable file, and the DELETE ALL typed-phrase gate.
 *
 * Page-local: only settings_data_maintenance.html loads it. The purge
 * confirmation lives in a modal injected AFTER load (purge_modal.html), so
 * the gate binds via event delegation at the document level -- it works no
 * matter when the dialog's markup appears.
 */
(function () {
  "use strict";

  // ---- Export & import card ----------------------------------------------

  var root = document.querySelector("[data-dm-root]");

  if (root) {
    var fileInput = root.querySelector("[data-dm-file]");
    var status = root.querySelector("[data-dm-status]");
    var zone = root.querySelector("[data-dm-dropzone]");
    var submitBtn = root.querySelector("[data-dm-submit]");
    var typeSelect = root.querySelector("[data-dm-type]");
    var formatSelect = root.querySelector("[data-dm-format]");
    var hint = root.querySelector("[data-dm-hint]");

    // Export pane: live "Includes: N Events, N Tasks, N Contacts" preview.
    // Each <option> carries its own server-rendered phrase in
    // data-dm-preview; this only composes it with the format's packaging
    // note, so the wording lives in one place (the template).
    function refreshExportHint() {
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
    if (typeSelect && formatSelect) {
      typeSelect.addEventListener("change", refreshExportHint);
      formatSelect.addEventListener("change", refreshExportHint);
      refreshExportHint();
    }

    // Import pane: detection preview. Mirrors routers/export.py's
    // server-side sniff (vCard / iCalendar / this app's own CSV shapes /
    // JSON backup) so the user sees what will happen before submitting --
    // cheap text scanning, not a real parser: the server is still the
    // authority, this is only the preview.

    function setStatus(message, isError) {
      if (!status) return;
      status.textContent = message;
      status.classList.toggle("dm-status-error", !!isError);
      status.hidden = !message;
    }

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

    function preview(file) {
      if (!file) {
        setStatus("", false);
        if (submitBtn) submitBtn.disabled = false;
        return;
      }
      file.text().then(function (text) {
        var found = detect(text);
        if (found) {
          setStatus("Detected: " + found.detail + " (" + found.kind.toUpperCase() + "). Ready to import.", false);
          if (submitBtn) submitBtn.disabled = false;
        } else {
          setStatus("Unrecognized file -- use an .ics calendar, .vcf contacts, .csv from this app's own export, or a data.json backup.", true);
          if (submitBtn) submitBtn.disabled = true;
        }
      });
    }

    if (fileInput) {
      fileInput.addEventListener("change", function () {
        preview(fileInput.files && fileInput.files[0]);
      });

      // Drag-and-drop onto the label; the input itself stays the real field
      // so the dropped file submits exactly like a picked one.
      if (zone) {
        ["dragenter", "dragover"].forEach(function (evt) {
          zone.addEventListener(evt, function (e) {
            e.preventDefault();
            zone.classList.add("is-dragover");
          });
        });
        ["dragleave", "drop"].forEach(function (evt) {
          zone.addEventListener(evt, function (e) {
            e.preventDefault();
            zone.classList.remove("is-dragover");
          });
        });
        zone.addEventListener("drop", function (e) {
          var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
          if (!file) return;
          try {
            var dt = new DataTransfer();
            dt.items.add(file);
            fileInput.files = dt.files;
          } catch (err) {
            return; // ancient browser without DataTransfer: picker still works
          }
          preview(file);
        });
      }
    }
  }

  // ---- Reset-database dialog: the DELETE ALL gate -------------------------
  //
  // purge_modal.html is injected into the modal overlay after this script
  // has long since run, so the gate is delegated at the document level
  // instead of bound to elements queried at load. The submit button renders
  // disabled straight from the server; typing the exact phrase arms it (and
  // typing anything else disarms it again). That typed phrase IS the check
  // -- there is no second confirm popover on top of it.

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
