"""Keyboard shortcuts (requirements 4.4; decision 22). Keys come from the keymap
(decision 33).

A hotkey that moves the rotator is an explicit press (invariant 2), so only a fresh
keydown counts: auto-repeat from a held key never sends a second command.
"""

from typing import Literal

from beam_navigator.core.keymap import Keymap

Screen = Literal["dashboard", "live_net"]
Action = Literal["rotate", "snap_back"] | tuple[Literal["sector"], str]

SECTOR_PREFIX = "sector_"


def action_for(
    code: str, ctrl: bool, alt: bool, shift: bool, keydown: bool, repeat: bool,
    screen: Screen, keymap: Keymap,
) -> Action | None:  # fmt: skip
    if not keydown or repeat:
        return None

    def bound(action_id: str) -> bool:
        return keymap[action_id].matches(code, ctrl, alt, shift)

    if bound("rotate"):
        return "rotate"
    if screen != "live_net":
        return None
    if bound("snap_back"):
        return "snap_back"
    for action_id in keymap:  # by code: top-row digits never call a numpad sector
        if action_id.startswith(SECTOR_PREFIX) and bound(action_id):
            return ("sector", action_id.removeprefix(SECTOR_PREFIX))
    return None
