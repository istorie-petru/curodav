"""Timeline (Gantt) view -- retired 2026-08-28 ("major rework" session,
item 4: "Tasks page: table view only... disable Kanban and Timeline
entirely"). This module used to own `GET /tasks/timeline` (the Gantt page
itself), `POST /tasks/timeline/create` (click-drag-to-create), and two
drag-interaction endpoints (`timeline-reschedule`/`timeline-lane`); all
four are gone now, replaced by a single redirect to the Table view, the
same "any bookmark still lands somewhere real, not a bare 404" precedent
`/projects`'s own retirement established (see routers/projects.py's module
docstring) and `routers/tasks.py::board_view_redirect`/`habits_view_
redirect` reuse for Kanban/Habits in this same session.

`timeline_layout.py` (the ported interval-packing/swimlane-assignment/bar-
geometry algorithms) and `static/timeline.js` (the drag interactions) are
deliberately left on disk, unimported by anything live -- same "don't
force-drop old code/data for a presentation-only retirement" convention
`routers/projects.py`'s own promote/demote/dates left untouched. Nothing
else in this app imports from this module (confirmed via grep before this
rewrite), so this is a safe, isolated file-level swap."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["timeline"])


@router.get("/tasks/timeline")
def timeline_view_redirect():
    return RedirectResponse(url="/tasks", status_code=302)


@router.post("/tasks/timeline/create")
def timeline_create_redirect():
    return RedirectResponse(url="/tasks", status_code=302)
