"""Desk backup and restore: a restore never moves the rotator (spec 4.8; AT 26, 35)."""

import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from beam_navigator.backup import BackupError
from beam_navigator.core.models import RotatorProfile
from beam_navigator.desk import Desk
from beam_navigator.rotators.base import Capabilities, CommandResult, ConnectionResult
from beam_navigator.rotators.service import RotateService
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import RotatorRepository


class FakeRotator:
    """Records every move it is sent; nothing here reaches a real rotator."""

    def __init__(self) -> None:
        self.moves: list[float] = []

    def connect(self) -> ConnectionResult:
        return ConnectionResult(True, "connected")

    def capabilities(self) -> Capabilities:
        return Capabilities(has_feedback=True, has_stop=True)

    def get_position(self) -> float | None:
        return 12.0

    def set_azimuth(self, deg: float) -> CommandResult:
        self.moves.append(deg)
        return CommandResult(True, "sent")

    def stop(self) -> CommandResult:
        self.moves.append(-1)
        return CommandResult(True, "stopped")

    def disconnect(self) -> None:
        pass


@pytest.fixture
def fake() -> FakeRotator:
    return FakeRotator()


def make_desk(path: Path | str, fake: FakeRotator) -> Desk:
    conn = open_db(path)
    return Desk(conn, RotateService(conn, adapter_for=lambda p: fake, tester_for=lambda p: fake))


@pytest.fixture
def desk(tmp_path: Path, fake: FakeRotator) -> Iterator[Desk]:
    made = make_desk(tmp_path / "beamnav.db", fake)
    yield made
    made.conn.close()


def test_backup_names_and_bytes(desk: Desk) -> None:
    name, data = desk.backup()
    assert name.startswith("beamnav-backup-") and name.endswith(".db")
    assert data.startswith(b"SQLite format 3\x00")


def test_data_dir(desk: Desk, tmp_path: Path, fake: FakeRotator) -> None:
    assert desk.data_dir() == tmp_path
    memory = make_desk(":memory:", fake)
    assert memory.data_dir() is None
    memory.conn.close()


def test_restore_sends_no_rotator_command_and_forgets(desk: Desk, fake: FakeRotator) -> None:
    profile = RotatorRepository(desk.conn).save(
        RotatorProfile(None, "Sim", "simulation", None, None, 0, 360, 0, None, (), False, False)
    )
    assert profile.id is not None
    desk.service.rotate(profile.id, "K2A", 90.0)
    assert desk.service.last_rotor(profile.id) is not None
    moves = list(fake.moves)
    _, data = desk.backup()
    kept = desk.restore_backup(data, datetime(2026, 10, 29, 15, 7))
    assert kept.parent.name == "backups" and kept.exists()
    assert fake.moves == moves
    assert desk.service.last_rotor(profile.id) is None


def test_restore_needs_a_file(fake: FakeRotator) -> None:
    memory = make_desk(":memory:", fake)
    _, data = memory.backup()
    with pytest.raises(BackupError, match="needs a database file"):
        memory.restore_backup(data)
    memory.conn.close()


def test_backup_has_no_password(desk: Desk) -> None:
    _, data = desk.backup()
    copy = sqlite3.connect(":memory:")
    copy.deserialize(data)
    keys = [row[0] for row in copy.execute("SELECT key FROM setting")]
    copy.close()
    assert not [key for key in keys if "password" in key.lower()]
    assert b"password" not in data.lower()
