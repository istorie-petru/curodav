/* The Accounts vault in the page (features/accounts-vault.md): Copy and Reveal fetch one value at a time, a copied value is
   cleared from the clipboard after 30 seconds, a revealed one hides again after 20, one-time codes count down, and the page
   clears itself as soon as the server says the vault has locked. Delegated at the document, so windows need no set-up. */
(function () {
  var CLEAR_AFTER = 30000, HIDE_AFTER = 20000;
  var toast = function (message, variant) { if (window.ccToast) window.ccToast({ message: message, variant: variant }); };

  function fetchSecret(uuid, field, action) {
    var body = new FormData();
    body.append("field", field);
    body.append("action", action);
    return fetch("/accounts/entry/" + encodeURIComponent(uuid) + "/secret", { method: "POST", body: body, headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        if (r.status === 423) { location.reload(); throw new Error("locked"); }
        if (!r.ok) throw new Error("failed");
        return r.json();
      }).then(function (d) { return d.value; });
  }

  function copyText(value, what) {
    if (!navigator.clipboard) { toast("This browser cannot copy here", "error"); return; }
    navigator.clipboard.writeText(value).then(function () {
      toast(what + " copied; the clipboard clears in 30 seconds");
      setTimeout(function () { navigator.clipboard.writeText("").catch(function () {}); }, CLEAR_AFTER);
    }, function () { toast("Could not copy", "error"); });
  }

  document.addEventListener("click", function (e) {
    var copy = e.target.closest("[data-acc-copy]");
    if (copy) {
      e.preventDefault();
      var field = copy.getAttribute("data-field");
      fetchSecret(copy.getAttribute("data-uuid"), field, "copy").then(function (v) {
        copyText(v, field === "Password" ? "Password" : field === "UserName" ? "User name" : field);
      }).catch(function (err) { if (err.message !== "locked") toast("Could not copy", "error"); });
      return;
    }
    var reveal = e.target.closest("[data-acc-reveal]");
    if (reveal) {
      e.preventDefault();
      var uuid = reveal.getAttribute("data-uuid"), name = reveal.getAttribute("data-field");
      var target = document.querySelector('[data-acc-secret][data-uuid="' + uuid + '"][data-field="' + CSS.escape(name) + '"]');
      if (!target) return;
      if (target.classList.contains("is-revealed")) { target.textContent = "••••••••"; target.classList.remove("is-revealed"); return; }
      fetchSecret(uuid, name, "reveal").then(function (v) {
        target.textContent = v;
        target.classList.add("is-revealed");
        setTimeout(function () { target.textContent = "••••••••"; target.classList.remove("is-revealed"); }, HIDE_AFTER);
      }).catch(function () {});
      return;
    }
    var otpCopy = e.target.closest("[data-acc-copy-otp]");
    if (otpCopy) {
      e.preventDefault();
      var code = document.querySelector('[data-acc-otp][data-uuid="' + otpCopy.getAttribute("data-uuid") + '"]');
      if (code && /^\d+$/.test(code.textContent)) copyText(code.textContent, "Code");
      return;
    }
    var gen = e.target.closest("[data-acc-generate]");
    if (gen) {
      e.preventDefault();
      var target = document.getElementById(gen.getAttribute("data-acc-generate") || "");
      fetch("/accounts/generate", { headers: { "X-Requested-With": "fetch" } }).then(function (r) { return r.json(); }).then(function (d) {
        var row = target || gen.closest("[data-row]");
        var input = row.querySelector('[name^="field_value_"]');
        input.value = d.value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
      return;
    }
  });

  // Settings, New passwords: the example follows the fields as they stand. The dropdown panels are moved out of the form
  // while open, so inputs are read through the form they belong to.
  function ruleForm(el) {
    var form = el && (el.form || (el.closest && el.closest("form")));
    return form && form.hasAttribute("data-acc-generator") ? form : null;
  }
  function regenerate(form) {
    if (!form) return;
    var data = new FormData(form);
    var mode = data.get("mode") || "random";
    form.querySelectorAll("[data-acc-mode]").forEach(function (el) { el.hidden = el.getAttribute("data-acc-mode") !== mode; });
    var q = new URLSearchParams();
    data.forEach(function (v, k) { if (k !== "sample") q.append(k, v); });
    fetch("/accounts/generate?" + q.toString(), { headers: { "X-Requested-With": "fetch" } }).then(function (r) { return r.json(); }).then(function (d) {
      var out = form.querySelector("[data-acc-generated]");
      if (out) out.value = d.value;
      var fill = form.querySelector("[data-acc-meter-fill]");
      if (fill) fill.style.width = Math.min(100, d.bits / 1.28) + "%";
      var text = form.querySelector("[data-acc-meter-text]");
      if (text) text.textContent = d.rating + " · " + d.bits + " bits";
    });
  }
  var typing = null;
  document.addEventListener("change", function (e) { regenerate(ruleForm(e.target)); });
  document.addEventListener("input", function (e) {
    var form = ruleForm(e.target);
    if (!form || e.target.name === "sample") return;
    clearTimeout(typing);
    typing = setTimeout(function () { regenerate(form); }, 300);
  });
  document.addEventListener("click", function (e) {
    var again = e.target.closest("[data-acc-regenerate]");
    if (again) { e.preventDefault(); regenerate(ruleForm(again)); }
  });

  // The entry form. Every field is one labelled value; its menu hides it (stored protected, shown masked) or shows it, and
  // removes it. Picking another type lays out that type's fields at once, keeping every value already typed.
  function setIcon(button, name) {
    var use = button.querySelector("use");
    if (use) { use.setAttribute("href", "#icon-" + name); use.setAttribute("xlink:href", "#icon-" + name); }
  }
  function setHidden(row, hidden) {
    row.querySelector("[data-acc-hidden]").value = hidden ? "1" : "0";
    var value = row.querySelector('[name^="field_value_"]');
    if (value) value.classList.toggle("accounts-masked", hidden);
    var eye = document.querySelector('[data-acc-eye="' + row.id + '"]');
    if (eye) {
      setIcon(eye, hidden ? "eye-off" : "eye");
      var label = eye.querySelector("span");
      if (label) label.textContent = hidden ? "Show" : "Hide";
    }
  }
  function addField(name, value, hidden, kind) {
    var host = document.getElementById("accounts-field-rows");
    var tpl = document.getElementById(kind === "long text" ? "accounts-field-template-long" : "accounts-field-template");
    if (!host || !tpl) return null;
    var holder = document.createElement("template");
    holder.innerHTML = tpl.innerHTML.replace(/__IDX__/g, "n" + Date.now().toString(36) + host.children.length);
    var row = holder.content.firstElementChild;
    row.querySelector('[name^="field_key_"]').value = name;
    row.querySelector("label").textContent = name;
    row.setAttribute("data-kind", kind || "text");
    var input = row.querySelector('[name^="field_value_"]');
    input.value = value || "";
    input.setAttribute("aria-label", name);
    row.querySelectorAll("[aria-label]").forEach(function (el) { el.setAttribute("aria-label", el.getAttribute("aria-label").replace("__NAME__", name)); });
    if (name !== "Password") row.querySelectorAll("[data-acc-generate]").forEach(function (el) { el.remove(); });
    host.appendChild(row);
    if (window.CCActionMenu) window.CCActionMenu.init();
    setHidden(row, hidden);
    return row;
  }
  function currentFields() {
    var host = document.getElementById("accounts-field-rows");
    return Array.prototype.map.call(host ? host.querySelectorAll("[data-row]") : [], function (row) {
      return { name: row.querySelector('[name^="field_key_"]').value, value: row.querySelector('[name^="field_value_"]').value,
               hidden: row.querySelector("[data-acc-hidden]").value === "1" };
    });
  }
  document.addEventListener("change", function (e) {
    var picked = e.target;
    if (picked.name !== "type" || !picked.checked || !picked.form || picked.form.id !== "accounts-entry-form") return;
    var fields = JSON.parse(picked.form.getAttribute("data-acc-kinds") || "{}")[picked.value];
    if (!fields) return;
    var had = {};
    currentFields().forEach(function (f) { had[f.name] = f; });
    document.getElementById("accounts-field-rows").innerHTML = "";
    fields.forEach(function (pair) {
      var name = pair[0], kind = pair[1], old = had[name];
      delete had[name];
      addField(name, old ? old.value : "", old ? old.hidden : (kind === "secret" || kind === "code"), kind);
    });
    Object.keys(had).forEach(function (name) { if (had[name].value) addField(name, had[name].value, had[name].hidden, "text"); });
  });
  document.addEventListener("click", function (e) {
    var eye = e.target.closest("[data-acc-eye]");
    if (eye) {
      e.preventDefault();
      var row = document.getElementById(eye.getAttribute("data-acc-eye"));
      if (row) setHidden(row, row.querySelector("[data-acc-hidden]").value !== "1");
      return;
    }
    var remove = e.target.closest("[data-acc-remove]");
    if (remove) {
      e.preventDefault();
      var gone = document.getElementById(remove.getAttribute("data-acc-remove"));
      if (gone) gone.remove();
      return;
    }
    var add = e.target.closest("[data-acc-add-field]");
    if (add) {
      e.preventDefault();
      var input = document.querySelector("[data-acc-new-field]");
      var name = (input && input.value || "").trim();
      if (!name) return;
      if (currentFields().some(function (f) { return f.name.toLowerCase() === name.toLowerCase(); })) { toast("There is already a field called " + name, "error"); return; }
      var row = addField(name, "", false, "text");
      input.value = "";
      if (row) row.querySelector('[name^="field_value_"]').focus();
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target.matches && e.target.matches("[data-acc-new-field]")) {
      e.preventDefault();
      var button = document.querySelector("[data-acc-add-field]");
      if (button) button.click();
    }
  });

  // Settings, entry types: the KeePass fields menu adds User name, Password and the others with their own name and kind,
  // once each.
  document.addEventListener("click", function (e) {
    var pick = e.target.closest("[data-acc-standard]");
    if (!pick) return;
    e.preventDefault();
    var name = pick.getAttribute("data-acc-standard");
    var host = document.getElementById("accounts-kind-rows");
    var tpl = document.getElementById("accounts-standard-template");
    if (!host || !tpl) return;
    if (host.querySelector('[data-standard="' + CSS.escape(name) + '"]')) { toast(name + " is already in this type", "error"); return; }
    var holder = document.createElement("template");
    holder.innerHTML = tpl.innerHTML.replace(/__IDX__/g, "s" + Date.now().toString(36)).replace(/__NAME__/g, name);
    var row = holder.content.firstElementChild;
    row.querySelector('[name^="field_kind_"]').value = pick.getAttribute("data-standard-kind-value");
    host.appendChild(row);
  });

  // After a password was changed in the edit window the page opens with ?undo_password=<entry>: offer to put the old one back.
  (function offerUndo() {
    var params = new URLSearchParams(location.search);
    var uuid = params.get("undo_password");
    if (!uuid) return;
    params.delete("undo_password");
    history.replaceState(null, "", location.pathname + (params.toString() ? "?" + params.toString() : ""));
    var show = function () {
      if (!window.ccToast) return setTimeout(show, 100);
      window.ccToast({
        message: "Password changed", duration: 12000, actionLabel: "Undo",
        onAction: function () {
          fetch("/accounts/entry/" + encodeURIComponent(uuid) + "/undo-field", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ field: "Password" }),
          }).then(function (r) { toast(r.ok ? "Password put back" : "Could not put it back", r.ok ? undefined : "error"); });
        },
      });
    };
    show();
  })();

  // Several entries at once: checkboxes on the rows (shift-click selects a range), a bar with Change and Bin or Restore and Delete,
  // and rows that can be dragged onto a space in the sidebar to move them (the whole selection moves when the dragged row is in it).
  var picked = new Set();
  function rowBoxes() { return Array.prototype.slice.call(document.querySelectorAll(".accounts-row .row-select")); }
  function syncBulk() {
    var bar = document.getElementById("accounts-bulk-bar");
    if (!bar) return;
    var all = document.querySelector("[data-acc-select-all]");
    var boxes = rowBoxes();
    boxes.forEach(function (b) {
      b.checked = picked.has(b.getAttribute("data-uuid"));
      var row = b.closest(".accounts-row");
      if (row) row.classList.toggle("is-selected", b.checked);
    });
    if (all) { all.checked = boxes.length > 0 && picked.size === boxes.length; all.indeterminate = picked.size > 0 && picked.size < boxes.length; }
    bar.hidden = picked.size === 0;
    var count = document.getElementById("accounts-bulk-count");
    if (count) count.textContent = picked.size + " selected";
    var ids = Array.from(picked).join(",");
    var edit = document.getElementById("accounts-bulk-edit");
    if (edit) edit.setAttribute("href", "/accounts/bulk?uuids=" + encodeURIComponent(ids));
    document.querySelectorAll("[data-acc-bulk-form] input[name=uuids]").forEach(function (i) { i.value = ids; });
  }
  var lastBox = null;
  document.addEventListener("click", function (e) {
    var box = e.target.closest && e.target.closest(".accounts-row .row-select");
    if (box) {
      var boxes = rowBoxes(), i = boxes.indexOf(box);
      var on = box.checked;
      if (e.shiftKey && lastBox !== null && boxes[lastBox]) {
        var from = Math.min(lastBox, i), to = Math.max(lastBox, i);
        for (var k = from; k <= to; k++) { if (on) picked.add(boxes[k].getAttribute("data-uuid")); else picked.delete(boxes[k].getAttribute("data-uuid")); }
      } else if (on) picked.add(box.getAttribute("data-uuid")); else picked.delete(box.getAttribute("data-uuid"));
      lastBox = i;
      syncBulk();
      return;
    }
    if (e.target.closest && e.target.closest("[data-acc-select-all]")) {
      var every = e.target.closest("[data-acc-select-all]").checked;
      rowBoxes().forEach(function (b) { if (every) picked.add(b.getAttribute("data-uuid")); else picked.delete(b.getAttribute("data-uuid")); });
      syncBulk();
      return;
    }
    if (e.target.closest && e.target.closest("#accounts-bulk-clear")) { picked.clear(); syncBulk(); }
  });
  document.addEventListener("dragstart", function (e) {
    var row = e.target.closest && e.target.closest(".accounts-row");
    if (!row) return;
    var id = row.getAttribute("data-uuid");
    var ids = picked.has(id) ? Array.from(picked) : [id];
    e.dataTransfer.setData("text/plain", ids.join(","));
    e.dataTransfer.effectAllowed = "move";
  });
  document.addEventListener("dragover", function (e) {
    var target = e.target.closest && e.target.closest("[data-acc-drop]");
    if (!target) return;
    e.preventDefault();
    target.classList.add("is-drop");
  });
  document.addEventListener("dragleave", function (e) {
    var target = e.target.closest && e.target.closest("[data-acc-drop]");
    if (target) target.classList.remove("is-drop");
  });
  document.addEventListener("drop", function (e) {
    var target = e.target.closest && e.target.closest("[data-acc-drop]");
    if (!target) return;
    e.preventDefault();
    target.classList.remove("is-drop");
    var ids = e.dataTransfer.getData("text/plain");
    if (!ids) return;
    var body = new FormData();
    body.append("uuids", ids);
    body.append("space", target.getAttribute("data-acc-drop"));
    fetch("/accounts/bulk/edit", { method: "POST", body: body, headers: { "X-Requested-With": "fetch" } }).then(function (r) {
      if (r.ok) location.reload(); else toast("Could not move them", "error");
    });
  });
  syncBulk();

  // One-time codes: fetch the code, count down, fetch again when it rolls over.
  function tickOtp() {
    document.querySelectorAll("[data-acc-otp]").forEach(function (el) {
      var left = el.parentElement.querySelector("[data-acc-otp-left]");
      var remaining = parseInt(el.getAttribute("data-remaining") || "0", 10);
      if (remaining > 1 && el.getAttribute("data-busy") !== "1") {
        el.setAttribute("data-remaining", String(remaining - 1));
        if (left) left.textContent = (remaining - 1) + "s";
        return;
      }
      if (el.getAttribute("data-busy") === "1") return;
      el.setAttribute("data-busy", "1");
      fetch("/accounts/entry/" + encodeURIComponent(el.getAttribute("data-uuid")) + "/otp", { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { if (r.status === 423) location.reload(); return r.json(); })
        .then(function (d) {
          el.textContent = d.code;
          el.setAttribute("data-remaining", String(d.remaining));
          if (left) left.textContent = d.remaining + "s";
        }).catch(function () {}).finally(function () { el.removeAttribute("data-busy"); });
    });
  }
  setInterval(tickOtp, 1000);

  // The page clears itself once the vault locks (idle time, another tab, logout).
  function checkLock() {
    if (!document.querySelector("[data-accounts-unlocked]")) return;
    fetch("/accounts/status", { headers: { "X-Requested-With": "fetch" } }).then(function (r) { return r.json(); })
      .then(function (d) { if (!d.unlocked) location.replace("/accounts"); }).catch(function () {});
  }
  setInterval(checkLock, 30000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) checkLock(); });
})();
