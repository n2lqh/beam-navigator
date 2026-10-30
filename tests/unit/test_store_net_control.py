import sqlite3
from collections.abc import Iterator
from dataclasses import replace

import pytest

from beam_navigator.core.maidenhead import GridError
from beam_navigator.core.models import Net
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository, StationRepository


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def net_id(conn: sqlite3.Connection) -> int:
    saved = NetRepository(conn).save_net(
        Net(None, "Test net", None, None, None, 144.2, None, None, "2 m", None, None, False)
    )
    assert saved.id is not None
    return saved.id


def session_on(conn: sqlite3.Connection, net_id: int, day: int) -> int:
    return NetRepository(conn).start_session(net_id, f"2026-10-{day:02d}").id


def test_checkin_carries_report_notes_time(conn: sqlite3.Connection, net_id: int) -> None:
    nets = NetRepository(conn)
    session = session_on(conn, net_id, 1)
    logged = nets.add_checkin(session, "K1ABC", name="BOB", report="59", notes="new antenna")
    assert (logged.report, logged.notes) == ("59", "new antenna")
    assert logged.logged_at is not None and logged.logged_at.startswith("20")


def test_update_checkin(conn: sqlite3.Connection, net_id: int) -> None:
    nets = NetRepository(conn)
    session = session_on(conn, net_id, 1)
    logged = nets.add_checkin(session, "K1ABC", name="BOB", grid="FN20ok")
    updated = nets.update_checkin(logged.id, name="ROBERT", grid=" ", qth="Cherry Hill",
                                  report="57", notes=None)  # fmt: skip
    assert (updated.name, updated.grid, updated.qth, updated.report) == (
        "ROBERT", None, "Cherry Hill", "57"
    )
    with pytest.raises(GridError):
        nets.update_checkin(logged.id, name="X", grid="ZZ99", qth=None, report=None, notes=None)
    assert nets.checkins(session)[0].name == "ROBERT"


def test_attendance_last_15(conn: sqlite3.Connection, net_id: int) -> None:
    nets = NetRepository(conn)
    sessions = [session_on(conn, net_id, day) for day in range(1, 17)]  # 16 sessions
    for index, session in enumerate(sessions):
        if index == 0 or index >= 4:  # the oldest one, then 12 of the last 15
            nets.add_checkin(session, "K3WGR")
    assert nets.attendance(net_id, "K3WGR") == (12, 15)
    assert nets.attendance(net_id, "K9ZZZ") == (0, 15)


def test_attendance_base_call(conn: sqlite3.Connection, net_id: int) -> None:
    nets = NetRepository(conn)
    nets.add_checkin(session_on(conn, net_id, 1), "K1ABC/P")
    nets.add_checkin(session_on(conn, net_id, 2), "K1ABC")
    assert nets.attendance(net_id, "k1abc") == (2, 2)


def test_previous_notes_newest_first(conn: sqlite3.Connection, net_id: int) -> None:
    nets = NetRepository(conn)
    first, second, third = (session_on(conn, net_id, day) for day in (1, 2, 3))
    nets.add_checkin(first, "K1ABC", notes="old note")
    nets.add_checkin(second, "K1ABC", notes="  ")
    nets.add_checkin(second, "W2KV", notes="not mine")
    nets.add_checkin(third, "K1ABC", notes="tonight")
    assert nets.previous_notes(net_id, "K1ABC", third) == [("2026-10-01", "old note")]


def test_call_counts(conn: sqlite3.Connection, net_id: int) -> None:
    nets = NetRepository(conn)
    for day in (1, 2):
        nets.add_checkin(session_on(conn, net_id, day), "K3WGR")
    nets.add_checkin(session_on(conn, net_id, 3), "K3WXX")
    assert nets.call_counts(net_id) == {"K3WGR": 2, "K3WXX": 1}


def test_add_station_note(conn: sqlite3.Connection) -> None:
    stations = StationRepository(conn)
    stations.add_note("k1abc", "Runs 100 W", "2026-10-28")
    stations.add_note("K1ABC", "New yagi", "2026-11-02")
    saved = stations.get("K1ABC")
    assert saved is not None
    assert saved.notes == "2026-10-28: Runs 100 W\n2026-11-02: New yagi"
    with pytest.raises(ValueError):
        stations.add_note("K1ABC", "  ", "2026-11-02")


def test_update_record_leaves_snapshots(conn: sqlite3.Connection, net_id: int) -> None:
    nets = NetRepository(conn)
    session = session_on(conn, net_id, 1)
    nets.add_checkin(session, "K1ABC", grid="FN20ok")
    stations = StationRepository(conn)
    stations.add_from_roster("K1ABC", "BOB", "FN20ok", None)
    record = stations.get("K1ABC")
    assert record is not None
    stations.save(replace(record, grid="FN20pk"))
    assert nets.checkins(session)[0].grid == "FN20ok"
