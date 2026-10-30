"""Rotor travel ranges and move planning (requirements 4.7, invariants 4 and 7).

A profile's travel is in rotor degrees: a north-stop rotor turns 0–360, a
south-stop rotor 180–540, a Yaesu 450° rotor 0–450. The rotor offset is applied
here, inside the rotator layer; bearings everywhere else stay true.
"""

import math
from dataclasses import dataclass
from typing import Literal

Direction = Literal["clockwise", "counter-clockwise"]

MAX_SPAN = 540.0
MAX_OFFSET = 180.0
PST_PATH_NOTE = "PstRotatorAz chooses the path; the direction shown is not guaranteed."


@dataclass(frozen=True)
class TravelRange:
    az_min: float
    az_max: float
    offset: float = 0.0


PRESETS: dict[str, TravelRange] = {
    "North stop (0–360°)": TravelRange(0, 360),
    "South stop (180–540°)": TravelRange(180, 540),
    "Yaesu 450° (0–450°)": TravelRange(0, 450),
}


@dataclass(frozen=True)
class MovePlan:
    target_true: float
    rotor_target: float | None = None
    command_deg: float | None = None
    rotor_from: float | None = None
    direction: Direction | None = None
    travel_deg: float | None = None
    long_way: bool = False
    seconds: float | None = None
    path_verified: bool = False
    error: str | None = None
    note: str | None = None


def travel_error(travel: TravelRange) -> str | None:
    values = (travel.az_min, travel.az_max, travel.offset)
    if not all(math.isfinite(value) for value in values):
        return "Travel range and offset must be numbers."
    if travel.az_max <= travel.az_min:
        return f"Travel end {travel.az_max:g}° must be above its start {travel.az_min:g}°."
    if travel.az_max - travel.az_min > MAX_SPAN:
        return f"Travel of {travel.az_max - travel.az_min:g}° is more than {MAX_SPAN:g}°."
    if abs(travel.offset) > MAX_OFFSET:
        return f"Offset {travel.offset:g}° must be between -180° and 180°."
    return None


def positions(target_true: float, travel: TravelRange) -> list[float]:
    """Every rotor position inside the travel that points at this true heading."""
    rotor = target_true + travel.offset
    candidate = rotor - 360.0 * math.ceil((rotor - travel.az_min) / 360.0)
    found = []
    while candidate <= travel.az_max + 1e-9:
        if candidate >= travel.az_min - 1e-9:
            found.append(round(candidate, 6))
        candidate += 360.0
    return found


def plan_move(
    target_true: float,
    travel: TravelRange,
    current_rotor: float | None,
    speed_deg_per_s: float | None = None,
    adapter_chooses_path: bool = False,
) -> MovePlan:
    problem = travel_error(travel)
    if problem is not None:
        return MovePlan(target_true, error=f"{problem} Nothing was sent.")
    if not (math.isfinite(target_true) and 0.0 <= target_true <= 359.9):
        return MovePlan(
            target_true, error=f"Heading {target_true:g}° is outside 0–359.9°. Nothing was sent."
        )
    reachable = positions(target_true, travel)
    if not reachable:
        return MovePlan(
            target_true,
            error=f"{target_true:g}° is outside this rotator's travel "
            f"({travel.az_min:g}–{travel.az_max:g}°). Nothing was sent.",
        )
    current = current_rotor if current_rotor is not None and math.isfinite(current_rotor) else None
    # min() keeps the first of equal distances, and reachable is ascending: ties go lower.
    rotor_target = reachable[0] if current is None else min(
        reachable, key=lambda p: abs(p - current)
    )
    if adapter_chooses_path:
        # The controller takes 0–359.9 and picks its own way round, so no direction,
        # travel or time can be promised (invariant 6). 359.95 → 0, not a refusal.
        command = rotor_target % 360.0
        if command > 359.9:
            command = 0.0
        return MovePlan(target_true, rotor_target, command, rotor_from=current, note=PST_PATH_NOTE)
    command = rotor_target
    note = None
    if current is None:
        return MovePlan(target_true, rotor_target, command, note=note)
    travel_deg = abs(rotor_target - current)
    direction: Direction | None = None
    if travel_deg > 0:
        direction = "clockwise" if rotor_target > current else "counter-clockwise"
    seconds = travel_deg / speed_deg_per_s if speed_deg_per_s else None
    return MovePlan(
        target_true,
        rotor_target,
        command,
        rotor_from=current,
        direction=direction,
        travel_deg=travel_deg,
        long_way=travel_deg > 180,
        seconds=seconds,
        path_verified=True,
    )
