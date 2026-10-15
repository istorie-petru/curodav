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
