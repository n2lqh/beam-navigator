"""beamnav-ui: the NiceGUI app on localhost (requirements 8). Pages only render; every
rule lives in beam_navigator.desk and below."""

import argparse
import functools
import os
import socket
import sys
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.responses import PlainTextResponse, RedirectResponse
from nicegui import app, ui
from platformdirs import user_data_dir

from beam_navigator.about import TITLE
from beam_navigator.data_folder import (
    DB_FILE,
    POINTER_FILE,
    Holder,
    acquire,
    held_by,
    pid_alive,
    release,
    resolve,
    take_over,
)
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
IN_USE_PATH = "/in-use"
LOCK_CHECK_S = 10.0  # how soon this PC notices another one took the data over
UNREACHABLE = (
    "Beam Navigator can't reach its data folder {folder}: {error}. Check that the shared"
    " folder's PC is on and the network is up. To use this PC's own folder instead, delete"
    " {pointer}."
)
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


@dataclass
class DataLock:
    """This PC's hold on the data folder (owner, 2026-11-21). desk is None while another
    PC has it: every page then shows who, with Take over."""

    folder: Path
    host: str
    pid: int
    since: str
    open_desk: Callable[[], Desk]
    alive: Callable[[int], bool] = pid_alive
    desk: Desk | None = None
    holder: Holder | None = None  # who has it, while this PC doesn't

    def start(self) -> None:
        self.holder = acquire(self.folder, self.host, self.pid, self.since, self.alive)
        if self.holder is None:
            self.desk = self.open_desk()

    def current(self) -> Desk:
        if self.desk is None:
            raise RuntimeError("The data folder is open on another PC.")
        return self.desk

    def take_over(self) -> None:
        take_over(self.folder, self.host, self.pid, self.since)
        self.holder = None
        if self.desk is None:
            self.desk = self.open_desk()

    def check(self) -> None:
        """Another PC took over: stop writing at once, so two never share the file."""
        if self.desk is None:
            return
        holder = held_by(self.folder)
        if holder is not None and (holder.host, holder.pid) != (self.host, self.pid):
            self.holder = holder
            self.desk.conn.close()
            self.desk = None

    def release(self) -> None:
        if self.desk is not None:
            release(self.folder, self.host, self.pid)


def _when(since: str) -> str:
    try:
        return datetime.fromisoformat(since).strftime("%a %d %b, %H:%M")
    except ValueError:
        return "an unknown time"


def in_use_page(lock: DataLock) -> None:
    holder = lock.holder or Holder("another PC", 0, "")

    def go() -> None:
        lock.take_over()
        ui.navigate.to("/")

    with ui.column().classes("w-full max-w-2xl mx-auto gap-4 p-8"):
        ui.label("Beam Navigator's data is in use").classes("text-2xl")
        ui.label(
            f"The data in {lock.folder} is open on {holder.host} since {_when(holder.since)}."
            " Only one PC at a time can use it safely."
        ).mark("in-use")
        ui.label(
            f"Quit Beam Navigator on {holder.host} first. Take over only if it isn't running"
            " there (left running, or it crashed): that PC stops using the data when you do."
        ).classes("text-caption")
        with ui.row():
            ui.button("Take over", on_click=go).mark("take-over")
            ui.button("Quit", on_click=lambda: app.shutdown()).props("flat").mark("in-use-quit")


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
    desk_factory: Callable[[], Desk],
    qrz_client: QrzClient | None = None,
    data_lock: DataLock | None = None,
    home: Path | None = None,
) -> None:
    """qrz_client: one client for the app, so its QRZ session key is reused (spec 4.9).
    data_lock: while another PC has the data, every page shows who (owner, 2026-11-21).
    home: this PC's own folder, where the choice of data folder is kept."""
    qrz = qrz_client or QrzClient()

    def page(path: str) -> Callable[[Callable[..., Any]], Any]:
        def wrap(build: Callable[..., Any]) -> Any:
            @functools.wraps(build)
            def guarded(*args: Any, **kwargs: Any) -> Any:
                if data_lock is not None and data_lock.desk is None:
                    return RedirectResponse(IN_USE_PATH)
                return build(*args, **kwargs)

            return ui.page(path)(guarded)

        return wrap

    if data_lock is not None:

        @ui.page(IN_USE_PATH)
        def in_use() -> RedirectResponse | None:
            if data_lock.desk is not None:
                return RedirectResponse("/")
            in_use_page(data_lock)
            return None

    @app.get("/robots.txt", include_in_schema=False)
    def robots() -> PlainTextResponse:
        return PlainTextResponse(ROBOTS_TXT)

    @app.get(IDENTITY_PATH, include_in_schema=False)
    def identity() -> PlainTextResponse:
        return PlainTextResponse(IDENTITY)

    @page("/")
    def dashboard_page(later: str | None = None) -> RedirectResponse | None:
        desk = desk_factory()
        if later is None and desk.needs_welcome():  # until a station is active (decision 35)
            return RedirectResponse("/welcome")
        header()
        dashboard(desk, qrz)
        return None

    @page("/welcome")
    def welcome() -> None:
        header()
        desk = desk_factory()
        welcome_page(desk, NetBook(desk.conn, desk))

    @page("/import")
    def import_roster() -> None:
        header()
        desk = desk_factory()
        bands = [band.name for band in desk.bands.list()]
        import_page(RosterReview(desk.conn, desk), NetRepository(desk.conn), bands, qrz)

    @page("/nets")
    def nets() -> None:
        header()
        desk = desk_factory()
        bands = [band.name for band in desk.bands.list()]
        nets_page(NetBook(desk.conn, desk), bands, desk.rotator_profiles.list(), qrz)

    @page("/nets/{net_id}")
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

    @page("/net/{session_id}")
    def live_net(session_id: int) -> None:
        header()
        desk = desk_factory()
        try:
            NetRepository(desk.conn).get_session(session_id)
        except ValueError as exc:
            ui.label(str(exc))
            return
        live_net_page(NetControl(desk.conn, desk), session_id, qrz)

    @page("/control/{session_id}")
    def net_control(session_id: int) -> None:
        header()
        desk = desk_factory()
        try:
            NetRepository(desk.conn).get_session(session_id)
        except ValueError as exc:
            ui.label(str(exc))
            return
        control_page(NetControl(desk.conn, desk), session_id, qrz)

    @page("/settings")
    def settings(restored: str | None = None, tab: str | None = None) -> None:
        header()
        settings_page(desk_factory(), qrz, restored, tab, home)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beamnav-ui", description="Start the Beam Navigator UI.")
    parser.add_argument(
        "--data-dir", type=Path, default=None,
        help="Use this data folder instead of the one chosen in Settings.",
    )  # fmt: skip
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
    home = Path(user_data_dir(APP_NAME, False))
    data_dir = resolve(home, args.data_dir)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Never fall back to another folder unasked: that would split the data in two.
        message = UNREACHABLE.format(folder=data_dir, error=exc, pointer=home / POINTER_FILE)
        print(message)
        if getattr(sys, "frozen", False):
            message_box(message)
        raise SystemExit(1) from exc
    log_without_console(data_dir)

    def open_desk() -> Desk:
        conn = open_db(data_dir / DB_FILE)
        return Desk(conn, RotateService(conn))

    since = datetime.now().astimezone().isoformat(timespec="seconds")
    lock = DataLock(data_dir, socket.gethostname(), os.getpid(), since, open_desk)
    lock.start()
    app.on_shutdown(lock.release)
    app.timer(LOCK_CHECK_S, lock.check)
    register_pages(lock.current, data_lock=lock, home=home)
    ui.run(host=HOST, port=args.port, reload=False, title="Beam Navigator",
           show=not args.no_browser)  # fmt: skip
