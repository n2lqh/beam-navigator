import math

import pytest
from geographiclib.geodesic import Geodesic  # type: ignore[import-untyped]

from beam_navigator.core.geometry import (
    COMPASS_POINTS,
    Path,
    coarse_location_note,
    compass_name,
    is_home,
    long_path,
    short_path,
)
from beam_navigator.core.maidenhead import grid_center
from beam_navigator.core.models import LatLon


def test_fm29pt_to_fn20ok_matches_geographiclib() -> None:  # acceptance 1
    home, target = grid_center("FM29pt"), grid_center("FN20ok")
    ref = Geodesic.WGS84.Inverse(home.lat, home.lon, target.lat, target.lon)
    path = short_path(home, target)
    assert path.bearing_deg == pytest.approx(ref["azi1"] % 360, abs=0.5)
    assert path.distance_km == pytest.approx(ref["s12"] / 1000, rel=0.005)
    assert 353 < path.bearing_deg < 355


def test_reverse_is_computed_not_added() -> None:  # acceptance 1
    home, target = grid_center("FM29pt"), grid_center("FN20ok")
    reverse = short_path(target, home)
    ref = Geodesic.WGS84.Inverse(target.lat, target.lon, home.lat, home.lon)
    assert reverse.bearing_deg == pytest.approx(ref["azi1"] % 360, abs=0.5)
    assert 173 < reverse.bearing_deg < 175


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("FM29pt", "FN10xi"),
        ("FM29pt", "FM18"),
        ("FN20ok", "FN31"),
        ("FM29pt42", "EN52"),
        ("FN31", "FM29jw"),
    ],
)
def test_paths_under_2000_km_match_geographiclib(a: str, b: str) -> None:
    start, end = grid_center(a), grid_center(b)
    ref = Geodesic.WGS84.Inverse(start.lat, start.lon, end.lat, end.lon)
    assert ref["s12"] < 2_000_000
    path = short_path(start, end)
    assert path.bearing_deg == pytest.approx(ref["azi1"] % 360, abs=0.5)
    assert path.distance_km == pytest.approx(ref["s12"] / 1000, rel=0.005)


def test_same_grid_is_home() -> None:  # acceptance 2
    assert is_home(grid_center("FM29pt"), grid_center("FM29pt"))
    assert not is_home(grid_center("FM29pt"), grid_center("FM29ps"))


def test_long_path() -> None:  # acceptance 4
    short = Path(354.2, 120.0)
    long = long_path(short)
    assert long.bearing_deg == pytest.approx(174.2)
    assert short.distance_km + long.distance_km == pytest.approx(40030.0)
    assert long_path(Path(270.0, 1.0)).bearing_deg == pytest.approx(90.0)


@pytest.mark.parametrize(
    ("bearing", "name"),
    [(0, "N"), (11.2, "N"), (11.3, "NNE"), (45, "NE"), (174, "S"), (337.5, "NNW"),
     (348.8, "N"), (359.9, "N")],
)
def test_compass_name(bearing: float, name: str) -> None:
    assert compass_name(bearing) == name


def test_compass_points_table() -> None:
    assert len(COMPASS_POINTS) == 16
    assert COMPASS_POINTS["N"] == 0.0
    assert COMPASS_POINTS["NNE"] == 22.5
    assert COMPASS_POINTS["SW"] == 225.0
    assert COMPASS_POINTS["NNW"] == 337.5


@pytest.mark.parametrize(("a", "b"), [("AA00", "RR99xx"), ("FM29pt", "RR99xx"), ("AA00", "AR09")])
def test_extreme_paths_are_finite(a: str, b: str) -> None:  # Review Focus 5
    path = short_path(grid_center(a), grid_center(b))
    assert 0 <= path.bearing_deg < 360
    assert math.isfinite(path.distance_km)


def test_antipodal_does_not_crash() -> None:  # Review Focus 5
    path = short_path(LatLon(40.0, -75.0), LatLon(-40.0, 105.0))
    assert 0 <= path.bearing_deg < 360
    assert path.distance_km == pytest.approx(math.pi * 6371.0)


def test_coarse_note_only_for_4_char_grid_at_1296_and_up() -> None:
    assert coarse_location_note("FN20", 1296.1) == "coarse location — ±50 km"
    assert coarse_location_note("fn20", 1296.0) == "coarse location — ±50 km"
    assert coarse_location_note("FN20", 432.1) is None
    assert coarse_location_note("FN20ok", 1296.1) is None
    assert coarse_location_note("FN20", None) is None
