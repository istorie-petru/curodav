"""The views a page offers in the header bar's switch: one list per page family, with the active one marked."""

from __future__ import annotations

from urllib.parse import quote


def _suffix(label: str, sep: str = "?") -> str:
    return f"{sep}label={quote(label)}" if label else ""


def header_views(kind: str, active: str, label: str = "", day: str = "", agenda: bool = True) -> list[dict]:
    if kind == "calendar":
        items = [
            ("fourweek", "4 weeks", "/calendar/fourweek" + _suffix(label)),
            ("day", "Day", (f"/calendar/day/{day}" if day else "/calendar/day") + _suffix(label)),
            ("plan", "Plan", "/calendar/week" + _suffix(label)),
        ]
    elif kind == "tasks":
        items = [("list", "List", "/tasks"), ("board", "Board", "/tasks/board"), ("habits", "Habits", "/habits")]
    elif kind == "scope":
        base = label or "/"
        items = [("overview", "Overview", base)]
        if agenda:
            items.append(("agenda", "Agenda", f"{base}?view=agenda"))
        items.append(("board", "Board", f"{base}?view=board"))
    else:
        return []
    return [{"key": key, "label": text, "url": url, "active": key == active} for key, text, url in items]


SETTINGS_GROUPS = [
    {"name": "Account", "icon": "user-check", "items": [("Profile", "/settings/your-profile"), ("Notifications", "/settings/notifications")]},
    {"name": "Preferences", "icon": "sun", "items": [("General", "/settings/general"), ("Appearance", "/settings/appearance")]},
    {"name": "Organise", "icon": "tag", "items": [("Shelves", "/settings/labels"), ("Tags", "/settings/tags"), ("Spaces", "/settings/groups")]},
    {"name": "Modules", "icon": "file-text", "items": [("Notebook", "/settings/notebook"), ("Finance", "/settings/finance-accounts"), ("Calendar", "/settings/calendar")]},
    {"name": "System", "icon": "database", "items": [("Data", "/settings/data-maintenance"), ("Published lists", "/published-lists"), ("Logs", "/settings/logs")]},
]


def current_settings_groups() -> list[dict]:
    """SETTINGS_GROUPS with the Settings entries of the enabled modules added under Modules."""
    from . import modules

    extra = modules.settings_items()
    return [{**g, "items": [*g["items"], *extra]} if g["name"] == "Modules" else g for g in SETTINGS_GROUPS]


def settings_group(request) -> dict | None:
    """The settings group the request's page belongs to, with its views; None outside Settings."""
    try:
        path = request.scope.get("path", "")
    except AttributeError:
        return None
    for group in current_settings_groups():
        for _, url in group["items"]:
            if path == url or path.startswith(url + "/"):
                views = [{"key": url, "label": text, "url": url, "active": url == _owner(group, path)} for text, url in group["items"]]
                return {"title": group["name"], "views": views}
    return None


def _owner(group: dict, path: str) -> str:
    return next(url for _, url in group["items"] if path == url or path.startswith(url + "/"))
