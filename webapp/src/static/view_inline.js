// In-place editing of the rows of a view modal (templates/_view_rows.html). Clicking a value swaps in its editor, which is a
// normal app component rendered into a <template>; the change is saved at once to the row's update-field URL and the
// value is repainted. Escape cancels; a failed save reports a toast and restores the old value.
(function () {
  function fail(message) {
    if (window.ccToast) window.ccToast({ message: message || "Could not save that change", variant: "error" });
  }

  async function save(host, value) {
    const resp = await fetch(host.dataset.viUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field: host.dataset.viField, value }),
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.error || "Could not save that change");
    }
  }

  function close(host) {
    const box = host.querySelector(".vi-edit");
    if (box) box.remove();
    const shown = host.querySelector(".vi-display");
    if (shown) shown.hidden = false;
    host.classList.remove("is-editing");
  }

  function paint(host, field, text, color) {
    const shown = host.querySelector(".vi-display");
    if (!shown) return;
    const empty = host.dataset.viEmpty || "";
    if (field === "status") {
      shown.innerHTML = "";
      const pill = document.createElement("span");
      pill.className = "cell-tag tag-" + color;
      pill.textContent = text;
      shown.appendChild(pill);
    } else {
      shown.innerHTML = "";
      const span = document.createElement("span");
      span.className = text ? (field === "description" || field === "notes" ? "detail-text" : "vi-text") : "vi-empty";
      span.textContent = text || empty;
      shown.appendChild(span);
    }
  }

  // The editor is cloned from a <template> each time it opens, so a saved value is written back into the template too;
  // otherwise opening the editor again would start from the value the window had when it was first drawn.
  function syncTemplate(host, field, value, text) {
    const tpl = host.querySelector("template.vi-editor");
    if (!tpl) return;
    const root = tpl.content;
    const area = root.querySelector("textarea");
    if (area) area.textContent = value || "";
    const input = root.querySelector("input.vi-input");
    if (input) input.setAttribute("value", value || "");
    const hidden = root.querySelector(".dtf-value");
    if (hidden) hidden.setAttribute("value", value || "");
    const shown = root.querySelector(".dtf-input");
    if (shown) shown.setAttribute("value", value ? text : "");
    root.querySelectorAll("input.vi-status-radio, input.vi-choice-radio").forEach((r) => { if (r.value === value) r.setAttribute("checked", ""); else r.removeAttribute("checked"); });
    const trigger = root.querySelector(".multiselect-trigger .ms-summary");
    if (trigger && (field === "status" || root.querySelector(".vi-choice-radio"))) trigger.textContent = text;
  }

  // A row whose editor is a list of choices other than the status (a rating, say): it saves the picked label as plain text.
  function isChoice(host) {
    const tpl = host.querySelector("template.vi-editor");
    return !!(tpl && tpl.content.querySelector(".vi-choice-radio"));
  }

  function openEditor(host) {
    if (host.classList.contains("is-editing")) return;
    const tpl = host.querySelector("template.vi-editor");
    if (!tpl) return;
    const box = document.createElement("div");
    box.className = "vi-edit";
    box.appendChild(tpl.content.cloneNode(true));
    host.classList.add("is-editing");
    host.querySelector(".vi-display").hidden = true;
    host.insertBefore(box, tpl);
    const focusTarget = box.querySelector("textarea, input.vi-input, .dtf-input, .multiselect-trigger");
    if (focusTarget) {
      focusTarget.focus();
      if (focusTarget.setSelectionRange && /^(textarea|input)$/i.test(focusTarget.tagName)) { const end = focusTarget.value.length; focusTarget.setSelectionRange(end, end); }
    }
    if (host.dataset.viField === "status" || isChoice(host)) {
      const trigger = box.querySelector(".multiselect-trigger");
      if (trigger) trigger.click();
    }
  }

  document.addEventListener("click", (e) => {
    const host = e.target.closest && e.target.closest(".vi-editable");
    if (!host || e.target.closest(".vi-edit, a[href]")) return;
    openEditor(host);
  });

  document.addEventListener("keydown", (e) => {
    const host = e.target.closest && e.target.closest(".vi-editable");
    if (!host) return;
    if (e.key === "Escape" && host.classList.contains("is-editing")) {
      e.stopPropagation();
      close(host);
    } else if (e.key === "Enter" && e.target.matches && e.target.matches(".vi-edit input.vi-input")) {
      e.preventDefault();
      e.target.blur();
    } else if ((e.key === "Enter" || e.key === " ") && e.target === host) {
      e.preventDefault();
      openEditor(host);
    }
  }, true);

  document.addEventListener("change", async (e) => {
    const host = e.target.closest && e.target.closest(".vi-editable.is-editing");
    if (!host) return;
    const field = host.dataset.viField;
    if (field === "due_at" && e.target.classList.contains("dtf-value")) {
      const text = host.querySelector(".dtf-input").value;
      try { await save(host, e.target.value || null); paint(host, field, e.target.value ? text : "", ""); syncTemplate(host, field, e.target.value || "", text); } catch (err) { fail(err.message); }
      close(host);
    } else if (e.target.classList.contains("vi-choice-radio")) {
      const label = e.target.closest("label").textContent.trim();
      try { await save(host, e.target.value); paint(host, field, e.target.value ? label : "", ""); syncTemplate(host, field, e.target.value, label); } catch (err) { fail(err.message); }
      close(host);
    } else if (field === "status" && e.target.classList.contains("vi-status-radio")) {
      const label = e.target.closest("label").textContent.trim();
      try { await save(host, e.target.value); paint(host, field, label, e.target.dataset.color || "gray"); syncTemplate(host, field, e.target.value, label); } catch (err) { fail(err.message); }
      close(host);
    }
  });

  // A date or status editor has nothing to save on blur (it saves when a value is chosen), so it closes when the pointer or
  // the focus goes elsewhere. Text editors save and close on blur instead.
  const keepOpenFor = ".dtf-panel, .multiselect-panel, .ms-panel";
  function closeChoiceEditors(except) {
    document.querySelectorAll(".vi-editable.is-editing").forEach((host) => {
      const f = host.dataset.viField;
      if (host !== except && (f === "due_at" || f === "status" || isChoice(host))) close(host);
    });
  }
  document.addEventListener("mousedown", (e) => {
    if (e.target.closest && e.target.closest(keepOpenFor)) return;
    closeChoiceEditors(e.target.closest ? e.target.closest(".vi-editable.is-editing") : null);
  }, true);
  document.addEventListener("focusout", (e) => {
    const host = e.target.closest && e.target.closest(".vi-editable.is-editing");
    if (!host || !(host.dataset.viField === "due_at" || host.dataset.viField === "status" || isChoice(host))) return;
    setTimeout(() => {
      const active = document.activeElement;
      if (host.isConnected && !host.contains(active) && !(active && active.closest && active.closest(keepOpenFor))) close(host);
    }, 150);
  });

  document.addEventListener("focusout", async (e) => {
    const area = e.target.matches && e.target.matches(".vi-edit textarea, .vi-edit input.vi-input") ? e.target : null;
    if (!area) return;
    const host = area.closest(".vi-editable");
    if (!host || !host.classList.contains("is-editing")) return;
    const field = host.dataset.viField;
    const value = area.value.trim();
    try { await save(host, value); paint(host, field, value, ""); syncTemplate(host, field, value, value); } catch (err) { fail(err.message); }
    close(host);
  });
})();
