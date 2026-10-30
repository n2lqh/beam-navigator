"""Turn typed text into a target: heading, compass point, grid, region, alias or callsign.

One resolver backs every target field (requirements 4.2). It never guesses a
location: an unknown station comes back with needs_grid=True.
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from beam_navigator.core.callsign import is_callsign, normalize_callsign
from beam_navigator.core.geometry import COMPASS_POINTS
from beam_navigator.core.maidenhead import grid_center, is_grid
from beam_navigator.core.models import LatLon
from beam_navigator.core.regions import load_regions


class TargetError(ValueError):
    """The text cannot be resolved to a target."""


@dataclass(frozen=True)
class AliasTarget:
    kind: Literal["grid", "coords", "station", "heading"]
    value: str


@dataclass(frozen=True)
class StationLocation:
    callsign: str
    grid: str | None
    latlon: LatLon | None
    source: Literal["saved", "roster"]


AliasLookup = Callable[[str], AliasTarget | None]
StationLookup = Callable[[str], StationLocation | None]

Kind = Literal["heading", "compass", "grid", "region", "callsign", "coordinates"]


@dataclass(frozen=True)
class Resolution:
    kind: Kind
    label: str
    source: str
    location: LatLon | None = None
    fixed_bearing: float | None = None
    grid_text: str | None = None
    alternative: str | None = None
    needs_grid: bool = False
    region_code: str | None = None


# Shortcodes that mean two things: (default reading, prefix of the alternative).
COLLISION_DEFAULTS: dict[str, tuple[str, str]] = {"NE": ("dir", "st")}

_PREFIXES = ("dir", "st", "grid", "call")
_HEADING = re.compile(r"-?\d+(\.\d+)?")


def resolve(
    text: str, aliases: AliasLookup | None = None, stations: StationLookup | None = None
) -> Resolution:
    cleaned = " ".join(text.split()).removesuffix("°").strip()
    if not cleaned:
        raise TargetError("Enter a heading, compass point, grid, state, alias or callsign.")

    prefix, sep, rest = cleaned.partition(":")
    if sep:
        kind = prefix.strip().lower()
        if kind not in _PREFIXES:
            raise TargetError(f"Unknown prefix {prefix!r}. Use dir:, st:, grid: or call:.")
        rest = rest.strip()
        if not rest:
            raise TargetError(f"Nothing after {kind}:.")
        return _resolve_forced(kind, rest, stations)

    for attempt in (_heading, _compass, _grid, _region):
        found = attempt(cleaned)
        if found is not None:
            return found
    if aliases is not None:
        alias = aliases(cleaned.upper())
        if alias is not None:
            return _resolve_alias(cleaned.upper(), alias, stations)
    if is_callsign(cleaned):
        return _station(cleaned, stations)
    raise TargetError(f"Not recognized: {cleaned!r}.")


def _resolve_forced(kind: str, text: str, stations: StationLookup | None) -> Resolution:
    if kind == "dir":
        found = _heading(text) or _compass(text, allow_collision=True)
    elif kind == "st":
        found = _region(text, allow_collision=True)
    elif kind == "grid":
        found = _grid(text)
    else:
        found = _station(text, stations) if is_callsign(text) else None
    if found is None:
        raise TargetError(f"{text!r} is not a valid {kind}: target.")
    return found


def _heading(text: str) -> Resolution | None:
    if not _HEADING.fullmatch(text):
        return None
    value = float(text)
    if value == 360:
        value = 0.0
    if not (math.isfinite(value) and 0 <= value <= 359.9):
        raise TargetError(f"Heading {text}° is outside 0–359.9°.")
    value = abs(value)  # "-0" is 0
    return Resolution("heading", f"{value:g}°", "typed", fixed_bearing=value)


def _compass(text: str, allow_collision: bool = False) -> Resolution | None:
    code = text.upper()
    if code not in COMPASS_POINTS:
        return None
    alternative = None
    collision = COLLISION_DEFAULTS.get(code)
    if collision is not None and not allow_collision:
        default, other = collision
        if default != "dir":
            return None
        alternative = f"{other}:{code}"
    return Resolution(
        "compass", code, "typed", fixed_bearing=COMPASS_POINTS[code], alternative=alternative
    )


def _grid(text: str) -> Resolution | None:
    if not is_grid(text):
        return None
    return Resolution("grid", text, "typed", location=grid_center(text), grid_text=text)


def _region(text: str, allow_collision: bool = False) -> Resolution | None:
    code = text.upper()
    region = load_regions().get(code)
    if region is None:
        return None
    alternative = None
    collision = COLLISION_DEFAULTS.get(code)
    if collision is not None and not allow_collision:
        default, other = collision
        if default != "st":
            return None
        alternative = f"{other}:{code}"
    return Resolution(
        "region",
        f"{region.name} ({code})",
        "region centroid",
        location=LatLon(region.lat, region.lon),
        alternative=alternative,
        region_code=code,
    )


def _valid_latlon(location: LatLon) -> bool:
    return -90 <= location.lat <= 90 and -180 <= location.lon <= 180  # False for NaN


def _station(text: str, stations: StationLookup | None) -> Resolution:
    call = normalize_callsign(text)
    station = stations(call) if stations is not None else None
    if station is None:
        return Resolution("callsign", call, "unknown", needs_grid=True)
    # Bad stored data is treated as unknown, never as a location (invariant 5).
    if station.latlon is not None and _valid_latlon(station.latlon):
        return Resolution(
            "callsign", call, station.source, location=station.latlon, grid_text=station.grid
        )
    if station.grid is not None and is_grid(station.grid):
        return Resolution(
            "callsign",
            call,
            station.source,
            location=grid_center(station.grid),
            grid_text=station.grid,
        )
    return Resolution("callsign", call, station.source, needs_grid=True)


def _resolve_alias(name: str, alias: AliasTarget, stations: StationLookup | None) -> Resolution:
    if alias.kind == "coords":
        try:
            lat_text, lon_text = alias.value.split(",")
            location = LatLon(float(lat_text), float(lon_text))
        except ValueError as exc:
            raise TargetError(f"Alias {name}: {alias.value!r} is not lat,lon.") from exc
        if not _valid_latlon(location):
            raise TargetError(f"Alias {name}: {alias.value!r} is not a place on Earth.")
        return Resolution("coordinates", name, "alias", location=location)
    if alias.kind == "station":
        target: Resolution | None = _station(alias.value, stations)
    elif alias.kind == "grid":
        target = _grid(alias.value)
    else:
        target = _heading(alias.value)
    if target is None:
        raise TargetError(f"Alias {name}: {alias.value!r} is not a valid {alias.kind}.")
    return Resolution(
        target.kind,
        name,
        "alias",
        location=target.location,
        fixed_bearing=target.fixed_bearing,
        grid_text=target.grid_text,
        needs_grid=target.needs_grid,
    )


def builtin_meaning(name: str) -> str | None:
    """What resolve() would read this text as without aliases, or None.

    Uses the resolver's own matchers in the same order, so the two never disagree
    (decision 12: built-in names win, so aliases must not use them)."""
    text = " ".join(name.split()).removesuffix("°").strip()
    if not text:
        return None
    try:
        if _heading(text) is not None:
            return "heading"
    except TargetError:
        return "heading"  # a number, even if out of range
    if _compass(text, allow_collision=True) is not None:
        return "compass point"
    if _grid(text) is not None:
        return "grid"
    if _region(text, allow_collision=True) is not None:
        return "state or province"
    if is_callsign(text):
        return "callsign"
    return None


def validate_alias(name: str, target: AliasTarget) -> AliasTarget:
    """Check an alias before it is saved; return the target with a cleaned value."""
    if not name.strip() or any(c.isspace() or c == ":" for c in name.strip()):
        raise TargetError(f"Alias name {name!r} must be one word without ':'.")
    meaning = builtin_meaning(name)
    if meaning is not None:
        raise TargetError(f"{name.strip().upper()} already means a {meaning}; choose another name.")
    value = target.value.strip()
    if target.kind == "heading":
        value = value.removesuffix("°").strip()
        if _HEADING.fullmatch(value) is None:
            raise TargetError(f"Alias heading {target.value!r} is not a number of degrees.")
        _heading(value)  # raises when out of range
    elif target.kind == "grid":
        if not is_grid(value):
            raise TargetError(f"Alias grid {target.value!r} is not a valid grid.")
    elif target.kind == "coords":
        try:
            lat_text, lon_text = value.split(",")
            location = LatLon(float(lat_text), float(lon_text))
        except ValueError as exc:
            raise TargetError(f"Alias coordinates {target.value!r} are not lat,lon.") from exc
        if not _valid_latlon(location):
            raise TargetError(f"Alias coordinates {target.value!r} are not a place on Earth.")
        value = f"{lat_text.strip()},{lon_text.strip()}"
    else:
        if not is_callsign(value):
            raise TargetError(f"Alias station {target.value!r} is not a callsign.")
        value = normalize_callsign(value)
    return AliasTarget(target.kind, value)
