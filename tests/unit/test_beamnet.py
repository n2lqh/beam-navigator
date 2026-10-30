"""*.beamnet.json: share net definitions, never overwrite, refuse bad files (spec 4.6)."""

import json
import re
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import date

import pytest

from beam_navigator.beamnet import (
    BeamnetError,
    beamnet_filename,
    import_beamnet,
    read_beamnet,
    write_beamnet,
)
from beam_navigator.desk import Desk
from beam_navigator.nets import NetBook, NetForm
from beam_navigator.rotators.service import RotateService
from beam_navigator.store.db import open_db


@pytest.fixture
def make_book() -> Iterator[Callable[[], NetBook]]:
    connections: list[sqlite3.Connection] = []

    def make() -> NetBook:
        conn = open_db(":memory:")
        connections.append(conn)
        return NetBook(conn, Desk(conn, RotateService(conn)))

    yield make
    for conn in connections:
        conn.close()


def form(**changes: object) -> NetForm:
    base = NetForm(
        name="Test net", weekday=1, start_time="20:00", timezone="America/New_York",
        frequency="144.2", channel="", mode="SSB", band="2 m", controller_call="K1ABC",
        controller_grid="FN20ok", rotator_id=None,
    )  # fmt: skip
    return replace(base, **changes)  # type: ignore[arg-type]


def file_with(*nets: dict[str, object], **top: object) -> bytes:
    return json.dumps({"format": "beamnet", "schema": 1, "nets": list(nets), **top}).encode()


def test_round_trip(make_book: Callable[[], NetBook]) -> None:
    source = make_book()
    first = source.save(form())
    second = source.save(
        form(name="Talkgroup net", frequency="", channel="TG 3100", band=None, weekday=None,
             start_time="", timezone="", controller_grid="")  # fmt: skip
    )
    data = write_beamnet([first, second])
    written = json.loads(data)
    assert written["format"] == "beamnet" and written["schema"] == 1
    assert written["nets"][0]["weekday"] == "tuesday"
    assert written["nets"][1]["weekday"] is None
    for key in ("id", "archived", "rotator_id"):
        assert key not in written["nets"][0]
    target = make_book()
    report = import_beamnet(target, data)
    assert report.added == ["Test net", "Talkgroup net"] and report.skipped == []
    imported = {n.name: n.id for n in target.pickable()}
    assert first.id is not None and second.id is not None
    assert target.form_for(imported["Test net"] or 0) == source.form_for(first.id)
    assert target.form_for(imported["Talkgroup net"] or 0) == source.form_for(second.id)


def test_preferred_rotator_not_exported(make_book: Callable[[], NetBook]) -> None:
    book = make_book()
    net = book.save(form())
    assert "rotator" not in write_beamnet([net]).decode()


def test_import_never_overwrites(make_book: Callable[[], NetBook]) -> None:
    book = make_book()
    existing = book.save(form())
    report = import_beamnet(book, file_with({"name": "TEST NET", "frequency_mhz": 432.1}))
    assert report.added == []
    assert report.skipped == ["TEST NET: a net with this name already exists; not changed"]
    assert existing.id is not None
    assert book.form_for(existing.id).frequency == "144.2"


def test_bad_net_skipped_others_added(make_book: Callable[[], NetBook]) -> None:
    book = make_book()
    report = import_beamnet(
        book,
        file_with({"name": "Bad grid", "default_controller_grid": "ZZ99"}, {"name": "Good net"}),
    )
    assert report.added == ["Good net"]
    assert len(report.skipped) == 1 and report.skipped[0].startswith("Bad grid:")
    assert "ZZ99" in report.skipped[0]


def test_same_name_twice_in_one_file(make_book: Callable[[], NetBook]) -> None:
    report = import_beamnet(make_book(), file_with({"name": "A net"}, {"name": "a NET"}))
    assert report.added == ["A net"]
    assert report.skipped == ["a NET: a net with this name already exists; not changed"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"\x00\xff" * 10, "not a beamnet file"),
        (b" " * 1_000_001, "larger than 1 MB"),
        (b"[]", "not a beamnet file"),
        (b'{"format": "other", "schema": 1, "nets": []}', "not a beamnet file"),
        (b'{"format": "beamnet", "schema": 2, "nets": []}', "newer Beam Navigator (schema 2)"),
        (b'{"format": "beamnet", "schema": "1", "nets": []}', "schema"),
        (b'{"format": "beamnet", "schema": true, "nets": []}', "schema"),
        (b'{"format": "beamnet", "schema": 1, "nets": {}}', "nets"),
        (b'{"format": "beamnet", "schema": 1}', "nets"),
        (b"", "not a beamnet file"),
    ],
)
def test_bad_files_refused(make_book: Callable[[], NetBook], data: bytes, message: str) -> None:
    book = make_book()
    with pytest.raises(BeamnetError, match=re.escape(message)):
        import_beamnet(book, data)
    assert book.pickable() == []


def test_unknown_keys_ignored(make_book: Callable[[], NetBook]) -> None:
    data = file_with({"name": "Test net", "color": "red"}, comment="from a later version")
    assert import_beamnet(make_book(), data).added == ["Test net"]


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        ({"name": "X", "frequency_mhz": "fast"}, "frequency_mhz must be a number"),
        ({"name": "X", "frequency_mhz": True}, "frequency_mhz must be a number"),
        ({"name": "X", "weekday": "funday", "start_time": "20:00"}, "unknown weekday 'funday'"),
        ({"name": "X", "mode": 5}, "mode must be text"),
        ({"name": 7}, "name must be text"),
        ("just text", "not a net entry"),
    ],
)
def test_wrong_field_type_skips_net(
    make_book: Callable[[], NetBook], entry: object, reason: str
) -> None:
    data = json.dumps({"format": "beamnet", "schema": 1, "nets": [entry]}).encode()
    entries = read_beamnet(data)
    assert len(entries) == 1 and entries[0][1] == reason
    report = import_beamnet(make_book(), data)
    assert report.added == [] and len(report.skipped) == 1 and reason in report.skipped[0]


def test_filenames(make_book: Callable[[], NetBook]) -> None:
    book = make_book()
    one = book.save(form(name="W2KV 2 m"))
    two = book.save(form(name="Other"))
    today = date(2026, 10, 28)
    assert beamnet_filename([one], today) == "w2kv-2-m.beamnet.json"
    assert beamnet_filename([one, two], today) == "nets-2026-10-28.beamnet.json"
    assert beamnet_filename([book.save(form(name="!!!"))], today) == "net.beamnet.json"


def test_deeply_nested_file_refused(make_book: Callable[[], NetBook]) -> None:  # review I1
    book = make_book()
    nested = b'{"format": "beamnet", "schema": 1, "nets": ' + b"[" * 200_000 + b"]" * 200_000
    assert len(nested) < 1_000_000
    with pytest.raises(BeamnetError, match="not a beamnet file"):
        import_beamnet(book, nested + b"}")
    assert book.pickable() == []


def test_favourite_not_exported(make_book: Callable[[], NetBook]) -> None:
    book = make_book()
    net = book.save(form())
    assert net.id is not None
    book.set_favourite(net.id, True)
    [starred] = book.pickable()
    assert starred.favourite
    assert "favourite" not in write_beamnet([starred]).decode()
