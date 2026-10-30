import math
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from beam_navigator.core.models import RotatorProfile
from beam_navigator.store.db import open_db
from beam_navigator.store.repositories import (
    AliasRepository,
    CommandLog,
    RotatorNotTested,
    RotatorRepository,
)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_db(":memory:")
    yield connection
    connection.close()


def pst(**changes: object) -> RotatorProfile:
    profile = RotatorProfile(
        id=None, name="VHF", adapter="pstrotator", host="127.0.0.1", port=12000,
        az_min=0.0, az_max=450.0, offset=0.0, speed_deg_per_s=None, bands=("2 m", "70 cm"),
        live=False, connection_tested=False,
    )  # fmt: skip
    return replace(profile, **changes)  # type: ignore[arg-type]


def test_new_profile_starts_in_simulation(conn: sqlite3.Connection) -> None:  # acceptance 25
    rotators = RotatorRepository(conn)
    saved = rotators.save(pst(live=True, connection_tested=True))
    assert saved.id is not None
    assert saved.live is False
    assert saved.connection_tested is False
    with pytest.raises(RotatorNotTested):
        rotators.set_live(saved.id, True)
    rotators.record_connection_test(saved.id, True)
    rotators.set_live(saved.id, True)
    assert rotators.get(saved.id).live is True


def test_changing_connection_needs_a_new_test(conn: sqlite3.Connection) -> None:  # Focus 3
    rotators = RotatorRepository(conn)
    saved = rotators.save(pst())
    assert saved.id is not None
    rotators.record_connection_test(saved.id, True)
    rotators.set_live(saved.id, True)
    renamed = rotators.save(replace(rotators.get(saved.id), name="VHF beam"))
    assert (renamed.live, renamed.connection_tested) == (True, True)
    moved = rotators.save(replace(renamed, port=12002))
    assert (moved.live, moved.connection_tested) == (False, False)


def test_failed_test_clears_live(conn: sqlite3.Connection) -> None:
    rotators = RotatorRepository(conn)
    saved = rotators.save(pst())
    assert saved.id is not None
    rotators.record_connection_test(saved.id, True)
    rotators.set_live(saved.id, True)
    rotators.record_connection_test(saved.id, False)
    assert (rotators.get(saved.id).live, rotators.get(saved.id).connection_tested) == (False, False)


def test_simulation_profile_cannot_go_live(conn: sqlite3.Connection) -> None:
    rotators = RotatorRepository(conn)
    saved = rotators.save(pst(adapter="simulation", host=None, port=None))
    assert saved.id is not None
    rotators.record_connection_test(saved.id, True)
    with pytest.raises(ValueError):
        rotators.set_live(saved.id, True)


@pytest.mark.parametrize(
    "changes",
    [{"az_min": 10.0, "az_max": 5.0}, {"az_min": math.nan}, {"speed_deg_per_s": 0.0},
     {"offset": 200.0}, {"name": " "}],
)
def test_invalid_profile_rejected(conn: sqlite3.Connection, changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RotatorRepository(conn).save(pst(**changes))
    assert RotatorRepository(conn).list() == []


def test_yaesu_profile_round_trips(conn: sqlite3.Connection) -> None:
    rotators = RotatorRepository(conn)
    saved = rotators.save(pst(speed_deg_per_s=6.0, offset=-3.5))
    assert saved.id is not None
    got = rotators.get(saved.id)
    assert (got.az_min, got.az_max, got.offset, got.speed_deg_per_s) == (0.0, 450.0, -3.5, 6.0)
    assert got.bands == ("2 m", "70 cm")
    assert rotators.list() == [got]


def test_command_log_newest_first(conn: sqlite3.Connection) -> None:
    saved = RotatorRepository(conn).save(pst())
    assert saved.id is not None
    log = CommandLog(conn)
    log.add(saved.id, "FN20ok", 354.2, "<PST><AZIMUTH>354</AZIMUTH></PST>", True, "sent", None)
    log.add(saved.id, "PA", 400.0, None, False, "outside travel", None)
    records = log.recent(saved.id)
    assert [r.target_label for r in records] == ["PA", "FN20ok"]
    assert records[0].ok is False and records[0].sent is None
    assert records[1].requested_true == 354.2


def test_version_1_database_upgrades(tmp_path: Path) -> None:
    path = tmp_path / "v1.db"
    old = sqlite3.connect(path)
    old.executescript(
        (Path(__file__).parents[2] / "src/beam_navigator/store/migrations/0001_initial.sql")
        .read_text(encoding="utf-8")
        + "\nPRAGMA user_version = 1;"
        + "\nINSERT INTO alias (name, kind, value) VALUES ('CLUB', 'grid', 'FM29jw');"
    )
    old.close()
    conn = open_db(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 8
    assert AliasRepository(conn).get("CLUB") is not None
    assert RotatorRepository(conn).list() == []
    conn.close()


@pytest.mark.parametrize(
    "changes",
    [{"port": 0}, {"port": -5}, {"port": 70000}, {"port": None}, {"host": None}, {"host": " "}],
)
def test_live_capable_profile_needs_host_and_port(
    conn: sqlite3.Connection, changes: dict[str, object]
) -> None:  # final review
    with pytest.raises(ValueError):
        RotatorRepository(conn).save(pst(**changes))
