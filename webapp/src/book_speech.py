"""Reading aloud on the server: a sentence becomes a WAV file.

The voice is Piper when its service is installed (`curodav-ctl install --voice`, CC_PIPER_URL), natural and offline, with the voice
of the book's language when there is one; else espeak-ng, mechanical but always there. The reader uses this unless the reader
settings ask for the browser's own voices.

Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from typing import Any

import httpx

MAX_CHARS = 1000

# The languages a book's file can be marked as: code (what the voices and the reader use), name, and Calibre's three-letter code.
LANGUAGES = (
    ("en", "English", "eng"), ("ro", "Romanian", "ron"), ("fr", "French", "fra"), ("de", "German", "deu"), ("es", "Spanish", "spa"),
    ("it", "Italian", "ita"), ("pt", "Portuguese", "por"), ("nl", "Dutch", "nld"), ("pl", "Polish", "pol"), ("ru", "Russian", "rus"),
    ("uk", "Ukrainian", "ukr"), ("cs", "Czech", "ces"), ("sk", "Slovak", "slk"), ("hu", "Hungarian", "hun"), ("bg", "Bulgarian", "bul"),
    ("el", "Greek", "ell"), ("tr", "Turkish", "tur"), ("sv", "Swedish", "swe"), ("no", "Norwegian", "nor"), ("da", "Danish", "dan"),
    ("fi", "Finnish", "fin"), ("la", "Latin", "lat"), ("ar", "Arabic", "ara"), ("he", "Hebrew", "heb"), ("hi", "Hindi", "hin"),
    ("ja", "Japanese", "jpn"), ("zh", "Chinese", "zho"), ("ko", "Korean", "kor"), ("sr", "Serbian", "srp"), ("hr", "Croatian", "hrv"),
    ("sl", "Slovenian", "slv"), ("ca", "Catalan", "cat"), ("lt", "Lithuanian", "lit"), ("lv", "Latvian", "lav"), ("et", "Estonian", "est"),
)
_BY_CODE = {c: (n, t) for c, n, t in LANGUAGES}
_BY_CALIBRE = {t: c for c, _, t in LANGUAGES}


def language_code(value: str) -> str:
    """A language as one of the codes above ("ro", "ro-RO" and "ron" all give "ro"), or "" when it is not one of them."""
    value = (value or "").strip().lower().replace("_", "-")
    if value in _BY_CODE:
        return value
    if value.split("-")[0] in _BY_CODE:
        return value.split("-")[0]
    return _BY_CALIBRE.get(value, "")


def to_calibre(code: str) -> list[str]:
    return [_BY_CODE[code][1]] if code in _BY_CODE else []


def from_calibre(codes: list[str]) -> str:
    return next((_BY_CALIBRE[c] for c in codes or [] if c in _BY_CALIBRE), "")
_VOICE = re.compile(r"[a-z]{2,3}(-[a-z0-9]{2,8})?")


_voices: dict[str, Any] = {"at": 0.0, "list": {}}


def piper_url() -> str:
    return os.environ.get("CC_PIPER_URL", "").rstrip("/")


def piper_voices() -> dict[str, str]:
    """Voice name -> language code ("ro_RO-mihai-medium" -> "ro_RO") of the Piper service, asked again after a minute."""
    url = piper_url()
    if not url:
        return {}
    if time.monotonic() - _voices["at"] > 60:
        try:
            data = httpx.get(f"{url}/voices", timeout=3).json()
            _voices["list"] = {name: ((cfg.get("language") or {}).get("code") or name.split("-")[0]) for name, cfg in data.items()}
        except (httpx.HTTPError, ValueError, AttributeError):
            _voices["list"] = {}
        _voices["at"] = time.monotonic()
    return _voices["list"]


def voice_for(lang: str) -> str | None:
    """The Piper voice for a language ("ro", "ro-RO"), else an English one, else any; None without Piper."""
    voices = piper_voices()
    if not voices:
        return None
    want = (lang or "en").lower().replace("-", "_")
    for prefix in (want, want.split("_")[0], "en"):
        for name, code in voices.items():
            if code.lower().startswith(prefix):
                return name
    return next(iter(voices))


def available() -> bool:
    return bool(piper_voices() or shutil.which("espeak-ng") or shutil.which("espeak"))


def _piper(text: str, lang: str) -> bytes | None:
    voice = voice_for(lang)
    if not voice:
        return None
    try:
        resp = httpx.post(f"{piper_url()}/synthesize", json={"text": text, "voice": voice}, timeout=30)
    except httpx.HTTPError:
        return None
    return resp.content if resp.status_code == 200 and resp.content[:4] == b"RIFF" else None


def speak(text: str, lang: str = "en") -> bytes | None:
    """The sentence as WAV audio in the book's language, from Piper when it is installed, else espeak-ng; None with neither."""
    text = " ".join((text or "").split())[:MAX_CHARS]
    if not text:
        return None
    audio = _piper(text, lang)
    if audio:
        return audio
    tool = shutil.which("espeak-ng") or shutil.which("espeak")
    if not tool:
        return None
    lang = (lang or "en").lower()
    for voice in dict.fromkeys([lang if _VOICE.fullmatch(lang) else "en", lang.split("-")[0] if _VOICE.fullmatch(lang.split("-")[0]) else "en", "en"]):
        try:
            run = subprocess.run([tool, "-v", voice, "--stdout"], input=text.encode("utf-8"), capture_output=True, timeout=30, check=False)
        except subprocess.TimeoutExpired:
            return None
        if run.returncode == 0 and run.stdout[:4] == b"RIFF":
            return run.stdout
    return None
