"""The first-run Welcome wizard through NiceGUI's simulated user (decision 35). Nothing
here sends a rotator command or contacts QRZ."""

import sqlite3
from collections.abc import Callable, Iterator

import pytest
from nicegui import ui
from nicegui.testing import User

from beam_navigator.core.models import OperatorProfile
from beam_navigator.desk import Desk
from beam_navigator.nets import NetBook
from beam_navigator.rotators.service import RotateService
from beam_navigator.store.db import open_db
from beam_navigator.ui.app import register_pages


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def desk(conn: sqlite3.Connection) -> Desk:
    return Desk(conn, RotateService(conn))


@pytest.fixture
def book(desk: Desk) -> NetBook:
    return NetBook(desk.conn, desk)


def element(user: User, marker: str) -> ui.element:
    [found] = user.find(marker=marker).elements
    return found


async def eventually(condition: Callable[[], bool]) -> None:
    import asyncio

    for _ in range(100):
        if condition():
            return
        await asyncio.sleep(0.02)
    assert condition()


def step(user: User) -> str:
    stepper = element(user, "welcome-stepper")
    assert isinstance(stepper, ui.stepper)
    return str(stepper.props["model-value"])


def saved(desk: Desk, name: str, grid: str, active: bool = False) -> OperatorProfile:
    profile = desk.profiles.save(
        OperatorProfile(None, name, None, grid, None, "km", "UTC", None, False)
    )
    assert profile.id is not None
    if active:
        desk.profiles.activate(profile.id)
    return profile


async def open_app(user: User, desk: Desk, path: str = "/") -> None:
    register_pages(lambda: desk)
    await user.open(path)


async def fill_station(user: User, grid: str, callsign: str = "") -> None:
    user.find(marker="welcome-callsign").clear().type(callsign)
    user.find(marker="welcome-grid").clear().type(grid)
    user.find(marker="welcome-next-1").click()


async def test_new_install_opens_welcome(user: User, desk: Desk) -> None:
    await open_app(user, desk)
    await user.should_see("Welcome to Beam Navigator")
    assert step(user) == "Your station"


async def test_active_profile_opens_dashboard(user: User, desk: Desk) -> None:
    saved(desk, "Home", "FN20", active=True)
    await open_app(user, desk)
    await user.should_not_see(marker="welcome-stepper")


async def test_inactive_profiles_offer_a_choice(user: User, desk: Desk) -> None:
    profile = saved(desk, "Portable", "FN20")
    await open_app(user, desk)
    await user.should_see("Use a saved station")
    await user.should_see("Portable")
    user.find(marker=f"welcome-use-{profile.id}").click()
    await eventually(lambda: step(user) == "Example nets")
    active = desk.profiles.get_active()
    assert active is not None and active.id == profile.id


async def test_station_step_creates_and_activates(user: User, desk: Desk) -> None:
    await open_app(user, desk)
    await fill_station(user, "FN20", "K2ABC")
    await eventually(lambda: step(user) == "Example nets")
    await user.should_see("Add example nets?")
    active = desk.profiles.get_active()
    assert active is not None and active.home_grid == "FN20" and active.callsign == "K2ABC"


async def test_bad_grid_reported_and_remembered(user: User, desk: Desk) -> None:
    await open_app(user, desk)
    await fill_station(user, "ZZ99")
    await eventually(lambda: bool(element(user, "welcome-error").text))  # type: ignore[attr-defined]
    assert step(user) == "Your station"
    assert desk.profiles.list() == []
    await user.open("/welcome")
    grid = element(user, "welcome-grid")
    assert isinstance(grid, ui.input) and grid.value == "ZZ99"


async def test_skip_for_now_then_back(user: User, desk: Desk) -> None:
    await open_app(user, desk)
    user.find(marker="welcome-skip").click()
    await user.should_see(marker="target")  # the dashboard, this visit only
    await user.should_not_see(marker="welcome-stepper")
    await user.open("/")
    await user.should_see(marker="welcome-stepper")


async def test_examples_add(user: User, desk: Desk, book: NetBook) -> None:
    await open_app(user, desk)
    await fill_station(user, "FN20")
    await eventually(lambda: step(user) == "Example nets")
    user.find(marker="welcome-examples-add").click()
    await user.should_see("Added 14 example nets.")
    await eventually(lambda: step(user) == "Next steps")
    assert not book.example_offer()


async def test_examples_no(user: User, desk: Desk, book: NetBook) -> None:
    await open_app(user, desk)
    await fill_station(user, "FN20")
    await eventually(lambda: step(user) == "Example nets")
    user.find(marker="welcome-examples-no").click()
    await eventually(lambda: step(user) == "Next steps")
    assert not book.example_offer()
    assert book.nets.list_nets() == []


async def test_examples_already_answered(user: User, desk: Desk, book: NetBook) -> None:
    book.decline_examples()
    await open_app(user, desk)
    await fill_station(user, "FN20")
    await eventually(lambda: step(user) == "Example nets")
    await user.should_see("Example nets: already set.")
    user.find(marker="welcome-next-2").click()
    await eventually(lambda: step(user) == "Next steps")


async def test_finish_goes_to_dashboard(user: User, desk: Desk) -> None:
    await open_app(user, desk)
    await fill_station(user, "FN20")
    await eventually(lambda: step(user) == "Example nets")
    user.find(marker="welcome-examples-no").click()
    await eventually(lambda: step(user) == "Next steps")
    user.find(marker="welcome-finish").click()
    await user.should_not_see(marker="welcome-stepper")
    assert not desk.needs_welcome()


async def test_settings_tab_query(user: User, desk: Desk) -> None:
    await open_app(user, desk, "/settings?tab=Rotators")
    [panels] = user.find(kind=ui.tab_panels).elements
    assert panels.props["model-value"] == "Rotators"


async def test_prefill_says_which_station_and_offers_new(user: User, desk: Desk) -> None:
    # Final review I3: the pre-filled form edits a saved station; it must say so.
    saved(desk, "Portable", "FN20")
    await open_app(user, desk)
    await user.should_see("Editing Portable")
    user.find(marker="welcome-new-station").click()
    grid = element(user, "welcome-grid")
    await eventually(lambda: isinstance(grid, ui.input) and grid.value == "")
    await fill_station(user, "FN31", "K2NEW")
    await eventually(lambda: step(user) == "Example nets")
    assert sorted(p.home_grid for p in desk.profiles.list()) == ["FN20", "FN31"]
