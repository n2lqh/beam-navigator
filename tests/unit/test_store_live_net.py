import math
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from beam_navigator.core.maidenhead import GridError
from beam_navigator.core.models import Net
from beam_navigator.core.roster_parser import parse_roster
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


def add_net(conn: sqlite3.Connection, name: str = "W2KV 2 m", archived: bool = False) -> int:
    saved = NetRepository(conn).save_net(
        Net(None, name, 0, "20:00", "America/New_York", 144.245, None, "FM", "2 m", "W2KV",
            "FN20OK", archived)  # fmt: skip
    )
    assert saved.id is not None
    return saved.id


def import_w2kv(conn: sqlite3.Connection, net_id: int, date: str = "2026-10-26") -> int:
    text = (FIXTURES / "w2kv_144mhz_2026-10-26.txt").read_text(encoding="utf-8")
    return NetRepository(conn).import_roster(net_id, date, text, parse_roster(text)).id


def test_measured_bearing_substitute(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    net_id = add_net(conn)
    session = nets.start_session(net_id, "2026-11-02")
    nets.set_session_controller(session.id, None, None, bearing=174.0)
    got = nets.get_session(session.id)
    assert (got.controller_call, got.controller_grid, got.controller_bearing) == (None, None, 174.0)
    net = nets.get_net(net_id)
    assert (net.default_controller_call, net.default_controller_grid) == ("W2KV", "FN20OK")


@pytest.mark.parametrize(
    ("grid", "bearing", "error"),
    [("ZZ99", None, GridError), (None, 360.0, ValueError), (None, math.nan, ValueError),
     (None, -1.0, ValueError)],
)  # fmt: skip
def test_bad_substitute_rejected(
    conn: sqlite3.Connection, grid: str | None, bearing: float | None, error: type[Exception]
) -> None:
    nets = NetRepository(conn)
    session = nets.start_session(add_net(conn), "2026-11-02")
    with pytest.raises(error):
        nets.set_session_controller(session.id, "K2XYZ", grid, bearing=bearing)
    assert nets.get_session(session.id).controller_call == "W2KV"


def test_set_heard_and_relay(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    session_id = import_w2kv(conn, add_net(conn))
    first = nets.checkins(session_id)[0]
    with pytest.raises(ValueError):
        nets.set_heard(first.id, "relay")
    nets.set_heard(first.id, "relay", "w2kv")
    got = nets.checkins(session_id)[0]
    assert (got.heard_state, got.relay_call) == ("relay", "W2KV")
    nets.set_heard(first.id, "heard", "W2KV")
    got = nets.checkins(session_id)[0]
    assert (got.heard_state, got.relay_call) == ("heard", None)
    nets.set_heard(first.id, None)
    assert nets.checkins(session_id)[0].heard_state is None


def test_list_nets_and_sessions(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    old = add_net(conn, "Archived net", archived=True)
    net_id = add_net(conn, "W2KV 2 m")
    add_net(conn, "A net")
    assert [n.name for n in nets.list_nets()] == ["A net", "W2KV 2 m", "Archived net"]
    import_w2kv(conn, net_id)
    later = nets.start_session(net_id, "2026-11-02")
    listed = nets.sessions(net_id)
    assert [(s.date, count) for s, count in listed] == [("2026-11-02", 0), ("2026-10-26", 17)]
    assert listed[0][0].id == later.id
    assert nets.sessions(old) == []


def test_acceptance_15_substitute_leaves_default(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    net_id = add_net(conn)
    first = import_w2kv(conn, net_id)
    tonight = nets.start_session(net_id, "2026-11-02")
    nets.set_session_controller(tonight.id, "K2XYZ", "FM29jw")
    net = nets.get_net(net_id)
    assert (net.default_controller_call, net.default_controller_grid) == ("W2KV", "FN20OK")
    earlier = nets.get_session(first)
    assert earlier.controller_call == "W2KV"
    assert nets.get_session(tonight.id).controller_call == "K2XYZ"
