"""The dashboard through NiceGUI's simulated user. Only simulation adapters: nothing here
may reach the real rotator on this PC."""

import asyncio
import sqlite3
from collections.abc import Iterator

import pytest
from nicegui import ui
from nicegui.testing import User

from beam_navigator.core.models import OperatorProfile, RotatorProfile
from beam_navigator.desk import Desk
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import (
    ProfileRepository,
    RotatorRepository,
    StationRepository,
)
from beam_navigator.ui.app import register_pages


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def sim() -> SimulationAdapter:
    return SimulationAdapter(az_max=360)


@pytest.fixture
def desk(conn: sqlite3.Connection, sim: SimulationAdapter) -> Desk:
    profiles = ProfileRepository(conn)
    saved = profiles.save(
        OperatorProfile(None, "Home", "N2LQH", "FM29pt", None, "mi", "America/New_York", "NJ",
                        False)  # fmt: skip
    )
    assert saved.id is not None
    profiles.activate(saved.id)
    RotatorRepository(conn).save(
        RotatorProfile(None, "VHF", "simulation", None, None, 0.0, 360.0, 0.0, None, ("2 m",),
                       False, False)  # fmt: skip
    )
    service = RotateService(conn, adapter_for=lambda p: sim, tester_for=lambda p: sim)
    return Desk(conn, service)


async def look_up(user: User, text: str) -> None:
    user.find(marker="target").type(text).trigger("keydown.enter")


async def test_lookup_shows_bearing(user: User, desk: Desk) -> None:
    register_pages(lambda: desk)
    await user.open("/")
    await look_up(user, "FN20ok")
    await user.should_see("FN20ok — typed")
    await user.should_see(" mi")
    await user.should_see("Rotate VHF to 35")


async def test_home_disables_rotate(user: User, desk: Desk) -> None:  # acceptance 2
    register_pages(lambda: desk)
    await user.open("/")
    await look_up(user, "FM29pt")
    await user.should_see("Home")
    [button] = user.find(marker="rotate").elements
    assert isinstance(button, ui.button)
    assert not button.enabled


async def test_typing_and_band_change_send_nothing(
    user: User, desk: Desk, sim: SimulationAdapter
) -> None:  # acceptance 26
    register_pages(lambda: desk)
    await user.open("/")
    for text in ("FN20ok", "NE", "PA"):
        user.find(marker="target").clear()
        await look_up(user, text)
    [band] = user.find(marker="band").elements
    assert isinstance(band, ui.select)
    band.set_value("6 m")
    band.set_value("2 m")
    await user.should_see("Rotate VHF to")
    assert sim.commands == []
    user.find(marker="rotate").click()
    await user.should_see("Simulated:")
    assert len(sim.commands) == 1


async def test_simulated_label(user: User, desk: Desk) -> None:  # Focus 1
    register_pages(lambda: desk)
    await user.open("/")
    await look_up(user, "247")
    await user.should_see("Rotate VHF to 247.0° (simulated)")


async def test_grid_needed_flow(user: User, desk: Desk, conn: sqlite3.Connection) -> None:
    register_pages(lambda: desk)
    await user.open("/")
    await look_up(user, "W2KV")
    await user.should_see("Grid needed")
    user.find(marker="grid").type("FN20ok")
    user.find("Use grid").click()
    await user.should_see("W2KV — typed")
    assert StationRepository(conn).get("W2KV") is None
    user.find("Save grid to W2KV").click()
    await user.should_see("Saved FN20ok for W2KV")
    saved = StationRepository(conn).get("W2KV")
    assert saved is not None and saved.grid == "FN20ok"


async def test_nebraska_offered(user: User, desk: Desk) -> None:  # acceptance 9
    register_pages(lambda: desk)
    await user.open("/")
    await look_up(user, "NE")
    await user.should_see("45.0° NE")
    user.find("Nebraska?").click()
    await user.should_see("Nebraska (NE) — region centroid")


def status_text(user: User) -> str:
    [label] = user.find(marker="status").elements
    assert isinstance(label, ui.label)
    return label.text


async def test_watch_reports_arrival(user: User, conn: sqlite3.Connection) -> None:
    # Final review I1: the progress timer must survive the controls refresh.
    profiles = ProfileRepository(conn)
    saved = profiles.save(OperatorProfile(None, "Home", None, "FM29pt", None, "km", "UTC", None,
                                          False))  # fmt: skip
    assert saved.id is not None
    profiles.activate(saved.id)
    RotatorRepository(conn).save(
        RotatorProfile(None, "VHF", "simulation", None, None, 0.0, 360.0, 0.0, 90.0, ("2 m",),
                       False, False)  # fmt: skip
    )
    slow = SimulationAdapter(az_max=360, speed_deg_per_s=90)
    service = RotateService(conn, adapter_for=lambda p: slow, tester_for=lambda p: slow)
    desk = Desk(conn, service)
    register_pages(lambda: desk)
    await user.open("/")
    await look_up(user, "90")
    await user.should_see("Rotate VHF to 90.0°")
    user.find(marker="rotate").click()
    await user.should_see("not confirmed yet")
    for _ in range(40):
        if "measured 90.0°" in status_text(user):
            break
        await asyncio.sleep(0.1)
    assert status_text(user) == "Simulated: Commanded 90.0°, measured 90.0°"
    assert len(slow.commands) == 1


async def test_changing_rotator_stops_the_watch(user: User, conn: sqlite3.Connection) -> None:
    # Final review I2: never report rotator B's position against rotator A's command.
    profiles = ProfileRepository(conn)
    saved = profiles.save(OperatorProfile(None, "Home", None, "FM29pt", None, "km", "UTC", None,
                                          False))  # fmt: skip
    assert saved.id is not None
    profiles.activate(saved.id)
    rotators = RotatorRepository(conn)
    first = rotators.save(
        RotatorProfile(None, "A", "simulation", None, None, 0.0, 360.0, 0.0, 10.0, ("2 m",),
                       False, False)  # fmt: skip
    )
    second = rotators.save(
        RotatorProfile(None, "B", "simulation", None, None, 0.0, 360.0, 0.0, None, ("6 m",),
                       False, False)  # fmt: skip
    )
    sims = {first.id: SimulationAdapter(az_max=360, speed_deg_per_s=10),
            second.id: SimulationAdapter(start_azimuth=270, az_max=360)}  # fmt: skip
    service = RotateService(conn, adapter_for=lambda p: sims[p.id], tester_for=lambda p: sims[p.id])
    desk = Desk(conn, service)
    register_pages(lambda: desk)
    await user.open("/")
    await look_up(user, "270")
    await user.should_see("Rotate A to 270.0°")
    user.find(marker="rotate").click()
    await user.should_see("not confirmed yet")
    [band] = user.find(marker="band").elements
    assert isinstance(band, ui.select)
    band.set_value("6 m")  # rotator B, already at 270°
    await asyncio.sleep(1.5)
    assert "measured 270.0°" not in status_text(user)


async def test_ctrl_enter_on_dashboard(user: User, desk: Desk, sim: SimulationAdapter) -> None:
    register_pages(lambda: desk)
    await user.open("/")
    await look_up(user, "FN20ok")
    await user.should_see("Rotate VHF to 35")
    keyboard = user.find(kind=ui.keyboard)
    for repeat in (False, True):
        keyboard.trigger(
            "key",
            {"action": "keydown", "repeat": repeat, "altKey": False, "ctrlKey": True,
             "metaKey": False, "shiftKey": False, "key": "Enter", "code": "Enter",
             "location": 0},
        )  # fmt: skip
    await user.should_see("Simulated:")
    assert len(sim.commands) == 1


class FakeQrz:
    """Replays QRZ spec examples and records the thread each call ran on."""

    def __init__(self, replies: list[bytes | Exception]) -> None:
        self.replies = list(replies)
        self.threads: list[int] = []

    def __call__(self, url: str, fields: dict[str, str]) -> bytes:
        import threading

        self.threads.append(threading.get_ident())
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def qrz_pages(desk: Desk, transport: FakeQrz) -> None:
    from beam_navigator.qrz_client import QrzClient
    from beam_navigator.qrz_login import save_login

    save_login("xx1xxx", "pw")
    register_pages(lambda: desk, QrzClient(transport=transport))


async def test_dashboard_qrz_button_opens_the_qrz_page(
    user: User, desk: Desk, sim: SimulationAdapter
) -> None:  # owner, 2026-10-29
    desk.settings.set("qrz_auto", "off")
    transport = FakeQrz([])
    qrz_pages(desk, transport)
    await user.open("/")
    await look_up(user, "K2WB")
    await user.should_see(marker="qrz-lookup")  # the result refreshes async
    [button] = user.find(marker="qrz-lookup").elements
    assert button.props["href"] == "https://www.qrz.com/db/K2WB"
    assert button.props["target"] == "_blank"
    assert transport.threads == [] and sim.commands == []  # no data lookup, no movement


async def test_dashboard_qrz_offline(
    user: User, desk: Desk, qrz_examples: list[bytes]
) -> None:  # acceptance 34
    from urllib.error import URLError

    qrz_pages(desk, FakeQrz([URLError("offline")]))
    await user.open("/")
    await look_up(user, "AA7BQ")  # looked up automatically: nothing is stored for AA7BQ
    await user.should_see("QRZ can't be reached. Everything else works offline.")
    user.find(marker="target").clear()
    await look_up(user, "FN20ok")
    await user.should_see("FN20ok — typed")


async def test_no_qrz_button_for_a_grid(user: User, desk: Desk) -> None:
    register_pages(lambda: desk)
    await user.open("/")
    await look_up(user, "FN20ok")
    await user.should_see("FN20ok — typed")
    await user.should_not_see(marker="qrz-lookup")


async def test_dashboard_looks_up_unknown_calls_automatically(
    user: User, desk: Desk, sim: SimulationAdapter, qrz_examples: list[bytes]
) -> None:  # owner, 2026-10-29
    import threading

    transport = FakeQrz([qrz_examples[0], qrz_examples[1]])
    qrz_pages(desk, transport)
    await user.open("/")
    await look_up(user, "AA7BQ")
    await user.should_see("from QRZ, ")
    await user.should_see("DM32af")
    await user.should_see("Location entered by the station on QRZ.")
    assert len(transport.threads) == 2
    assert all(t != threading.get_ident() for t in transport.threads)  # off the event loop
    assert desk.stations.get("AA7BQ") is None  # saved only on Save this station
    assert sim.commands == []  # invariant 2


async def test_dashboard_no_automatic_lookup_when_a_grid_is_saved(
    user: User, desk: Desk, qrz_examples: list[bytes]
) -> None:
    from beam_navigator.core.models import Station

    desk.stations.save(Station("AA7BQ", "FRED", "FN20ok", None, None, "saved", ""))
    transport = FakeQrz([qrz_examples[0], qrz_examples[1]])
    qrz_pages(desk, transport)
    await user.open("/")
    await look_up(user, "AA7BQ")
    await user.should_see("AA7BQ — saved")
    await asyncio.sleep(0.2)
    assert transport.threads == []


async def test_dashboard_automatic_lookup_is_quiet_without_a_login(
    user: User, desk: Desk
) -> None:
    from beam_navigator.qrz_client import QrzClient

    transport = FakeQrz([])
    register_pages(lambda: desk, QrzClient(transport=transport))
    await user.open("/")
    await look_up(user, "AA7BQ")
    await user.should_see(marker="qrz-lookup")
    await asyncio.sleep(0.2)
    await user.should_not_see("Set up your QRZ login")
    assert transport.threads == []


def cache_aa7bq(desk: Desk, qrz_examples: list[bytes], geoloc: str = "user") -> None:
    from dataclasses import replace

    from beam_navigator.core.qrz import parse_response

    record = parse_response(qrz_examples[1]).record
    assert record is not None
    desk.qrz.save(replace(record, geoloc=geoloc), "2026-10-29T00:00:00+00:00")


async def test_dashboard_auto_lookup_replaces_grid_needed(
    user: User, desk: Desk, qrz_examples: list[bytes]
) -> None:  # owner, 2026-10-29
    qrz_pages(desk, FakeQrz([qrz_examples[0], qrz_examples[1]]))
    await user.open("/")
    await look_up(user, "AA7BQ")
    await user.should_see("AA7BQ — QRZ")
    await user.should_see("Save this station")
    await user.should_not_see("Grid needed")
    await user.should_not_see("Use this location")


async def test_dashboard_uses_cached_qrz_location(
    user: User, desk: Desk, sim: SimulationAdapter, qrz_examples: list[bytes]
) -> None:
    cache_aa7bq(desk, qrz_examples)
    transport = FakeQrz([])
    qrz_pages(desk, transport)
    await user.open("/")
    await look_up(user, "AA7BQ")
    await user.should_see("AA7BQ — QRZ")
    assert transport.threads == [] and sim.commands == []


async def test_dashboard_save_this_station(
    user: User, desk: Desk, sim: SimulationAdapter, qrz_examples: list[bytes]
) -> None:
    cache_aa7bq(desk, qrz_examples)
    qrz_pages(desk, FakeQrz([]))
    await user.open("/")
    await look_up(user, "AA7BQ")
    await user.should_see(marker="qrz-save")
    user.find(marker="qrz-save").click()
    await user.should_see("Saved AA7BQ")
    await user.should_see("AA7BQ — saved")
    saved = desk.stations.get("AA7BQ")
    assert saved is not None and (saved.grid, saved.source) == ("DM32af", "saved")
    await user.should_not_see(marker="qrz-save")
    assert sim.commands == []  # invariant 2


async def test_dashboard_approximate_qrz_keeps_grid_needed(
    user: User, desk: Desk, qrz_examples: list[bytes]
) -> None:
    cache_aa7bq(desk, qrz_examples, geoloc="zip")
    qrz_pages(desk, FakeQrz([]))
    await user.open("/")
    await look_up(user, "AA7BQ")
    await user.should_see("Grid needed")
    await user.should_see("Show approximate bearing")
    await user.should_not_see(marker="qrz-save")


async def test_dashboard_says_looking_up_while_qrz_answers(
    user: User, desk: Desk, qrz_examples: list[bytes]
) -> None:
    import threading

    release = threading.Event()

    class Slow(FakeQrz):
        def __call__(self, url: str, fields: dict[str, str]) -> bytes:
            release.wait(5)
            return super().__call__(url, fields)

    qrz_pages(desk, Slow([qrz_examples[0], qrz_examples[1]]))
    await user.open("/")
    await look_up(user, "AA7BQ")
    await user.should_see("Looking up AA7BQ on QRZ…")
    await user.should_not_see("Grid needed")
    release.set()
    await user.should_see("AA7BQ — QRZ")


async def test_remapped_rotate_key_moves_once(
    user: User, desk: Desk, sim: SimulationAdapter
) -> None:  # decision 33; invariant 2
    from beam_navigator.core.keymap import parse_chord

    desk.set_key("rotate", parse_chord("F9"))
    register_pages(lambda: desk)
    await user.open("/")
    await look_up(user, "FN20ok")
    await user.should_see("Rotate VHF to 35")
    keyboard = user.find(kind=ui.keyboard)

    def key(code: str, ctrl: bool, repeat: bool) -> None:
        keyboard.trigger(
            "key",
            {"action": "keydown", "repeat": repeat, "altKey": False, "ctrlKey": ctrl,
             "metaKey": False, "shiftKey": False, "key": code, "code": code, "location": 0},
        )  # fmt: skip

    key("Enter", ctrl=True, repeat=False)  # the old chord: nothing
    await asyncio.sleep(0.2)
    assert sim.commands == []
    key("F9", ctrl=False, repeat=False)
    key("F9", ctrl=False, repeat=True)  # held: still one command
    await user.should_see("Simulated:")
    assert len(sim.commands) == 1


async def test_keys_changed_after_the_page_opened(
    user: User, desk: Desk, sim: SimulationAdapter
) -> None:  # final review I4: an open page follows Settings
    from beam_navigator.core.keymap import parse_chord

    register_pages(lambda: desk)
    await user.open("/")
    await look_up(user, "FN20ok")
    await user.should_see("Rotate VHF to 35")
    desk.set_key("rotate", parse_chord("F9"))  # changed in another tab
    keyboard = user.find(kind=ui.keyboard)

    def key(code: str, ctrl: bool) -> None:
        keyboard.trigger(
            "key",
            {"action": "keydown", "repeat": False, "altKey": False, "ctrlKey": ctrl,
             "metaKey": False, "shiftKey": False, "key": code, "code": code, "location": 0},
        )  # fmt: skip

    key("Enter", ctrl=True)  # the old Rotate key: freed in Settings, so nothing
    await asyncio.sleep(0.2)
    assert sim.commands == []
    key("F9", ctrl=False)
    await user.should_see("Simulated:")
    assert len(sim.commands) == 1
