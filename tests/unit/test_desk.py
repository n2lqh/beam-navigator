import sqlite3
from collections.abc import Iterator
from dataclasses import replace

import pytest

from beam_navigator.core.lookup import lookup
from beam_navigator.core.maidenhead import grid_center
from beam_navigator.core.models import OperatorProfile, RotatorProfile
from beam_navigator.core.targets import AliasTarget, resolve
from beam_navigator.desk import Desk, progress_text
from beam_navigator.rotators.base import RotatorAdapter
from beam_navigator.rotators.service import PositionReading, RotateOutcome, RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.rotators.travel import MovePlan
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import (
    AliasRepository,
    ProfileRepository,
    RotatorRepository,
    StationRepository,
)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


def add_profile(conn: sqlite3.Connection) -> None:
    profiles = ProfileRepository(conn)
    saved = profiles.save(
        OperatorProfile(None, "Home", "N2LQH", "FM29pt", None, "mi", "America/New_York", "NJ",
                        False)  # fmt: skip
    )
    assert saved.id is not None
    profiles.activate(saved.id)


def add_rotator(conn: sqlite3.Connection, **changes: object) -> RotatorProfile:
    profile = RotatorProfile(
        id=None, name="VHF", adapter="simulation", host=None, port=None, az_min=0.0,
        az_max=360.0, offset=0.0, speed_deg_per_s=None, bands=("2 m",), live=False,
        connection_tested=False,
    )  # fmt: skip
    return RotatorRepository(conn).save(replace(profile, **changes))  # type: ignore[arg-type]


def desk_with(conn: sqlite3.Connection, adapter: RotatorAdapter) -> Desk:
    service = RotateService(conn, adapter_for=lambda p: adapter, tester_for=lambda p: adapter)
    return Desk(conn, service)


@pytest.fixture
def sim() -> SimulationAdapter:
    return SimulationAdapter(az_max=360)


@pytest.fixture
def desk(conn: sqlite3.Connection, sim: SimulationAdapter) -> Desk:
    add_profile(conn)
    add_rotator(conn)
    return desk_with(conn, sim)


def test_grid_lookup_text(desk: Desk) -> None:
    view = desk.look_up("FN20ok", "2 m")
    expected = lookup(grid_center("FM29pt"), resolve("FN20ok"))
    assert view.error is None
    assert view.bearing_deg == pytest.approx(expected.bearing_deg)
    assert view.bearing_text is not None and view.bearing_text.endswith(" N")
    assert view.distance_text is not None and view.distance_text.endswith(" mi")
    assert view.title == "FN20ok — typed"
    assert view.reverse_text is not None and view.reverse_text.startswith("Reverse 17")
    assert view.long_path_text is None
    assert view.can_rotate


def test_home_disables_rotate(desk: Desk) -> None:  # acceptance 2
    view = desk.look_up("FM29pt", "2 m")
    assert view.message == "Home"
    assert view.bearing_text is None
    assert not view.can_rotate


def test_in_region(desk: Desk) -> None:  # acceptance 8
    view = desk.look_up("nj", "2 m")
    assert view.message == "You are in NJ"
    assert not view.can_rotate


def test_ne_offers_nebraska(desk: Desk) -> None:  # acceptance 9
    view = desk.look_up("NE", "2 m")
    assert view.bearing_deg == 45
    assert view.distance_text is None
    assert view.alternative == "st:NE"
    assert view.alternative_label == "Nebraska?"
    assert desk.look_up("st:NE", "2 m").title == "Nebraska (NE) — region centroid"


def test_alias_same_as_grid(desk: Desk, conn: sqlite3.Connection) -> None:  # acceptance 10
    AliasRepository(conn).save("CLUB", AliasTarget("grid", "FM29jw"))
    club = desk.look_up("CLUB", "2 m")
    grid = desk.look_up("FM29jw", "2 m")
    assert (club.bearing_text, club.distance_text) == (grid.bearing_text, grid.distance_text)
    assert club.title == "CLUB — alias"


def test_unknown_callsign_needs_grid(desk: Desk, conn: sqlite3.Connection) -> None:
    view = desk.look_up("w2kv", "2 m")
    assert view.message == "Grid needed"
    assert view.needs_grid_for == "W2KV"
    assert not view.can_rotate
    typed = desk.look_up_with_grid("W2KV", "FN20ok", "2 m")
    assert typed.title == "W2KV — typed"
    assert typed.bearing_text == desk.look_up("FN20ok", "2 m").bearing_text
    assert StationRepository(conn).get("W2KV") is None


def test_look_up_with_bad_grid(desk: Desk) -> None:
    assert desk.look_up_with_grid("W2KV", "ZZ99", "2 m").error is not None


def test_save_station_grid_keeps_name(desk: Desk, conn: sqlite3.Connection) -> None:
    stations = StationRepository(conn)
    stations.add_from_roster("W2KV", "Bob", None, "Cherry Hill")
    desk.save_station_grid("W2KV", "FN20ok")
    saved = stations.get("W2KV")
    assert saved is not None
    assert (saved.name, saved.qth, saved.grid, saved.source) == (
        "Bob", "Cherry Hill", "FN20ok", "saved"
    )
    assert desk.look_up("W2KV", "2 m").title == "W2KV — saved"


def test_save_station_grid_rejects_bad_grid(desk: Desk, conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        desk.save_station_grid("W2KV", "ZZ99")
    assert StationRepository(conn).get("W2KV") is None


def test_no_profile(conn: sqlite3.Connection, sim: SimulationAdapter) -> None:  # Focus 2
    view = desk_with(conn, sim).look_up("FN20ok", "2 m")
    assert view.error == "Set up your station first: Settings → Station."
    assert not view.can_rotate


@pytest.mark.parametrize("text", ["x" * 1_000_000, "\x00\x01", "", "   ", "call:", "400"])
def test_garbage_input(desk: Desk, text: str) -> None:  # Focus 5
    view = desk.look_up(text, "2 m")
    assert view.error
    assert not view.can_rotate


def test_long_path_follows_band(desk: Desk) -> None:
    six = desk.look_up("FN20ok", "6 m")
    assert six.long_path_text is not None and six.long_path_text.startswith("Long path ")
    assert desk.look_up("FN20ok", "2 m").long_path_text is None
    assert desk.look_up("FN20", "23 cm").coarse_note == "coarse location — ±50 km"
    assert desk.look_up("FN20", "2 m").coarse_note is None


def test_selected_band(desk: Desk) -> None:
    assert desk.selected_band() == "2 m"
    desk.select_band("6 m")
    assert desk.selected_band() == "6 m"


def test_rotate_label_simulated(desk: Desk) -> None:  # Focus 1
    rotator = desk.default_rotator("2 m")
    assert rotator is not None and rotator.id is not None
    assert desk.rotate_label(rotator, 294.6) == "Rotate VHF to 294.6° (simulated)"
    assert desk.rotate_label(replace(rotator, live=True), 294.6) == "Rotate VHF to 294.6°"
    assert desk.default_rotator("6 m") is None
    assert [r.name for r in desk.rotators()] == ["VHF"]
    assert desk.rotate(rotator.id, "FN20ok", 90.0).status.startswith("Simulated: ")


def test_plan_text(desk: Desk) -> None:
    rotator = desk.default_rotator("2 m")
    assert rotator is not None and rotator.id is not None
    assert desk.plan_text(rotator.id, 90.0) == "Path unverified (position unknown)"
    desk.rotate(rotator.id, "a", 350.0)
    assert desk.plan_text(rotator.id, 10.0) == "Long way round: counter-clockwise 340.0°"
    assert desk.plan_text(rotator.id, 340.0) == "Counter-clockwise 10.0°"


def test_lookup_and_band_choice_send_nothing(desk: Desk, sim: SimulationAdapter) -> None:  # 26
    for text in ("FN20ok", "NE", "PA", "W2KV", "247"):
        desk.look_up(text, desk.selected_band())
    desk.select_band("6 m")
    rotator = desk.default_rotator("2 m")
    assert rotator is not None and rotator.id is not None
    desk.plan_text(rotator.id, 90.0)
    assert sim.commands == []
    desk.rotate(rotator.id, "FN20ok", 354.2)
    assert len(sim.commands) == 1


def outcome(
    measured: float | None = None, seconds: float | None = 10.0, ok: bool = True
) -> RotateOutcome:
    plan = MovePlan(90.0, 90.0, 90.0, seconds=seconds)
    return RotateOutcome(plan, True, ok, "Command sent — position unverified", measured)


def test_progress_text() -> None:
    assert progress_text(outcome(measured=90.0), 0, None)[1] is True
    moving = progress_text(outcome(), 2, PositionReading(30.0, 30.0, ""))
    assert moving == ("Commanded 90.0°, measured 30.0° — moving", False)
    arrived = progress_text(outcome(), 9, PositionReading(89.8, 89.8, ""))
    assert arrived == ("Commanded 90.0°, measured 89.8°", True)
    text, stop = progress_text(outcome(), 3, PositionReading(None, None, "No reply. Not retried."))
    assert stop and "No reply. Not retried." in text
    assert progress_text(outcome(), 4, None) == (
        "Command sent — position unverified · 4 s of about 10 s", False
    )
    assert progress_text(outcome(seconds=None), 4, None)[0] == (
        "Command sent — position unverified · 4 s"
    )
    text, stop = progress_text(outcome(), 41, PositionReading(30.0, 30.0, ""))
    assert stop and "not there after 41 s" in text
    assert progress_text(outcome(ok=False), 0, None)[1] is True


def test_watch_reads_and_labels_simulation(desk: Desk, sim: SimulationAdapter) -> None:
    rotator = desk.default_rotator("2 m")
    assert rotator is not None and rotator.id is not None
    pressed = desk.rotate(rotator.id, "FN20ok", 90.0)
    text, stop = desk.watch(rotator.id, replace(pressed, measured=None), 1.0)
    assert text == "Simulated: Commanded 90.0°, measured 90.0°"
    assert stop
    assert len(sim.commands) == 1  # watching only reads


def test_recent_commands(desk: Desk) -> None:
    rotator = desk.default_rotator("2 m")
    assert rotator is not None and rotator.id is not None
    for heading in (10.0, 20.0, 30.0):
        desk.rotate(rotator.id, f"to {heading:g}", heading)
    assert [r.target_label for r in desk.recent_commands(rotator.id, 2)] == ["to 30", "to 20"]


def test_read_and_stop_say_simulated(desk: Desk) -> None:  # final review I3
    rotator = desk.default_rotator("2 m")
    assert rotator is not None and rotator.id is not None
    assert desk.read_position(rotator.id).startswith("Simulated: Rotor reads ")
    assert desk.stop(rotator.id).startswith("Simulated: ")


def test_bearing_to(desk: Desk) -> None:
    found = desk.bearing_to("FN20ok")
    assert found is not None
    assert found.text.endswith(" N") and found.distance_text.endswith(" mi")
    assert found.distance_km == pytest.approx(70, abs=5)
    assert desk.bearing_to("FM29pt") is None  # home
    assert desk.bearing_to("ZZ99") is None
    assert desk.bearing_to("") is None
