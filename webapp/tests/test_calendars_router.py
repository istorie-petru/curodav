"""Unit test for the calendar-slug generation in routers/calendars.py --
the part of calendar creation that's pure logic and worth covering
directly. The rest of that router (cookie-based visibility toggle,
create/delete against a live CalDAV collection) is exercised in the live
smoke test, not duplicated here as a unit test.

`_slugify` no longer bakes in a fixed reserved-name set ("tasks"/
"contacts") -- since task lists and address books became their own
multi-collection tables (2026-07-31), the caller (`_all_collection_uids`)
is responsible for passing every name already in use across all three
collection types (calendars, task_lists, addressbooks) as `existing`, and
collision-avoidance is purely a function of that set. See
routers/task_lists.py/addressbooks.py for the identical helper."""

from __future__ import annotations

from src.routers.calendars import _all_collection_uids, _slugify


class TestSlugify:
    def test_basic_name(self):
        assert _slugify("Work", set()) == "work"

    def test_spaces_and_punctuation_become_dashes(self):
        assert _slugify("My Uni Schedule!", set()) == "my-uni-schedule"

    def test_collision_gets_suffixed(self):
        assert _slugify("Work", {"work"}) == "work-2"
        assert _slugify("Work", {"work", "work-2"}) == "work-3"

    def test_names_already_used_by_task_lists_or_addressbooks_are_avoided(self):
        # Simulates what _all_collection_uids would hand back if a task
        # list named "tasks" and the default "contacts" address book
        # already existed -- a new calendar named either must not collide.
        existing = {"tasks", "contacts"}
        assert _slugify("Tasks", existing) not in existing
        assert _slugify("Contacts", existing) not in existing

    def test_empty_name_falls_back_to_calendar(self):
        assert _slugify("!!!", set()) == "calendar"


class TestAllCollectionUids:
    def test_union_across_calendars_task_lists_addressbooks(self, tmp_path):
        from src import db

        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as conn:
            db.ensure_default_calendar(conn)
            db.ensure_default_task_list(conn)
            db.ensure_default_addressbook(conn)
            uids = _all_collection_uids(conn)
        assert uids == {"calendar", "tasks", "contacts"}
