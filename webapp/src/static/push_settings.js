// Settings > General's "Notifications on this device" card (Web Push,
// 2026-09-24, plans/ui-cleanup-2026-09.md item 7, slice P1). Subscribes
// this browser with the server's VAPID public key (/push/public-key),
// stores the subscription (/push/subscribe), and can send a test push.
// Per device: a phone and a laptop each turn it on separately.
(function () {
  const status = document.getElementById("push-status");
  if (!status) return;
  const enableBtn = document.getElementById("push-enable");
  const testBtn = document.getElementById("push-test");
  const disableBtn = document.getElementById("push-disable");

  const card = document.getElementById("push-settings");
  const prefsForm = document.getElementById("push-prefs-form");
  const inactiveHint = card && card.querySelector(".push-inactive-hint");

  function show(text, state) {
    status.textContent = text;
    enableBtn.hidden = state !== "off";
    testBtn.hidden = state !== "on";
    disableBtn.hidden = state !== "on";
    // 2026-09-25 (UI audit H-20): while this device gets nothing (off,
    // blocked, unsupported) the reminder rows dim and say where reminders
    // go -- they stay editable, since they're app-wide and another device
    // may have notifications on.
    if (card) card.classList.toggle("is-push-inactive", state !== "on");
    if (inactiveHint) inactiveHint.hidden = state === "on";
  }

  // UI audit H-20: a browser's own error text ("Registration failed -
  // push service error", "DOMException: ...") means nothing to a person;
  // say what to try instead.
  function plainError(err) {
    const name = (err && err.name) || "";
    if (name === "NotAllowedError") return "Notifications are blocked for this site. Allow them in the browser's site settings, then try again.";
    if (name === "AbortError" || name === "InvalidStateError")
      return "The browser's push service didn't answer. Check your connection and try again.";
    return "Something went wrong on this device. Try again in a moment.";
  }

  // UI audit H-19: one Save for types, time and contact email, saved in
  // place with a confirmation (no reload that jumped to the page top).
  if (prefsForm) {
    prefsForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = prefsForm.querySelector("button[type='submit']");
      if (btn) btn.disabled = true;
      try {
        const resp = await fetch(prefsForm.action, {
          method: "POST",
          headers: { "X-Requested-With": "fetch" },
          body: new FormData(prefsForm),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.error || "Couldn't save the notification settings. Try again.");
        window.ccToast && window.ccToast({ title: "Notification settings saved" });
      } catch (err) {
        window.ccToast && window.ccToast({ message: err.message, variant: "error" });
      } finally {
        if (btn) btn.disabled = false;
      }
    });
  }

  function keyBytes(b64url) {
    const pad = "=".repeat((4 - (b64url.length % 4)) % 4);
    const raw = atob((b64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }

  async function postJson(url, body) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
      body: JSON.stringify(body || {}),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "Request failed.");
    return data;
  }

  // pwa.js registers the worker on window "load", which can land after
  // this runs (or late, behind a slow external resource) -- register here
  // too (same script + scope: the browser returns the existing one), then
  // wait for it to be active.
  async function registration() {
    await navigator.serviceWorker.register("/sw.js");
    return navigator.serviceWorker.ready;
  }

  async function refresh() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      show("This browser doesn't support push notifications. On iPhone, add Curodav to the Home Screen first.", "none");
      return;
    }
    if (Notification.permission === "denied") {
      show("Blocked for this site. Allow notifications in the browser's site settings, then reload.", "none");
      return;
    }
    const reg = await registration();
    const sub = await reg.pushManager.getSubscription();
    if (sub) show("On. You'll get reminders here.", "on");
    else show("Off.", "off");
  }

  enableBtn.addEventListener("click", async () => {
    enableBtn.disabled = true;
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        await refresh();
        return;
      }
      const { key } = await (await fetch("/push/public-key")).json();
      const reg = await registration();
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
      await postJson("/push/subscribe", sub.toJSON());
      window.ccToast && window.ccToast({ title: "Notifications on", message: "Try “Send test”." });
    } catch (err) {
      window.ccToast && window.ccToast({ title: "Couldn't turn notifications on", message: plainError(err), variant: "error" });
    } finally {
      enableBtn.disabled = false;
      refresh();
    }
  });

  testBtn.addEventListener("click", async () => {
    testBtn.disabled = true;
    try {
      const r = await postJson("/push/test");
      window.ccToast && window.ccToast({ message: r.sent ? "Test sent. It should appear in a moment." : "No device accepted the test." });
    } catch (err) {
      window.ccToast && window.ccToast({ message: err.message, variant: "error" });
    } finally {
      testBtn.disabled = false;
    }
  });

  disableBtn.addEventListener("click", async () => {
    disableBtn.disabled = true;
    try {
      const reg = await registration();
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await postJson("/push/unsubscribe", { endpoint: sub.endpoint });
        await sub.unsubscribe();
      }
    } catch (err) {
      window.ccToast && window.ccToast({ title: "Couldn't turn notifications off", message: plainError(err), variant: "error" });
    } finally {
      disableBtn.disabled = false;
      refresh();
    }
  });

  refresh().catch(() => show("Couldn't check notification status.", "none"));
})();
