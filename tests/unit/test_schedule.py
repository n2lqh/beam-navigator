from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from beam_navigator.core.schedule import (
    WEEKDAYS,
    check_zone,
    next_occurrence,
    occurrence_text,
    parse_start_time,
    zone_for,
)

NEW_YORK = ZoneInfo("America/New_York")


def test_weekdays_start_monday() -> None:
    assert WEEKDAYS[0] == "monday" and WEEKDAYS[6] == "sunday" and len(WEEKDAYS) == 7


def test_next_occurrence_later_today() -> None:
    now = datetime(2026, 11, 3, 18, 0, tzinfo=NEW_YORK)  # a Tuesday
    assert next_occurrence(1, "20:00", NEW_YORK, now) == datetime(
        2026, 11, 3, 20, 0, tzinfo=NEW_YORK
    )


def test_next_occurrence_after_start_is_next_week() -> None:
    now = datetime(2026, 11, 3, 20, 1, tzinfo=NEW_YORK)
    assert next_occurrence(1, "20:00", NEW_YORK, now) == datetime(
        2026, 11, 10, 20, 0, tzinfo=NEW_YORK
    )


def test_next_occurrence_across_dst() -> None:
    now = datetime(2026, 10, 31, 12, 0, tzinfo=NEW_YORK)  # Saturday, still EDT
    when = next_occurrence(6, "20:00", NEW_YORK, now)
    assert (when.year, when.month, when.day, when.hour, when.minute) == (2026, 11, 1, 20, 0)
    assert when.utcoffset() == timedelta(hours=-5)  # EST after the change


def test_next_occurrence_from_utc_now() -> None:
    now = datetime(2026, 11, 4, 0, 30, tzinfo=ZoneInfo("UTC"))  # Tue 19:30 in New York
    assert next_occurrence(1, "20:00", NEW_YORK, now) == datetime(
        2026, 11, 3, 20, 0, tzinfo=NEW_YORK
    )


def test_occurrence_text() -> None:
    when = datetime(2026, 11, 3, 20, 0, tzinfo=NEW_YORK)
    assert occurrence_text(when) == "Tue 3 Nov 2026, 20:00 EST"
    assert occurrence_text(None) == "Not scheduled"


@pytest.mark.parametrize(
    ("text", "expected"), [("20:00", "20:00"), ("8:05", "08:05"), (" 19:30 ", "19:30"), ("", None)]
)
def test_parse_start_time(text: str, expected: str | None) -> None:
    assert parse_start_time(text) == expected


@pytest.mark.parametrize("text", ["24:00", "8pm", "2000", "20:60", "7:5"])
def test_parse_start_time_refuses(text: str) -> None:
    with pytest.raises(ValueError, match="Start time must be HH:MM, 24-hour."):
        parse_start_time(text)


def test_zone_for_skips_unknown() -> None:
    assert zone_for("Not/AZone", "Asia/Tokyo") == ZoneInfo("Asia/Tokyo")
    assert zone_for(None, " ") is None


def test_check_zone() -> None:
    assert check_zone(" America/New_York ") == "America/New_York"
    assert check_zone("") is None
    with pytest.raises(ValueError, match="America/New_York"):
        check_zone("America/NewYork")
