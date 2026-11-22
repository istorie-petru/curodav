"""The Accounts vault's contents: groups, entries, history, the recycle bin, one-time codes, the generator and the health
check (features/accounts-vault.md).

Everything works on an open `vault_kdbx.Database` in memory. Curodav's own additions to an entry are ordinary KeePass custom
fields with a `curodav.` prefix (`curodav.type`, `curodav.contact`), so other KeePass programs show and keep them.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import math
import secrets
import string
import struct
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlparse

from . import vault_kdbx as kdbx

STANDARD = ("Title", "UserName", "Password", "URL", "Notes")
TYPE_FIELD, CONTACT_FIELD = "curodav.type", "curodav.contact"
OTP_FIELD = "otp"
RECYCLE_ICON = 43
# Field kinds a type can give its fields; a "secret" field is stored protected and shown with Copy and Reveal.
FIELD_KINDS = ("text", "secret", "address", "date", "code", "long text")
# A type's field named like one of these is that KeePass standard field; any other name is a custom field.
STANDARD_LABELS = {"User name": "UserName", "Password": "Password", "Address": "URL", "Notes": "Notes", "One-time code": OTP_FIELD}
# The kind each standard field always has, whatever type it appears in.
STANDARD_KINDS = {"User name": "text", "Password": "secret", "Address": "address", "One-time code": "code", "Notes": "long text"}
_NOTES = {"name": "Notes", "kind": "long text"}
DEFAULT_TYPES = [
    {"key": "login", "name": "Login", "icon": "key", "fields": [
        {"name": "User name", "kind": "text"}, {"name": "Password", "kind": "secret"}, {"name": "Address", "kind": "address"},
        {"name": "One-time code", "kind": "code"}, _NOTES]},
    {"key": "identity", "name": "Identity", "icon": "id-card", "fields": [
        {"name": "Full name", "kind": "text"}, {"name": "Birth date", "kind": "date"}, {"name": "Address", "kind": "long text"},
        {"name": "Phone", "kind": "text"}, {"name": "ID number", "kind": "secret"}, _NOTES]},
    {"key": "card", "name": "Card", "icon": "credit-card", "fields": [
        {"name": "Cardholder", "kind": "text"}, {"name": "Number", "kind": "secret"}, {"name": "Expiry", "kind": "text"},
        {"name": "CVC", "kind": "secret"}, {"name": "PIN", "kind": "secret"}, _NOTES]},
    {"key": "wifi", "name": "Wi-Fi", "icon": "wifi", "fields": [{"name": "Network", "kind": "text"}, {"name": "Password", "kind": "secret"},
                                                               {"name": "Security", "kind": "text"}, _NOTES]},
    {"key": "api", "name": "API key", "icon": "code", "fields": [{"name": "Key", "kind": "secret"}, {"name": "Secret", "kind": "secret"},
                                                                {"name": "Address", "kind": "address"}, _NOTES]},
    {"key": "recovery", "name": "Recovery codes", "icon": "life-buoy", "fields": [{"name": "Codes", "kind": "secret"}, _NOTES]},
    {"key": "note", "name": "Secure note", "icon": "file-text", "fields": [_NOTES]},
]
LOOKALIKES = set("Il1O0o|`'\"")


class EntryError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field, self.message = field, message


# ---------------------------------------------------------------- tree helpers

def _root_group(db: kdbx.Database) -> ET.Element:
    return db.root.find("./Root/Group")


def _meta(db: kdbx.Database) -> ET.Element:
    return db.root.find("./Meta")


def _set(parent: ET.Element, tag: str, value: str) -> None:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = value


def _touch(el: ET.Element, location: bool = False) -> None:
    times = el.find("Times")
    if times is None:
        times = kdbx.new_times()
        el.append(times)
    now = kdbx.encode_time()
    _set(times, "LastModificationTime", now)
    if location:
        _set(times, "LocationChanged", now)


def _strings(entry: ET.Element) -> dict[str, tuple[str, bool]]:
    out = {}
    for s in entry.findall("String"):
        value = s.find("Value")
        out[s.findtext("Key") or ""] = (kdbx.value_text(value), value is not None and value.get("Protected", "").lower() == "true")
    return out


def _set_string(entry: ET.Element, key: str, value: str, protected: bool = False) -> None:
    for s in entry.findall("String"):
        if s.findtext("Key") == key:
            kdbx.set_value(s.find("Value"), value, protected)
            return
    s = ET.Element("String")
    ET.SubElement(s, "Key").text = key
    kdbx.set_value(ET.SubElement(s, "Value"), value, protected)
    index = max([i for i, c in enumerate(list(entry)) if c.tag == "String"], default=-1) + 1
    entry.insert(index or len(entry), s)


def _remove_string(entry: ET.Element, key: str) -> None:
    for s in entry.findall("String"):
        if s.findtext("Key") == key:
            entry.remove(s)


def _parents(db: kdbx.Database) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in db.root.iter() for child in parent}


def _groups(db: kdbx.Database):
    return [g for g in _root_group(db).iter("Group")]


def _entries(db: kdbx.Database):
    """Live entries (not the copies kept in a History)."""
    out = []
    for g in _groups(db):
        out.extend(g.findall("Entry"))
    return out


def ref(el: ET.Element | None) -> str:
    """An element's UUID as hex, which is safe in an address (the file stores it as base64, which may hold a slash)."""
    if el is None:
        return ""
    try:
        return base64.b64decode(el.findtext("UUID") or "").hex()
    except ValueError:
        return ""


def _matches(el: ET.Element, uuid: str) -> bool:
    return bool(uuid) and (el.findtext("UUID") == uuid or ref(el) == uuid.lower())


def find_group(db: kdbx.Database, uuid: str) -> ET.Element | None:
    return next((g for g in _groups(db) if _matches(g, uuid)), None)


def find_entry(db: kdbx.Database, uuid: str) -> ET.Element | None:
    return next((e for e in _entries(db) if _matches(e, uuid)), None)


def recycle_bin(db: kdbx.Database, create: bool = False) -> ET.Element | None:
    uid = _meta(db).findtext("RecycleBinUUID") or ""
    group = find_group(db, uid) if uid else None
    if group is None and create:
        group = kdbx.new_group("Recycle Bin", RECYCLE_ICON)
        _root_group(db).append(group)
        _set(_meta(db), "RecycleBinUUID", group.findtext("UUID"))
        _set(_meta(db), "RecycleBinEnabled", "True")
    return group


def _in_bin(db: kdbx.Database, el: ET.Element, parents=None) -> bool:
    bin_ = recycle_bin(db)
    if bin_ is None:
        return False
    parents = parents or _parents(db)
    node = el
    while node is not None:
        if node is bin_:
            return True
        node = parents.get(node)
    return False


def _expiry(el: ET.Element) -> datetime | None:
    times = el.find("Times")
    if times is None or (times.findtext("Expires") or "").lower() != "true":
        return None
    return kdbx.decode_time(times.findtext("ExpiryTime"))


# ---------------------------------------------------------------- reading

def sync_spaces(db: kdbx.Database, spaces: list[str]) -> bool:
    """Gives every Curodav space a group of the same name under the vault's root; True when one had to be made.
    Groups are never made by hand: an entry sits in a space's group or, with no space, at the root."""
    root = _root_group(db)
    have = {(g.findtext("Name") or "").lower() for g in root.findall("Group")}
    made = False
    for name in spaces:
        if name.lower() not in have:
            root.append(kdbx.new_group(name))
            made = True
    return made


def space_group(db: kdbx.Database, space: str) -> ET.Element | None:
    if not space:
        return None
    return next((g for g in _root_group(db).findall("Group") if (g.findtext("Name") or "").lower() == space.lower() and g is not recycle_bin(db)), None)


def space_of(db: kdbx.Database, entry: ET.Element, parents=None) -> str:
    """The space an entry sits in: the name of its top group under the root, or "" at the root."""
    parents = parents or _parents(db)
    root, node, top = _root_group(db), entry, None
    while node is not None and node is not root:
        top, node = node, parents.get(node)
    return (top.findtext("Name") or "") if top is not None and top is not entry and top is not recycle_bin(db) else ""


def summary(db: kdbx.Database, entry: ET.Element, parents=None) -> dict:
    s = _strings(entry)
    parents = parents or _parents(db)
    group = parents.get(entry)
    expires = _expiry(entry)
    return {
        "uuid": ref(entry), "title": s.get("Title", ("",))[0] or "Untitled", "username": s.get("UserName", ("",))[0],
        "url": s.get("URL", ("",))[0], "type": s.get(TYPE_FIELD, ("login",))[0] or "login",
        "tags": [t for t in (entry.findtext("Tags") or "").replace(",", ";").split(";") if t.strip()],
        "group": group.findtext("Name") if group is not None else "", "group_uuid": ref(group), "space": space_of(db, entry, parents),
        "has_otp": bool(s.get(OTP_FIELD, ("",))[0]), "expires": expires.date().isoformat() if expires else "",
        "expired": bool(expires and expires < datetime.now(timezone.utc)),
        "modified": kdbx.decode_time((entry.find("Times") or ET.Element("x")).findtext("LastModificationTime")),
    }


def list_entries(db: kdbx.Database, *, space: str | None = None, query: str = "", tag: str = "", kind: str = "", trash: bool = False,
                 uuids: set[str] | None = None, known: set[str] | None = None) -> list[dict]:
    """Entries in a space ("" for no space, None for all), matched against title, user name, address, tags and custom field names."""
    parents = _parents(db)
    scope = None
    needle = query.strip().lower()
    out = []
    for entry in (scope.iter("Entry") if scope is not None else _entries(db)):
        if parents.get(entry) is not None and parents[entry].tag == "History":
            continue
        if _in_bin(db, entry, parents) != trash:
            continue
        row = summary(db, entry, parents)
        if known is not None and row["space"].lower() not in known:
            row["space"] = ""
        if space is not None and not trash and row["space"].lower() != space.lower():
            continue
        if uuids is not None and row["uuid"] not in uuids:
            continue
        if tag and tag.lower() not in {t.lower() for t in row["tags"]}:
            continue
        if kind and row["type"] != kind:
            continue
        if needle:
            hay = " ".join([row["title"], row["username"], row["url"], " ".join(row["tags"]),
                            " ".join(k for k in _strings(entry) if k not in STANDARD)]).lower()
            if needle not in hay:
                continue
        out.append(row)
    out.sort(key=lambda r: r["title"].lower())
    return out


def all_tags(db: kdbx.Database) -> list[str]:
    tags = {t.strip() for e in _entries(db) for t in (e.findtext("Tags") or "").replace(",", ";").split(";") if t.strip()}
    return sorted(tags, key=str.lower)


def entry_detail(db: kdbx.Database, uuid: str, types: list[dict]) -> dict | None:
    """One entry for its view: standard fields, custom fields in the type's order, notes, tags and the history count.
    Secret values are never part of it; they are fetched one at a time with `secret`."""
    entry = find_entry(db, uuid)
    if entry is None:
        return None
    s = _strings(entry)
    row = summary(db, entry)
    type_ = next((t for t in types if t["key"] == row["type"]), types[0])
    kinds = {f["name"]: f["kind"] for f in type_["fields"]}
    custom = []
    for key, (value, protected) in s.items():
        if key in STANDARD or key == OTP_FIELD or key.startswith("curodav."):
            continue
        custom.append({"key": key, "value": "" if protected else value, "protected": protected, "kind": kinds.get(key, "secret" if protected else "text")})
    order = [f["name"] for f in type_["fields"]]
    custom.sort(key=lambda f: (order.index(f["key"]) if f["key"] in order else len(order), f["key"].lower()))
    history = entry.find("History")
    return {**row, "type_name": type_["name"], "type_icon": type_["icon"], "notes": s.get("Notes", ("",))[0],
            "has_password": bool(s.get("Password", ("",))[0]), "custom": custom, "contact": s.get(CONTACT_FIELD, ("",))[0],
            "history": len(history.findall("Entry")) if history is not None else 0,
            "attachments": [b.findtext("Key") for b in entry.findall("Binary")]}


def edit_values(db: kdbx.Database, uuid: str) -> dict | None:
    """Everything an entry's edit form shows, secrets included; only sent inside the form of an unlocked vault."""
    entry = find_entry(db, uuid)
    if entry is None:
        return None
    s = _strings(entry)
    row = summary(db, entry)
    custom = [{"key": k, "value": v, "protected": p} for k, (v, p) in s.items() if k not in STANDARD and k != OTP_FIELD and not k.startswith("curodav.")]
    return {**row, "password": s.get("Password", ("",))[0], "notes": s.get("Notes", ("",))[0], "otp": s.get(OTP_FIELD, ("",))[0],
            "hidden": [k for k in ("UserName", "Password", "URL", "Notes") if s.get(k, ("", False))[1]],
            "contact": s.get(CONTACT_FIELD, ("",))[0], "custom": custom}


def secret(db: kdbx.Database, uuid: str, key: str) -> str | None:
    entry = find_entry(db, uuid)
    if entry is None:
        return None
    value = _strings(entry).get(key)
    if value is None:
        return None
    times = entry.find("Times")
    if times is not None:
        _set(times, "LastAccessTime", kdbx.encode_time())
        _set(times, "UsageCount", str(int(times.findtext("UsageCount") or "0") + 1))
    return value[0]


# ---------------------------------------------------------------- writing

def _keep_history(db: kdbx.Database, entry: ET.Element) -> None:
    history = entry.find("History")
    if history is None:
        history = ET.SubElement(entry, "History")
    snapshot = copy.deepcopy(entry)
    old = snapshot.find("History")
    if old is not None:
        snapshot.remove(old)
    history.append(snapshot)
    limit = int(_meta(db).findtext("HistoryMaxItems") or "10")
    while limit >= 0 and len(history.findall("Entry")) > limit:
        history.remove(history.findall("Entry")[0])


def save_entry(db: kdbx.Database, uuid: str | None, data: dict, types: list[dict]) -> str:
    """Creates or changes an entry from a form's values; a change keeps the previous version in the entry's history."""
    title = (data.get("title") or "").strip()
    if not title:
        raise EntryError("title", "An entry needs a title")
    group = space_group(db, data.get("space") or "") or find_group(db, data.get("group") or "") or _root_group(db)
    if uuid:
        entry = find_entry(db, uuid)
        if entry is None:
            raise EntryError("title", "This entry no longer exists")
        _keep_history(db, entry)
    else:
        entry = ET.SubElement(group, "Entry")
        ET.SubElement(entry, "UUID").text = kdbx.new_uuid()
        ET.SubElement(entry, "IconID").text = "0"
        entry.append(kdbx.new_times())
    otp = (data.get("otp") or "").strip()
    if otp and not otp.startswith("otpauth://"):
        otp = "otpauth://totp/Curodav?secret=" + otp.replace(" ", "").upper()
    if otp and totp(otp) is None:
        raise EntryError("otp", "The one-time code secret is not valid")
    type_key = data.get("type") or "login"
    if type_key not in {t["key"] for t in types}:
        type_key = "login"
    hidden = set(data["hidden"] if "hidden" in data else ["Password"])
    for key, value, protected in (("Title", title, False), ("UserName", data.get("username") or "", "UserName" in hidden),
                                  ("Password", data.get("password") or "", "Password" in hidden), ("URL", (data.get("url") or "").strip(), "URL" in hidden),
                                  ("Notes", data.get("notes") or "", "Notes" in hidden), (TYPE_FIELD, type_key, False)):
        _set_string(entry, key, value, protected)
    if otp:
        _set_string(entry, OTP_FIELD, otp, True)
    elif "otp" in data:
        _remove_string(entry, OTP_FIELD)
    if "contact" in data:
        contact = (data.get("contact") or "").strip()
        if contact:
            _set_string(entry, CONTACT_FIELD, contact)
        else:
            _remove_string(entry, CONTACT_FIELD)
    wanted = {}
    for f in data.get("custom") or []:
        key = (f.get("key") or "").strip()
        if not key:
            continue
        if key in STANDARD or key == OTP_FIELD or key.startswith("curodav."):
            raise EntryError("custom", f"{key} is a reserved field name")
        wanted[key] = (f.get("value") or "", bool(f.get("protected")))
    for key in [k for k in _strings(entry) if k not in STANDARD and k != OTP_FIELD and not k.startswith("curodav.") and k not in wanted]:
        _remove_string(entry, key)
    for key, (value, protected) in wanted.items():
        _set_string(entry, key, value, protected)
    if "tags" in data:
        _set(entry, "Tags", ";".join(dict.fromkeys(t.strip() for t in data.get("tags") or [] if t.strip())))
    times = entry.find("Times")
    expires = (data.get("expires") or "").strip()
    if "expires" not in data:
        pass
    elif expires:
        try:
            when = datetime.fromisoformat(expires).replace(tzinfo=timezone.utc)
        except ValueError:
            raise EntryError("expires", "The expiry date is not a date") from None
        _set(times, "Expires", "True")
        _set(times, "ExpiryTime", kdbx.encode_time(when))
    else:
        _set(times, "Expires", "False")
    parents = _parents(db)
    if parents.get(entry) is not group:
        parents[entry].remove(entry)
        group.append(entry)
        _touch(entry, location=True)
    _touch(entry)
    return ref(entry)


def set_field(db: kdbx.Database, uuid: str, key: str, value: str) -> bool:
    """One field changed from the entry's view window; the earlier version is kept in the history like any edit.
    Returns whether the stored value changed."""
    entry = find_entry(db, uuid)
    if entry is None:
        raise EntryError("entry", "This entry no longer exists")
    strings = _strings(entry)
    if key == "Title" and not value.strip():
        raise EntryError("title", "An entry needs a title")
    if not (key in ("Title", "UserName", "Password", "URL", "Notes") or (key in strings and key != OTP_FIELD and not key.startswith("curodav."))):
        raise EntryError("field", "That field cannot be changed here")
    if strings.get(key, ("", None))[0] == value:
        return False
    _keep_history(db, entry)
    _set_string(entry, key, value, strings.get(key, ("", key == "Password"))[1])
    _touch(entry)
    return True


def is_secret(db: kdbx.Database, uuid: str, key: str) -> bool:
    entry = find_entry(db, uuid)
    return entry is not None and (key == "Password" or _strings(entry).get(key, ("", False))[1])


def undo_field(db: kdbx.Database, uuid: str, key: str) -> None:
    """Puts back the value a field had before its last change, from the newest earlier version; the undone value stays in the history."""
    entry = find_entry(db, uuid)
    versions = entry.find("History").findall("Entry") if entry is not None and entry.find("History") is not None else []
    current = _strings(entry).get(key, ("", False))[0] if entry is not None else ""
    for old in reversed(versions):  # the newest earlier version whose value is not the current one
        value = _strings(old).get(key, ("", False))[0]
        if value != current:
            set_field(db, uuid, key, value)
            return
    raise EntryError("field", "There is nothing to undo")


def move_entry(db: kdbx.Database, uuid: str, space: str) -> bool:
    """Files an entry under a space's group ("" for no space). A move is not a change to the entry, so it keeps no history."""
    entry = find_entry(db, uuid)
    if entry is None:
        raise EntryError("entry", "This entry no longer exists")
    target = space_group(db, space) or _root_group(db)
    parents = _parents(db)
    if parents[entry] is target or _in_bin(db, entry, parents):
        return False
    parents[entry].remove(entry)
    target.append(entry)
    _touch(entry, location=True)
    return True


def bulk_edit(db: kdbx.Database, uuids: list[str], *, space: str | None = None, type_key: str | None = None,
              add_tags: list[str] | None = None, remove_tags: list[str] | None = None, types: list[dict] | None = None) -> int:
    """Changes several entries at once: the space, the type, tags to add and tags to remove. Returns how many entries changed.
    An entry whose content changes keeps its earlier version in the history."""
    add = [t.strip() for t in add_tags or [] if t.strip()]
    drop = {t.strip().lower() for t in remove_tags or [] if t.strip()}
    if type_key is not None and type_key not in {t["key"] for t in types or []}:
        raise EntryError("type", "That type does not exist")
    changed = 0
    for uuid in dict.fromkeys(uuids):
        entry = find_entry(db, uuid)
        if entry is None:
            continue
        mine = False
        tags = [t for t in (entry.findtext("Tags") or "").replace(",", ";").split(";") if t.strip()]
        new_tags = [t for t in tags if t.lower() not in drop] + [t for t in add if t.lower() not in {x.lower() for x in tags}]
        new_tags = list(dict.fromkeys(new_tags))
        current_type = _strings(entry).get(TYPE_FIELD, ("login", False))[0]
        content = new_tags != tags or (type_key is not None and type_key != current_type)
        if content:
            _keep_history(db, entry)
            _set(entry, "Tags", ";".join(new_tags))
            if type_key is not None:
                _set_string(entry, TYPE_FIELD, type_key)
            _touch(entry)
            mine = True
        if space is not None and move_entry(db, uuid, space):
            mine = True
        changed += 1 if mine else 0
    return changed


def delete_entries(db: kdbx.Database, uuids: list[str]) -> tuple[int, int]:
    """Moves entries to the recycle bin, or deletes those already there for good. Returns (binned, deleted)."""
    binned = deleted = 0
    for uuid in dict.fromkeys(uuids):
        if find_entry(db, uuid) is None:
            continue
        if delete_entry(db, uuid) == "binned":
            binned += 1
        else:
            deleted += 1
    return binned, deleted


def restore_entries(db: kdbx.Database, uuids: list[str]) -> int:
    count = 0
    for uuid in dict.fromkeys(uuids):
        try:
            restore_entry(db, uuid)
            count += 1
        except EntryError:
            continue
    return count


def delete_entry(db: kdbx.Database, uuid: str) -> str:
    """Moves an entry to the recycle bin, or deletes it for good when it is already there. Returns which happened."""
    entry = find_entry(db, uuid)
    if entry is None:
        raise EntryError("entry", "This entry no longer exists")
    parents = _parents(db)
    if _in_bin(db, entry, parents):
        parents[entry].remove(entry)
        deleted = db.root.find("./Root/DeletedObjects")
        if deleted is None:
            deleted = ET.SubElement(db.root.find("./Root"), "DeletedObjects")
        obj = ET.SubElement(deleted, "DeletedObject")
        ET.SubElement(obj, "UUID").text = entry.findtext("UUID")
        ET.SubElement(obj, "DeletionTime").text = kdbx.encode_time()
        return "deleted"
    bin_ = recycle_bin(db, create=True)
    _set(entry, "PreviousParentGroup", parents[entry].findtext("UUID"))
    parents[entry].remove(entry)
    bin_.append(entry)
    _touch(entry, location=True)
    return "binned"


def restore_entry(db: kdbx.Database, uuid: str) -> None:
    entry = find_entry(db, uuid)
    if entry is None or not _in_bin(db, entry):
        raise EntryError("entry", "This entry is not in the recycle bin")
    target = find_group(db, entry.findtext("PreviousParentGroup") or "") or _root_group(db)
    if _in_bin(db, target):
        target = _root_group(db)
    _parents(db)[entry].remove(entry)
    target.append(entry)
    _touch(entry, location=True)


def empty_bin(db: kdbx.Database) -> int:
    """Deletes everything in the recycle bin for good; returns how many entries went."""
    bin_ = recycle_bin(db)
    if bin_ is None:
        return 0
    parents = _parents(db)
    gone = [e for e in _entries(db) if _in_bin(db, e, parents)]
    for entry in gone:
        delete_entry(db, ref(entry))
    for group in list(bin_.findall("Group")):
        bin_.remove(group)
    return len(gone)


def history(db: kdbx.Database, uuid: str) -> list[dict]:
    entry = find_entry(db, uuid)
    if entry is None or entry.find("History") is None:
        return []
    rows = []
    for i, old in enumerate(entry.find("History").findall("Entry")):
        s = _strings(old)
        rows.append({"index": i, "title": s.get("Title", ("",))[0], "username": s.get("UserName", ("",))[0],
                     "modified": kdbx.decode_time(old.find("Times").findtext("LastModificationTime")) if old.find("Times") is not None else None})
    return list(reversed(rows))


def restore_version(db: kdbx.Database, uuid: str, index: int) -> None:
    """Brings back an earlier version of an entry, keeping the current one in the history first."""
    entry = find_entry(db, uuid)
    versions = entry.find("History").findall("Entry") if entry is not None and entry.find("History") is not None else []
    if not 0 <= index < len(versions):
        raise EntryError("version", "That version no longer exists")
    old = copy.deepcopy(versions[index])
    _keep_history(db, entry)
    for s in entry.findall("String"):
        entry.remove(s)
    for i, string_el in enumerate(old.findall("String")):
        entry.insert(i + 1, string_el)
    _set(entry, "Tags", old.findtext("Tags") or "")
    _touch(entry)


# ---------------------------------------------------------------- one-time codes

def totp(uri: str, at: float | None = None) -> dict | None:
    """The current code of an otpauth:// URI (RFC 6238) and the seconds it has left, or None for an invalid one."""
    try:
        parsed = urlparse(uri)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        raw = params["secret"].replace(" ", "").upper()
        key = base64.b32decode(raw + "=" * (-len(raw) % 8))
        period = int(params.get("period", 30))
        digits = int(params.get("digits", 6))
        algo = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}[params.get("algorithm", "SHA1").upper()]
    except (KeyError, ValueError, TypeError):
        return None
    if not key or period <= 0 or not 6 <= digits <= 10:
        return None
    now = time.time() if at is None else at
    counter = int(now // period)
    digest = hmac.new(key, struct.pack(">Q", counter), algo).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    label = unquote(parsed.path.lstrip("/"))
    return {"code": str(code).zfill(digits), "remaining": period - int(now % period), "period": period, "label": label}


# ---------------------------------------------------------------- generator

SYMBOLS = "!#$%&*+-=?@^_~.,:;"
_CONSONANTS, _VOWELS = "bcdfghjklmnprstvwz", "aeiou"


def generate(length: int = 20, lower: bool = True, upper: bool = True, digits: bool = True, symbols: bool = True, no_lookalikes: bool = True,
             min_digits: int = 1, min_symbols: int = 1, symbol_set: str = SYMBOLS, exclude: str = "") -> dict:
    """A random password from the chosen sets, with at least the asked number of digits and symbols and one of each other set.
    Returns the value and its entropy in bits, worked out from the pool it was drawn from."""
    length = max(8, min(int(length), 128))
    drop = set(exclude) | (LOOKALIKES if no_lookalikes else set())
    clean = lambda chars: "".join(dict.fromkeys(c for c in chars if c not in drop and not c.isspace()))  # noqa: E731
    sets = {"lower": clean(string.ascii_lowercase) if lower else "", "upper": clean(string.ascii_uppercase) if upper else "",
            "digits": clean(string.digits) if digits else "", "symbols": clean(symbol_set or SYMBOLS) if symbols else ""}
    sets = {k: v for k, v in sets.items() if v} or {"lower": clean(string.ascii_lowercase) or string.ascii_lowercase}
    need = {k: 1 for k in sets}
    if "digits" in sets:
        need["digits"] = max(1, min(int(min_digits), length // 2))
    if "symbols" in sets:
        need["symbols"] = max(1, min(int(min_symbols), length // 2))
    while sum(need.values()) > length:
        biggest = max(need, key=need.get)
        need[biggest] -= 1
    pool = "".join(sets.values())
    out = [secrets.choice(sets[k]) for k, n in need.items() for _ in range(n)]
    out += [secrets.choice(pool) for _ in range(length - len(out))]
    for i in range(len(out) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        out[i], out[j] = out[j], out[i]
    return {"value": "".join(out), "bits": int(length * math.log2(len(pool)))}


def memorable(words: int = 4, separator: str = "-", capitalize: bool = True, number: bool = True) -> dict:
    """A passphrase of made-up pronounceable words (consonant and vowel syllables), with its entropy in bits."""
    words = max(3, min(int(words), 10))
    syllable_bits = math.log2(len(_CONSONANTS) * len(_VOWELS))
    parts, bits = [], 0.0
    for _ in range(words):
        count = 2 + secrets.randbelow(2)
        word = "".join(secrets.choice(_CONSONANTS) + secrets.choice(_VOWELS) for _ in range(count))
        bits += count * syllable_bits + 1
        parts.append(word.capitalize() if capitalize else word)
    if number:
        parts[secrets.randbelow(len(parts))] += str(secrets.randbelow(100))
        bits += math.log2(100) + math.log2(words)
    return {"value": (separator if separator is not None else "-")[:3].join(parts), "bits": int(bits)}


def rating(bits: int) -> str:
    return "Weak" if bits < 60 else "Fair" if bits < 80 else "Strong" if bits < 110 else "Very strong"


def strength(password: str) -> int:
    """Rough entropy in bits from length and character classes; good enough to flag weak passwords, never shown as a promise."""
    if not password:
        return 0
    size = sum(n for s, n in ((string.ascii_lowercase, 26), (string.ascii_uppercase, 26), (string.digits, 10)) if any(c in s for c in password))
    size += 33 if any(not c.isalnum() for c in password) else 0
    unique = len(set(password))
    return int(min(len(password), unique * 2) * math.log2(max(size, 2)))


# ---------------------------------------------------------------- health

def health(db: kdbx.Database, now: datetime | None = None) -> dict:
    """Weak, reused, old and expired passwords, worked out in memory and never stored."""
    now = now or datetime.now(timezone.utc)
    parents = _parents(db)
    rows = [(summary(db, e, parents), _strings(e).get("Password", ("",))[0]) for e in _entries(db) if not _in_bin(db, e, parents)]
    by_password: dict[str, list[dict]] = {}
    for row, pw in rows:
        if pw:
            by_password.setdefault(hashlib.sha256(pw.encode()).hexdigest(), []).append(row)
    reused = [r for group in by_password.values() if len(group) > 1 for r in group]
    weak = [row for row, pw in rows if pw and strength(pw) < 60]
    old = [row for row, pw in rows if pw and row["modified"] and row["modified"] < now - timedelta(days=365)]
    expired = [row for row, _ in rows if row["expired"]]
    return {"weak": weak, "reused": reused, "old": old, "expired": expired, "total": len(rows),
            "fine": len(rows) - len({r["uuid"] for r in weak + reused + old + expired})}
