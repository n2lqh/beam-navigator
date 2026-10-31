import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from beam_navigator.core.geometry import short_path
from beam_navigator.core.maidenhead import grid_center
from beam_navigator.core.models import Net, OperatorProfile, RotatorProfile, Station
from beam_navigator.core.roster_parser import parse_roster
from beam_navigator.core.sector import CANT_TELL, SECTOR_UP, SECTORS
from beam_navigator.desk import Desk
from beam_navigator.live_net import LiveNet, RegularRow, filter_rows, sort_regulars, sort_rows
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import (
    NetRepository,
    ProfileRepository,
    RotatorRepository,
    StationRepository,
)

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
        OperatorProfile(None, "Home", "N2LQH", "FM29pt", None, "mi", "America/New_York", "NJ",
                        False)  # fmt: skip
    )
    assert saved.id is not None
    profiles.activate(saved.id)
    RotatorRepository(conn).save(
        RotatorProfile(None, "VHF", "simulation", None, None, 0.0, 360.0, 0.0, None, ("2 m",),
                       False, False)  # fmt: skip
    )
    return Desk(conn, RotateService(conn, adapter_for=lambda p: sim, tester_for=lambda p: sim))


@pytest.fixture
def live(conn: sqlite3.Connection, desk: Desk) -> LiveNet:
    return LiveNet(conn, desk)


def add_net(conn: sqlite3.Connection, name: str, band: str | None = "2 m") -> int:
    saved = NetRepository(conn).save_net(
        Net(None, name, None, None, None, 144.245, None, None, band, None, None, False)
    )
    assert saved.id is not None
    return saved.id


def import_fixture(conn: sqlite3.Connection, net_id: int, name: str) -> int:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return NetRepository(conn).import_roster(net_id, "2026-10-26", text, parse_roster(text)).id


@pytest.fixture
def w2kv(conn: sqlite3.Connection) -> int:
    return import_fixture(conn, add_net(conn, "W2KV 2 m"), "w2kv_144mhz_2026-10-26.txt")


def test_controller_both_directions(live: LiveNet, w2kv: int) -> None:  # acceptance 16
    view = live.view(w2kv)
    controller = view.controller
    assert controller.callsign == "W2KV"
    assert controller.source == "session grid"
    assert controller.bearing_deg == pytest.approx(354, abs=1)
    assert controller.you_to_controller == f"You → controller: {controller.bearing_deg:.1f}°"
    expected = short_path(grid_center("FN20OK"), grid_center("FM29pt")).bearing_deg
    assert controller.controller_to_you_deg == pytest.approx(expected, abs=0.01)
    assert controller.controller_to_you == f"Controller → you: {expected:.1f}° (S)"
    assert view.title == "W2KV 2 m · 2026-10-26"
    assert view.frequency == "144.245 MHz"
    assert live.announce(w2kv, "S").message == SECTOR_UP


def test_unknown_controller_cant_tell(conn: sqlite3.Connection, live: LiveNet) -> None:  # 17
    session = import_fixture(
        conn, add_net(conn, "222 activity", "1.25 m"), "wa3nuf_222mhz_activity_2026-10-21.txt"
    )
    assert live.view(session).controller.source == "unknown"
    for sector in SECTORS:
        result = live.announce(session, sector)
        assert result.up is None and result.message == CANT_TELL


def test_controller_from_saved_record(conn: sqlite3.Connection, live: LiveNet) -> None:
    nets = NetRepository(conn)
    session = nets.start_session(add_net(conn, "Test"), "2026-11-02")
    StationRepository(conn).save(Station("K2XYZ", None, "FN20ok", None, None, "saved", ""))
    live.set_substitute(session.id, "K2XYZ", None, None)
    assert live.view(session.id).controller.source == "saved"
    assert live.announce(session.id, "S").up is True


def test_measured_bearing_only(conn: sqlite3.Connection, live: LiveNet) -> None:  # Focus 3
    session = NetRepository(conn).start_session(add_net(conn, "Test"), "2026-11-02")
    live.set_substitute(session.id, None, None, 200.0)
    controller = live.view(session.id).controller
    assert controller.source == "measured bearing"
    assert controller.you_to_controller == "You → controller: 200.0°"
    assert controller.controller_to_you is None and controller.controller_to_you_deg is None
    assert live.announce(session.id, "S").message == CANT_TELL
    assert live.target(session.id, "controller", None) == ("Controller", 200.0)
    with pytest.raises(ValueError):
        live.set_substitute(session.id, " ", None, None)


def test_rows_use_snapshot_then_saved_grid(conn: sqlite3.Connection, live: LiveNet) -> None:
    session = import_fixture(conn, add_net(conn, "DMR", None), "ka3wxv_dmr_2026-10-26.txt")
    rows = live.view(session).rows
    assert all(row.grid_text == "Grid needed" and row.bearing_deg is None for row in rows)
    stations = StationRepository(conn)
    first = stations.get(rows[0].callsign)
    assert first is not None
    stations.save(replace(first, grid="FN20ok"))
    again = live.view(session).rows[0]
    assert again.grid_text == "FN20ok (saved)"
    assert again.bearing_text is not None and again.bearing_text.endswith(" N")


def test_published_column_separate(conn: sqlite3.Connection, live: LiveNet) -> None:  # 12
    session = import_fixture(conn, add_net(conn, "N3RG 6 m", "6 m"), "n3rg_50mhz_2026-10-26.txt")
    rows = live.view(session).rows
    assert any(row.published for row in rows)
    for row in rows:
        assert row.bearing_text is None or row.bearing_text != row.published


def test_sort_and_filter(live: LiveNet, w2kv: int) -> None:
    rows = live.view(w2kv).rows
    assert [r.callsign for r in sort_rows(rows, "roster")] == [r.callsign for r in rows]
    by_call = [r.callsign for r in sort_rows(rows, "callsign")]
    assert by_call == sorted(by_call)
    by_bearing = [r.bearing_deg for r in sort_rows(rows, "bearing") if r.bearing_deg is not None]
    assert by_bearing == sorted(by_bearing)
    by_distance = sort_rows(rows, "distance")
    known = [r.distance_km for r in by_distance if r.distance_km is not None]
    assert known == sorted(known)
    assert all(r.distance_km is None for r in by_distance[len(known):])
    assert [r.callsign for r in filter_rows(rows, "k3wgr")] == ["K3WGR"]
    assert [r.callsign for r in filter_rows(rows, "fn10XI")] == ["K3WGR"]
    assert filter_rows(rows, "") == rows


def test_nothing_sent_without_press(
    conn: sqlite3.Connection, live: LiveNet, w2kv: int, sim: SimulationAdapter
) -> None:  # acceptance 18
    view = live.view(w2kv)
    for sector in SECTORS:
        live.announce(w2kv, sector)
    NetRepository(conn).set_heard(view.rows[0].checkin_id, "weak")
    live.target(w2kv, "controller", None)
    live.target(w2kv, "station", view.rows[3].checkin_id)
    live.set_substitute(w2kv, "W2KV", "FN20OK", None)
    assert sim.commands == []
    rotator = view.rotator
    assert rotator is not None and rotator.id is not None
    outcome = live.snap_back(w2kv, rotator.id)
    assert outcome is not None and outcome.sent
    assert len(sim.commands) == 1


def test_follow_station_targets_row(live: LiveNet, w2kv: int, desk: Desk) -> None:
    row = next(r for r in live.view(w2kv).rows if r.callsign == "K3WGR")
    found = desk.bearing_to("FN10xi")
    assert found is not None
    assert live.target(w2kv, "station", row.checkin_id) == ("K3WGR", found.deg)
    assert live.target(w2kv, "station", None) is None


def test_no_rotator_for_band(conn: sqlite3.Connection, live: LiveNet) -> None:  # Focus 5
    session = NetRepository(conn).start_session(add_net(conn, "No band", None), "2026-11-02")
    view = live.view(session.id)
    assert view.rotator is None
    assert view.rotate_reason == "No rotator for this band"


def test_preferred_rotator_offered_first(
    conn: sqlite3.Connection, live: LiveNet, sim: SimulationAdapter
) -> None:  # spec 3: a net's preferred rotator
    preferred = RotatorRepository(conn).save(
        RotatorProfile(None, "Tower", "simulation", None, None, 0.0, 360.0, 0.0, None, (),
                       False, False)  # fmt: skip
    )
    nets = NetRepository(conn)
    net = nets.get_net(add_net(conn, "Test net"))  # band 2 m has the VHF rotator
    nets.save_net(replace(net, rotator_id=preferred.id))
    session = nets.start_session(net.id or 0, "2026-11-02")
    view = live.view(session.id)
    assert view.rotator is not None and view.rotator.id == preferred.id
    assert sim.commands == []


# Participant screen: regulars, typed targets, last time (owner, 2026-10-30) -----------


def regular(call: str, grid: str | None, bearing: float | None, last_seen: str) -> RegularRow:
    return RegularRow(call, None, grid or "Grid needed", bearing, None, None, "1 of last 1",
                      last_seen)  # fmt: skip


def tonight_after(conn: sqlite3.Connection, session_id: int) -> int:
    nets = NetRepository(conn)
    return nets.start_session(nets.get_session(session_id).net_id, "2026-11-02").id


def test_regulars_from_past_sessions(conn: sqlite3.Connection, live: LiveNet, w2kv: int) -> None:
    past = NetRepository(conn).checkins(w2kv)
    tonight = tonight_after(conn, w2kv)
    view = live.view(tonight)
    assert view.rows == []
    assert {r.callsign for r in view.regulars} == {c.callsign for c in past}
    with_grid = next(c for c in past if c.grid)
    row = next(r for r in view.regulars if r.callsign == with_grid.callsign)
    assert row.attendance_text == "1 of last 2"
    assert row.last_seen == "2026-10-26"
    expected = live.desk.bearing_to(with_grid.grid)
    assert expected is not None and row.bearing_deg == pytest.approx(expected.deg)
    assert row.grid_text == with_grid.grid


def test_regulars_leave_once_checked_in(conn: sqlite3.Connection, live: LiveNet, w2kv: int) -> None:
    call = NetRepository(conn).checkins(w2kv)[0].callsign
    tonight = tonight_after(conn, w2kv)
    NetRepository(conn).add_checkin(tonight, call)
    assert call not in {r.callsign for r in live.view(tonight).regulars}


def test_sort_regulars_each_key() -> None:  # acceptance 40
    rows = [
        regular("W2KV", "FN20", 350.0, "2026-10-19"),
        regular("K1ABC", None, None, "2026-10-26"),
        regular("AA2B", "FM29", 10.0, "2026-10-19"),
    ]
    assert [r.callsign for r in sort_regulars(rows, "callsign")] == ["AA2B", "K1ABC", "W2KV"]
    assert [r.callsign for r in sort_regulars(rows, "grid")] == ["AA2B", "W2KV", "K1ABC"]
    assert [r.callsign for r in sort_regulars(rows, "direction")] == ["AA2B", "W2KV", "K1ABC"]
    assert [r.callsign for r in sort_regulars(rows, "last")] == ["K1ABC", "AA2B", "W2KV"]


def test_filter_rows_takes_regulars() -> None:
    rows = [regular("W2KV", "FN20", 350.0, "2026-10-19"), regular("K1ABC", None, None, "x")]
    assert [r.callsign for r in filter_rows(rows, "fn2")] == ["W2KV"]


def test_regular_without_grid(conn: sqlite3.Connection, live: LiveNet) -> None:  # Focus 3
    nets = NetRepository(conn)
    net_id = add_net(conn, "Test")
    past = nets.start_session(net_id, "2026-10-26")
    nets.add_checkin(past.id, "K1ABC")
    tonight = nets.start_session(net_id, "2026-11-02").id
    [row] = live.view(tonight).regulars
    assert row.grid_text == "Grid needed" and row.bearing_deg is None
    assert live.target(tonight, "regular", None, callsign="K1ABC") is None


def test_regular_falls_back_to_saved_grid(conn: sqlite3.Connection, live: LiveNet) -> None:
    nets = NetRepository(conn)
    net_id = add_net(conn, "Test")
    nets.add_checkin(nets.start_session(net_id, "2026-10-26").id, "K1ABC")
    StationRepository(conn).save(Station("K1ABC", "Al", "FN20", None, None, "saved", ""))
    tonight = nets.start_session(net_id, "2026-11-02").id
    [row] = live.view(tonight).regulars
    assert row.grid_text == "FN20 (saved)" and row.name == "Al"
    target = live.target(tonight, "regular", None, callsign="K1ABC")
    assert target is not None and target[0] == "K1ABC"


def test_aim_resolves_and_sends_nothing(
    live: LiveNet, w2kv: int, sim: SimulationAdapter
) -> None:  # acceptance 37
    view, aim = live.aim(w2kv, "FN20")
    assert aim is not None and view.bearing_deg is not None
    assert aim == ("FN20", pytest.approx(view.bearing_deg))
    assert live.aim(w2kv, "W")[1] == ("W", 270.0)
    assert live.aim(w2kv, "K9ZZZ")[1] is None  # unknown call: Grid needed, no target
    assert live.aim(w2kv, "K3")[0].error is not None
    assert sim.commands == []


def test_rotate_typed_and_regular_one_command_each(
    conn: sqlite3.Connection, live: LiveNet, w2kv: int, desk: Desk, sim: SimulationAdapter
) -> None:  # acceptance 38
    rotator = desk.rotators()[0].id
    assert rotator is not None
    live.rotate(w2kv, rotator, "typed", None, typed=("W", 270.0))
    assert len(sim.commands) == 1
    tonight = tonight_after(conn, w2kv)
    call = next(r.callsign for r in live.view(tonight).regulars if r.bearing_deg is not None)
    live.rotate(tonight, rotator, "regular", None, callsign=call)
    assert len(sim.commands) == 2


def test_view_last_time_and_closed(conn: sqlite3.Connection, live: LiveNet, w2kv: int) -> None:
    nets = NetRepository(conn)
    assert live.view(w2kv).closed is False and live.view(w2kv).last_time is None
    nets.close_session(w2kv, "try 30°")
    tonight = tonight_after(conn, w2kv)
    assert live.view(tonight).last_time == ("2026-10-26", "try 30°")
    assert live.view(w2kv).closed is True


def test_heard_aim_uses_typed_grid_else_record(
    conn: sqlite3.Connection, live: LiveNet, desk: Desk, sim: SimulationAdapter
) -> None:  # owner, 2026-10-31: direction and Aim on the I-hear line
    found = live.heard_aim("K9ZZZ", "FN20")
    expected = desk.bearing_to("FN20")
    assert found is not None and expected is not None
    assert found == ("K9ZZZ", expected)
    StationRepository(conn).save(Station("K2XYZ", None, "FN20ok", None, None, "saved", ""))
    assert live.heard_aim("k2xyz", "") == ("K2XYZ", desk.bearing_to("FN20ok"))
    assert live.heard_aim("K9ZZZ", "") is None  # no grid anywhere: nothing to aim at
    assert live.heard_aim("", "FN20") is None
    assert sim.commands == []
