"""Where the database lives, and who has it open (owner, 2026-11-21).

The data folder may be shared between the PCs on the owner's network. SQLite on a
network share is only safe with one PC at a time, so the folder holds a lock file naming
the PC that has it open. Another PC is refused until the operator takes over; a lock left
by a crash on this same PC is cleared without asking. The choice of folder is kept in a
pointer file in this PC's own folder, since the database can't say where it lives.
"""

import ctypes
import json
import os
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

DB_FILE = "beamnav.db"
POINTER_FILE = "data-folder.txt"
LOCK_FILE = "beamnav.lock"


@dataclass(frozen=True)
class Holder:
    host: str
    pid: int
    since: str  # ISO time the PC opened the folder


def resolve(home: Path, given: Path | None) -> Path:
    """--data-dir, else the chosen folder, else this PC's own folder."""
    if given is not None:
        return given
    pointer = home / POINTER_FILE
    if pointer.exists():
        text = pointer.read_text(encoding="utf-8").strip()
        if text:
            return Path(text)
    return home


def choose(home: Path, folder: Path) -> None:
    """Used from the next start. This PC's own folder needs no pointer."""
    pointer = home / POINTER_FILE
    if folder.resolve() == home.resolve():
        pointer.unlink(missing_ok=True)
        return
    home.mkdir(parents=True, exist_ok=True)
    pointer.write_text(str(folder), encoding="utf-8")


def held_by(folder: Path) -> Holder | None:
    lock = folder / LOCK_FILE
    if not lock.exists():
        return None
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
        return Holder(str(data["host"]), int(data["pid"]), str(data["since"]))
    except (ValueError, KeyError, TypeError, OSError):
        return Holder("unknown", 0, "")  # unreadable: still someone's, never ignored


def _write(folder: Path, host: str, pid: int, since: str) -> None:
    (folder / LOCK_FILE).write_text(json.dumps(asdict(Holder(host, pid, since))), "utf-8")


def acquire(
    folder: Path, host: str, pid: int, since: str, alive: Callable[[int], bool]
) -> Holder | None:
    """Takes the lock and returns None, or returns who holds it. Another PC is never
    assumed gone; on this PC a holder whose process has ended left it after a crash."""
    holder = held_by(folder)
    if holder is not None and holder.pid != pid:
        if holder.host != host or alive(holder.pid):
            return holder
    _write(folder, host, pid, since)
    return None


def take_over(folder: Path, host: str, pid: int, since: str) -> None:
    """The second PC's choice, after checking the first isn't still running."""
    _write(folder, host, pid, since)


def release(folder: Path, host: str, pid: int) -> None:
    holder = held_by(folder)
    if holder is not None and (holder.host, holder.pid) == (host, pid):
        (folder / LOCK_FILE).unlink(missing_ok=True)


def pid_alive(pid: int) -> bool:
    """Without signalling it: on Windows os.kill(pid, 0) would end the process."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def move_data(
    conn: sqlite3.Connection, folder: Path, db_file: str
) -> Literal["copied", "existing"]:
    """Copies the open database into the folder, unless one is already there: that one is
    used as it is and never overwritten."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / db_file
        if target.exists():
            return "existing"
        copy = sqlite3.connect(target)
        try:
            conn.backup(copy)
        finally:
            copy.close()
    except (OSError, sqlite3.Error) as exc:
        raise ValueError(f"Beam Navigator can't use {folder}: {exc}") from exc
    return "copied"
