// Drag-and-drop for the shared upload zone (_upload_zone.html): a dropped file
// goes into the zone's own file input and fires `change`, so whatever is
// already listening (the crop editor) runs exactly as for a picked file.
(function () {
  function zoneOf(e) {
    return e.target.closest && e.target.closest("[data-upload-zone]");
  }
  document.addEventListener("dragover", function (e) {
    var zone = zoneOf(e);
    if (!zone) return;
    e.preventDefault();
    zone.classList.add("is-dragover");
  });
  document.addEventListener("dragleave", function (e) {
    var zone = zoneOf(e);
    if (zone && !zone.contains(e.relatedTarget)) zone.classList.remove("is-dragover");
  });
  document.addEventListener("drop", function (e) {
    var zone = zoneOf(e);
    if (!zone) return;
    e.preventDefault();
    zone.classList.remove("is-dragover");
    var input = zone.querySelector('input[type="file"]');
    var files = e.dataTransfer && e.dataTransfer.files;
    if (!input || !files || !files.length) return;
    input.files = files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  // Edit on a stored image: re-open the crop editor on it. Apply fills the
  // zone's input and the upload form submits itself (data-autosubmit).
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-upload-edit]");
    if (!btn || !window.CCAvatarCropper) return;
    e.preventDefault();
    var input = document.querySelector('input[type="file"][form="' + btn.getAttribute("data-upload-input") + '"]');
    if (!input) return;
    var kind = input.classList.contains("banner-upload-input") ? "banner" : "avatar";
    window.CCAvatarCropper.edit(btn.getAttribute("data-upload-edit"), input, kind);
  });
})();
