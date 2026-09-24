"""Web Push slice P1 (2026-09-24, plans/ui-cleanup-2026-09.md item 7):
VAPID keys, subscriptions, the send path (with a fake sender -- no real
push service is reachable from tests), endpoint validation, and the
service worker / Settings wiring."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest
from pywebpush import WebPushException
from starlette.requests import Request

from src import db, push
from src.routers import push as push_router

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _json_req(payload, path="/push/subscribe"):
    body = json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": path, "headers": [(b"user-agent", b"TestUA")],
                    "query_string": b""}, receive)


SUB = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "BPk", "auth": "xyz"}}


class TestKeys:
    def test_public_key_is_stable_uncompressed_p256(self, conn):
        k1 = push.public_key(conn)
        k2 = push.public_key(conn)
        assert k1 == k2  # generated once, persisted
        raw = base64.urlsafe_b64decode(k1 + "=" * (-len(k1) % 4))
        assert len(raw) == 65 and raw[0] == 4
        assert "=" not in k1
        assert db.get_app_meta(conn, "push_vapid_private_pem").startswith("-----BEGIN PRIVATE KEY-----")


class TestSubscribe:
    def test_subscribe_and_unsubscribe(self, conn):
        resp = asyncio.run(push_router.subscribe(_json_req(SUB), conn=conn))
        assert resp == {"ok": True}
        (row,) = db.list_push_subscriptions(conn)
        assert (row["endpoint"], row["user_agent"]) == (SUB["endpoint"], "TestUA")
        asyncio.run(push_router.subscribe(_json_req(SUB), conn=conn))  # idempotent
        assert len(db.list_push_subscriptions(conn)) == 1
        asyncio.run(push_router.unsubscribe(_json_req({"endpoint": SUB["endpoint"]}, "/push/unsubscribe"), conn=conn))
        assert db.list_push_subscriptions(conn) == []

    @pytest.mark.parametrize(
        "payload",
        [
            {"endpoint": "http://push.example.com/abc", "keys": SUB["keys"]},  # not https
            {"endpoint": "file:///etc/passwd", "keys": SUB["keys"]},
            {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "", "auth": "x"}},
            {"endpoint": "https://push.example.com/abc"},
            {"keys": SUB["keys"]},
        ],
    )
    def test_rejects_invalid(self, conn, payload):
        resp = asyncio.run(push_router.subscribe(_json_req(payload), conn=conn))
        assert resp.status_code == 400
        assert db.list_push_subscriptions(conn) == []


class _Resp:
    def __init__(self, status):
        self.status_code = status


class TestSend:
    def test_sends_payload_and_prunes_gone(self, conn):
        db.upsert_push_subscription(conn, "https://a.example/1", "k", "a", None, "now")
        db.upsert_push_subscription(conn, "https://b.example/2", "k", "a", None, "now")
        db.upsert_push_subscription(conn, "https://c.example/3", "k", "a", None, "now")
        calls = []

        def fake(subscription_info, data, **kw):
            calls.append((subscription_info["endpoint"], json.loads(data), kw))
            if "b.example" in subscription_info["endpoint"]:
                raise WebPushException("gone", response=_Resp(410))
            if "c.example" in subscription_info["endpoint"]:
                raise WebPushException("server error", response=_Resp(500))

        result = push.send_to_all(conn, "Hi", "Body", url="/habits", tag="t", sender=fake)
        assert result == {"sent": 1, "failed": 1, "pruned": 1}
        assert [s["endpoint"] for s in db.list_push_subscriptions(conn)] == ["https://a.example/1", "https://c.example/3"]
        endpoint, payload, kw = calls[0]
        assert payload == {"title": "Hi", "body": "Body", "url": "/habits", "tag": "t"}
        assert kw["vapid_claims"]["sub"].startswith(("https://", "mailto:"))
        ok_row = next(s for s in db.list_push_subscriptions(conn) if s["endpoint"] == "https://a.example/1")
        assert ok_row["last_ok_at"]

    def test_network_error_never_raises(self, conn):
        db.upsert_push_subscription(conn, "https://a.example/1", "k", "a", None, "now")

        def boom(**kw):
            raise ConnectionError("offline")

        assert push.send_to_all(conn, "Hi", "B", sender=boom) == {"sent": 0, "failed": 1, "pruned": 0}

    def test_test_endpoint_needs_a_device(self, conn):
        assert push_router.send_test(conn=conn).status_code == 400


class TestWiring:
    def test_service_worker_handles_push_and_click(self):
        sw = (_STATIC / "sw.js").read_text()
        assert 'self.addEventListener("push"' in sw
        assert 'self.addEventListener("notificationclick"' in sw
        assert "u.origin === self.location.origin" in sw  # never navigates off-site

    def test_settings_card_and_script(self, conn):
        from src.routers import settings as settings_router

        req = Request({"type": "http", "method": "GET", "path": "/settings/general", "headers": [], "query_string": b""})
        body = settings_router.settings_general(req, conn=conn).body.decode()
        assert 'id="push-settings"' in body and "push_settings.js" in body
