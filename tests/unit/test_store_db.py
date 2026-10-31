import re
import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from beam_navigator.store.db import SCHEMA_VERSION, MigrationError, migrate, open_db

TABLES = {
    "operator_profile", "alias", "station", "net", "session", "checkin", "rotator_profile",
    "rotator_command",
}  # fmt: skip


def user_version(conn: sqlite3.Connection) -> int:
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    return version


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def test_new_database_is_at_schema_version() -> None:
    conn = open_db(":memory:")
    assert SCHEMA_VERSION == 9
    assert user_version(conn) == SCHEMA_VERSION
    assert TABLES <= table_names(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_reopen_does_not_rerun_migrations(tmp_path: Path) -> None:  # Review Focus 3
    path = tmp_path / "b.db"
    conn = open_db(path)
    conn.execute("INSERT INTO alias (name, kind, value) VALUES ('CLUB', 'grid', 'FM29jw')")
    conn.commit()
    conn.close()
    again = open_db(path)
    assert again.execute("SELECT value FROM alias WHERE name = 'CLUB'").fetchone()[0] == "FM29jw"
    assert user_version(again) == SCHEMA_VERSION
    again.close()


def test_migrations_apply_in_order_and_only_once() -> None:
    conn = sqlite3.connect(":memory:")
    steps = [(1, "CREATE TABLE a(x)"), (2, "CREATE TABLE b(x)")]
    migrate(conn, steps)
    migrate(conn, steps)
    assert user_version(conn) == 2
    assert {"a", "b"} <= table_names(conn)


def test_failed_migration_rolls_back() -> None:
    conn = sqlite3.connect(":memory:")
    with pytest.raises(MigrationError, match="Migration 2"):
        migrate(conn, [(1, "CREATE TABLE a(x)"), (2, "CREATE TABLE b(x); SYNTAX ERROR")])
    assert "b" not in table_names(conn)
    assert user_version(conn) == 1


def test_newer_database_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(MigrationError, match="newer"):
        open_db(path)


def test_migration_files_are_numbered() -> None:
    names = sorted(
        entry.name
        for entry in (files("beam_navigator.store") / "migrations").iterdir()
        if entry.name.endswith(".sql")
    )
    assert names
    assert all(re.fullmatch(r"\d{4}_[a-z0-9_]+\.sql", name) for name in names)
    assert [int(name[:4]) for name in names] == list(range(1, len(names) + 1))
    assert len(names) == SCHEMA_VERSION
