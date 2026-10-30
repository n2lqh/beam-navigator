"""Callsign recognition shared by the target resolver and the roster parser."""

import re

from beam_navigator.core.maidenhead import is_grid

_CALLSIGN = re.compile(
    r"(?:(?P<prefix>[A-Z0-9]{1,4})/)?"
    r"(?P<base>(?P<head>[A-Z0-9]{1,3})[0-9][A-Z]{1,4})"
    r"(?:/(?P<suffix>[A-Z0-9]{1,4}))?"
)


def normalize_callsign(text: str) -> str:
    return text.strip().upper()


def _match(text: str) -> re.Match[str] | None:
    call = normalize_callsign(text)
    match = _CALLSIGN.fullmatch(call)
    # Real prefixes carry a letter (W, 2E, VE); "123A" is not a callsign.
    if match is None or not any(c.isalpha() for c in match["head"]) or is_grid(call):
        return None
    return match


def is_callsign(text: str) -> bool:
    return _match(text) is not None


def base_callsign(text: str) -> str:
    match = _match(text)
    if match is None:
        raise ValueError(f"{text.strip()!r} is not a callsign.")
    return match["base"]
