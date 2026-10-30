import sqlite3
from collections.abc import Iterator
from math import nan

import pytest

from beam_navigator.core.models import LatLon, OperatorProfile
from beam_navigator.core.targets import AliasTarget, TargetError, resolve
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import AliasRepository, ProfileRepository


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


def profile(name: str, grid: str = "FM29pt", region: str | None = "nj") -> OperatorProfile:
    return OperatorProfile(
        id=None,
        name=name,
        callsign=None,
        home_grid=grid,
        latlon=None,
        units="mi",
        timezone="America/New_York",
        home_region=region,
        is_active=False,
    )


def test_alias_in_store_matches_typed_grid(conn: sqlite3.Connection) -> None:  # acceptance 10
    aliases = AliasRepository(conn)
    aliases.save("club", AliasTarget("grid", "FM29jw"))
    assert aliases.get("CLUB") == AliasTarget("grid", "FM29jw")
    assert resolve("CLUB", aliases=aliases.get).location == resolve("FM29jw").location
    assert aliases.list() == [("CLUB", AliasTarget("grid", "FM29jw"))]


def test_alias_colliding_with_builtin_is_refused(conn: sqlite3.Connection) -> None:  # decision 12
    with pytest.raises(TargetError):
        AliasRepository(conn).save("NC", AliasTarget("grid", "FN20ok"))
    assert AliasRepository(conn).list() == []


def test_alias_save_replaces_and_delete_removes(conn: sqlite3.Connection) -> None:
    aliases = AliasRepository(conn)
    aliases.save("CLUB", AliasTarget("grid", "FM29jw"))
    aliases.save("CLUB", AliasTarget("heading", "90"))
    assert aliases.get("club") == AliasTarget("heading", "90")
    aliases.delete("club")
    assert aliases.get("CLUB") is None


def test_new_database_has_no_profile(conn: sqlite3.Connection) -> None:  # invariant 10
    assert ProfileRepository(conn).get_active() is None
    assert ProfileRepository(conn).list() == []


def test_activate_leaves_exactly_one_active(conn: sqlite3.Connection) -> None:
    profiles = ProfileRepository(conn)
    home = profiles.save(profile("Home"))
    portable = profiles.save(profile("Portable", grid="FN20ok", region=None))
    assert home.id is not None and portable.id is not None
    profiles.activate(home.id)
    profiles.activate(portable.id)
    assert [p.name for p in profiles.list() if p.is_active] == ["Portable"]
    active = profiles.get_active()
    assert active is not None and active.home_grid == "FN20ok"


def test_home_region_stored_upper_case(conn: sqlite3.Connection) -> None:  # decision 10
    profiles = ProfileRepository(conn)
    saved = profiles.save(profile("Home", region="nj"))
    assert saved.id is not None
    profiles.activate(saved.id)
    active = profiles.get_active()
    assert active is not None and active.home_region == "NJ"


@pytest.mark.parametrize(("grid", "region"), [("ZZ99", "NJ"), ("FM29pt", "XX")])
def test_invalid_profile_rejected(conn: sqlite3.Connection, grid: str, region: str) -> None:
    with pytest.raises(ValueError):
        ProfileRepository(conn).save(profile("Home", grid=grid, region=region))
    assert ProfileRepository(conn).list() == []


def test_update_keeps_id(conn: sqlite3.Connection) -> None:
    profiles = ProfileRepository(conn)
    saved = profiles.save(profile("Home"))
    updated = profiles.save(
        OperatorProfile(**{**saved.__dict__, "home_grid": "FM29ps", "callsign": "n2lqh"})
    )
    assert updated.id == saved.id
    assert [(p.home_grid, p.callsign) for p in profiles.list()] == [("FM29ps", "N2LQH")]


@pytest.mark.parametrize(
    "latlon", [LatLon(999.0, 999.0), LatLon(91.0, 0.0), LatLon(0.0, -181.0), LatLon(nan, 0.0)]
)
def test_profile_coordinates_must_be_on_earth(conn: sqlite3.Connection, latlon: LatLon) -> None:
    bad = OperatorProfile(**{**profile("Home").__dict__, "latlon": latlon})
    with pytest.raises(ValueError):
        ProfileRepository(conn).save(bad)
    assert ProfileRepository(conn).list() == []
