(function () {
  const toggle = document.getElementById("mobile-nav-toggle");
  const drawer = document.getElementById("mobile-nav-drawer");
  const scrim = document.getElementById("mobile-nav-scrim");
  const handle = document.getElementById("mobile-nav-handle");
  if (!toggle || !drawer || !scrim) return;

  function isOpen() {
    return document.documentElement.hasAttribute("data-mobile-nav-open");
  }

  function open() {
    document.documentElement.setAttribute("data-mobile-nav-open", "1");
    toggle.setAttribute("aria-expanded", "true");
  }

  function close() {
    document.documentElement.removeAttribute("data-mobile-nav-open");
    toggle.setAttribute("aria-expanded", "false");
  }

  toggle.addEventListener("click", () => {
    if (isOpen()) close();
    else open();
  });
  scrim.addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isOpen()) close();
  });

  // A real destination link inside the drawer (Home/Calendar/.../a Space
  // or Project row) navigates the page away, which makes closing moot in
  // most cases -- except `data-command-palette-open`/`data-modal`
  // triggers (Search; "+ New" is hidden on mobile, see style.css), which
  // open an overlay in place instead of a full page load. The one drawer
  // control that must NOT close on click is `.sidebar-tree-toggle` (a
  // Space's chevron, expands/collapses its children in place) -- it's a
  // `<button>`, not an `a.tab-btn`, so the `a.tab-btn` selector below
  // already excludes it without a separate check.
  drawer.addEventListener("click", (e) => {
    if (e.target.closest("a.tab-btn")) close();
  });

  // Drag-down-to-dismiss, same Pointer Events pattern as static/modal.js's
  // `#modal-handle` (see that file's own comment for why Pointer Events
  // specifically -- one listener covers mouse, touch, and pen instead of
  // wiring each separately).
  if (handle) {
    let dragging = false;
    let startY = 0;
    let currentY = 0;

    handle.addEventListener("pointerdown", (e) => {
      dragging = true;
      startY = e.clientY;
      currentY = 0;
      drawer.style.transition = "none";
      handle.setPointerCapture(e.pointerId);
    });
    handle.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      currentY = Math.max(0, e.clientY - startY);
      drawer.style.transform = `translateY(${currentY}px)`;
    });
    function endDrag() {
      if (!dragging) return;
      dragging = false;
      drawer.style.transition = "";
      drawer.style.transform = "";
      // Past ~90px of drag, treat it as an intentional dismiss rather
      // than a small accidental nudge -- matches #modal-handle's own
      // threshold and the native iOS/Material "flick past a point" feel.
      if (currentY > 90) close();
    }
    handle.addEventListener("pointerup", endDrag);
    handle.addEventListener("pointercancel", endDrag);
  }
})();
