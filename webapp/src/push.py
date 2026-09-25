"""Web Push delivery (2026-09-24, plans/ui-cleanup-2026-09.md item 7,
slice P1: the plumbing -- keys, subscriptions, one send path).

- **VAPID keys**: one P-256 key pair per install, generated on first use
  and kept in app_meta (the private key never leaves the server; the
  public key is what a browser's `pushManager.subscribe` needs as its
  `applicationServerKey`). No Settings field to paste keys into -- there's
  nothing for the user to manage, and regenerating would silently orphan
  every existing subscription.
- **Subscriptions** live in `push_subscriptions` (db.py), one per
  browser/device that turned notifications on.
- **send_to_all** encrypts a small JSON payload (title/body/url/tag) per
  subscription via pywebpush and prunes subscriptions the push service
  reports as gone (404/410).

What to notify about, and when (event starts, tasks/habits due, sleep/
leisure time), is the scheduler's job -- later slices.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02, _check_sub
from pywebpush import WebPushException, webpush

from . import db

log = logging.getLogger(__name__)

_PRIVATE_KEY_META = "push_vapid_private_pem"
# The VAPID "sub" claim: push services want a contact they can reach
# about abusive traffic -- a `mailto:` address or a bare `https://` ORIGIN
# (py_vapid rejects anything with a path, which a first version of this
# default had: caught by the live scheduler check, 2026-09-24). Set your
# own email in Settings > General > Notifications (stored in app_meta
# under CONTACT_KEY, wins over the env var) or CC_PUSH_CONTACT=mailto:...
DEFAULT_CONTACT = "https://github.com"
CONTACT_KEY = "push_contact_email"
# Deliberately stricter than py_vapid's _check_sub, whose mailto branch
# isn't end-anchored (it would accept trailing junk, newlines included).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")
# How long a push service may hold an undelivered notification (seconds).
_TTL = 6 * 60 * 60


def _vapid(conn) -> Vapid02:
    pem = db.get_app_meta(conn, _PRIVATE_KEY_META)
    if pem:
        return Vapid02.from_pem(pem.encode())
    vapid = Vapid02()
    vapid.generate_keys()
    db.set_app_meta(conn, _PRIVATE_KEY_META, vapid.private_pem().decode())
    return vapid


def public_key(conn) -> str:
    """The applicationServerKey for `pushManager.subscribe`: the raw
    uncompressed P-256 point, base64url without padding."""
    raw = _vapid(conn).public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def normalize_email(value: str | None) -> str | None:
    """A Settings-entered address (with or without a `mailto:` prefix) as
    a bare lowercase-domain email, or None if it isn't a plausible one."""
    value = (value or "").strip()
    if value.lower().startswith("mailto:"):
        value = value[7:]
    if len(value) > 254 or not _EMAIL_RE.fullmatch(value):
        return None
    local, domain = value.rsplit("@", 1)
    return f"{local}@{domain.lower()}"


def contact_email(conn) -> str:
    """The email saved in Settings, or "" if none."""
    return db.get_app_meta(conn, CONTACT_KEY) or ""


def _contact(conn=None) -> str:
    if conn is not None:
        saved = normalize_email(contact_email(conn))
        if saved:
            return f"mailto:{saved}"
    value = (os.environ.get("CC_PUSH_CONTACT") or "").strip()
    if value and not _check_sub(value):
        log.warning("CC_PUSH_CONTACT %r isn't a mailto: address or https:// origin; using the default", value)
        value = ""
    return value or DEFAULT_CONTACT


def send_to_all(conn, title: str, body: str, url: str = "/", tag: str | None = None, sender=webpush) -> dict:
    """Send one notification to every subscribed device. Returns
    {"sent": n, "failed": n, "pruned": n}. `sender` is injectable for
    tests (pywebpush.webpush's signature)."""
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    vapid = _vapid(conn)
    contact = _contact(conn)
    now = datetime.now(timezone.utc).isoformat()
    sent = failed = pruned = 0
    for sub in db.list_push_subscriptions(conn):
        info = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
        try:
            sender(
                subscription_info=info,
                data=payload,
                vapid_private_key=vapid,
                vapid_claims={"sub": contact},
                ttl=_TTL,
                timeout=10,
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                db.delete_push_subscription(conn, sub["endpoint"])
                pruned += 1
            else:
                log.warning("Web Push to %s failed: %s", sub["endpoint"][:60], exc)
                failed += 1
            continue
        except Exception as exc:  # network error etc. -- never crash a caller
            log.warning("Web Push to %s failed: %s", sub["endpoint"][:60], exc)
            failed += 1
            continue
        db.mark_push_subscription_ok(conn, sub["endpoint"], now)
        sent += 1
    return {"sent": sent, "failed": failed, "pruned": pruned}
