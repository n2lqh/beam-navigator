# Milestone 1c — SQLite Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local SQLite store, created and upgraded by numbered `.sql` migrations, that saves operator profiles, aliases, stations, nets, sessions and check-ins, and feeds saved aliases and stations into the target resolver.

**Architecture:** `store/db.py` opens a connection and applies `store/migrations/NNNN_*.sql` in order, tracked by `PRAGMA user_version`. `store/repositories.py` holds one small class per entity, each taking a `sqlite3.Connection` and returning frozen dataclasses from `core/models.py`. Rules that need no database (alias name collisions, value checks) live in `core`; the store calls them.

**Tech Stack:** Python 3.12 stdlib `sqlite3`, `importlib.resources`. No ORM. No new dependencies.

**Spec:** `docs/requirements.md` v2.0 — sections 2 (invariants 3, 5, 9, 10), 3, 4.2, 4.3, 4.6, 8; 7 (tests 10, 13, 14, 15 and the cross-fixture checks). Decisions 10 and 12 in `docs/decisions.md`.

## Scope

In: schema for every entity in spec section 3 except rotator profiles; migrations; repositories; resolver wiring; roster import with raw text; identical re-import detection; conflicts with saved stations; expected participants; substitute controller.

Out (Milestone 2, with rotator settings and the UI): rotator profiles and the command log (their own migration), the default database location (needs `platformdirs`), CLI commands that read the database, backup/restore (Milestone 4).

## Global Constraints

- `store/` uses the standard `sqlite3` module and numbered `.sql` migrations. No ORM (CLAUDE.md).
- `core/` stays free of `sqlite3` imports.
- Every connection runs `PRAGMA foreign_keys = ON`. History is never cascade-deleted: foreign keys use `ON DELETE RESTRICT`.
- Times are stored as UTC ISO-8601 text; session dates as `YYYY-MM-DD` text, always supplied by the caller, never derived from roster words (spec 7, WA3NUF note).
- Callsigns are stored normalized with `normalize_callsign` (upper case, full text including `/P`).
- Grid text is stored exactly as given; comparisons upper-case it.
- Raw roster text is stored unchanged with each imported session (invariant 9).
- Published bearings are stored as printed text and never read back as a heading (invariant 3).
- No station, net or profile is created by default (invariant 10). Tests use the fixture rosters and `tmp_path`/`:memory:` databases only.
- Match the existing code: 4-space indentation, line length 100, `ruff`, `mypy --strict` on `src/beam_navigator`.

## Review Focus

1. **Re-import of the same roster through a different mail client** (CRLF vs LF, trailing spaces, a BOM) → still detected as identical. Test in Task 4.
2. **Callsign case:** a station saved as `n2lqh` and a roster row `N2LQH` → one station record. Test in Task 3.
3. **Database reopened from disk:** data written, connection closed, file reopened → same data, no migration re-run. Test in Task 1.
4. **Deleting a net that has sessions** → refused with an error, history intact. Test in Task 4.
5. **Non-ASCII text** (`Québec`, `José`, emoji in notes) → round-trips unchanged. Test in Task 3.

---

### Task 1: Database and migrations

**Files:**
- Create: `src/beam_navigator/store/__init__.py` (empty), `src/beam_navigator/store/db.py`, `src/beam_navigator/store/migrations/0001_initial.sql`
- Test: `tests/unit/test_store_db.py`

**Interfaces:**
- Produces: `MigrationError(RuntimeError)`. `open_db(path: Path | str) -> sqlite3.Connection` — creates the file if needed, sets `row_factory = sqlite3.Row`, enables foreign keys, applies pending migrations. `SCHEMA_VERSION: int` (the highest migration number shipped, 1 for now). `migrate(conn: sqlite3.Connection, migrations: Sequence[tuple[int, str]]) -> None` (used by `open_db` with the packaged files; tests pass their own list).

Schema for `0001_initial.sql` (all `id INTEGER PRIMARY KEY`):

| Table | Columns |
|---|---|
| `operator_profile` | `name TEXT NOT NULL UNIQUE`, `callsign TEXT`, `home_grid TEXT NOT NULL`, `lat REAL`, `lon REAL`, `units TEXT NOT NULL CHECK (units IN ('km','mi'))`, `timezone TEXT NOT NULL`, `home_region TEXT`, `is_active INTEGER NOT NULL DEFAULT 0` |
| `alias` | `name TEXT NOT NULL UNIQUE`, `kind TEXT NOT NULL CHECK (kind IN ('grid','coords','station','heading'))`, `value TEXT NOT NULL` |
| `station` | `callsign TEXT NOT NULL UNIQUE`, `name TEXT`, `grid TEXT`, `qth TEXT`, `lat REAL`, `lon REAL`, `source TEXT NOT NULL CHECK (source IN ('saved','roster'))`, `notes TEXT NOT NULL DEFAULT ''`, `updated_at TEXT NOT NULL` |
| `net` | `name TEXT NOT NULL UNIQUE`, `weekday INTEGER CHECK (weekday BETWEEN 0 AND 6)`, `start_time TEXT`, `timezone TEXT`, `frequency_mhz REAL`, `channel TEXT`, `mode TEXT`, `band TEXT`, `default_controller_call TEXT`, `default_controller_grid TEXT`, `archived INTEGER NOT NULL DEFAULT 0` |
| `session` | `net_id INTEGER NOT NULL REFERENCES net(id) ON DELETE RESTRICT`, `date TEXT NOT NULL`, `controller_call TEXT`, `controller_grid TEXT`, `status TEXT NOT NULL CHECK (status IN ('active','closed','imported'))`, `raw_text TEXT`, `created_at TEXT NOT NULL` |
| `checkin` | `session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE RESTRICT`, `sequence INTEGER`, `logged_at TEXT`, `callsign TEXT NOT NULL`, `name TEXT`, `grid TEXT`, `qth TEXT`, `report TEXT`, `notes TEXT`, `published_bearing TEXT`, `heard_state TEXT CHECK (heard_state IN ('heard','weak','not_heard','relay'))`, `relay_call TEXT` |

Plus indexes `checkin(session_id)`, `checkin(callsign)`, `session(net_id, date)`, and a partial unique index allowing at most one active profile: `CREATE UNIQUE INDEX one_active_profile ON operator_profile(is_active) WHERE is_active = 1`.

- [ ] **Step 1: Write the failing tests.**
  - `test_new_database_is_at_schema_version`: `open_db(":memory:")` → `PRAGMA user_version` == `SCHEMA_VERSION` == 1; tables `operator_profile, alias, station, net, session, checkin` exist; `PRAGMA foreign_keys` == 1.
  - `test_reopen_does_not_rerun_migrations` (Review Focus 3): `open_db(tmp_path/"b.db")`, insert an alias row, close; reopen → row present, `user_version` still 1.
  - `test_migrations_apply_in_order_and_only_once`: `migrate(conn, [(1, "CREATE TABLE a(x)"), (2, "CREATE TABLE b(x)")])` twice → `user_version` 2, no error.
  - `test_failed_migration_rolls_back`: `migrate(conn, [(1, "CREATE TABLE a(x)"), (2, "CREATE TABLE b(x); SYNTAX ERROR")])` raises `MigrationError` naming migration 2; table `b` does not exist; `user_version` == 1.
  - `test_newer_database_is_refused`: set `user_version` to 99 → `open_db` raises `MigrationError` containing "newer".
  - `test_migration_files_are_numbered`: every file in the packaged migrations folder matches `^\d{4}_[a-z0-9_]+\.sql$`, numbers start at 1 with no gaps.
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_store_db.py -v`. Expected: FAIL, `ModuleNotFoundError`.
- [ ] **Step 3:** Implement. Each pending migration runs as one transaction: `conn.executescript(f"BEGIN; {sql}; PRAGMA user_version = {n}; COMMIT;")`; on `sqlite3.Error`, `conn.rollback()` and raise `MigrationError(f"Migration {n} failed: {exc}")`. Packaged files are read with `importlib.resources.files("beam_navigator.store") / "migrations"`.
- [ ] **Step 4:** Run tests, `uv run ruff check .`, `uv run mypy src/beam_navigator`. Expected: PASS.
- [ ] **Step 5:** Commit `feat: SQLite store with numbered migrations`.

---

### Task 2: Domain models, operator profiles and aliases

**Files:**
- Modify: `src/beam_navigator/core/models.py`, `src/beam_navigator/core/targets.py`
- Create: `src/beam_navigator/store/repositories.py`
- Test: `tests/unit/test_targets.py`, `tests/unit/test_store_profiles_aliases.py`

**Interfaces:**
- Produces in `core/models.py`: `OperatorProfile(id: int | None, name: str, callsign: str | None, home_grid: str, latlon: LatLon | None, units: Literal["km","mi"], timezone: str, home_region: str | None, is_active: bool)`.
- Produces in `core/targets.py`:
  - `builtin_meaning(name: str) -> str | None` — `"heading"`, `"compass point"`, `"grid"`, `"state or province"` or `"callsign"` if `resolve` would read `name` that way without aliases; else `None`.
  - `validate_alias(name: str, target: AliasTarget) -> AliasTarget` — returns the cleaned target (upper-cased name is the caller's; value stripped, trailing `°` removed for headings, callsign normalized for stations) or raises `TargetError`: name empty or containing `:` or whitespace; `builtin_meaning(name)` not `None` (message names the meaning, decision 12); value that does not resolve as its kind (heading out of range, bad grid, coords off Earth, station value not a callsign).
- Produces in `store/repositories.py`:
  - `ProfileRepository(conn)`: `save(profile: OperatorProfile) -> OperatorProfile` (insert or update by id; validates `home_grid` with `grid_center`, `home_region` against `load_regions()`, raising `ValueError`), `get_active() -> OperatorProfile | None`, `activate(profile_id: int) -> None` (deactivates the others in one transaction), `list() -> list[OperatorProfile]`.
  - `AliasRepository(conn)`: `save(name: str, target: AliasTarget) -> None` (upper-cases name, calls `validate_alias`, insert or replace), `delete(name: str) -> None`, `get(name: str) -> AliasTarget | None` (signature matches `AliasLookup`), `list() -> list[tuple[str, AliasTarget]]`.

- [ ] **Step 1: Write the failing tests.**
  - In `test_targets.py`: `builtin_meaning` returns `"compass point"` for `NE`, `"state or province"` for `NC`, `"grid"` for `FN20`, `"heading"` for `247`, `"callsign"` for `W2KV`, `None` for `CLUB` and `BEACON2M`. `validate_alias("CLUB", AliasTarget("grid", " FM29jw "))` → `AliasTarget("grid", "FM29jw")`; `validate_alias("B", AliasTarget("heading", " 90° "))` → value `"90"`; `TargetError` for names `NC`, `N`, `W2KV`, `"MY CLUB"`, `"st:X"`, `""` and for values heading `"400"`, grid `"ZZ99"`, coords `"95,400"`, station `"hello world"`.
  - In `test_store_profiles_aliases.py`: acceptance 10 through the store — `AliasRepository(conn).save("club", AliasTarget("grid", "FM29jw"))`, then `resolve("CLUB", aliases=repo.get).location == resolve("FM29jw").location`. Saving `NC` raises `TargetError`. `activate` leaves exactly one active profile; `get_active().home_region == "NJ"` after saving one with `home_region="nj"` (stored upper-case). Saving `home_grid="ZZ99"` or `home_region="XX"` raises `ValueError`. New database → `get_active() is None` (invariant 10).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. `builtin_meaning` calls the resolver's private matchers in the same order as `resolve`, so the two can never disagree.
- [ ] **Step 4:** Run the full suite, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: operator profiles and aliases in the store (acceptance 10, decision 12)`.

---

### Task 3: Stations

**Files:**
- Modify: `src/beam_navigator/core/models.py`, `src/beam_navigator/store/repositories.py`
- Test: `tests/unit/test_store_stations.py`

**Interfaces:**
- Produces in `core/models.py`: `Station(callsign: str, name: str | None, grid: str | None, qth: str | None, latlon: LatLon | None, source: Literal["saved","roster"], notes: str)`.
- Produces in `store/repositories.py` — `StationRepository(conn)`:
  - `get(callsign: str) -> Station | None` (normalizes the argument).
  - `save(station: Station) -> None` — explicit user save; insert or update every field; `source="saved"`.
  - `add_from_roster(callsign, name, grid, qth) -> bool` — inserts with `source="roster"` only if no record exists; returns whether it inserted. Never updates an existing record.
  - `set_notes(callsign: str, notes: str) -> None`.
  - `lookup(callsign: str) -> StationLocation | None` — matches `StationLookup`; `None` when the station is unknown.

- [ ] **Step 1: Write the failing tests.**
  - `save` then `get("n2lqh")` returns the record with callsign `N2LQH` (Review Focus 2).
  - `add_from_roster("K3WGR", "AL", "FN10xh", …)` → True; again with `"FN10xi"` → False and the saved grid is still `FN10xh` (spec 7: change no saved record silently).
  - `resolve("W2KV", stations=repo.lookup)` → location `grid_center("FN20ok")`, source `"saved"` after a `save`; `"roster"` after only `add_from_roster`.
  - Unknown station → `resolve(...).needs_grid` (invariant 5).
  - `Québec`, `José`, `"🙂 good copy"` round-trip through `save`/`set_notes`/`get` unchanged (Review Focus 5).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: station records feed the target resolver`.

---

### Task 4: Nets, sessions and roster import

**Files:**
- Modify: `src/beam_navigator/core/models.py`, `src/beam_navigator/store/repositories.py`
- Test: `tests/unit/test_store_nets.py`

**Interfaces:**
- Produces in `core/models.py`: `Net(id: int | None, name: str, weekday: int | None, start_time: str | None, timezone: str | None, frequency_mhz: float | None, channel: str | None, mode: str | None, band: str | None, default_controller_call: str | None, default_controller_grid: str | None, archived: bool)`; `Session(id: int, net_id: int, date: str, controller_call: str | None, controller_grid: str | None, status: Literal["active","closed","imported"], raw_text: str | None)`; `CheckIn(id: int, session_id: int, sequence: int | None, callsign: str, name: str | None, grid: str | None, qth: str | None, published_bearing: str | None)`.
- Produces in `store/repositories.py` — `NetRepository(conn)`:
  - `save_net(net: Net) -> Net`, `get_net(net_id: int) -> Net`, `delete_net(net_id: int) -> None` (raises `sqlite3.IntegrityError` when sessions exist).
  - `find_identical_import(net_id: int, date: str, raw_text: str) -> int | None` — session id of an earlier import for the same net and date whose raw text is the same after `_canonical(text)`: drop a leading `﻿`, `\r\n`→`\n`, strip trailing spaces on each line, strip the whole text.
  - `import_roster(net_id: int, date: str, raw_text: str, result: ParseResult, replace_session_id: int | None = None) -> Session` — validates `date` with `datetime.date.fromisoformat` (`ValueError` otherwise); in one transaction: deletes the replaced session's check-ins and session when `replace_session_id` is given, inserts a session with `status="imported"`, the raw text unchanged, `controller_call`/`controller_grid` from the tagged row; inserts one check-in per row with a callsign (snapshots of name, grid, QTH, published bearing, sequence); calls `StationRepository.add_from_roster` for each.
  - `checkins(session_id: int) -> list[CheckIn]` in sequence order.
  - `saved_grid_conflicts(result: ParseResult) -> dict[int, str]` — keyed by index into `result.rows`; a conflict when the row's grid and the saved station's grid differ case-insensitively over the length of the shorter one (`fm29` vs `FM29pt` agrees; `FN10xi` vs `FN10xh` conflicts): `"Saved grid FN10xh differs"`. Used by the review table before saving (spec 4.3).

- [ ] **Step 1: Write the failing tests** (nets created in the test; fixtures parsed with `parse_roster`).
  - Import N3RG for 2026-10-26: session raw text equals the file text exactly; 22 check-ins; N3ITT's `published_bearing == "0°"`; controller `N3RG`/`FM29ki`.
  - Acceptance 13: `find_identical_import(net, "2026-10-26", same_text)` returns that session id; with the text converted to CRLF plus a BOM it still matches (Review Focus 1); a different date or different text returns `None`. `import_roster(..., replace_session_id=sid)` leaves exactly one session for that net and date; without it, two.
  - Cross-fixture (spec 7): import N3RG (50 MHz net) then W2KV (144 MHz net) for 2026-10-26. N2LQH has one station record and appears in two sessions. `saved_grid_conflicts(parse_roster(w2kv_text))` contains `"Saved grid FN10xh differs"` for the K3WGR row; the station record still says `FN10xh`; the W2KV check-in snapshot says `FN10xi`. AF3G's snapshots are `GLEN` and `GLENN`.
  - Snapshots: after `StationRepository.save` changes N2LQH's grid, the 50 MHz check-in still says `FM29pt` (spec 3).
  - `import_roster(..., date="Tuesday")` raises `ValueError`; nothing is written.
  - `delete_net` on a net with a session raises `sqlite3.IntegrityError`; the session is still there (Review Focus 4).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: nets, sessions and roster import with raw text (acceptance 13)`.

---

### Task 5: Expected participants and substitute controller

**Files:**
- Modify: `src/beam_navigator/core/models.py`, `src/beam_navigator/store/repositories.py`
- Test: `tests/unit/test_store_sessions.py`

**Interfaces:**
- Produces in `core/models.py`: `Participant(callsign: str, last_grid: str | None, sessions_attended: int, last_seen: str)`.
- Produces on `NetRepository`:
  - `start_session(net_id: int, date: str) -> Session` — `status="active"`, controller copied from the net default.
  - `participants(net_id: int) -> list[Participant]` — every callsign with a check-in in any session of the net; `last_grid` from the most recent session that had a grid.
  - `expected(session_id: int) -> list[Participant]` — participants of the session's net minus callsigns checked in to this session.
  - `set_session_controller(session_id: int, callsign: str | None, grid: str | None) -> None` — this session only.
  - `save_controller_as_default(session_id: int) -> None` — the explicit "Save as default" (spec 3).
  - `add_checkin(session_id: int, callsign: str, *, allow_duplicate: bool = False, **snapshot) -> CheckIn` — raises `DuplicateCheckIn(callsign, existing: CheckIn)` when the callsign is already in the session and `allow_duplicate` is false (spec 3 key rule).

- [ ] **Step 1: Write the failing tests.**
  - Acceptance 14: import W2KV for 2026-10-26, `start_session(net, "2026-11-02")` → `expected(sid)` has the 17 W2KV callsigns, `checkins(sid)` is empty; after `add_checkin(sid, "K4SO")`, `expected` has 16.
  - Acceptance 15: net default controller `W2KV`/`FN20ok`; session A imported, session B started; `set_session_controller(B, "N3RG", "FM29ki")` → net default unchanged, session A's controller unchanged, session B's is N3RG. `save_controller_as_default(B)` then changes the net default.
  - `add_checkin` twice with the same call raises `DuplicateCheckIn` whose `existing.sequence` is the first entry's; with `allow_duplicate=True` it adds a second.
  - `participants` for the W2KV net after two imports counts `sessions_attended == 2` for a station in both.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: expected participants and substitute controller (acceptance 14, 15)`.
