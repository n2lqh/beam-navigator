"""Backup and restore of the whole database as one file (spec 4.8; decision 34).

A backup is an exact SQLite copy. A restore checks the file completely in memory before the
live database is touched, keeps a copy of the current data, and leaves every rotator in
simulation: the backup may come from another PC, so live mode needs a connection test
passed here again (invariant 8).
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from beam_navigator.store.db import SCHEMA_VERSION, MigrationError, migrate, packaged_migrations

SQLITE_HEADER = b"SQLite format 3\x00"
_REQUIRED_TABLES = {"operator_profile", "station", "net"}
NOT_A_BACKUP = "This is not a Beam Navigator backup."
DAMAGED = "This backup is damaged and can't be restored."
NEWER = "This backup is from a newer Beam Navigator. Update the app, then restore it."


class BackupError(ValueError):
    """The file can't be restored; the live data was not changed."""


def _schema(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    return {(row[0], row[1]) for row in conn.execute("SELECT type, name FROM sqlite_master")}


def _app_schema() -> set[tuple[str, str]]:
    fresh = sqlite3.connect(":memory:")
    try:
        migrate(fresh, packaged_migrations())
        return _schema(fresh)
    finally:
        fresh.close()


def backup_bytes(conn: sqlite3.Connection) -> bytes:
    conn.commit()
    copy = sqlite3.connect(":memory:")
    try:
        conn.backup(copy)
        return copy.serialize()
    finally:
        copy.close()


def backup_filename(now: datetime) -> str:
    return f"beamnav-backup-{now:%Y-%m-%d-%H%M}.db"


def checked_backup(data: bytes) -> sqlite3.Connection:
    """The backup in memory, migrated to this app's schema, with rotators in simulation.
    The caller closes it."""
    if not data.startswith(SQLITE_HEADER):
        raise BackupError(NOT_A_BACKUP)
    checked = sqlite3.connect(":memory:")
    try:
        _check(checked, data)
        checked.execute("UPDATE rotator_profile SET live = 0, connection_tested = 0")
        checked.commit()
        still_live = checked.execute(
            "SELECT COUNT(*) FROM rotator_profile WHERE live OR connection_tested"
        ).fetchone()[0]
        if still_live:
            raise BackupError(NOT_A_BACKUP)
    except BackupError:
        checked.close()
        raise
    except sqlite3.DatabaseError as exc:
        checked.close()
        raise BackupError(DAMAGED) from exc
    return checked


def _check(checked: sqlite3.Connection, data: bytes) -> None:
    try:
        checked.deserialize(data)
        version: int = checked.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise BackupError(NOT_A_BACKUP) from exc
    if version == 0:
        raise BackupError(NOT_A_BACKUP)
    try:
        verdict = checked.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise BackupError(DAMAGED) from exc
    if verdict != "ok":
        raise BackupError(DAMAGED)
    if version > SCHEMA_VERSION:
        raise BackupError(NEWER)
    tables = {row[0] for row in checked.execute("SELECT name FROM sqlite_master")}
    if not _REQUIRED_TABLES <= tables:
        raise BackupError(NOT_A_BACKUP)
    try:
        migrate(checked, packaged_migrations())
    except MigrationError as exc:
        raise BackupError(DAMAGED) from exc
    # Exactly the tables and indexes this app makes: a trigger or view from elsewhere would
    # be copied into the live database and could put a rotator back in live mode (final
    # review I1).
    if _schema(checked) != _app_schema():
        raise BackupError(NOT_A_BACKUP)


def _safety_path(keep_dir: Path, now: datetime) -> Path:
    stem = f"before-restore-{now:%Y-%m-%d-%H%M%S}"
    path = keep_dir / f"{stem}.db"
    n = 2
    while path.exists():  # never overwrite an earlier safety copy
        path = keep_dir / f"{stem}-{n}.db"
        n += 1
    return path


def restore(conn: sqlite3.Connection, data: bytes, keep_dir: Path, now: datetime) -> Path:
    """Replace the live database with the backup; returns the copy kept of the old data."""
    checked = checked_backup(data)
    try:
        conn.commit()
        keep_dir.mkdir(parents=True, exist_ok=True)
        path = _safety_path(keep_dir, now)
        safety = sqlite3.connect(path)
        try:
            conn.backup(safety)
        finally:
            safety.close()
        checked.backup(conn)  # one step: it completes or leaves the data as it was
    except (OSError, sqlite3.Error) as exc:
        # A full disk, a locked file or a read-only folder (final review I2).
        raise BackupError(f"Couldn't restore: {exc}. Nothing was changed.") from exc
    finally:
        checked.close()
    return path
