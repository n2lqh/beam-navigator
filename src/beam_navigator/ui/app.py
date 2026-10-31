"""beamnav-ui: the NiceGUI app on localhost (requirements 8). Pages only render; every
rule lives in beam_navigator.desk and below."""

import argparse
import socket
import sys
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path

from fastapi.responses import PlainTextResponse, RedirectResponse
from nicegui import app, ui
from platformdirs import user_data_dir

from beam_navigator.about import TITLE
from beam_navigator.desk import Desk
from beam_navigator.net_control import NetControl
from beam_navigator.nets import NetBook
from beam_navigator.qrz_client import QrzClient
from beam_navigator.roster_review import RosterReview
from beam_navigator.rotators.service import RotateService
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository
from beam_navigator.ui.control import control_page
from beam_navigator.ui.live_net import live_net_page
from beam_navigator.ui.lookup import dashboard
from beam_navigator.ui.nets import net_page, nets_page
from beam_navigator.ui.roster import import_page
from beam_navigator.ui.settings import settings_page
from beam_navigator.ui.welcome import welcome_page

APP_NAME = "beam-navigator"
DB_FILE = "beamnav.db"
DEFAULT_PORT = 8080
# Nothing here is for search engines; answering keeps "robots.txt not found" out of the
# console the operator sees (owner, 2026-10-29; decision 39).
ROBOTS_TXT = "User-agent: *\nDisallow: /\n"
HOST = "127.0.0.1"  # localhost only: LAN access is off by default (requirements 8)
# A second launch asks the port who is there; only Beam Navigator answers this (decision 44).
IDENTITY_PATH = "/beam-navigator.txt"
IDENTITY = TITLE
PROBE_TIMEOUT_S = 2.0
LOG_FILE = "beamnav.log"
PORT_IN_USE = (
    "Port {port} is already in use. Beam Navigator may already be running: open"
    " http://127.0.0.1:{port} in your browser. To run a second copy, start it with --port"
    " and another number."
)


def port_free(host: str, port: int) -> bool:
    """Binds for a moment and lets go, so the server can bind it next."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":
        # As the server binds there, so a quick restart is not refused while old
        # connections wait out TIME_WAIT. On Windows this option would share a live
        # listener, so it is left off (final review I1).
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((host, port))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def running_copy_at(port: int) -> bool:
    """True when the program on this port answers as Beam Navigator."""
    try:
        with urllib.request.urlopen(
            f"http://{HOST}:{port}{IDENTITY_PATH}", timeout=PROBE_TIMEOUT_S
        ) as reply:
            return bool(reply.read().decode("utf-8", "replace") == IDENTITY)
    except (OSError, ValueError):
        return False


def message_box(text: str) -> None:
    """The .exe has no console (decision 44), so it says why in a Windows message box."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x40)  # MB_ICONINFORMATION


def log_without_console(data_dir: Path) -> None:
    """A windowed .exe has no stdout or stderr: the server's messages go to beamnav.log in
    the data folder instead, rewritten each start. With a console nothing changes."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    # Open for the life of the process: the server writes here until it stops.
    log = (data_dir / LOG_FILE).open("w", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = log


def header() -> None:
    with ui.dialog() as stopped_dialog, ui.card():
        stopped = ui.label("").classes("text-lg")
    stopped_dialog.props("persistent")

    def quit_now() -> None:
        quit_dialog.close()
        stopped.set_text("Beam Navigator has stopped. You can close this tab.")
        stopped_dialog.open()
        # A moment for the page to show the message before the server goes away.
        ui.timer(0.5, lambda: app.shutdown(), once=True)

    with ui.dialog() as quit_dialog, ui.card():
        ui.label("Quit Beam Navigator?").classes("text-lg")
        ui.label("The antenna stays where it is. Start Beam Navigator again to carry on.")
        with ui.row():
            ui.button("Quit", on_click=quit_now).mark("quit-confirm")
            ui.button("Cancel", on_click=quit_dialog.close).props("flat").mark("quit-cancel")

    with ui.header().classes("items-center gap-6"):
        ui.label("Beam Navigator").classes("text-lg font-bold")
        ui.link("Dashboard", "/").classes("text-white")
        ui.link("Import", "/import").classes("text-white")
        ui.link("Nets", "/nets").classes("text-white")
        ui.link("Settings", "/settings").classes("text-white")
        ui.space()
        ui.button("Quit", on_click=quit_dialog.open).props("flat color=white").mark("quit")


def register_pages(
    desk_factory: Callable[[], Desk], qrz_client: QrzClient | None = None
) -> None:
    """qrz_client: one client for the app, so its QRZ session key is reused (spec 4.9)."""
    qrz = qrz_client or QrzClient()

    @app.get("/robots.txt", include_in_schema=False)
    def robots() -> PlainTextResponse:
        return PlainTextResponse(ROBOTS_TXT)

    @app.get(IDENTITY_PATH, include_in_schema=False)
    def identity() -> PlainTextResponse:
        return PlainTextResponse(IDENTITY)

    @ui.page("/")
    def dashboard_page(later: str | None = None) -> RedirectResponse | None:
        desk = desk_factory()
        if later is None and desk.needs_welcome():  # until a station is active (decision 35)
            return RedirectResponse("/welcome")
        header()
        dashboard(desk, qrz)
        return None

    @ui.page("/welcome")
    def welcome() -> None:
        header()
        desk = desk_factory()
        welcome_page(desk, NetBook(desk.conn, desk))

    @ui.page("/import")
    def import_roster() -> None:
        header()
        desk = desk_factory()
        bands = [band.name for band in desk.bands.list()]
        import_page(RosterReview(desk.conn, desk), NetRepository(desk.conn), bands)

    @ui.page("/nets")
    def nets() -> None:
        header()
        desk = desk_factory()
        bands = [band.name for band in desk.bands.list()]
        nets_page(NetBook(desk.conn, desk), bands, desk.rotator_profiles.list(), qrz)

    @ui.page("/nets/{net_id}")
    def net_history(net_id: int) -> None:
        header()
        desk = desk_factory()
        book = NetBook(desk.conn, desk)
        try:
            book.nets.get_net(net_id)
        except ValueError as exc:
            ui.label(str(exc))
            return
        bands = [band.name for band in desk.bands.list()]
        net_page(book, net_id, bands, desk.rotator_profiles.list())

    @ui.page("/net/{session_id}")
    def live_net(session_id: int) -> None:
        header()
        desk = desk_factory()
        try:
            NetRepository(desk.conn).get_session(session_id)
        except ValueError as exc:
            ui.label(str(exc))
            return
        live_net_page(NetControl(desk.conn, desk), session_id, qrz)

    @ui.page("/control/{session_id}")
    def net_control(session_id: int) -> None:
        header()
        desk = desk_factory()
        try:
            NetRepository(desk.conn).get_session(session_id)
        except ValueError as exc:
            ui.label(str(exc))
            return
        control_page(NetControl(desk.conn, desk), session_id, qrz)

    @ui.page("/settings")
    def settings(restored: str | None = None, tab: str | None = None) -> None:
        header()
        settings_page(desk_factory(), qrz, restored, tab)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beamnav-ui", description="Start the Beam Navigator UI.")
    parser.add_argument("--data-dir", type=Path, default=Path(user_data_dir(APP_NAME, False)))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open a browser tab on start."
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if not port_free(HOST, args.port):
        if running_copy_at(args.port):
            # A second double-click: show the copy that is already running (decision 44).
            if not args.no_browser:
                webbrowser.open(f"http://{HOST}:{args.port}")
            raise SystemExit(0)
        # Something else holds the port: say why, not a traceback (decision 36).
        message = PORT_IN_USE.format(port=args.port)
        print(message)
        if getattr(sys, "frozen", False):
            message_box(message)
        raise SystemExit(1)
    data_dir: Path = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    log_without_console(data_dir)
    conn = open_db(data_dir / DB_FILE)
    desk = Desk(conn, RotateService(conn))
    register_pages(lambda: desk)
    ui.run(host=HOST, port=args.port, reload=False, title="Beam Navigator",
           show=not args.no_browser)  # fmt: skip
