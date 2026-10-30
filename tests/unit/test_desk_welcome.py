"""The first-run wizard's rules: shown until a station is active, entries remembered
(Milestone 4; decision 35)."""

import sqlite3
from collections.abc import Iterator

import pytest

from beam_navigator.core.models import OperatorProfile
from beam_navigator.desk import WELCOME_DRAFT, Desk, WelcomeDraft
from beam_navigator.rotators.service import RotateService
from beam_navigator.store.db import open_db


@pytest.fixture
def desk() -> Iterator[Desk]:
    conn: sqlite3.Connection = open_db(":memory:")
    yield Desk(conn, RotateService(conn))
    conn.close()


def saved(desk: Desk, name: str, grid: str) -> OperatorProfile:
    return desk.profiles.save(
        OperatorProfile(None, name, None, grid, None, "km", "UTC", None, False)
    )


def test_new_database_needs_welcome(desk: Desk) -> None:
    assert desk.needs_welcome()
    assert desk.welcome_draft() == WelcomeDraft()


def test_inactive_profiles_still_need_it(desk: Desk) -> None:
    saved(desk, "Portable", "FN20")
    assert desk.needs_welcome()


def test_active_profile_ends_it(desk: Desk) -> None:
    profile = saved(desk, "Home", "FN20")
    assert profile.id is not None
    desk.profiles.activate(profile.id)
    assert not desk.needs_welcome()


def test_save_station_inserts_and_activates(desk: Desk) -> None:
    profile = desk.save_welcome_station(WelcomeDraft("n0call", "FN20", "mi", "America/New_York"))
    assert profile.name == "N0CALL" and profile.units == "mi" and profile.is_active
    assert profile.timezone == "America/New_York"
    assert not desk.needs_welcome()
    assert desk.settings.get(WELCOME_DRAFT) is None


def test_no_callsign_is_named_home(desk: Desk) -> None:
    assert desk.save_welcome_station(WelcomeDraft(grid="FN20")).name == "Home"


def test_bad_grid_keeps_the_draft(desk: Desk) -> None:
    with pytest.raises(ValueError):
        desk.save_welcome_station(WelcomeDraft(grid="ZZ99"))
    assert desk.profiles.list() == []
    assert desk.welcome_draft().grid == "ZZ99"


def test_bad_zone_keeps_the_draft(desk: Desk) -> None:
    with pytest.raises(ValueError, match="is not a time zone"):
        desk.save_welcome_station(WelcomeDraft(grid="FN20", timezone="Mars/Base"))
    assert desk.profiles.list() == []
    assert desk.welcome_draft().timezone == "Mars/Base"


def test_draft_from_latest_profile(desk: Desk) -> None:
    saved(desk, "First", "FN20")
    latest = saved(desk, "Second", "FN31")
    draft = desk.welcome_draft()
    assert draft.grid == "FN31" and draft.profile_id == latest.id
    profile = desk.save_welcome_station(draft)
    assert len(desk.profiles.list()) == 2
    assert profile.id == latest.id and profile.name == "Second" and profile.is_active


def test_kept_draft_wins_over_profile(desk: Desk) -> None:
    saved(desk, "Portable", "FN20")
    desk.keep_welcome_draft(WelcomeDraft(grid="FM18"))
    assert desk.welcome_draft().grid == "FM18"


@pytest.mark.parametrize("raw", ["{not json", "[1]", '{"grid": 5}', '{"units": "furlongs"}'])
def test_corrupt_draft_falls_back(desk: Desk, raw: str) -> None:
    desk.settings.set(WELCOME_DRAFT, raw)
    assert desk.welcome_draft() == WelcomeDraft()
    profile = saved(desk, "Portable", "FN20")
    assert desk.welcome_draft() == WelcomeDraft(grid="FN20", profile_id=profile.id)


def test_use_station(desk: Desk) -> None:
    profile = saved(desk, "Portable", "FN20")
    assert profile.id is not None
    desk.keep_welcome_draft(WelcomeDraft(grid="FM18"))
    desk.use_station(profile.id)
    assert not desk.needs_welcome()
    assert desk.settings.get(WELCOME_DRAFT) is None


def test_profile_id_that_vanished(desk: Desk) -> None:
    profile = desk.save_welcome_station(WelcomeDraft(grid="FN20", profile_id=999))
    assert profile.id != 999 and profile.is_active


def test_changed_grid_drops_the_old_exact_position(desk: Desk) -> None:
    # Final review I1: an old lat/lon would keep bearings at the old place (invariant 3).
    from beam_navigator.core.models import LatLon

    profile = desk.profiles.save(OperatorProfile(None, "Home", None, "FN20", LatLon(40.5, -74.5),
                                                 "km", "UTC", "NJ", False))  # fmt: skip
    moved = desk.save_welcome_station(WelcomeDraft(grid="JO01", profile_id=profile.id))
    assert moved.latlon is None and moved.home_region is None
    kept = desk.save_welcome_station(WelcomeDraft(grid="JO01", profile_id=profile.id))
    assert kept.home_grid == "JO01"
    exact = LatLon(40.5, -74.5)
    again = desk.profiles.save(
        OperatorProfile(profile.id, "Home", None, "FN20", exact, "km", "UTC", "NJ", False)
    )
    same = desk.save_welcome_station(WelcomeDraft(grid="FN20", profile_id=again.id))
    assert same.latlon == LatLon(40.5, -74.5) and same.home_region == "NJ"


def test_name_taken_is_a_clear_error(desk: Desk) -> None:
    # Final review I2: a UNIQUE name clash was an IntegrityError the page never showed.
    saved(desk, "Home", "FN20")
    with pytest.raises(ValueError, match="A station named 'Home' already exists"):
        desk.save_welcome_station(WelcomeDraft(grid="FN31"))
    assert len(desk.profiles.list()) == 1
    assert desk.welcome_draft().grid == "FN31"
