"""beamnav-ui: the NiceGUI app on localhost (requirements 8). Pages only render; every
rule lives in beam_navigator.desk and below."""

import argparse
import socket
import sys
from collections.abc import Callable
from pathlib import Path

from fastapi.responses import PlainTextResponse, RedirectResponse
from nicegui import app, ui
from platformdirs import user_data_dir

from beam_navigator.desk import Desk
from beam_navigator.live_net import LiveNet
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


def header() -> None:
    with ui.header().classes("items-center gap-6"):
        ui.label("Beam Navigator").classes("text-lg font-bold")
        ui.link("Dashboard", "/").classes("text-white")
        ui.link("Import", "/import").classes("text-white")
        ui.link("Nets", "/nets").classes("text-white")
        ui.link("Settings", "/settings").classes("text-white")


def register_pages(
    desk_factory: Callable[[], Desk], qrz_client: QrzClient | None = None
) -> None:
    """qrz_client: one client for the app, so its QRZ session key is reused (spec 4.9)."""
    qrz = qrz_client or QrzClient()

    @app.get("/robots.txt", include_in_schema=False)
    def robots() -> PlainTextResponse:
        return PlainTextResponse(ROBOTS_TXT)

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
        live_net_page(LiveNet(desk.conn, desk), session_id)

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
        # A second double-click of the .exe: say why, not a traceback (decision 36).
        print(PORT_IN_USE.format(port=args.port))
        if getattr(sys, "frozen", False):
            try:
                input("Press Enter to close.")  # the console window closes on exit
            except EOFError:
                pass  # started with no keyboard, e.g. by a script
        raise SystemExit(1)
    data_dir: Path = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = open_db(data_dir / DB_FILE)
    desk = Desk(conn, RotateService(conn))
    register_pages(lambda: desk)
    ui.run(host=HOST, port=args.port, reload=False, title="Beam Navigator",
           show=not args.no_browser)  # fmt: skip
