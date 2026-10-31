import pytest

from beam_navigator.core.keymap import DEFAULTS, Keymap, parse_chord
from beam_navigator.entry_keys import FIELDS, key_action, next_field, previous_field


def act(field: str, code: str, ctrl: bool = False, shift: bool = False,
        keymap: Keymap = DEFAULTS, alt: bool = False) -> str:  # fmt: skip
    return key_action(field, code, ctrl, alt, shift, keymap)


def test_field_order() -> None:
    assert FIELDS == ("callsign", "name", "grid", "qth", "report", "notes")


@pytest.mark.parametrize("field", FIELDS)
def test_tab_enter_escape_everywhere(field: str) -> None:
    assert act(field, "Tab") == "next"
    assert act(field, "Tab", shift=True) == "previous"
    assert act(field, "Enter") == "log"
    assert act(field, "NumpadEnter") == "log"
    assert act(field, "Escape") == "clear"
    assert act(field, "KeyN", alt=True) == "note"  # Alt+N: Chrome and Edge keep Ctrl+N
    assert act(field, "KeyN", ctrl=True) == "type"
    assert act(field, "KeyN", alt=True, shift=True) == "type"  # chords match exactly
    assert act(field, "KeyA") == "type"


def test_space_advances_where_no_space_can_be_typed() -> None:
    assert act("callsign", "Space") == "next"
    assert act("grid", "Space") == "next"


@pytest.mark.parametrize("field", ["name", "qth", "report", "notes"])
def test_space_types_in_free_text_fields(field: str) -> None:  # Focus 1
    assert act(field, "Space") == "type"


def test_arrows_only_in_callsign() -> None:
    assert act("callsign", "ArrowDown") == "suggest_down"
    assert act("callsign", "ArrowUp") == "suggest_up"
    assert act("notes", "ArrowDown") == "type"


def test_remapped_log_key() -> None:  # decision 33
    keymap = {**DEFAULTS, "log": parse_chord("F2")}
    assert act("name", "F2", keymap=keymap) == "log"
    assert act("name", "Enter", keymap=keymap) == "type"


def test_space_stays_fixed_in_callsign() -> None:
    keymap = {**DEFAULTS, "next": parse_chord("F3")}
    assert act("callsign", "Space", keymap=keymap) == "next"
    assert act("callsign", "Tab", keymap=keymap) == "type"
    assert act("name", "Space", keymap=keymap) == "type"


def test_next_and_previous() -> None:
    assert next_field("callsign") == "name"
    assert next_field("report") == "notes"
    assert previous_field("name") == "callsign"


def test_ends_do_not_wrap() -> None:
    assert next_field("notes") == "notes"
    assert previous_field("callsign") == "callsign"


def test_next_field_within_given_fields() -> None:  # the participant's I-hear line
    three = ("callsign", "name", "grid")
    assert next_field("name", three) == "grid"
    assert next_field("grid", three) == "grid"
    assert previous_field("callsign", three) == "callsign"
    assert previous_field("grid", three) == "name"
