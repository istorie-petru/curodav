// The now page (media_now.html): the plus and minus buttons move progress in place; finishing an entry takes it off the in-progress row.
(function () {
  document.addEventListener("submit", async function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-media-step")) return;
    e.preventDefault();
    var card = form.closest(".media-card");
    try {
      var resp = await fetch(form.action, { method: "POST", headers: { "X-Requested-With": "fetch" }, body: new FormData(form) });
      if (!resp.ok) throw new Error(String(resp.status));
      var data = await resp.json();
      var count = card.querySelector("[data-media-count]");
      if (count) count.textContent = data.text;
      var bar = card.querySelector("[data-media-bar]");
      if (bar) bar.style.width = data.percent + "%";
      if (data.status === "finished") {
        window.ccToast({ message: '"' + card.querySelector(".media-card-title").textContent + '" is ' + data.status_label.toLowerCase() });
        card.remove();
      }
    } catch (err) {
      window.ccToast({ message: "Could not save the progress. Please try again.", variant: "error" });
    }
  });
})();
