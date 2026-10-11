"""The app's one source of "now" and "today".

Code that needs the current date or time calls these instead of
`date.today()` / `datetime.now()`, so tests can set the date with
`set_override` instead of depending on the real clock. Existing call sites
move over as the feature areas are reworked (see the testing and backend
conventions); new code uses this module from the start.
"""

from datetime import date, datetime, timezone

_override: datetime | None = None


def set_override(moment: datetime | None) -> None:
    """Pin the clock to `moment` (tests only); None restores the real clock."""
    global _override
    _override = moment


def now() -> datetime:
    return _override if _override is not None else datetime.now(timezone.utc)


def today() -> date:
    """Today on the user's calendar: the date in the process's configured time zone, not the UTC date."""
    return now().astimezone().date()


def local_now() -> datetime:
    """A naive datetime in the process's configured time zone."""
    return now().astimezone().replace(tzinfo=None)


def local_hour() -> int:
    if _override is not None:
        return _override.hour
    return now().astimezone().hour
