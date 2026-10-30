"""The only code that moves a rotator (invariant 2).

rotate() and stop() are called once per explicit press. preview() and
test_connection() never send a move. Every attempt is logged (spec 4.7).
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from beam_navigator.core.models import RotatorProfile
from beam_navigator.rotators.base import (
    Capabilities,
    CommandResult,
    ConnectionResult,
    RotatorAdapter,
    RotatorError,
)
from beam_navigator.rotators.hamlib import HamlibAdapter
from beam_navigator.rotators.pstrotator import PstRotatorAdapter
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.rotators.travel import MovePlan, TravelRange, plan_move
from beam_navigator.store.repositories import CommandLog, RotatorRepository

UNVERIFIED = "Command sent — position unverified"
# A reading this close to the target counts as arrived; PstRotator works in whole degrees.
ARRIVED_WITHIN_DEG = 0.5


def _arc(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _simulation(profile: RotatorProfile) -> SimulationAdapter:
    return SimulationAdapter(
        start_azimuth=profile.az_min,
        speed_deg_per_s=profile.speed_deg_per_s,
        az_min=profile.az_min,
        az_max=profile.az_max,
    )


def build_test_adapter(profile: RotatorProfile) -> RotatorAdapter:
    """The profile's real adapter type, live or not: a connection test must reach the
    configured host and port, not the simulator. Only ever used to connect and read."""
    if profile.adapter == "simulation":
        return _simulation(profile)
    if profile.host is None or profile.port is None:
        raise ValueError(f"{profile.name} has no host and port to connect to.")
    if profile.adapter == "pstrotator":
        return PstRotatorAdapter(host=profile.host, port=profile.port)
    return HamlibAdapter(
        host=profile.host, port=profile.port, az_min=profile.az_min, az_max=profile.az_max
    )


def build_adapter(profile: RotatorProfile) -> RotatorAdapter:
    """For Rotate and Stop: a profile that is not live is always simulated (invariant 8)."""
    if not profile.live or profile.adapter == "simulation":
        return _simulation(profile)
    return build_test_adapter(profile)


@dataclass(frozen=True)
class RotateOutcome:
    plan: MovePlan
    sent: bool  # set_azimuth was called (at most once per press)
    ok: bool
    status: str
    measured: float | None


@dataclass(frozen=True)
class PositionReading:
    rotor: float | None  # rotor degrees, as the controller reports them
    true: float | None  # the same position as a true heading
    message: str


NO_FEEDBACK = "This rotator does not report its position."


def _travel(profile: RotatorProfile) -> TravelRange:
    return TravelRange(profile.az_min, profile.az_max, profile.offset)


class RotateService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        adapter_for: Callable[[RotatorProfile], RotatorAdapter] = build_adapter,
        tester_for: Callable[[RotatorProfile], RotatorAdapter] = build_test_adapter,
    ) -> None:
        self._rotators = RotatorRepository(conn)
        self._log = CommandLog(conn)
        self._adapter_for = adapter_for
        self._tester_for = tester_for
        # One adapter per rotator, so a simulated rotor remembers where it is between
        # presses; rebuilt whenever the profile changes.
        self._adapters: dict[int, tuple[RotatorProfile, RotatorAdapter]] = {}
        # The last rotor position actually read this session, per rotator, with the
        # profile it was read under: after any profile change (going live, a new host)
        # it may describe a simulator, so it is not used (decision 19).
        self._last_rotor: dict[int, tuple[RotatorProfile, float]] = {}

    def forget(self) -> None:
        """After a restore: the rotators and positions known so far may not exist."""
        self._adapters.clear()
        self._last_rotor.clear()

    def _adapter(self, rotator_id: int) -> tuple[RotatorProfile, RotatorAdapter]:
        profile = self._rotators.get(rotator_id)
        cached = self._adapters.get(rotator_id)
        if cached is None or cached[0] != profile:
            cached = (profile, self._adapter_for(profile))
            self._adapters[rotator_id] = cached
        return cached

    def preview(
        self, rotator_id: int, target_true: float, current_rotor: float | None = None
    ) -> MovePlan:
        """The planned move, shown before Rotate. Touches no rotator."""
        profile = self._rotators.get(rotator_id)
        if current_rotor is None:
            current_rotor = self._known(rotator_id, profile)
        return plan_move(
            target_true,
            _travel(profile),
            current_rotor,
            profile.speed_deg_per_s,
            adapter_chooses_path=profile.adapter == "pstrotator",  # decision 15
        )

    def last_rotor(self, rotator_id: int) -> float | None:
        return self._known(rotator_id, self._rotators.get(rotator_id))

    def _known(self, rotator_id: int, profile: RotatorProfile) -> float | None:
        known = self._last_rotor.get(rotator_id)
        return known[1] if known is not None and known[0] == profile else None

    def capabilities(self, rotator_id: int) -> Capabilities:
        """What the Rotate adapter supports. Builds it if needed; never connects."""
        return self._adapter(rotator_id)[1].capabilities()

    def read_position(self, rotator_id: int) -> PositionReading:
        """The explicit Read position press, and progress polling. Never moves."""
        profile, adapter = self._adapter(rotator_id)
        if not adapter.capabilities().has_feedback:
            return PositionReading(None, None, NO_FEEDBACK)
        connection = adapter.connect()
        if not connection.ok:
            return PositionReading(None, None, connection.message)
        try:
            rotor = adapter.get_position()
        except RotatorError as exc:
            return PositionReading(None, None, str(exc))
        finally:
            adapter.disconnect()
        if rotor is None:
            return PositionReading(None, None, NO_FEEDBACK)
        self._last_rotor[rotator_id] = (profile, rotor)
        true = (rotor - profile.offset) % 360.0
        return PositionReading(rotor, true, f"Rotor reads {true:.1f}°")

    def test_move(self, rotator_id: int, target_true: float) -> RotateOutcome:
        """"Test move in simulation" (spec 4.8): a throwaway simulator with this profile's
        travel and speed. Never touches the configured rotator and is not logged."""
        profile = self._rotators.get(rotator_id)
        known = self._known(rotator_id, profile)
        simulator = SimulationAdapter(
            start_azimuth=profile.az_min if known is None else known,
            speed_deg_per_s=profile.speed_deg_per_s,
            az_min=profile.az_min,
            az_max=profile.az_max,
        )
        return self._press(None, profile, simulator, "Test move", target_true)

    def rotate(self, rotator_id: int, target_label: str, target_true: float) -> RotateOutcome:
        profile, adapter = self._adapter(rotator_id)
        return self._press(rotator_id, profile, adapter, target_label, target_true)

    def _press(
        self,
        rotator_id: int | None,
        profile: RotatorProfile,
        adapter: RotatorAdapter,
        target_label: str,
        target_true: float,
    ) -> RotateOutcome:
        """One press: at most one move. rotator_id None is a test move: not logged and
        not remembered."""
        caps = adapter.capabilities()

        def finish(
            plan: MovePlan,
            sent_text: str | None,
            ok: bool,
            status: str,
            measured: float | None = None,
        ) -> RotateOutcome:
            if rotator_id is not None:
                self._log.add(
                    rotator_id, target_label, target_true, sent_text, ok, status, measured
                )
            return RotateOutcome(plan, sent_text is not None, ok, status, measured)

        connection = adapter.connect()
        if not connection.ok:
            return finish(MovePlan(target_true), None, False, connection.message)
        try:
            current = self._read(adapter) if caps.has_feedback else None
            self._remember(rotator_id, profile, current)
            plan = plan_move(
                target_true,
                _travel(profile),
                current,
                profile.speed_deg_per_s,
                adapter_chooses_path=caps.chooses_path,
            )
            if plan.error is not None or plan.command_deg is None:
                return finish(plan, None, False, plan.error or "Nothing was sent.")
            # Capture exactly what this move sent: a later position read overwrites
            # last_sent, and an adapter that refuses leaves it as None.
            adapter.last_sent = None
            result = adapter.set_azimuth(plan.command_deg)  # the one move of this press
            sent_text = adapter.last_sent
            if not result.ok:
                return finish(plan, sent_text, False, result.message)
            if not caps.has_feedback:
                return finish(plan, sent_text, True, UNVERIFIED)
            try:
                measured = adapter.get_position()
            except RotatorError as exc:
                return finish(plan, sent_text, True, f"{UNVERIFIED} ({exc})")  # never retried
            if measured is None:
                return finish(plan, sent_text, True, UNVERIFIED)
            self._remember(rotator_id, profile, measured)
            measured_true = (measured - profile.offset) % 360.0
            if _arc(measured_true, target_true) > ARRIVED_WITHIN_DEG:
                # Read just after sending: the rotor is still on its way (invariant 6).
                status = (
                    f"Command sent — rotor read {measured_true:.1f}° just after sending; "
                    "the move is not confirmed yet"
                )
                return finish(plan, sent_text, True, status)
            status = f"Commanded {target_true:.1f}°, measured {measured_true:.1f}°"
            return finish(plan, sent_text, True, status, measured)
        finally:
            adapter.disconnect()

    def stop(self, rotator_id: int) -> CommandResult:
        """The explicit Stop press."""
        _, adapter = self._adapter(rotator_id)
        if not adapter.capabilities().has_stop:
            raise ValueError("This rotator has no stop command.")
        connection = adapter.connect()
        if not connection.ok:
            self._log.add(rotator_id, "Stop", None, None, False, connection.message, None)
            return CommandResult(False, connection.message)
        try:
            result = adapter.stop()
            self._log.add(rotator_id, "Stop", None, adapter.last_sent, result.ok, result.message,
                          None)  # fmt: skip
            return result
        finally:
            adapter.disconnect()

    def test_connection(self, rotator_id: int) -> ConnectionResult:
        """Connect and, where supported, read the position. Never moves the rotator.
        A UDP connect proves nothing, so a rotator with feedback passes only on a reply."""
        adapter = self._tester_for(self._rotators.get(rotator_id))  # fresh, never cached
        connection = adapter.connect()
        try:
            if connection.ok and adapter.capabilities().has_feedback:
                try:
                    position = adapter.get_position()
                    connection = ConnectionResult(True, f"Rotator answered: {position}°.")
                except RotatorError as exc:
                    connection = ConnectionResult(False, str(exc))
        finally:
            adapter.disconnect()
        self._rotators.record_connection_test(rotator_id, connection.ok)
        return connection

    def _remember(
        self, rotator_id: int | None, profile: RotatorProfile, rotor: float | None
    ) -> None:
        if rotator_id is not None and rotor is not None:
            self._last_rotor[rotator_id] = (profile, rotor)

    @staticmethod
    def _read(adapter: RotatorAdapter) -> float | None:
        try:
            return adapter.get_position()
        except RotatorError:
            return None  # unknown position: the plan says the path is unverified
