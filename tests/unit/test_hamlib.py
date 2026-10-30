import socket
import threading
from collections.abc import Callable, Iterator

import pytest

from beam_navigator.rotators.base import RotatorError
from beam_navigator.rotators.hamlib import HamlibAdapter


class FakeRotctld:
    """Accepts one client and answers each received line from a script (None = stay silent)."""

    def __init__(self, replies: list[bytes | None]) -> None:
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port: int = self.listener.getsockname()[1]
        self.replies = replies
        self.received: list[str] = []
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        conn, _ = self.listener.accept()
        with conn, conn.makefile("rb") as lines:
            for reply in self.replies:
                line = lines.readline()
                if not line:
                    return
                self.received.append(line.decode().rstrip("\n"))
                if reply is None:
                    self._done.wait(2)
                    return
                conn.sendall(reply)

    def close(self) -> None:
        self._done.set()
        self._thread.join(timeout=2)
        self.listener.close()


RotorFactory = Callable[[list[bytes | None]], tuple[HamlibAdapter, FakeRotctld]]


@pytest.fixture
def make_rotor() -> Iterator[RotorFactory]:
    created: list[tuple[HamlibAdapter, FakeRotctld]] = []

    def factory(replies: list[bytes | None]) -> tuple[HamlibAdapter, FakeRotctld]:
        server = FakeRotctld(replies)
        rotor = HamlibAdapter(port=server.port, timeout_s=0.5)
        assert rotor.connect().ok
        created.append((rotor, server))
        return rotor, server

    yield factory
    for rotor, server in created:
        rotor.disconnect()
        server.close()


def test_set_sends_documented_command(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor([b"RPRT 0\n"])
    result = rotor.set_azimuth(90)
    assert result.ok
    assert server.received == ["P 90.0 0.0"]


def test_highest_heading_never_becomes_360(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor([b"RPRT 0\n"])
    assert rotor.set_azimuth(359.9).ok
    assert server.received == ["P 359.9 0.0"]


def test_heading_above_359_9_sends_nothing(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor([b"RPRT 0\n"])
    assert not rotor.set_azimuth(359.99).ok
    assert server.received == []


def test_set_error_code_reported(make_rotor: RotorFactory) -> None:
    rotor, _server = make_rotor([b"RPRT -1\n"])
    result = rotor.set_azimuth(90)
    assert not result.ok
    assert "RPRT -1" in result.message


def test_out_of_range_sends_nothing(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor([b"RPRT 0\n"])
    result = rotor.set_azimuth(360)
    assert not result.ok
    assert server.received == []


def test_reads_position(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor([b"294.600000\n0.000000\n"])
    assert rotor.get_position() == pytest.approx(294.6)
    assert server.received == ["p"]


def test_position_error_raised(make_rotor: RotorFactory) -> None:
    rotor, _server = make_rotor([b"RPRT -5\n"])
    with pytest.raises(RotatorError, match="RPRT -5"):
        rotor.get_position()


def test_timeout_reported_and_not_retried(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor([None])
    result = rotor.set_azimuth(90)
    assert not result.ok
    assert "Not retried" in result.message
    assert server.received == ["P 90.0 0.0"]


def test_stop_command(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor([b"RPRT 0\n"])
    assert rotor.stop().ok
    assert server.received == ["S"]


def test_connection_refused_reported() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        unused_port = probe.getsockname()[1]
    rotor = HamlibAdapter(port=unused_port, timeout_s=0.5)
    result = rotor.connect()
    assert not result.ok
    assert "Could not connect" in result.message


def test_450_degree_rotor_accepts_overlap_positions() -> None:
    server = FakeRotctld([b"RPRT 0\n"])
    rotor = HamlibAdapter(port=server.port, timeout_s=0.5, az_min=0.0, az_max=450.0)
    try:
        assert rotor.connect().ok
        assert rotor.set_azimuth(400).ok
        rejected = rotor.set_azimuth(451)
        assert not rejected.ok
        assert "outside 0–450°" in rejected.message
        assert server.received == ["P 400.0 0.0"]
        assert rotor.capabilities().chooses_path is False
    finally:
        rotor.disconnect()
        server.close()


def test_default_range_still_rejects_400(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor([b"RPRT 0\n"])
    assert not rotor.set_azimuth(400).ok
    assert server.received == []


# Decision 8: a late reply is never read as the answer to the next command ---------------


class SlowFirstRotctld:
    """Answers the first connection's "p" only after the client has timed out; every later
    connection is answered at once with a different position."""

    def __init__(self, delay_s: float) -> None:
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(2)
        self.listener.settimeout(3)
        self.port: int = self.listener.getsockname()[1]
        self.delay_s = delay_s
        self.connections = 0
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        for number in range(2):
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            self.connections += 1
            with conn, conn.makefile("rb") as lines:
                if not lines.readline():
                    return
                if number == 0:
                    threading.Event().wait(self.delay_s)
                    try:
                        conn.sendall(b"350.0\n0.0\n")
                    except OSError:
                        pass
                    continue
                conn.sendall(b"90.0\n0.0\n")
                lines.readline()  # hold the connection until the client closes it

    def close(self) -> None:
        self._thread.join(timeout=3)
        self.listener.close()


def test_late_reply_is_not_read_as_next_answer() -> None:
    server = SlowFirstRotctld(delay_s=0.4)
    rotor = HamlibAdapter(port=server.port, timeout_s=0.2)
    try:
        assert rotor.connect().ok
        with pytest.raises(RotatorError, match="Not retried"):
            rotor.get_position()
        threading.Event().wait(0.4)  # the late reply arrives now
        assert rotor.get_position() == 90.0
        assert server.connections == 2
    finally:
        rotor.disconnect()
        server.close()
