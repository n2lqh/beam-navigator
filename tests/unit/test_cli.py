import random
import re
import socket
from pathlib import Path

import pytest

from beam_navigator.cli import main, rotor_main
from beam_navigator.core.lookup import lookup
from beam_navigator.core.maidenhead import grid_center
from beam_navigator.core.targets import resolve


def test_simulation_moves_and_reports_position(capsys: pytest.CaptureFixture[str]) -> None:
    assert rotor_main(["--adapter", "simulation", "--az", "90"]) == 0
    out = capsys.readouterr().out
    assert "Sent:      set_azimuth 90" in out
    assert "Query:     get_position" in out
    assert "Reply:     90.0" in out
    assert "None" not in out
    assert "Position:  90.0°" in out


@pytest.mark.parametrize("heading", ["360", "400", "-5", "nan"])
def test_invalid_heading_rejected_before_connecting(
    heading: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as fake_rotator:
        fake_rotator.bind(("127.0.0.1", 0))
        fake_rotator.settimeout(0.2)
        port = str(fake_rotator.getsockname()[1])
        code = rotor_main(["--adapter", "pstrotator", "--port", port, f"--az={heading}"])
        assert code == 2
        assert "Rejected:" in capsys.readouterr().out
        with pytest.raises(TimeoutError):
            fake_rotator.recvfrom(1024)


def bind_below_ephemeral_range(sock: socket.socket) -> None:
    """Bind to a port P with P + 1 free, both below every OS's ephemeral range.

    The adapter listens for the reply on P + 1. Windows hands out ephemeral
    ports in sequence, so with P from bind(0) the adapter's own send socket
    would be given P + 1 first.
    """
    for _ in range(100):
        port = random.randrange(20000, 32000)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.bind(("0.0.0.0", port + 1))
            sock.bind(("127.0.0.1", port))
        except OSError:
            continue
        return
    pytest.fail("No free UDP port pair found")


def test_pstrotator_run_sends_one_move_and_one_query(capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as fake_rotator:
        bind_below_ephemeral_range(fake_rotator)
        fake_rotator.settimeout(0.2)
        port = str(fake_rotator.getsockname()[1])
        code = rotor_main(
            ["--adapter", "pstrotator", "--port", port, "--az", "90", "--timeout", "0.3"]
        )
        received = []
        while True:
            try:
                received.append(fake_rotator.recvfrom(1024)[0])
            except TimeoutError:
                break
    assert received == [b"<PST><AZIMUTH>90</AZIMUTH></PST>", b"<PST>AZ?</PST>"]
    assert code == 1
    assert "Position:  unverified" in capsys.readouterr().out


def test_hamlib_connection_failure_reported(capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = str(probe.getsockname()[1])
    code = rotor_main(["--adapter", "hamlib", "--port", port, "--az", "90", "--timeout", "0.5"])
    assert code == 1
    assert "Could not connect" in capsys.readouterr().out


def test_bearing_grid(capsys: pytest.CaptureFixture[str]) -> None:  # acceptance 1
    assert main(["bearing", "FN20ok", "--from", "FM29pt"]) == 0
    out = capsys.readouterr().out
    assert "Target:    FN20ok (grid, typed)" in out
    assert "Bearing:   354." in out
    assert "Reverse:   174." in out
    assert " km" in out


def test_bearing_requires_from() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["bearing", "FN20ok"])
    assert exc.value.code == 2


def test_bearing_bad_from(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bearing", "FN20ok", "--from", "ZZ99"]) == 2
    assert "Rejected:" in capsys.readouterr().out


def test_bearing_rejected_target(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bearing", "400", "--from", "FM29pt"]) == 2
    assert "Rejected:" in capsys.readouterr().out


def test_bearing_unknown_station(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bearing", "W2KV", "--from", "FM29pt"]) == 0
    assert "Grid needed" in capsys.readouterr().out


def test_bearing_miles(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bearing", "FN20ok", "--from", "FM29pt", "--units", "mi"]) == 0
    assert " mi" in capsys.readouterr().out


def test_bearing_home_region(capsys: pytest.CaptureFixture[str]) -> None:  # acceptance 8
    assert main(["bearing", "NJ", "--from", "FM29pt", "--home-region", "NJ"]) == 0
    assert "You are in NJ" in capsys.readouterr().out


def test_bearing_collision_offers_alternative(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bearing", "NE", "--from", "FM29pt"]) == 0
    assert "st:NE" in capsys.readouterr().out


def test_bearing_long_path_and_coarse_note(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["bearing", "FN20", "--from", "FM29pt", "--long-path", "--mhz", "1296.1"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Long path:" in out
    assert "coarse location — ±50 km" in out


FIXTURES = Path(__file__).parent.parent / "fixtures"
N3RG = str(FIXTURES / "n3rg_50mhz_2026-10-26.txt")


def test_parse_lists_rows_and_controller(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["parse", N3RG, "--from", "FM29pt"]) == 0
    out = capsys.readouterr().out
    assert "PUBLISHED (theirs)" in out
    assert "Check-ins: 22" in out
    assert "Controller: N3RG" in out
    assert len([line for line in out.splitlines() if line.lstrip()[:1].isdigit()]) == 22


def test_published_bearing_never_in_from_you_column(capsys: pytest.CaptureFixture[str]) -> None:
    # acceptance 12: N3ITT is printed with 0°, its bearing from FM29pt is not 0°
    assert main(["parse", N3RG, "--from", "FM29pt"]) == 0
    line = next(line for line in capsys.readouterr().out.splitlines() if " N3ITT " in line)
    from_you = lookup(grid_center("FM29pt"), resolve("grid:FN20kl")).bearing_deg
    assert from_you is not None
    fields = re.split(r"\s{2,}", line.strip())  # columns are separated by 2+ spaces
    assert fields[:5] == ["4", "N3ITT", "AL", "OTTSVILLE, PA", "FN20kl"]
    assert fields[5] == f"{from_you:.1f}°"
    assert fields[5] != "0.0°"
    assert fields[7] == "0°"


def test_parse_without_from_has_no_bearings(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["parse", N3RG]) == 0
    line = next(line for line in capsys.readouterr().out.splitlines() if " N2LQH " in line)
    assert line.count("°") == 1  # only the published 35°


def test_parse_shows_count_warning(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["parse", str(FIXTURES / "w2kv_144mhz_2026-10-26.txt"), "--from", "FM29pt"]) == 0
    assert "Warning:   Text says 18 check-ins; 17 parsed." in capsys.readouterr().out


def test_parse_missing_file(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["parse", str(tmp_path / "nope.txt")]) == 2
    assert "Rejected:" in capsys.readouterr().out
