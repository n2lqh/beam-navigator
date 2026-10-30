import pytest

from beam_navigator.core.maidenhead import GridError, grid_center, is_grid


# Centres follow from the Maidenhead definition: field 20° x 10°, then /10, /24,
# /10, /24; centre = south-west corner + half a cell (acceptance 3).
@pytest.mark.parametrize(
    ("grid", "lat", "lon"),
    [
        ("FN20", 40.5, -75.0),
        ("FN20ok", 40.4375, -74.791667),
        ("FM29pt", 39.8125, -74.708333),
        ("FM29pt42", 39.802083, -74.7125),
        ("FM29pt42ab", 39.800260, -74.716493),
        ("AA00", -89.5, -179.0),
        ("RR99xx", 89.979167, 179.958333),
    ],
)
def test_grid_center(grid: str, lat: float, lon: float) -> None:
    center = grid_center(grid)
    assert center.lat == pytest.approx(lat, abs=1e-6)
    assert center.lon == pytest.approx(lon, abs=1e-6)


def test_case_insensitive() -> None:
    assert grid_center("fn20OK") == grid_center("FN20ok")


def test_surrounding_whitespace_ignored() -> None:
    assert grid_center(" FN20ok\n") == grid_center("FN20ok")


@pytest.mark.parametrize(
    "bad", ["FN2", "FN20o", "ZZ99", "FN20ok4", "SA00", "FN20yz", "", "F N20", "FN2O"]
)
def test_invalid_grid_rejected(bad: str) -> None:
    with pytest.raises(GridError):
        grid_center(bad)


def test_error_message_names_the_problem() -> None:
    with pytest.raises(GridError, match="Z"):
        grid_center("ZZ99")
    with pytest.raises(GridError, match="4, 6, 8 or 10"):
        grid_center("FN2")


@pytest.mark.parametrize(
    ("text", "expected"), [("FN20ok", True), ("fm29", True), ("W2KV", False), ("FN2", False)]
)
def test_is_grid(text: str, expected: bool) -> None:
    assert is_grid(text) is expected
