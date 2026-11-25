from collections.abc import Iterator
from pathlib import Path

import pytest

from beam_navigator.core.models import Net
from beam_navigator.core.roster_parser import parse_roster
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import DuplicateCheckIn, NetRepository

FIXTURES = Path(__file__).parent.parent / "fixtures"
W2KV_TEXT = (FIXTURES / "w2kv_144mhz_2026-10-26.txt").read_text(encoding="utf-8")
W2KV_CALLS = [str(row.callsign) for row in parse_roster(W2KV_TEXT).checkins]


@pytest.fixture
def nets() -> Iterator[NetRepository]:
    conn = open_db(":memory:")
    yield NetRepository(conn)
    conn.close()


def two_metre_net(nets: NetRepository) -> int:
    net = nets.save_net(
        Net(None, "Pack Rats 2 m", 0, "20:00", "America/New_York", 144.245, None, "SSB", "2 m",
            "W2KV", "FN20ok", False)  # fmt: skip
    )
    assert net.id is not None
    return net.id


def test_expected_stations_for_next_week(nets: NetRepository) -> None:  # acceptance 14
    net_id = two_metre_net(nets)
    nets.import_roster(net_id, "2026-10-26", W2KV_TEXT, parse_roster(W2KV_TEXT))
    session = nets.start_session(net_id, "2026-11-02")
    assert session.status == "active"
    expected = nets.expected(session.id)
    assert sorted(p.callsign for p in expected) == sorted(W2KV_CALLS)
    assert len(expected) == 17
    assert nets.checkins(session.id) == []  # expected, never checked in
    nets.add_checkin(session.id, "k4so")
    assert len(nets.expected(session.id)) == 16
    assert "K4SO" not in {p.callsign for p in nets.expected(session.id)}


def test_participants_count_attendance(nets: NetRepository) -> None:
    net_id = two_metre_net(nets)
    nets.import_roster(net_id, "2026-10-26", W2KV_TEXT, parse_roster(W2KV_TEXT))
    later = nets.start_session(net_id, "2026-11-02")
    nets.add_checkin(later.id, "K3WGR", grid="FN10xh")
    nets.add_checkin(later.id, "K1ABC")
    people = {p.callsign: p for p in nets.participants(net_id)}
    assert people["K3WGR"].sessions_attended == 2
    assert people["K3WGR"].last_grid == "FN10xh"
    assert people["K3WGR"].last_seen == "2026-11-02"
    assert people["K1ABC"].last_grid is None
    assert people["K4SO"].sessions_attended == 1
    assert people["K4SO"].last_seen == "2026-10-26"


def test_substitute_controller_is_one_night_only(nets: NetRepository) -> None:  # acceptance 15
    net_id = two_metre_net(nets)
    a = nets.import_roster(net_id, "2026-10-26", W2KV_TEXT, parse_roster(W2KV_TEXT))
    b = nets.start_session(net_id, "2026-11-02")
    assert (b.controller_call, b.controller_grid) == ("W2KV", "FN20ok")  # copied from default
    nets.set_session_controller(b.id, "n3rg", "FM29ki")
    net = nets.get_net(net_id)
    assert (net.default_controller_call, net.default_controller_grid) == ("W2KV", "FN20ok")
    assert nets.get_session(a.id).controller_call == "W2KV"
    assert nets.get_session(b.id).controller_call == "N3RG"
    nets.save_controller_as_default(b.id)
    net = nets.get_net(net_id)
    assert (net.default_controller_call, net.default_controller_grid) == ("N3RG", "FM29ki")
    assert nets.get_session(a.id).controller_call == "W2KV"


def test_duplicate_checkin_needs_explicit_choice(nets: NetRepository) -> None:  # spec 3
    net_id = two_metre_net(nets)
    session = nets.start_session(net_id, "2026-11-02")
    first = nets.add_checkin(session.id, "W2KV", name="DAVE")
    with pytest.raises(DuplicateCheckIn) as caught:
        nets.add_checkin(session.id, "w2kv")
    assert caught.value.existing == first
    assert caught.value.callsign == "W2KV"
    second = nets.add_checkin(session.id, "W2KV", allow_duplicate=True)
    assert second.sequence == 2
    assert [c.callsign for c in nets.checkins(session.id)] == ["W2KV", "W2KV"]


def test_start_session_rejects_bad_date(nets: NetRepository) -> None:
    net_id = two_metre_net(nets)
    with pytest.raises(ValueError):
        nets.start_session(net_id, "Monday")


def test_expected_matches_base_callsign() -> None:
    # final review I2: W1ABC/M tonight means W1ABC is not "not heard yet"
    conn = open_db(":memory:")
    nets = NetRepository(conn)
    net = nets.save_net(Net(None, "N", None, None, None, None, None, None, None, None, None,
                            False))  # fmt: skip
    assert net.id is not None
    nets.add_checkin(nets.start_session(net.id, "2026-10-26").id, "W1ABC")
    tonight = nets.start_session(net.id, "2026-11-02").id
    nets.add_checkin(tonight, "W1ABC/M")
    assert [p.callsign for p in nets.expected(tonight)] == []


def test_import_without_a_controller_uses_the_nets_saved_one(nets: NetRepository) -> None:
    # owner, 2026-11-21: an imported session had no net control though the net had one
    net_id = two_metre_net(nets)
    session = nets.import_roster(
        net_id, "2026-10-26", W2KV_TEXT, parse_roster(W2KV_TEXT), controller=None
    )
    assert (session.controller_call, session.controller_grid) == ("W2KV", "FN20ok")


def test_start_session_twice_opens_the_same_session(nets: NetRepository) -> None:
    # One session per net per night (owner, 2026-11-24).
    net_id = two_metre_net(nets)
    first = nets.start_session(net_id, "2026-11-23")
    nets.close_session(first.id, "")
    again = nets.start_session(net_id, "2026-11-23")
    assert again.id == first.id and again.status == "closed"
    assert nets.start_session(net_id, "2026-11-30").id != first.id


def test_session_on(nets: NetRepository) -> None:
    net_id = two_metre_net(nets)
    assert nets.session_on(net_id, "2026-11-23") is None
    made = nets.start_session(net_id, "2026-11-23")
    assert nets.session_on(net_id, "2026-11-23") == made


def test_import_refuses_a_night_that_has_a_session(nets: NetRepository) -> None:
    net_id = two_metre_net(nets)
    nets.start_session(net_id, "2026-10-26")
    with pytest.raises(ValueError, match="already has a session on 2026-10-26"):
        nets.import_roster(net_id, "2026-10-26", W2KV_TEXT, parse_roster(W2KV_TEXT))


def test_start_session_on_an_imported_night_makes_it_yours(nets: NetRepository) -> None:
    # Final review: logging into an import left it "imported", so Replace could delete it.
    net_id = two_metre_net(nets)
    imported = nets.import_roster(net_id, "2026-10-26", W2KV_TEXT, parse_roster(W2KV_TEXT))
    started = nets.start_session(net_id, "2026-10-26")
    assert started.id == imported.id and started.status == "active"
    assert len(nets.checkins(started.id)) == 17


def test_replace_refuses_an_import_holding_your_check_ins(nets: NetRepository) -> None:
    net_id = two_metre_net(nets)
    imported = nets.import_roster(net_id, "2026-10-26", W2KV_TEXT, parse_roster(W2KV_TEXT))
    nets.add_checkin(imported.id, "W1AW")  # logged from the live net screen
    with pytest.raises(ValueError, match="your own check-ins"):
        nets.import_roster(
            net_id, "2026-10-26", W2KV_TEXT, parse_roster(W2KV_TEXT),
            replace_session_id=imported.id,
        )  # fmt: skip
    assert "W1AW" in [c.callsign for c in nets.checkins(imported.id)]


def test_session_on_prefers_your_own_session_over_an_import(nets: NetRepository) -> None:
    # Owner's 144 MHz 2026-11-23: their closed #25 and an older-rule import #28.
    net_id = two_metre_net(nets)
    mine = nets.start_session(net_id, "2026-11-23")
    nets.close_session(mine.id, "")
    nets._conn.execute(  # an import made before one session per night (owner, 2026-11-24)
        "INSERT INTO session (net_id, date, status, raw_text, created_at)"
        " VALUES (?, '2026-11-23', 'imported', 'x', '2026-11-24T00:00:00+00:00')",
        (net_id,),
    )
    found = nets.session_on(net_id, "2026-11-23")
    assert found is not None and found.id == mine.id
    assert nets.start_session(net_id, "2026-11-23").id == mine.id
