import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from beam_navigator.core.models import Net, RotatorProfile, Station
from beam_navigator.core.roster_parser import parse_roster
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository, RotatorRepository, StationRepository

FIXTURES = Path(__file__).parent.parent / "fixtures"
N3RG_TEXT = (FIXTURES / "n3rg_50mhz_2026-10-26.txt").read_text(encoding="utf-8")
W2KV_TEXT = (FIXTURES / "w2kv_144mhz_2026-10-26.txt").read_text(encoding="utf-8")


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


def make_net(nets: NetRepository, name: str, **extra: object) -> int:
    fields: dict[str, object] = {
        "id": None, "name": name, "weekday": 0, "start_time": "20:00",
        "timezone": "America/New_York", "frequency_mhz": None, "channel": None, "mode": "SSB",
        "band": None, "default_controller_call": None, "default_controller_grid": None,
        "archived": False,
    }  # fmt: skip
    fields.update(extra)
    net = nets.save_net(Net(**fields))  # type: ignore[arg-type]
    assert net.id is not None
    return net.id


def count(conn: sqlite3.Connection, table: str) -> int:
    value: int = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return value


def test_import_keeps_raw_text_and_snapshots(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    net_id = make_net(nets, "Pack Rats 6 m", frequency_mhz=50.15)
    session = nets.import_roster(net_id, "2026-10-26", N3RG_TEXT, parse_roster(N3RG_TEXT))
    assert session.raw_text == N3RG_TEXT  # invariant 9
    assert session.status == "imported"
    assert (session.controller_call, session.controller_grid) == ("N3RG", "FM29ki")
    checkins = nets.checkins(session.id)
    assert len(checkins) == 22
    assert [c.sequence for c in checkins] == list(range(1, 23))
    n3itt = next(c for c in checkins if c.callsign == "N3ITT")
    assert n3itt.published_bearing == "0°"  # invariant 3: stored as printed


def test_identical_reimport_is_detected(conn: sqlite3.Connection) -> None:  # acceptance 13
    nets = NetRepository(conn)
    net_id = make_net(nets, "Pack Rats 6 m")
    first = nets.import_roster(net_id, "2026-10-26", N3RG_TEXT, parse_roster(N3RG_TEXT))
    assert nets.find_identical_import(net_id, "2026-10-26", N3RG_TEXT) == first.id
    other_client = "﻿" + N3RG_TEXT.replace("\n", "  \r\n")  # Review Focus 1
    assert nets.find_identical_import(net_id, "2026-10-26", other_client) == first.id
    assert nets.find_identical_import(net_id, "2026-10-27", N3RG_TEXT) is None
    assert nets.find_identical_import(net_id, "2026-10-26", W2KV_TEXT) is None


def test_replace_or_keep_both(conn: sqlite3.Connection) -> None:  # acceptance 13
    nets = NetRepository(conn)
    net_id = make_net(nets, "Pack Rats 6 m")
    first = nets.import_roster(net_id, "2026-10-26", N3RG_TEXT, parse_roster(N3RG_TEXT))
    nets.import_roster(
        net_id, "2026-10-26", N3RG_TEXT, parse_roster(N3RG_TEXT), replace_session_id=first.id
    )
    assert count(conn, "session") == 1
    assert count(conn, "checkin") == 22
    nets.import_roster(net_id, "2026-10-26", N3RG_TEXT, parse_roster(N3RG_TEXT))
    assert count(conn, "session") == 2


def test_cross_fixture_history(conn: sqlite3.Connection) -> None:  # spec 7 cross-fixture
    nets = NetRepository(conn)
    stations = StationRepository(conn)
    six = make_net(nets, "Pack Rats 6 m")
    two = make_net(nets, "Pack Rats 2 m")
    s6 = nets.import_roster(six, "2026-10-26", N3RG_TEXT, parse_roster(N3RG_TEXT))
    w2kv = parse_roster(W2KV_TEXT)
    conflicts = nets.saved_grid_conflicts(w2kv)
    k3wgr_index = next(i for i, row in enumerate(w2kv.rows) if row.callsign == "K3WGR")
    assert conflicts[k3wgr_index] == "Saved grid FN10xh differs"
    n2lqh_index = next(i for i, row in enumerate(w2kv.rows) if row.callsign == "N2LQH")
    assert n2lqh_index not in conflicts  # FM29PT vs FM29pt agree
    s2 = nets.import_roster(two, "2026-10-26", W2KV_TEXT, w2kv)

    assert count(conn, "station WHERE callsign = 'N2LQH'") == 1
    k3wgr = stations.get("K3WGR")
    assert k3wgr is not None and k3wgr.grid == "FN10xh"  # no silent change
    snap = {c.callsign: c for c in nets.checkins(s2.id)}
    assert snap["K3WGR"].grid == "FN10xi"
    assert snap["AF3G"].name == "GLENN"
    assert {c.callsign: c for c in nets.checkins(s6.id)}["AF3G"].name == "GLEN"
    assert snap["KA3FQS"].qth == "AMBLER, PA"


def test_shorter_grid_is_not_a_conflict(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    StationRepository(conn).add_from_roster("N1DSB", "Dan", "FM29ab", "Waterford, NJ")
    result = parse_roster("10 N1DSB Dan Waterford, NJ fm29")
    assert nets.saved_grid_conflicts(result) == {}


def test_snapshots_survive_station_edit(conn: sqlite3.Connection) -> None:  # spec 3
    nets = NetRepository(conn)
    net_id = make_net(nets, "Pack Rats 6 m")
    session = nets.import_roster(net_id, "2026-10-26", N3RG_TEXT, parse_roster(N3RG_TEXT))
    StationRepository(conn).save(
        Station("N2LQH", "TERRY", "FM29ps", "TABERNACLE, NJ", None, "saved", "")
    )
    n2lqh = next(c for c in nets.checkins(session.id) if c.callsign == "N2LQH")
    assert n2lqh.grid == "FM29pt"


@pytest.mark.parametrize("date", ["Tuesday", "2026-13-01", "10-26-26", ""])
def test_bad_date_writes_nothing(conn: sqlite3.Connection, date: str) -> None:
    nets = NetRepository(conn)
    net_id = make_net(nets, "Pack Rats 6 m")
    with pytest.raises(ValueError):
        nets.import_roster(net_id, date, N3RG_TEXT, parse_roster(N3RG_TEXT))
    assert count(conn, "session") == 0
    assert count(conn, "checkin") == 0
    assert count(conn, "station") == 0


def test_net_with_history_cannot_be_deleted(conn: sqlite3.Connection) -> None:  # Focus 4
    nets = NetRepository(conn)
    net_id = make_net(nets, "Pack Rats 6 m")
    nets.import_roster(net_id, "2026-10-26", N3RG_TEXT, parse_roster(N3RG_TEXT))
    with pytest.raises(sqlite3.IntegrityError):
        nets.delete_net(net_id)
    assert count(conn, "session") == 1
    empty = make_net(nets, "Unused")
    nets.delete_net(empty)
    assert count(conn, "net") == 1


def test_talkgroup_net_has_no_frequency(conn: sqlite3.Connection) -> None:  # spec 7 KA3WXV
    nets = NetRepository(conn)
    net_id = make_net(nets, "Pack Rats DMR", channel="Pack Rats talkgroup", mode="DMR")
    net = nets.get_net(net_id)
    assert net.frequency_mhz is None
    assert net.channel == "Pack Rats talkgroup"


# Final review findings ----------------------------------------------------------------


def test_replace_only_an_import_of_the_same_net_and_date(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    six = make_net(nets, "Pack Rats 6 m")
    two = make_net(nets, "Pack Rats 2 m")
    live = nets.start_session(two, "2026-10-26")
    nets.add_checkin(live.id, "K1ABC")
    imported = nets.import_roster(six, "2026-10-26", N3RG_TEXT, parse_roster(N3RG_TEXT))
    for wrong in (live.id, 9999):
        with pytest.raises(ValueError):
            nets.import_roster(
                six, "2026-10-26", N3RG_TEXT, parse_roster(N3RG_TEXT), replace_session_id=wrong
            )
    with pytest.raises(ValueError):  # same net, other date
        nets.import_roster(
            six, "2026-10-27", N3RG_TEXT, parse_roster(N3RG_TEXT), replace_session_id=imported.id
        )
    assert [c.callsign for c in nets.checkins(live.id)] == ["K1ABC"]
    assert len(nets.checkins(imported.id)) == 22
    assert count(conn, "session") == 2


def test_later_roster_fills_missing_grid(conn: sqlite3.Connection) -> None:
    stations = StationRepository(conn)
    stations.add_from_roster("K3JJZ", "El", None, None)  # first seen on the DMR net
    stations.add_from_roster("K3JJZ", "EL", "FM29ab", "PHILADELPHIA, PA")
    station = stations.get("K3JJZ")
    assert station is not None
    assert (station.grid, station.qth, station.name) == ("FM29ab", "PHILADELPHIA, PA", "El")
    stations.add_from_roster("K3JJZ", "EL", "FN20lb", None)
    station = stations.get("K3JJZ")
    assert station is not None and station.grid == "FM29ab"  # never overwritten


def test_saved_record_without_grid_is_not_filled(conn: sqlite3.Connection) -> None:
    stations = StationRepository(conn)
    stations.save(Station("K3JJZ", "EL", None, None, None, "saved", ""))
    stations.add_from_roster("K3JJZ", "EL", "FM29ab", "PHILADELPHIA, PA")
    station = stations.get("K3JJZ")
    assert station is not None and station.grid is None


def save_rotator(conn: sqlite3.Connection, name: str) -> int:
    saved = RotatorRepository(conn).save(
        RotatorProfile(None, name, "simulation", None, None, 0.0, 360.0, 0.0, None, (),
                       False, False)  # fmt: skip
    )
    assert saved.id is not None
    return saved.id


def test_net_keeps_preferred_rotator(conn: sqlite3.Connection) -> None:  # spec 3
    nets = NetRepository(conn)
    rotator_id = save_rotator(conn, "Tower")
    net_id = make_net(nets, "Test net", rotator_id=rotator_id)
    assert nets.get_net(net_id).rotator_id == rotator_id


def test_deleting_rotator_clears_net_preference(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    rotator_id = save_rotator(conn, "Tower")
    net_id = make_net(nets, "Test net", rotator_id=rotator_id)
    with conn:
        conn.execute("DELETE FROM rotator_profile WHERE id = ?", (rotator_id,))
    assert nets.get_net(net_id).rotator_id is None
