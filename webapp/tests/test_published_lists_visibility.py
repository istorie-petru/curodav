"""Published Lists' visibility states + standalone public feed (2026-08-29).

See src/routers/published_lists.py's module docstring for the model:
private (Radicale only) / public (also a standalone unauthenticated link,
routers/public_lists.py) / archived (paused, Radicale collection torn
down, row kept). Radicale is optional throughout -- every mutating route
is best-effort about the bridge (see published_lists.py's module
docstring), so a None bridge must never turn into an unhandled exception.

Coverage, following test_phase6_published_lists.py's conventions (direct
router-function calls, a FakeBridge modeling Radicale as in-memory dicts):

  - db.py: the visibility/public_token migration defaults, get/set
    helpers, get_published_list_by_token.
  - published_lists.py: materialize_all skips archived rows; new_public_
    token/teardown_collection.
  - routers/published_lists.py: create_list's visibility field (default
    private, public generates a token); set_visibility's three
    transitions (tears down on archive, re-materializes on un-archive,
    generates a token the first time something goes public, is a no-op
    on Radicale when bridge is None); delete_list/create_list no longer
    hard-require a bridge.
  - routers/public_lists.py: a public token's live-generated .ics/.vcf
    feed, 404 for unknown/private/archived tokens and a mismatched
    extension, and the bare-token redirect.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.published_lists import materialize_all, new_public_token
from test_phase6_published_lists import FakeBridge, _make_task


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _fake_request(path: str) -> Request:
    return Request(
        {
            "type": "http", "method": "GET", "path": path,
            "query_string": b"", "scheme": "http", "server": ("testserver", 80),
            "root_path": "", "headers": [], "app": None,
        }
    )


# --------------------------------------------------------------------- #
# db.py
# --------------------------------------------------------------------- #


class TestDbVisibility:
    def test_new_row_defaults_to_private(self, conn):
        db.upsert_published_list(conn, {
            "id": "l1", "name": "A", "entity_type": "task",
            "label_filter": {"any": ["X"]}, "radicale_collection_path": "published-a",
            "created_at": _now(),
        })
        row = db.get_published_list(conn, "l1")
        assert row["visibility"] == "private"
        assert row["public_token"] is None

    def test_set_visibility_updates_only_those_columns(self, conn):
        db.upsert_published_list(conn, {
            "id": "l1", "name": "A", "entity_type": "task",
            "label_filter": {"any": ["X"]}, "radicale_collection_path": "published-a",
            "created_at": _now(),
        })
        db.set_published_list_visibility(conn, "l1", "public", "tok123")
        row = db.get_published_list(conn, "l1")
        assert row["visibility"] == "public"
        assert row["public_token"] == "tok123"
        assert row["name"] == "A"  # untouched

    def test_set_visibility_without_token_leaves_existing_token(self, conn):
        db.upsert_published_list(conn, {
            "id": "l1", "name": "A", "entity_type": "task",
            "label_filter": {"any": ["X"]}, "radicale_collection_path": "published-a",
            "created_at": _now(), "visibility": "public", "public_token": "tok123",
        })
        db.set_published_list_visibility(conn, "l1", "private")
        row = db.get_published_list(conn, "l1")
        assert row["visibility"] == "private"
        assert row["public_token"] == "tok123"  # stable across toggles

    def test_get_published_list_by_token(self, conn):
        db.upsert_published_list(conn, {
            "id": "l1", "name": "A", "entity_type": "task",
            "label_filter": {"any": ["X"]}, "radicale_collection_path": "published-a",
            "created_at": _now(), "visibility": "public", "public_token": "tok123",
        })
        assert db.get_published_list_by_token(conn, "tok123")["id"] == "l1"
        assert db.get_published_list_by_token(conn, "no-such-token") is None
        assert db.get_published_list_by_token(conn, "") is None

    def test_new_public_token_is_random_and_long(self):
        a, b = new_public_token(), new_public_token()
        assert a != b
        assert len(a) >= 32


# --------------------------------------------------------------------- #
# published_lists.py -- materialize_all skips archived
# --------------------------------------------------------------------- #


class TestMaterializeAllSkipsArchived:
    def _row(self, list_id, visibility):
        return {
            "id": list_id, "name": "A", "entity_type": "task",
            "label_filter": {"all": ["University"]},
            "radicale_collection_path": f"published-{list_id}",
            "created_at": _now(), "visibility": visibility,
        }

    def test_archived_row_is_never_materialized(self, conn):
        _make_task(conn, "t1", "A", ["University"])
        db.upsert_published_list(conn, self._row("archived-list", "archived"))
        db.upsert_published_list(conn, self._row("live-list", "private"))
        results = materialize_all(conn, FakeBridge())
        assert "archived-list" not in results
        assert "live-list" in results


# --------------------------------------------------------------------- #
# routers/published_lists.py
# --------------------------------------------------------------------- #


class TestCreateListVisibility:
    def test_defaults_to_private_no_token(self, conn):
        from src.routers import published_lists as router

        bridge = FakeBridge()
        router.create_list(name="Uni", entity_type="task", labels=["University"], conn=conn, bridge=bridge)
        row = db.list_published_lists(conn)[0]
        assert row["visibility"] == "private"
        assert row["public_token"] is None

    def test_public_at_creation_generates_token_and_still_materializes(self, conn):
        from src.routers import published_lists as router

        _make_task(conn, "t1", "A", ["University"])
        bridge = FakeBridge()
        router.create_list(
            name="Uni", entity_type="task", labels=["University"], visibility="public",
            conn=conn, bridge=bridge,
        )
        row = db.list_published_lists(conn)[0]
        assert row["visibility"] == "public"
        assert row["public_token"]
        assert set(bridge.task_collections["published-uni"]) == {"t1"}

    def test_create_succeeds_with_no_bridge(self, conn):
        """Radicale is optional -- module docstring. A None bridge (never
        configured/unreachable) must not block creating or sharing a
        List."""
        from src.routers import published_lists as router

        router.create_list(
            name="Uni", entity_type="task", labels=["University"], visibility="public",
            conn=conn, bridge=None,
        )
        row = db.list_published_lists(conn)[0]
        assert row["visibility"] == "public"
        assert row["public_token"]

    def test_invalid_visibility_falls_back_to_private(self, conn):
        from src.routers import published_lists as router

        router.create_list(
            name="Uni", entity_type="task", labels=["University"], visibility="nonsense",
            conn=conn, bridge=FakeBridge(),
        )
        assert db.list_published_lists(conn)[0]["visibility"] == "private"


class TestSetVisibility:
    def _create(self, conn, bridge, visibility="private"):
        from src.routers import published_lists as router

        router.create_list(name="Uni", entity_type="task", labels=["University"], visibility=visibility, conn=conn, bridge=bridge)
        return db.list_published_lists(conn)[0]["id"]

    def test_private_to_public_generates_token(self, conn):
        from src.routers import published_lists as router

        bridge = FakeBridge()
        list_id = self._create(conn, bridge)
        assert db.get_published_list(conn, list_id)["public_token"] is None
        router.set_visibility(list_id, visibility="public", conn=conn, bridge=bridge)
        row = db.get_published_list(conn, list_id)
        assert row["visibility"] == "public"
        assert row["public_token"]

    def test_public_to_private_keeps_token_but_stops_serving(self, conn):
        from src.routers import published_lists as router

        bridge = FakeBridge()
        list_id = self._create(conn, bridge, "public")
        token = db.get_published_list(conn, list_id)["public_token"]
        router.set_visibility(list_id, visibility="private", conn=conn, bridge=bridge)
        row = db.get_published_list(conn, list_id)
        assert row["visibility"] == "private"
        assert row["public_token"] == token  # stable, just inert while private

    def test_archiving_tears_down_the_radicale_collection(self, conn):
        from src.routers import published_lists as router

        _make_task(conn, "t1", "A", ["University"])
        bridge = FakeBridge()
        list_id = self._create(conn, bridge)
        assert "t1" in bridge.task_collections["published-uni"]
        router.set_visibility(list_id, visibility="archived", conn=conn, bridge=bridge)
        assert "published-uni" in bridge.deleted_task_list_collections
        # The row itself survives -- "archived" is paused, not deleted.
        assert db.get_published_list(conn, list_id) is not None

    def test_archiving_with_no_bridge_does_not_raise(self, conn):
        from src.routers import published_lists as router

        list_id = self._create(conn, None)
        router.set_visibility(list_id, visibility="archived", conn=conn, bridge=None)
        assert db.get_published_list(conn, list_id)["visibility"] == "archived"

    def test_unarchiving_rematerializes(self, conn):
        from src.routers import published_lists as router

        _make_task(conn, "t1", "A", ["University"])
        bridge = FakeBridge()
        list_id = self._create(conn, bridge)
        router.set_visibility(list_id, visibility="archived", conn=conn, bridge=bridge)
        assert "published-uni" not in bridge.task_collections
        router.set_visibility(list_id, visibility="private", conn=conn, bridge=bridge)
        assert set(bridge.task_collections["published-uni"]) == {"t1"}

    def test_materialize_all_resumes_after_unarchiving(self, conn):
        from src.routers import published_lists as router

        _make_task(conn, "t1", "A", ["University"])
        bridge = FakeBridge()
        list_id = self._create(conn, bridge)
        router.set_visibility(list_id, visibility="archived", conn=conn, bridge=bridge)
        results = materialize_all(conn, bridge)
        assert list_id not in results
        router.set_visibility(list_id, visibility="private", conn=conn, bridge=bridge)
        # A fresh member added after un-archiving is picked up by the
        # normal periodic materialize_all, no special "re-create" step.
        _make_task(conn, "t2", "B", ["University"])
        results = materialize_all(conn, bridge)
        assert list_id in results
        assert set(bridge.task_collections["published-uni"]) == {"t1", "t2"}

    def test_unknown_list_id_is_a_no_op_redirect(self, conn):
        from src.routers import published_lists as router

        resp = router.set_visibility("no-such-id", visibility="public", conn=conn, bridge=FakeBridge())
        assert resp.status_code == 303

    def test_invalid_visibility_value_is_a_no_op(self, conn):
        from src.routers import published_lists as router

        bridge = FakeBridge()
        list_id = self._create(conn, bridge)
        router.set_visibility(list_id, visibility="nonsense", conn=conn, bridge=bridge)
        assert db.get_published_list(conn, list_id)["visibility"] == "private"


class TestDeleteListNoBridge:
    def test_delete_succeeds_with_no_bridge(self, conn):
        from src.routers import published_lists as router

        list_id = TestSetVisibility()._create(conn, None)
        router.delete_list(list_id, conn=conn, bridge=None)
        assert db.get_published_list(conn, list_id) is None


class TestListIndexPublicUrl:
    def test_public_row_gets_a_public_url_private_does_not(self, conn):
        from src.routers import published_lists as router

        bridge = FakeBridge()
        router.create_list(name="Uni", entity_type="task", labels=["University"], visibility="public", conn=conn, bridge=bridge)
        router.create_list(name="Priv", entity_type="task", labels=["University"], conn=conn, bridge=bridge)

        request = _fake_request("/published-lists")
        request.scope["app"] = _FakeApp()
        resp = router.list_index(request, conn=conn)
        by_name = {row["name"]: row for row in resp.context["lists"]}
        assert by_name["Uni"]["public_url"] is not None
        assert "/public/lists/" in by_name["Uni"]["public_url"]
        assert by_name["Priv"]["public_url"] is None


class _FakeSettings:
    radicale_base_url = "http://127.0.0.1:5232/devuser/"


class _FakeApp:
    class state:
        settings = _FakeSettings()


# --------------------------------------------------------------------- #
# routers/public_lists.py -- the standalone public feed
# --------------------------------------------------------------------- #


class TestPublicListsFeed:
    def _public_task_list(self, conn, bridge=None):
        from src.routers import published_lists as router

        _make_task(conn, "t1", "Buy milk", ["Shared"])
        router.create_list(name="Shared", entity_type="task", labels=["Shared"], visibility="public", conn=conn, bridge=bridge)
        return db.list_published_lists(conn)[0]

    def test_valid_public_task_token_serves_ics(self, conn):
        from src.routers import public_lists as pub

        row = self._public_task_list(conn)
        resp = pub.public_list_ics(row["public_token"], conn=conn)
        assert resp.status_code == 200
        assert resp.media_type == "text/calendar"
        body = resp.body.decode()
        assert "BEGIN:VCALENDAR" in body
        assert "SUMMARY:Buy milk" in body

    def test_valid_public_contact_token_serves_vcf(self, conn):
        from src.routers import public_lists as pub
        from src.routers import published_lists as router

        db.upsert_contact(conn, {"uid": "c1", "full_name": "Prof X", "tags": ["University"], "created_at": _now()})
        router.create_list(name="Contacts", entity_type="contact", labels=["University"], visibility="public", conn=conn, bridge=None)
        row = db.list_published_lists(conn)[0]
        resp = pub.public_list_vcf(row["public_token"], conn=conn)
        assert resp.status_code == 200
        assert resp.media_type == "text/vcard"
        assert "BEGIN:VCARD" in resp.body.decode()

    def test_wrong_extension_for_entity_type_is_404(self, conn):
        from fastapi import HTTPException

        from src.routers import public_lists as pub

        row = self._public_task_list(conn)
        with pytest.raises(HTTPException) as exc:
            pub.public_list_vcf(row["public_token"], conn=conn)
        assert exc.value.status_code == 404

    def test_unknown_token_is_404(self, conn):
        from fastapi import HTTPException

        from src.routers import public_lists as pub

        with pytest.raises(HTTPException) as exc:
            pub.public_list_ics("not-a-real-token", conn=conn)
        assert exc.value.status_code == 404

    def test_private_list_token_is_404(self, conn):
        from fastapi import HTTPException

        from src.routers import public_lists as pub
        from src.routers import published_lists as router

        row = self._public_task_list(conn)
        router.set_visibility(row["id"], visibility="private", conn=conn, bridge=None)
        with pytest.raises(HTTPException) as exc:
            pub.public_list_ics(row["public_token"], conn=conn)
        assert exc.value.status_code == 404

    def test_archived_list_token_is_404(self, conn):
        from fastapi import HTTPException

        from src.routers import public_lists as pub
        from src.routers import published_lists as router

        row = self._public_task_list(conn)
        router.set_visibility(row["id"], visibility="archived", conn=conn, bridge=None)
        with pytest.raises(HTTPException) as exc:
            pub.public_list_ics(row["public_token"], conn=conn)
        assert exc.value.status_code == 404

    def test_bare_token_redirects_to_extension_url(self, conn):
        from src.routers import public_lists as pub

        row = self._public_task_list(conn)
        resp = pub.public_list_redirect(row["public_token"], conn=conn)
        assert resp.status_code == 302
        assert resp.headers["location"] == f"/public/lists/{row['public_token']}.ics"

    def test_feed_reflects_current_membership_live(self, conn):
        """No Radicale round-trip involved -- the feed is generated
        straight from the label filter on every request, so a membership
        change is visible immediately, not just after the next sync
        tick."""
        from src.routers import public_lists as pub

        row = self._public_task_list(conn)
        db.set_object_labels(conn, "task", "t1", [])  # no longer a member
        resp = pub.public_list_ics(row["public_token"], conn=conn)
        assert "Buy milk" not in resp.body.decode()
