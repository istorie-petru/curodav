// Playful wording for toasts. Mirrors the script-side phrases in src/terminology.py; only used when
// <html data-terminology="playful">.
(function () {
  const PLAYFUL = {
    "Copied": "Copied. Paste responsibly",
    "Deleted": "Gone. Poof",
    "Moved": "Moved. Smooth",
    "Notification settings saved": "Got it. I'll nudge you accordingly",
    "Could not save that move. Reverted.": "That didn't stick, so it's back where it was",
    "Could not load the log": "The log is playing hide and seek"
};
  window.ccPhrase = function (text) {
    if (typeof text !== "string" || document.documentElement.dataset.terminology !== "playful") return text;
    return Object.prototype.hasOwnProperty.call(PLAYFUL, text) ? PLAYFUL[text] : text;
  };
})();
