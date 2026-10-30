import math
import sqlite3
from collections.abc import Iterator
from dataclasses import replace

import pytest

from beam_navigator.core.models import Band, RotatorProfile
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import BandRepository, RotatorRepository, SettingRepository


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


def rotator(name: str, *bands: str) -> RotatorProfile:
    return RotatorProfile(
        id=None, name=name, adapter="simulation", host=None, port=None, az_min=0.0,
        az_max=360.0, offset=0.0, speed_deg_per_s=None, bands=bands, live=False,
        connection_tested=False,
    )  # fmt: skip


def test_seeded_bands(conn: sqlite3.Connection) -> None:
    bands = BandRepository(conn).list()
    assert [b.name for b in bands] == ["10 m", "6 m", "2 m", "1.25 m", "70 cm", "33 cm", "23 cm"]
    assert [b.mhz for b in bands] == [28, 50, 144, 222, 432, 902, 1296]
    assert [b.name for b in bands if b.long_path] == ["10 m", "6 m"]


def test_add_and_toggle_long_path(conn: sqlite3.Connection) -> None:
    bands = BandRepository(conn)
    assert bands.add(" 13 cm ", 2304) == Band("13 cm", 2304, False)
    bands.set_long_path("13 cm", True)
    assert bands.get("13 cm") == Band("13 cm", 2304, True)
    assert [b.name for b in bands.list()][-1] == "13 cm"


@pytest.mark.parametrize(("name", "mhz"), [(" ", 10.0), ("4 m", 0.0), ("4 m", math.nan),
                                           ("2 m", 145.0)])  # fmt: skip
def test_bad_band_rejected(conn: sqlite3.Connection, name: str, mhz: float) -> None:
    with pytest.raises(ValueError):
        BandRepository(conn).add(name, mhz)
    assert len(BandRepository(conn).list()) == 7


def test_band_in_use_cannot_be_deleted(conn: sqlite3.Connection) -> None:  # Focus 4
    RotatorRepository(conn).save(rotator("VHF", "2 m"))
    bands = BandRepository(conn)
    with pytest.raises(ValueError, match="2 m is served by VHF; remove it from that rotator"):
        bands.delete("2 m")
    assert bands.get("2 m") is not None
    bands.delete("23 cm")
    assert bands.get("23 cm") is None


def test_rotator_band_must_exist(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="Unknown band '3 m'."):
        RotatorRepository(conn).save(rotator("VHF", "3 m"))


def test_band_served_by_one_rotator(conn: sqlite3.Connection) -> None:
    rotators = RotatorRepository(conn)
    hf = rotators.save(rotator("HF beam", "2 m", "6 m"))
    with pytest.raises(ValueError, match="2 m is already served by HF beam."):
        rotators.save(rotator("VHF", "2 m"))
    rotators.save(replace(hf, name="HF yagi"))  # re-saving the same rotator is fine


def test_rotator_for_band(conn: sqlite3.Connection) -> None:
    saved = RotatorRepository(conn).save(rotator("VHF", "2 m", "70 cm"))
    bands = BandRepository(conn)
    assert bands.rotator_for("70 cm") == saved
    assert bands.rotator_for("6 m") is None


def test_setting_round_trip_and_delete(conn: sqlite3.Connection) -> None:
    settings = SettingRepository(conn)
    assert settings.get("dashboard_band") is None
    settings.set("dashboard_band", "2 m")
    settings.set("dashboard_band", "6 m")
    assert settings.get("dashboard_band") == "6 m"
    settings.set("dashboard_band", None)
    assert settings.get("dashboard_band") is None
