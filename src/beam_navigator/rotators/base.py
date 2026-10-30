"""Adapter interface shared by every rotator (requirements 4.7)."""

import math
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Capabilities:
    has_feedback: bool
    has_stop: bool
    # True when the controller picks the way round itself (PstRotator takes 0–359 only),
    # so a planned direction cannot be guaranteed.
    chooses_path: bool = False


@dataclass(frozen=True)
class ConnectionResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    message: str


class RotatorError(Exception):
    """A rotator could not answer: timeout, refused connection, or unreadable reply."""


class RotatorAdapter(Protocol):
    # Exact text of the last command sent and reply received, for the spike CLI
    # and the command log. None until something is sent or received.
    last_sent: str | None
    last_reply: str | None

    def connect(self) -> ConnectionResult: ...
    def capabilities(self) -> Capabilities: ...
    def get_position(self) -> float | None: ...
    def set_azimuth(self, deg: float) -> CommandResult: ...  # degrees in this adapter's range
    def stop(self) -> CommandResult: ...
    def disconnect(self) -> None: ...


def azimuth_error(deg_true: float) -> str | None:
    """Return why a heading is invalid, or None if it may be sent.

    Out-of-range values are rejected, never wrapped (invariants 4 and 7).
    """
    if not math.isfinite(deg_true):
        return f"Heading {deg_true} is not a number."
    if not 0.0 <= deg_true <= 359.9:
        return f"Heading {deg_true:g}° is outside 0–359.9°. Nothing was sent."
    return None


def range_error(deg: float, az_min: float, az_max: float) -> str | None:
    """Return why a rotor position is invalid for this travel, or None if it may be sent.

    Out-of-range values are rejected, never wrapped (invariant 7)."""
    if not math.isfinite(deg):
        return f"Position {deg} is not a number."
    if not az_min <= deg <= az_max:
        return f"Position {deg:g}° is outside {az_min:g}–{az_max:g}°. Nothing was sent."
    return None
