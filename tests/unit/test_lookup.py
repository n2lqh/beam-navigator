import pytest

from beam_navigator.core.lookup import lookup
from beam_navigator.core.maidenhead import grid_center
from beam_navigator.core.targets import resolve

HOME = grid_center("FM29pt")


def test_grid_target() -> None:  # acceptance 1
    result = lookup(HOME, resolve("FN20ok"))
    assert result.bearing_deg is not None and 353 < result.bearing_deg < 355
    assert result.compass == "N"
    assert result.reverse_deg is not None and 173 < result.reverse_deg < 175
    assert result.distance_km is not None and result.distance_km > 0
    assert result.can_rotate
    assert result.message is None
    assert result.long_path is None


def test_same_grid_is_home() -> None:  # acceptance 2
    result = lookup(HOME, resolve("FM29pt"))
    assert result.message == "Home"
    assert result.bearing_deg is None
    assert not result.can_rotate


@pytest.mark.parametrize(("code", "bearing"), [("PA", 295), ("MD", 243)])
def test_region_centroid_bearing(code: str, bearing: float) -> None:  # acceptance 7
    result = lookup(HOME, resolve(code), home_region="NJ")
    assert result.bearing_deg == pytest.approx(bearing, abs=3)
    assert result.target.source == "region centroid"
    assert result.can_rotate


def test_inside_home_region() -> None:  # acceptance 8
    result = lookup(HOME, resolve("NJ"), home_region="nj")
    assert result.message == "You are in NJ"
    assert result.bearing_deg is None
    assert not result.can_rotate


def test_home_region_unknown_still_gives_bearing() -> None:
    assert lookup(HOME, resolve("NJ")).bearing_deg is not None


def test_fixed_heading_has_no_distance() -> None:
    result = lookup(HOME, resolve("247"))
    assert result.bearing_deg == 247
    assert result.compass == "WSW"
    assert result.distance_km is None
    assert result.reverse_deg is None
    assert result.can_rotate


def test_unknown_station_needs_grid() -> None:  # invariant 5
    result = lookup(HOME, resolve("W2KV"))
    assert result.message == "Grid needed"
    assert result.bearing_deg is None
    assert not result.can_rotate


def test_long_path_only_when_asked() -> None:  # acceptance 4
    result = lookup(HOME, resolve("FN20ok"), include_long_path=True)
    assert result.long_path is not None
    assert result.distance_km is not None
    assert result.distance_km + result.long_path.distance_km == pytest.approx(40030.0)


def test_coarse_note() -> None:  # spec 5
    assert lookup(HOME, resolve("FN20"), freq_mhz=1296.1).coarse_note == "coarse location — ±50 km"
    assert lookup(HOME, resolve("FN20ok"), freq_mhz=1296.1).coarse_note is None
