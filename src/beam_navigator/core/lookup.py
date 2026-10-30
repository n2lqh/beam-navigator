"""Bearing lookup: what the dashboard shows for one target (requirements 4.1, 5)."""

from dataclasses import dataclass

from beam_navigator.core.geometry import (
    Path,
    coarse_location_note,
    compass_name,
    is_home,
    long_path,
    short_path,
)
from beam_navigator.core.models import LatLon
from beam_navigator.core.targets import Resolution


@dataclass(frozen=True)
class BearingResult:
    target: Resolution
    bearing_deg: float | None = None
    compass: str | None = None
    distance_km: float | None = None
    reverse_deg: float | None = None
    long_path: Path | None = None
    message: str | None = None
    can_rotate: bool = False
    coarse_note: str | None = None


def lookup(
    home: LatLon,
    target: Resolution,
    home_region: str | None = None,
    include_long_path: bool = False,
    freq_mhz: float | None = None,
) -> BearingResult:
    if target.fixed_bearing is not None:
        bearing = target.fixed_bearing
        return BearingResult(target, bearing, compass_name(bearing), can_rotate=True)
    if target.location is None:
        return BearingResult(target, message="Grid needed")
    # Without region polygons, only the operator can say they are inside it.
    if target.region_code is not None and home_region is not None:
        if target.region_code == home_region.strip().upper():
            return BearingResult(target, message=f"You are in {target.region_code}")
    if is_home(home, target.location):
        return BearingResult(target, message="Home")

    path = short_path(home, target.location)
    return BearingResult(
        target,
        bearing_deg=path.bearing_deg,
        compass=compass_name(path.bearing_deg),
        distance_km=path.distance_km,
        reverse_deg=short_path(target.location, home).bearing_deg,
        long_path=long_path(path) if include_long_path else None,
        can_rotate=True,
        coarse_note=coarse_location_note(target.grid_text, freq_mhz) if target.grid_text else None,
    )
