// 1.8 slice 3 -- registers the PWA shell service worker (static/sw.js,
// served at the root path by routers/pwa.py so its scope covers the
// whole app). Loaded globally in base.html, same as this app's other
// self-initializing scripts. Guarded by the feature check because this
// still needs to run cleanly in browsers without serviceWorker support
// (or a plain http:// dev context, where registration is refused) --
// every other page feature here is unaffected either way.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Registration failure (unsupported context, blocked by browser
      // settings, etc.) is silent by design -- the app is fully
      // functional online without a service worker at all; this is a
      // progressive enhancement, not a requirement.
    });
  });
}
