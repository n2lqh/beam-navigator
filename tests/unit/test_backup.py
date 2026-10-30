"""Backup and restore of the whole database (spec 4.8; decision 34)."""

import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from beam_navigator.backup import (
    BackupError,
    backup_bytes,
    backup_filename,
    checked_backup,
    restore,
)
from beam_navigator.core.models import RotatorProfile, Station
from beam_navigator.store.db import SCHEMA_VERSION, migrate, open_db, packaged_migrations
from beam_navigator.store.repositories import RotatorRepository, StationRepository

NOW = datetime(2026, 10, 29, 15, 7)


def station(callsign: str) -> Station:
    return Station(callsign, None, "FM29pt", None, None, "saved", "")


def callsigns(conn: sqlite3.Connection) -> list[str]:
    return sorted(row[0] for row in conn.execute("SELECT callsign FROM station"))


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db = open_db(tmp_path / "beamnav.db")
    StationRepository(db).save(station("K2A"))
    yield db
    db.close()


def test_backup_round_trip(conn: sqlite3.Connection) -> None:
    checked = checked_backup(backup_bytes(conn))
    assert callsigns(checked) == ["K2A"]
    checked.close()


def test_backup_filename() -> None:
    assert backup_filename(NOW) == "beamnav-backup-2026-10-29-1507.db"


def _empty_sqlite() -> bytes:
    empty = sqlite3.connect(":memory:")
    empty.execute("CREATE TABLE x (y)")
    data = empty.serialize()
    empty.close()
    return data


@pytest.mark.parametrize(
    "data", [b"", b"\x00garbage", b"x" * 1_000_000, _empty_sqlite()],
    ids=["empty", "garbage", "megabyte", "other-sqlite"],
)  # fmt: skip
def test_refuses_non_backups(data: bytes) -> None:
    with pytest.raises(BackupError, match="not a Beam Navigator backup"):
        checked_backup(data)


def test_refuses_newer(conn: sqlite3.Connection) -> None:
    copy = sqlite3.connect(":memory:")
    copy.deserialize(backup_bytes(conn))
    copy.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    data = copy.serialize()
    copy.close()
    with pytest.raises(BackupError, match="newer Beam Navigator"):
        checked_backup(data)


def test_refuses_damaged(conn: sqlite3.Connection) -> None:
    repo = StationRepository(conn)
    for n in range(200):
        repo.save(station(f"K{n}XYZ"))
    data = bytearray(backup_bytes(conn))
    assert len(data) > 8192
    data[4096:8192] = b"\xff" * 4096
    with pytest.raises(BackupError, match="damaged|not a Beam Navigator backup"):
        checked_backup(bytes(data))


def test_older_schema_is_migrated() -> None:
    old = sqlite3.connect(":memory:")
    migrate(old, packaged_migrations()[:7])
    assert old.execute("PRAGMA user_version").fetchone()[0] == 7
    checked = checked_backup(old.serialize())
    assert checked.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    checked.close()
    old.close()


def test_rotators_come_back_simulated(conn: sqlite3.Connection) -> None:
    profile = RotatorRepository(conn).save(
        RotatorProfile(None, "Tower", "pstrotator", "127.0.0.1", 12000, 0, 360, 0, None, (),
                       False, False)  # fmt: skip
    )
    conn.execute("UPDATE rotator_profile SET live = 1, connection_tested = 1 WHERE id = ?",
                 (profile.id,))  # fmt: skip
    conn.commit()
    checked = checked_backup(backup_bytes(conn))
    rows = checked.execute("SELECT live, connection_tested FROM rotator_profile").fetchall()
    assert [tuple(row) for row in rows] == [(0, 0)]
    checked.close()


def test_safety_copy_never_overwritten(conn: sqlite3.Connection, tmp_path: Path) -> None:
    data = backup_bytes(conn)
    first = restore(conn, data, tmp_path / "backups", NOW)
    second = restore(conn, data, tmp_path / "backups", NOW)
    assert first != second and first.exists() and second.exists()


def test_restore_replaces_and_keeps_a_copy(conn: sqlite3.Connection, tmp_path: Path) -> None:
    data = backup_bytes(conn)
    StationRepository(conn).save(station("K2B"))
    kept = restore(conn, data, tmp_path / "backups", NOW)
    assert callsigns(conn) == ["K2A"]
    assert kept == tmp_path / "backups" / "before-restore-2026-10-29-150700.db"
    copy = sqlite3.connect(kept)
    assert callsigns(copy) == ["K2A", "K2B"]
    copy.close()


def test_restore_refused_changes_nothing(conn: sqlite3.Connection, tmp_path: Path) -> None:
    StationRepository(conn).save(station("K2B"))
    with pytest.raises(BackupError):
        restore(conn, b"\x00garbage", tmp_path / "backups", NOW)
    assert callsigns(conn) == ["K2A", "K2B"]
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize(
    "extra",
    [
        "CREATE TRIGGER relive AFTER UPDATE ON rotator_profile WHEN NEW.live = 0"
        " BEGIN UPDATE rotator_profile SET live = 1, connection_tested = 1; END",
        "CREATE VIEW extra AS SELECT 1",
        "CREATE TABLE extra (x)",
    ],
    ids=["trigger", "view", "table"],
)
def test_refuses_objects_this_app_never_makes(conn: sqlite3.Connection, extra: str) -> None:
    # Final review I1: a trigger in a crafted file could put a rotator back in live mode.
    copy = sqlite3.connect(":memory:")
    copy.deserialize(backup_bytes(conn))
    copy.execute(extra)
    copy.commit()
    data = copy.serialize()
    copy.close()
    with pytest.raises(BackupError, match="not a Beam Navigator backup"):
        checked_backup(data)


def test_restore_failure_is_reported(conn: sqlite3.Connection, tmp_path: Path) -> None:
    # Final review I2: a folder that can't be made is a message, not a raw OSError.
    blocker = tmp_path / "backups"
    blocker.write_text("not a folder")
    with pytest.raises(BackupError, match="Couldn't restore: .*Nothing was changed."):
        restore(conn, backup_bytes(conn), blocker, NOW)
    assert callsigns(conn) == ["K2A"]


def test_restore_round_trips_settings(conn: sqlite3.Connection, tmp_path: Path) -> None:
    conn.execute("INSERT INTO setting (key, value) VALUES ('keymap', '{\"rotate\": \"F9\"}')")
    conn.commit()
    data = backup_bytes(conn)
    conn.execute("UPDATE setting SET value = '{}' WHERE key = 'keymap'")
    conn.commit()
    restore(conn, data, tmp_path / "backups", NOW)
    assert conn.execute("SELECT value FROM setting WHERE key = 'keymap'").fetchone()[0] == (
        '{"rotate": "F9"}'
    )
