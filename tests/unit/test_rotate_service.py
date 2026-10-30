import socket
import sqlite3
from collections.abc import Iterator
from dataclasses import replace

import pytest

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
from beam_navigator.rotators.service import RotateService, build_adapter, build_test_adapter
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import CommandLog, RotatorRepository

UNVERIFIED = "Command sent — position unverified"


class FakeAdapter:
    """A controllable stand-in for a real rotator."""

    def __init__(
        self,
        feedback: bool = True,
        has_stop: bool = True,
        connect_ok: bool = True,
        position: float | None = 0.0,
        fail_read_after_move: bool = False,
    ) -> None:
        self.feedback = feedback
        self.has_stop = has_stop
        self.connect_ok = connect_ok
        self.position = position
        self.fail_read_after_move = fail_read_after_move
        self.moves: list[float] = []
        self.stops = 0
        self.last_sent: str | None = None
        self.last_reply: str | None = None

    def connect(self) -> ConnectionResult:
        return ConnectionResult(self.connect_ok, "connected" if self.connect_ok else "refused")

    def capabilities(self) -> Capabilities:
        return Capabilities(has_feedback=self.feedback, has_stop=self.has_stop)

    def get_position(self) -> float | None:
        if self.fail_read_after_move and self.moves:
            raise RotatorError("No reply on UDP port 12001 within 2 s. Not retried.")
        return self.position

    def set_azimuth(self, deg: float) -> CommandResult:
        self.moves.append(deg)
        self.last_sent = f"move {deg:g}"
        return CommandResult(True, "sent")

    def stop(self) -> CommandResult:
        self.stops += 1
        return CommandResult(True, "stopped")

    def disconnect(self) -> None:
        pass


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


def add_rotator(conn: sqlite3.Connection, **changes: object) -> int:
    profile = RotatorProfile(
        id=None, name="VHF", adapter="simulation", host=None, port=None, az_min=0.0,
        az_max=360.0, offset=0.0, speed_deg_per_s=None, bands=(), live=False,
        connection_tested=False,
    )  # fmt: skip
    saved = RotatorRepository(conn).save(replace(profile, **changes))  # type: ignore[arg-type]
    assert saved.id is not None
    return saved.id


def service_with(conn: sqlite3.Connection, adapter: RotatorAdapter) -> RotateService:
    # Both factories: a connection test must never reach the real rotator on this PC.
    return RotateService(conn, adapter_for=lambda p: adapter, tester_for=lambda p: adapter)


def test_one_command_per_press(conn: sqlite3.Connection) -> None:  # acceptance 26
    rotator = add_rotator(conn)
    sim = SimulationAdapter(az_max=360)
    service = service_with(conn, sim)
    for heading in (10.0, 90.0, 180.0):
        assert service.rotate(rotator, "test", heading).sent
    assert len(sim.commands) == 3
    for _ in range(5):
        service.preview(rotator, 45.0)
    service.test_connection(rotator)
    RotatorRepository(conn).save(replace(RotatorRepository(conn).get(rotator), name="VHF 2"))
    assert len(sim.commands) == 3


def test_outside_travel_sends_nothing(conn: sqlite3.Connection) -> None:  # acceptance 27
    rotator = add_rotator(conn, az_max=350.0)
    sim = SimulationAdapter(az_max=350)
    outcome = service_with(conn, sim).rotate(rotator, "PA", 355.0)
    assert outcome.sent is False
    assert sim.commands == []
    assert outcome.status == "355° is outside this rotator's travel (0–350°). Nothing was sent."
    [record] = CommandLog(conn).recent(rotator)
    assert record.ok is False and record.sent is None and record.target_label == "PA"


def test_no_feedback_is_unverified(conn: sqlite3.Connection) -> None:  # acceptance 28
    rotator = add_rotator(conn)
    outcome = service_with(conn, FakeAdapter(feedback=False)).rotate(rotator, "FN20ok", 354.2)
    assert outcome.sent and outcome.ok
    assert outcome.status == UNVERIFIED
    assert outcome.measured is None


def test_timeout_after_move_is_reported_not_retried(conn: sqlite3.Connection) -> None:  # 29
    rotator = add_rotator(conn)
    fake = FakeAdapter(fail_read_after_move=True)
    outcome = service_with(conn, fake).rotate(rotator, "FN20ok", 354.2)
    assert fake.moves == [354.2]
    assert outcome.sent
    assert outcome.status.startswith(UNVERIFIED + " (")
    assert "Not retried" in outcome.status
    assert len(CommandLog(conn).recent(rotator)) == 1


def test_connect_failure_sends_nothing(conn: sqlite3.Connection) -> None:  # Focus 4
    rotator = add_rotator(conn)
    fake = FakeAdapter(connect_ok=False)
    outcome = service_with(conn, fake).rotate(rotator, "FN20ok", 354.2)
    assert fake.moves == []
    assert outcome.sent is False
    assert outcome.status == "refused"
    assert len(CommandLog(conn).recent(rotator)) == 1


def test_measured_position_reported(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn)
    outcome = service_with(conn, SimulationAdapter(az_max=360)).rotate(rotator, "FN20ok", 354.2)
    assert outcome.status == "Commanded 354.2°, measured 354.2°"
    assert outcome.measured == pytest.approx(354.2)
    [record] = CommandLog(conn).recent(rotator)
    assert (record.requested_true, record.ok, record.measured) == (354.2, True, 354.2)


def test_yaesu_takes_the_overlap(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn, az_max=450.0)
    sim = SimulationAdapter(start_azimuth=350, az_max=450)
    outcome = service_with(conn, sim).rotate(rotator, "CLUB", 10.0)
    assert sim.commands[-1].azimuth == 370
    assert outcome.plan.direction == "clockwise"


def test_preview_never_builds_an_adapter(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn, az_max=450.0)

    def refuse(profile: RotatorProfile) -> RotatorAdapter:
        raise AssertionError("preview must not touch a rotator")

    plan = RotateService(conn, adapter_for=refuse).preview(rotator, 10.0, current_rotor=350.0)
    assert plan.rotor_target == 370


def test_not_live_profile_is_simulated(conn: sqlite3.Connection) -> None:  # invariant 8
    rotator = add_rotator(conn, adapter="pstrotator", host="127.0.0.1", port=12000)
    profile = RotatorRepository(conn).get(rotator)
    assert isinstance(build_adapter(profile), SimulationAdapter)


def test_connection_test_is_recorded_and_moves_nothing(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn, adapter="pstrotator", host="127.0.0.1", port=12000)
    fake = FakeAdapter()
    assert service_with(conn, fake).test_connection(rotator).ok
    assert fake.moves == [] and fake.stops == 0
    assert RotatorRepository(conn).get(rotator).connection_tested is True
    failing = FakeAdapter(connect_ok=False)
    assert not service_with(conn, failing).test_connection(rotator).ok
    assert RotatorRepository(conn).get(rotator).connection_tested is False


def test_stop(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn)
    sim = SimulationAdapter(az_max=360)
    service_with(conn, sim).stop(rotator)
    assert [c.command for c in sim.commands] == ["stop"]
    [record] = CommandLog(conn).recent(rotator)
    assert record.target_label == "Stop" and record.requested_true is None
    no_stop = FakeAdapter(has_stop=False)
    with pytest.raises(ValueError):
        service_with(conn, no_stop).stop(rotator)
    assert no_stop.stops == 0


def test_simulated_rotor_remembers_position_between_presses(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn)
    service = RotateService(conn)  # default adapter_for builds a simulation once
    service.rotate(rotator, "a", 90.0)
    second = service.rotate(rotator, "b", 100.0)
    assert second.plan.rotor_from == 90
    assert second.plan.travel_deg == 10


# Final review findings ----------------------------------------------------------------


class RecordingAdapter(FakeAdapter):
    """Like a real adapter, a position read overwrites last_sent."""

    def __init__(self, refuse: bool = False, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.refuse = refuse

    def get_position(self) -> float | None:
        self.last_sent = "<PST>AZ?</PST>"
        return super().get_position()

    def set_azimuth(self, deg: float) -> CommandResult:
        if self.refuse:
            return CommandResult(False, "Heading outside 0–359.9°. Nothing was sent.")
        super().set_azimuth(deg)
        self.last_sent = f"<PST><AZIMUTH>{deg:g}</AZIMUTH></PST>"
        return CommandResult(True, "sent")


def test_log_records_the_move_not_the_query(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn)
    service_with(conn, RecordingAdapter()).rotate(rotator, "FN20ok", 90.0)
    [record] = CommandLog(conn).recent(rotator)
    assert record.sent == "<PST><AZIMUTH>90</AZIMUTH></PST>"


def test_refused_move_is_not_logged_as_sent(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn)
    outcome = service_with(conn, RecordingAdapter(refuse=True)).rotate(rotator, "x", 90.0)
    assert outcome.sent is False
    assert outcome.ok is False
    [record] = CommandLog(conn).recent(rotator)
    assert record.sent is None


def test_reading_while_moving_is_not_a_result(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn, speed_deg_per_s=6.0)
    sim = SimulationAdapter(start_azimuth=0, speed_deg_per_s=6, az_max=360)
    outcome = service_with(conn, sim).rotate(rotator, "FN20ok", 90.0)
    assert "measured" not in outcome.status
    assert outcome.status.startswith("Command sent — rotor read 0.0° just after sending")


def test_connection_test_uses_the_real_adapter_type(conn: sqlite3.Connection) -> None:
    # Critical finding: a non-live profile must not be "tested" against the simulator.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]  # nothing listens here once closed
    rotator = add_rotator(conn, adapter="hamlib", host="127.0.0.1", port=closed_port)
    profile = RotatorRepository(conn).get(rotator)
    assert isinstance(build_test_adapter(profile), HamlibAdapter)
    assert isinstance(build_adapter(profile), SimulationAdapter)  # Rotate stays simulated
    result = RotateService(conn).test_connection(rotator)
    assert result.ok is False
    assert RotatorRepository(conn).get(rotator).connection_tested is False


def test_pstrotator_test_adapter_is_real() -> None:
    profile = RotatorProfile(
        id=1, name="VHF", adapter="pstrotator", host="127.0.0.1", port=12000, az_min=0.0,
        az_max=450.0, offset=0.0, speed_deg_per_s=None, bands=(), live=False,
        connection_tested=False,
    )  # fmt: skip
    assert isinstance(build_test_adapter(profile), PstRotatorAdapter)  # built, never connected


# Plan 2b: remembered position, read and test move -------------------------------------


def test_preview_uses_last_known_position(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn)
    service = service_with(conn, SimulationAdapter(az_max=360))
    service.rotate(rotator, "a", 90.0)
    plan = service.preview(rotator, 100.0)
    assert plan.rotor_from == pytest.approx(90)
    assert plan.direction == "clockwise"


def test_preview_pstrotator_states_no_direction(conn: sqlite3.Connection) -> None:  # Focus 3
    rotator = add_rotator(conn, adapter="pstrotator", host="127.0.0.1", port=12000, az_max=450.0)

    def refuse(profile: RotatorProfile) -> RotatorAdapter:
        raise AssertionError("preview must not touch a rotator")

    plan = RotateService(conn, adapter_for=refuse, tester_for=refuse).preview(
        rotator, 30.0, current_rotor=40.0
    )
    assert plan.direction is None
    assert plan.path_verified is False


def test_read_position_never_moves(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn)
    fake = FakeAdapter(position=123.0)
    service = service_with(conn, fake)
    reading = service.read_position(rotator)
    assert (reading.rotor, reading.true) == (123.0, 123.0)
    assert fake.moves == [] and fake.stops == 0
    assert service.last_rotor(rotator) == 123.0
    assert CommandLog(conn).recent(rotator) == []


def test_read_position_error_reported(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn)
    fake = FakeAdapter(fail_read_after_move=True)
    service = service_with(conn, fake)
    service.rotate(rotator, "a", 90.0)
    reading = service.read_position(rotator)
    assert reading.rotor is None and reading.true is None
    assert "Not retried" in reading.message
    assert fake.moves == [90.0]


def test_read_position_without_feedback(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn)
    reading = service_with(conn, FakeAdapter(feedback=False)).read_position(rotator)
    assert reading.rotor is None
    assert reading.message == "This rotator does not report its position."


def test_test_move_touches_only_a_throwaway_simulator(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn, adapter="pstrotator", host="127.0.0.1", port=12000)

    def refuse(profile: RotatorProfile) -> RotatorAdapter:
        raise AssertionError("a test move must not touch the configured rotator")

    outcome = RotateService(conn, adapter_for=refuse, tester_for=refuse).test_move(rotator, 90.0)
    assert outcome.sent
    assert CommandLog(conn).recent(rotator) == []


def test_capabilities_do_not_connect(conn: sqlite3.Connection) -> None:
    rotator = add_rotator(conn)
    fake = FakeAdapter(connect_ok=False, has_stop=False)
    assert service_with(conn, fake).capabilities(rotator).has_stop is False


def test_simulated_position_not_used_after_profile_change(conn: sqlite3.Connection) -> None:
    # Final review I4: a simulator's position must not plan a live rotator's move.
    rotator = add_rotator(conn, adapter="hamlib", host="127.0.0.1", port=4533)
    service = service_with(conn, SimulationAdapter(az_max=360))
    service.rotate(rotator, "a", 90.0)
    assert service.preview(rotator, 40.0).rotor_from == pytest.approx(90)
    rotators = RotatorRepository(conn)
    rotators.record_connection_test(rotator, True)
    rotators.set_live(rotator, True)
    plan = service.preview(rotator, 40.0)
    assert plan.rotor_from is None
    assert plan.direction is None and not plan.path_verified
