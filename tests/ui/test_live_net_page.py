"""The nets page and live net screen through NiceGUI's simulated user. Simulator only."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from beam_navigator.core.models import Net, OperatorProfile, RotatorProfile
from beam_navigator.core.roster_parser import parse_roster
from beam_navigator.core.sector import CANT_TELL, SECTOR_UP
from beam_navigator.desk import Desk
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository, ProfileRepository, RotatorRepository
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
    RotatorRepository(conn).save(
        RotatorProfile(None, "VHF", "simulation", None, None, 0.0, 360.0, 0.0, None,
                       ("2 m", "1.25 m"), False, False)  # fmt: skip
    )
    return Desk(conn, RotateService(conn, adapter_for=lambda p: sim, tester_for=lambda p: sim))


def add_net(conn: sqlite3.Connection, name: str, band: str) -> int:
    saved = NetRepository(conn).save_net(
        Net(None, name, None, None, None, 144.245, None, None, band, None, None, False)
    )
    assert saved.id is not None
    return saved.id


def import_fixture(conn: sqlite3.Connection, net_id: int, name: str) -> int:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return NetRepository(conn).import_roster(net_id, "2026-10-26", text, parse_roster(text)).id


@pytest.fixture
def w2kv_net(conn: sqlite3.Connection) -> int:
    return add_net(conn, "W2KV 2 m", "2 m")


@pytest.fixture
def w2kv(conn: sqlite3.Connection, w2kv_net: int) -> int:
    return import_fixture(conn, w2kv_net, "w2kv_144mhz_2026-10-26.txt")


async def open_net(user: User, desk: Desk, session_id: int) -> None:
    register_pages(lambda: desk)
    await user.open(f"/net/{session_id}")


async def test_header_names_net_control_with_bearing(
    user: User, desk: Desk, w2kv: int
) -> None:  # redesign: one line, with a way to change it
    await open_net(user, desk, w2kv)
    await user.should_see("Net control: W2KV · 354")
    await user.should_see(marker="net-control-change")
    await user.should_see("Change…")
    await user.should_see("Rotate VHF to 35")


async def test_compass_click_sector_up(user: User, desk: Desk, w2kv: int) -> None:  # 16
    await open_net(user, desk, w2kv)
    user.find(marker="sector-S").click()
    await user.should_see(SECTOR_UP)


async def test_unknown_controller(user: User, desk: Desk, conn: sqlite3.Connection) -> None:
    session = import_fixture(
        conn, add_net(conn, "222", "1.25 m"), "wa3nuf_222mhz_activity_2026-10-21.txt"
    )  # acceptance 17
    await open_net(user, desk, session)
    user.find(marker="sector-S").click()
    await user.should_see(CANT_TELL)
    await user.should_not_see(SECTOR_UP)


async def test_row_click_and_sectors_send_nothing_snap_back_one(
    user: User, desk: Desk, w2kv: int, conn: sqlite3.Connection, sim: SimulationAdapter
) -> None:  # acceptance 18, without a Follow toggle
    await open_net(user, desk, w2kv)
    first = NetRepository(conn).checkins(w2kv)[3]
    user.find(marker=f"row-{first.id}").click()
    await user.should_see(f"({first.callsign})")
    await user.should_see("from: Tonight list")
    for sector in ("N", "S", "E"):
        user.find(marker=f"sector-{sector}").click()
    assert sim.commands == []
    user.find(marker="snap-back").click()
    await user.should_see("Simulated:")
    await user.should_see("from: Net control")
    assert len(sim.commands) == 1


async def test_no_follow_toggle(user: User, desk: Desk, w2kv: int) -> None:
    await open_net(user, desk, w2kv)
    await user.should_see("Rotate to net control")
    await user.should_not_see("Follow")
    await user.should_not_see(marker="mode")
    await user.should_not_see("Snap back")


async def test_target_card_follows_picks(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int, sim: SimulationAdapter
) -> None:  # behaviour rules 1 and 2: each pick sets the Target and sends nothing
    tonight = tonight_after(conn, w2kv)
    await open_net(user, desk, tonight)
    await user.should_see("No target yet — pick a station")  # this net has no net control
    user.find(marker="regular-W2KV").click()
    await user.should_see("from: Regulars")
    user.find(marker="aim").type("FN20").trigger("keydown.enter")
    await user.should_see("from: Typed")
    user.find(marker="entry-callsign").type("K9ZZZ")
    user.find(marker="entry-grid").type("FN20")
    await user.should_see("Aim to K9ZZZ")
    user.find(marker="i-hear-aim").click()
    await user.should_see("from: I hear")
    await user.should_see("(K9ZZZ)")
    assert sim.commands == []


async def test_only_the_target_row_is_highlighted(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int
) -> None:  # Review Focus 4
    await open_net(user, desk, w2kv)
    first = NetRepository(conn).checkins(w2kv)[0]
    user.find(marker=f"row-{first.id}").click()
    await user.should_see("from: Tonight list")
    [row] = user.find(marker=f"row-{first.id}").elements
    assert "bg-blue-1" in row.classes
    user.find(marker="entry-callsign").type("K9ZZZ")  # the Aim box would filter row 1 out
    user.find(marker="entry-grid").type("FN20")
    await user.should_see("Aim to K9ZZZ")
    user.find(marker="i-hear-aim").click()
    await user.should_see("from: I hear")
    [row] = user.find(marker=f"row-{first.id}").elements
    assert "bg-blue-1" not in row.classes


async def test_not_set_offers_set_net_control(
    user: User, desk: Desk, conn: sqlite3.Connection
) -> None:  # the owner's Mud Toads net
    session = NetRepository(conn).start_session(add_net(conn, "Mud Toads", "2 m"), "2026-11-02")
    await open_net(user, desk, session.id)
    await user.should_see("Net control: not set")
    await user.should_see("Set net control…")
    await user.should_see("No target yet — pick a station")
    await user.should_see(marker="rotate-reason")


def fill(user: User, marker: str, value: str) -> None:
    [field] = user.find(marker=marker).elements
    assert isinstance(field, ui.input)
    field.set_value(value)


async def test_new_session_shows_expected(
    user: User, desk: Desk, w2kv: int, w2kv_net: int, conn: sqlite3.Connection
) -> None:  # acceptance 14
    register_pages(lambda: desk)
    await user.open("/nets")
    await user.should_see("W2KV 2 m")
    [when] = user.find(marker=f"start-date-{w2kv_net}").elements
    assert isinstance(when, ui.input)
    when.set_value("2026-11-02")
    user.find(marker=f"start-{w2kv_net}").click()
    await user.should_see("Regulars not heard yet (17)")
    sessions = NetRepository(conn).sessions(w2kv_net)
    assert [(s.date, count) for s, count in sessions][0] == ("2026-11-02", 0)


async def test_use_for_tonight_leaves_net(
    user: User, desk: Desk, w2kv: int, w2kv_net: int, conn: sqlite3.Connection
) -> None:  # acceptance 15
    await open_net(user, desk, w2kv)
    user.find(marker="net-control-change").click()
    [call] = user.find(marker="nc-call").elements
    assert isinstance(call, ui.input) and call.value == "W2KV"  # opens with tonight's values
    fill(user, "nc-call", "K2XYZ")
    fill(user, "nc-grid", "FM29jw")
    user.find(marker="nc-tonight").click()
    await user.should_see("Net control: K2XYZ")
    assert NetRepository(conn).get_session(w2kv).controller_call == "K2XYZ"
    assert NetRepository(conn).get_net(w2kv_net).default_controller_call is None


async def test_save_for_net_sets_default(
    user: User, desk: Desk, conn: sqlite3.Connection
) -> None:  # behaviour rule 6
    nets = NetRepository(conn)
    net_id = add_net(conn, "Mud Toads", "2 m")
    session = nets.start_session(net_id, "2026-11-02")
    await open_net(user, desk, session.id)
    user.find(marker="net-control-change").click()
    fill(user, "nc-call", "kd8ud")
    fill(user, "nc-grid", "FM19")
    user.find(marker="nc-save").click()
    await user.should_see("Net control: KD8UD · ")
    net = nets.get_net(net_id)
    assert (net.default_controller_call, net.default_controller_grid) == ("KD8UD", "FM19")


async def test_bad_grid_keeps_dialog_open(
    user: User, desk: Desk, w2kv: int, conn: sqlite3.Connection
) -> None:
    await open_net(user, desk, w2kv)
    user.find(marker="net-control-change").click()
    fill(user, "nc-grid", "ZZ99")
    user.find(marker="nc-save").click()
    await user.should_see(marker="nc-call")
    assert NetRepository(conn).get_session(w2kv).controller_grid != "ZZ99"


def press(user: User, code: str, key: str, ctrl: bool = False, repeat: bool = False) -> None:
    user.find(kind=ui.keyboard).trigger(
        "key",
        {"action": "keydown", "repeat": repeat, "altKey": False, "ctrlKey": ctrl,
         "metaKey": False, "shiftKey": False, "key": key, "code": code, "location": 0},
    )  # fmt: skip


async def test_home_snaps_back_once(
    user: User, desk: Desk, w2kv: int, sim: SimulationAdapter
) -> None:  # Focus 1
    await open_net(user, desk, w2kv)
    await user.should_see("Rotate VHF to")
    press(user, "Home", "Home")
    press(user, "Home", "Home", repeat=True)
    await user.should_see("Simulated:")
    assert len(sim.commands) == 1


async def test_ctrl_enter_rotates_once(
    user: User, desk: Desk, w2kv: int, sim: SimulationAdapter
) -> None:
    await open_net(user, desk, w2kv)
    await user.should_see("Rotate VHF to")
    press(user, "Enter", "Enter", ctrl=True)
    press(user, "Enter", "Enter", ctrl=True, repeat=True)
    await user.should_see("Simulated:")
    assert len(sim.commands) == 1


async def test_numpad_announces(user: User, desk: Desk, w2kv: int) -> None:  # acceptance 16
    await open_net(user, desk, w2kv)
    press(user, "Numpad2", "2")
    await user.should_see(SECTOR_UP)


async def test_keys_ignored_while_typing(user: User, desk: Desk, w2kv: int) -> None:  # Focus 2
    # The browser drops key events while a field has focus (ui.keyboard's ignore list);
    # the simulated user has no focus, so pin the configuration that does it.
    await open_net(user, desk, w2kv)
    [keyboard] = user.find(kind=ui.keyboard).elements
    assert {"input", "select", "textarea", "button"} <= set(keyboard.props["ignore"])
    assert keyboard.props["repeating"] is False


def has_js_listener(element: ui.element, event: str, fragment: str) -> bool:
    def same(a: str, b: str) -> bool:  # NiceGUI stores "update:model-value" as camelCase
        return a.replace("-", "").lower() == b.replace("-", "").lower()

    return any(
        same(listener.type, event) and fragment in (listener.js_handler or "")
        for listener in element._event_listeners.values()
    )


async def test_via_relay_asks_for_the_call(
    user: User, desk: Desk, w2kv: int, conn: sqlite3.Connection
) -> None:  # final review I1
    await open_net(user, desk, w2kv)
    first = NetRepository(conn).checkins(w2kv)[0]
    [heard] = user.find(marker=f"heard-{first.id}").elements
    assert isinstance(heard, ui.select)
    heard.set_value("relay")
    await user.should_see("Relayed by")
    [relay] = user.find(marker="relay-call").elements
    assert isinstance(relay, ui.input)
    relay.set_value("w2kv")
    user.find("Save relay").click()
    await user.should_see("via W2KV")
    saved = NetRepository(conn).checkins(w2kv)[0]
    assert (saved.heard_state, saved.relay_call) == ("relay", "W2KV")


async def test_heard_select_click_does_not_reach_the_row(
    user: User, desk: Desk, w2kv: int, conn: sqlite3.Connection
) -> None:  # final review I2: opening the menu must not select (and rebuild) the row
    await open_net(user, desk, w2kv)
    first = NetRepository(conn).checkins(w2kv)[0]
    [heard] = user.find(marker=f"heard-{first.id}").elements
    # A listener on the select itself stops Quasar opening its menu (checked in a browser),
    # so the row ignores clicks that start inside a form field instead.
    assert not has_js_listener(heard, "click", "")
    [row] = user.find(marker=f"row-{first.id}").elements
    assert has_js_listener(row, "click", "closest('.q-field')")


async def test_controls_give_focus_back_to_hotkeys(user: User, desk: Desk, w2kv: int) -> None:
    # final review I4: after clicking these, Home and Ctrl+Enter must still work
    await open_net(user, desk, w2kv)
    for marker in ("net-control-change", "rotator", "tonight-sort", "regular-sort"):
        [element] = user.find(marker=marker).elements
        assert has_js_listener(element, "click", "blur") or has_js_listener(
            element, "update:model-value", "blur"
        ), marker


# Participant screen (owner, 2026-10-30) ---------------------------------------------------


def tonight_after(conn: sqlite3.Connection, session_id: int) -> int:
    nets = NetRepository(conn)
    return nets.start_session(nets.get_session(session_id).net_id, "2026-11-02").id


async def test_aim_enter_sends_nothing(
    user: User, desk: Desk, w2kv: int, sim: SimulationAdapter
) -> None:  # acceptance 37
    await open_net(user, desk, w2kv)
    user.find(marker="aim").type("FN20").trigger("keydown.enter")
    await user.should_see("Rotate VHF to 342")
    await user.should_see("FN20 — typed")
    assert sim.commands == []


async def test_aim_unknown_says_why(user: User, desk: Desk, w2kv: int) -> None:
    await open_net(user, desk, w2kv)
    user.find(marker="aim").type("K3").trigger("keydown.enter")
    await user.should_see("Not recognized")


async def test_aim_filters_both_lists(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int, sim: SimulationAdapter
) -> None:  # acceptance 41
    tonight = tonight_after(conn, w2kv)
    regulars = [c.callsign for c in NetRepository(conn).checkins(w2kv)]
    NetRepository(conn).add_checkin(tonight, regulars[0])
    await open_net(user, desk, tonight)
    await user.should_see(marker=f"regular-{regulars[1]}")
    user.find(marker="aim").type(regulars[1])
    await user.should_see(marker=f"regular-{regulars[1]}")
    await user.should_not_see(marker=f"regular-{regulars[2]}")
    await user.should_not_see(regulars[0])
    assert sim.commands == []


async def test_regular_click_sends_nothing_then_rotate_once(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int, sim: SimulationAdapter
) -> None:  # acceptance 39
    tonight = tonight_after(conn, w2kv)
    await open_net(user, desk, tonight)
    await user.should_see("Regulars not heard yet")
    user.find(marker="regular-W2KV").click()
    await user.should_see("(W2KV)")
    assert sim.commands == []
    user.find(marker="rotate").click()
    await user.should_see("Simulated:")
    assert len(sim.commands) == 1


async def test_last_time_card(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int
) -> None:  # acceptance 44 (screen)
    nets = NetRepository(conn)
    nets.close_session(w2kv, "try 30° for K3WGR")
    await open_net(user, desk, tonight_after(conn, w2kv))
    await user.should_see("Last time (2026-10-26)")
    await user.should_see("try 30° for K3WGR")


async def test_no_last_time_card_without_notes(user: User, desk: Desk, w2kv: int) -> None:
    await open_net(user, desk, w2kv)
    await user.should_not_see(marker="last-time")


def entry(user: User, name: str) -> ui.input:
    [found] = user.find(marker=f"entry-{name}").elements
    assert isinstance(found, ui.input)
    return found


def press_enter(user: User, name: str) -> None:
    user.find(marker=f"entry-{name}").trigger(
        "keydown", {"code": "Enter", "shiftKey": False, "ctrlKey": False, "altKey": False}
    )


async def test_i_hear_logs_and_moves_regular(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int, sim: SimulationAdapter
) -> None:
    tonight = tonight_after(conn, w2kv)
    await open_net(user, desk, tonight)
    await user.should_see(marker="regular-W2KV")
    entry(user, "callsign").set_value("W2KV")
    press_enter(user, "callsign")  # first Enter fills (decision 31)
    press_enter(user, "callsign")  # the next logs
    await user.should_see("Logged W2KV")
    [checkin] = NetRepository(conn).checkins(tonight)
    assert checkin.callsign == "W2KV" and checkin.heard_state == "heard"
    await user.should_not_see(marker="regular-W2KV")
    assert sim.commands == []


async def test_i_hear_has_net_control_fields(user: User, desk: Desk, w2kv: int) -> None:
    # owner, 2026-10-31: the same boxes as the net control screen
    await open_net(user, desk, w2kv)
    for name in ("callsign", "name", "grid", "qth", "report", "notes"):
        await user.should_see(marker=f"entry-{name}")


async def test_i_hear_duplicate_asks(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int
) -> None:  # Review Focus 4
    tonight = tonight_after(conn, w2kv)
    NetRepository(conn).add_checkin(tonight, "W2KV")
    await open_net(user, desk, tonight)
    entry(user, "callsign").set_value("W2KV")
    press_enter(user, "callsign")
    press_enter(user, "callsign")
    await user.should_see("Already checked in")
    assert len(NetRepository(conn).checkins(tonight)) == 1


async def test_heard_button_sends_nothing(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int, sim: SimulationAdapter
) -> None:  # acceptance 39
    tonight = tonight_after(conn, w2kv)
    await open_net(user, desk, tonight)
    user.find(marker="heard-regular-W2KV").click()
    await user.should_not_see(marker="regular-W2KV")
    [checkin] = NetRepository(conn).checkins(tonight)
    assert checkin.callsign == "W2KV" and checkin.heard_state == "heard"
    assert sim.commands == []


async def test_add_tonight_fills_i_hear(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int
) -> None:
    tonight = tonight_after(conn, w2kv)
    await open_net(user, desk, tonight)
    user.find(marker="aim").type("W2KV").trigger("keydown.enter")
    user.find(marker="add-tonight").click()
    assert entry(user, "callsign").value == "W2KV"
    assert NetRepository(conn).checkins(tonight) == []


async def test_close_with_notes_then_next_session_shows_them(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int, w2kv_net: int
) -> None:  # acceptance 44
    await open_net(user, desk, w2kv)
    user.find(marker="close-session").click()
    user.find(marker="close-notes").type("try 30° for K3WGR")
    user.find(marker="close-confirm").click()
    session = NetRepository(conn).get_session(w2kv)
    assert session.status == "closed" and session.closing_notes == "try 30° for K3WGR"
    await user.open(f"/net/{tonight_after(conn, w2kv)}")
    await user.should_see("try 30° for K3WGR")
    other = NetRepository(conn).start_session(add_net(conn, "Other", "2 m"), "2026-11-02").id
    await user.open(f"/net/{other}")
    await user.should_not_see("try 30° for K3WGR")


async def test_closed_session_read_only_rotate_works(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int, sim: SimulationAdapter
) -> None:  # acceptance 45
    NetRepository(conn).close_session(w2kv, "")
    await open_net(user, desk, w2kv)
    await user.should_see(marker="closed-badge")
    assert not entry(user, "callsign").enabled
    first = NetRepository(conn).checkins(w2kv)[0]
    [heard] = user.find(marker=f"heard-{first.id}").elements
    assert not heard.enabled
    user.find(marker="rotate").click()
    await user.should_see("Simulated:")
    assert len(sim.commands) == 1
    user.find(marker="reopen").click()
    await user.should_not_see(marker="closed-badge")
    assert entry(user, "callsign").enabled
    assert NetRepository(conn).get_session(w2kv).status == "active"


async def test_aim_unresolved_clears_typed_target(
    user: User, desk: Desk, w2kv: int, sim: SimulationAdapter
) -> None:  # final review I1: never rotate to an earlier typed target
    await open_net(user, desk, w2kv)
    user.find(marker="aim").type("FN20").trigger("keydown.enter")
    await user.should_see("Rotate VHF to 342")
    [box] = user.find(marker="aim").elements
    box.set_value("K9ZZZ")
    user.find(marker="aim").trigger("keydown.enter")
    await user.should_not_see("Rotate VHF to 342")  # wait for the redraw
    [rotate] = user.find(marker="rotate").elements
    assert not rotate.enabled
    assert sim.commands == []


async def test_heard_on_selected_regular_keeps_target(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int, sim: SimulationAdapter
) -> None:  # final review M2, regraded: select, Heard, then Rotate still points there
    tonight = tonight_after(conn, w2kv)
    await open_net(user, desk, tonight)
    user.find(marker="regular-W2KV").click()
    user.find(marker="heard-regular-W2KV").click()
    await user.should_not_see(marker="regular-W2KV")  # wait for the redraw
    await user.should_see("Rotate VHF to 354")
    user.find(marker="rotate").click()
    await user.should_see("Simulated:")
    assert len(sim.commands) == 1


async def test_heard_base_call_duplicate_says_so(
    user: User, desk: Desk, conn: sqlite3.Connection, w2kv: int
) -> None:  # final review I2: no crash when the regular is already here as CALL/M
    tonight = tonight_after(conn, w2kv)
    NetRepository(conn).add_checkin(tonight, "W2KV/M")
    await open_net(user, desk, tonight)
    await user.should_not_see(marker="regular-W2KV")


async def test_i_hear_shows_direction_and_aims_without_rotating(
    user: User, desk: Desk, w2kv: int, sim: SimulationAdapter
) -> None:  # owner, 2026-10-31
    await open_net(user, desk, w2kv)
    [aim] = user.find(marker="i-hear-aim").elements
    assert not aim.enabled
    user.find(marker="entry-callsign").type("K9ZZZ")
    user.find(marker="entry-grid").type("FN20")
    await user.should_see("342")
    user.find(marker="i-hear-aim").click()
    await user.should_see("Rotate VHF to 342")
    await user.should_see("(K9ZZZ)")
    assert sim.commands == []
    user.find(marker="rotate").click()
    await user.should_see("Simulated:")
    assert len(sim.commands) == 1


async def test_i_hear_aim_names_the_call_and_sits_left_of_qrz(
    user: User, desk: Desk, w2kv: int
) -> None:  # owner, 2026-10-31: "Aim to <CallSign>", then Look up on QRZ, same style
    await open_net(user, desk, w2kv)
    [aim] = user.find(marker="i-hear-aim").elements
    assert aim.props["label"] == "Aim"  # nothing on the line yet
    user.find(marker="entry-callsign").type("k9zzz")
    await user.should_see("Aim to K9ZZZ")
    [aim] = user.find(marker="i-hear-aim").elements
    [qrz] = user.find(marker="qrz-lookup").elements
    row = aim.parent_slot.children  # type: ignore[union-attr]
    qrz_box = qrz.parent_slot.parent  # type: ignore[union-attr]  # its refreshable wrapper
    assert qrz_box in row and row.index(aim) == row.index(qrz_box) - 1
    assert aim.props.get("flat") == qrz.props.get("flat") is True
    assert aim.props.get("size") == qrz.props.get("size")
