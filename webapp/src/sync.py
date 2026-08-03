"""Pulls the current state of Radicale's calendar/tasks/contacts
collections into the local SQLite cache (db.py).

v1 is a full-refresh poll, not delta sync: every run re-lists everything
from Radicale and upserts it, then deletes any local row whose uid no
longer exists on the server. That's the right tradeoff for a personal,
low-item-count self-hosted setup -- CalDAV's `sync-collection` REPORT
(true delta sync, only fetch what changed since a stored sync-token) is a
legitimate later upgrade once "full refresh every poll" is actually shown
to be slow, not before. Writes made through this app's own API (routers/)
call the bridge directly and update the cache inline, so the poll here
mainly exists to pick up changes made by *other* CalDAV/CardDAV clients
(desktop's bridge daemon, a phone's native Calendar/Contacts app).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time

from . import db
from .caldav_bridge import CalDavBridge

logger = logging.getLogger(__name__)


_MIGRATION_KEY = "contacts_two_addressbooks_migrated_v1"


def _run_addressbook_migration(bridge: CalDavBridge, conn: sqlite3.Connection) -> None:
    """One-time migration from arbitrary addressbooks to exactly two
    (Active='contacts', Archived='contacts-archived').  Guarded by an
    app_meta flag so it only runs once even if full_refresh is called
    multiple times.

    For each extra addressbook:
      1. Data-layer: db.migrate_addressbooks_to_two reassigns contacts
         to Active and adds the old book's name as a tag.
      2. CardDAV: for each affected contact, delete the vCard from the
         old collection and save it into Active (pick up the tag update).
      3. Delete the old CardDAV collection.
      4. Delete the old addressbooks row from the local DB.

    Safe to re-run if interrupted: migrate_addressbooks_to_two is
    idempotent (contacts already in Active are not re-processed), and
    delete_addressbook_collection is tolerant of a missing collection."""
    if db.get_app_meta(conn, _MIGRATION_KEY) == "1":
        return  # Already done

    # Snapshot the "extra" addressbooks *before* the data-layer migration
    # changes their contacts' addressbook_path -- we need the old uid to
    # move the vCards.
    _KEEP = {db.DEFAULT_ADDRESSBOOK_UID, db.ARCHIVED_ADDRESSBOOK_UID}
    extra = [ab for ab in db.list_addressbooks(conn) if ab["uid"] not in _KEEP]
    if not extra:
        # Nothing to migrate -- mark done and return.
        db.set_app_meta(conn, _MIGRATION_KEY, "1")
        return

    # Gather per-addressbook contact data *before* the data-layer move,
    # since we need the old addressbook_path to reach the right CardDAV
    # collection for deletion.
    contact_snapshots: dict[str, list[dict]] = {}
    for ab in extra:
        contacts = db.list_contacts(conn, addressbook_path=ab["uid"])
        contact_snapshots[ab["uid"]] = contacts

    # Step 1: data-layer migration (tags + addressbook_path rewrite).
    db.migrate_addressbooks_to_two(conn)

    # Step 2 + 3: CardDAV moves and old-collection deletion.
    for ab in extra:
        old_uid = ab["uid"]
        for contact in contact_snapshots[old_uid]:
            try:
                # Delete from old CardDAV collection.
                bridge.delete_contact(contact["uid"], old_uid)
            except Exception:
                logger.exception(
                    "Migration: failed to delete contact %r from old addressbook %r; "
                    "skipping -- it may already be absent or will be cleaned up on "
                    "next sync",
                    contact["uid"],
                    old_uid,
                )
            try:
                # Re-fetch the updated contact row (now has the new tag)
                # and push it into the Active collection.
                updated = db.get_contact(conn, contact["uid"])
                if updated:
                    bridge.save_contact_row(updated)
            except Exception:
                logger.exception(
                    "Migration: failed to save contact %r into Active addressbook; "
                    "will be picked up on next full sync",
                    contact["uid"],
                )
        try:
            bridge.delete_addressbook_collection(old_uid)
        except Exception:
            logger.exception(
                "Migration: failed to delete old CardDAV addressbook collection %r; "
                "skipping -- it may already be absent",
                old_uid,
            )
        db.delete_contacts_by_addressbook(conn, old_uid)  # already moved, belt-and-suspenders
        db.delete_addressbook(conn, old_uid)

    db.set_app_meta(conn, _MIGRATION_KEY, "1")
    logger.info(
        "contacts_two_addressbooks_migrated_v1: migrated %d addressbook(s): %s",
        len(extra),
        [ab["name"] for ab in extra],
    )


def full_refresh(bridge: CalDavBridge, conn: sqlite3.Connection) -> None:
    db.ensure_default_calendar(conn)
    db.ensure_default_task_list(conn)
    db.ensure_default_addressbook(conn)
    db.ensure_default_archived_addressbook(conn)

    # One-time migration: collapse arbitrary addressbooks into Active +
    # Archived, tagging contacts with their old addressbook name.  Runs
    # before the contact sync loop so the sync loop only sees the two
    # canonical collections.
    _run_addressbook_migration(bridge, conn)

    # Each collection is refreshed independently, and a failure in one
    # (most commonly: Radicale's REPORT handler 500ing because *some*
    # item in that specific collection is unparseable -- see
    # caldav_bridge.py's _get_by_uid_direct docstring for why listing
    # can't route around that the way single-object reads now do) no
    # longer aborts the whole refresh. Previously one broken calendar
    # meant tasks and contacts silently stopped syncing too, and -- worse
    # -- since this same function also runs synchronously at startup
    # (main.py), it meant the *entire app* refused to boot until that one
    # object was found and removed by hand.
    seen_uids: set[str] = set()
    for calendar in db.list_calendars(conn):
        try:
            rows = bridge.list_event_rows(calendar["uid"])
        except Exception:
            logger.exception(
                "Failed to sync calendar %r; leaving its cached events as-is "
                "for this refresh (likely one unparseable item on the server "
                "-- see README's troubleshooting notes)",
                calendar["uid"],
            )
            seen_uids |= set(db.all_event_uids_in_calendar(conn, calendar["uid"]))
            continue
        for row in rows:
            db.upsert_event(conn, row)
            seen_uids.add(row["uid"])
    for stale_uid in db.all_event_uids(conn) - seen_uids:
        db.delete_event(conn, stale_uid)

    # Multiple task lists -- same per-collection failure isolation as
    # calendars above (one bad list's REPORT 500 shouldn't stop syncing
    # any other list, or contacts).
    seen_uids = set()
    for task_list in db.list_task_lists(conn):
        try:
            rows = bridge.list_task_rows(task_list["uid"])
        except Exception:
            logger.exception(
                "Failed to sync task list %r; leaving its cached tasks as-is for this refresh",
                task_list["uid"],
            )
            seen_uids |= db.all_task_uids_in_list(conn, task_list["uid"])
            continue
        for row in rows:
            db.upsert_task(conn, row)
            seen_uids.add(row["uid"])
    for stale_uid in db.all_task_uids(conn) - seen_uids:
        db.delete_task(conn, stale_uid)

    # Multiple address books, same pattern.
    seen_uids = set()
    for addressbook in db.list_addressbooks(conn):
        try:
            rows = bridge.list_contact_rows(addressbook["uid"])
        except Exception:
            logger.exception(
                "Failed to sync address book %r; leaving its cached contacts as-is for this refresh",
                addressbook["uid"],
            )
            seen_uids |= {
                c["uid"] for c in db.list_contacts(conn, addressbook_path=addressbook["uid"])
            }
            continue
        for row in rows:
            db.upsert_contact(conn, row)
            seen_uids.add(row["uid"])
    for stale_uid in db.all_contact_uids(conn) - seen_uids:
        db.delete_contact(conn, stale_uid)


def run_periodic(
    bridge: CalDavBridge,
    db_path,
    interval_seconds: int,
    stop_event: threading.Event,
) -> None:
    """Runs in a background thread (see main.py's startup hook). Opens its
    own SQLite connection -- sqlite3 connections aren't safe to share
    across threads with FastAPI's request-handling threadpool."""
    while not stop_event.is_set():
        try:
            with db.connect(db_path) as conn:
                full_refresh(bridge, conn)
        except Exception:
            logger.exception("Background Radicale sync failed; will retry next interval")
        stop_event.wait(interval_seconds)


def start_background_sync(
    bridge: CalDavBridge, db_path, interval_seconds: int
) -> tuple[threading.Thread, threading.Event]:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_periodic,
        args=(bridge, db_path, interval_seconds, stop_event),
        daemon=True,
        name="radicale-sync",
    )
    thread.start()
    return thread, stop_event
