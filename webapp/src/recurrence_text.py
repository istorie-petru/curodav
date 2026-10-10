"""Plain-language phrasing for an RRULE string ("Every 2 weeks on Monday, until 12 Dec 2026").

Pure and clock-free. Feature notes: curodav-notes/documentation/features/recurrence-display.md.
"""

from datetime import date

_UNITS = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}
_SIMPLE = {"DAILY": "Daily", "WEEKLY": "Weekly", "MONTHLY": "Monthly", "YEARLY": "Yearly"}
_DAYS = {"MO": "Monday", "TU": "Tuesday", "WE": "Wednesday", "TH": "Thursday",
         "FR": "Friday", "SA": "Saturday", "SU": "Sunday"}
_ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _parse(rrule: str) -> dict[str, str]:
    return {k.upper(): v for k, v in (p.split("=", 1) for p in rrule.split(";") if "=" in p)}


def _end_phrase(parts: dict[str, str]) -> str:
    until = parts.get("UNTIL", "")
    if until:
        digits = until.replace("-", "")[:8]
        try:
            d = date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
            return f", until {d.day} {d.strftime('%b %Y')}"
        except ValueError:
            return ""
    count = parts.get("COUNT", "")
    if count.isdigit():
        n = int(count)
        return f", {n} time{'s' if n != 1 else ''}"
    return ""


def describe(rrule: str | None) -> str:
    """Readable phrase for `rrule`; empty for no rule, "Custom" when it can't be read."""
    if not rrule or rrule.strip().lower() in ("none", "nothing"):
        return ""
    parts = _parse(rrule)
    freq = parts.get("FREQ", "").upper()
    if freq not in _UNITS:
        return "Custom"
    interval = int(parts["INTERVAL"]) if parts.get("INTERVAL", "").isdigit() and int(parts["INTERVAL"]) > 0 else 1
    unit = _UNITS[freq]
    base = _SIMPLE[freq] if interval == 1 else f"Every {interval} {unit}s"
    byday = [d.strip().upper() for d in parts.get("BYDAY", "").split(",") if d.strip()]
    qualifier = ""
    if byday:
        names, ordinals = [], set()
        for token in byday:
            ordinal, code = token[:-2], token[-2:]
            if code not in _DAYS:
                return "Custom"
            if ordinal.lstrip("+-").isdigit():
                ordinals.add(int(ordinal))
            names.append(_DAYS[code])
        if ordinals and len(ordinals) == 1 and freq == "MONTHLY" and (o := next(iter(ordinals))) in _ORDINALS:
            qualifier = f" on the {_ORDINALS[o]} {_join(names)}"
        elif not ordinals:
            qualifier = f" on {_join(names)}"
        else:
            return "Custom"
    elif parts.get("BYMONTHDAY", "").lstrip("-").isdigit() and freq == "MONTHLY":
        qualifier = " on day " + parts["BYMONTHDAY"] if parts["BYMONTHDAY"] != "-1" else " on the last day"
    return base + qualifier + _end_phrase(parts)
