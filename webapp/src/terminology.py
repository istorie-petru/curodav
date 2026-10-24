"""Playful wording for the Terminology setting.

`PLAYFUL` maps a standard phrase to its playful one. Standard mode never reads it. Server-rendered text goes
through the `phrase` template filter; toast text goes through `static/phrases.js`, which carries the same map for the
phrases that only appear in scripts (keep the two lists in step; a test checks the shared ones).
"""

from __future__ import annotations

from contextvars import ContextVar

PLAYFUL = {
    "No accounts yet": "No accounts. Your wallet is suspiciously quiet",
    "No spaces yet.": "No spaces yet. Everyone is flying solo",
    "No tags yet.": "No tags yet. Nothing here but tumbleweeds",
    "No templates yet": "No templates yet. Blank page energy",
    "No holidays configured yet": "No holidays yet. Work forever, apparently",
    "No time blocks configured yet": "No time blocks. Sleep is currently optional",
    "No documents yet": "No documents yet. The pen awaits",
    "Copied": "Copied. Paste responsibly",
    "Deleted": "Gone. Poof",
    "Moved": "Moved. Smooth",
    "Notification settings saved": "Got it. I'll nudge you accordingly",
    "Could not save that move. Reverted.": "That didn't stick, so it's back where it was",
    "Could not load the log": "The log is playing hide and seek",
}

GREETINGS = {
    "Good morning": "Rise and shine",
    "Good afternoon": "Afternoon",
    "Good evening": "Evening",
}
GREETING_TAILS = {"Good evening": ". Look at you, still going"}

current_request: ContextVar = ContextVar("terminology_request", default=None)


def playful_text(text: str) -> str:
    if text in PLAYFUL:
        return PLAYFUL[text]
    for standard, playful in GREETINGS.items():
        if text == standard:
            return playful
        if text.startswith(standard + ", "):
            return f"{playful}, {text[len(standard) + 2:]}{GREETING_TAILS.get(standard, '')}"
    return text
