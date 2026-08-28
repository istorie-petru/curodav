"""Timeline (Gantt view) is retired -- 2026-08-28 "major rework" session,
item 4 ("Tasks page: table view only... disable Kanban and Timeline
entirely"). routers/timeline.py is now a two-route redirect stub; the old
TestBuildContext/TestTimelineViewRoute/TestReschedule/TestSetLane/
TestCreate classes (which exercised the removed Gantt layout/drag-endpoint
code) are gone with it -- `timeline_layout.py`'s own pure-function tests
(test_timeline_layout.py) are untouched and still cover the ported
interval-packing/swimlane-assignment/bar-geometry algorithms, which stay on
disk unused by any live route."""

from __future__ import annotations

from src.routers import timeline as timeline_router


class TestTimelineRetired:
    def test_timeline_view_redirects_to_tasks(self):
        resp = timeline_router.timeline_view_redirect()
        assert resp.status_code == 302
        assert resp.headers["location"] == "/tasks"

    def test_timeline_create_redirects_to_tasks(self):
        resp = timeline_router.timeline_create_redirect()
        assert resp.status_code == 302
        assert resp.headers["location"] == "/tasks"
