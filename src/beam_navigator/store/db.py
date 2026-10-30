"""SQLite connection and numbered .sql migrations, tracked by PRAGMA user_version."""

import sqlite3
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path


class MigrationError(RuntimeError):
    """The database could not be brought to this app's schema version."""


def packaged_migrations() -> list[tuple[int, str]]:
    folder = files("beam_navigator.store") / "migrations"
    entries = sorted((e for e in folder.iterdir() if e.name.endswith(".sql")), key=lambda e: e.name)
    return [(int(entry.name[:4]), entry.read_text(encoding="utf-8")) for entry in entries]


SCHEMA_VERSION = max((number for number, _ in packaged_migrations()), default=0)


def _version(conn: sqlite3.Connection) -> int:
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    return version


def migrate(conn: sqlite3.Connection, migrations: Sequence[tuple[int, str]]) -> None:
    current = _version(conn)
    newest = max((number for number, _ in migrations), default=0)
    if current > newest:
        raise MigrationError(
            f"Database schema version {current} is newer than this app ({newest}). "
            "Update Beam Navigator; the database was not changed."
        )
    for number, sql in sorted(migrations):
        if number <= current:
            continue
        try:
            # One transaction per migration: it applies completely or not at all.
            conn.executescript(f"BEGIN;\n{sql}\n;PRAGMA user_version = {number};\nCOMMIT;")
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.rollback()
            raise MigrationError(f"Migration {number} failed: {exc}") from exc


def open_db(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        migrate(conn, packaged_migrations())
    except Exception:
        conn.close()
        raise
    return conn
