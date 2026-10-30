"""The net controller screen through NiceGUI's simulated user. No rotator is involved."""

import asyncio
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from beam_navigator.core.models import Net, OperatorProfile
from beam_navigator.core.roster_parser import parse_roster
from beam_navigator.desk import Desk
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository, ProfileRepository, StationRepository
from beam_navigator.ui.app import register_pages

FIXTURES = Path(__file__).parents[1] / "fixtures"


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
    return Desk(conn, RotateService(conn, adapter_for=lambda p: sim, tester_for=lambda p: sim))


@pytest.fixture
def tonight(conn: sqlite3.Connection) -> int:
    nets = NetRepository(conn)
    net = nets.save_net(
        Net(None, "W2KV 2 m", None, None, None, 144.245, None, None, "2 m", "W2KV", "FN20OK",
            False)  # fmt: skip
    )
    assert net.id is not None
    text = (FIXTURES / "w2kv_144mhz_2026-10-26.txt").read_text(encoding="utf-8")
    earlier = nets.import_roster(net.id, "2026-10-26", text, parse_roster(text))
    k3wgr = next(c for c in nets.checkins(earlier.id) if c.callsign == "K3WGR")
    nets.update_checkin(k3wgr.id, name=k3wgr.name, grid=k3wgr.grid, qth=k3wgr.qth, report=None,
                        notes="weak but readable")  # fmt: skip
    return nets.start_session(net.id, "2026-11-02").id


def field(user: User, name: str) -> ui.input:
    [found] = user.find(marker=f"entry-{name}").elements
    assert isinstance(found, ui.input)
    return found


CODES = {" ": "Space", "n": "KeyN", "N": "KeyN"}  # what the browser sends as event.code


def key(user: User, name: str, pressed: str, shift: bool = False, ctrl: bool = False) -> None:
    user.find(marker=f"entry-{name}").trigger(
        "keydown",
        {"code": CODES.get(pressed, pressed), "shiftKey": shift, "ctrlKey": ctrl, "altKey": False},
    )


def enter_twice(user: User) -> None:
    """Enter in Callsign fills the details first; a second Enter logs (owner, 2026-10-29)."""
    key(user, "callsign", "Enter")
    key(user, "callsign", "Enter")


def active(user: User) -> str:
    """The field the entry line has focused (marked with the entry-active class)."""
    names = ("callsign", "name", "grid", "qth", "report", "notes")
    [found] = [n for n in names if "entry-active" in field(user, n).classes]
    return found


async def open_control(user: User, desk: Desk, session_id: int) -> None:
    register_pages(lambda: desk)
    await user.open(f"/control/{session_id}")


async def test_known_call_space_autofills(user: User, desk: Desk, tonight: int,
                                          conn: sqlite3.Connection) -> None:  # 19  # fmt: skip
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("k3wgr")
    key(user, "callsign", " ")
    record = StationRepository(conn).get("K3WGR")
    assert record is not None
    await user.should_see("2026-10-26: weak but readable")
    assert field(user, "name").value == record.name
    assert field(user, "grid").value == "FN10xi"
    assert "italic" in field(user, "grid").classes
    assert active(user) == "name"


async def test_unknown_stops_on_name_and_grid(
    user: User, desk: Desk, tonight: int, conn: sqlite3.Connection
) -> None:  # acceptance 20
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K9ZZZ")
    key(user, "callsign", " ")
    await user.should_see("New station — name and grid needed")
    assert active(user) == "name"
    assert "bg-yellow-2" in field(user, "grid").classes
    key(user, "name", "Enter")
    await user.should_see("grid missing")
    assert [c.callsign for c in NetRepository(conn).checkins(tonight)] == ["K9ZZZ"]


async def test_changed_grid_session_only(
    user: User, desk: Desk, tonight: int, conn: sqlite3.Connection
) -> None:  # acceptance 21
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K3WGR")
    key(user, "callsign", " ")
    field(user, "grid").set_value("FN10xh")
    key(user, "grid", "Enter")
    await user.should_see("Grid: FN10xi → FN10xh")
    user.find("This session only").click()
    await user.should_see("Logged K3WGR")
    record = StationRepository(conn).get("K3WGR")
    assert record is not None and record.grid == "FN10xi"
    assert NetRepository(conn).checkins(tonight)[0].grid == "FN10xh"


async def test_duplicate_update_existing(
    user: User, desk: Desk, tonight: int, conn: sqlite3.Connection
) -> None:  # acceptance 22
    await open_control(user, desk, tonight)
    for report in ("", "59"):
        field(user, "callsign").set_value("K9ZZZ")
        field(user, "report").set_value(report)
        enter_twice(user)
    await user.should_see("Already checked in")
    user.find("Update existing").click()
    await user.should_see("Updated K9ZZZ")
    [only] = NetRepository(conn).checkins(tonight)
    assert only.report == "59"


async def test_full_checkin_without_mouse(
    user: User, desk: Desk, tonight: int, conn: sqlite3.Connection
) -> None:  # acceptance 23
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K9ZZZ")
    key(user, "callsign", " ")
    field(user, "name").set_value("MARY ANN")
    key(user, "name", "Tab")
    field(user, "grid").set_value("FN20ok")
    key(user, "grid", " ")
    field(user, "qth").set_value("CHERRY HILL")
    key(user, "qth", "Tab")
    field(user, "report").set_value("59")
    key(user, "report", "Enter")
    await user.should_see("Logged K9ZZZ")
    [logged] = NetRepository(conn).checkins(tonight)
    assert (logged.name, logged.grid, logged.qth, logged.report) == (
        "MARY ANN", "FN20ok", "CHERRY HILL", "59"
    )
    assert active(user) == "callsign"
    assert field(user, "callsign").value == ""


async def test_partial_list_ranked(user: User, desk: Desk, tonight: int) -> None:  # 24
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K3W")
    await user.should_see("K3WGR")
    key(user, "callsign", "ArrowDown")
    key(user, "callsign", "Enter")
    assert field(user, "callsign").value == "K3WGR"
    assert field(user, "grid").value == "FN10xi"


async def test_empty_enter_and_esc(
    user: User, desk: Desk, tonight: int, conn: sqlite3.Connection
) -> None:  # Focus 5
    await open_control(user, desk, tonight)
    key(user, "callsign", "Enter")
    field(user, "callsign").set_value("K1ABC")
    field(user, "name").set_value("BOB")
    key(user, "name", "Escape")
    assert field(user, "callsign").value == "" and field(user, "name").value == ""
    assert active(user) == "callsign"
    assert NetRepository(conn).checkins(tonight) == []


async def test_export_downloads(user: User, desk: Desk, tonight: int) -> None:
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K9ZZZ")
    enter_twice(user)
    await user.should_see("Logged K9ZZZ")
    user.find("CSV").click()
    response = await user.download.next()
    assert "K9ZZZ" in response.text
    assert "bearing_from" in response.text.splitlines()[0]


async def test_duplicate_dialog_defaults_to_cancel(
    user: User, desk: Desk, tonight: int, conn: sqlite3.Connection
) -> None:  # final review C1
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K9ZZZ")
    field(user, "name").set_value("BOB")
    enter_twice(user)
    await user.should_see("Logged K9ZZZ")
    field(user, "callsign").set_value("K9ZZZ")
    enter_twice(user)
    await user.should_see("Already checked in")
    [update] = user.find(marker="dup-update").elements
    [cancel] = user.find(marker="dup-cancel").elements
    assert "autofocus" in cancel.props and "autofocus" not in update.props
    user.find(marker="dup-update").click()
    await user.should_see("Updated K9ZZZ")
    assert NetRepository(conn).checkins(tonight)[0].name == "BOB"  # merged, not wiped


async def test_changing_the_call_drops_autofilled_details(
    user: User, desk: Desk, tonight: int, conn: sqlite3.Connection
) -> None:  # final review I1
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K3WGR")
    key(user, "callsign", " ")
    assert field(user, "grid").value == "FN10xi"
    field(user, "callsign").set_value("K9ZZZ")
    assert field(user, "grid").value == "" and field(user, "name").value == ""
    enter_twice(user)
    await user.should_see("Logged K9ZZZ")
    created = StationRepository(conn).get("K9ZZZ")
    assert created is not None and created.grid is None


async def test_enter_from_callsign_autofills(
    user: User, desk: Desk, tonight: int, conn: sqlite3.Connection
) -> None:  # final review I2
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K3WGR")
    key(user, "callsign", "Enter")
    assert field(user, "grid").value == "FN10xi"  # filled, not logged yet
    assert active(user) == "name"
    assert NetRepository(conn).checkins(tonight) == []
    key(user, "name", "Enter")
    await user.should_see("Logged K3WGR")
    assert NetRepository(conn).checkins(tonight)[0].grid == "FN10xi"


async def test_station_note_button(user: User, desk: Desk, tonight: int) -> None:  # I3
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K3WGR")
    user.find(marker="note-button").click()
    await user.should_see("Add a station note")


async def test_table_cell_bad_grid_restored_then_name_saves(
    user: User, desk: Desk, tonight: int, conn: sqlite3.Connection
) -> None:  # final review I4
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K9ZZZ")
    field(user, "grid").set_value("FN20ok")
    enter_twice(user)
    await user.should_see("Logged K9ZZZ")
    [checkin] = NetRepository(conn).checkins(tonight)
    await user.should_see(marker=f"cell-{checkin.id}-grid")  # the table refreshes async
    grid_cell = user.find(marker=f"cell-{checkin.id}-grid")
    [grid_box] = grid_cell.elements
    assert isinstance(grid_box, ui.input)
    grid_box.set_value("ZZ99")
    grid_cell.trigger("blur")
    await user.should_see("'ZZ99' is not a grid square")
    assert grid_box.value == "FN20ok"  # restored, still the same element (no rebuild)
    name_cell = user.find(marker=f"cell-{checkin.id}-name")
    [name_box] = name_cell.elements
    assert isinstance(name_box, ui.input)
    name_box.set_value("MARY ANN")
    name_cell.trigger("blur")
    await user.should_see("Saved K9ZZZ")
    saved = NetRepository(conn).checkins(tonight)[0]
    assert (saved.name, saved.grid) == ("MARY ANN", "FN20ok")


class FakeQrz:
    def __init__(self, replies: list[bytes]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, url: str, fields: dict[str, str]) -> bytes:
        self.calls += 1
        return self.replies.pop(0)


async def open_control_qrz(user: User, desk: Desk, session_id: int, transport: FakeQrz) -> None:
    from beam_navigator.qrz_client import QrzClient
    from beam_navigator.qrz_login import save_login

    save_login("xx1xxx", "pw")
    register_pages(lambda: desk, QrzClient(transport=transport))
    await user.open(f"/control/{session_id}")


async def test_controller_qrz_fills_blanks(
    user: User, desk: Desk, tonight: int, qrz_examples: list[bytes]
) -> None:  # requirements 4.9
    transport = FakeQrz([qrz_examples[0], qrz_examples[1]])
    await open_control_qrz(user, desk, tonight, transport)
    field(user, "callsign").set_value("AA7BQ")
    field(user, "name").set_value("FRED")
    key(user, "callsign", " ")
    await user.should_see("Filled from QRZ")
    assert field(user, "name").value == "FRED"  # typed: kept
    assert field(user, "grid").value == "DM32af"
    assert field(user, "qth").value == "SCOTTSDALE, AZ"
    assert "from-qrz" in field(user, "grid").classes
    assert "from-qrz" not in field(user, "name").classes


async def test_controller_auto_lookup(
    user: User, desk: Desk, tonight: int, qrz_examples: list[bytes]
) -> None:
    transport = FakeQrz([qrz_examples[0], qrz_examples[1]])  # on by default
    await open_control_qrz(user, desk, tonight, transport)
    field(user, "callsign").set_value("AA7BQ")
    key(user, "callsign", " ")
    await user.should_see("Filled from QRZ")
    assert transport.calls == 2 and field(user, "grid").value == "DM32af"


async def test_controller_no_auto_lookup_when_off(
    user: User, desk: Desk, tonight: int, qrz_examples: list[bytes]
) -> None:
    desk.settings.set("qrz_auto", "off")
    transport = FakeQrz([qrz_examples[0], qrz_examples[1]])
    await open_control_qrz(user, desk, tonight, transport)
    field(user, "callsign").set_value("AA7BQ")
    key(user, "callsign", " ")
    await user.should_see("New station — name and grid needed")
    assert transport.calls == 0


async def test_controller_no_auto_lookup_when_a_grid_is_saved(
    user: User, desk: Desk, tonight: int, qrz_examples: list[bytes]
) -> None:  # owner, 2026-10-29
    from beam_navigator.core.models import Station

    desk.stations.save(Station("AA7BQ", "FRED", "FN20ok", None, None, "saved", ""))
    transport = FakeQrz([qrz_examples[0], qrz_examples[1]])
    await open_control_qrz(user, desk, tonight, transport)
    field(user, "callsign").set_value("AA7BQ")
    key(user, "callsign", " ")
    await user.should_see(marker="qrz-lookup")
    assert field(user, "grid").value == "FN20ok"
    assert transport.calls == 0


async def test_controller_auto_lookup_fills_a_known_call_without_a_grid(
    user: User, desk: Desk, tonight: int, qrz_examples: list[bytes]
) -> None:
    from beam_navigator.core.models import Station

    desk.stations.save(Station("AA7BQ", "FRED", None, None, None, "saved", ""))
    transport = FakeQrz([qrz_examples[0], qrz_examples[1]])
    await open_control_qrz(user, desk, tonight, transport)
    field(user, "callsign").set_value("AA7BQ")
    key(user, "callsign", " ")
    await user.should_see("Filled from QRZ")
    assert field(user, "name").value == "FRED"  # stored: kept
    assert field(user, "grid").value == "DM32af"


async def test_enter_fills_from_cached_qrz(
    user: User, desk: Desk, tonight: int, qrz_examples: list[bytes]
) -> None:  # owner, 2026-10-29: a call QRZ already answered fills without a new lookup
    from beam_navigator.core.qrz import parse_response

    record = parse_response(qrz_examples[1]).record
    assert record is not None
    desk.qrz.save(record, "2026-10-29T00:00:00+00:00")
    transport = FakeQrz([])
    await open_control_qrz(user, desk, tonight, transport)
    field(user, "callsign").set_value("AA7BQ")
    key(user, "callsign", "Enter")
    await user.should_see("Filled from QRZ")
    assert (field(user, "name").value, field(user, "grid").value, field(user, "qth").value) == (
        'FRED "The Boss" LLOYD', "DM32af", "SCOTTSDALE, AZ"
    )
    assert "from-qrz" in field(user, "grid").classes
    assert active(user) == "name" and transport.calls == 0


async def test_cached_approximate_qrz_never_fills_a_grid(
    user: User, desk: Desk, tonight: int, qrz_examples: list[bytes]
) -> None:
    from dataclasses import replace

    from beam_navigator.core.qrz import parse_response

    record = parse_response(qrz_examples[1]).record
    assert record is not None
    desk.qrz.save(replace(record, geoloc="zip"), "2026-10-29T00:00:00+00:00")
    await open_control_qrz(user, desk, tonight, FakeQrz([]))
    field(user, "callsign").set_value("AA7BQ")
    key(user, "callsign", " ")
    await user.should_see("Filled from QRZ")
    assert field(user, "grid").value == "" and "bg-yellow-2" in field(user, "grid").classes


async def test_enter_runs_the_automatic_lookup(
    user: User, desk: Desk, tonight: int, qrz_examples: list[bytes]
) -> None:
    transport = FakeQrz([qrz_examples[0], qrz_examples[1]])
    await open_control_qrz(user, desk, tonight, transport)
    field(user, "callsign").set_value("AA7BQ")
    key(user, "callsign", "Enter")
    await user.should_see("Filled from QRZ")
    assert field(user, "grid").value == "DM32af" and transport.calls == 2


async def test_entry_boxes_are_wide_enough(user: User, desk: Desk, tonight: int) -> None:
    await open_control(user, desk, tonight)
    widths = {"callsign": "w-36", "name": "w-96", "grid": "w-28", "qth": "w-80"}
    for name, width in widths.items():
        assert width in field(user, name).classes, name
    rows = {name: field(user, name).parent_slot.parent.id for name in widths}  # type: ignore[union-attr]
    assert rows["callsign"] == rows["name"] == rows["grid"] != rows["qth"]  # QTH: line two


async def test_controller_qrz_button_opens_the_qrz_page(
    user: User, desk: Desk, tonight: int
) -> None:  # owner, 2026-10-29
    transport = FakeQrz([])
    await open_control_qrz(user, desk, tonight, transport)
    [before] = user.find(marker="qrz-lookup").elements
    assert "href" not in before.props  # no call yet
    field(user, "callsign").set_value("k2wb")
    # Redrawn with the link already set: a browser ignores an href added to a drawn button.
    for _ in range(100):  # the redraw runs in a background task
        [button] = user.find(marker="qrz-lookup").elements
        if button is not before:
            break
        await asyncio.sleep(0.01)
    assert button is not before
    assert button.props["href"] == "https://www.qrz.com/db/K2WB"
    assert button.props["target"] == "_blank" and transport.calls == 0


async def test_table_cells_are_wide_enough(
    user: User, desk: Desk, tonight: int, conn: sqlite3.Connection
) -> None:  # owner, 2026-10-29: the logged name must fit in the table too
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K9ZZZ")
    enter_twice(user)
    await user.should_see("Logged K9ZZZ")
    [checkin] = NetRepository(conn).checkins(tonight)
    await user.should_see(marker=f"cell-{checkin.id}-name")
    widths = {"name": "w-80", "grid": "w-24", "qth": "w-48"}
    for name, width in widths.items():
        [cell] = user.find(marker=f"cell-{checkin.id}-{name}").elements
        assert width in cell.classes, name


async def test_export_can_leave_out_report_and_notes(
    user: User, desk: Desk, tonight: int
) -> None:  # owner, 2026-10-29
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K9ZZZ")
    enter_twice(user)
    await user.should_see("Logged K9ZZZ")
    for marker in ("export-report", "export-notes"):
        [box] = user.find(marker=marker).elements
        assert box.value is True  # type: ignore[attr-defined]  # included unless unticked
        box.set_value(False)  # type: ignore[attr-defined]
    user.find("CSV").click()
    response = await user.download.next()
    header = response.text.splitlines()[0].split(",")
    assert "report" not in header and "notes" not in header and "name" in header


async def test_controller_fills_blanks_from_cached_qrz(
    user: User, desk: Desk, tonight: int, qrz_examples: list[bytes]
) -> None:  # decision 32: a roster name stays, QRZ fills the missing grid
    from beam_navigator.core.qrz import parse_response

    record = parse_response(qrz_examples[1]).record
    assert record is not None
    desk.stations.add_from_roster("AA7BQ", "FRED", None, None)
    desk.qrz.save(record, "2026-10-29T00:00:00+00:00")
    transport = FakeQrz([])
    await open_control_qrz(user, desk, tonight, transport)
    field(user, "callsign").set_value("AA7BQ")
    key(user, "callsign", " ")
    await user.should_see("Filled from QRZ")
    assert field(user, "name").value == "FRED" and field(user, "grid").value == "DM32af"
    assert "from-qrz" in field(user, "grid").classes and transport.calls == 0


async def test_remapped_log_key(
    user: User, desk: Desk, tonight: int, conn: sqlite3.Connection
) -> None:  # decision 33
    from beam_navigator.core.keymap import parse_chord

    desk.set_key("log", parse_chord("F2"))
    await open_control(user, desk, tonight)
    field(user, "callsign").set_value("K9ZZZ")
    key(user, "callsign", "Enter")  # no longer a key here
    await asyncio.sleep(0.1)
    assert NetRepository(conn).checkins(tonight) == []
    key(user, "callsign", "F2")  # first press fills (decision 31)
    key(user, "callsign", "F2")  # the next logs
    await user.should_see("Logged K9ZZZ")
    assert len(NetRepository(conn).checkins(tonight)) == 1


def test_keys_js_follows_the_keymap() -> None:
    from beam_navigator.core.keymap import DEFAULTS, parse_chord
    from beam_navigator.ui.control import _keys_js

    keymap = {**DEFAULTS, "log": parse_chord("F2")}
    script = _keys_js(keymap, space_advances=False)
    assert "['F2', false, false, false]" in script
    assert "['Enter'," not in script  # Enter is no longer a bound key
    assert "'Space'" in _keys_js(keymap, space_advances=True)


async def test_control_page_asks_for_a_reload_after_keys_change(
    user: User, desk: Desk, tonight: int, conn: sqlite3.Connection
) -> None:  # final review I4: the page's key filter was built with the old keys
    from beam_navigator.core.keymap import parse_chord

    await open_control(user, desk, tonight)
    desk.set_key("log", parse_chord("F2"))  # changed in another tab
    field(user, "callsign").set_value("K9ZZZ")
    enter_twice(user)
    await user.should_see("Keys were changed in Settings. Reload this page to use them.")
    assert NetRepository(conn).checkins(tonight) == []


async def test_no_heard_states_option(user: User, desk: Desk, tonight: int) -> None:
    # Owner, 2026-10-29 (decision 40): heard states are private; the net controller adds
    # stations to the roster, so the export never offers them.
    await open_control(user, desk, tonight)
    await user.should_see("Include report")
    await user.should_not_see("Include my heard states")
