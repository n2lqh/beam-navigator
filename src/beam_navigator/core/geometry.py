"""Great-circle bearing and distance on a spherical Earth (requirements 5)."""

import math
from dataclasses import dataclass

from beam_navigator.core.models import LatLon

EARTH_RADIUS_KM = 6371.0
LONG_PATH_TOTAL_KM = 40030.0
HOME_RADIUS_KM = 0.5
COARSE_FROM_MHZ = 1296.0

_COMPASS_NAMES = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]  # fmt: skip
COMPASS_POINTS: dict[str, float] = {name: i * 22.5 for i, name in enumerate(_COMPASS_NAMES)}


@dataclass(frozen=True)
class Path:
    bearing_deg: float
    distance_km: float


def _normalize(bearing_deg: float) -> float:
    result = bearing_deg % 360.0
    # A tiny negative input can round to exactly 360.0.
    return 0.0 if result >= 360.0 else result


def distance_km(origin: LatLon, target: LatLon) -> float:
    lat1, lat2 = math.radians(origin.lat), math.radians(target.lat)
    dlat = lat2 - lat1
    dlon = math.radians(target.lon - origin.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def short_path(origin: LatLon, target: LatLon) -> Path:
    lat1, lat2 = math.radians(origin.lat), math.radians(target.lat)
    dlon = math.radians(target.lon - origin.lon)
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = _normalize(math.degrees(math.atan2(y, x)))
    return Path(bearing, distance_km(origin, target))


def long_path(short: Path) -> Path:
    return Path(_normalize(short.bearing_deg + 180.0), LONG_PATH_TOTAL_KM - short.distance_km)


def is_home(origin: LatLon, target: LatLon, radius_km: float = HOME_RADIUS_KM) -> bool:
    return distance_km(origin, target) < radius_km


def compass_name(bearing_deg: float) -> str:
    index = int((_normalize(bearing_deg) + 11.25) // 22.5) % 16
    return _COMPASS_NAMES[index]


def coarse_location_note(grid_text: str, freq_mhz: float | None) -> str | None:
    if freq_mhz is None or freq_mhz < COARSE_FROM_MHZ or len(grid_text.strip()) != 4:
        return None
    return "coarse location — ±50 km"
