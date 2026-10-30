# Milestone 2b — Web UI Shell, Bearing Lookup and Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A NiceGUI app on `localhost` (`beamnav-ui`) with the bearing-lookup dashboard (spec 4.1) and the Settings screens (station, bands, aliases, rotators; spec 4.8), including a Rotate button that sends exactly one command per press through the Milestone 2a service.

**Architecture:** Every decision lives outside `ui/`. A new `desk.py` joins `core`, `store` and `rotators` into what one screen needs: it resolves and looks up a target, picks the band's rotator, formats the text the dashboard shows, and calls `RotateService`. `ui/` files only build widgets and call `Desk`. Two rotator fixes deferred from Milestone 0 (decisions 7 and 8) land first, because this plan is the first one that can drive a live rotator from the app.

**Tech Stack:** Python 3.12+, NiceGUI 3.18 (already a dependency), `sqlite3`, `platformdirs`. Dev only: **`pytest-asyncio` (new; needs the owner's approval before Task 6)** for NiceGUI's simulated-user test fixture.

**Spec:** `docs/requirements.md` v2.0 — invariants 1–8; sections 4.1, 4.2, 4.7, 4.8, 8; section 7 tests 2, 7–10, 25–28, 32. `docs/decisions.md` 7, 8, 10, 15–17. `docs/rotator-notes.md`.

**Out of scope (later plans):** roster import screen and live net (2c), hotkeys including the Rotate hotkey (2c, with the number-pad sector keys), LAN access and PIN, pywebview, backup and export (Milestone 4).

## Design

**Bands are data.** Migration 0003 adds a `band` table: `name`, nominal `mhz` and `long_path`. It is seeded with 10 m (28, long path on), 6 m (50, long path on), 2 m (144), 1.25 m (222), 70 cm (432), 33 cm (902) and 23 cm (1296). The nominal MHz feeds the coarse-location note (1296 and up). The operator can add bands (microwave), delete them, and toggle long path. A rotator's `bands` must name rows in this table, and each band is served by at most one rotator. That rotator is the band's default, so the band → rotator map has one source. The dashboard can still pick any rotator before Rotate (spec 4.7).

**One small settings table.** Migration 0003 also adds `setting(key, value)` for the dashboard's selected band and selected rotator. NiceGUI's `app.storage` is not used, because it writes outside the platform data directory.

**Planned move before the press.** `RotateService` remembers the last rotor position it read for each rotator (before a move, after a move, or from an explicit **Read position** press). `preview()` uses that position, so the dashboard can show direction, long way and estimated time. With no known position it says the path is unverified. A preview for PstRotatorAz states no direction (decision 15).

**Labels never overstate.** The Rotate button reads `Rotate VHF to 294.6°`. When that rotator is not live it reads `Rotate VHF to 294.6° (simulated)`, and the status line says so too. Moving the simulator must never look like moving the antenna.

**Rotator I/O runs on NiceGUI's event loop.** One `sqlite3` connection is used from one thread. A rotator call blocks for at most the adapter timeout (2 s). This is recorded as a decision, and a worker thread can come later if it matters.

**Progress after a press.** With feedback, the dashboard polls `read_position` once a second. It shows commanded and measured separately and stops when within 0.5° of the target, on a read error (reported, not retried), or after the estimate plus 30 s (90 s with no estimate). Without feedback it shows elapsed time against the estimate and "position unverified". Polling only reads; it never sends a move.

## Global Constraints

- **No movement without an explicit press** (invariant 2). Only a click on the Rotate or Stop button reaches `RotateService.rotate()` or `stop()`. Typing, Enter, choosing a band or rotator, saving any setting, Test connection, Read position and progress polling send no move.
- **Simulation by default** (invariant 8). The Live switch is disabled until Test connection passes, and editing host, port or adapter turns it off again (the repository already enforces this).
- **Truthful status** (invariant 6). Without feedback the status contains exactly `Command sent — position unverified`.
- **Never invent a location** (invariant 5). Unknown grid shows `Grid needed`. Every result shows its source.
- **Offline** (invariant 1). No CDN or network fetch. The UI binds `127.0.0.1` only, and LAN access stays off.
- `ui/` files hold no business logic: no geometry, no formatting rules, no rotator decisions. If a `ui/` test would need to check a computed value, that value belongs in `desk.py`.
- **UI tests never reach a real rotator.** Every UI test injects simulation or fake adapters through `Desk`/`RotateService` (`adapter_for` and `tester_for`), as in `tests/unit/test_rotate_service.py`.
- Runtime dependencies stay NiceGUI and platformdirs.
- Data directory: `platformdirs.user_data_dir("beam-navigator", appauthor=False)`, database file `beamnav.db`. `--data-dir` overrides it.
- Match the existing code: 4-space indentation, line length 100, `ruff`, `mypy --strict` on `src/beam_navigator`.

## Review Focus

1. **Rotator not live.** The button and status say `(simulated)`, and nothing implies the antenna moved. Tests in Tasks 5 and 7.
2. **No active station profile** (first run). The lookup says `Set up your station first: Settings → Station.` and does not crash. Test in Task 5.
3. **PstRotatorAz preview.** The preview never states a direction (2a's `preview()` ignored `chooses_path`). Test in Task 4.
4. **Band deleted or renamed while a rotator serves it.** This is refused with the rotator's name. Test in Task 3.
5. **Garbage in the lookup box** (1 MB of text, control characters, an invalid typed grid). This gives an error line, no crash, and nothing saved. Tests in Task 5.

---

### Task 1: PstRotator accepts replies only from the rotator (decision 7)

**Files:**
- Modify: `src/beam_navigator/rotators/pstrotator.py` (`_await_azimuth`)
- Test: `tests/unit/test_pstrotator.py`
- Modify: `docs/decisions.md` (mark 7 resolved)

**Interfaces:**
- Produces: `accepted_senders(host: str) -> frozenset[str]` (module function).
  - For a host that resolves to a loopback address, the set holds `127.0.0.1` plus every IPv4 address from `socket.gethostbyname_ex(socket.gethostname())[2]`, because PstRotatorAz replies from the LAN address (decision 9).
  - Otherwise it holds the resolved host address.
  - Resolution errors are raised as `RotatorError`.

- [ ] **Step 1: Write the failing tests.**
  - `test_reply_from_another_host_is_ignored`: configure the adapter's host as `192.0.2.1` (TEST-NET; the send goes nowhere), then deliver `AZ:85\r` to the reply port from `127.0.0.1`. `get_position` raises `RotatorError` matching `Not retried`.
  - `test_loopback_host_accepts_lan_sender`: `accepted_senders("127.0.0.1")` contains `lan_address()` and `127.0.0.1`.
  - The existing `test_reads_reply_sent_to_lan_address` must still pass.
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_pstrotator.py -v`. Expected: the new rejection test FAILS (the reply is accepted), and `accepted_senders` raises ImportError.
- [ ] **Step 3:** Implement. `_await_azimuth` skips datagrams whose sender IP is not in `accepted_senders(self.host)`, computed once per `get_position`. A skipped datagram is not recorded in `last_reply`.
- [ ] **Step 4:** Run the file, `uv run ruff check .` and `uv run mypy src/beam_navigator`. Expected: PASS.
- [ ] **Step 5:** In `docs/decisions.md`, append `**Resolved 2026-10-28 (plan 2b Task 1).**` to decision 7. Commit `fix: PstRotator accepts position replies only from the rotator (decision 7)`.

### Task 2: Hamlib never reads a late reply as the next answer (decision 8)

**Files:**
- Modify: `src/beam_navigator/rotators/hamlib.py`
- Test: `tests/unit/test_hamlib.py`
- Modify: `docs/decisions.md` (mark 8 resolved)

**Interfaces:**
- Behaviour only. After any timeout or `OSError`, the adapter closes its socket and clears `_buffer`. The next `_send` opens a fresh connection; that is a reconnect, not a resend of the failed command. The `assert` in `_read_line` becomes `raise OSError("Not connected.")` (Milestone 0 nit, same lines).

- [ ] **Step 1: Write the failing test.** `test_late_reply_is_not_read_as_next_answer`: a fake `rotctld` on loopback answers the first `p` only after the adapter's timeout (`timeout_s=0.2`; it replies `350.0\n0.0\n` after 0.4 s), then answers every later connection's `p` with `90.0\n0.0\n`. The first `get_position()` raises `RotatorError` (`Not retried`). The second returns `90.0`, not `350.0`. The fake server records two connections.
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_hamlib.py -v`. Expected: FAIL, the second read returns 350.0.
- [ ] **Step 3:** Implement as in Interfaces.
- [ ] **Step 4:** Run the file, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Mark decision 8 resolved, as in Task 1. Commit `fix: Hamlib reconnects after a timeout so a late reply is never misread (decision 8)`.

### Task 3: Bands and settings in the store

**Files:**
- Create: `src/beam_navigator/store/migrations/0003_bands_settings.sql`
- Modify: `src/beam_navigator/core/models.py` (add `Band`)
- Modify: `src/beam_navigator/store/repositories.py` (`BandRepository`, `SettingRepository`, band rules in `RotatorRepository.save`)
- Test: `tests/unit/test_store_bands.py`; update `test_store_rotators.py::test_version_1_database_upgrades` (expects version 3)

**Interfaces:**
- Produces:
  - `Band(name: str, mhz: float, long_path: bool)`, a frozen dataclass.
  - `BandRepository(conn)` with:
    - `list() -> list[Band]` (ordered by `mhz`)
    - `get(name) -> Band | None`
    - `add(name: str, mhz: float) -> Band`
    - `set_long_path(name: str, on: bool) -> None`
    - `delete(name: str) -> None`
    - `rotator_for(name: str) -> RotatorProfile | None`
  - `SettingRepository(conn)` with `get(key: str) -> str | None` and `set(key: str, value: str | None) -> None` (None deletes).
  - Seed rows exactly as in **Design**.
- Rules:
  - A band name is unique and non-blank, and `mhz` is finite and > 0.
  - `delete` of a band a rotator serves raises `ValueError` naming that rotator: `"2 m is served by VHF; remove it from that rotator first."`
  - `RotatorRepository.save` raises `ValueError` for a band not in the table (`"Unknown band '3 m'."`) and for a band another rotator serves (`"2 m is already served by HF beam."`).

- [ ] **Step 1: Write the failing tests** in `test_store_bands.py`:
  - `test_seeded_bands`: the names in order and the long-path flags (only 10 m and 6 m on).
  - `test_add_and_toggle_long_path`
  - `test_bad_band_rejected`: blank name, `mhz` 0, NaN, a duplicate.
  - `test_band_in_use_cannot_be_deleted` (Focus 4)
  - `test_rotator_band_must_exist`
  - `test_band_served_by_one_rotator`
  - `test_rotator_for_band`
  - `test_setting_round_trip_and_delete`
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_store_bands.py tests/unit/test_store_rotators.py -v`. Expected: FAIL (ImportError; version 2 ≠ 3).
- [ ] **Step 3:** Implement the migration (`band` with `name TEXT NOT NULL UNIQUE`, `mhz REAL NOT NULL CHECK (mhz > 0)`, `long_path INTEGER NOT NULL DEFAULT 0`; `setting` with `key TEXT PRIMARY KEY`, `value TEXT NOT NULL`) and the repositories.
- [ ] **Step 4:** Run the whole suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Add decision 18 to `docs/decisions.md`: bands are a table with nominal MHz, each band is served by at most one rotator, and that rotator is its default. Commit `feat: band table and app settings in the store (spec 4.7, 4.8)`.

### Task 4: RotateService remembers position; truthful preview

**Files:**
- Modify: `src/beam_navigator/rotators/service.py`
- Test: `tests/unit/test_rotate_service.py`

**Interfaces:**
- Produces:
  - `PositionReading(rotor: float | None, true: float | None, message: str)`, a frozen dataclass.
  - `RotateService.read_position(rotator_id: int) -> PositionReading` connects, reads once and disconnects through the cached adapter. It never moves. A `RotatorError` becomes `PositionReading(None, None, str(exc))`, and a rotator without feedback gives the message `"This rotator does not report its position."`. A successful read updates the remembered position.
  - `RotateService.last_rotor(rotator_id: int) -> float | None`.
  - `RotateService.capabilities(rotator_id: int) -> Capabilities` (cached adapter; no connect).
  - `RotateService.test_move(rotator_id: int, target_true: float) -> RotateOutcome` runs on a fresh `SimulationAdapter` built from the profile's travel and speed, starting at the remembered position or `az_min`. It is never logged and never touches the cached adapter ("Test move in simulation", spec 4.8).
  - `preview(rotator_id, target_true, current_rotor=None)`: with `current_rotor` None, use `last_rotor(rotator_id)`. Pass `adapter_chooses_path=True` when `profile.adapter == "pstrotator"`.
  - `rotate()` stores the rotor position it read before planning, and the raw rotor reading after the move when one comes back.

- [ ] **Step 1: Write the failing tests.**
  - `test_preview_uses_last_known_position`: simulation, rotate to 90, then `preview(r, 100)` has `rotor_from == 90` and direction clockwise.
  - `test_preview_pstrotator_states_no_direction` (Focus 3): a pstrotator profile on 0–450, `preview(r, 30, current_rotor=40)` gives direction None and `path_verified` False; no adapter is built.
  - `test_read_position_never_moves`: `FakeAdapter`; `moves == []`; the reading is remembered.
  - `test_read_position_error_reported`: `FakeAdapter(fail_read_after_move=True)` after a move gives `rotor` None and a message containing `Not retried`.
  - `test_test_move_touches_only_a_throwaway_simulator`: a pstrotator profile with `adapter_for` refusing (raising) gives `outcome.sent`, and `CommandLog(conn).recent(r) == []`.
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_rotate_service.py -v`. Expected: the five new tests FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the whole suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Add decision 19 (the preview uses the last position read this session; unknown means unverified) and decision 20 (rotator I/O on the event loop, up to 2 s; see **Design**). Commit `feat: rotate service remembers position, read and test-move without moving`.

### Task 5: Desk — what the dashboard shows

**Files:**
- Create: `src/beam_navigator/desk.py`
- Test: `tests/unit/test_desk.py`

**Interfaces:**
- Consumes: `resolve`, `lookup`, `ProfileRepository`, `AliasRepository`, `StationRepository`, `BandRepository`, `SettingRepository`, `RotatorRepository`, `RotateService` (Task 4).
- Produces:
  - `LookupView`, a frozen dataclass:
    - `title: str`: the resolved label and its source, `f"{label} — {source}"`
    - `bearing_deg: float | None`
    - `bearing_text: str | None`: `"294.6° WNW"`
    - `distance_text: str | None`: the profile's units; `"{:,.0f} km"` (or `mi`) at 10 or more, one decimal below 10; miles = km / 1.609344
    - `reverse_text: str | None`
    - `long_path_text: str | None`: `"Long path 114.6° · 38,000 km"`
    - `message: str | None`: `Grid needed`, `Home`, `You are in NJ`
    - `coarse_note: str | None`
    - `alternative: str | None`: the forced input, e.g. `"st:NE"`
    - `alternative_label: str | None`: `"Nebraska?"`, using the region name
    - `needs_grid_for: str | None`: the callsign whose grid is missing
    - `can_rotate: bool`
    - `error: str | None`
  - `Desk(conn: sqlite3.Connection, service: RotateService)` with:
    - `look_up(text: str, band: str | None) -> LookupView`. It catches `TargetError` and `GridError` into `error`. With no active profile it gives `error="Set up your station first: Settings → Station."`. Long path follows the band's flag, and the band's `mhz` feeds the coarse note.
    - `look_up_with_grid(callsign: str, grid: str, band: str | None) -> LookupView`: source `typed`; saves nothing.
    - `save_station_grid(callsign: str, grid: str) -> None`: validates the grid first, keeps the existing name, QTH and notes, and clears lat/lon (they described the old location).
    - `selected_band() -> str | None`: the stored setting if that band still exists, else `2 m` if present, else the first band.
    - `select_band(name: str) -> None`.
    - `rotators() -> list[RotatorProfile]`.
    - `default_rotator(band: str | None) -> RotatorProfile | None`.
    - `rotate_label(rotator: RotatorProfile, bearing_deg: float) -> str`: `"Rotate VHF to 294.6°"`, plus `" (simulated)"` when not live.
    - `plan_text(rotator_id: int, bearing_deg: float) -> str`: from `service.preview`, e.g. `"Clockwise 20.0° · about 3 s"`, `"Long way round: counter-clockwise 340.0°"`, `"Path unverified (position unknown)"`, or the plan's note or error.
    - `rotate(rotator_id: int, label: str, bearing_deg: float) -> RotateOutcome`: one call to `service.rotate`. When the rotator is not live, the returned status is prefixed with `Simulated: `.
  - `progress_text(outcome: RotateOutcome, elapsed_s: float, reading: PositionReading | None) -> tuple[str, bool]`: the status text and whether polling should stop, as in **Design**.

- [ ] **Step 1: Write the failing tests** (profile `FM29pt`, units `mi`, home region `NJ`; a simulation rotator `VHF` serving `2 m`, injected through `RotateService(conn, adapter_for=..., tester_for=...)` with a `SimulationAdapter`):
  - `test_grid_lookup_text`: `FN20ok` gives a bearing within 0.5° of `lookup()`'s, `bearing_text` ending in `" N"`, the distance in `mi`, and `can_rotate`.
  - `test_home_disables_rotate` (acceptance 2): `FM29pt` gives message `Home` and `can_rotate` False.
  - `test_in_region` (acceptance 8): `NJ` gives `You are in NJ` and `can_rotate` False.
  - `test_ne_offers_nebraska` (acceptance 9): `NE` gives bearing 45, `alternative == "st:NE"` and `alternative_label == "Nebraska?"`.
  - `test_alias_same_as_grid` (acceptance 10).
  - `test_unknown_callsign_needs_grid`: `W2KV` with no record gives `Grid needed` and `needs_grid_for == "W2KV"`; `look_up_with_grid` gives source `typed`, and the station table is unchanged.
  - `test_save_station_grid_keeps_name`; `test_save_station_grid_rejects_bad_grid` (Focus 5): `ZZ99` raises and nothing is saved.
  - `test_no_profile` (Focus 2).
  - `test_garbage_input` (Focus 5): 1 MB of `"x"`, and `"\x00\x01"`, each give `error` set and no exception.
  - `test_long_path_follows_band`: 6 m on, 2 m off; 23 cm and `FN20` give the coarse note.
  - `test_rotate_label_simulated` (Focus 1).
  - `test_lookup_and_band_choice_send_nothing` (acceptance 26): a `look_up` of 5 inputs, `select_band`, `plan_text` and `default_rotator` give `sim.commands == []`; then `rotate` gives exactly 1.
  - `test_progress_text`: feedback arriving (within 0.5°, stop), still moving (continue), a read error (stop, message shown), no feedback (`position unverified`, elapsed against estimate), and past the time limit (stop).
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_desk.py -v`. Expected: FAIL, ImportError.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the whole suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: desk joins lookup, bands and rotate for the dashboard (acceptance 2, 8-10, 26)`.

### Task 6: App shell and dashboard page

**Prerequisite:** the owner has approved adding `pytest-asyncio` as a dev dependency (`uv add --dev pytest-asyncio`). Without approval, stop here.

**Files:**
- Create:
  - `src/beam_navigator/ui/__init__.py`
  - `src/beam_navigator/ui/app.py`
  - `src/beam_navigator/ui/lookup.py`
  - `tests/conftest.py`
  - `tests/ui/test_dashboard.py`
- Modify:
  - `pyproject.toml`: the `beamnav-ui = "beam_navigator.ui.app:main"` script; `[tool.pytest.ini_options]` `asyncio_mode = "auto"` and `main_file = ""`; the dev dependency
  - `uv.lock`

**Interfaces:**
- Produces:
  - `ui.app.register_pages(desk_factory: Callable[[], Desk]) -> None`: defines `/` (dashboard) and `/settings` (Task 7 fills it). The header links Dashboard and Settings.
  - `ui.app.main(argv: list[str] | None = None) -> None`: takes `--data-dir PATH` and `--port INT` (default 8080). It opens the database in the data directory, creates the directory if needed, and runs `ui.run(host="127.0.0.1", port=..., reload=False, title="Beam Navigator", show=True)`.
  - `ui.lookup.dashboard(desk: Desk) -> None` builds the page.
  - `tests/conftest.py`: `pytest_plugins = ["nicegui.testing.user_plugin"]`.
- **Dashboard contents** (all text from `Desk`):
  - one large target input (Enter looks up)
  - a band select
  - a result card: the title, the bearing in large type, distance, reverse, long path, coarse note, message
  - an alternative button that looks up `alternative`
  - when `needs_grid_for` is set: an inline grid field, a **Use grid** button, then a **Save grid to W2KV** button (asked, not automatic)
  - a rotator select (default from `default_rotator`)
  - the plan line
  - the **Rotate** button labelled by `rotate_label`, disabled when `can_rotate` is False or there is no rotator
  - **Read position**
  - **Stop**, only when `capabilities(...).has_stop`, with the caption `Stop does not replace the controller's physical stop.`
  - a status line updated by a `ui.timer(1.0)` using `progress_text`; it is deactivated when that returns stop

- [ ] **Step 1: Write the failing tests** (`tests/ui/test_dashboard.py`; each test builds a `Desk` on an in-memory DB with a seeded profile and a simulation rotator, calls `register_pages(lambda: desk)`, then `await user.open("/")`):
  - `test_lookup_shows_bearing`: type `FN20ok` and press Enter; `await user.should_see("354.")` and see `mi`.
  - `test_home_disables_rotate` (acceptance 2): the Rotate button is disabled.
  - `test_typing_and_band_change_send_nothing` (acceptance 26): look up 3 targets and change the band; `sim.commands == []`. One click on Rotate gives exactly 1.
  - `test_simulated_label` (Focus 1): the button text ends in `(simulated)`.
  - `test_grid_needed_flow`: `W2KV` shows `Grid needed`; enter `FN20ok` and **Use grid** to see a bearing; the station table is still empty until **Save grid to W2KV** is clicked.
- [ ] **Step 2:** Run `uv run pytest tests/ui -v`. Expected: FAIL, ImportError.
- [ ] **Step 3:** Implement. Pages read `desk_factory()` per page build. The timer is created per press and cancelled on stop.
- [ ] **Step 4:** Run the whole suite, ruff and mypy. Expected: PASS. Then start it by hand: `uv run beamnav-ui --data-dir <scratch dir>` opens the dashboard in a browser, with no console errors and an empty database showing the set-up message. **Do not configure a pstrotator or hamlib rotator during this check.**
- [ ] **Step 5:** Commit `feat: beamnav-ui app shell and bearing-lookup dashboard (spec 4.1)`.

### Task 7: Settings — station, bands, aliases, rotators

**Files:**
- Create: `src/beam_navigator/ui/settings.py`
- Test: `tests/ui/test_settings.py`
- Modify: `src/beam_navigator/ui/app.py` (`/settings` calls `settings_page(desk)`)
- Modify: `src/beam_navigator/desk.py`: thin pass-throughs only if a screen needs one; each gets a unit test in `test_desk.py`

**Interfaces:**
- Produces: `ui.settings.settings_page(desk: Desk) -> None`, with four tabs:
  - **Station:**
    - the profile list with Activate
    - an add/edit form: name, callsign, grid, optional lat/lon, units km/mi, timezone, home region
    - repository `ValueError` text shown inline, nothing saved
  - **Bands:**
    - a table with a long-path switch per band
    - add a band (name, MHz)
    - delete, showing the refusal text from Task 3
  - **Aliases:**
    - the list
    - add (name, kind, value), with `validate_alias` errors shown inline
    - delete
  - **Rotators:**
    - the list showing the mode (`Simulation`/`Live`) for each profile
    - an add/edit form: name, adapter, host, port, a travel preset select from `PRESETS` that fills min/max, editable min/max, offset, speed, and band checkboxes from the band table
    - **Test connection**, showing the result message
    - a **Live** switch, disabled until `connection_tested` (acceptance 25), and when on, labelled `Live: Rotate turns the real antenna`
    - **Test move in simulation** with a heading field (Task 4 `test_move`)
    - the last 10 entries of `CommandLog.recent`

- [ ] **Step 1: Write the failing tests** (`tests/ui/test_settings.py`, the same fixture style; the rotator tests inject a `tester_for` that returns a `FakeAdapter`-style object so nothing reaches the network):
  - `test_add_station_profile`: save `FM29pt` and activate it; the dashboard lookup now works.
  - `test_bad_grid_shown_not_saved` (Focus 5).
  - `test_live_switch_needs_test` (acceptance 25): a new pstrotator profile at `127.0.0.1:12000` has Live disabled. After Test connection passes on the fake, Live is enabled. Editing the port disables it again. No move is ever sent (`fake.moves == []`).
  - `test_test_move_in_simulation`: it shows the simulated outcome; the command log is empty.
  - `test_band_long_path_toggle` and `test_delete_band_in_use_refused` (Focus 4).
  - `test_alias_round_trip`: add `CLUB` → `FM29jw`; the dashboard lookup of `CLUB` equals `FM29jw`.
- [ ] **Step 2:** Run `uv run pytest tests/ui/test_settings.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the whole suite, ruff and mypy. Expected: PASS. Run `beamnav-ui` by hand against a scratch data directory and click through each tab, using simulation rotators only.
- [ ] **Step 5:** Update the `uv run beamnav-ui` line in `CLAUDE.md`'s Commands block only if it differs from the real entry point. Add decision 21 to `docs/decisions.md`: hotkeys, including the Rotate hotkey, arrive with plan 2c. Commit `feat: settings screens for station, bands, aliases and rotators (spec 4.8, acceptance 25)`.
