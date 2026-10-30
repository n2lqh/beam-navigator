"""QRZ results are cached apart from station records (requirements 4.9, acceptance 36)."""

import sqlite3
from collections.abc import Iterator
from dataclasses import replace

import pytest

from beam_navigator.core.qrz import parse_response
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import QrzRepository


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


def test_save_and_get(conn: sqlite3.Connection, qrz_examples: list[bytes]) -> None:
    record = parse_response(qrz_examples[1]).record
    assert record is not None
    cache = QrzRepository(conn)
    cache.save(record, "2026-10-28T20:00:00+00:00")
    assert cache.get("aa7bq") == (record, "2026-10-28T20:00:00+00:00")
    assert cache.get("K9ZZZ") is None


def test_second_save_replaces(conn: sqlite3.Connection, qrz_examples: list[bytes]) -> None:
    record = parse_response(qrz_examples[1]).record
    assert record is not None
    cache = QrzRepository(conn)
    cache.save(record, "2026-10-27T20:00:00+00:00")
    cache.save(replace(record, grid=None, geoloc="state"), "2026-10-28T20:00:00+00:00")
    saved = cache.get("AA7BQ")
    assert saved is not None and saved[0].grid is None and saved[1].startswith("2026-10-28")


def test_station_table_untouched(conn: sqlite3.Connection, qrz_examples: list[bytes]) -> None:
    record = parse_response(qrz_examples[1]).record
    assert record is not None
    QrzRepository(conn).save(record, "2026-10-28T20:00:00+00:00")
    assert conn.execute("SELECT COUNT(*) FROM station").fetchone()[0] == 0
