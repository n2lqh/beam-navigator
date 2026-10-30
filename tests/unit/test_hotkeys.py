import pytest

from beam_navigator.core.keymap import DEFAULTS, Keymap, parse_chord
from beam_navigator.hotkeys import action_for


def press(
    code: str, key: str = "", ctrl: bool = False, screen: str = "live_net",
    keydown: bool = True, repeat: bool = False, keymap: Keymap = DEFAULTS,
) -> object:  # fmt: skip
    """key (the typed character) is kept for readability; matching is by code."""
    return action_for(code, ctrl, False, False, keydown, repeat, screen, keymap)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("code", "sector"),
    [("Numpad8", "N"), ("Numpad9", "NE"), ("Numpad6", "E"), ("Numpad3", "SE"),
     ("Numpad2", "S"), ("Numpad1", "SW"), ("Numpad4", "W"), ("Numpad7", "NW")],
)  # fmt: skip
def test_numpad_sectors(code: str, sector: str) -> None:
    assert press(code, code[-1]) == ("sector", sector)
    assert press(code, code[-1], screen="dashboard") is None


def test_rotate_and_snap_back() -> None:
    assert press("Enter", "Enter", ctrl=True) == "rotate"
    assert press("Enter", "Enter", ctrl=True, screen="dashboard") == "rotate"
    assert press("NumpadEnter", "Enter", ctrl=True) == "rotate"
    assert press("Enter", "Enter") is None  # plain Enter never rotates
    assert press("Home", "Home") == "snap_back"
    assert press("Home", "Home", screen="dashboard") is None


def test_repeat_and_keyup_ignored() -> None:  # Focus 1
    assert press("Home", "Home", repeat=True) is None
    assert press("Enter", "Enter", ctrl=True, repeat=True) is None
    assert press("Numpad2", "2", repeat=True) is None
    assert press("Home", "Home", keydown=False) is None


def test_top_row_digits_and_other_keys_ignored() -> None:
    assert press("Digit2", "2") is None
    assert press("KeyS", "s") is None
    assert press("Numpad5", "5") is None
    assert press("Numpad2", "2", ctrl=True) is None  # a modifier means it is not a sector call


def test_remapped_rotate() -> None:  # decision 33
    keymap = {**DEFAULTS, "rotate": parse_chord("F9")}
    assert press("F9", screen="dashboard", keymap=keymap) == "rotate"
    assert press("Enter", ctrl=True, screen="dashboard", keymap=keymap) is None  # old chord free
    assert press("F9", screen="dashboard", repeat=True, keymap=keymap) is None  # invariant 2


def test_remapped_sector() -> None:
    keymap = {**DEFAULTS, "sector_N": parse_chord("ArrowUp")}
    assert press("ArrowUp", keymap=keymap) == ("sector", "N")
    assert press("Numpad8", keymap=keymap) is None
    assert press("ArrowUp", screen="dashboard", keymap=keymap) is None  # sectors: live net only


def test_shift_and_alt_must_match() -> None:
    assert action_for("Enter", True, False, True, True, False, "dashboard", DEFAULTS) is None
    assert action_for("Home", False, True, False, True, False, "live_net", DEFAULTS) is None
