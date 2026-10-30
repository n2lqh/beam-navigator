"""Keyboard shortcuts the operator can change (requirements 4.5; decision 33).

Keys are matched by physical key code (KeyboardEvent.code), as the number-pad sectors
always were. A chord is stored as text such as "Ctrl+Enter" or "Alt+KeyN"; only the
operator's changes are saved, and anything that no longer passes the rules falls back to
its default.
"""

import re
from dataclasses import dataclass
from typing import Literal

from beam_navigator.core.sector import NUMPAD_SECTORS

Scope = Literal["screen", "entry"]  # dashboard and live net; the net-control entry line
_MODIFIERS = ("Ctrl", "Alt", "Shift")
_CODE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_MODIFIER_CODES = {"ControlLeft", "ControlRight", "ShiftLeft", "ShiftRight", "AltLeft",
                   "AltRight", "MetaLeft", "MetaRight"}  # fmt: skip
_PUNCTUATION = {"Minus", "Equal", "BracketLeft", "BracketRight", "Backslash", "Semicolon",
                "Quote", "Comma", "Period", "Slash", "Backquote"}  # fmt: skip
MOVES_ROTATOR = {"rotate", "snap_back"}  # announcing a sector never moves it
_SAFE_TO_MOVE = {"Home", "End", "Insert", "PageUp", "PageDown"}
_BROWSER = {"Ctrl+KeyW", "Ctrl+KeyT", "Ctrl+Tab", "Ctrl+Shift+Tab", "Ctrl+KeyL", "Ctrl+KeyR",
            "Ctrl+KeyN", "F5", "F11", "F12", "Alt+F4"}  # fmt: skip  # Ctrl+N: a new window


@dataclass(frozen=True)
class Chord:
    code: str
    ctrl: bool = False
    alt: bool = False
    shift: bool = False

    def __post_init__(self) -> None:
        # The number-pad Enter is Enter everywhere, so it can never hide a clash
        # (final review: Ctrl+NumpadEnter saved as a sector key still rotated).
        object.__setattr__(self, "code", _same_key(self.code))

    def matches(self, code: str, ctrl: bool, alt: bool, shift: bool) -> bool:
        return Chord(code, ctrl, alt, shift) == self


def _same_key(code: str) -> str:
    return "Enter" if code == "NumpadEnter" else code


@dataclass(frozen=True)
class Action:
    id: str
    scope: Scope
    label: str
    default: Chord


ACTIONS: tuple[Action, ...] = (
    Action("rotate", "screen", "Rotate to the target", Chord("Enter", ctrl=True)),
    Action("snap_back", "screen", "Snap back to net control", Chord("Home")),
    *(Action(f"sector_{sector}", "screen", f"Announce sector {sector}", Chord(code))
      for code, sector in NUMPAD_SECTORS.items()),
    Action("next", "entry", "Next field", Chord("Tab")),
    Action("previous", "entry", "Previous field", Chord("Tab", shift=True)),
    Action("log", "entry", "Log the check-in", Chord("Enter")),
    Action("clear", "entry", "Clear the line", Chord("Escape")),
    # Alt+N, not Ctrl+N: Chrome and Edge open a new window on Ctrl+N (owner, 2026-10-29).
    Action("note", "entry", "Add a station note", Chord("KeyN", alt=True)),
    Action("suggest_down", "entry", "Next suggestion", Chord("ArrowDown")),
    Action("suggest_up", "entry", "Previous suggestion", Chord("ArrowUp")),
)  # fmt: skip
_BY_ID = {action.id: action for action in ACTIONS}

Keymap = dict[str, Chord]
DEFAULTS: Keymap = {action.id: action.default for action in ACTIONS}


def parse_chord(text: str) -> Chord:
    """"Ctrl+Alt+Shift+Code", modifiers optional but in that order, each at most once."""
    *mods, code = text.split("+")
    if not _CODE.fullmatch(code) or any(m not in _MODIFIERS for m in mods):
        raise ValueError(f"{text!r} is not a key.")
    if mods != [m for m in _MODIFIERS if m in mods]:
        raise ValueError(f"{text!r} is not a key.")
    return Chord(code, ctrl="Ctrl" in mods, alt="Alt" in mods, shift="Shift" in mods)


def _mods(chord: Chord) -> list[str]:
    return [m for m, on in zip(_MODIFIERS, (chord.ctrl, chord.alt, chord.shift), strict=True) if on]


def stored(chord: Chord) -> str:
    return "+".join([*_mods(chord), chord.code])


def label(chord: Chord) -> str:
    """For people: "Alt+N", "Numpad 8", "5"."""
    code = chord.code
    if code.startswith("Key") and len(code) == 4:
        code = code[3:]
    elif code.startswith("Digit") and len(code) == 6:
        code = code[5:]
    elif code.startswith("Numpad"):
        code = f"Numpad {code[6:]}"
    return "+".join([*_mods(chord), code])


def _types_a_character(chord: Chord) -> bool:
    if chord.ctrl or chord.alt:
        return False
    code = chord.code
    return (
        code == "Space" or code in _PUNCTUATION or code == "NumpadDecimal"
        or (code.startswith("Key") and len(code) == 4)
        or (code.startswith("Digit") and len(code) == 6)
        or (code.startswith("Numpad") and code[6:].isdigit())
    )  # fmt: skip


def _safe_to_move(chord: Chord) -> bool:
    """A key that moves the rotator: with Ctrl or Alt, or a key that never types and is
    not used to work a control (F-keys, Home, End, Insert, Page Up/Down, number pad).
    A plain letter, Space, Enter or arrow could fire while a dropdown has focus
    (final review: invariant 2)."""
    code = chord.code
    return (
        chord.ctrl or chord.alt
        or (code.startswith("F") and code[1:].isdigit())
        or code in _SAFE_TO_MOVE or code.startswith("Numpad")
    )  # fmt: skip


def _rule(action: Action, chord: Chord) -> str | None:
    """The rules that do not depend on the other keys."""
    shown = label(chord)
    if chord.code in _MODIFIER_CODES:
        return "Press a key, not just Ctrl, Alt or Shift."
    if stored(chord) in _BROWSER:
        return f"The browser keeps {shown} for itself."
    if action.scope == "screen" and chord.code == "Tab" and not (chord.ctrl or chord.alt):
        return "Tab moves between buttons; choose another key."
    if action.id in MOVES_ROTATOR and not _safe_to_move(chord):
        return (
            "Keys that move the rotator need Ctrl or Alt, or a key such as F9, Home or a"
            " number-pad key."
        )
    if action.scope == "entry" and _types_a_character(chord):
        return f"{shown} types a character, so it can't be an entry-line key."
    return None


def _clash(keymap: Keymap, action: Action, chord: Chord) -> Action | None:
    for other in ACTIONS:
        if other.id != action.id and other.scope == action.scope and keymap.get(other.id) == chord:
            return other
    return None


def check(keymap: Keymap, action_id: str, chord: Chord) -> str | None:
    """Why this chord can't be bound to this action, or None if it can."""
    action = _BY_ID[action_id]
    refusal = _rule(action, chord)
    if refusal is not None:
        return refusal
    other = _clash(keymap, action, chord)
    return None if other is None else f"{label(chord)} is already used for {other.label}."


def resolve(overrides: dict[str, str]) -> tuple[Keymap, bool]:
    """The defaults with the operator's changes applied as a whole, so a swap made in two
    steps survives (final review). A change that is unknown, unreadable or breaks a rule is
    dropped; changes that still clash go back to their defaults until none do."""
    keymap = dict(DEFAULTS)
    discarded = any(key not in _BY_ID for key in overrides)
    changed: set[str] = set()
    for action in ACTIONS:
        text = overrides.get(action.id)
        if text is None:
            continue
        try:
            chord = parse_chord(text)
        except ValueError:
            discarded = True
            continue
        if _rule(action, chord) is not None:
            discarded = True
            continue
        keymap[action.id] = chord
        changed.add(action.id)
    while clashing := {i for i in changed if _clash(keymap, _BY_ID[i], keymap[i]) is not None}:
        for action_id in clashing:
            keymap[action_id] = DEFAULTS[action_id]
        changed -= clashing
        discarded = True
    return keymap, discarded
