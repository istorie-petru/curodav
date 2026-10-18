/* Touch long-press to start a drag. A finger that moves before the hold
   elapses is a scroll and is left alone; once armed, touchmove is cancelled
   so the finger drags the item instead of the page. Mouse and pen are not
   handled here. Used by the month grid. */
(function () {
  const HOLD_MS = 250;
  const SLOP_PX = 8;

  function bind(el, begin) {
    let timer = null;
    let armed = false;
    let x = 0;
    let y = 0;
    let pointerId = 0;

    function stopWatching() {
      clearTimeout(timer);
      timer = null;
      document.removeEventListener("pointermove", watch);
      document.removeEventListener("pointerup", release);
      document.removeEventListener("pointercancel", release);
    }
    function release() {
      stopWatching();
      armed = false;
    }
    function watch(e) {
      if (Math.abs(e.clientX - x) > SLOP_PX || Math.abs(e.clientY - y) > SLOP_PX) stopWatching();
    }

    el.addEventListener("touchmove", (e) => {
      if (armed && e.cancelable) e.preventDefault();
    }, { passive: false });
    el.addEventListener("contextmenu", (e) => { if (armed || timer) e.preventDefault(); });
    el.addEventListener("pointerup", () => { armed = false; });
    el.addEventListener("pointercancel", () => { armed = false; });

    el.addEventListener("pointerdown", (e) => {
      if (e.pointerType !== "touch" || e.button !== 0) return;
      x = e.clientX;
      y = e.clientY;
      pointerId = e.pointerId;
      document.addEventListener("pointermove", watch);
      document.addEventListener("pointerup", release);
      document.addEventListener("pointercancel", release);
      timer = setTimeout(() => {
        stopWatching();
        armed = true;
        if (navigator.vibrate) navigator.vibrate(10);
        begin({ clientX: x, clientY: y, pointerId });
      }, HOLD_MS);
    });
  }

  window.CCTouchHold = { bind };
})();
