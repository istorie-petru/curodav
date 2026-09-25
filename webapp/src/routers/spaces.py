"""Old Space page URL. A Space's page lives at `/labels/{name}` since
labels-as-modules slice b (2026-09-25, routers/label_pages.py, which also
took over the Space-scope query this module used to own). This only keeps
old `/spaces/{name}` links and bookmarks working. Slice c turns Spaces into
text groups with their own pages.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/spaces", tags=["spaces"])


@router.get("/{name}")
def space_detail_redirect(name: str):
    return RedirectResponse(url=f"/labels/{quote(name)}", status_code=301)
