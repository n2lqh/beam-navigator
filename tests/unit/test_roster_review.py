import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from beam_navigator.core.models import Net, OperatorProfile, Station
from beam_navigator.desk import Desk
from beam_navigator.roster_review import RosterReview
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository, ProfileRepository, StationRepository

FIXTURES = Path(__file__).parents[1] / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def review(conn: sqlite3.Connection) -> RosterReview:
    profiles = ProfileRepository(conn)
    saved = profiles.save(
        OperatorProfile(None, "Home", "N2LQH", "FM29pt", None, "mi", "America/New_York", "NJ",
                        False)  # fmt: skip
    )
    assert saved.id is not None
    profiles.activate(saved.id)
    sim = SimulationAdapter(az_max=360)
    desk = Desk(conn, RotateService(conn, adapter_for=lambda p: sim, tester_for=lambda p: sim))
    return RosterReview(conn, desk)


@pytest.fixture
def net_id(conn: sqlite3.Connection) -> int:
    saved = NetRepository(conn).save_net(
        Net(None, "W2KV 2 m", None, None, None, 144.245, None, None, "2 m", None, None, False)
    )
    assert saved.id is not None
    return saved.id


def test_w2kv_review(review: RosterReview) -> None:
    result = review.parse(fixture("w2kv_144mhz_2026-10-26.txt"))
    included = [row for row in result.rows if row.include]
    assert len(included) == 17
    assert result.controller_suggested
    assert [row.callsign for row in result.rows if row.is_controller] == ["W2KV"]
    assert "Text says 18 check-ins; 17 parsed." in result.warnings
    k3wgr = next(row for row in result.rows if row.callsign == "K3WGR")
    assert k3wgr.grid == "FN10xi"
    assert k3wgr.from_you is not None and k3wgr.distance is not None


def test_published_never_from_you(review: RosterReview) -> None:  # acceptance 12
    result = review.parse(fixture("n3rg_50mhz_2026-10-26.txt"))
    me = next(row for row in result.rows if row.callsign == "N2LQH")
    assert me.published is not None and me.published.startswith("35")
    assert me.from_you is None  # FM29pt is home
    for row in result.rows:
        assert row.from_you is None or row.from_you != row.published


def test_unparsed_rows_kept_out_and_in_raw_text(
    review: RosterReview, conn: sqlite3.Connection, net_id: int
) -> None:
    text = "1 K1DY BILL TROY, ME FN54jq\n?? smudge ??\n2 AF3G GLEN HOLLAND, PA FN20LE"
    result = review.parse(text)
    smudge = result.rows[1]
    assert smudge.callsign is None and not smudge.include
    assert smudge.line_text == "?? smudge ??"
    smudge.include = True  # the UI never allows it; save must ignore it anyway
    session = review.save(net_id, "2026-10-26", result)
    assert len(NetRepository(conn).checkins(session.id)) == 2
    assert session.raw_text == text


def test_edit_grid_recomputes(review: RosterReview) -> None:
    result = review.parse(fixture("ka3wxv_dmr_2026-10-26.txt"))
    row = next(row for row in result.rows if row.callsign)
    assert row.grid is None and row.from_you is None
    row.grid = "FN20ok"
    review.recompute(row)
    assert row.from_you is not None and row.from_you.endswith(" N")


def test_invalid_edited_grid_refused(
    review: RosterReview, conn: sqlite3.Connection, net_id: int
) -> None:  # Focus 4
    result = review.parse(fixture("w2kv_144mhz_2026-10-26.txt"))
    result.rows[2].grid = "ZZ99"
    with pytest.raises(ValueError, match="'ZZ99' is not a grid square"):
        review.save(net_id, "2026-10-26", result)
    assert NetRepository(conn).sessions(net_id) == []


def test_blank_grid_saved_as_missing(
    review: RosterReview, conn: sqlite3.Connection, net_id: int
) -> None:
    result = review.parse(fixture("w2kv_144mhz_2026-10-26.txt"))
    result.rows[0].grid = "  "
    session = review.save(net_id, "2026-10-26", result)
    assert NetRepository(conn).checkins(session.id)[0].grid is None


def test_excluded_row_not_saved_but_raw_text_kept(
    review: RosterReview, conn: sqlite3.Connection, net_id: int
) -> None:
    text = fixture("w2kv_144mhz_2026-10-26.txt")
    result = review.parse(text)
    result.rows[0].include = False
    result.rows[1].name = "MARCUS"
    session = review.save(net_id, "2026-10-26", result)
    checkins = NetRepository(conn).checkins(session.id)
    assert len(checkins) == 16
    assert "K4SO" not in [c.callsign for c in checkins]
    assert checkins[0].name == "MARCUS"
    assert session.raw_text == text


def test_controller_choice(review: RosterReview, conn: sqlite3.Connection, net_id: int) -> None:
    result = review.parse(fixture("w2kv_144mhz_2026-10-26.txt"))
    review.set_controller(result, 0)
    assert [row.callsign for row in result.rows if row.is_controller] == ["K4SO"]
    session = review.save(net_id, "2026-10-26", result)
    assert session.controller_call == "K4SO"
    review.set_controller(result, None)
    assert not any(row.is_controller for row in result.rows)


def test_duplicate_detected_then_replace_or_keep(
    review: RosterReview, conn: sqlite3.Connection, net_id: int
) -> None:  # acceptance 13
    text = fixture("w2kv_144mhz_2026-10-26.txt")
    assert review.duplicate_of(net_id, "2026-10-26", review.parse(text)) is None
    first = review.save(net_id, "2026-10-26", review.parse(text))
    again = review.parse(text)
    assert review.duplicate_of(net_id, "2026-10-26", again) == first.id
    review.save(net_id, "2026-10-26", again, replace_session_id=first.id)
    assert len(NetRepository(conn).sessions(net_id)) == 1
    review.save(net_id, "2026-10-26", review.parse(text))
    assert len(NetRepository(conn).sessions(net_id)) == 2


def test_activity_night_no_controller(review: RosterReview) -> None:
    result = review.parse(fixture("wa3nuf_222mhz_activity_2026-10-21.txt"))
    assert not result.controller_suggested
    assert not any(row.is_controller for row in result.rows)


def test_acceptance_14_expected_after_import(
    review: RosterReview, conn: sqlite3.Connection, net_id: int
) -> None:
    review.save(net_id, "2026-10-26", review.parse(fixture("w2kv_144mhz_2026-10-26.txt")))
    nets = NetRepository(conn)
    tonight = nets.start_session(net_id, "2026-11-02")
    assert len(nets.expected(tonight.id)) == 17
    assert nets.checkins(tonight.id) == []


def test_create_net(review: RosterReview, conn: sqlite3.Connection) -> None:
    net = review.create_net(" W2KV 2 m ", "2 m", "144.245", "")
    assert (net.name, net.band, net.frequency_mhz, net.channel) == ("W2KV 2 m", "2 m", 144.245,
                                                                   None)  # fmt: skip
    dmr = review.create_net("Pack Rats DMR", None, "", "TG 31425")
    assert (dmr.frequency_mhz, dmr.channel, dmr.band) == (None, "TG 31425", None)
    for bad in (("", None, "", ""), ("W2KV 2 m", None, "", ""), ("X", None, "abc", ""),
                ("Y", None, "-5", ""), ("Z", "3 m", "", "")):  # fmt: skip
        with pytest.raises(ValueError):
            review.create_net(*bad)
    assert len(NetRepository(conn).list_nets()) == 2


def test_excluded_controller_row_keeps_the_controller(
    review: RosterReview, conn: sqlite3.Connection, net_id: int
) -> None:  # final review I3: the NCS is often left out of the check-ins
    result = review.parse(fixture("w2kv_144mhz_2026-10-26.txt"))
    controller = next(row for row in result.rows if row.is_controller)
    controller.include = False
    session = review.save(net_id, "2026-10-26", result)
    assert (session.controller_call, session.controller_grid) == ("W2KV", "FN20OK")
    assert "W2KV" not in [c.callsign for c in NetRepository(conn).checkins(session.id)]


def test_create_net_name_unique_ignoring_case(review: RosterReview) -> None:  # review I2
    review.create_net("Pack Rats", None, "", "")
    with pytest.raises(ValueError, match="A net called pack rats already exists."):
        review.create_net(" pack rats ", None, "", "")


# A newer roster grid replaces an earlier roster grid only when the operator says so
# (owner, 2026-10-29; decision 13 settled in decision 40).


def k3wgr_row(review: RosterReview, conn: sqlite3.Connection) -> tuple[object, object]:
    result = review.parse(fixture("w2kv_144mhz_2026-10-26.txt"))
    return result, next(row for row in result.rows if row.callsign == "K3WGR")


def test_earlier_roster_grid_is_offered(review: RosterReview, conn: sqlite3.Connection) -> None:
    StationRepository(conn).add_from_roster("K3WGR", None, "FN10xh", None)
    _, row = k3wgr_row(review, conn)
    assert row.earlier_grid == "FN10xh" and row.replace_grid is False  # type: ignore[attr-defined]


def test_a_saved_grid_is_never_offered(review: RosterReview, conn: sqlite3.Connection) -> None:
    StationRepository(conn).save(Station("K3WGR", None, "FN10xh", None, None, "saved", ""))
    _, row = k3wgr_row(review, conn)
    assert row.earlier_grid is None  # type: ignore[attr-defined]
    assert "Saved grid FN10xh differs" in row.warnings  # type: ignore[attr-defined]


def test_replace_when_chosen(review: RosterReview, conn: sqlite3.Connection, net_id: int) -> None:
    stations = StationRepository(conn)
    stations.add_from_roster("K3WGR", None, "FN10xh", None)
    result, row = k3wgr_row(review, conn)
    row.replace_grid = True  # type: ignore[attr-defined]
    review.save(net_id, "2026-10-26", result)  # type: ignore[arg-type]
    station = stations.get("K3WGR")
    assert station is not None and station.grid == "FN10xi" and station.source == "roster"


def test_kept_unless_chosen(review: RosterReview, conn: sqlite3.Connection, net_id: int) -> None:
    stations = StationRepository(conn)
    stations.add_from_roster("K3WGR", None, "FN10xh", None)
    result, _ = k3wgr_row(review, conn)
    review.save(net_id, "2026-10-26", result)  # type: ignore[arg-type]
    station = stations.get("K3WGR")
    assert station is not None and station.grid == "FN10xh"
