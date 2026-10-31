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


def test_frozen_shows_a_message_box(
    taken_port: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The .exe has no console (decision 44), so the reason goes in a Windows message box.
    # Patch and call app.main on the same module object: NiceGUI's test plugin can import
    # it afresh, and a stale main showed a real message box during a full run.
    import sys

    from beam_navigator.ui import app

    shown: list[str] = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(app, "message_box", shown.append)
    with pytest.raises(SystemExit) as stopped:
        app.main(["--data-dir", str(tmp_path), "--port", str(taken_port)])
    assert stopped.value.code == 1
    assert len(shown) == 1 and "is already in use" in shown[0]


@pytest.fixture
def running_copy() -> Iterator[int]:
    """A server on the port that answers as Beam Navigator does."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from beam_navigator.ui.app import IDENTITY, IDENTITY_PATH

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = IDENTITY.encode() if self.path == IDENTITY_PATH else b""
            self.send_response(200 if body else 404)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("args, opened", [([], True), (["--no-browser"], False)])
def test_second_launch_opens_the_running_copy(
    running_copy: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    args: list[str], opened: bool,
) -> None:  # owner, 2026-10-31: no console, so a second double-click just shows the app
    from beam_navigator.ui import app

    urls: list[str] = []
    shown: list[str] = []
    monkeypatch.setattr(app.webbrowser, "open", urls.append)
    monkeypatch.setattr(app, "message_box", shown.append)
    with pytest.raises(SystemExit) as stopped:
        app.main(["--data-dir", str(tmp_path / "data"), "--port", str(running_copy), *args])
    assert stopped.value.code == 0
    assert urls == ([f"http://127.0.0.1:{running_copy}"] if opened else [])
    assert shown == []
    assert not (tmp_path / "data").exists()


def test_without_a_console_output_goes_to_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A windowed .exe has no stdout or stderr; the server's log must still have somewhere to go.
    import sys

    from beam_navigator.ui.app import LOG_FILE, log_without_console

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    log_without_console(tmp_path)
    assert sys.stdout is not None and sys.stderr is sys.stdout
    print("NiceGUI ready to go")
    sys.stdout.close()
    assert "NiceGUI ready to go" in (tmp_path / LOG_FILE).read_text(encoding="utf-8")


def test_with_a_console_nothing_changes(tmp_path: Path) -> None:
    import sys

    from beam_navigator.ui.app import LOG_FILE, log_without_console

    before = sys.stdout, sys.stderr
    log_without_console(tmp_path)
    assert (sys.stdout, sys.stderr) == before
    assert not (tmp_path / LOG_FILE).exists()


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


async def test_identity_is_answered(user: object) -> None:
    # How a second launch knows the program on the port is Beam Navigator (decision 44).
    import httpx
    from nicegui import app

    from beam_navigator.about import TITLE
    from beam_navigator.ui.app import IDENTITY, IDENTITY_PATH, register_pages

    register_pages(lambda: None)  # type: ignore[arg-type,return-value]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        reply = await client.get(IDENTITY_PATH)
    assert reply.status_code == 200 and reply.text == IDENTITY == TITLE
