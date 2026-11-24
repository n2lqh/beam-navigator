"""The roster import screen through NiceGUI's simulated user. Simulator only."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from beam_navigator.core.models import Net, OperatorProfile, RotatorProfile, Station
from beam_navigator.core.qrz import QrzRecord
from beam_navigator.desk import Desk
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import (
    NetRepository,
    ProfileRepository,
    RotatorRepository,
    StationRepository,
)
from beam_navigator.ui.app import register_pages

W2KV = (Path(__file__).parents[1] / "fixtures" / "w2kv_144mhz_2026-10-26.txt").read_text(
    encoding="utf-8"
)


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
        OperatorProfile(None, "Home", None, "FM29pt", None, "mi", "UTC", "NJ", False)
    )
    assert saved.id is not None
    profiles.activate(saved.id)
    RotatorRepository(conn).save(
        RotatorProfile(None, "VHF", "simulation", None, None, 0.0, 360.0, 0.0, None, ("2 m",),
                       False, False)  # fmt: skip
    )
    return Desk(conn, RotateService(conn, adapter_for=lambda p: sim, tester_for=lambda p: sim))


@pytest.fixture
def net_id(conn: sqlite3.Connection) -> int:
    saved = NetRepository(conn).save_net(
        Net(None, "W2KV 2 m", None, None, None, 144.245, None, None, "2 m", None, None, False)
    )
    assert saved.id is not None
    return saved.id


def pick(user: User, marker: str, value: object) -> None:
    [found] = user.find(marker=marker).elements
    assert isinstance(found, (ui.select, ui.input))
    found.set_value(value)


async def paste_and_parse(user: User, desk: Desk, net_id: int) -> None:
    register_pages(lambda: desk)
    await user.open("/import")
    pick(user, "roster-text", W2KV)
    pick(user, "net", net_id)
    pick(user, "date", "2026-10-26")
    user.find(marker="parse").click()
    await user.should_see("From you:")  # the table, not the pasted text


async def test_import_w2kv(
    user: User, desk: Desk, net_id: int, conn: sqlite3.Connection
) -> None:
    await paste_and_parse(user, desk, net_id)
    await user.should_see("Text says 18 check-ins; 17 parsed.")
    user.find(marker="save").click()
    await user.should_see("Saved 17 check-ins")
    await user.should_see("Open live net")
    assert len(NetRepository(conn).sessions(net_id)) == 1


async def test_reimport_asks_replace_or_cancel(
    user: User, desk: Desk, net_id: int, conn: sqlite3.Connection
) -> None:  # acceptance 13
    await paste_and_parse(user, desk, net_id)
    user.find(marker="save").click()
    await user.should_see("Saved 17 check-ins")
    user.find(marker="save").click()
    await user.should_see("for this night is already imported")
    await user.should_see("Cancel")
    await user.should_not_see("Keep both")
    user.find(marker="replace-confirm").click()
    await user.should_see("Saved 17 check-ins")
    assert len(NetRepository(conn).sessions(net_id)) == 1


async def test_reimport_of_different_text_also_asks_replace(
    user: User, desk: Desk, net_id: int, conn: sqlite3.Connection
) -> None:  # one session per net per night (owner, 2026-11-24)
    await paste_and_parse(user, desk, net_id)
    user.find(marker="save").click()
    await user.should_see("Saved 17 check-ins")
    pick(user, "roster-text", DMR)
    user.find(marker="parse").click()
    await user.should_not_see(marker="row-grid-16")  # the 11-row DMR list has replaced W2KV's 17
    user.find(marker="save").click()
    await user.should_see("for this night is already imported")
    user.find(marker="replace-confirm").click()
    await user.should_see("Open live net")  # cleared by Parse, back only after this save
    sessions = NetRepository(conn).sessions(net_id)
    assert len(sessions) == 1
    assert sessions[0][0].raw_text == DMR


async def test_invalid_grid_edit_blocks_save(
    user: User, desk: Desk, net_id: int, conn: sqlite3.Connection
) -> None:  # Focus 4
    await paste_and_parse(user, desk, net_id)
    pick(user, "row-grid-2", "ZZ99")
    user.find(marker="save").click()
    await user.should_see("'ZZ99' is not a grid square")
    assert NetRepository(conn).sessions(net_id) == []


async def test_new_net_dialog(user: User, desk: Desk, conn: sqlite3.Connection) -> None:
    register_pages(lambda: desk)
    await user.open("/import")
    user.find("New net").click()
    pick(user, "net-name", "Pack Rats DMR")
    pick(user, "net-channel", "TG 31425")
    user.find("Create net").click()
    await user.should_see("Created Pack Rats DMR")
    assert [n.name for n in NetRepository(conn).list_nets()] == ["Pack Rats DMR"]


async def test_import_sends_nothing(
    user: User, desk: Desk, net_id: int, sim: SimulationAdapter
) -> None:
    await paste_and_parse(user, desk, net_id)
    user.find(marker="save").click()
    await user.should_see("Saved 17 check-ins")
    assert sim.commands == []


async def test_replace_earlier_roster_grid(
    user: User, desk: Desk, net_id: int, conn: sqlite3.Connection
) -> None:  # decision 40: the operator is asked; ticking it replaces the grid
    from beam_navigator.store.repositories import StationRepository

    StationRepository(conn).add_from_roster("K3WGR", None, "FN10xh", None)
    await paste_and_parse(user, desk, net_id)
    await user.should_see("Replace earlier roster grid FN10xh")
    [box] = user.find(kind=ui.checkbox, content="Replace earlier roster grid FN10xh").elements
    assert isinstance(box, ui.checkbox) and box.value is False
    box.set_value(True)
    user.find(marker="save").click()
    await user.should_see("Saved 17 check-ins")
    station = StationRepository(conn).get("K3WGR")
    assert station is not None and station.grid == "FN10xi"


# owner, 2026-11-18: grids a roster leaves out come from the database, then QRZ ------

DMR = (Path(__file__).parents[1] / "fixtures" / "ka3wxv_dmr_2026-10-26.txt").read_text(
    encoding="utf-8"
)


class StubQrz:
    """Answers every call with one grid and records what was asked; no network."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def lookup(self, callsign: str) -> tuple[QrzRecord, str | None]:
        self.asked.append(callsign)
        return QrzRecord(callsign, None, "FN10ab", None, None, None, None), None


async def parse_dmr(user: User, net_id: int) -> None:
    await user.open("/import")
    pick(user, "roster-text", DMR)
    pick(user, "net", net_id)
    pick(user, "date", "2026-10-26")
    user.find(marker="parse").click()


async def test_import_fills_grids_from_saved_records_and_qrz(
    user: User, desk: Desk, net_id: int, conn: sqlite3.Connection, sim: SimulationAdapter
) -> None:
    StationRepository(conn).save(Station("K3JJZ", None, "FN10xh", None, None, "saved", ""))
    stub = StubQrz()
    register_pages(lambda: desk, stub)  # type: ignore[arg-type]
    await parse_dmr(user, net_id)
    await user.should_see("from saved record")
    await user.should_see("QRZ filled")
    assert "K3JJZ" not in stub.asked and "WX3K" in stub.asked
    await user.should_see("from QRZ")
    assert sim.commands == []


async def test_import_without_qrz_login_stays_quiet(
    user: User, desk: Desk, net_id: int
) -> None:
    register_pages(lambda: desk)  # the real client, with no login saved
    await parse_dmr(user, net_id)
    await user.should_see("From you:")
    await user.should_not_see("QRZ filled")
    await user.should_not_see("Set up your QRZ login")


WA3NUF = (Path(__file__).parents[1] / "fixtures" / "wa3nuf_222mhz_activity_2026-10-21.txt"
          ).read_text(encoding="utf-8")  # fmt: skip


async def test_net_control_list_offers_the_nets_saved_one(
    user: User, desk: Desk, conn: sqlite3.Connection
) -> None:  # owner, 2026-11-21: a net control saved for the net never showed on Import
    nets = NetRepository(conn)
    net = nets.save_net(
        Net(None, "DVFRC 50", None, None, None, 50.125, None, None, "6 m", "K3WWT", "FM29iv",
            False)  # fmt: skip
    )
    register_pages(lambda: desk)
    await user.open("/import")
    pick(user, "roster-text", WA3NUF)  # this roster names no net control
    pick(user, "date", "2026-10-21")
    user.find(marker="parse").click()
    await user.should_see("From you:")
    pick(user, "net", net.id)  # picked after parsing: the list follows the net
    await user.should_see("K3WWT (saved for this net)")
    user.find(marker="save").click()
    await user.should_see("Saved")
    [session] = nets.sessions(net.id or 0)
    assert session[0].controller_call == "K3WWT"


# Compare with my session (owner, 2026-11-24) ------------------------------------------


@pytest.fixture
def own_session(conn: sqlite3.Connection, net_id: int) -> int:
    nets = NetRepository(conn)
    session = nets.start_session(net_id, "2026-10-26")
    nets.add_checkin(session.id, "K3WGR", grid="FN10")
    nets.add_checkin(session.id, "W1AW")
    return session.id


def untick(user: User, call: str) -> None:
    [box] = user.find(marker=f"add-{call}").elements
    assert isinstance(box, ui.checkbox)
    box.set_value(False)


async def test_compare_shows_three_groups(
    user: User, desk: Desk, net_id: int, own_session: int
) -> None:
    await paste_and_parse(user, desk, net_id)
    await user.should_see("You have your own session for this night.")
    await user.should_not_see(marker="save")
    user.find(marker="compare").click()
    await user.should_see("Net control had, you didn't (16)")
    await user.should_see("You had, net control didn't (1)")
    await user.should_see("W1AW")
    await user.should_see("On both lists (1)")
    await user.should_see("Grid: FN10 (you) · FN10xi (net control)")


async def test_add_ticked_stations(
    user: User, desk: Desk, net_id: int, own_session: int, conn: sqlite3.Connection,
    sim: SimulationAdapter,
) -> None:  # fmt: skip
    await paste_and_parse(user, desk, net_id)
    user.find(marker="compare").click()
    await user.should_see("Net control had, you didn't (16)")
    untick(user, "K4SO")
    user.find(marker="add-ticked").click()
    await user.should_see("Added 15 stations")
    await user.should_see("Open live net")
    nets = NetRepository(conn)
    calls = [c.callsign for c in nets.checkins(own_session)]
    assert len(calls) == 17 and "K4SO" not in calls
    assert nets.get_session(own_session).raw_text == W2KV
    assert sim.commands == []


async def test_add_asks_qrz_once_per_call(
    user: User, desk: Desk, net_id: int, own_session: int, conn: sqlite3.Connection
) -> None:
    stub = StubQrz()
    register_pages(lambda: desk, stub)  # type: ignore[arg-type]
    await user.open("/import")
    pick(user, "roster-text", W2KV)
    pick(user, "net", net_id)
    pick(user, "date", "2026-10-26")
    user.find(marker="parse").click()
    await user.should_see("From you:")
    before = list(stub.asked)  # Parse's own grid lookups
    user.find(marker="compare").click()
    await user.should_see("Net control had, you didn't (16)")
    assert stub.asked == before  # nothing asked until Add
    user.find(marker="add-ticked").click()
    await user.should_see("Added 16 stations")
    after = stub.asked[len(before):]
    assert len(after) == len(set(after)) and not set(after) & set(before)
    calls = {c.callsign for c in NetRepository(conn).checkins(own_session)}
    assert set(after) <= calls and len(after) + len(before) >= 16


async def test_add_without_qrz_login(
    user: User, desk: Desk, net_id: int, own_session: int
) -> None:  # Review Focus 5
    await paste_and_parse(user, desk, net_id)  # the real client, with no login saved
    user.find(marker="compare").click()
    await user.should_see("Net control had, you didn't (16)")
    user.find(marker="add-ticked").click()
    await user.should_see("Added 16 stations")
    await user.should_not_see("Set up your QRZ login")


async def test_actions_follow_the_picked_night(
    user: User, desk: Desk, net_id: int, own_session: int
) -> None:  # Review Focus 1
    await paste_and_parse(user, desk, net_id)
    await user.should_see(marker="compare")
    pick(user, "date", "2026-10-27")
    await user.should_see(marker="save")
    await user.should_not_see(marker="compare")
    pick(user, "date", "2026-10-26")
    await user.should_see(marker="compare")
    await user.should_not_see(marker="save")
