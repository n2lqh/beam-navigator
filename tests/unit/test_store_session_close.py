import sqlite3
from collections.abc import Iterator

import pytest

from beam_navigator.core.models import Net
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository, SessionClosed


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


def add_net(conn: sqlite3.Connection, name: str = "W2KV 2 m") -> int:
    saved = NetRepository(conn).save_net(
        Net(None, name, 0, "20:00", "America/New_York", 144.245, None, "FM", "2 m", "W2KV",
            "FN20OK", False)  # fmt: skip
    )
    assert saved.id is not None
    return saved.id


def test_close_and_reopen_keep_notes(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    session = nets.start_session(add_net(conn), "2026-10-30")
    closed = nets.close_session(session.id, "  K3WGR weak from 40°  ")
    assert closed.status == "closed"
    assert closed.closing_notes == "K3WGR weak from 40°"
    assert closed.closed_at is not None
    again = nets.reopen_session(session.id)
    assert again.status == "active"
    assert again.closing_notes == "K3WGR weak from 40°"


def test_blank_notes_stored_as_none(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    session = nets.start_session(add_net(conn), "2026-10-30")
    assert nets.close_session(session.id, "   ").closing_notes is None


def test_closed_session_refuses_writes(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    session = nets.start_session(add_net(conn), "2026-10-30")
    checkin = nets.add_checkin(session.id, "K3WGR")
    nets.close_session(session.id, "")
    with pytest.raises(SessionClosed, match="This session is closed"):
        nets.add_checkin(session.id, "W2KV")
    with pytest.raises(SessionClosed):
        nets.set_heard(checkin.id, "heard", None)
    with pytest.raises(SessionClosed):
        nets.update_checkin(checkin.id, name="Bob", grid=None, qth=None, report=None,
                            notes=None)  # fmt: skip
    nets.reopen_session(session.id)
    nets.add_checkin(session.id, "W2KV")
    nets.set_heard(checkin.id, "heard", None)


def test_closed_check_comes_before_duplicate_check(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    session = nets.start_session(add_net(conn), "2026-10-30")
    nets.add_checkin(session.id, "K3WGR")
    nets.close_session(session.id, "")
    with pytest.raises(SessionClosed):
        nets.add_checkin(session.id, "K3WGR")


def test_last_closing_notes_scope(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    net_a, net_b = add_net(conn, "A"), add_net(conn, "B")
    first = nets.start_session(net_a, "2026-10-19")
    nets.close_session(first.id, "first")
    other = nets.start_session(net_b, "2026-10-20")
    nets.close_session(other.id, "other net")
    second = nets.start_session(net_a, "2026-10-26")
    assert nets.last_closing_notes(net_a, second.id) == ("2026-10-19", "first")
    nets.close_session(second.id, "")
    third = nets.start_session(net_a, "2026-11-02")
    assert nets.last_closing_notes(net_a, third.id) is None  # newest closed has no notes
    assert nets.last_closing_notes(net_b, third.id) == ("2026-10-20", "other net")


def test_last_closing_notes_skips_this_session(conn: sqlite3.Connection) -> None:
    nets = NetRepository(conn)
    net_id = add_net(conn)
    session = nets.start_session(net_id, "2026-10-26")
    nets.close_session(session.id, "mine")
    assert nets.last_closing_notes(net_id, session.id) is None
