"""The shared data folder through NiceGUI's simulated user (owner, 2026-11-21): one PC at
a time, Take over from the second, and Settings → Data to choose the folder."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from beam_navigator.core.models import OperatorProfile
from beam_navigator.data_folder import POINTER_FILE, Holder, acquire, held_by, take_over
from beam_navigator.desk import Desk
from beam_navigator.rotators.service import RotateService
from beam_navigator.store.db import open_db
from beam_navigator.ui.app import DataLock, register_pages

SINCE = "2026-11-21T19:42:00-05:00"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection


@pytest.fixture
def desk(conn: sqlite3.Connection) -> Desk:
    saved = Desk(conn, RotateService(conn))
    profile = saved.profiles.save(
        OperatorProfile(None, "Home", None, "FM29pt", None, "mi", "", "NJ", False)
    )
    assert profile.id is not None
    saved.profiles.activate(profile.id)
    return saved


def lock_for(folder: Path, desk: Desk) -> DataLock:
    return DataLock(folder, "OFFICE", 20, SINCE, lambda: desk, alive=lambda pid: False)


async def test_second_pc_is_shown_who_has_it_and_can_take_over(
    user: User, desk: Desk, tmp_path: Path
) -> None:
    acquire(tmp_path, "SHACK", 10, SINCE, lambda pid: False)
    lock = lock_for(tmp_path, desk)
    lock.start()
    assert lock.desk is None  # nothing opened while another PC has it
    register_pages(lock.current, data_lock=lock)
    await user.open("/nets")
    await user.should_see("open on SHACK")
    await user.should_see("Take over")
    user.find(marker="take-over").click()
    await user.should_see("Nets")
    assert held_by(tmp_path) == Holder("OFFICE", 20, SINCE)


async def test_taken_over_elsewhere_stops_this_pc(
    user: User, desk: Desk, tmp_path: Path
) -> None:
    lock = lock_for(tmp_path, desk)
    lock.start()
    assert lock.desk is desk
    take_over(tmp_path, "SHACK", 10, SINCE)  # the other PC took it
    lock.check()
    assert lock.desk is None  # this PC stops writing
    register_pages(lock.current, data_lock=lock)
    await user.open("/")
    await user.should_see("open on SHACK")


async def test_settings_moves_the_data_to_a_shared_folder(
    user: User, desk: Desk, tmp_path: Path
) -> None:
    home, shared = tmp_path / "home", tmp_path / "shared"
    home.mkdir()
    register_pages(lambda: desk, home=home)
    await user.open("/settings?tab=Data")
    [box] = user.find(marker="data-folder").elements
    assert isinstance(box, ui.input)
    box.set_value(str(shared))
    user.find(marker="data-folder-use").click()
    await user.should_see("Quit and start Beam Navigator again")
    assert (shared / "beamnav.db").exists()
    assert (home / POINTER_FILE).read_text(encoding="utf-8").strip() == str(shared)
    user.find(marker="data-folder-home").click()
    await user.should_see("this PC's own folder")
    assert not (home / POINTER_FILE).exists()
