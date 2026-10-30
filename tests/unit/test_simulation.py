import math

import pytest

from beam_navigator.rotators.base import azimuth_error
from beam_navigator.rotators.simulation import SimulationAdapter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize("heading", [0.0, 90.0, 359.9])
def test_valid_headings_accepted(heading: float) -> None:
    assert azimuth_error(heading) is None


@pytest.mark.parametrize(
    "heading", [-0.1, 359.95, 359.99, 360.0, 400.0, math.nan, math.inf]
)
def test_invalid_headings_rejected(heading: float) -> None:
    assert azimuth_error(heading) is not None


def test_one_command_per_set() -> None:
    rotor = SimulationAdapter()
    rotor.set_azimuth(90)
    assert [c.azimuth for c in rotor.commands] == [90]


def test_out_of_range_records_nothing() -> None:
    rotor = SimulationAdapter()
    result = rotor.set_azimuth(400)
    assert not result.ok
    assert "outside" in result.message
    assert rotor.commands == []
    assert rotor.get_position() == 0.0


def test_without_speed_arrives_instantly() -> None:
    rotor = SimulationAdapter()
    rotor.set_azimuth(247)
    assert rotor.get_position() == 247


def test_moves_at_configured_speed() -> None:
    clock = FakeClock()
    rotor = SimulationAdapter(start_azimuth=10, speed_deg_per_s=6, clock=clock)
    rotor.set_azimuth(100)
    clock.now = 5
    assert rotor.get_position() == pytest.approx(40)
    clock.now = 60
    assert rotor.get_position() == 100


def test_moves_down_without_wrapping_through_north() -> None:
    clock = FakeClock()
    rotor = SimulationAdapter(start_azimuth=350, speed_deg_per_s=10, clock=clock)
    rotor.set_azimuth(10)
    clock.now = 2
    assert rotor.get_position() == pytest.approx(330)


def test_stop_freezes_position() -> None:
    clock = FakeClock()
    rotor = SimulationAdapter(speed_deg_per_s=6, clock=clock)
    rotor.set_azimuth(90)
    clock.now = 5
    rotor.stop()
    clock.now = 60
    assert rotor.get_position() == pytest.approx(30)


def test_450_degree_simulation_moves_into_overlap() -> None:
    clock = FakeClock()
    rotor = SimulationAdapter(start_azimuth=350, speed_deg_per_s=10, clock=clock, az_max=450)
    assert rotor.set_azimuth(400).ok
    clock.now = 2
    assert rotor.get_position() == 370  # numeric path: 350 → 400 through 360
    clock.now = 10
    assert rotor.get_position() == 400
    assert not rotor.set_azimuth(451).ok
    assert rotor.capabilities().chooses_path is False


def test_default_simulation_range_unchanged() -> None:
    assert not SimulationAdapter().set_azimuth(400).ok
