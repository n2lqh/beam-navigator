"""A second copy on a taken port explains itself instead of crashing (decision 36)."""

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from beam_navigator.ui.app import main, port_free


@pytest.fixture
def taken_port() -> Iterator[int]:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen()
    yield holder.getsockname()[1]
    holder.close()


def test_port_free_on_an_unused_port() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    assert port_free("127.0.0.1", port)


def test_port_taken(taken_port: int) -> None:
    assert not port_free("127.0.0.1", taken_port)


def test_main_reports_a_taken_port(
    taken_port: int, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    with pytest.raises(SystemExit) as stopped:
        main(["--data-dir", str(data_dir), "--port", str(taken_port)])
    assert stopped.value.code == 1
    out = capsys.readouterr().out
    assert "is already in use" in out and f"http://127.0.0.1:{taken_port}" in out
    assert not (data_dir / "beamnav.db").exists()


def test_no_browser_option() -> None:
    from beam_navigator.ui.app import build_parser

    assert build_parser().parse_args(["--no-browser"]).no_browser
    assert not build_parser().parse_args([]).no_browser


def test_frozen_with_no_keyboard_still_exits_cleanly(
    taken_port: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Hand check: the .exe started with no stdin hit EOFError at "Press Enter to close."
    import io
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(SystemExit) as stopped:
        main(["--data-dir", str(tmp_path), "--port", str(taken_port)])
    assert stopped.value.code == 1


class RecordingSocket:
    """Records socket options; binds nothing."""

    def __init__(self, *args: object) -> None:
        self.options: list[tuple[int, int, int]] = []

    def setsockopt(self, level: int, name: int, value: int) -> None:
        self.options.append((level, name, value))

    def bind(self, address: object) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.mark.parametrize("platform, reuse", [("linux", True), ("darwin", True), ("win32", False)])
def test_probe_matches_the_server_bind(
    monkeypatch: pytest.MonkeyPatch, platform: str, reuse: bool
) -> None:
    # Final review I1: off Windows the server binds with SO_REUSEADDR, so a probe without
    # it refused a quick restart while old connections sat in TIME_WAIT. On Windows the
    # option would let the probe share a live listener, so it is never set there.
    import sys

    from beam_navigator.ui import app

    made: list[RecordingSocket] = []

    def factory(*args: object) -> RecordingSocket:
        made.append(RecordingSocket())
        return made[-1]

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(app.socket, "socket", factory)
    assert app.port_free("127.0.0.1", 8080)
    reused = (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) in made[0].options
    assert reused == reuse


async def test_robots_txt_is_answered(user: object) -> None:
    # Browsers ask for /robots.txt; unanswered, every request printed "not found" in the
    # console the operator sees (owner, 2026-10-29; decision 39).
    import httpx
    from nicegui import app

    from beam_navigator.ui.app import ROBOTS_TXT, register_pages

    register_pages(lambda: None)  # type: ignore[arg-type,return-value]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        reply = await client.get("/robots.txt?498143")
    assert reply.status_code == 200
    assert reply.text == ROBOTS_TXT and reply.headers["content-type"].startswith("text/plain")
