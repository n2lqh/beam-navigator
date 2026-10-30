"""The controller's entry line keys (requirements 4.5; decisions 23 and 33).

Space moves on only where a space can never be typed (callsign, grid), as contest
loggers do; elsewhere it types a space, so "MARY ANN" and "CHERRY HILL" work.
"""

from typing import Literal

from beam_navigator.core.keymap import Keymap

FIELDS = ("callsign", "name", "grid", "qth", "report", "notes")
SPACE_ADVANCES = ("callsign", "grid")  # fixed, not remappable (decision 33)

KeyAction = Literal[
    "next", "previous", "log", "clear", "suggest_down", "suggest_up", "note", "type"
]
ENTRY_ACTIONS: tuple[KeyAction, ...] = (
    "note", "next", "previous", "log", "clear", "suggest_down", "suggest_up"
)  # fmt: skip


def key_action(
    field: str, code: str, ctrl: bool, alt: bool, shift: bool, keymap: Keymap
) -> KeyAction:
    """What a key does in this field; keys come from the keymap (decision 33)."""
    if code == "Space" and not (ctrl or alt or shift) and field in SPACE_ADVANCES:
        return "next"
    for action in ENTRY_ACTIONS:
        if keymap[action].matches(code, ctrl, alt, shift):
            if action in ("suggest_down", "suggest_up") and field != "callsign":
                return "type"
            return action
    return "type"


def next_field(field: str) -> str:
    index = FIELDS.index(field)
    return FIELDS[min(index + 1, len(FIELDS) - 1)]


def previous_field(field: str) -> str:
    return FIELDS[max(FIELDS.index(field) - 1, 0)]
