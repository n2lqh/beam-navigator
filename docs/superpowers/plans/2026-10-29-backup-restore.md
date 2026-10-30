# Backup and Restore (Plan 4a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settings → Data backs up the whole database to one file and restores it, safely. This is the first plan of Milestone 4.

**Architecture:**
- A new top-level module, `src/beam_navigator/backup.py` (beside `export.py`), does the work with the standard `sqlite3` backup and serialize APIs, entirely in memory.
- `Desk` wraps it: it finds the data folder from the open database, keeps a safety copy, and tells `RotateService` to forget the rotor positions it remembered.
- A Data tab in Settings has a Backup button (a download) and a Restore upload, behind a confirmation dialog.

**Tech Stack:** Python 3.12+, `sqlite3` (`Connection.backup`, `serialize`, `deserialize`), NiceGUI 3.18 (`ui.download.content`, `ui.upload`, `ui.dialog`), pytest. No new dependencies.

**Spec:** `docs/requirements.md` 4.8 ("Backup and restore of the whole database to a single file"), section 6 Milestone 4, invariants 2 and 8, and acceptance test 35.

## Global Constraints

- Invariant 2: a restore never sends a rotator command.
- Invariant 8: live mode needs a connection test passed on this machine. After a restore, every rotator profile is in simulation (`live = 0`).
- Acceptance test 35: the QRZ password never appears in a backup. It lives only in keyring, and the backup is the database alone.
- `core/` is untouched. `backup.py` lives beside `export.py` because it uses `sqlite3`.
- Never delete the operator's files. Safety copies are kept; nothing prunes them.
- No new dependencies.

## Design (decisions this plan makes)

**Backup file.**
- Name: `beamnav-backup-YYYY-MM-DD-HHMM.db` (local time).
- Contents: an exact SQLite copy, made with `conn.backup(memory_conn)` then `memory_conn.serialize()`. No temporary files.

**A file is a Beam Navigator backup when**, opened in memory with `deserialize`, all of these hold:
1. It starts with `b"SQLite format 3\x00"`.
2. `PRAGMA integrity_check` returns `ok`.
3. `PRAGMA user_version` is between 1 and `SCHEMA_VERSION`.
4. The tables `operator_profile`, `station` and `net` exist.

**Refusal messages** (`BackupError`, shown as written):
- Not SQLite, user_version 0, or missing tables: "This is not a Beam Navigator backup."
- integrity_check fails: "This backup is damaged and can't be restored."
- user_version is newer: "This backup is from a newer Beam Navigator. Update the app, then restore it."

A file that passes is migrated in memory with `migrate(...)`, and every rotator gets `live = 0`, before anything touches the live database.

**Restore order:**
1. Check the file.
2. Commit the live connection.
3. Write the safety copy to `<data dir>/backups/before-restore-YYYY-MM-DD-HHMMSS.db`.
4. Copy the checked file into the live connection (`checked.backup(live_conn)`).
5. Call `RotateService.forget()`, which clears the cached adapters and remembered rotor positions.

If step 1 fails, nothing is written. The data dir is the folder of the `main` entry in `PRAGMA database_list`. An in-memory database has no folder, so `Desk.restore_backup` then raises `BackupError("Restore needs a database file.")`.

**Settings → Data tab** (markers in brackets):
- A Backup button [`backup-download`].
- A Restore upload [`backup-restore`], `.db`, at most 50 MB.
- Choosing a file opens a dialog [`restore-dialog`] reading: "Restore replaces all your stations, nets, history and settings with this backup. Your current data is saved first in {folder}. Every rotator will be put in simulation mode." It has the buttons Restore [`restore-confirm`] and Cancel.
- On success it shows a notice that stays until the operator closes it (`timeout=0`, `close_button=True`), so the simulation warning is not missed: "Restored. Your current data was saved as {file name}. Rotators are back in simulation: run Test connection to go live again. Reload any other open Beam Navigator pages."
- On refusal it shows the `BackupError` text, and nothing changes.

## Review Focus

- A restore while a rotator is live: it must end in simulation, with zero commands sent and no remembered position reused.
- A garbage, empty or huge upload: refused with a message, never a crash (acceptance test 32's spirit), and the live data is unchanged.
- A backup from an older schema: restored and migrated to the current one.
- A backup made, then data changed, then restored: the data returns exactly, including settings such as `keymap`.
- The safety copy really opens as a database holding the pre-restore data.

---

### Task 1: `backup.py`, making and checking backups

**Files:**
- Create: `src/beam_navigator/backup.py`
- Test: `tests/unit/test_backup.py`

**Interfaces:**
- Consumes: `store.db.migrate`, `store.db._packaged_migrations` (rename it to public `packaged_migrations`, keeping the call in `open_db`), `store.db.SCHEMA_VERSION`.
- Produces:
  - `class BackupError(ValueError)`
  - `backup_bytes(conn: sqlite3.Connection) -> bytes`
  - `backup_filename(now: datetime) -> str`
  - `checked_backup(data: bytes) -> sqlite3.Connection`, an in-memory connection, migrated, with rotators in simulation. The caller closes it.
  - `restore(conn: sqlite3.Connection, data: bytes, keep_dir: Path, now: datetime) -> Path`, returning the safety copy's path.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_backup.py`. Use a file database from `open_db(tmp_path / "beamnav.db")` with one station saved through `StationRepository`.
  - `test_backup_round_trip`: `checked_backup(backup_bytes(conn))` holds the station.
  - `test_backup_filename`: `backup_filename(datetime(2026, 10, 29, 15, 7)) == "beamnav-backup-2026-10-29-1507.db"`.
  - `test_refuses_non_backups`, parametrized over `b""`, `b"\x00garbage"`, `b"x" * 1_000_000`, and the bytes of an empty SQLite database (user_version 0): each raises `BackupError` matching "not a Beam Navigator backup".
  - `test_refuses_newer`: bump `user_version` to `SCHEMA_VERSION + 1` in a copy; raises matching "newer Beam Navigator".
  - `test_refuses_damaged`: overwrite bytes 4096..8192 of a real backup that has more than two pages (add 200 stations first) with `b"\xff"`. It raises `BackupError` matching "damaged" or "not a Beam Navigator backup". Either is acceptable, because SQLite may fail to open it at all; the assertion is that it is refused.
  - `test_older_schema_is_migrated`: build a database with `migrate(conn, packaged_migrations()[:7])`. `checked_backup` of its bytes gives user_version == `SCHEMA_VERSION`.
  - `test_rotators_come_back_simulated`: save a rotator profile and set `live = 1` with SQL. After `checked_backup`, every `live` is 0.
  - `test_restore_replaces_and_keeps_a_copy`:
    - back up (station A only), add station B, then `restore(conn, data, tmp_path / "backups", now)`
    - the live conn has A and not B
    - the returned path is `tmp_path / "backups" / "before-restore-2026-10-29-150700.db"`, and opened it holds A and B
  - `test_restore_refused_changes_nothing`: `restore` with garbage raises `BackupError`, the station count is unchanged, and the `backups` folder does not exist.

- [ ] **Step 2: Run them to see them fail.** Run: `uv run pytest tests/unit/test_backup.py -q`. Expected: FAIL, because `beam_navigator.backup` is missing.

- [ ] **Step 3: Implement `backup.py`** to the Design section. Wrap every `sqlite3.DatabaseError` from deserialize and the PRAGMAs in `BackupError` (refusal text by the rule above). Write the safety copy with `conn.backup(sqlite3.connect(path))` and close it. Create `keep_dir` only after the check passes.

- [ ] **Step 4: Run the tests to see them pass.** Run: `uv run pytest tests/unit/test_backup.py -q`. Expected: all pass. Then `uv run pytest -q` shows the full suite green.

- [ ] **Step 5: Commit**: `feat: back up and check the whole database in one file (spec 4.8)`.

### Task 2: `Desk` backup and restore; the rotator service forgets

**Files:**
- Modify: `src/beam_navigator/desk.py`, `src/beam_navigator/rotators/service.py`
- Test: `tests/unit/test_desk_backup.py`

**Interfaces:**
- Consumes: Task 1's `backup_bytes`, `backup_filename`, `restore`, `BackupError`.
- Produces:
  - `RotateService.forget() -> None`
  - `Desk.backup() -> tuple[str, bytes]`, giving the filename and bytes
  - `Desk.data_dir() -> Path | None`
  - `Desk.restore_backup(data: bytes, now: datetime | None = None) -> Path`

- [ ] **Step 1: Write the failing tests.** The desk sits on `open_db(tmp_path / "beamnav.db")` with a `RotateService` whose `adapter_for` returns a recording fake, like `FakeRotator` in `tests/ui/test_settings.py`.
  - `test_backup_names_and_bytes`: the name starts "beamnav-backup-" and ends ".db", and the bytes start with `b"SQLite format 3\x00"`.
  - `test_data_dir`: equals `tmp_path`. For `open_db(":memory:")` it is `None`.
  - `test_restore_sends_no_rotator_command_and_forgets` (acceptance test 26, invariant 2):
    - rotate once, so the service remembers a position
    - back up, then restore
    - the fake received exactly that one command and no more
    - `service.last_rotor(id)` is `None`
  - `test_restore_needs_a_file`: on `:memory:`, it raises `BackupError` matching "needs a database file".
  - `test_backup_has_no_password` (acceptance test 35): no row of the backup's `setting` table has a key containing "password", and the bytes do not contain the text `"password"`.

- [ ] **Step 2: Run them to see them fail.** Run: `uv run pytest tests/unit/test_desk_backup.py -q`. Expected: FAIL with AttributeError for `backup` or `forget`.

- [ ] **Step 3: Implement it.**
  - `forget()` clears `_adapters` and `_last_rotor`.
  - `data_dir()` reads `PRAGMA database_list`; an empty file name means `None`.
  - `restore_backup` calls `restore(self.conn, data, dir / "backups", now or datetime.now())` and then `self.service.forget()`.

- [ ] **Step 4: Run the tests to see them pass.** Run: `uv run pytest tests/unit/test_desk_backup.py -q`. Expected: all pass. Then the full suite, `ruff check .` and `mypy src/beam_navigator/core`.

- [ ] **Step 5: Commit**: `feat: desk backup and restore; restore never moves the rotator (spec 4.8, AT 26, 35)`.

### Task 3: Settings → Data tab and docs

**Files:**
- Modify: `src/beam_navigator/ui/settings.py`, `docs/decisions.md` (add decision 34), `docs/requirements.md` 4.8 (add "(Settings → Data; decision 34)" after the backup line)
- Test: `tests/ui/test_settings.py`

**Interfaces:**
- Consumes: Task 2's `Desk.backup`, `Desk.restore_backup`, `Desk.data_dir`.

- [ ] **Step 1: Write the failing UI tests.** Use the existing settings fixtures, with the desk on a `tmp_path` file database.
  - `test_backup_downloads`: click `backup-download`. `await user.download.next()` returns bytes starting `b"SQLite format 3\x00"`.
  - `test_restore_after_confirm`:
    - back up via `desk.backup()`, then add a station
    - `handle_uploads` the bytes on `backup-restore`
    - the user sees "Restore replaces all your stations" and "put in simulation mode"
    - click `restore-confirm`
    - the user sees "Restored." and "Rotators are back in simulation", and the added station is gone
  - `test_restore_cancel_changes_nothing`: upload, click Cancel; the station is still there.
  - `test_restore_garbage_reports`: upload `b"\x00garbage"`; the user sees "not a Beam Navigator backup" and no dialog opens.

- [ ] **Step 2: Run them to see them fail.** Run: `uv run pytest tests/ui/test_settings.py -q -k "backup or restore"`. Expected: FAIL, marker not found.

- [ ] **Step 3: Implement `_data_panel(desk)` and a "Data" tab after Keys.**
  - Check the upload with `checked_backup` before the dialog opens, so garbage never gets a dialog. Close the checked connection.
  - Keep the bytes for the confirm.
  - Write decision 34 (summarising the Design section) and the requirements note.

- [ ] **Step 4: Run the tests to see them pass.** Run the full suite, `ruff check .` and `mypy src/beam_navigator/core`. Expected: all green.

- [ ] **Step 5: Commit**: `feat: Settings → Data backs up and restores (spec 4.8, decision 34)`.
