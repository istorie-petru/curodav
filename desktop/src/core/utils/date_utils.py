from datetime import date, datetime, timedelta


def today_str() -> str:
    return date.today().isoformat()


def days_from_now(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def parse_date_token(token: str) -> str | None:
    token = token.lower().removeprefix("@")
    if token == "today":
        return today_str()
    if token == "tomorrow":
        return days_from_now(1)
    if token == "next-week":
        return days_from_now(7)
    try:
        return date.fromisoformat(token).isoformat()
    except (ValueError, TypeError):
        return None


def overdue_days(due_at: str | None) -> int:
    if not due_at:
        return 0
    try:
        due = date.fromisoformat(due_at)
        return max(0, (date.today() - due).days)
    except (ValueError, TypeError):
        return 0


_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def relative_date_label(due_at: str | None) -> str:
    """Human-friendly relative label for a due/start date string, falling
    back to an absolute "Mon DD" (or "Mon DD, YYYY" across year boundaries)
    once relative phrasing stops being useful (more than a week out in
    either direction) -- table/board cells default to this instead of the
    raw ISO string.
    """
    if not due_at:
        return ""
    try:
        d = date.fromisoformat(due_at[:10])
    except (ValueError, TypeError):
        return due_at

    today = date.today()
    delta = (d - today).days

    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta == -1:
        return "Yesterday"
    if 1 < delta <= 6:
        return _WEEKDAY_NAMES[d.weekday()]
    if -6 <= delta < -1:
        return f"{-delta}d overdue"
    if 1 < delta <= 30 and delta > 6:
        weeks = round(delta / 7)
        return f"In {weeks}w" if weeks > 1 else "In 1w"

    fmt = "%b %d" if d.year == today.year else "%b %d, %Y"
    return d.strftime(fmt)
