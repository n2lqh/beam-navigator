"""The nets page and each net's history page, through NiceGUI's simulated user (spec 4.6).
Simulator only; none of these pages may send a rotator command."""

import asyncio
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from nicegui import ui
from nicegui.testing import User

from beam_navigator.core.models import OperatorProfile
from beam_navigator.core.roster_parser import parse_roster
from beam_navigator.desk import Desk
from beam_navigator.nets import NetBook, NetForm
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import NetRepository, ProfileRepository
from beam_navigator.ui.app import register_pages

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def sim() -> SimulationAdapter:
    return SimulationAdapter(az_max=360)


@pytest.fixture
def desk(conn: sqlite3.Connection, sim: SimulationAdapter) -> Desk:
    profiles = ProfileRepository(conn)
    saved = profiles.save(
        OperatorProfile(None, "Home", None, "FM29pt", None, "mi", "America/New_York", "NJ",
                        False)  # fmt: skip
    )
    assert saved.id is not None
    profiles.activate(saved.id)
    return Desk(conn, RotateService(conn, adapter_for=lambda p: sim, tester_for=lambda p: sim))


@pytest.fixture
def book(conn: sqlite3.Connection, desk: Desk) -> NetBook:
    return NetBook(conn, desk)


def form(**changes: object) -> NetForm:
    base = NetForm(
        name="Test net", weekday=1, start_time="20:00", timezone="", frequency="144.2",
        channel="", mode="", band="2 m", controller_call="", controller_grid="",
        rotator_id=None,
    )  # fmt: skip
    return replace(base, **changes)  # type: ignore[arg-type]


def element(user: User, marker: str) -> Any:
    [found] = user.find(marker=marker).elements
    return found


async def open_nets(user: User, desk: Desk) -> None:
    register_pages(lambda: desk)
    await user.open("/nets")


async def test_new_net_from_form(user: User, desk: Desk, conn: sqlite3.Connection) -> None:
    await open_nets(user, desk)
    user.find(marker="new-net").click()
    element(user, "form-name").set_value("Test net")
    element(user, "form-weekday").set_value(1)
    element(user, "form-start").set_value("20:00")
    element(user, "form-zone").set_value("America/New_York")
    element(user, "form-frequency").set_value("144.2")
    user.find(marker="form-save").click()
    await user.should_see("Test net")
    [net] = NetRepository(conn).list_nets()
    assert (net.weekday, net.start_time, net.frequency_mhz) == (1, "20:00", 144.2)
    await user.should_see("20:00 E")  # EST or EDT, depending on today's date
    await user.should_see("Tue ")


async def test_form_error_shown(user: User, desk: Desk, conn: sqlite3.Connection) -> None:
    await open_nets(user, desk)
    user.find(marker="new-net").click()
    element(user, "form-name").set_value("Test net")
    element(user, "form-zone").set_value("America/NewYork")
    user.find(marker="form-save").click()
    await user.should_see("Unknown time zone")
    assert NetRepository(conn).list_nets() == []


async def test_edit_fills_form(user: User, desk: Desk, book: NetBook) -> None:
    net = book.save(form(mode="SSB"))
    await open_nets(user, desk)
    user.find(marker=f"edit-{net.id}").click()
    assert element(user, "form-name").value == "Test net"
    element(user, "form-mode").set_value("FM")
    user.find(marker="form-save").click()
    await user.should_see("Saved Test net")
    assert net.id is not None and book.form_for(net.id).mode == "FM"


async def test_duplicate_and_archive(user: User, desk: Desk, book: NetBook) -> None:
    net = book.save(form())
    await open_nets(user, desk)
    user.find(marker=f"duplicate-{net.id}").click()
    await user.should_see("Test net (copy)")
    [copy] = [n for n in book.pickable() if n.name == "Test net (copy)"]
    await user.should_see(marker=f"net-card-{copy.id}")  # the list refreshes async
    user.find(marker=f"archive-{copy.id}").click()
    await user.should_not_see(marker=f"net-card-{copy.id}")
    element(user, "show-archived").set_value(True)
    await user.should_see(marker=f"net-card-{copy.id}")
    await user.should_see("Unarchive")


async def test_import_file_reports(user: User, desk: Desk, book: NetBook) -> None:
    book.save(form())
    await open_nets(user, desk)
    data = json.dumps({"format": "beamnet", "schema": 1,
                       "nets": [{"name": "New net"}, {"name": "test net"}]}).encode()  # fmt: skip
    upload = element(user, "import-nets")
    assert isinstance(upload, ui.upload)
    await upload.handle_uploads(
        [ui.upload.SmallFileUpload("x.beamnet.json", "application/json", data)]
    )
    await user.should_see("Added: New net")
    await user.should_see("already exists")
    assert sorted(n.name for n in book.pickable()) == ["New net", "Test net"]


async def test_bad_import_file_reports(user: User, desk: Desk, book: NetBook) -> None:
    await open_nets(user, desk)
    upload = element(user, "import-nets")
    await upload.handle_uploads(
        [ui.upload.SmallFileUpload("x.beamnet.json", "application/json", b"\x00garbage")]
    )
    await user.should_see("This is not a beamnet file")
    assert book.pickable() == []


async def test_export_one_downloads(user: User, desk: Desk, book: NetBook) -> None:
    net = book.save(form())
    await open_nets(user, desk)
    user.find(marker=f"export-{net.id}").click()
    response = await user.download.next()
    assert '"format": "beamnet"' in response.text and "Test net" in response.text


async def test_export_all_skips_archived(user: User, desk: Desk, book: NetBook) -> None:
    book.save(form())
    archived = book.save(form(name="Old net"))
    assert archived.id is not None
    book.set_archived(archived.id, True)
    await open_nets(user, desk)
    user.find(marker="export-all").click()
    response = await user.download.next()
    assert "Test net" in response.text and "Old net" not in response.text


async def test_import_page_hides_archived(user: User, desk: Desk, book: NetBook) -> None:
    book.save(form())
    archived = book.save(form(name="Old net"))
    assert archived.id is not None
    book.set_archived(archived.id, True)
    register_pages(lambda: desk)
    await user.open("/import")
    picker = element(user, "net")
    assert isinstance(picker, ui.select)
    assert list(picker.options.values()) == ["Test net"]  # type: ignore[union-attr]


def import_w2kv(conn: sqlite3.Connection, net_id: int) -> int:
    text = (FIXTURES / "w2kv_144mhz_2026-10-26.txt").read_text(encoding="utf-8")
    return NetRepository(conn).import_roster(net_id, "2026-10-26", text, parse_roster(text)).id


async def test_net_page_shows_history(
    user: User, desk: Desk, book: NetBook, conn: sqlite3.Connection
) -> None:
    net = book.save(form(controller_call="W2KV", controller_grid="FN20ok"))
    assert net.id is not None
    session_id = import_w2kv(conn, net.id)
    register_pages(lambda: desk)
    await user.open(f"/nets/{net.id}")
    await user.should_see("W2KV · FN20ok")
    await user.should_see("2026-10-26")
    await user.should_see("17 check-ins")
    await user.should_see("Participants (17)")
    assert element(user, "grid-K3WGR").text == "FN10xi"
    await user.should_see(marker=f"open-{session_id}")
    await user.should_see(marker=f"control-{session_id}")


async def test_unknown_grid_shown_as_dash(
    user: User, desk: Desk, book: NetBook, conn: sqlite3.Connection
) -> None:
    net = book.save(form())
    assert net.id is not None
    nets = NetRepository(conn)
    nets.add_checkin(nets.start_session(net.id, "2026-11-03").id, "K9ZZZ")
    register_pages(lambda: desk)
    await user.open(f"/nets/{net.id}")
    await user.should_see("Participants (1)")
    assert element(user, "grid-K9ZZZ").text == "—"  # unknown, never guessed


async def test_archived_net_page_opens(
    user: User, desk: Desk, book: NetBook, conn: sqlite3.Connection
) -> None:
    net = book.save(form())
    assert net.id is not None
    import_w2kv(conn, net.id)
    book.set_archived(net.id, True)
    register_pages(lambda: desk)
    await user.open(f"/nets/{net.id}")
    await user.should_see("Archived")
    await user.should_see("2026-10-26")


async def test_unknown_net_page(user: User, desk: Desk) -> None:
    register_pages(lambda: desk)
    await user.open("/nets/999")
    await user.should_see("No net with id 999.")


async def test_no_rotator_command_from_nets_pages(
    user: User, desk: Desk, book: NetBook, sim: SimulationAdapter
) -> None:  # invariant 2
    net = book.save(form())
    await open_nets(user, desk)
    user.find(marker=f"duplicate-{net.id}").click()
    user.find(marker=f"export-{net.id}").click()
    await user.download.next()
    user.find(marker=f"archive-{net.id}").click()
    await user.open(f"/nets/{net.id}")
    user.find(marker="edit-net").click()
    element(user, "form-mode").set_value("FM")
    user.find(marker="form-save").click()
    await user.should_see("Saved Test net")
    assert sim.commands == []


async def test_example_banner_add(user: User, desk: Desk, book: NetBook) -> None:  # 4.6
    await open_nets(user, desk)
    await user.should_see("Add example nets?")
    user.find(marker="add-examples").click()
    await user.should_see("Example — unverified")
    assert len(book.pickable()) == 14
    await user.open("/nets")
    await user.should_not_see("Add example nets?")


async def test_example_banner_decline(user: User, desk: Desk, book: NetBook) -> None:
    await open_nets(user, desk)
    user.find(marker="decline-examples").click()
    await user.should_not_see("Add example nets?")
    await user.open("/nets")
    await user.should_not_see("Add example nets?")
    assert book.pickable() == []


async def test_checked_box_clears_unverified(user: User, desk: Desk, book: NetBook) -> None:
    book.add_examples()
    [net] = [n for n in book.pickable() if n.name == "Pack Rats Monday 50 MHz"]
    await open_nets(user, desk)
    user.find(marker=f"edit-{net.id}").click()
    element(user, "form-checked").set_value(True)
    user.find(marker="form-save").click()
    await user.should_see("Saved Pack Rats Monday 50 MHz")
    assert net.id is not None and not book.form_for(net.id).unverified


async def test_checked_box_hidden_for_verified_net(user: User, desk: Desk, book: NetBook) -> None:
    net = book.save(form())
    await open_nets(user, desk)
    user.find(marker=f"edit-{net.id}").click()
    await user.should_see(marker="form-name")
    await user.should_not_see(marker="form-checked")  # hidden for a net that is not an example


def card_order(user: User) -> list[str]:
    """Cards in page order: find() returns a set, but elements are numbered as they render."""
    cards = sorted(user.find(marker="net-card").elements, key=lambda e: e.id)
    return [m for card in cards for m in card._markers if m.startswith("net-card-")]


async def test_search_filters_cards(user: User, desk: Desk, book: NetBook) -> None:
    first = book.save(form())
    other = book.save(form(name="Other net"))
    await open_nets(user, desk)
    element(user, "net-search").set_value("other")
    await user.should_not_see(marker=f"net-card-{first.id}")
    await user.should_see(marker=f"net-card-{other.id}")
    element(user, "net-search").set_value("zzz")
    await user.should_see('No nets match "zzz".')


async def test_star_sorts_first(user: User, desk: Desk, book: NetBook) -> None:
    first = book.save(form(name="A net"))
    second = book.save(form(name="B net"))
    await open_nets(user, desk)
    assert card_order(user) == [f"net-card-{first.id}", f"net-card-{second.id}"]
    user.find(marker=f"favourite-{second.id}").click()
    await user.should_see(marker=f"favourite-{second.id}")
    for _ in range(100):
        if card_order(user)[0] == f"net-card-{second.id}":
            break
        await asyncio.sleep(0.01)
    assert card_order(user) == [f"net-card-{second.id}", f"net-card-{first.id}"]
    assert element(user, f"favourite-{second.id}").props.get("icon") == "star"
    assert second.id is not None and book.nets.get_net(second.id).favourite


async def test_favourites_only_switch(user: User, desk: Desk, book: NetBook) -> None:
    plain = book.save(form(name="A net"))
    starred = book.save(form(name="B net"))
    assert starred.id is not None
    book.set_favourite(starred.id, True)
    await open_nets(user, desk)
    element(user, "favourites-only").set_value(True)
    await user.should_not_see(marker=f"net-card-{plain.id}")
    await user.should_see(marker=f"net-card-{starred.id}")


async def test_star_keeps_search(user: User, desk: Desk, book: NetBook) -> None:
    hidden = book.save(form(name="A net"))
    shown = book.save(form(name="Other net"))
    await open_nets(user, desk)
    element(user, "net-search").set_value("other")
    await user.should_not_see(marker=f"net-card-{hidden.id}")
    user.find(marker=f"favourite-{shown.id}").click()
    await user.should_see(marker=f"net-card-{shown.id}")
    assert element(user, "net-search").value == "other"
    await user.should_not_see(marker=f"net-card-{hidden.id}")


async def test_no_rotator_command_from_star_or_search(
    user: User, desk: Desk, book: NetBook, sim: SimulationAdapter
) -> None:  # invariant 2
    net = book.save(form())
    await open_nets(user, desk)
    element(user, "net-search").set_value("test")
    user.find(marker=f"favourite-{net.id}").click()
    element(user, "favourites-only").set_value(True)
    await user.should_see(marker=f"net-card-{net.id}")
    assert sim.commands == []


class FakeQrz:
    """Replays QRZ spec examples (or errors) and counts the calls."""

    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, url: str, fields: dict[str, str]) -> bytes:
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return bytes(reply)


def examples_missing_from_qrz() -> int:
    """How many example stations QRZ would be asked about, from a scratch database."""
    scratch = open_db(":memory:")
    desk = Desk(scratch, RotateService(scratch))
    book = NetBook(scratch, desk)
    book.add_examples()
    missing = len(desk.qrz_missing(book.example_callsigns()))
    scratch.close()
    return missing


async def test_examples_then_qrz_fills_missing(
    user: User, desk: Desk, book: NetBook, qrz_examples: list[bytes]
) -> None:  # decision 32
    from beam_navigator.qrz_client import QrzClient
    from beam_navigator.qrz_login import save_login

    missing = examples_missing_from_qrz()
    assert missing >= 2  # the "not found, carry on" path runs
    replies = [qrz_examples[0]] + [qrz_examples[3]] * (missing - 1) + [qrz_examples[1]]
    transport = FakeQrz(replies)
    save_login("xx1xxx", "pw")
    register_pages(lambda: desk, QrzClient(transport=transport))
    await user.open("/nets")
    user.find(marker="add-examples").click()
    await user.should_see("QRZ filled in details for 1 example stations.")
    assert transport.calls == 1 + missing


async def test_examples_qrz_quiet_without_login(user: User, desk: Desk, book: NetBook) -> None:
    from beam_navigator.qrz_client import QrzClient

    transport = FakeQrz([])
    register_pages(lambda: desk, QrzClient(transport=transport))
    await user.open("/nets")
    user.find(marker="add-examples").click()
    await user.should_see("Example — unverified")
    await asyncio.sleep(0.2)
    await user.should_not_see("Set up your QRZ login")
    assert transport.calls == 0


async def test_examples_qrz_stops_once_offline(user: User, desk: Desk, book: NetBook) -> None:
    from urllib.error import URLError

    from beam_navigator.qrz_client import QrzClient
    from beam_navigator.qrz_login import save_login

    transport = FakeQrz([URLError("offline")])
    save_login("xx1xxx", "pw")
    register_pages(lambda: desk, QrzClient(transport=transport))
    await user.open("/nets")
    user.find(marker="add-examples").click()
    await user.should_see("QRZ can't be reached. Everything else works offline.")
    assert transport.calls == 1
