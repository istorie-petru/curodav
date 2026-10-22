from datetime import date

from src import quick_next, secretariat

TODAY = date(2026, 10, 22)


def _task(uid, due, status="todo", tags=None):
    return {"uid": uid, "title": uid, "due_at": due, "status": status, "tags": tags or []}


def test_curated_lists_overdue_first_then_by_date_and_skips_done_and_far_items():
    tasks = [_task("later", "2026-10-30"), _task("late", "2026-10-20"), _task("done", "2026-10-22", "done"),
             _task("far", "2027-01-01"), _task("undated", None)]
    events = [{"uid": "e1", "title": "Class", "start_at": "2026-10-22T10:00", "tags": [], "all_day": 0}]
    rows = quick_next.curated(TODAY, tasks, events)
    assert [r["uid"] for r in rows] == ["late", "e1", "later"]
    assert rows[0]["overdue"] and not rows[2]["overdue"]


def test_curated_is_capped():
    tasks = [_task(f"t{i}", "2026-10-23") for i in range(30)]
    assert len(quick_next.curated(TODAY, tasks, [])) == quick_next.LIMIT


def test_search_hits_become_rows_of_each_kind():
    hits = [{"type": "task", "entity": _task("a", "2026-10-22")},
            {"type": "contact", "title": "Ana", "entity": {"uid": "c1", "tags": ["Uni"]}}]
    rows = quick_next.from_search(hits)
    assert [(r["kind"], r["url"]) for r in rows] == [("task", "/tasks/a"), ("contact", "/contacts/c1")]
    assert rows[1]["title"] == "Ana" and rows[1]["tags"] == ["Uni"]


def test_pinned_notes_lead_and_keep_their_order():
    notes = [{"uid": "a"}, {"uid": "b", "pinned": 1}, {"uid": "c"}, {"uid": "d", "pinned": 1}]
    assert [n["uid"] for n in secretariat.pinned_first(notes)] == ["b", "d", "a", "c"]
