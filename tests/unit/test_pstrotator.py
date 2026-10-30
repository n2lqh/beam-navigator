import socket
import threading
from collections.abc import Callable, Iterator

import pytest

from beam_navigator.rotators.base import RotatorError
from beam_navigator.rotators.pstrotator import PstRotatorAdapter, accepted_senders


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


class FakePstRotator:
    """Receives datagrams like PstRotator and, if told to, answers AZ? on the reply port."""

    def __init__(self, reply: bytes | None = None, reply_host: str | None = None) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.3)
        self.port: int = self.sock.getsockname()[1]
        self.reply_port = free_udp_port()
        self.reply = reply
        self.reply_host = reply_host
        self.received: list[bytes] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._running = True
        self._thread.start()

    def _serve(self) -> None:
        while self._running:
            try:
                data, sender = self.sock.recvfrom(1024)
            except (TimeoutError, OSError):
                continue
            self.received.append(data)
            if data == b"<PST>AZ?</PST>" and self.reply is not None:
                self._send_reply(self.reply, sender[0])

    def _send_reply(self, reply: bytes, sender_host: str) -> None:
        if self.reply_host is None:
            self.sock.sendto(reply, (sender_host, self.reply_port))
            return
        # A loopback-bound socket cannot send to a LAN address on Windows.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as lan:
            lan.sendto(reply, (self.reply_host, self.reply_port))

    def close(self) -> None:
        self._running = False
        self._thread.join()
        self.sock.close()


RotorFactory = Callable[..., tuple[PstRotatorAdapter, FakePstRotator]]


@pytest.fixture
def make_rotor() -> Iterator[RotorFactory]:
    servers: list[FakePstRotator] = []
    rotors: list[PstRotatorAdapter] = []

    def factory(
        reply: bytes | None = None, reply_host: str | None = None
    ) -> tuple[PstRotatorAdapter, FakePstRotator]:
        server = FakePstRotator(reply, reply_host)
        rotor = PstRotatorAdapter(
            port=server.port, reply_port=server.reply_port, timeout_s=0.5
        )
        assert rotor.connect().ok
        servers.append(server)
        rotors.append(rotor)
        return rotor, server

    yield factory
    for rotor in rotors:
        rotor.disconnect()
    for server in servers:
        server.close()


def wait_for(server: FakePstRotator, count: int) -> None:
    for _ in range(50):
        if len(server.received) >= count:
            return
        threading.Event().wait(0.01)


def test_set_sends_exactly_one_documented_command(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor()
    result = rotor.set_azimuth(85)
    threading.Event().wait(0.1)
    assert server.received == [b"<PST><AZIMUTH>85</AZIMUTH></PST>"]
    assert result.ok
    assert "position unverified" in result.message


@pytest.mark.parametrize(
    ("heading", "sent"),
    [(0.0, "0"), (294.6, "295"), (294.4, "294"), (359.4, "359"), (359.6, "359"), (359.9, "359")],
)
def test_heading_sent_as_whole_degrees(make_rotor: RotorFactory, heading: float, sent: str) -> None:
    rotor, server = make_rotor()
    rotor.set_azimuth(heading)
    wait_for(server, 1)
    assert server.received == [f"<PST><AZIMUTH>{sent}</AZIMUTH></PST>".encode()]


def test_out_of_range_sends_nothing(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor()
    result = rotor.set_azimuth(400)
    threading.Event().wait(0.1)
    assert not result.ok
    assert server.received == []


def test_stop_command(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor()
    rotor.stop()
    wait_for(server, 1)
    assert server.received == [b"<PST><STOP>1</STOP></PST>"]


def test_reads_position_from_reply_port(make_rotor: RotorFactory) -> None:
    rotor, _server = make_rotor(reply=b"AZ:123.4")
    assert rotor.get_position() == pytest.approx(123.4)
    assert rotor.last_reply == "AZ:123.4"


def lan_address() -> str:
    # connect() on UDP only picks a route; nothing is sent.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))
        except OSError:
            pytest.skip("No non-loopback IPv4 route on this machine")
        address: str = probe.getsockname()[0]
    if address.startswith("127.") or address == "0.0.0.0":
        pytest.skip("No non-loopback IPv4 address on this machine")
    return address


def test_reads_reply_sent_to_lan_address(make_rotor: RotorFactory) -> None:
    # PstRotatorAz on the same PC answers from and to the LAN address, not
    # loopback (docs/rotator-notes.md, live test 2026-10-27).
    rotor, _server = make_rotor(reply=b"AZ:85\r", reply_host=lan_address())
    assert rotor.get_position() == pytest.approx(85)


def test_timeout_reported_and_not_retried(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor(reply=None)
    with pytest.raises(RotatorError, match="Not retried"):
        rotor.get_position()
    assert server.received == [b"<PST>AZ?</PST>"]


def test_unreadable_reply_is_reported(make_rotor: RotorFactory) -> None:
    rotor, _server = make_rotor(reply=b"HELLO")
    with pytest.raises(RotatorError, match="HELLO"):
        rotor.get_position()


def test_reply_port_in_use_is_reported(make_rotor: RotorFactory) -> None:
    rotor, server = make_rotor(reply=b"AZ:10.0")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as squatter:
        squatter.bind(("0.0.0.0", server.reply_port))
        with pytest.raises(RotatorError, match="another program"):
            rotor.get_position()
    assert server.received == []


def test_not_connected_sends_nothing() -> None:
    rotor = PstRotatorAdapter()
    result = rotor.set_azimuth(90)
    assert not result.ok
    assert rotor.last_sent is None


def test_pstrotator_chooses_its_own_path() -> None:
    assert PstRotatorAdapter().capabilities().chooses_path is True


# Decision 7: only the rotator's own replies count --------------------------------------


def test_reply_from_another_host_is_ignored() -> None:
    reply_port = free_udp_port()
    # TEST-NET host: the query goes nowhere; the reply arrives from loopback instead.
    rotor = PstRotatorAdapter(host="192.0.2.1", port=9, reply_port=reply_port, timeout_s=0.5)
    assert rotor.connect().ok

    def stray_reply() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stray:
            for _ in range(4):
                stray.sendto(b"AZ:85\r", ("127.0.0.1", reply_port))
                threading.Event().wait(0.1)

    sender = threading.Thread(target=stray_reply, daemon=True)
    sender.start()
    try:
        with pytest.raises(RotatorError, match="Not retried"):
            rotor.get_position()
        assert rotor.last_reply is None
    finally:
        sender.join()
        rotor.disconnect()


def test_loopback_host_accepts_lan_sender() -> None:
    senders = accepted_senders("127.0.0.1")
    assert "127.0.0.1" in senders
    assert lan_address() in senders


def test_senders_resolved_once_per_adapter(
    make_rotor: RotorFactory, monkeypatch: pytest.MonkeyPatch
) -> None:  # final review: no hostname lookups on every read
    rotor, _server = make_rotor(reply=b"AZ:85\r")
    calls: list[str] = []
    real = socket.gethostbyname_ex

    def counting(name: str) -> tuple[str, list[str], list[str]]:
        calls.append(name)
        return real(name)

    monkeypatch.setattr(socket, "gethostbyname_ex", counting)
    for _ in range(3):
        assert rotor.get_position() == pytest.approx(85)
    assert len(calls) <= 1
