"""The roster import screen through NiceGUI's simulated user. Simulator only."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from beam_navigator.core.models import Net, OperatorProfile, RotatorProfile
from beam_navigator.desk import Desk
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository, ProfileRepository, RotatorRepository
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


async def test_reimport_asks_replace_or_keep(
    user: User, desk: Desk, net_id: int, conn: sqlite3.Connection
) -> None:  # acceptance 13
    await paste_and_parse(user, desk, net_id)
    user.find(marker="save").click()
    await user.should_see("Saved 17 check-ins")
    user.find(marker="save").click()
    await user.should_see("Replace")
    user.find("Replace").click()
    await user.should_see("Saved 17 check-ins")
    assert len(NetRepository(conn).sessions(net_id)) == 1


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
