"""Item 10 follow-up (2026-09-27) -- serves an operator-supplied flair
photo straight off disk, from `Settings.flairs_dir` (`CC_FLAIRS_DIR`, see
config.py's own comment). This is the one route in the whole app that
serves arbitrary operator-placed files by name -- see `_safe_flair_id`
below for why the id is validated before ever touching the filesystem.

Not the app's own `/static/` mount (main.py): these bytes never ship
with the app and never live under `src/static/` at all -- see
src/flairs.py's own module docstring for the full story (the reference
Google Calendar images this feature was designed against are
copyrighted; the app ships zero photo bytes, an operator supplies their
own under the documented flair ids -- `documentation/flairs.md` has the
full list). Mirrors routers/banners.py's own `/banners/image` (read
bytes, sniff the real content-type rather than trusting the extension,
long-cache since the URL src/flairs.py builds is already mtime-
versioned)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .. import flairs
from ..image_sniff import sniff_image_type

router = APIRouter(tags=["flairs"])

# Every real flair id (src/flairs.py's FLAIR_KEYWORDS keys) is already
# lowercase-kebab-case, but this route reads `flair_id` straight off the
# URL path -- validated against that exact shape before it's ever used to
# build a filesystem path, so a request for a bogus/hostile id (path
# traversal, an unexpected extension smuggled into the segment, ...)
# 404s before any `Path` construction happens, rather than relying on
# `FLAIR_KEYWORDS` containment alone (an operator could legitimately drop
# a file under an id this app doesn't know about yet, e.g. testing a
# future keyword addition, so this checks *shape*, not *membership*).
# 2026-09-29: moved to flairs.py itself as `ID_SHAPE`, reused verbatim by
# `flairs.ingest_uploaded_photos` (the bulk-upload feature) for the exact
# same reason -- one definition of "what a safe flair id looks like".
_SAFE_ID = flairs.ID_SHAPE


@router.get("/flairs/{flair_id}")
def flair_image(flair_id: str):
    """Reads `{flairs_dir}/{flair_id}{ext}` for whichever extension
    `flairs.flair_image_url` found (the URL it built only carries the id
    and a cache-busting version, not the extension, so this route
    re-probes `flairs.SUPPORTED_EXTENSIONS` the same way). 404 for an id
    with no file placed yet, or a corrupt/unreadable one, or one whose
    bytes don't actually sniff as a real image -- same "never serve
    something that isn't really a photo" guard `/banners/image` and the
    contact-photo route both already apply to their own on-disk/stored
    bytes.

    Reads `flairs.get_flairs_dir()` (module state `main.py`'s lifespan
    sets via `flairs.configure`), not `request.app.state.settings` --
    one source of truth, the same one `flair_image_url` itself already
    uses to decide whether a URL exists at all, so this route can never
    disagree with the function that built the URL in the first place.
    A never-configured directory (`None`) is a 404, same as an id with
    no file in it."""
    if not _SAFE_ID.match(flair_id):
        raise HTTPException(404)
    directory = flairs.get_flairs_dir()
    if directory is None:
        raise HTTPException(404)
    for ext in flairs.SUPPORTED_EXTENSIONS:
        path = directory / f"{flair_id}{ext}"
        try:
            data = path.read_bytes()
        except OSError:
            continue
        image_type = sniff_image_type(data)
        if image_type is None:
            continue
        return Response(
            content=data,
            media_type=f"image/{image_type}",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "Content-Encoding": "identity",
            },
        )
    raise HTTPException(404)
