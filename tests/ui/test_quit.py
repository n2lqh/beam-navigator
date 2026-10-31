"""Quit stops Beam Navigator from the browser: the .exe has no console window to close
(owner, 2026-10-31; decision 44)."""

import asyncio
from collections.abc import Iterator

import pytest
from nicegui import app
from nicegui.testing import User

from beam_navigator.desk import Desk
from beam_navigator.rotators.service import RotateService
from beam_navigator.rotators.simulation import SimulationAdapter
from beam_navigator.store.db import open_db
from beam_navigator.ui.app import register_pages


@pytest.fixture
def desk() -> Iterator[Desk]:
    conn = open_db(":memory:")
    sim = SimulationAdapter(az_max=360)
    yield Desk(conn, RotateService(conn, adapter_for=lambda p: sim, tester_for=lambda p: sim))
    conn.close()


@pytest.fixture
def stops(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []
    monkeypatch.setattr(app, "shutdown", lambda: calls.append(True))
    return calls


async def test_quit_asks_then_stops(user: User, desk: Desk, stops: list[bool]) -> None:
    register_pages(lambda: desk)
    await user.open("/settings")
    user.find(marker="quit").click()
    await user.should_see("Quit Beam Navigator?")
    assert stops == []
    user.find(marker="quit-confirm").click()
    await user.should_see("Beam Navigator has stopped. You can close this tab.")
    for _ in range(20):
        if stops:
            break
        await asyncio.sleep(0.1)
    assert stops == [True]


async def test_quit_cancel_keeps_running(user: User, desk: Desk, stops: list[bool]) -> None:
    register_pages(lambda: desk)
    await user.open("/settings")
    user.find(marker="quit").click()
    user.find(marker="quit-cancel").click()
    await user.should_not_see("Beam Navigator has stopped")
    assert stops == []
