"""The keymap: actions, default chords and the rules for a new binding (spec 4.5;
decisions 22, 23 and 33)."""

import pytest

from beam_navigator.core.keymap import DEFAULTS, check, label, parse_chord, resolve, stored


def test_defaults_match_decisions_22_and_23() -> None:
    assert stored(DEFAULTS["rotate"]) == "Ctrl+Enter"
    assert stored(DEFAULTS["snap_back"]) == "Home"
    assert stored(DEFAULTS["sector_NE"]) == "Numpad9"
    assert stored(DEFAULTS["previous"]) == "Shift+Tab"
    assert stored(DEFAULTS["note"]) == "Alt+KeyN" and len(DEFAULTS) == 17


@pytest.mark.parametrize(
    "text", ["Ctrl+Enter", "Shift+Tab", "Ctrl+Alt+Shift+F9", "Numpad8", "Ctrl+KeyN"]
)
def test_parse_and_store_round_trip(text: str) -> None:
    assert stored(parse_chord(text)) == text


@pytest.mark.parametrize(
    "text", ["", "Ctrl+", "Shift+Ctrl+Enter", "Ctrl+Ctrl+Enter", "Hyper+F1", "Ctrl+Bad Key"]
)
def test_bad_chords_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse_chord(text)


def test_labels() -> None:
    assert [label(parse_chord(t)) for t in ("Ctrl+KeyN", "Numpad8", "Digit5", "Ctrl+Enter")] == [
        "Ctrl+N", "Numpad 8", "5", "Ctrl+Enter"
    ]  # fmt: skip


def test_enter_matches_numpad_enter() -> None:
    assert DEFAULTS["rotate"].matches("NumpadEnter", ctrl=True, alt=False, shift=False)
    assert not DEFAULTS["rotate"].matches("NumpadEnter", ctrl=False, alt=False, shift=False)
    assert not DEFAULTS["rotate"].matches("Enter", ctrl=True, alt=False, shift=True)


@pytest.mark.parametrize(
    ("action", "text", "message"),
    [
        ("rotate", "Home", "Home is already used for Rotate to net control."),
        ("log", "KeyL", "L types a character, so it can't be an entry-line key."),
        ("log", "Space", "Space types a character, so it can't be an entry-line key."),
        ("rotate", "Tab", "Tab moves between buttons; choose another key."),
        ("rotate", "Ctrl+KeyR", "The browser keeps Ctrl+R for itself."),
        ("note", "Ctrl+KeyN", "The browser keeps Ctrl+N for itself."),  # new window
        ("note", "ShiftLeft", "Press a key, not just Ctrl, Alt or Shift."),
    ],
)
def test_check_refuses(action: str, text: str, message: str) -> None:
    assert check(dict(DEFAULTS), action, parse_chord(text)) == message


def test_check_allows() -> None:
    keymap = dict(DEFAULTS)
    assert check(keymap, "rotate", parse_chord("F9")) is None
    assert check(keymap, "log", parse_chord("Alt+KeyL")) is None  # a modifier: types nothing
    assert check(keymap, "rotate", parse_chord("Ctrl+Enter")) is None  # its own chord
    assert check(keymap, "log", parse_chord("Home")) is None  # Home is a screen key; scopes differ


def test_resolve_discards_bad_overrides() -> None:
    keymap, discarded = resolve(
        {"rotate": "F9", "nonsense": "F1", "log": "KeyQ", "clear": "Hyper+F1"}
    )
    assert stored(keymap["rotate"]) == "F9"
    assert keymap["log"] == DEFAULTS["log"] and keymap["clear"] == DEFAULTS["clear"]
    assert discarded
    assert resolve({}) == (DEFAULTS, False)


def test_numpad_enter_is_enter() -> None:  # final review C1
    from beam_navigator.core.keymap import Chord

    assert Chord("NumpadEnter", ctrl=True) == DEFAULTS["rotate"]
    assert parse_chord("Ctrl+NumpadEnter") == parse_chord("Ctrl+Enter")
    assert check(dict(DEFAULTS), "sector_N", Chord("NumpadEnter", ctrl=True)) == (
        "Ctrl+Enter is already used for Rotate to the target."
    )
    assert check(dict(DEFAULTS), "next", Chord("NumpadEnter")) == (
        "Enter is already used for Log the check-in."
    )


def test_resolve_keeps_a_swap() -> None:  # final review C2: order must not matter
    keymap, discarded = resolve({"rotate": "Home", "snap_back": "Ctrl+Enter"})
    assert stored(keymap["rotate"]) == "Home" and stored(keymap["snap_back"]) == "Ctrl+Enter"
    assert not discarded
    keymap, discarded = resolve({"snap_back": "Ctrl+Enter"})  # a real clash: that one reverts
    assert keymap["snap_back"] == DEFAULTS["snap_back"] and discarded


@pytest.mark.parametrize("text", ["KeyR", "Space", "Enter", "ArrowUp", "Digit5", "Shift+KeyR"])
def test_rotator_keys_need_a_modifier_or_a_safe_key(text: str) -> None:  # final review I3
    message = (
        "Keys that move the rotator need Ctrl or Alt, or a key such as F9, Home or a"
        " number-pad key."
    )
    assert check(dict(DEFAULTS), "rotate", parse_chord(text)) == message
    assert check(dict(DEFAULTS), "snap_back", parse_chord(text)) == message


@pytest.mark.parametrize("text", ["F9", "Numpad5", "Alt+KeyR", "Ctrl+Space", "End", "PageUp"])
def test_rotator_keys_allowed(text: str) -> None:
    assert check(dict(DEFAULTS), "rotate", parse_chord(text)) is None


def test_sector_keys_may_be_plain() -> None:  # announcing never moves the rotator
    assert check(dict(DEFAULTS), "sector_N", parse_chord("KeyN")) is None
