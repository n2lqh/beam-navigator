"""Acceptance test 30: Hamlib adapter against a real rotctld dummy rotator.

Skipped when rotctld is not installed; CI installs Hamlib.
"""

import shutil
import socket
import subprocess
import time
from collections.abc import Iterator

import pytest

from beam_navigator.rotators.hamlib import HamlibAdapter

ROTCTLD = shutil.which("rotctld")
pytestmark = pytest.mark.skipif(ROTCTLD is None, reason="rotctld (Hamlib) is not installed")


@pytest.fixture
def rotctld_port() -> Iterator[int]:
    assert ROTCTLD is not None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    process = subprocess.Popen([ROTCTLD, "-m", "1", "-T", "127.0.0.1", "-t", str(port)])
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        yield port
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_sets_and_reads_dummy_rotator(rotctld_port: int) -> None:
    rotor = HamlibAdapter(port=rotctld_port, timeout_s=5)
    assert rotor.connect().ok
    try:
        assert rotor.set_azimuth(90).ok
        position = None
        for _ in range(100):
            position = rotor.get_position()
            if abs(position - 90) < 1:
                break
            time.sleep(0.1)
        assert position == pytest.approx(90, abs=1)
    finally:
        rotor.disconnect()
