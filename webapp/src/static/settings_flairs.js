(function () {
  "use strict";

  function closest(el, selector) {
    return el && el.closest ? el.closest(selector) : null;
  }

  // ---- Live status + enabling Submit ---------------------------------
  //
  // Any of the form's four file inputs getting a value (drag-drop onto
  // the two hidden dropzone inputs, or either visible picker button)
  // runs through here -- one shared summary line and one shared
  // "something is staged" check, so it doesn't matter which input the
  // user actually used.
  function form() {
    return document.getElementById("flairs-upload-form");
  }

  function describeFiles(fileList) {
    if (!fileList || !fileList.length) return "";
    if (fileList.length === 1) return fileList[0].name;
    return fileList.length + " files selected";
  }

  function refreshStatus() {
    var f = form();
    if (!f) return;
    var inputs = f.querySelectorAll("input[type=file]");
    var descriptions = [];
    var anyStaged = false;
    inputs.forEach(function (input) {
      if (input.files && input.files.length) {
        anyStaged = true;
        descriptions.push(describeFiles(input.files));
      }
    });
    var status = f.querySelector("[data-dm-status]");
    if (status) status.textContent = descriptions.join(" + ");
    var submit = document.getElementById("flairs-upload-submit-btn");
    if (submit) submit.disabled = !anyStaged;
  }

  document.addEventListener("change", function (e) {
    if (e.target && e.target.matches && e.target.matches('#flairs-upload-form input[type=file]')) {
      refreshStatus();
    }
  });

  // ---- Drag-and-drop onto the dropzone --------------------------------
  //
  // A dropped .zip (exactly one file, name ends in .zip) goes to the
  // dropzone's own hidden zip input; anything else dropped (one or more
  // image files) goes to the dropzone's own hidden multi-photo input.
  // Dropping a FOLDER isn't handled here -- that needs recursive
  // DataTransferItem.webkitGetAsEntry() traversal, which this first
  // version doesn't attempt (see settings_flairs.html's own comment on
  // the "Choose a folder..." picker button, which covers that case by
  // selection instead of drop).
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
    var f = form();
    var dropped = e.dataTransfer && e.dataTransfer.files;
    if (!f || !dropped || !dropped.length) return;
    var isSingleZip = dropped.length === 1 && /\.zip$/i.test(dropped[0].name);
    var target = f.querySelector(isSingleZip ? '[data-dm-file="drop-zip"]' : '[data-dm-file="drop-multi"]');
    if (!target) return;
    var dt = new DataTransfer();
    if (isSingleZip) {
      dt.items.add(dropped[0]);
    } else {
      for (var i = 0; i < dropped.length; i++) {
        // A zip mixed in among dropped photos still just lands in the
        // multi-photo field under this simple rule (only an
        // exactly-one-file-and-it's-a-zip drop is treated as "the
        // zip") -- it'll be skipped server-side as an unsupported
        // extension rather than silently ignored, same as any other
        // non-matching file would be.
        dt.items.add(dropped[i]);
      }
    }
    target.files = dt.files;
    refreshStatus();
  });
})();
