// New-contact form: the photo lives in the upload modal, which replaces the
// form. Clicking the avatar first saves what has been typed so far to the
// buffer contact, so coming back to the form shows it all again.
(function () {
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-draft-photo]");
    if (!btn) return;
    e.preventDefault();
    const uid = btn.getAttribute("data-draft-photo");
    const form = btn.closest("form");
    if (!form) return;
    const data = new FormData(form);
    if (!data.get("full_name")) data.set("full_name", "");
    data.delete("draft_uid");
    await fetch("/contacts/" + uid, {
      method: "POST",
      headers: { "X-Requested-With": "fetch" },
      body: data,
    });
    if (!window.CCModal) return;
    window.CCModal.setUrl("/contacts/" + uid + "/edit");
    window.CCModal.open("/contacts/" + uid + "/photo/modal");
  });
})();
