(function () {
  "use strict";

  function closest(el, selector) {
    return el && el.closest ? el.closest(selector) : null;
  }

  // ---- Export dialog: live "Includes: N Events, N Tasks, N Contacts" ----
  //
  // Each type radio carries its own server-rendered phrase in
  // data-dm-preview; this composes it with the format's packaging note, so
  // the wording lives in one place (the template).

  // A dropdown's panel is portaled out of its wrapper while open, so its
  // inputs are reached through CCMultiselect.panelFor, not querySelector.
  function dropdownInputs(root) {
    var panel = root && window.CCMultiselect.panelFor(root);
    return panel ? Array.from(panel.querySelectorAll("input")) : [];
  }

  function refreshExportHint(scope) {
    var typeRoot = scope.querySelector(".dm-type-select");
    var formatRoot = scope.querySelector(".dm-format-select");
    var typeInput = dropdownInputs(typeRoot).find(function (i) { return i.checked; });
    var formatInput = dropdownInputs(formatRoot).find(function (i) { return i.checked; });
    var hint = scope.querySelector("[data-dm-hint]");
    if (!typeInput || !hint) return;
    var type = typeInput.value;
    var csv = !!formatInput && formatInput.value === "csv";
    var parts = [typeInput.dataset.dmPreview || ""];
    var fixed = { labels: ".json", notes: "a .zip of .md files", finance: "a .zip of .csv files", citations: ".csv", glossary: ".csv" };
    if (fixed[type]) {
      parts.push("always exports as " + fixed[type] + ".");
    } else if (type === "all") {
      parts.push(csv ? "one .zip of spreadsheets." : "one .zip bundle (.ics/.vcf).");
    } else {
      parts.push(csv ? "opens in any spreadsheet app." : "opens in any calendar or contacts app.");
    }
    hint.textContent = parts.filter(Boolean).join(" \u00b7 ");
    if (formatRoot) {
      var labelsPicked = !!fixed[type];
      dropdownInputs(formatRoot).concat(Array.from(formatRoot.querySelectorAll(".ms-trigger"))).forEach(function (el) { el.disabled = labelsPicked; });
      formatRoot.title = labelsPicked ? "This data always exports as " + fixed[type] : "";
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
      tasks: ["uid", "title", "status", "due", "tags"],
      events: ["uid", "title", "start", "end", "all day", "location", "meeting url", "tags"],
      contacts: ["uid", "name", "organization", "phone", "email", "address", "tags"],
      "finance accounts": ["name", "type", "currency", "opening_balance", "opening_date"],
      "finance transactions": ["date", "description", "account", "type", "amount", "label", "tags", "to_account"],
      citations: ["uid", "type", "title", "authors", "year", "container title", "doi", "url"],
      glossary: ["uid", "term", "definition"]
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
    var submitBtn = document.getElementById("import-submit-btn");
    var file = input.files && input.files[0];
    if (!file) {
      setStatus(form, "", false);
      if (submitBtn) submitBtn.disabled = false;
      return;
    }
    var lower = file.name.toLowerCase();
    if (/\.(md|markdown)$/.test(lower) || /\.zip$/.test(lower)) {
      setStatus(form, "Detected: " + (/\.zip$/.test(lower) ? "a zip bundle (notes, spreadsheets and calendars inside)" : "a Markdown note") + ". Ready to import.", false);
      if (submitBtn) submitBtn.disabled = false;
      return;
    }
    file.text().then(function (text) {
      var found = detect(text);
      if (found) {
        setStatus(form, "Detected: " + found.detail + " (" + found.kind.toUpperCase() + "). Ready to import.", false);
        if (submitBtn) submitBtn.disabled = false;
      } else {
        setStatus(form, "Unrecognized file -- use an .ics, .vcf, .csv from this app's own export, .md, .zip or a data.json backup.", true);
        if (submitBtn) submitBtn.disabled = true;
      }
    });
  }

  // ---- Delegated bindings (dialogs inject after load) ---------------------

  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t.matches) return;
    var exportRoot = document.querySelector("[data-dm-export-root]");
    if (exportRoot && t.matches("input") && closest(t, ".multiselect-panel")) {
      refreshExportHint(exportRoot);
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

  document.addEventListener("click", function (e) {
    var btn = closest(e.target, '[data-action="purge-all"]');
    if (!btn) return;
    window.ccConfirmSheet({
      anchor: btn,
      message: "Deletes every task, event, contact, shelf, habit, and published list. Backups are kept.",
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

})();
