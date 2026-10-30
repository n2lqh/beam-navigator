"""Net schedules (requirements 4.6; decisions 24, 25): weekday, start time, time zone and
the next occurrence. Pure: "now" is always passed in."""

import re
from datetime import datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# Fixed English names, so the text never depends on this computer's locale.
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_START_TIME = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


def parse_start_time(text: str) -> str | None:
    clean = text.strip()
    if not clean:
        return None
    match = _START_TIME.fullmatch(clean)
    if match is None:
        raise ValueError("Start time must be HH:MM, 24-hour.")
    return f"{int(match[1]):02d}:{match[2]}"


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def zone_for(*names: str | None) -> tzinfo | None:
    """The first real zone among the names (decision 24); None means this computer's."""
    for name in names:
        if name and name.strip():
            zone = _zone(name.strip())
            if zone is not None:
                return zone
    return None


def check_zone(name: str) -> str | None:
    clean = name.strip()
    if not clean:
        return None
    if _zone(clean) is None:
        raise ValueError(f"Unknown time zone {clean!r}. Use a name like America/New_York.")
    return clean


def next_occurrence(weekday: int, start_time: str, zone: tzinfo | None, now: datetime) -> datetime:
    """The first weekday-and-time at or after now, in the zone (local when None)."""
    start = time.fromisoformat(start_time)
    today = now.astimezone(zone).date()
    for offset in range(8):
        day = today + timedelta(days=offset)
        if day.weekday() != weekday:
            continue
        naive = datetime.combine(day, start)
        when = naive.replace(tzinfo=zone) if zone is not None else naive.astimezone()
        if when >= now:
            return when
    raise AssertionError("unreachable: a weekday recurs within 8 days")


def occurrence_text(when: datetime | None) -> str:
    if when is None:
        return "Not scheduled"
    day = WEEKDAYS[when.weekday()][:3].title()
    return f"{day} {when.day} {_MONTHS[when.month - 1]} {when.year}, {when:%H:%M} {when.tzname()}"
