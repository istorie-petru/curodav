"""Access for programs other than the browser: personal API tokens, the OAuth 2.0 server Claude connectors use, and an activity log.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

Only SHA-256 hashes of tokens and codes are stored; a token is shown once, when it is made. OAuth follows the
authorization code flow with PKCE (S256 only), dynamic client registration and rotating refresh tokens. An access
token from either path is one `api_tokens` row, so revoking it in Settings works the same for both.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from . import clock

# What a token may do, area by area. Editing an area includes reading it. The older "read" (every area) and "write"
# (edit notes) are still understood.
SCOPES = {
    "read:notes": "Read notes, entries and the library",
    "read:calendar": "Read tasks and events",
    "read:university": "Read university",
    "write:notes": "Edit notes",
    "write:library": "Edit the library",
    "write:university": "Edit university",
}
_IMPLIED_READ = {"write:notes": "read:notes", "write:library": "read:notes", "write:university": "read:university"}
READ_SCOPES = ("read:notes", "read:calendar", "read:university")
DEFAULT_SCOPES = " ".join(READ_SCOPES)
_LEGACY = {"read": READ_SCOPES, "write": ("write:notes",)}
TOKEN_PREFIX = "cdv_"
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=60)
CODE_TTL = timedelta(minutes=5)
ACTIVITY_KEEP = 2000
MAX_CLIENTS = 50

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS api_tokens (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'personal',
    client_id TEXT NOT NULL DEFAULT '',
    scopes TEXT NOT NULL DEFAULT 'read',
    resource TEXT NOT NULL DEFAULT '',
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT,
    refresh_hash TEXT UNIQUE,
    refresh_expires_at TEXT,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id TEXT PRIMARY KEY,
    client_name TEXT NOT NULL DEFAULT '',
    redirect_uris_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_codes (
    code_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    scopes TEXT NOT NULL,
    resource TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    token_uid TEXT NOT NULL,
    surface TEXT NOT NULL,
    action TEXT NOT NULL
);
"""


class OAuthError(ValueError):
    """An OAuth error answered as {"error": code, "error_description": message}."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> datetime:
    return clock.now()


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _new_secret() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def normal_scopes(text: str | None, default: str = DEFAULT_SCOPES) -> str:
    """The scopes we know among `text`, space-separated in a fixed order; editing an area adds reading it. Nothing known
    gives `default`."""
    asked: set[str] = set()
    for word in (text or "").split():
        for scope in _LEGACY.get(word, (word,)):
            if scope in SCOPES:
                asked |= {scope, _IMPLIED_READ.get(scope, scope)}
    return " ".join(s for s in SCOPES if s in asked) or default


def scope_rows(scopes: str) -> list[dict[str, Any]]:
    """One row per scope for the switches in Settings and on the consent page."""
    held = set(normal_scopes(scopes, "").split())
    return [{"key": key, "label": label, "on": key in held} for key, label in SCOPES.items()]


_SHORT = {"read:notes": "notes", "read:calendar": "calendar", "read:university": "university",
          "write:notes": "notes", "write:library": "library", "write:university": "university"}


def describe(scopes: str) -> str:
    """A short summary for the token table, such as "Reads notes, university; edits university"."""
    held = normal_scopes(scopes, "").split()
    if not held:
        return "Nothing"
    reads = [_SHORT[s] for s in held if s.startswith("read:")]
    edits = [_SHORT[s] for s in held if s.startswith("write:")]
    parts = ["Reads " + ", ".join(reads)] if reads else []
    if edits:
        parts.append("edits " + ", ".join(edits))
    return "; ".join(parts)


def has_scope(token: dict[str, Any] | None, scope: str) -> bool:
    """Whether the token may do `scope`; "read" asks for any reading at all."""
    held = set(normal_scopes((token or {}).get("scopes"), "").split())
    return bool(held & set(READ_SCOPES)) if scope == "read" else scope in held


def set_scopes(conn: sqlite3.Connection, uid: str, scopes: str) -> bool:
    """Changes what a token may do, from the next request on. A token with no scope left keeps reading nothing."""
    cur = conn.execute("UPDATE api_tokens SET scopes = ? WHERE uid = ? AND revoked_at IS NULL", (normal_scopes(scopes, ""), uid))
    conn.commit()
    return cur.rowcount > 0


def get_token(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    for t in list_tokens(conn):
        if t["uid"] == uid:
            return t
    return None


# ---- Tokens ----

def create_personal_token(conn: sqlite3.Connection, name: str, scopes: str = DEFAULT_SCOPES) -> tuple[str, str]:
    """Makes a token that does not expire and returns (uid, secret). The secret is never readable again."""
    secret, uid = _new_secret(), str(uuid.uuid4())
    conn.execute("INSERT INTO api_tokens (uid, name, kind, scopes, token_hash, created_at) VALUES (?, ?, 'personal', ?, ?, ?)",
                 (uid, (name or "").strip()[:80] or "Token", normal_scopes(scopes, ""), _hash(secret), _iso(_now())))
    conn.commit()
    return uid, secret


def list_tokens(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Tokens still in force, newest first, with the app name for OAuth ones. Hashes are left out."""
    rows = conn.execute(
        "SELECT t.uid, t.name, t.kind, t.scopes, t.created_at, t.last_used_at, t.expires_at, t.refresh_expires_at, "
        "coalesce(c.client_name, '') AS client_name FROM api_tokens t LEFT JOIN oauth_clients c ON c.client_id = t.client_id "
        "WHERE t.revoked_at IS NULL AND (t.kind = 'personal' OR t.refresh_expires_at > ?) ORDER BY t.created_at DESC",
        (_iso(_now()),),
    ).fetchall()
    return [dict(r) for r in rows]


def revoke_token(conn: sqlite3.Connection, uid: str) -> bool:
    cur = conn.execute("UPDATE api_tokens SET revoked_at = ? WHERE uid = ? AND revoked_at IS NULL", (_iso(_now()), uid))
    conn.commit()
    return cur.rowcount > 0


def check_token(conn: sqlite3.Connection, secret: str | None, scope: str | None = "read") -> dict[str, Any] | None:
    """The token row when `secret` is a live token holding `scope` (None: any), else None. Marks it used."""
    if not secret or not secret.startswith(TOKEN_PREFIX):
        return None
    row = conn.execute("SELECT * FROM api_tokens WHERE token_hash = ?", (_hash(secret),)).fetchone()
    if row is None or row["revoked_at"]:
        return None
    now = _now()
    if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= now:
        return None
    if scope is not None and not has_scope(dict(row), scope):
        return None
    last = row["last_used_at"]
    if not last or now - datetime.fromisoformat(last) > timedelta(minutes=1):
        conn.execute("UPDATE api_tokens SET last_used_at = ? WHERE uid = ?", (_iso(now), row["uid"]))
        conn.commit()
    return dict(row)


def log_activity(conn: sqlite3.Connection, token_uid: str, surface: str, action: str) -> None:
    conn.execute("INSERT INTO api_activity (at, token_uid, surface, action) VALUES (?, ?, ?, ?)",
                 (_iso(_now()), token_uid, surface, action[:200]))
    conn.execute("DELETE FROM api_activity WHERE id <= (SELECT max(id) FROM api_activity) - ?", (ACTIVITY_KEEP,))
    conn.commit()


def recent_activity(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT a.at, a.surface, a.action, coalesce(t.name, '') AS token_name FROM api_activity a "
        "LEFT JOIN api_tokens t ON t.uid = a.token_uid ORDER BY a.id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ---- OAuth clients ----

def _redirect_ok(uri: str) -> bool:
    """HTTPS anywhere, or plain HTTP to this machine (Claude Code's loopback callback)."""
    parts = urlsplit(uri)
    if parts.fragment or not parts.netloc:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")


def register_client(conn: sqlite3.Connection, metadata: Any) -> dict[str, Any]:
    """RFC 7591 registration for a public client (no secret; PKCE protects the code)."""
    if not isinstance(metadata, dict):
        raise OAuthError("invalid_client_metadata", "The body must be a JSON object.")
    uris = metadata.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) and _redirect_ok(u) for u in uris):
        raise OAuthError("invalid_redirect_uri", "redirect_uris must list HTTPS or loopback addresses.")
    if metadata.get("token_endpoint_auth_method", "none") != "none":
        raise OAuthError("invalid_client_metadata", "Only public clients (token_endpoint_auth_method none) are supported.")
    if conn.execute("SELECT count(*) FROM oauth_clients").fetchone()[0] >= MAX_CLIENTS:
        conn.execute("DELETE FROM oauth_clients WHERE client_id IN (SELECT client_id FROM oauth_clients c WHERE NOT EXISTS "
                     "(SELECT 1 FROM api_tokens t WHERE t.client_id = c.client_id AND t.revoked_at IS NULL) "
                     "ORDER BY created_at LIMIT 10)")
    client_id = "cdv-client-" + secrets.token_urlsafe(16)
    name = str(metadata.get("client_name") or "")[:80] or "Unnamed app"
    now = _now()
    conn.execute("INSERT INTO oauth_clients (client_id, client_name, redirect_uris_json, created_at) VALUES (?, ?, ?, ?)",
                 (client_id, name, json.dumps(uris), _iso(now)))
    conn.commit()
    return {"client_id": client_id, "client_id_issued_at": int(now.timestamp()), "client_name": name, "redirect_uris": uris,
            "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"]}


def get_client(conn: sqlite3.Connection, client_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM oauth_clients WHERE client_id = ?", (client_id or "",)).fetchone()
    if row is None:
        return None
    return {"client_id": row["client_id"], "client_name": row["client_name"], "redirect_uris": json.loads(row["redirect_uris_json"])}


def check_authorize_request(conn: sqlite3.Connection, params: dict[str, str]) -> dict[str, Any]:
    """Validates an /oauth/authorize request. Raises OAuthError with `redirect` False when the client or redirect URI is
    wrong (the error must not go to that address) and True when the error can be sent back to the client."""
    client = get_client(conn, params.get("client_id", ""))
    if client is None:
        raise OAuthError("invalid_client", "This app is not registered.")
    redirect_uri = params.get("redirect_uri", "")
    if redirect_uri not in client["redirect_uris"]:
        raise OAuthError("invalid_request", "The redirect address does not match the registration.")
    if params.get("response_type") != "code":
        raise OAuthError("unsupported_response_type", "Only response_type=code is supported.")
    if params.get("code_challenge_method") != "S256" or not params.get("code_challenge"):
        raise OAuthError("invalid_request", "PKCE with code_challenge_method=S256 is required.")
    return {"client": client, "redirect_uri": redirect_uri, "scopes": normal_scopes(params.get("scope")),
            "state": params.get("state", ""), "code_challenge": params["code_challenge"], "resource": params.get("resource", "")}


def issue_code(conn: sqlite3.Connection, request: dict[str, Any]) -> str:
    code = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM oauth_codes WHERE expires_at < ?", (_iso(_now()),))
    conn.execute("INSERT INTO oauth_codes (code_hash, client_id, redirect_uri, code_challenge, scopes, resource, expires_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (_hash(code), request["client"]["client_id"], request["redirect_uri"], request["code_challenge"],
                  request["scopes"], request["resource"], _iso(_now() + CODE_TTL)))
    conn.commit()
    return code


def _pkce_ok(verifier: str, challenge: str) -> bool:
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return 43 <= len(verifier) <= 128 and secrets.compare_digest(digest, challenge)


def _token_response(conn: sqlite3.Connection, uid: str, scopes: str) -> dict[str, Any]:
    access, refresh, now = _new_secret(), _new_secret(), _now()
    conn.execute("UPDATE api_tokens SET token_hash = ?, expires_at = ?, refresh_hash = ?, refresh_expires_at = ? WHERE uid = ?",
                 (_hash(access), _iso(now + ACCESS_TTL), _hash(refresh), _iso(now + REFRESH_TTL), uid))
    conn.commit()
    return {"access_token": access, "token_type": "Bearer", "expires_in": int(ACCESS_TTL.total_seconds()),
            "refresh_token": refresh, "scope": scopes}


def exchange_code(conn: sqlite3.Connection, form: dict[str, str]) -> dict[str, Any]:
    code = form.get("code", "")
    row = conn.execute("SELECT * FROM oauth_codes WHERE code_hash = ?", (_hash(code),)).fetchone()
    conn.execute("DELETE FROM oauth_codes WHERE code_hash = ?", (_hash(code),))
    conn.commit()
    if row is None or datetime.fromisoformat(row["expires_at"]) <= _now():
        raise OAuthError("invalid_grant", "The code is unknown, used or expired.")
    if form.get("client_id") != row["client_id"] or form.get("redirect_uri") != row["redirect_uri"]:
        raise OAuthError("invalid_grant", "The code was issued to another app or address.")
    if not _pkce_ok(form.get("code_verifier", ""), row["code_challenge"]):
        raise OAuthError("invalid_grant", "The code verifier does not match.")
    client = get_client(conn, row["client_id"]) or {"client_name": ""}
    uid = str(uuid.uuid4())
    conn.execute("INSERT INTO api_tokens (uid, name, kind, client_id, scopes, resource, token_hash, created_at) "
                 "VALUES (?, ?, 'oauth', ?, ?, ?, ?, ?)",
                 (uid, client["client_name"], row["client_id"], row["scopes"], row["resource"], _hash(secrets.token_hex(16)), _iso(_now())))
    return _token_response(conn, uid, row["scopes"])


def refresh(conn: sqlite3.Connection, form: dict[str, str]) -> dict[str, Any]:
    """Rotates both tokens. A refresh token is good once; the old pair stops working."""
    row = conn.execute("SELECT * FROM api_tokens WHERE refresh_hash = ?", (_hash(form.get("refresh_token", "")),)).fetchone()
    if (row is None or row["revoked_at"] or form.get("client_id") != row["client_id"]
            or datetime.fromisoformat(row["refresh_expires_at"]) <= _now()):
        raise OAuthError("invalid_grant", "The refresh token is unknown, revoked or expired.")
    return _token_response(conn, row["uid"], row["scopes"])


def token_request(conn: sqlite3.Connection, form: dict[str, str]) -> dict[str, Any]:
    grant = form.get("grant_type")
    if grant == "authorization_code":
        return exchange_code(conn, form)
    if grant == "refresh_token":
        return refresh(conn, form)
    raise OAuthError("unsupported_grant_type", "Use authorization_code or refresh_token.")


# ---- Discovery documents ----

def protected_resource_metadata(base: str) -> dict[str, Any]:
    """RFC 9728: `resource` is the connector address exactly."""
    return {"resource": f"{base}/mcp", "authorization_servers": [base], "scopes_supported": list(SCOPES),
            "bearer_methods_supported": ["header"], "resource_name": "Curodav"}


def authorization_server_metadata(base: str) -> dict[str, Any]:
    """RFC 8414."""
    return {"issuer": base, "authorization_endpoint": f"{base}/oauth/authorize", "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register", "scopes_supported": list(SCOPES),
            "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none"]}
