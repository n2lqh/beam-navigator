import math

import pytest

from beam_navigator.rotators.travel import (
    PRESETS,
    TravelRange,
    plan_move,
    positions,
    travel_error,
)

NORTH = TravelRange(0, 360)
SOUTH = TravelRange(180, 540)
YAESU = TravelRange(0, 450)
PST_NOTE = "PstRotatorAz chooses the path; the direction shown is not guaranteed."


def test_presets() -> None:
    assert PRESETS == {
        "North stop (0–360°)": NORTH,
        "South stop (180–540°)": SOUTH,
        "Yaesu 450° (0–450°)": YAESU,
    }
    assert all(travel_error(travel) is None for travel in PRESETS.values())


@pytest.mark.parametrize(
    "travel",
    [TravelRange(0, 0), TravelRange(10, 5), TravelRange(0, 800), TravelRange(math.nan, 360),
     TravelRange(0, math.inf), TravelRange(0, 360, 200), TravelRange(0, 360, math.nan)],
)
def test_travel_error(travel: TravelRange) -> None:  # Review Focus 5
    assert travel_error(travel) is not None


def test_positions() -> None:
    assert positions(10, YAESU) == [10, 370]
    assert positions(10, NORTH) == [10]
    assert positions(170, SOUTH) == [530]
    assert positions(355, TravelRange(0, 350)) == []


def test_north_stop_long_way() -> None:
    plan = plan_move(10, NORTH, current_rotor=350)
    assert plan.rotor_target == 10
    assert plan.command_deg == 10
    assert plan.rotor_from == 350
    assert plan.direction == "counter-clockwise"
    assert plan.travel_deg == 340
    assert plan.long_way
    assert plan.path_verified
    assert plan.error is None


def test_yaesu_overlap_takes_short_way() -> None:
    plan = plan_move(10, YAESU, current_rotor=350)
    assert plan.rotor_target == 370
    assert plan.direction == "clockwise"
    assert plan.travel_deg == 20
    assert not plan.long_way


def test_yaesu_unknown_position() -> None:
    plan = plan_move(10, YAESU, current_rotor=None)
    assert plan.rotor_target == 10
    assert plan.direction is None
    assert plan.travel_deg is None
    assert plan.seconds is None
    assert not plan.path_verified


def test_south_stop() -> None:
    plan = plan_move(170, SOUTH, current_rotor=190)
    assert plan.rotor_target == 530
    assert plan.direction == "clockwise"
    assert plan.travel_deg == 340
    assert plan.long_way


def test_outside_travel_rejected() -> None:  # invariant 7
    plan = plan_move(355, TravelRange(0, 350), current_rotor=0)
    assert plan.error == "355° is outside this rotator's travel (0–350°). Nothing was sent."
    assert plan.rotor_target is None
    assert plan.command_deg is None


def test_offset_crosses_stop() -> None:  # Review Focus 1
    plan = plan_move(355, TravelRange(0, 360, 10), current_rotor=0)
    assert plan.rotor_target == pytest.approx(5)
    assert plan.command_deg == pytest.approx(5)
    assert plan.target_true == 355


def test_time_estimate() -> None:
    assert plan_move(90, NORTH, current_rotor=0, speed_deg_per_s=2).seconds == 45
    assert plan_move(90, NORTH, current_rotor=0).seconds is None


def test_pstrotator_path_unverified() -> None:  # Review Focus 2
    plan = plan_move(30, YAESU, current_rotor=40, adapter_chooses_path=True)
    assert plan.command_deg == 30
    assert not plan.path_verified
    assert plan.note == PST_NOTE


def test_pstrotator_command_is_modulo_360() -> None:
    plan = plan_move(10, YAESU, current_rotor=350, adapter_chooses_path=True)
    assert plan.rotor_target == 370
    assert plan.command_deg == 10


@pytest.mark.parametrize("target", [math.nan, math.inf, -1.0, 360.0])
def test_non_finite_or_out_of_range_target_rejected(target: float) -> None:  # Review Focus 5
    plan = plan_move(target, NORTH, current_rotor=0)
    assert plan.error is not None
    assert plan.command_deg is None


def test_bad_travel_rejected_in_plan() -> None:
    plan = plan_move(10, TravelRange(10, 5), current_rotor=0)
    assert plan.error is not None
    assert plan.command_deg is None


def test_ties_take_the_lower_position() -> None:
    plan = plan_move(0, TravelRange(0, 540), current_rotor=180)
    assert positions(0, TravelRange(0, 540)) == [0, 360]
    assert plan.rotor_target == 0


def test_pstrotator_plan_states_no_direction() -> None:  # final review, Focus 2
    plan = plan_move(30, YAESU, current_rotor=40, speed_deg_per_s=6, adapter_chooses_path=True)
    assert plan.direction is None
    assert plan.travel_deg is None
    assert plan.seconds is None
    assert plan.long_way is False


def test_pstrotator_command_never_exceeds_359_9() -> None:  # final review
    plan = plan_move(0, TravelRange(0, 360, -0.05), current_rotor=0, adapter_chooses_path=True)
    assert plan.command_deg == 0.0
