"""Talks to the self-hosted Radicale server: CalDAV (events/tasks) via the
`caldav` library, CardDAV (contacts) hand-rolled with `httpx` -- the
`caldav` PyPI package (3.2.1 as of this writing) only implements CalDAV,
not CardDAV/addressbooks, confirmed by inspecting its public API before
writing this. CardDAV's basic operations (MKCOL with an addressbook
resourcetype, PUT/GET/DELETE a .vcf, PROPFIND depth 1 for etags) are
simple enough that hand-rolling them is less risk than depending on an
unmaintained third-party addressbook library.

Radicale is the source of truth throughout this module -- every write goes
straight to it; nothing here caches. sync.py is the layer that mirrors
these results into the local SQLite cache db.py serves reads from.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse as _urlparse
from xml.etree import ElementTree as ET

import caldav
import httpx
import vobject
from caldav.lib.error import NotFoundError, PutError, ReportError

from .config import Settings
from .ical_rows import event_row_to_ical, ical_to_event_row, ical_to_task_row, task_row_to_ical
from .vcard_rows import contact_row_to_vcard, vcard_to_contact_row

_DAV_NS = {"d": "DAV:"}


class CalDavBridge:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = caldav.DAVClient(
            url=settings.radicale_base_url,
            username=settings.radicale_username,
            password=settings.radicale_password,
        )
        self.principal = self.client.principal()
        # Multi-calendar: lazily-populated cache of CalDAV Calendar objects
        # keyed by collection path ("calendar", "work", ...). Each is a
        # real, separate CalDAV collection -- db.py's `calendars` table
        # only adds local name/color metadata on top.
        self._event_calendars: dict[str, caldav.Calendar] = {}
        # Multiple task lists / address books, added 2026-07-31 -- same
        # lazily-populated-dict pattern as `_event_calendars` above, keyed
        # by `list_path`/`addressbook_path` (db.py's `task_lists`/
        # `addressbooks` tables). `settings.tasks_collection`/
        # `contacts_collection` are only the *default* list/addressbook's
        # collection name now (still created eagerly below so a fresh
        # install has somewhere to put the first task/contact without the
        # UI needing to create a list first).
        self._task_calendars: dict[str, caldav.Calendar] = {}
        self._addressbooks: dict[str, CardDavClient] = {}
        self._task_calendar(settings.tasks_collection)
        self._addressbook(settings.contacts_collection)

    def _get_or_create_calendar(
        self, cal_id: str, component_set: list[str] | None = None
    ) -> caldav.Calendar:
        cal = self.principal.calendar(cal_id=cal_id)
        try:
            cal.get_display_name()
            return cal
        except NotFoundError:
            kwargs: dict[str, Any] = {"cal_id": cal_id, "name": cal_id.capitalize()}
            if component_set:
                kwargs["supported_calendar_component_set"] = component_set
            return self.principal.make_calendar(**kwargs)

    def _event_calendar(self, calendar_path: str) -> caldav.Calendar:
        if calendar_path not in self._event_calendars:
            self._event_calendars[calendar_path] = self._get_or_create_calendar(calendar_path)
        return self._event_calendars[calendar_path]

    @staticmethod
    def _object_url(collection: caldav.Calendar, uid: str) -> str:
        base = str(collection.url)
        if not base.endswith("/"):
            base += "/"
        return f"{base}{uid}.ics"

    def _get_by_uid_direct(
        self, collection: caldav.Calendar, uid: str, cls: type
    ) -> caldav.CalendarObjectResource:
        """Fetch one object by the URL Radicale (and every CalDAV server
        this app has been tested against) deterministically gives it --
        `{collection}/{uid}.ics`, confirmed from Radicale's own request
        log ("PUT request for '/devuser/calendar/<uid>.ics'") -- via a
        plain GET, instead of `Calendar.event_by_uid`/`.todo_by_uid`'s
        REPORT-with-filter search.

        This matters because Radicale's REPORT handler (app/report.py)
        parses *every* item in the collection to evaluate the filter, and
        wraps that in a bare `except Exception: raise RuntimeError(...)`
        with no per-item recovery -- one legacy/foreign/corrupted .ics
        anywhere in the collection (e.g. from a previous bug, a manual
        edit, an import from another CalDAV client) makes the *entire*
        REPORT 500, including a plain "does this UID exist" lookup for a
        completely unrelated object. A create/update/delete of one event
        should never depend on every *other* event in the calendar being
        parseable. A plain GET only touches the one URL requested, so it
        can't be brought down by an unrelated broken sibling.

        Falls back to the REPORT-based lookup if the server (unlike
        Radicale) doesn't use UID-based filenames, or if the direct GET
        itself 404s in a way that still leaves open whether the object
        exists under a different URL -- `CalendarObjectResource.load()`
        already does its own multiget/re-search fallback for that case
        before finally raising NotFoundError."""
        obj = cls(self.client, url=self._object_url(collection, uid), parent=collection)
        obj.load()
        return obj

    def ensure_calendar(self, calendar_path: str) -> None:
        """Public wrapper so routers/calendars.py can create the real
        CalDAV collection for a new calendar without reaching into the
        private `_event_calendar`."""
        self._event_calendar(calendar_path)

    def delete_calendar_collection(self, calendar_path: str) -> None:
        """Deletes the actual CalDAV collection and everything in it. The
        caller (routers/calendar.py) is responsible for also removing the
        `calendars` row and any cached `events` rows for this path."""
        self._event_calendar(calendar_path).delete()
        self._event_calendars.pop(calendar_path, None)

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #

    def list_event_rows(self, calendar_path: str) -> list[dict[str, Any]]:
        # `.events()` issues a plain calendar-query REPORT for full current
        # state every call. The generic `.objects()` alias is sync-token
        # based (meant for incremental delta sync) and was observed to
        # return stale/deleted references when called repeatedly against
        # the same long-lived Calendar instance -- not what a naive
        # "get everything right now" poll (sync.py) wants.
        rows = []
        for obj in self._event_calendar(calendar_path).events():
            row = self._event_obj_to_row(obj, calendar_path)
            if row:
                rows.append(row)
        return rows

    def save_event_row(self, row: dict[str, Any]) -> dict[str, Any]:
        calendar_path = row.get("calendar_path") or "calendar"
        cal = self._event_calendar(calendar_path)
        ics = event_row_to_ical(row).decode()
        try:
            obj = self._get_by_uid_direct(cal, row["uid"], caldav.Event)
            obj.data = ics
            obj.save()
        except NotFoundError:
            try:
                obj = cal.save_event(ical=ics)
            except PutError:
                # The direct lookup said "not found" but the server rejected
                # the create as a conflict anyway -- something else already
                # created this UID between our lookup and our write (e.g.
                # a second near-simultaneous save of the same object, or a
                # server-side consistency lag right after a prior write).
                # Retry as an update rather than surfacing a 500: whatever
                # created it, our version is the one that should win since
                # it's what the caller (a form submit, a drag-drop, a
                # Schedule regeneration) just explicitly asked to save.
                obj = self._get_by_uid_direct(cal, row["uid"], caldav.Event)
                obj.data = ics
                obj.save()
        return self._event_obj_to_row(obj, calendar_path)

    def delete_event(self, uid: str, calendar_path: str) -> None:
        try:
            self._get_by_uid_direct(self._event_calendar(calendar_path), uid, caldav.Event).delete()
        except NotFoundError:
            pass

    @staticmethod
    def _event_obj_to_row(
        obj: caldav.CalendarObjectResource, calendar_path: str
    ) -> dict[str, Any] | None:
        component = obj.icalendar_component
        if component is None or component.name != "VEVENT":
            return None
        row = ical_to_event_row(component)
        row["href"] = str(obj.url)
        row["etag"] = obj.etag
        row["calendar_path"] = calendar_path
        return row

    # ------------------------------------------------------------------ #
    # Tasks (multiple lists -- see __init__'s comment)
    # ------------------------------------------------------------------ #

    def _task_calendar(self, list_path: str) -> caldav.Calendar:
        if list_path not in self._task_calendars:
            self._task_calendars[list_path] = self._get_or_create_calendar(
                list_path, component_set=["VTODO"]
            )
        return self._task_calendars[list_path]

    def ensure_task_list(self, list_path: str) -> None:
        """Public wrapper so routers/task_lists.py can create the real
        CalDAV VTODO collection for a new task list -- same role
        ensure_calendar plays for events."""
        self._task_calendar(list_path)

    def delete_task_list_collection(self, list_path: str) -> None:
        self._task_calendar(list_path).delete()
        self._task_calendars.pop(list_path, None)

    def list_task_rows(self, list_path: str) -> list[dict[str, Any]]:
        rows = []
        for obj in self._task_calendar(list_path).todos(include_completed=True):
            row = self._task_obj_to_row(obj, list_path)
            if row:
                rows.append(row)
        return rows

    def save_task_row(self, row: dict[str, Any]) -> dict[str, Any]:
        list_path = row.get("list_path") or "tasks"
        cal = self._task_calendar(list_path)
        ics = task_row_to_ical(row).decode()
        try:
            obj = self._get_by_uid_direct(cal, row["uid"], caldav.Todo)
            obj.data = ics
            obj.save()
        except NotFoundError:
            try:
                obj = cal.save_todo(ical=ics)
            except PutError:
                # Same race as save_event_row -- see its comment.
                obj = self._get_by_uid_direct(cal, row["uid"], caldav.Todo)
                obj.data = ics
                obj.save()
        return self._task_obj_to_row(obj, list_path)

    def delete_task(self, uid: str, list_path: str = "tasks") -> None:
        try:
            self._get_by_uid_direct(self._task_calendar(list_path), uid, caldav.Todo).delete()
        except NotFoundError:
            pass

    @staticmethod
    def _task_obj_to_row(obj: caldav.CalendarObjectResource, list_path: str) -> dict[str, Any] | None:
        component = obj.icalendar_component
        if component is None or component.name != "VTODO":
            return None
        row = ical_to_task_row(component)
        row["href"] = str(obj.url)
        row["etag"] = obj.etag
        row["calendar_path"] = "tasks"
        row["list_path"] = list_path
        return row

    # ------------------------------------------------------------------ #
    # Contacts (multiple address books -- see __init__'s comment)
    # ------------------------------------------------------------------ #

    def _addressbook(self, addressbook_path: str) -> "CardDavClient":
        if addressbook_path not in self._addressbooks:
            client = CardDavClient(self.settings, addressbook_path)
            client.ensure_collection()
            self._addressbooks[addressbook_path] = client
        return self._addressbooks[addressbook_path]

    def ensure_addressbook(self, addressbook_path: str) -> None:
        """Public wrapper so routers/addressbooks.py can create the real
        CardDAV collection for a new address book."""
        self._addressbook(addressbook_path)

    def delete_addressbook_collection(self, addressbook_path: str) -> None:
        self._addressbook(addressbook_path).delete_collection()
        self._addressbooks.pop(addressbook_path, None)

    def list_contact_rows(self, addressbook_path: str) -> list[dict[str, Any]]:
        client = self._addressbook(addressbook_path)
        rows = []
        for href, etag in client.list_resources():
            text = client.get(href)
            if text is None:
                continue
            try:
                card = vobject.readOne(text)
            except Exception:
                continue
            row = vcard_to_contact_row(card)
            row["href"] = href
            row["etag"] = etag
            row["addressbook_path"] = addressbook_path
            rows.append(row)
        return rows

    def save_contact_row(self, row: dict[str, Any]) -> dict[str, Any]:
        addressbook_path = row.get("addressbook_path") or "contacts"
        client = self._addressbook(addressbook_path)
        vcard_text = contact_row_to_vcard(row)
        href = client.put(row["uid"], vcard_text, etag=row.get("etag"))
        row = dict(row)
        row["href"] = href
        row["addressbook_path"] = addressbook_path
        return row

    def delete_contact(self, uid: str, addressbook_path: str = "contacts") -> None:
        self._addressbook(addressbook_path).delete(uid)


class CardDavClient:
    """Minimal CardDAV client: MKCOL (with addressbook resourcetype),
    PROPFIND depth 1 (listing + etags), GET, PUT, DELETE. Verified against
    a real local Radicale instance during development -- see
    webapp/tests/test_caldav_bridge.py."""

    def __init__(self, settings: Settings, collection: str | None = None) -> None:
        self._base = settings.radicale_base_url.rstrip("/") + "/"
        # `collection` is the addressbook's own path segment
        # (`addressbooks.uid` in db.py) -- defaults to the configured
        # single collection for any caller that still constructs this
        # directly without one (there shouldn't be any left in this
        # codebase, but a default here is a cheap safety net).
        self._collection = collection or settings.contacts_collection
        self._auth = (settings.radicale_username, settings.radicale_password)
        self._collection_url = f"{self._base}{self._collection}/"

    def ensure_collection(self) -> None:
        body = """<?xml version="1.0" encoding="utf-8"?>
<D:mkcol xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:carddav">
  <D:set>
    <D:prop>
      <D:resourcetype><D:collection/><C:addressbook/></D:resourcetype>
      <D:displayname>Contacts</D:displayname>
    </D:prop>
  </D:set>
</D:mkcol>"""
        resp = httpx.request(
            "MKCOL",
            self._collection_url,
            auth=self._auth,
            content=body,
            headers={"Content-Type": "application/xml"},
        )
        # 201 = created, 405/409 = already exists -- both fine.
        if resp.status_code not in (201, 405, 409):
            resp.raise_for_status()

    def list_resources(self) -> list[tuple[str, str | None]]:
        body = """<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:">
  <D:prop><D:getetag/></D:prop>
</D:propfind>"""
        resp = httpx.request(
            "PROPFIND",
            self._collection_url,
            auth=self._auth,
            content=body,
            headers={"Content-Type": "application/xml", "Depth": "1"},
        )
        resp.raise_for_status()
        tree = ET.fromstring(resp.text)
        results = []
        for response in tree.findall("d:response", _DAV_NS):
            href = response.findtext("d:href", namespaces=_DAV_NS)
            if href is None or href.rstrip("/") == self._collection_url_path():
                continue
            if not href.endswith(".vcf"):
                continue
            etag = response.findtext(".//d:getetag", namespaces=_DAV_NS)
            results.append((href, etag))
        return results

    def _collection_url_path(self) -> str:
        return _urlparse(self._collection_url).path.rstrip("/")

    def get(self, href: str) -> str | None:
        # `href` from PROPFIND is already an absolute path from the server
        # root (e.g. "/devuser/contacts/x.vcf") -- join it against the
        # origin only. Joining against `self._base` (which already
        # includes "/devuser/") would double that segment.
        url = href if href.startswith("http") else self._origin() + href
        resp = httpx.get(url, auth=self._auth)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def _origin(self) -> str:
        parsed = _urlparse(self._base)
        return f"{parsed.scheme}://{parsed.netloc}"

    def put(self, uid: str, vcard_text: str, etag: str | None = None) -> str:
        url = f"{self._collection_url}{uid}.vcf"
        headers = {"Content-Type": "text/vcard"}
        if etag:
            headers["If-Match"] = etag
        resp = httpx.put(url, auth=self._auth, content=vcard_text, headers=headers)
        resp.raise_for_status()
        return url

    def delete(self, uid: str) -> None:
        url = f"{self._collection_url}{uid}.vcf"
        resp = httpx.delete(url, auth=self._auth)
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()

    def delete_collection(self) -> None:
        """Deletes the whole addressbook collection and everything in it --
        used by CalDavBridge.delete_addressbook_collection when a user
        deletes an address book (routers/addressbooks.py). The caller is
        responsible for also removing the local `addressbooks` row and any
        cached `contacts` rows, same division of responsibility as
        delete_calendar_collection/delete_events_by_calendar."""
        resp = httpx.delete(self._collection_url, auth=self._auth)
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()
