"""The shared data folder and its lock (owner, 2026-11-21): one PC at a time, with a way
for the second PC to take over a lock left behind."""

import sqlite3
from pathlib import Path

import pytest

from beam_navigator.data_folder import (
    LOCK_FILE,
    POINTER_FILE,
    Holder,
    acquire,
    choose,
    held_by,
    move_data,
    release,
    resolve,
    take_over,
)
from beam_navigator.store.db import open_db

SINCE = "2026-11-21T19:42:00-05:00"


def never_alive(pid: int) -> bool:
    return False


def always_alive(pid: int) -> bool:
    return True


def test_resolve_order(tmp_path: Path) -> None:
    home, shared, given = tmp_path / "home", tmp_path / "shared", tmp_path / "given"
    home.mkdir()
    assert resolve(home, None) == home  # nothing chosen: this PC's own folder
    choose(home, shared)
    assert (home / POINTER_FILE).exists()
    assert resolve(home, None) == shared
    assert resolve(home, given) == given  # --data-dir still wins
    choose(home, home)  # back to this PC's own folder
    assert not (home / POINTER_FILE).exists()
    assert resolve(home, None) == home


def test_first_pc_takes_the_lock(tmp_path: Path) -> None:
    assert acquire(tmp_path, "SHACK", 10, SINCE, never_alive) is None
    assert held_by(tmp_path) == Holder("SHACK", 10, SINCE)


def test_another_pc_is_refused_until_it_takes_over(tmp_path: Path) -> None:
    acquire(tmp_path, "SHACK", 10, SINCE, never_alive)
    blocked = acquire(tmp_path, "OFFICE", 20, SINCE, never_alive)
    assert blocked == Holder("SHACK", 10, SINCE)  # another PC: never assumed gone
    take_over(tmp_path, "OFFICE", 20, SINCE)
    assert held_by(tmp_path) == Holder("OFFICE", 20, SINCE)


def test_same_pc_after_a_crash_takes_it_back(tmp_path: Path) -> None:
    acquire(tmp_path, "SHACK", 10, SINCE, never_alive)
    assert acquire(tmp_path, "SHACK", 11, SINCE, never_alive) is None
    assert held_by(tmp_path) == Holder("SHACK", 11, SINCE)


def test_same_pc_still_running_is_refused(tmp_path: Path) -> None:
    acquire(tmp_path, "SHACK", 10, SINCE, never_alive)
    assert acquire(tmp_path, "SHACK", 11, SINCE, always_alive) == Holder("SHACK", 10, SINCE)


def test_release_removes_only_our_lock(tmp_path: Path) -> None:
    acquire(tmp_path, "SHACK", 10, SINCE, never_alive)
    release(tmp_path, "OFFICE", 20)  # not ours: left alone
    assert held_by(tmp_path) is not None
    release(tmp_path, "SHACK", 10)
    assert not (tmp_path / LOCK_FILE).exists()


def test_a_damaged_lock_file_reads_as_unknown_holder(tmp_path: Path) -> None:
    (tmp_path / LOCK_FILE).write_text("not json", encoding="utf-8")
    holder = held_by(tmp_path)
    assert holder is not None and holder.host == "unknown"  # never silently ignored


def test_move_copies_data_into_an_empty_folder(tmp_path: Path) -> None:
    conn = open_db(str(tmp_path / "beamnav.db"))
    conn.execute("INSERT INTO setting (key, value) VALUES ('marker', 'here')")
    conn.commit()
    target = tmp_path / "shared"
    assert move_data(conn, target, "beamnav.db") == "copied"
    copied = sqlite3.connect(target / "beamnav.db")
    assert copied.execute("SELECT value FROM setting WHERE key = 'marker'").fetchone() == ("here",)
    copied.close()
    assert move_data(conn, target, "beamnav.db") == "existing"  # never overwritten
    conn.close()


def test_move_refuses_a_folder_it_cannot_write(tmp_path: Path) -> None:
    conn = open_db(":memory:")
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="can't use"):
        move_data(conn, blocker / "sub", "beamnav.db")
    conn.close()


def test_pid_alive_reads_without_signalling() -> None:
    import os
    import subprocess
    import sys

    from beam_navigator.data_folder import pid_alive

    assert pid_alive(os.getpid())
    assert not pid_alive(0)
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    assert not pid_alive(finished.pid)
