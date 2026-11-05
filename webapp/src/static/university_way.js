// A way of evaluating: choosing its type adds the first empty event and/or task row that type usually needs (data-form-items on the form), if there is none yet.
document.addEventListener("change", (e) => {
  const input = e.target;
  if (!input || input.name !== "form" || input.type !== "radio") return;
  const form = input.form || input.closest("form");
  if (!form || !form.hasAttribute("data-form-items")) return;
  let items = {};
  try { items = JSON.parse(form.getAttribute("data-form-items")); } catch (err) { return; }
  const want = items[input.value];
  if (!want) return;
  const add = (hostId) => {
    const host = form.querySelector("#" + hostId);
    const btn = form.querySelector('[data-rows-add="' + hostId + '"]');
    if (host && btn && !host.querySelector("[data-row]")) btn.click();
  };
  if (want === "event" || want === "both") add("university-event-rows");
  if (want === "task" || want === "both") add("university-task-rows");
});
