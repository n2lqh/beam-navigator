"""Net rules: the form, save, duplicate, archive and the history view (spec 4.6)."""

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from beam_navigator.core.models import OperatorProfile, RotatorProfile
from beam_navigator.core.roster_parser import parse_roster
from beam_navigator.desk import Desk
from beam_navigator.nets import NetBook, NetForm
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository, ProfileRepository, RotatorRepository

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = datetime(2026, 11, 3, 18, 0, tzinfo=ZoneInfo("America/New_York"))  # a Tuesday


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def book(conn: sqlite3.Connection) -> NetBook:
    profiles = ProfileRepository(conn)
    saved = profiles.save(
        OperatorProfile(None, "Home", None, "FM29pt", None, "mi", "America/New_York", "NJ",
                        False)  # fmt: skip
    )
    assert saved.id is not None
    profiles.activate(saved.id)
    sim = SimulationAdapter(az_max=360)
    desk = Desk(conn, RotateService(conn, adapter_for=lambda p: sim, tester_for=lambda p: sim))
    return NetBook(conn, desk)


def form(**changes: object) -> NetForm:
    base = NetForm(
        name="Test net", weekday=1, start_time="20:00", timezone="America/New_York",
        frequency="144.2", channel="", mode="SSB", band="2 m", controller_call="k1abc",
        controller_grid="FN20ok", rotator_id=None,
    )  # fmt: skip
    return replace(base, **changes)  # type: ignore[arg-type]


def test_save_and_form_round_trip(book: NetBook, conn: sqlite3.Connection) -> None:
    rotator = RotatorRepository(conn).save(
        RotatorProfile(None, "Tower", "simulation", None, None, 0.0, 360.0, 0.0, None, (),
                       False, False)  # fmt: skip
    )
    net = book.save(form(rotator_id=rotator.id))
    assert net.id is not None
    assert book.form_for(net.id) == form(controller_call="K1ABC", rotator_id=rotator.id)


def test_blanks_stored_as_none(book: NetBook) -> None:
    net = book.save(
        form(weekday=None, start_time="", timezone="", frequency="", channel="TG 31", mode="",
             band=None, controller_call="", controller_grid="")  # fmt: skip
    )
    assert (net.weekday, net.start_time, net.timezone, net.frequency_mhz, net.mode) == (
        None, None, None, None, None
    )  # fmt: skip
    assert (net.channel, net.band, net.default_controller_call) == ("TG 31", None, None)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": "  "}, "A net needs a name."),
        ({"start_time": "8pm"}, "Start time must be HH:MM, 24-hour."),
        ({"timezone": "America/NewYork"}, "Unknown time zone 'America/NewYork'."),
        ({"start_time": ""}, "Give both a weekday and a start time, or neither."),
        ({"weekday": None}, "Give both a weekday and a start time, or neither."),
        ({"frequency": "-1"}, "Frequency must be a positive number of MHz."),
        ({"frequency": "fast"}, "Frequency must be a positive number of MHz."),
        ({"frequency": "nan"}, "Frequency must be a positive number of MHz."),
        ({"band": "4 m"}, "Unknown band '4 m'. Add it in Settings → Bands first."),
        ({"controller_call": "net control"}, "'NET CONTROL' is not a callsign."),
        ({"controller_grid": "ZZ99"}, "'ZZ99' is not a grid square."),
        ({"rotator_id": 999}, "No rotator with id 999."),
        ({"weekday": 7}, "Weekday must be Monday to Sunday."),
    ],
)
def test_save_rules(book: NetBook, changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError) as caught:
        book.save(form(**changes))
    assert str(caught.value).startswith(message)
    assert book.listing(NOW, show_archived=True) == []


def test_name_unique_ignoring_case(book: NetBook) -> None:
    net = book.save(form())
    assert net.id is not None
    with pytest.raises(ValueError, match="A net called test NET already exists."):
        book.save(form(name=" test NET "))
    assert book.save(form(mode="FM"), net.id).mode == "FM"  # its own name is fine


def test_duplicate_names_copies(book: NetBook, conn: sqlite3.Connection) -> None:
    net = book.save(form())
    assert net.id is not None
    NetRepository(conn).start_session(net.id, "2026-11-03")
    first, second = book.duplicate(net.id), book.duplicate(net.id)
    assert (first.name, second.name) == ("Test net (copy)", "Test net (copy 2)")
    assert first.id is not None
    assert book.form_for(first.id) == replace(book.form_for(net.id), name="Test net (copy)")
    assert not first.archived
    assert NetRepository(conn).sessions(first.id) == []


def test_archived_hidden_but_history_kept(book: NetBook, conn: sqlite3.Connection) -> None:
    net = book.save(form())
    assert net.id is not None
    session = NetRepository(conn).start_session(net.id, "2026-11-03")
    book.set_archived(net.id, True)
    assert book.listing(NOW) == []
    assert book.pickable() == []
    assert [s.net.name for s in book.listing(NOW, show_archived=True)] == ["Test net"]
    assert [s.id for s, _ in book.view(net.id, NOW).sessions] == [session.id]
    book.set_archived(net.id, False)
    assert [n.name for n in book.pickable()] == ["Test net"]


def test_edit_keeps_archived(book: NetBook) -> None:
    net = book.save(form())
    assert net.id is not None
    book.set_archived(net.id, True)
    assert book.save(form(mode="FM"), net.id).archived


def test_edit_does_not_rewrite_sessions(book: NetBook, conn: sqlite3.Connection) -> None:
    net = book.save(form())
    assert net.id is not None
    session = NetRepository(conn).start_session(net.id, "2026-11-03")
    book.save(form(controller_call="W2KV", controller_grid="FN20ok"), net.id)
    after = NetRepository(conn).get_session(session.id)
    assert (after.controller_call, after.controller_grid) == ("K1ABC", "FN20ok")


def test_view_participants_and_controller(book: NetBook, conn: sqlite3.Connection) -> None:
    net = book.save(form(controller_call="", controller_grid=""))
    assert net.id is not None
    text = (FIXTURES / "w2kv_144mhz_2026-10-26.txt").read_text(encoding="utf-8")
    NetRepository(conn).import_roster(net.id, "2026-10-26", text, parse_roster(text))
    view = book.view(net.id, NOW)
    assert len(view.participants) == 17
    calls = [p.callsign for p in view.participants]
    assert calls == sorted(calls)  # all attended once, so callsign order
    assert view.controller_text == "No default controller"
    book.save(form(controller_call="W2KV", controller_grid="FN20ok"), net.id)
    assert book.view(net.id, NOW).controller_text == "W2KV · FN20ok"
    book.save(form(controller_call="W2KV", controller_grid=""), net.id)
    assert book.view(net.id, NOW).controller_text == "W2KV · grid unknown"


def test_participants_ranked_by_attendance(book: NetBook, conn: sqlite3.Connection) -> None:
    net = book.save(form())
    assert net.id is not None
    nets = NetRepository(conn)
    for day in ("2026-11-03", "2026-11-10"):
        nets.add_checkin(nets.start_session(net.id, day).id, "W9ZZZ")
    nets.add_checkin(nets.start_session(net.id, "2026-11-17").id, "K1AAA")
    assert [p.callsign for p in book.view(net.id, NOW).participants] == ["W9ZZZ", "K1AAA"]


def test_listing_next_text(book: NetBook) -> None:
    book.save(form())
    book.save(form(name="Other net", weekday=None, start_time=""))
    texts = {s.net.name: s.next_text for s in book.listing(NOW)}
    assert texts == {"Test net": "Tue 3 Nov 2026, 20:00 EST", "Other net": "Not scheduled"}
    assert book.view(book.listing(NOW)[1].net.id or 0, NOW).next_text == (
        "Tue 3 Nov 2026, 20:00 EST"
    )


@pytest.fixture
def searchable(book: NetBook) -> dict[str, int]:
    nets = {
        "Pack Rats Monday": form(name="Pack Rats Monday", frequency="50.15", band="6 m",
                                 controller_call="N3RG", controller_grid=""),
        "DMR net": form(name="DMR net", frequency="", channel="TG 31425", band=None,
                        controller_call="", controller_grid=""),
        "UHF net": form(name="UHF net", frequency="432.11", band="70 cm",
                        controller_call="WB2RVX", controller_grid=""),
        "VHF net": form(name="VHF net", frequency="144.245", band="2 m",
                        controller_call="W2KV", controller_grid=""),
    }  # fmt: skip
    return {name: book.save(f).id or 0 for name, f in nets.items()}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (" PACK rats ", ["Pack Rats Monday"]),
        ("tg 31", ["DMR net"]),
        ("144.2", ["VHF net"]),
        ("70 cm", ["UHF net"]),
        ("w2kv", ["VHF net"]),
        ("zzz", []),
        ("", ["DMR net", "Pack Rats Monday", "UHF net", "VHF net"]),
    ],
)
def test_search_matches_fields(
    book: NetBook, searchable: dict[str, int], query: str, expected: list[str]
) -> None:
    assert [s.net.name for s in book.listing(NOW, query=query)] == expected


def test_search_full_microwave_frequency(book: NetBook) -> None:  # review I1
    book.save(form(name="23 cm net", frequency="1296.125", band="23 cm"))
    assert [s.net.name for s in book.listing(NOW, query="1296.125")] == ["23 cm net"]


def test_favourites_first_then_name(book: NetBook, searchable: dict[str, int]) -> None:
    book.set_favourite(searchable["UHF net"], True)
    assert [s.net.name for s in book.listing(NOW)] == [
        "UHF net", "DMR net", "Pack Rats Monday", "VHF net"
    ]  # fmt: skip
    assert [s.net.name for s in book.listing(NOW, favourites_only=True)] == ["UHF net"]
    book.set_favourite(searchable["UHF net"], False)
    assert book.listing(NOW, favourites_only=True) == []


def test_favourite_archived_hidden(book: NetBook, searchable: dict[str, int]) -> None:
    net_id = searchable["UHF net"]
    book.set_favourite(net_id, True)
    book.set_archived(net_id, True)
    assert book.listing(NOW, favourites_only=True) == []
    shown = book.listing(NOW, show_archived=True, favourites_only=True)
    assert [s.net.name for s in shown] == ["UHF net"]


def test_edit_keeps_favourite_duplicate_does_not(book: NetBook) -> None:
    net = book.save(form())
    assert net.id is not None
    book.set_favourite(net.id, True)
    assert book.save(form(mode="FM"), net.id).favourite
    assert not book.duplicate(net.id).favourite
