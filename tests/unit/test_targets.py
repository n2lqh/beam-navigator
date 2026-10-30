import math

import pytest

from beam_navigator.core.geometry import COMPASS_POINTS
from beam_navigator.core.maidenhead import grid_center
from beam_navigator.core.models import LatLon
from beam_navigator.core.regions import load_regions
from beam_navigator.core.targets import (
    COLLISION_DEFAULTS,
    AliasTarget,
    StationLocation,
    TargetError,
    builtin_meaning,
    resolve,
    validate_alias,
)


def no_station(call: str) -> StationLocation | None:
    return None


@pytest.mark.parametrize(
    ("text", "bearing"), [("N", 0), ("NE", 45), ("SW", 225), ("NNW", 337.5), ("nnw", 337.5)]
)
def test_compass(text: str, bearing: float) -> None:  # acceptance 5
    r = resolve(text)
    assert r.kind == "compass"
    assert r.fixed_bearing == bearing
    assert r.location is None


@pytest.mark.parametrize(
    ("text", "bearing"),
    [("247°", 247), ("247", 247), ("247 °", 247), ("360", 0), ("-0", 0), ("0", 0),
     ("359.9", 359.9)],
)
def test_heading(text: str, bearing: float) -> None:  # acceptance 6, Review Focus 3
    r = resolve(text)
    assert r.kind == "heading"
    assert r.fixed_bearing == bearing
    assert r.location is None


@pytest.mark.parametrize("text", ["400", "-5", "359.95", "nan", "inf", "1e2"])
def test_bad_heading_rejected(text: str) -> None:  # acceptance 6, Review Focus 3
    with pytest.raises(TargetError):
        resolve(text)


def test_ne_defaults_to_northeast_and_offers_nebraska() -> None:  # acceptance 9
    r = resolve("NE")
    assert r.kind == "compass"
    assert r.alternative == "st:NE"
    nebraska = resolve("st:NE")
    assert nebraska.kind == "region"
    assert nebraska.source == "region centroid"
    assert nebraska.region_code == "NE"
    assert resolve("dir:NE").fixed_bearing == 45


def test_every_collision_has_a_rule() -> None:  # spec 4.2
    collisions = set(COMPASS_POINTS) & set(load_regions())
    assert collisions <= set(COLLISION_DEFAULTS)


def test_region_resolves_to_centroid() -> None:
    r = resolve("pa")
    region = load_regions()["PA"]
    assert r.kind == "region"
    assert r.region_code == "PA"
    assert r.location == LatLon(region.lat, region.lon)
    assert r.source == "region centroid"
    assert r.alternative is None


def test_grid_keeps_original_text() -> None:
    r = resolve("FN20ok")
    assert r.kind == "grid"
    assert r.grid_text == "FN20ok"
    assert r.location == grid_center("FN20ok")
    assert r.source == "typed"


def test_alias_matches_typed_grid() -> None:  # acceptance 10
    aliases = {"CLUB": AliasTarget("grid", "FM29jw")}.get
    via_alias, typed = resolve("club", aliases=aliases), resolve("FM29jw")
    assert via_alias.location == typed.location
    assert via_alias.source == "alias"
    assert via_alias.label == "CLUB"


def test_alias_to_heading_and_coordinates() -> None:
    aliases = {
        "BEACON2M": AliasTarget("heading", "300"),
        "HILL": AliasTarget("coords", "40.1,-75.2"),
    }.get
    assert resolve("beacon2m", aliases=aliases).fixed_bearing == 300
    hill = resolve("HILL", aliases=aliases)
    assert hill.kind == "coordinates"
    assert hill.location == LatLon(40.1, -75.2)


def test_alias_to_station() -> None:
    aliases = {"NETCTL": AliasTarget("station", "W2KV")}.get
    stations = {"W2KV": StationLocation("W2KV", "FN20ok", None, "saved")}.get
    r = resolve("netctl", aliases=aliases, stations=stations)
    assert r.location == grid_center("FN20ok")
    assert r.source == "alias"


def test_builtin_names_win_over_aliases() -> None:
    # The store must refuse such alias names (plan 1c); the resolver never lets
    # an alias silently change what NC or N means.
    aliases = {"NC": AliasTarget("grid", "FN20ok"), "N": AliasTarget("heading", "90")}.get
    assert resolve("NC", aliases=aliases).region_code == "NC"
    assert resolve("N", aliases=aliases).fixed_bearing == 0


def test_known_station_uses_saved_grid() -> None:
    stations = {"W2KV": StationLocation("W2KV", "FN20ok", None, "saved")}.get
    r = resolve("w2kv", stations=stations)
    assert r.kind == "callsign"
    assert r.location == grid_center("FN20ok")
    assert r.source == "saved"


def test_exact_coordinates_override_grid() -> None:  # spec 5
    stations = {"W2KV": StationLocation("W2KV", "FN20ok", LatLon(40.44, -74.79), "saved")}.get
    assert resolve("W2KV", stations=stations).location == LatLon(40.44, -74.79)


def test_unknown_station_needs_grid() -> None:  # invariant 5
    r = resolve("W2KV", stations=no_station)
    assert r.needs_grid
    assert r.location is None
    assert resolve("W2KV").needs_grid


def test_messy_input_normalized() -> None:  # Review Focus 1
    assert resolve(" fn20OK ").location == resolve("FN20ok").location
    assert resolve(" NNW").fixed_bearing == 337.5


@pytest.mark.parametrize(
    "text", ["", "   ", "st:", "foo:NE", "FN2", "???", "st:XX", "grid:W2KV", "call:FN20"]
)
def test_junk_rejected(text: str) -> None:  # Review Focus 2
    with pytest.raises(TargetError):
        resolve(text)


@pytest.mark.parametrize(
    ("text", "kind"),
    [("FN20ok", "grid"), ("AB12", "grid"), ("W2KV", "callsign"), ("K1ABC/P", "callsign"),
     ("EA/K1ABC", "callsign"), ("PA", "region")],
)
def test_kind_detection(text: str, kind: str) -> None:  # Review Focus 4
    assert resolve(text, stations=no_station).kind == kind


@pytest.mark.parametrize("bad_grid", ["ZZ12", "", "FN2"])
def test_station_with_invalid_grid_needs_grid(bad_grid: str) -> None:  # review finding 1
    stations = {"W2KV": StationLocation("W2KV", bad_grid, None, "roster")}.get
    r = resolve("W2KV", stations=stations)
    assert r.needs_grid
    assert r.location is None


@pytest.mark.parametrize(
    "bad", [LatLon(math.nan, 0.0), LatLon(95.0, 0.0), LatLon(0.0, 400.0), LatLon(0.0, math.inf)]
)
def test_station_with_invalid_coordinates_falls_back_to_grid(bad: LatLon) -> None:  # finding 2
    stations = {"W2KV": StationLocation("W2KV", "FN20ok", bad, "saved")}.get
    assert resolve("W2KV", stations=stations).location == grid_center("FN20ok")
    no_grid = {"W2KV": StationLocation("W2KV", None, bad, "saved")}.get
    assert resolve("W2KV", stations=no_grid).needs_grid


@pytest.mark.parametrize("value", ["95,400", "nan,0", "0,inf", "40,-181", "40", "a,b"])
def test_coords_alias_out_of_range_rejected(value: str) -> None:  # review finding 2
    aliases = {"HILL": AliasTarget("coords", value)}.get
    with pytest.raises(TargetError, match="HILL"):
        resolve("HILL", aliases=aliases)


@pytest.mark.parametrize(
    ("name", "meaning"),
    [("NE", "compass point"), ("nc", "state or province"), ("FN20", "grid"),
     ("247", "heading"), ("400", "heading"), ("W2KV", "callsign"), ("CLUB", None),
     ("BEACON2M", None)],
)
def test_builtin_meaning(name: str, meaning: str | None) -> None:  # decision 12
    assert builtin_meaning(name) == meaning


def test_validate_alias_cleans_values() -> None:
    assert validate_alias("CLUB", AliasTarget("grid", " FM29jw ")) == AliasTarget("grid", "FM29jw")
    assert validate_alias("B", AliasTarget("heading", " 90° ")) == AliasTarget("heading", "90")
    assert validate_alias("NETCTL", AliasTarget("station", " w2kv ")) == AliasTarget(
        "station", "W2KV"
    )
    assert validate_alias("HILL", AliasTarget("coords", "40.1, -75.2")) == AliasTarget(
        "coords", "40.1,-75.2"
    )


@pytest.mark.parametrize("name", ["NC", "N", "W2KV", "MY CLUB", "st:X", "", "  "])
def test_validate_alias_rejects_names(name: str) -> None:
    with pytest.raises(TargetError):
        validate_alias(name, AliasTarget("grid", "FM29jw"))


@pytest.mark.parametrize(
    "target",
    [AliasTarget("heading", "400"), AliasTarget("heading", "west"), AliasTarget("grid", "ZZ99"),
     AliasTarget("coords", "95,400"), AliasTarget("coords", "nan,0"),
     AliasTarget("station", "hello world")],
)
def test_validate_alias_rejects_values(target: AliasTarget) -> None:
    with pytest.raises(TargetError):
        validate_alias("CLUB", target)
