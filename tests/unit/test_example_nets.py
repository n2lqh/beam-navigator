"""Example nets: only what the owner's schedule states, opt-in, unverified (spec 4.6;
decision 27)."""

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import pytest

from beam_navigator.beamnet import read_beamnet, write_beamnet
from beam_navigator.core.models import Net, Station
from beam_navigator.core.roster_parser import parse_roster
from beam_navigator.desk import Desk
from beam_navigator.nets import (
    EXAMPLE_NETS,
    EXAMPLE_ROSTERS,
    EXAMPLE_SETTING,
    NetBook,
    NetForm,
    example_rosters,
)
from beam_navigator.rotators.service import RotateService
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository

SOURCE = (Path(__file__).parents[2] / "docs" / "example-nets-source.txt").read_text(
    encoding="utf-8"
)


@pytest.fixture
def book() -> Iterator[NetBook]:
    conn: sqlite3.Connection = open_db(":memory:")
    yield NetBook(conn, Desk(conn, RotateService(conn)))
    conn.close()


def examples() -> list[dict[str, object]]:
    document = json.loads(EXAMPLE_NETS.read_bytes())
    nets: list[dict[str, object]] = document["nets"]
    return nets


def test_examples_match_source() -> None:
    nets = examples()
    assert len(nets) == 14
    lines = SOURCE.splitlines()
    for net in nets:
        assert net["unverified"] is True
        frequency = net["frequency_mhz"]
        if frequency is not None:
            assert isinstance(frequency, float)
            assert f"{frequency:.3f}" in SOURCE, net["name"]
        call, grid = net["default_controller_call"], net["default_controller_grid"]
        if call is not None:
            assert any(str(call) in line and (grid is None or str(grid) in line)
                       for line in lines), net["name"]  # a null grid: none given
        if net["timezone"] is not None:
            assert str(net["name"]).startswith("K1WHS") and "Eastern Time" in SOURCE
    assert [n["name"] for n in nets if n["timezone"] is not None] == [
        "K1WHS 222 MHz Tuesday Activity Night"
    ]


def test_examples_match_plan_table() -> None:
    by_name = {str(n["name"]): n for n in examples()}
    monday = by_name["Pack Rats Monday 144 MHz"]
    assert (monday["weekday"], monday["start_time"], monday["frequency_mhz"], monday["band"]) == (
        "monday", "20:00", 144.245, "2 m"
    )  # fmt: skip
    assert (monday["default_controller_call"], monday["default_controller_grid"]) == (
        "W2KV", "FN20ok"
    )  # fmt: skip
    high = by_name["DVFRC Friday 2304 MHz"]
    assert (high["weekday"], high["start_time"], high["band"]) == ("friday", "21:15", None)
    assert high["default_controller_call"] is None
    assert by_name["K1WHS 222 MHz Tuesday Activity Night"]["frequency_mhz"] is None
    assert {str(n["name"]): n["mode"] for n in examples() if n["mode"] is not None} == {
        "Packrat DMR Net": "DMR"
    }  # the owner named DMR for that net (2026-10-29); the schedule names no other mode


def test_add_examples_once(book: NetBook) -> None:
    assert book.example_offer()
    report = book.add_examples()
    assert len(report.added) == 14 and report.skipped == []
    assert not book.example_offer()
    assert book.desk.settings.get(EXAMPLE_SETTING) == "added"
    again = book.add_examples()
    assert again.added == [] and len(again.skipped) == 14
    assert all(net.unverified for net in book.pickable())


def test_decline_examples(book: NetBook) -> None:
    book.decline_examples()
    assert not book.example_offer()
    assert book.desk.settings.get(EXAMPLE_SETTING) == "declined"
    assert book.pickable() == []


def test_checked_clears_unverified(book: NetBook) -> None:
    book.add_examples()
    [net] = [n for n in book.pickable() if n.name == "Pack Rats Monday 50 MHz"]
    assert net.id is not None
    form = book.form_for(net.id)
    assert form.unverified
    assert book.save(form, net.id).unverified  # saved unchanged: still unverified
    assert not book.save(replace(form, unverified=False), net.id).unverified


def test_new_net_is_verified(book: NetBook) -> None:
    form = NetForm(
        name="Test net", weekday=None, start_time="", timezone="", frequency="", channel="",
        mode="", band=None, controller_call="", controller_grid="", rotator_id=None,
    )  # fmt: skip
    assert not book.save(form).unverified


def test_export_keeps_unverified_flag(book: NetBook) -> None:
    book.add_examples()
    [example] = [n for n in book.pickable() if n.name == "Pack Rats Monday 50 MHz"]
    assert example.id is not None
    checked = book.save(replace(book.form_for(example.id), name="Checked net",
                                unverified=False))  # fmt: skip
    written = json.loads(write_beamnet([example, checked]))["nets"]
    assert written[0]["unverified"] is True
    assert "unverified" not in written[1]
    forms = [form for _, form in read_beamnet(write_beamnet([example, checked]))]
    assert [f.unverified for f in forms if isinstance(f, NetForm)] == [True, False]


def test_dmr_example_net() -> None:  # the owner's message, 2026-10-29
    [dmr] = [n for n in examples() if n["name"] == "Packrat DMR Net"]
    assert dmr == {
        "name": "Packrat DMR Net", "weekday": "monday", "start_time": "19:00", "timezone": None,
        "frequency_mhz": None, "channel": "Talkgroup 8804", "mode": "DMR", "band": None,
        "default_controller_call": "KA3WXV", "default_controller_grid": None, "unverified": True,
    }  # fmt: skip
    assert "Packrat DMR Net Monday night 7pm New control george KA3WXV Talkgroup 8803" in SOURCE
    assert "sorry 8804" in SOURCE


def test_mud_toads_controller() -> None:  # the owner's message, 2026-10-29
    [toads] = [n for n in examples() if "Mud Toads" in str(n["name"])]
    assert toads["name"] == "Chesapeake Bay Mud Toads Net"
    assert (toads["default_controller_call"], toads["default_controller_grid"]) == ("KD8UD", None)
    assert "kd8UD is the net controller" in SOURCE


def test_example_rosters_are_the_owner_fixtures() -> None:
    fixtures = Path(__file__).parents[1] / "fixtures"
    rosters = example_rosters()
    assert len(rosters) == 6
    packaged = files("beam_navigator") / "data" / "example_rosters"
    for entry in json.loads(EXAMPLE_ROSTERS.read_text(encoding="utf-8"))["rosters"]:
        assert (packaged / entry["file"]).read_bytes() == (fixtures / entry["file"]).read_bytes()


def test_example_rosters_name_example_nets() -> None:
    names = {n["name"] for n in examples()}
    assert all(r.net in names for r in example_rosters())
    assert [r.date for r in example_rosters()][0] == "2026-10-26"


def test_add_examples_imports_rosters(book: NetBook) -> None:  # decision 32
    book.add_examples()
    nets = {n.name: n for n in book.pickable()}
    for roster in example_rosters():
        net_id = nets[roster.net].id
        assert net_id is not None
        [(session, count)] = NetRepository(book.desk.conn).sessions(net_id)
        assert (session.date, session.status, session.raw_text) == (
            roster.date, "imported", roster.text
        )  # fmt: skip
        assert count == len([r for r in parse_roster(roster.text).rows if r.callsign])
    calls = book.example_callsigns()
    assert len(calls) == len(set(calls)) > 0
    for call in calls:
        record = book.desk.stations.get(call)
        assert record is not None and record.source == "roster", call


def test_examples_never_overwrite_a_saved_station(book: NetBook) -> None:
    book.desk.stations.save(Station("K1DY", "MINE", "FN20aa", None, None, "saved", ""))
    book.add_examples()
    kept = book.desk.stations.get("K1DY")
    assert kept is not None and (kept.name, kept.grid, kept.source) == ("MINE", "FN20aa", "saved")
    assert "K1DY" in book.example_callsigns()  # it is in N3RG's roster


def test_rosters_skip_a_net_the_operator_owns(book: NetBook) -> None:
    mine = NetRepository(book.desk.conn).save_net(Net(
        None, "Pack Rats Monday 50 MHz", None, None, None, 50.125, None, None, "6 m", None, None,
        False,
    ))  # fmt: skip
    book.add_examples()
    assert mine.id is not None
    assert NetRepository(book.desk.conn).sessions(mine.id) == []


def test_second_add_examples_adds_no_sessions(book: NetBook) -> None:
    book.add_examples()
    count = "SELECT COUNT(*) FROM session"
    before = book.desk.conn.execute(count).fetchone()[0]
    book.add_examples()
    assert book.desk.conn.execute(count).fetchone()[0] == before == 6
