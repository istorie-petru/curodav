"""Bringing accounts into the vault and taking them out (features/accounts-vault.md).

`read_import` turns a KeePass file, a CSV export (KeePassXC, Bitwarden, Chrome, Firefox or any file with similar columns) or
a Bitwarden JSON export into plain rows; `preview` counts them and finds the ones already in the vault; `apply` adds them to a
space, keeping each row's group from the other program as a tag. `export_csv` writes the KeePassXC CSV layout, which is unprotected and only offered after
the master password is given again.
"""

from __future__ import annotations

import csv
import io
import json

from . import vault_kdbx as kdbx
from . import vault_service as vs

_COLUMNS = {
    "title": ("title", "name", "account", "site"),
    "username": ("username", "user name", "login_username", "login", "user", "email"),
    "password": ("password", "login_password", "pass"),
    "url": ("url", "website", "login_uri", "uri", "web site", "address"),
    "notes": ("notes", "note", "extra", "comments"),
    "otp": ("totp", "otp", "login_totp", "one-time password"),
    "group": ("group", "folder", "grouping", "category"),
    "tags": ("tags",),
}
MAX_IMPORT_BYTES = 20 * 1024 * 1024


class ImportError_(ValueError):
    pass


def _row(**kw) -> dict:
    return {"title": "", "username": "", "password": "", "url": "", "notes": "", "otp": "", "group": "", "tags": [], "custom": [], **kw}


def _from_kdbx(data: bytes, password: str, key_file: bytes | None) -> list[dict]:
    try:
        database = kdbx.load(data, kdbx.composite_key(password or None, key_file or None))
    except kdbx.WrongKey:
        raise ImportError_("The password or key file does not open that KeePass file") from None
    except kdbx.VaultError as exc:
        raise ImportError_(str(exc)) from None
    rows = []
    for entry in vs.list_entries(database):
        values = vs.edit_values(database, entry["uuid"])
        rows.append(_row(title=values["title"], username=values["username"], password=values["password"], url=values["url"],
                         notes=values["notes"], otp=values["otp"], group=entry["group"], tags=values["tags"], custom=values["custom"]))
    return rows


def _from_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ImportError_("The file has no header row")
    names = {h.strip().lower(): h for h in reader.fieldnames if h}
    pick = {key: next((names[c] for c in cands if c in names), None) for key, cands in _COLUMNS.items()}
    if not pick["password"] and not pick["username"]:
        raise ImportError_("No user name or password column was found")
    rows = []
    for record in reader:
        get = lambda k: (record.get(pick[k]) or "").strip() if pick[k] else ""  # noqa: E731
        title = get("title") or get("url") or get("username")
        if not title and not get("password"):
            continue
        rows.append(_row(title=title or "Untitled", username=get("username"), password=(record.get(pick["password"]) or "") if pick["password"] else "",
                         url=get("url"), notes=get("notes"), otp=get("otp"), group=get("group").replace("/", " / "),
                         tags=[t.strip() for t in get("tags").replace(",", ";").split(";") if t.strip()]))
    return rows


def _from_bitwarden(data: dict) -> list[dict]:
    folders = {f.get("id"): f.get("name") or "" for f in data.get("folders") or []}
    rows = []
    for item in data.get("items") or []:
        login = item.get("login") or {}
        uris = login.get("uris") or []
        custom = [{"key": f.get("name") or "Field", "value": f.get("value") or "", "protected": f.get("type") == 1} for f in item.get("fields") or []]
        for part in ("card", "identity"):
            for key, value in (item.get(part) or {}).items():
                if value and isinstance(value, str):
                    custom.append({"key": key, "value": value, "protected": key in ("number", "code", "ssn", "passportNumber", "licenseNumber")})
        rows.append(_row(title=item.get("name") or "Untitled", username=login.get("username") or "", password=login.get("password") or "",
                         url=(uris[0].get("uri") if uris else "") or "", notes=item.get("notes") or "", otp=login.get("totp") or "",
                         group=folders.get(item.get("folderId"), ""), custom=custom))
    return rows


def read_import(filename: str, data: bytes, password: str = "", key_file: bytes | None = None) -> list[dict]:
    if len(data) > MAX_IMPORT_BYTES:
        raise ImportError_("The file is too large to import")
    if data[:4] == b"\x03\xd9\xa2\x9a":
        return _from_kdbx(data, password, key_file)
    text = data.decode("utf-8-sig", "replace")
    if filename.lower().endswith(".json") or text.lstrip().startswith("{"):
        try:
            parsed = json.loads(text)
        except ValueError:
            raise ImportError_("The JSON file cannot be read") from None
        if parsed.get("encrypted"):
            raise ImportError_("Export the Bitwarden vault unencrypted to import it")
        return _from_bitwarden(parsed)
    return _from_csv(text)


def _identity(row: dict) -> tuple[str, str, str]:
    return (row["title"].strip().lower(), (row["username"] or "").strip().lower(), (row["url"] or "").strip().lower().rstrip("/"))


def preview(database: kdbx.Database, rows: list[dict]) -> dict:
    have = {_identity(r) for r in vs.list_entries(database)}
    duplicates = [r for r in rows if _identity(r) in have]
    return {"count": len(rows), "duplicates": len(duplicates), "new": len(rows) - len(duplicates),
            "groups": sorted({r["group"] for r in rows if r["group"]})}


def apply(database: kdbx.Database, rows: list[dict], types: list[dict], skip_duplicates: bool = True, space: str = "") -> int:
    """Adds the rows to a space (or to no space). A row's group from the other program becomes a tag, since groups here are spaces."""
    have = {_identity(r) for r in vs.list_entries(database)}
    added = 0
    for row in rows:
        if skip_duplicates and _identity(row) in have:
            continue
        otp = row["otp"]
        if otp and vs.totp(otp if otp.startswith("otpauth://") else "otpauth://totp/x?secret=" + otp.replace(" ", "")) is None:
            row = {**row, "notes": (row["notes"] + "\n\nOne-time code: " + otp).strip(), "otp": ""}
        tags = list(row["tags"]) + ([row["group"].split(" / ")[-1]] if row["group"] else [])
        vs.save_entry(database, None, {**row, "tags": tags, "space": space, "group": "", "type": "login"}, types)
        added += 1
    return added


def export_csv(database: kdbx.Database) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Group", "Title", "Username", "Password", "URL", "Notes", "TOTP", "Tags"])
    for entry in vs.list_entries(database):
        v = vs.edit_values(database, entry["uuid"])
        writer.writerow([entry["space"], v["title"], v["username"], v["password"], v["url"], v["notes"], v["otp"], ";".join(v["tags"])])
    return out.getvalue()
