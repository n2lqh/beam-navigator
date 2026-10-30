"""Starts the built BeamNavigator.exe on a throwaway data folder (decision 36).

Skipped unless BEAMNAV_EXE names the built file:
    $env:BEAMNAV_EXE = "dist/BeamNavigator.exe"; uv run pytest tests/packaging
It never saves a QRZ login or opens Nets, so no lookup can start.
"""

import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from beam_navigator.store.db import SCHEMA_VERSION

EXE = os.environ.get("BEAMNAV_EXE")
pytestmark = pytest.mark.skipif(not EXE, reason="set BEAMNAV_EXE to a built BeamNavigator.exe")


def free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port: int = probe.getsockname()[1]
    probe.close()
    return port


def outside_pytest() -> dict[str, str]:
    """Without pytest's variables: NiceGUI sees PYTEST_* and expects its test harness."""
    return {k: v for k, v in os.environ.items() if not k.startswith("PYTEST")}


def stop(process: subprocess.Popen[bytes]) -> None:
    """A one-file build runs as a launcher and the app: stop both."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
    else:
        process.kill()
    process.wait(timeout=10)


def test_exe_starts_and_makes_the_database(tmp_path: Path) -> None:
    assert EXE is not None
    port = free_port()
    process = subprocess.Popen(
        [str(Path(EXE).resolve()), "--data-dir", str(tmp_path), "--port", str(port),
         "--no-browser"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=outside_pytest(),
    )  # fmt: skip
    try:
        deadline = time.monotonic() + 30
        status = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/welcome") as reply:
                    status = reply.status
                    break
            except OSError:
                time.sleep(0.5)
        assert status == 200
    finally:
        stop(process)
    db = sqlite3.connect(tmp_path / "beamnav.db")
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    db.close()
