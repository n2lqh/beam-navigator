"""Virtual rotator: records every command and moves at a configured speed."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from beam_navigator.rotators.base import (
    Capabilities,
    CommandResult,
    ConnectionResult,
    range_error,
)


@dataclass(frozen=True)
class SimulatedCommand:
    at: float
    command: str
    azimuth: float | None


class SimulationAdapter:
    def __init__(
        self,
        start_azimuth: float = 0.0,
        speed_deg_per_s: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        az_min: float = 0.0,
        az_max: float = 359.9,
    ) -> None:
        self.speed_deg_per_s = speed_deg_per_s
        self.az_min = az_min
        self.az_max = az_max
        self.commands: list[SimulatedCommand] = []
        self.last_sent: str | None = None
        self.last_reply: str | None = None
        self._clock = clock
        self._from_az = start_azimuth
        self._target_az = start_azimuth
        self._move_started = clock()

    def connect(self) -> ConnectionResult:
        return ConnectionResult(True, "Simulation — no hardware connected.")

    def capabilities(self) -> Capabilities:
        return Capabilities(has_feedback=True, has_stop=True)

    def get_position(self) -> float:
        position = self._position()
        self.last_sent = "get_position"
        self.last_reply = f"{position:.1f}"
        return position

    def _position(self) -> float:
        # Travels along the numeric path, like a rotor with its stop at north.
        if self.speed_deg_per_s is None:
            return self._target_az
        travelled = (self._clock() - self._move_started) * self.speed_deg_per_s
        span = self._target_az - self._from_az
        if travelled >= abs(span):
            return self._target_az
        return self._from_az + travelled * (1 if span > 0 else -1)

    def set_azimuth(self, deg: float) -> CommandResult:
        error = range_error(deg, self.az_min, self.az_max)
        if error:
            return CommandResult(False, error)
        self._from_az = self._position()
        self._target_az = deg
        self._move_started = self._clock()
        self.last_sent = f"set_azimuth {deg:g}"
        self.commands.append(SimulatedCommand(self._move_started, "set_azimuth", deg))
        return CommandResult(True, f"Simulated rotor moving to {deg:g}°.")

    def stop(self) -> CommandResult:
        position = self._position()
        self._from_az = self._target_az = position
        self.last_sent = "stop"
        self.commands.append(SimulatedCommand(self._clock(), "stop", None))
        return CommandResult(True, f"Simulated rotor stopped at {position:.1f}°.")

    def disconnect(self) -> None:
        pass
