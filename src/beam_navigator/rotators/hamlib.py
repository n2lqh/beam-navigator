"""Hamlib rotctld over TCP (requirements 4.7).

Set: "P <az> <el>" (el 0.0, azimuth only). Get: "p" answers az and el lines.
Stop: "S". Set and stop answer "RPRT 0" on success, a negative code on error.
"""

import socket

from beam_navigator.rotators.base import (
    Capabilities,
    CommandResult,
    ConnectionResult,
    RotatorError,
    range_error,
)


class HamlibAdapter:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4533,
        timeout_s: float = 2.0,
        az_min: float = 0.0,
        az_max: float = 359.9,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        # rotctld takes positions in the rotor's own range, e.g. 0–450 for a 450° rotor.
        self.az_min = az_min
        self.az_max = az_max
        self.last_sent: str | None = None
        self.last_reply: str | None = None
        self._sock: socket.socket | None = None
        self._buffer = b""
        self._dropped = False

    def connect(self) -> ConnectionResult:
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout_s)
        except OSError as exc:
            return ConnectionResult(
                False, f"Could not connect to rotctld at {self.host}:{self.port}: {exc}"
            )
        return ConnectionResult(True, f"Connected to rotctld at {self.host}:{self.port}.")

    def capabilities(self) -> Capabilities:
        return Capabilities(has_feedback=True, has_stop=True)

    def set_azimuth(self, deg: float) -> CommandResult:
        error = range_error(deg, self.az_min, self.az_max)
        if error:
            return CommandResult(False, error)
        return self._report_command(f"P {deg:.1f} 0.0")

    def stop(self) -> CommandResult:
        return self._report_command("S")

    def get_position(self) -> float:
        try:
            self._send("p")
            first = self._read_line()
            if first.startswith("RPRT"):
                raise RotatorError(f"rotctld returned an error: {first}")
            elevation = self._read_line()
        except (TimeoutError, OSError) as exc:
            self._drop_connection()
            raise RotatorError(self._failure_text(exc)) from exc
        self.last_reply = f"{first}\n{elevation}"
        try:
            return float(first)
        except ValueError as exc:
            raise RotatorError(f"Unreadable azimuth from rotctld: {first!r}") from exc

    def disconnect(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        self._dropped = False

    def _report_command(self, command: str) -> CommandResult:
        try:
            self._send(command)
            reply = self._read_line()
        except (TimeoutError, OSError) as exc:
            self._drop_connection()
            return CommandResult(False, self._failure_text(exc))
        self.last_reply = reply
        if reply == "RPRT 0":
            return CommandResult(True, "rotctld accepted the command.")
        return CommandResult(False, f"rotctld rejected the command: {reply}")

    def _drop_connection(self) -> None:
        # A reply that arrives after a timeout would otherwise be read as the answer
        # to the next command (decision 8). The next command opens a fresh connection.
        if self._sock is not None:
            self._sock.close()
            self._sock = None
            self._dropped = True
        self._buffer = b""

    def _send(self, command: str) -> None:
        if self._sock is None and self._dropped:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout_s)
            self._dropped = False
        if self._sock is None:
            raise OSError("Not connected. Nothing was sent.")
        self._sock.sendall(f"{command}\n".encode("ascii"))
        self.last_sent = command

    def _read_line(self) -> str:
        if self._sock is None:
            raise OSError("Not connected.")
        while b"\n" not in self._buffer:
            chunk = self._sock.recv(1024)
            if not chunk:
                raise OSError("rotctld closed the connection.")
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line.decode("ascii", errors="replace").strip()

    def _failure_text(self, exc: Exception) -> str:
        if isinstance(exc, TimeoutError):
            return f"No reply from rotctld within {self.timeout_s:g} s. Not retried."
        return f"rotctld communication failed: {exc}"
