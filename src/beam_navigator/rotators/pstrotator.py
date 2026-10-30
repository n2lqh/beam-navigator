"""PstRotator / PstRotatorAz over UDP (requirements 4.7).

Commands go to the configured port; replies to AZ? arrive on port + 1.
Verify against the installed version and record findings in docs/rotator-notes.md.
"""

import math
import re
import socket
import time

from beam_navigator.rotators.base import (
    Capabilities,
    CommandResult,
    ConnectionResult,
    RotatorError,
    azimuth_error,
)

AZIMUTH_REPLY = re.compile(r"AZ:\s*(-?\d+(?:\.\d+)?)")


def accepted_senders(host: str) -> frozenset[str]:
    """Addresses a position reply may come from (decision 7). A PstRotatorAz on this PC
    replies from its LAN address, not loopback (decision 9), so a loopback host also
    accepts this PC's own addresses."""
    try:
        address = socket.gethostbyname(host)
    except OSError as exc:
        raise RotatorError(f"Cannot resolve rotator host {host!r}: {exc}") from exc
    if not address.startswith("127."):
        return frozenset({address})
    own = {"127.0.0.1", address}
    try:
        own.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass  # loopback replies still count
    return frozenset(own)


class PstRotatorAdapter:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 12000,
        reply_port: int | None = None,
        timeout_s: float = 2.0,
    ) -> None:
        self.host = host
        self.port = port
        self.reply_port = port + 1 if reply_port is None else reply_port
        self.timeout_s = timeout_s
        self.last_sent: str | None = None
        self.last_reply: str | None = None
        self._sock: socket.socket | None = None
        self._senders: frozenset[str] | None = None  # resolved once, not on every read

    def connect(self) -> ConnectionResult:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except OSError as exc:
            return ConnectionResult(False, f"Could not open a UDP socket: {exc}")
        return ConnectionResult(
            True,
            f"UDP to {self.host}:{self.port}. UDP has no handshake, "
            "so delivery is not confirmed.",
        )

    def capabilities(self) -> Capabilities:
        return Capabilities(has_feedback=True, has_stop=True, chooses_path=True)

    def set_azimuth(self, deg_true: float) -> CommandResult:
        error = azimuth_error(deg_true)
        if error:
            return CommandResult(False, error)
        # The documented command uses whole degrees; decimals are unverified.
        # Capped at 359: rounding up to 360 and wrapping to 0 could swing the
        # rotor the long way round on a north-stop rotor (invariant 7).
        whole = min(math.floor(deg_true + 0.5), 359)
        return self._send(f"<PST><AZIMUTH>{whole}</AZIMUTH></PST>")

    def stop(self) -> CommandResult:
        return self._send("<PST><STOP>1</STOP></PST>")

    def get_position(self) -> float:
        # Bind before asking so a fast reply is not missed. No SO_REUSEADDR:
        # on Windows it would let us steal a port another program owns.
        # All interfaces, even for a local PstRotator: it replies to the LAN
        # address, not loopback (docs/rotator-notes.md).
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            try:
                listener.bind(("0.0.0.0", self.reply_port))
            except OSError as exc:
                raise RotatorError(
                    f"Cannot listen for the reply on UDP port {self.reply_port}; "
                    f"another program may be using it ({exc})."
                ) from exc
            sent = self._send("<PST>AZ?</PST>")
            if not sent.ok:
                raise RotatorError(sent.message)
            return self._await_azimuth(listener)
        finally:
            listener.close()

    def disconnect(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _send(self, command: str) -> CommandResult:
        if self._sock is None:
            return CommandResult(False, "Not connected. Nothing was sent.")
        try:
            self._sock.sendto(command.encode("ascii"), (self.host, self.port))
        except OSError as exc:
            return CommandResult(False, f"Send failed: {exc}")
        self.last_sent = command
        return CommandResult(True, "Command sent — position unverified.")

    def _await_azimuth(self, listener: socket.socket) -> float:
        if self._senders is None:
            self._senders = accepted_senders(self.host)
        senders = self._senders
        deadline = time.monotonic() + self.timeout_s
        received: list[str] = []
        while (remaining := deadline - time.monotonic()) > 0:
            listener.settimeout(remaining)
            try:
                data, sender = listener.recvfrom(1024)
            except TimeoutError:
                break
            except OSError as exc:
                raise RotatorError(f"Receive failed: {exc}") from exc
            if sender[0] not in senders:
                continue  # not from the rotator: never shown as its position
            text = data.decode("ascii", errors="replace")
            received.append(text)
            self.last_reply = text
            match = AZIMUTH_REPLY.search(text)
            if match:
                return float(match.group(1))
        if received:
            raise RotatorError(f"No AZ: value in reply: {' | '.join(received)!r}")
        raise RotatorError(
            f"No reply on UDP port {self.reply_port} within {self.timeout_s:g} s. Not retried."
        )
