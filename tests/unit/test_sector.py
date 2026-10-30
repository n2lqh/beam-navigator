import pytest

from beam_navigator.core.sector import (
    CANT_TELL,
    DEFAULT_TOLERANCE_DEG,
    NUMPAD_SECTORS,
    SECTOR_UP,
    SECTORS,
    check_sector,
    sector_name,
)


def test_numpad_layout() -> None:
    assert NUMPAD_SECTORS == {
        "Numpad8": "N", "Numpad9": "NE", "Numpad6": "E", "Numpad3": "SE",
        "Numpad2": "S", "Numpad1": "SW", "Numpad4": "W", "Numpad7": "NW",
    }  # fmt: skip
    assert SECTORS == {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270,
                       "NW": 315}  # fmt: skip
    assert DEFAULT_TOLERANCE_DEG == 22.5


def test_acceptance_16() -> None:
    result = check_sector("S", 174.2)
    assert result.up is True
    assert result.message == SECTOR_UP == "YOUR SECTOR IS UP"


@pytest.mark.parametrize("sector", list(SECTORS))
def test_acceptance_17(sector: str) -> None:
    result = check_sector(sector, None)
    assert result.up is None
    assert result.message == CANT_TELL
    assert CANT_TELL == "Controller location unknown — can't tell if this call is for you."


def test_boundary_is_inclusive() -> None:
    assert check_sector("N", 22.5).up is True
    assert check_sector("NE", 22.5).up is True
    assert check_sector("N", 22.6).up is False


def test_wraps_north() -> None:
    assert check_sector("N", 350.0).up is True
    assert check_sector("NW", 350.0).up is False  # 35° from NW's centre
    assert sector_name(350.0) == "N"
    assert sector_name(174.2) == "S"


def test_not_my_sector_message() -> None:
    result = check_sector("N", 174.2)
    assert result.up is False
    assert result.message == "Not your sector — you are S of the controller."


def test_unknown_sector_rejected() -> None:
    with pytest.raises(ValueError):
        check_sector("NNE", 10.0)


def test_banner_never_claims_hearing() -> None:
    for sector in SECTORS:
        for position in (None, 0.0, 90.0, 174.2, 359.9):
            assert "hear" not in check_sector(sector, position).message.lower()
