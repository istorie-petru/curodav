// Repeatable rows in a window: a host element (data-rows-host, data-rows-template="<id of a <template>>") holds rows (data-row); the plus
// button (data-rows-add="<host id>") adds one from the template and the minus button (data-rows-remove) drops its row. Pasting several lines
// into a field marked data-rows-split makes one row per line. Delegated at the document, so content injected into a window needs no set-up.
(function () {
  let counter = 0;

  // A row comes from a <template>; "__IDX__" in it becomes a number no other row has, for rows that own a list of rows (a component with its parts).
  function addRow(host, after, templateId) {
    const tpl = document.getElementById(templateId || host.getAttribute("data-rows-template"));
    if (!tpl) return null;
    counter += 1;
    const holder = document.createElement("template");
    holder.innerHTML = tpl.innerHTML.replace(/__IDX__/g, "n" + Date.now().toString(36) + counter);
    const row = holder.content.firstElementChild;
    if (!row) return null;
    if (after && after.nextSibling) host.insertBefore(row, after.nextSibling);
    else host.appendChild(row);
    if (window.CCActionMenu) window.CCActionMenu.init();
    return row;
  }

  document.addEventListener("click", function (e) {
    const add = e.target.closest("[data-rows-add]");
    if (add) {
      e.preventDefault();
      const host = document.getElementById(add.getAttribute("data-rows-add"));
      const row = host && addRow(host, null, add.getAttribute("data-rows-template"));
      const field = row && row.querySelector("input:not([type=hidden])");
      if (field) field.focus();
      return;
    }
    const child = e.target.closest("[data-rows-add-child]");
    if (child) {
      e.preventDefault();
      const block = child.closest("[data-row]");
      const host = child.parentElement.querySelector("[data-rows-host]");
      const made = host && addRow(host, null);
      const parent = block && block.querySelector("input[name=ev_key]");
      const link = made && made.querySelector("input[name=" + (child.getAttribute("data-rows-link") || "sub_parent") + "]");
      if (link && parent) link.value = parent.value;
      const field = made && made.querySelector("input:not([type=hidden])");
      if (field) field.focus();
      return;
    }
    const remove = e.target.closest("[data-rows-remove]");
    if (remove) {
      e.preventDefault();
      const row = remove.closest("[data-row]");
      if (row) row.remove();
    }
  });

  document.addEventListener("paste", function (e) {
    const input = e.target.closest && e.target.closest("input[data-rows-split]");
    if (!input) return;
    const text = (e.clipboardData || window.clipboardData).getData("text");
    const lines = text.split(/\r?\n/).map(function (s) { return s.trim(); }).filter(Boolean);
    if (lines.length < 2) return;
    e.preventDefault();
    const row = input.closest("[data-row]");
    const host = row && row.closest("[data-rows-host]");
    if (!host) return;
    input.value = lines[0];
    let after = row;
    lines.slice(1).forEach(function (line) {
      const made = addRow(host, after);
      const field = made && made.querySelector("input[data-rows-split]");
      if (field) field.value = line;
      after = made || after;
    });
  });

  // A drop-down inside a row (data-rows-pick items in an action menu): the chosen item goes into the row's hidden field and its label.
  // The open panel is moved out of the row by the menu code, so the row is remembered when its trigger is pressed.
  let lastPick = null;
  document.addEventListener("pointerdown", function (e) {
    const pick = e.target.closest && e.target.closest(".rows-pick");
    if (pick) lastPick = pick;
  }, true);
  document.addEventListener("click", function (e) {
    const item = e.target.closest && e.target.closest("[data-rows-pick]");
    if (!item || !lastPick) return;
    const field = lastPick.querySelector("input[type=hidden]");
    const label = lastPick.querySelector(".rows-pick-label");
    if (field) field.value = item.getAttribute("data-rows-pick");
    if (label) label.innerHTML = item.innerHTML;
  });
})();
