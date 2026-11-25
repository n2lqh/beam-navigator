"""Comparing the owner's session with net control's list (owner, 2026-11-24)."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from beam_navigator.core.models import Net, OperatorProfile
from beam_navigator.core.qrz import QrzRecord
from beam_navigator.desk import Desk
from beam_navigator.roster_compare import RosterCompare
from beam_navigator.roster_review import Review, RosterReview
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository, ProfileRepository

W2KV = (Path(__file__).parents[1] / "fixtures" / "w2kv_144mhz_2026-10-26.txt").read_text(
    encoding="utf-8"
)
NOTE = "From net control's list"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def desk(conn: sqlite3.Connection) -> Desk:
    profiles = ProfileRepository(conn)
    saved = profiles.save(
        OperatorProfile(None, "Home", "N2LQH", "FM29pt", None, "mi", "America/New_York", "NJ",
                        False)  # fmt: skip
    )
    assert saved.id is not None
    profiles.activate(saved.id)
    sim = SimulationAdapter(az_max=360)
    return Desk(conn, RotateService(conn, adapter_for=lambda p: sim, tester_for=lambda p: sim))


@pytest.fixture
def nets(conn: sqlite3.Connection) -> NetRepository:
    return NetRepository(conn)


@pytest.fixture
def session_id(nets: NetRepository) -> int:
    net = nets.save_net(
        Net(None, "W2KV 2 m", None, None, None, 144.245, None, None, "2 m", None, None, False)
    )
    assert net.id is not None
    session = nets.start_session(net.id, "2026-10-26")
    nets.add_checkin(session.id, "K3WGR", grid="FN10")
    nets.add_checkin(session.id, "W1AW")
    return session.id


@pytest.fixture
def review(conn: sqlite3.Connection, desk: Desk) -> Review:
    return RosterReview(conn, desk).parse(W2KV)


@pytest.fixture
def compare(conn: sqlite3.Connection, desk: Desk) -> RosterCompare:
    return RosterCompare(conn, desk)


def only(compare_result_missing: list, *calls: str) -> None:  # type: ignore[type-arg]
    for row in compare_result_missing:
        row.add = row.callsign in calls


def test_compare_groups(compare: RosterCompare, session_id: int, review: Review) -> None:
    result = compare.compare(session_id, review)
    assert [(b.callsign, b.differences) for b in result.both] == [
        ("K3WGR", ["Grid: FN10 (you) · FN10xi (net control)"])
    ]
    assert [c.callsign for c in result.only_mine] == ["W1AW"]
    listed = [row.callsign for row in review.rows if row.include and row.callsign]
    expected = [c for c in listed if c not in ("K3WGR", "N2LQH")]
    assert [m.callsign for m in result.missing] == expected
    assert len(result.missing) == 15 and all(m.add for m in result.missing)


def test_add_marks_not_heard_with_a_note(
    compare: RosterCompare, nets: NetRepository, session_id: int, review: Review
) -> None:
    result = compare.compare(session_id, review)
    only(result.missing, "K4SO", "KD4AA")
    added = compare.add(result)
    assert [c.callsign for c in added] == ["K4SO", "KD4AA"]
    for checkin in added:
        assert checkin.heard_state == "not_heard"
        assert checkin.notes == NOTE
        assert checkin.logged_at is None
    assert [c.sequence for c in added] == [3, 4]
    assert nets.get_session(session_id).raw_text == W2KV


def test_add_works_on_a_closed_session(
    compare: RosterCompare, nets: NetRepository, session_id: int, review: Review
) -> None:
    nets.close_session(session_id, "")
    result = compare.compare(session_id, review)
    only(result.missing, "K4SO")
    assert [c.callsign for c in compare.add(result)] == ["K4SO"]
    assert nets.get_session(session_id).status == "closed"


def _k4so(review: Review):  # type: ignore[no-untyped-def]
    return next(row for row in review.rows if row.callsign == "K4SO")


def test_add_uses_stored_qrz_finer_grid_and_fills_blanks(
    compare: RosterCompare, desk: Desk, nets: NetRepository, session_id: int, review: Review
) -> None:
    desk.qrz_store(
        QrzRecord("K4SO", "MARK SMITH", "FM18ap", "AMISSVILLE, VA", None, None, "user"), None
    )
    result = compare.compare(session_id, review)
    only(result.missing, "K4SO")
    [kept] = compare.add(result)
    assert (kept.name, kept.grid) == ("MARK", "FM18AP")  # QRZ fills blanks only


@pytest.mark.parametrize(
    ("name", "grid", "want"),
    [("MARK", "FM18", ("MARK", "FM18ap")), ("", "", ("MARK SMITH", "FM18ap"))],
)
def test_add_refines_a_rough_grid_and_fills_blanks_from_qrz(
    compare: RosterCompare, desk: Desk, session_id: int, review: Review,
    name: str, grid: str, want: tuple[str, str],
) -> None:  # fmt: skip
    desk.qrz_store(
        QrzRecord("K4SO", "MARK SMITH", "FM18ap", "AMISSVILLE, VA", None, None, "user"), None
    )
    row = _k4so(review)
    row.name, row.grid = name, grid
    result = compare.compare(session_id, review)
    only(result.missing, "K4SO")
    [added] = compare.add(result)
    assert (added.name, added.grid) == want
    record = desk.stations.get("K4SO")
    assert record is not None and record.grid in (None, "FM18")  # QRZ's grid isn't roster-learned


def test_qrz_grid_from_a_zip_is_ignored(
    compare: RosterCompare, desk: Desk, session_id: int, review: Review
) -> None:
    desk.qrz_store(QrzRecord("K4SO", None, "FM18xx", None, None, None, "zip"), None)
    _k4so(review).grid = ""
    result = compare.compare(session_id, review)
    only(result.missing, "K4SO")
    [added] = compare.add(result)
    assert added.grid is None


def test_qrz_wanted(compare: RosterCompare, desk: Desk, session_id: int, review: Review) -> None:
    desk.qrz_store(QrzRecord("K4SO", "MARK", "FM18ap", None, None, None, "user"), None)
    result = compare.compare(session_id, review)
    only(result.missing, "K4SO", "KD4AA", "KA3FQS")
    assert compare.qrz_wanted(result) == ["KD4AA", "KA3FQS"]


def test_duplicate_rows_add_once(
    compare: RosterCompare, session_id: int, review: Review
) -> None:  # Review Focus 2
    review.rows.append(_k4so(review))
    result = compare.compare(session_id, review)
    assert [m.callsign for m in result.missing].count("K4SO") == 1
    only(result.missing, "K4SO")
    assert len(compare.add(result)) == 1


def test_add_twice_adds_nothing_more(
    compare: RosterCompare, nets: NetRepository, session_id: int, review: Review
) -> None:  # Review Focus 3
    result = compare.compare(session_id, review)
    first = compare.add(result)
    assert len(first) == 15
    assert compare.add(result) == []
    assert len(nets.checkins(session_id)) == 17


def test_excluded_rows_are_not_compared(
    compare: RosterCompare, session_id: int, review: Review
) -> None:  # Review Focus 4
    _k4so(review).include = False
    result = compare.compare(session_id, review)
    calls = [m.callsign for m in result.missing] + [b.callsign for b in result.both]
    assert "K4SO" not in calls


def test_add_refuses_a_bad_grid(
    compare: RosterCompare, nets: NetRepository, session_id: int, review: Review
) -> None:  # final review: Save checks grids, so Add must too
    _k4so(review).grid = "ZZ99"
    result = compare.compare(session_id, review)
    with pytest.raises(ValueError, match="'ZZ99' is not a grid square"):
        compare.add(result)
    assert len(nets.checkins(session_id)) == 2
