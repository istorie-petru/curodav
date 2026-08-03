// Progressive enhancement for `<input class="tag-input" list="...">`
// (task_form.html/event_form.html/contact_form.html's Tags field) into a
// recommend-as-you-type autocomplete over the current comma-separated
// *fragment* being typed -- a plain native <datalist> popup replaces the
// entire input value on selection, which breaks "tag1, tag2, |typing
// tag3" the instant you pick a suggestion (it would wipe tag1/tag2). This
// keeps the underlying <input>'s name/value exactly the same shape
// (comma-separated text) the routers already parse via `_tags_list()`, so
// nothing server-side needed to change, and the field still works with no
// JS at all -- it's just a plain text input with a native datalist popup
// in that case, not broken.
//
// A global script (loaded once in base.html), not a per-page one: form
// pages loaded through modal.js arrive via `body.innerHTML = ...`, which
// never executes any `<script>` tag inside that HTML -- only a
// MutationObserver watching for newly-inserted `.tag-input` elements
// reliably catches those, whether the form was fetched into the modal or
// rendered as an ordinary full page.
(function () {
  const enhanced = new WeakSet();

  function enhance(input) {
    if (enhanced.has(input)) return;
    enhanced.add(input);
    const listId = input.getAttribute("list");
    const datalist = listId && document.getElementById(listId);
    if (!datalist) return;
    const names = Array.from(datalist.options).map((o) => o.value);
    input.setAttribute("autocomplete", "off");

    const wrap = document.createElement("div");
    wrap.className = "tag-input-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const menu = document.createElement("div");
    menu.className = "tag-input-menu";
    wrap.appendChild(menu);

    function currentFragment() {
      const parts = input.value.split(",");
      return parts[parts.length - 1].trim();
    }

    function alreadyTagged() {
      return input.value
        .split(",")
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean);
    }

    function closeMenu() {
      menu.innerHTML = "";
      menu.classList.remove("is-open");
    }

    function pick(name) {
      const parts = input.value.split(",");
      parts[parts.length - 1] = " " + name;
      input.value = parts.map((p) => p.trim()).filter(Boolean).join(", ") + ", ";
      closeMenu();
      input.focus();
    }

    function openMenu() {
      const frag = currentFragment().toLowerCase();
      if (!frag) {
        closeMenu();
        return;
      }
      const already = alreadyTagged();
      const matches = names.filter(
        (n) => n.toLowerCase().includes(frag) && !already.includes(n.toLowerCase())
      );
      if (!matches.length) {
        closeMenu();
        return;
      }
      menu.innerHTML = "";
      matches.slice(0, 8).forEach((n) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "tag-input-option";
        item.textContent = n;
        // mousedown (not click) fires before the input's blur handler
        // closes the menu, so the option is still there to be clicked.
        item.addEventListener("mousedown", (e) => {
          e.preventDefault();
          pick(n);
        });
        menu.appendChild(item);
      });
      menu.classList.add("is-open");
    }

    input.addEventListener("input", openMenu);
    input.addEventListener("focus", openMenu);
    input.addEventListener("blur", () => setTimeout(closeMenu, 120));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeMenu();
    });
  }

  function scan(root) {
    (root.querySelectorAll ? root.querySelectorAll("input.tag-input") : []).forEach(enhance);
    if (root.matches && root.matches("input.tag-input")) enhance(root);
  }

  document.addEventListener("DOMContentLoaded", () => scan(document));

  new MutationObserver((mutations) => {
    for (const m of mutations) {
      m.addedNodes.forEach((node) => {
        if (node.nodeType === 1) scan(node);
      });
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
