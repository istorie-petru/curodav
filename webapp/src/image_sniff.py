"""Magic-byte image sniffing -- no Pillow/PIL dependency, deliberately
(see routers/contacts.py's own `_read_photo` comment: "No resizing/
transcoding (would need Pillow, a new dependency)" -- this app has stayed
off image libraries on purpose).

This doesn't decode or fully validate an image end-to-end (a truncated or
otherwise corrupt-but-correctly-signed file still passes -- that would
need a real image-decoding library) -- it only confirms the first few
bytes match a real signature for one of the four types this app supports,
closing the gap where arbitrary bytes with a spoofed header would
otherwise be accepted and stored.
"""

from __future__ import annotations


def sniff_image_type(data: bytes) -> str | None:
    """One of "jpeg"/"png"/"gif"/"webp" -- the same vocabulary every
    upload route's own Content-Type allowlist already uses -- if `data`
    starts with that format's real magic bytes, else None. GIF/PNG/JPEG
    signatures sit at a fixed offset from the start; WEBP is a RIFF
    container, so both the outer "RIFF" tag (bytes 0-3) and the inner
    "WEBP" tag (bytes 8-11) are checked -- a RIFF file that isn't WEBP
    (e.g. a .wav) correctly sniffs as None."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None
