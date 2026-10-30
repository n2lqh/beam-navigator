import csv
import io
import json
import sqlite3
from collections.abc import Iterator

import pytest

from beam_navigator.core.models import Net, OperatorProfile
from beam_navigator.desk import Desk
from beam_navigator.export import export_filename, export_session
from beam_navigator.net_control import Entry, NetControl
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository, ProfileRepository

AWKWARD_NAME = 'O\'Brien, "Bob"'
AWKWARD_NOTES = "line one\nline two, with comma"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def desk(conn: sqlite3.Connection) -> Desk:
    profiles = ProfileRepository(conn)
    saved = profiles.save(
        OperatorProfile(None, "Home", "N2LQH", "FM29pt", None, "km", "UTC", "NJ", False)
    )
    assert saved.id is not None
    profiles.activate(saved.id)
    sim = SimulationAdapter(az_max=360)
    return Desk(conn, RotateService(conn, adapter_for=lambda p: sim, tester_for=lambda p: sim))


@pytest.fixture
def session_id(conn: sqlite3.Connection, desk: Desk) -> int:
    nets = NetRepository(conn)
    net = nets.save_net(
        Net(None, "W2KV 2 m", None, None, None, 144.245, None, None, "2 m", "W2KV", "FN20OK",
            False)  # fmt: skip
    )
    assert net.id is not None
    session = nets.start_session(net.id, "2026-11-02")
    control = NetControl(conn, desk)
    control.log(session.id, Entry("K3WGR", name="AL", grid="FN10xi", qth="Wernersville"))
    second = control.log(session.id, Entry("K1ABC", name=AWKWARD_NAME, notes=AWKWARD_NOTES))
    nets.set_heard(second.id, "weak")
    return session.id


def run(
    conn: sqlite3.Connection, desk: Desk, session_id: int, fmt: str, heard: bool = False
) -> str:
    return export_session(conn, desk, session_id, fmt, include_heard=heard)  # type: ignore[arg-type]


def test_header_fields_every_format(
    conn: sqlite3.Connection, desk: Desk, session_id: int
) -> None:
    for fmt in ("text", "csv", "json"):
        out = run(conn, desk, session_id, fmt)
        for value in ("W2KV 2 m", "2026-11-02", "144.245 MHz", "W2KV", "FN20OK"):
            assert value in out, (fmt, value)


def test_bearings_labelled_from_net_control(
    conn: sqlite3.Connection, desk: Desk, session_id: int
) -> None:
    assert "from net control" in run(conn, desk, session_id, "text")
    rows = list(csv.DictReader(io.StringIO(run(conn, desk, session_id, "csv"))))
    assert rows[0]["bearing"] != "" and rows[0]["bearing_from"] == "net control"  # K3WGR
    assert rows[1]["bearing"] == "" and rows[1]["bearing_from"] == ""  # K1ABC: never invented
    data = json.loads(run(conn, desk, session_id, "json"))
    assert data["bearings"] == "from net control"
    assert data["checkins"][0]["bearing"] is not None


def test_heard_excluded_by_default(conn: sqlite3.Connection, desk: Desk, session_id: int) -> None:
    for fmt in ("text", "csv", "json"):
        assert "weak" not in run(conn, desk, session_id, fmt).lower(), fmt
    assert "weak" in run(conn, desk, session_id, "text", heard=True)
    rows = list(csv.DictReader(io.StringIO(run(conn, desk, session_id, "csv", heard=True))))
    assert rows[1]["heard"] == "weak"
    data = json.loads(run(conn, desk, session_id, "json", heard=True))
    assert data["checkins"][1]["heard"] == "weak"


def test_csv_and_json_survive_awkward_text(
    conn: sqlite3.Connection, desk: Desk, session_id: int
) -> None:  # Focus 4
    rows = list(csv.DictReader(io.StringIO(run(conn, desk, session_id, "csv"))))
    assert (rows[1]["name"], rows[1]["notes"]) == (AWKWARD_NAME, AWKWARD_NOTES)
    data = json.loads(run(conn, desk, session_id, "json"))
    assert data["schema"] == 1
    assert (data["checkins"][1]["name"], data["checkins"][1]["notes"]) == (
        AWKWARD_NAME, AWKWARD_NOTES
    )


def test_filename(conn: sqlite3.Connection, session_id: int) -> None:
    nets = NetRepository(conn)
    session = nets.get_session(session_id)
    net = nets.get_net(session.net_id)
    assert export_filename(session, net, "csv") == "w2kv-2-m_2026-11-02.csv"
    assert export_filename(session, net, "text") == "w2kv-2-m_2026-11-02.txt"


def test_names_and_qth_in_proper_case(
    conn: sqlite3.Connection, desk: Desk, session_id: int
) -> None:  # owner, 2026-10-29
    control = NetControl(conn, desk)
    control.log(session_id, Entry("K2XYZ", name="MARY ANN", qth="CHERRY HILL, NJ"))
    text = run(conn, desk, session_id, "text")
    assert "Mary Ann" in text and "Cherry Hill, NJ" in text and "MARY ANN" not in text
    rows = list(csv.DictReader(io.StringIO(run(conn, desk, session_id, "csv"))))
    assert (rows[2]["name"], rows[2]["qth"]) == ("Mary Ann", "Cherry Hill, NJ")
    assert rows[0]["name"] == "Al"
    data = json.loads(run(conn, desk, session_id, "json"))
    assert data["checkins"][2]["name"] == "Mary Ann"


def test_report_and_notes_can_be_left_out(
    conn: sqlite3.Connection, desk: Desk, session_id: int
) -> None:  # owner, 2026-10-29
    control = NetControl(conn, desk)
    control.log(session_id, Entry("K2XYZ", report="59"))
    def out(fmt: str, report: bool, notes: bool) -> str:
        return export_session(conn, desk, session_id, fmt,  # type: ignore[arg-type]
                              include_report=report, include_notes=notes)  # fmt: skip
    full = out("text", True, True)
    assert "59" in full and "Notes: line one" in full
    bare = out("text", False, False)
    assert "59" not in bare and "Notes:" not in bare
    columns = csv.DictReader(io.StringIO(out("csv", False, False))).fieldnames or []
    assert "report" not in columns and "notes" not in columns and "name" in columns
    first = json.loads(out("json", True, False))["checkins"][0]
    assert "report" in first and "notes" not in first


def test_text_is_one_block_per_station(
    conn: sqlite3.Connection, desk: Desk, session_id: int
) -> None:  # owner, 2026-10-29: the layout of W2KV's roster, plus the bearing
    control = NetControl(conn, desk)
    control.log(session_id, Entry("K4SO", name="MARK", grid="FM18ap", qth="AMISSVILLE, VA",
                                  report="59"))  # fmt: skip
    text = run(conn, desk, session_id, "text")
    blocks = text.split("\n\n")
    assert blocks[0].splitlines()[0] == "W2KV 2 m — 2026-11-02"
    first = blocks[1].splitlines()
    assert first[:3] == ["K3WGR", "Al", "Wernersville FN10xi"]
    assert first[3].endswith(" km") and "° from net control, " in first[3]
    awkward = blocks[2].splitlines()
    assert awkward == ["K1ABC", AWKWARD_NAME, "Notes: line one / line two, with comma"]
    last = blocks[3].splitlines()
    assert last[:3] == ["K4SO", "Mark", "Amissville, VA FM18ap"]
    assert last[4] == "Report: 59"
    assert text.endswith("Report: 59\n")


def own_station_session(conn: sqlite3.Connection, units: str) -> tuple[Desk, int]:
    """A net with no net control, logged by N2LQH at FM29pt."""
    profiles = ProfileRepository(conn)
    mine = profiles.save(
        OperatorProfile(None, "Mine", "N2LQH", "FM29pt", None, units, "UTC", "NJ", False)
    )
    assert mine.id is not None
    profiles.activate(mine.id)
    desk = Desk(conn, RotateService(conn))
    nets = NetRepository(conn)
    net = nets.save_net(Net(None, "No controller net", None, None, None, 144.25, None, None,
                            "2 m", None, None, False))  # fmt: skip
    assert net.id is not None
    session = nets.start_session(net.id, "2026-10-29")
    NetControl(conn, desk).log(session.id, Entry("K3WGR", name="AL", grid="FN10xi"))
    return desk, session.id


def test_bearings_from_own_station_without_net_control(conn: sqlite3.Connection) -> None:
    desk, session = own_station_session(conn, "km")  # owner, 2026-10-29
    text = run(conn, desk, session, "text")
    assert "Net control: unknown" in text
    assert "Bearings are from N2LQH (FM29pt): net control's location is unknown." in text
    assert "° from N2LQH, " in text and "from net control" not in text.split("\n\n")[1]
    rows = list(csv.DictReader(io.StringIO(run(conn, desk, session, "csv"))))
    assert rows[0]["bearing"] != "" and rows[0]["bearing_from"] == "N2LQH (FM29pt)"
    assert json.loads(run(conn, desk, session, "json"))["bearings"] == "from N2LQH (FM29pt)"


def test_distance_in_the_operators_units(conn: sqlite3.Connection) -> None:
    desk, session = own_station_session(conn, "mi")
    block = run(conn, desk, session, "text").split("\n\n")[1]
    assert block.splitlines()[-1].endswith(" mi")
    rows = list(csv.DictReader(io.StringIO(run(conn, desk, session, "csv"))))
    assert "distance_mi" in rows[0] and "distance_km" not in rows[0]
    assert NetControl(conn, desk).live.controller_location(session) is None  # from N2LQH
    from beam_navigator.core.geometry import short_path
    from beam_navigator.core.maidenhead import grid_center

    expected = short_path(grid_center("FM29pt"), grid_center("FN10xi")).distance_km / 1.609344
    assert float(rows[0]["distance_mi"]) == pytest.approx(expected, abs=0.05)
    data = json.loads(run(conn, desk, session, "json"))
    assert data["checkins"][0]["distance_mi"] == float(rows[0]["distance_mi"])


def test_no_bearings_without_any_known_origin(conn: sqlite3.Connection) -> None:
    desk = Desk(conn, RotateService(conn))  # no profile, no net control: nothing to measure from
    nets = NetRepository(conn)
    net = nets.save_net(Net(None, "Bare net", None, None, None, None, "TG 1", None, None, None,
                            None, False))  # fmt: skip
    assert net.id is not None
    session = nets.start_session(net.id, "2026-10-29")
    NetControl(conn, desk).log(session.id, Entry("K3WGR", grid="FN10xi"))
    text = run(conn, desk, session.id, "text")
    assert "No bearings: net control's location is unknown." in text and "°" not in text
