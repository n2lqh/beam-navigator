import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from beam_navigator.core.geometry import compass_name, short_path
from beam_navigator.core.maidenhead import grid_center
from beam_navigator.core.models import Net, OperatorProfile
from beam_navigator.core.roster_parser import parse_roster
from beam_navigator.desk import Desk
from beam_navigator.net_control import Entry, NetControl
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import (
    DuplicateCheckIn,
    NetRepository,
    ProfileRepository,
    StationRepository,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def control(conn: sqlite3.Connection) -> NetControl:
    profiles = ProfileRepository(conn)
    saved = profiles.save(
        OperatorProfile(None, "Home", "N2LQH", "FM29pt", None, "mi", "UTC", "NJ", False)
    )
    assert saved.id is not None
    profiles.activate(saved.id)
    sim = SimulationAdapter(az_max=360)
    desk = Desk(conn, RotateService(conn, adapter_for=lambda p: sim, tester_for=lambda p: sim))
    return NetControl(conn, desk)


@pytest.fixture
def net_id(conn: sqlite3.Connection) -> int:
    saved = NetRepository(conn).save_net(
        Net(None, "W2KV 2 m", 0, "20:00", "America/New_York", 144.245, None, "FM", "2 m",
            "W2KV", "FN20OK", False)  # fmt: skip
    )
    assert saved.id is not None
    text = (FIXTURES / "w2kv_144mhz_2026-10-26.txt").read_text(encoding="utf-8")
    NetRepository(conn).import_roster(saved.id, "2026-10-26", text, parse_roster(text))
    return saved.id


@pytest.fixture
def tonight(conn: sqlite3.Connection, net_id: int) -> int:
    return NetRepository(conn).start_session(net_id, "2026-11-02").id


def test_autofill_known(control: NetControl, net_id: int) -> None:  # acceptance 19
    found = control.autofill("k3wgr")
    assert found.known
    assert (found.callsign, found.grid, found.source) == ("K3WGR", "FN10xi", "roster")
    assert found.name and found.qth


def test_autofill_unknown(control: NetControl) -> None:  # acceptance 20
    found = control.autofill("K9ZZZ")
    assert not found.known
    assert (found.name, found.grid, found.qth) == (None, None, None)


def test_info_panel(
    control: NetControl, conn: sqlite3.Connection, net_id: int, tonight: int
) -> None:
    nets = NetRepository(conn)
    earlier = nets.sessions(net_id)[-1][0]
    row = next(c for c in nets.checkins(earlier.id) if c.callsign == "K3WGR")
    nets.update_checkin(row.id, name=row.name, grid=row.grid, qth=row.qth, report=None,
                        notes="weak but readable")  # fmt: skip
    control.add_station_note("K3WGR", "New 2 m yagi")
    info = control.info(tonight, "K3WGR")
    path = short_path(grid_center("FN20OK"), grid_center("FN10xi"))
    assert info.from_net_control is not None
    assert info.from_net_control.startswith(
        f"From net control: {path.bearing_deg:.1f}° {compass_name(path.bearing_deg)} · "
    )
    assert info.attendance == "1 of last 2"
    assert info.previous_notes == ["2026-10-26: weak but readable"]
    assert info.station_notes.endswith("New 2 m yagi")
    assert "FN10xi" in info.last
    assert control.info(tonight, "K9ZZZ").last == "No record"


def test_suggest_ranked_by_attendance(
    control: NetControl, conn: sqlite3.Connection, net_id: int, tonight: int
) -> None:  # acceptance 24
    nets = NetRepository(conn)
    old = nets.start_session(net_id, "2026-10-19")
    nets.add_checkin(old.id, "K3WGR")
    nets.add_checkin(old.id, "K3WXX")
    found = control.suggest(tonight, "K3W")
    assert [s.callsign for s in found][:2] == ["K3WGR", "K3WXX"]
    assert found[0].attended == 2
    assert control.suggest(tonight, "k") == []


def test_duplicate_base_call(control: NetControl, conn: sqlite3.Connection, tonight: int) -> None:
    control.log(tonight, Entry("K1ABC", name="BOB", grid="FN20ok"))  # Focus 2
    with pytest.raises(DuplicateCheckIn):
        control.log(tonight, Entry("K1ABC/P"))
    existing = control.duplicate(tonight, "k1abc/p")
    assert existing is not None and existing.logged_at is not None
    local = datetime.fromisoformat(existing.logged_at).astimezone(ZoneInfo("America/New_York"))
    assert control.duplicate_text(tonight, existing) == (
        f"Already checked in at {local:%H:%M} (#1)"
    )
    imported = NetRepository(conn).sessions(NetRepository(conn).get_session(tonight).net_id)
    old_session = imported[-1][0]
    first = NetRepository(conn).checkins(old_session.id)[0]
    assert control.duplicate_text(old_session.id, first) == (
        f"Already checked in (#{first.sequence})"
    )


def test_changes_and_case(control: NetControl, net_id: int) -> None:  # Focus 3, test 21
    record = control.autofill("K3WGR")
    assert control.changes(Entry("K3WGR", name=record.name or "", grid="fn10XI")) == []
    changed = control.changes(Entry("K3WGR", name="ALBERT", grid="FN10xh"))
    assert changed == [f"Name: {record.name} → ALBERT", "Grid: FN10xi → FN10xh"]
    assert control.changes(Entry("K3WGR")) == []  # blanks are not changes
    assert control.changes(Entry("K9ZZZ", name="NEW")) == []  # unknown station


def test_log_session_only_leaves_record(
    control: NetControl, conn: sqlite3.Connection, tonight: int
) -> None:  # acceptance 21
    control.log(tonight, Entry("K3WGR", name="AL", grid="FN10xh"))
    record = StationRepository(conn).get("K3WGR")
    assert record is not None and record.grid == "FN10xi"
    assert NetRepository(conn).checkins(tonight)[0].grid == "FN10xh"


def test_log_update_record(control: NetControl, conn: sqlite3.Connection, tonight: int) -> None:
    control.add_station_note("K3WGR", "keep me")
    control.log(tonight, Entry("K3WGR", name="AL", grid="FN10xh", qth="Wernersville"),
                update_record=True)  # fmt: skip
    record = StationRepository(conn).get("K3WGR")
    assert record is not None
    assert (record.grid, record.qth, record.source) == ("FN10xh", "Wernersville", "saved")
    assert record.notes.endswith("keep me")


def test_unknown_logged_with_blanks_flagged(
    control: NetControl, conn: sqlite3.Connection, tonight: int
) -> None:  # acceptance 20
    control.log(tonight, Entry("K9ZZZ"))
    [row] = control.rows(tonight)
    assert row.flags == ["name missing", "grid missing"]
    created = StationRepository(conn).get("K9ZZZ")
    assert created is not None and created.source == "roster"


def test_update_existing(control: NetControl, tonight: int) -> None:  # acceptance 22
    logged = control.log(tonight, Entry("K1ABC", name="BOB"))
    control.update_existing(logged.id, Entry("K1ABC", name="BOB", grid="FN20ok", report="59"))
    [row] = control.rows(tonight)
    assert (row.grid, row.report, row.flags) == ("FN20ok", "59", [])


def test_bad_grid_refused_nothing_logged(control: NetControl, tonight: int) -> None:
    with pytest.raises(ValueError):
        control.log(tonight, Entry("K1ABC", grid="ZZ99"))
    with pytest.raises(ValueError):
        control.log(tonight, Entry("  "))
    assert control.rows(tonight) == []


def test_merge_into_existing_keeps_what_was_not_retyped(
    control: NetControl, tonight: int
) -> None:  # final review C1
    logged = control.log(tonight, Entry("K1ABC", name="BOB", grid="FN20ok", notes="first"))
    control.merge_into_existing(logged.id, Entry("K1ABC", report="59"))
    [row] = control.rows(tonight)
    assert (row.name, row.grid, row.notes, row.report) == ("BOB", "FN20ok", "first", "59")
    with pytest.raises(ValueError):
        control.merge_into_existing(logged.id, Entry("K1ABC", grid="ZZ99"))


def test_times_shown_in_the_nets_time_zone(
    control: NetControl, conn: sqlite3.Connection, net_id: int
) -> None:  # decision 24, tzdata approved 2026-10-28
    nets = NetRepository(conn)
    tokyo = nets.save_net(replace(nets.get_net(net_id), id=None, name="Tokyo net",
                                  timezone="Asia/Tokyo"))  # fmt: skip
    assert tokyo.id is not None
    session = nets.start_session(tokyo.id, "2026-11-02").id
    logged = control.log(session, Entry("K1ABC"))
    assert logged.logged_at is not None
    expected = datetime.fromisoformat(logged.logged_at).astimezone(ZoneInfo("Asia/Tokyo"))
    assert control.rows(session)[0].time == f"{expected:%H:%M}"
    broken = nets.save_net(replace(nets.get_net(net_id), id=None, name="Bad zone",
                                   timezone="Not/AZone"))  # fmt: skip
    assert broken.id is not None
    other = nets.start_session(broken.id, "2026-11-02").id
    logged = control.log(other, Entry("K2ABC"))
    assert logged.logged_at is not None
    utc_profile = datetime.fromisoformat(logged.logged_at).astimezone(ZoneInfo("UTC"))
    assert control.rows(other)[0].time == f"{utc_profile:%H:%M}"  # falls back to the profile


def test_qrz_fill_only_blanks(control: NetControl, qrz_examples: list[bytes]) -> None:  # 4.9
    from dataclasses import replace

    from beam_navigator.core.qrz import parse_response
    from beam_navigator.net_control import Entry

    record = parse_response(qrz_examples[1]).record
    assert record is not None
    typed = Entry("AA7BQ", name="FRED", grid="", qth="")
    assert control.qrz_fill(typed, record) == Entry(
        "AA7BQ", name="FRED", grid="DM32af", qth="SCOTTSDALE, AZ"
    )
    vague = replace(record, geoloc="state")
    assert control.qrz_fill(typed, vague).grid == ""  # approximate: never a grid
