"""Server-side image re-encoding to WebP (2026-09-13, direct request:
"contact images should be resource efficient (webp) -- I know they can be
saved inline in the contacts thing [as whatever format the syncing CardDAV
client chose], I would prefer the frontend to serve webp images not the
one in vcf directly. Of course they should be the same [visually]").

This is the first real image-decoding dependency this app has ever taken
on -- `image_sniff.py`'s own header comment documents a long-standing,
deliberate "no Pillow/PIL dependency" stance, and `routers/contacts.py`'s
`_read_photo`/`routers/banners.py` both have comments from as far back as
2026-08 explicitly declining to add one ("would need Pillow, a new
dependency"). That stance held as long as nothing actually needed to
decode pixels -- sniffing a signature, storing/serving bytes verbatim, and
capping upload size never did. Re-encoding to a *different* format is not
possible without a real decoder; there's no way to transcode JPEG/PNG/GIF
bytes into WebP by just re-arranging bytes. Scoped to `contacts.photo_b64`
only (the only surface this request named) -- banners and the user's own
profile photo (routers/banners.py's banner_image, routers/settings.py's
profile_photo_image) still serve their stored bytes as-is, unchanged."""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

from PIL import Image

# 82 matches typical avatar/thumbnail-quality WebP presets (cwebp's own
# default is 75; a contact photo is usually small and displayed small, so
# erring a few points above that default favors visual fidelity over the
# marginal extra bytes saved -- there was no numeric target given in the
# request beyond "resource efficient", so this is a reasonable default
# rather than a value derived from a specific size/quality requirement).
_WEBP_QUALITY = 82

# 2026-09-18 (direct report: "contacts page is slow loading all the
# photos") -- avatars render at 34px/52px (style.css's .avatar-circle/
# .avatar-large), so this is generous retina headroom (comfortably covers
# a 4x-density 52px avatar) while still cutting transferred bytes a lot
# versus serving a full-resolution source. Sibling app Pineart's own
# thumbnail pipeline (backend/app/services/images.py) uses the same
# "only downscale, never up" LANCZOS technique for the same reason.
_MAX_DIMENSION = 256


def to_webp(data: bytes, *, max_dimension: int | None = _MAX_DIMENSION) -> bytes | None:
    """Decodes `data` as an image and re-encodes it as WebP, returning the
    new bytes -- or None if `data` isn't a real, decodable image (a
    corrupt/truncated sync payload should fail closed, not raise past the
    caller into a 500; the route falls back to serving the original bytes
    verbatim in that case, the same behavior every photo route already had
    before this module existed).

    Every source format this app accepts (JPEG/PNG/GIF/WEBP, see
    routers/contacts.py's `_CONTENT_TYPE_TO_VCARD_TYPE`) round-trips
    through Pillow's own encoder/decoder -- no format-specific branching
    needed here. `convert("RGBA")` first handles two cases WebP's own
    encoder can't take as-is directly from every source mode: a palette-
    mode GIF (`P`) and a JPEG's `CMYK`/`L` variants; RGBA is a safe common
    target that also preserves a GIF/PNG's own transparency instead of
    flattening it onto a black/white background the way a plain RGB
    convert would.

    `max_dimension` downscales the longer edge to at most that many pixels
    (LANCZOS, never upscales) before encoding -- pass None to keep the
    source resolution verbatim (not used by any caller today, kept for
    callers that might want the un-downscaled transcode)."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()  # force a full decode now -- catches truncated data eagerly, not lazily on save()
            rgba = img.convert("RGBA")
            if max_dimension is not None and max(rgba.width, rgba.height) > max_dimension:
                ratio = max_dimension / max(rgba.width, rgba.height)
                new_size = (max(1, round(rgba.width * ratio)), max(1, round(rgba.height * ratio)))
                rgba = rgba.resize(new_size, Image.Resampling.LANCZOS)
            out = io.BytesIO()
            rgba.save(out, format="WEBP", quality=_WEBP_QUALITY)
            return out.getvalue()
    except Exception:
        # Deliberately broad: Pillow raises different exception types for
        # different corruption modes (UnidentifiedImageError, OSError,
        # struct.error for a truncated header, ...) and this path already
        # has a safe fallback (serve the original bytes) -- there's no
        # scenario here where letting an exception propagate is better
        # than falling back.
        return None


def write_cached_webp(directory: Path, filename: str, data: bytes) -> None:
    """Writes `data` to `directory/filename` without ever leaving a
    half-written file there -- a crash or power loss mid-write would leave
    a truncated cache entry that then gets served as a broken image on
    every subsequent request (unlike a cache miss, which just re-derives).
    Same temp-file-in-the-same-directory-then-`os.replace` technique
    sibling app Pineart's own image pipeline uses for exactly this reason
    (`backend/app/services/images.py`'s `_atomic_write_bytes`)."""
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{filename}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, directory / filename)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
