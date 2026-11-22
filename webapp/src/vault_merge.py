"""Merging two copies of one vault, for when the file was changed outside Curodav while it was open (features/accounts-vault.md).

Entries and groups are matched by UUID. An entry present on one side only is kept, unless the other side deleted it after
its last change. An entry on both sides keeps the newer version, and the older one is added to its history, so nothing is
lost. A group takes the newer name and position. Deletions travel through `DeletedObjects`, as in KeePass itself.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

from . import vault_kdbx as kdbx


def _modified(el: ET.Element):
    times = el.find("Times")
    return kdbx.decode_time(times.findtext("LastModificationTime") if times is not None else None)


def _located(el: ET.Element):
    times = el.find("Times")
    return kdbx.decode_time(times.findtext("LocationChanged") if times is not None else None)


def _index(db: kdbx.Database):
    """Every group and entry by UUID with its parent group, history copies left out."""
    groups, entries = {}, {}

    def walk(group: ET.Element, parent: ET.Element | None) -> None:
        groups[group.findtext("UUID")] = (group, parent)
        for entry in group.findall("Entry"):
            entries[entry.findtext("UUID")] = (entry, group)
        for child in group.findall("Group"):
            walk(child, group)

    walk(db.root.find("./Root/Group"), None)
    return groups, entries


def _deleted(db: kdbx.Database) -> dict[str, object]:
    out = {}
    for obj in db.root.findall("./Root/DeletedObjects/DeletedObject"):
        out[obj.findtext("UUID")] = kdbx.decode_time(obj.findtext("DeletionTime"))
    return out


def _history(entry: ET.Element) -> ET.Element:
    history = entry.find("History")
    if history is None:
        history = ET.SubElement(entry, "History")
    return history


def _snapshot(entry: ET.Element) -> ET.Element:
    copy_ = copy.deepcopy(entry)
    old = copy_.find("History")
    if old is not None:
        copy_.remove(old)
    return copy_


def _same(a: ET.Element, b: ET.Element) -> bool:
    return ET.tostring(_snapshot(a)) == ET.tostring(_snapshot(b))


def _drop(entry: ET.Element, parent: ET.Element, local: kdbx.Database, uuid: str, when) -> None:
    parent.remove(entry)
    deleted = local.root.find("./Root/DeletedObjects")
    if deleted is None:
        deleted = ET.SubElement(local.root.find("./Root"), "DeletedObjects")
    obj = ET.SubElement(deleted, "DeletedObject")
    ET.SubElement(obj, "UUID").text = uuid
    ET.SubElement(obj, "DeletionTime").text = kdbx.encode_time(when) if when else kdbx.encode_time()


def merge(local: kdbx.Database, remote: kdbx.Database) -> dict[str, int]:
    """Brings the changes of `remote` into `local`; returns counts of what came in (added, updated, removed, kept)."""
    counts = {"added": 0, "updated": 0, "removed": 0, "kept": 0}
    l_groups, l_entries = _index(local)
    r_groups, r_entries = _index(remote)
    l_deleted, r_deleted = _deleted(local), _deleted(remote)

    # groups first, parents before children
    for uuid, (group, parent) in r_groups.items():
        if parent is None or uuid in l_groups or uuid in l_deleted:
            if uuid in l_groups and parent is not None:
                mine = l_groups[uuid][0]
                if (_modified(group) or 0) and (_modified(mine) is None or _modified(group) > _modified(mine)):
                    mine.find("Name").text = group.findtext("Name") or mine.findtext("Name")
            continue
        target = l_groups.get(parent.findtext("UUID"), (local.root.find("./Root/Group"), None))[0]
        new = copy.deepcopy(group)
        for child in list(new):
            if child.tag in ("Group", "Entry"):
                new.remove(child)
        target.append(new)
        l_groups[uuid] = (new, target)

    for uuid, (entry, group) in r_entries.items():
        if uuid in l_deleted and (_modified(entry) is None or l_deleted[uuid] is None or _modified(entry) <= l_deleted[uuid]):
            continue
        target = l_groups.get(group.findtext("UUID"), (local.root.find("./Root/Group"), None))[0]
        if uuid not in l_entries:
            target.append(copy.deepcopy(entry))
            counts["added"] += 1
            continue
        mine, my_group = l_entries[uuid]
        theirs_newer = (_modified(entry) or 0) and (_modified(mine) is None or _modified(entry) > _modified(mine))
        if theirs_newer and not _same(entry, mine):
            keep = _snapshot(mine)
            position = list(my_group).index(mine)
            my_group.remove(mine)
            fresh = copy.deepcopy(entry)
            _history(fresh).append(keep)
            my_group.insert(position, fresh)
            mine = fresh
            counts["updated"] += 1
        elif not theirs_newer and not _same(entry, mine) and _modified(entry) is not None:
            existing = [ET.tostring(h) for h in _history(mine).findall("Entry")]
            theirs = _snapshot(entry)
            if ET.tostring(theirs) not in existing:
                _history(mine).append(theirs)
                counts["kept"] += 1
        moved = _located(entry)
        if moved is not None and (_located(mine) is None or moved > _located(mine)) and l_groups.get(group.findtext("UUID")):
            new_parent = l_groups[group.findtext("UUID")][0]
            current = next((g for g in l_groups.values() if mine in list(g[0])), None)
            if current and current[0] is not new_parent:
                current[0].remove(mine)
                new_parent.append(mine)

    for uuid, when in r_deleted.items():
        if uuid in l_entries:
            entry, group = l_entries[uuid]
            if _modified(entry) is None or when is None or _modified(entry) <= when:
                if entry in list(group):
                    _drop(entry, group, local, uuid, when)
                    counts["removed"] += 1
    return counts
