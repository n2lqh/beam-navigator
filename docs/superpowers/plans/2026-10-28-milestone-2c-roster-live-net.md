# Milestone 2c — Roster Import and Live Net Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The operator can paste a net roster, review it with bearings from their own station, save it, and follow the net on a live screen. The live screen has the controller row, the announced-sector banner, heard states, a substitute controller, Follow/Snap back and keyboard hotkeys. That completes Milestone 2.

**Architecture:** As in 2b, every rule lives outside `ui/`.
- `core/sector.py` (pure) decides whether an announced sector is the operator's.
- `roster_review.py` turns a parse into editable review rows and saves them.
- `live_net.py` builds everything the live screen shows and chooses what Rotate points at.
- Rotate still goes only through `Desk.rotate`.
- `ui/roster.py` and `ui/live_net.py` only render and call these.

**Tech Stack:** Python 3.12+, NiceGUI 3.18, `sqlite3`. No new dependencies.

**Spec:** `docs/requirements.md` v2.0 — invariants 2, 3, 5, 6, 9, 10; sections 4.3, 4.4; section 7 fixtures and tests 11–18. `docs/decisions.md` 13, 14, 18–21.

**Out of scope (Milestone 3):** the net controller entry line (4.5), the full nets list and history screens with archive and `*.beamnet.json` (4.6), export, and remapping hotkeys (4.8). This plan has only the net picker and session list that import and the live screen need.

## Design

**Hotkeys.** Keys are fixed in this plan; remapping comes in Milestone 3. Decision 22 records this.

| Key | Where | Action |
|---|---|---|
| `Ctrl+Enter` | dashboard, live net | Rotate to the displayed target (the explicit press, invariant 2) |
| `Home` | live net | Snap back to controller: target the controller and rotate, one press |
| Number pad `8 9 6 3 2 1 4 7` | live net | Announce sector N NE E SE S SW W NW |

- Hotkeys never act while a text field, select or textarea has focus. This uses NiceGUI `ui.keyboard`'s default ignore list.
- Hotkeys never act on auto-repeat (`e.action.repeat`), so holding a key sends at most one command.
- Number-pad keys match on `e.key.code` (`Numpad8` …), never on the digit, so the top-row digits do nothing.

**Controller location for the live screen** comes from the first source that gives one:
1. the session's controller grid (an import or a substitute);
2. the saved station record of the controller's callsign;
3. a manually measured bearing for tonight (substitute only). This gives **You → controller** but no **Controller → you**, so the sector check says it can't tell.
4. Otherwise it is unknown.

Controller → you is computed with `short_path(controller, user)`, never as reverse + 180 (spec 4.4).

**Check-in rows** use the check-in's own snapshot grid (spec 3: check-ins snapshot location). With no snapshot grid, the station record's grid is used and labelled `(saved)`. Otherwise the row shows `Grid needed`. A published bearing is shown only in its own **Published** column (invariant 3, acceptance 12).

**Target mode.** **Follow Controller** (the default) or **Follow Station**. In Follow Station, Rotate points at the selected row. Selecting a row, changing mode or announcing a sector sends nothing (acceptance 18). **Snap back** sets Follow Controller and calls `Desk.rotate` exactly once.

**Rotator on the live screen.** The net's band's default rotator (decision 18) is shown in the header with Simulation/Live and the last status. It can be changed before Rotate. A net with no band, or a band with no rotator, shows `No rotator for this band` and disables Rotate.

**Import review.** Paste or **Paste from clipboard** (`ui.clipboard.read()`), pick a net (or create one inline: name, band, frequency MHz or channel), and enter the date. The date defaults to today and is never derived from the text. The review table shows each parsed row with:
- **include**, sequence, callsign, and editable name, QTH and grid
- **Published**, **From you** and distance
- a controller choice
- warnings: the parser's, plus `saved_grid_conflicts`

Unparsed rows are shown with their text, cannot be included, and are kept in the stored raw text (invariant 9). The parser's controller is preselected only when the parser marked one. On **Save**, identical text for the same net and date asks **Replace**, **Keep both** or **Cancel** (acceptance 13).

## Global Constraints

- **No movement without an explicit press** (invariant 2). Only the Rotate button, `Ctrl+Enter`, the Snap back button and `Home` reach `Desk.rotate`, once per press. Import, Save, selecting rows, sorting, filtering, announcing sectors, heard states, substitute controller and mode changes send nothing.
- **Bearings are from the user's station** (invariant 3). Published bearings are display-only, in their own labelled column.
- **Never invent a location** (invariant 5). An unknown grid shows `Grid needed`; every bearing shows where its location came from.
- **Source data is never lost** (invariant 9). Raw roster text is stored with every imported session, including rows the operator excluded.
- Banner text is exactly `YOUR SECTOR IS UP`. Unknown text is exactly `Controller location unknown — can't tell if this call is for you.` Nothing claims the controller can hear the user.
- Fixture files in `tests/fixtures/` are read, never written (CLAUDE.md rule 4).
- **UI tests never reach a real rotator:** inject simulators as in `tests/ui/test_dashboard.py`.
- `ui/` holds no business logic. Match the existing code: 4-space indentation, line length 100, `ruff`, `mypy --strict` on `src/beam_navigator`.

## Review Focus

1. **A held key** (`Home` or `Ctrl+Enter` auto-repeat) gives exactly one rotate. Test in Task 7.
2. **A hotkey pressed while typing** in the filter or grid field (number-pad digits, `Home` moving the caret) gives no sector change and no rotate. Test in Task 7.
3. **Controller known only by a measured bearing.** You → controller is shown, Controller → you is unknown, and the sector check gives the can't-tell message. Test in Task 4.
4. **An edited grid in review is invalid or blank.** Save is refused naming the row, nothing is saved, and the raw text is not half-stored. Test in Task 3.
5. **A session for a net with no band, or a band without a rotator.** The live screen still works, and Rotate is disabled with the reason. Test in Task 4.

---

### Task 1: Store — heard state, measured controller bearing, session lists

**Files:**
- Create: `src/beam_navigator/store/migrations/0004_live_net.sql`
- Modify: `src/beam_navigator/core/models.py`
  - `CheckIn` gains `heard_state: str | None = None` and `relay_call: str | None = None`
  - `Session` gains `controller_bearing: float | None = None`
- Modify: `src/beam_navigator/store/repositories.py`
- Test: `tests/unit/test_store_live_net.py`; update the schema-version assertions (4) in `test_store_db.py`, `test_store_rotators.py`

**Interfaces:**
- Produces:
  - Migration: `ALTER TABLE session ADD COLUMN controller_bearing REAL CHECK (controller_bearing >= 0 AND controller_bearing < 360)`.
  - `NetRepository.set_session_controller(session_id, callsign, grid, bearing: float | None = None)`:
    - the grid, if given, must be a valid grid (`GridError`)
    - the bearing must be finite and 0–359.9 (`ValueError`)
    - the net default is unchanged (acceptance 15)
  - `NetRepository.set_heard(checkin_id: int, state: Literal["heard", "weak", "not_heard", "relay"] | None, relay_call: str | None = None) -> None`:
    - `relay` needs a valid callsign, normalized
    - any other state clears `relay_call`
  - `NetRepository.list_nets() -> list[Net]`: archived last, then by name.
  - `NetRepository.sessions(net_id: int) -> list[tuple[Session, int]]`: each session with its check-in count, newest date first.
  - `get_session` and `checkins` fill the new fields.

- [ ] **Step 1: Write the failing tests:**
  - `test_measured_bearing_substitute` (bearing 174.0 stored; net default unchanged)
  - `test_bad_substitute_rejected` (grid `ZZ99`; bearing 360, NaN)
  - `test_set_heard_and_relay` (relay without call raises; `relay` + `w2kv` stores `W2KV`; switching to `heard` clears it)
  - `test_list_nets_and_sessions` (two nets, an archived one last; session counts; newest first)
  - `test_acceptance_15_substitute_leaves_default`: import W2KV for 2026-10-26, start 2026-11-02, substitute `K2XYZ`/`FM29jw` on the new session; the net default and the 2026-10-26 session are unchanged.
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_store_live_net.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the whole suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: heard state, measured controller bearing and session lists in the store`.

### Task 2: Announced sector (pure core)

**Files:**
- Create: `src/beam_navigator/core/sector.py`
- Test: `tests/unit/test_sector.py`

**Interfaces:**
- Produces:
  - `SECTORS: dict[str, float]`: `N` 0, `NE` 45, `E` 90, `SE` 135, `S` 180, `SW` 225, `W` 270, `NW` 315.
  - `NUMPAD_SECTORS: dict[str, str]`: `Numpad8` N, `Numpad9` NE, `Numpad6` E, `Numpad3` SE, `Numpad2` S, `Numpad1` SW, `Numpad4` W, `Numpad7` NW.
  - `DEFAULT_TOLERANCE_DEG = 22.5`.
  - `SECTOR_UP = "YOUR SECTOR IS UP"`.
  - `CANT_TELL = "Controller location unknown — can't tell if this call is for you."`
  - `sector_name(bearing_deg: float) -> str`: 8-point.
  - `SectorCheck(up: bool | None, message: str)`.
  - `check_sector(announced: str, controller_to_user_deg: float | None, tolerance_deg: float = DEFAULT_TOLERANCE_DEG) -> SectorCheck`:
    - unknown location gives `up` None and `CANT_TELL`
    - within the tolerance (inclusive) gives `SECTOR_UP`
    - otherwise `f"Not your sector — you are {sector_name(x)} of the controller."`
    - an unknown sector raises `ValueError`

- [ ] **Step 1: Write the failing tests:**
  - `test_numpad_layout`
  - `test_acceptance_16`: controller → user 174.2 and announced `S` gives up True, message `SECTOR_UP`
  - `test_acceptance_17`: None, for every sector, gives up None and `CANT_TELL`
  - `test_boundary_is_inclusive`: 22.5 is in both N and NE
  - `test_wraps_north`: 350 is in N
  - `test_not_my_sector_message`
  - `test_banner_never_claims_hearing`: across every sector and position, no message contains `hear`; `SECTOR_UP` and `CANT_TELL` equal their exact strings
- [ ] **Step 2:** Run. Expected: FAIL (ImportError).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: announced-sector check (acceptance 16, 17)`.

### Task 3: Roster review service

**Files:**
- Create: `src/beam_navigator/roster_review.py`
- Test: `tests/unit/test_roster_review.py` (reads the fixtures; never writes them)

**Interfaces:**
- Consumes: `parse_roster`, `NetRepository` (`find_identical_import`, `import_roster`, `saved_grid_conflicts`), `Desk` (active profile, units, distance text via a new public `Desk.bearing_to(grid: str) -> tuple[float, str] | None`, which gives the bearing and distance text, or None when there is no profile or the grid is invalid).
- Produces:
  - `ReviewRow`, a mutable dataclass:
    - `index: int`, `line_text: str`, `sequence: int | None`, `callsign: str | None`
    - `name`, `qth`, `grid: str | None`
    - `published: str | None`, `include: bool`, `is_controller: bool`
    - `warnings: list[str]`
    - `from_you: str | None`: `"354.2° N"`
    - `distance: str | None`
  - `Review(raw_text: str, rows: list[ReviewRow], warnings: list[str], controller_suggested: bool)`.
  - `RosterReview(conn: sqlite3.Connection, desk: Desk)` with:
    - `parse(text: str) -> Review`:
      - unparsed rows have `include` False
      - the parser's warnings and stated-count mismatch are in `Review.warnings`
      - saved-grid conflicts are added to each row's warnings
    - `recompute(row: ReviewRow) -> None`: refreshes `from_you` and `distance` after a grid edit.
    - `set_controller(review: Review, index: int | None) -> None`: at most one controller.
    - `duplicate_of(net_id: int, date: str, review: Review) -> int | None`.
    - `save(net_id: int, date: str, review: Review, replace_session_id: int | None = None) -> Session`:
      - builds a `ParseResult` from the included rows with the edited values and `is_controller`, and stores the raw text unchanged
      - an included row with a callsign and a non-blank invalid grid raises `ValueError(f"Row {sequence or index}: {grid!r} is not a grid square.")` before anything is written
      - a blank grid is allowed and saved as missing

- [ ] **Step 1: Write the failing tests** (profile FM29pt; net "W2KV 2 m" with band `2 m`):
  - `test_w2kv_review`: 17 included rows; controller suggested W2KV; the stated-count warning (18 versus 17) is present; K3WGR grid `FN10xi`
  - `test_published_never_from_you` (acceptance 12, N3RG fixture): N2LQH's `published` equals the parser's value for that row, while its `from_you` is None (FM29pt is home). No row's `from_you` equals its `published`.
  - `test_unparsed_rows_kept_out_and_in_raw_text`
  - `test_edit_grid_recomputes`
  - `test_invalid_edited_grid_refused` (Focus 4): nothing is saved, `sessions(net) == []`
  - `test_excluded_row_not_saved_but_raw_text_kept`
  - `test_duplicate_detected_then_replace_or_keep` (acceptance 13): the second `duplicate_of` returns the first id; `save(..., replace_session_id=id)` leaves one session; saving without it leaves two
  - `test_activity_night_no_controller` (WA3NUF): `controller_suggested` False, no row is controller
  - `test_acceptance_14_expected_after_import`: save W2KV for 2026-10-26, `start_session` 2026-11-02, then `expected` has 17 and `checkins` is empty
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement, adding `Desk.bearing_to` with its own test in `test_desk.py`.
- [ ] **Step 4:** Run the suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: roster review with bearings from you, edits and replace-or-keep (acceptance 12-14)`.

### Task 4: Live net service

**Files:**
- Create: `src/beam_navigator/live_net.py`
- Test: `tests/unit/test_live_net.py`

**Interfaces:**
- Consumes: Task 1 store methods, Task 2 `check_sector`/`sector_name`, `Desk` (`bearing_to`, `rotate`, `default_rotator`, `rotate_label`).
- Produces:
  - `ControllerView`:
    - `callsign: str | None`
    - `source: str`: `session grid`, `saved`, `measured bearing` or `unknown`
    - `you_to_controller: str | None`: `"You → controller: 354.2°"`
    - `controller_to_you: str | None`: `"Controller → you: 174.2° (S)"`
    - `bearing_deg: float | None`
    - `controller_to_you_deg: float | None`
  - `NetRow`:
    - `checkin_id: int`, `sequence: int | None`, `callsign: str`, `name: str | None`
    - `grid_text: str`: the grid, `"FN20 (saved)"` or `"Grid needed"`
    - `bearing_deg: float | None`, `bearing_text: str | None`, `distance_km: float | None`, `distance_text: str | None`
    - `published: str | None`, `heard: str | None`, `relay_call: str | None`
  - `LiveNetView`:
    - `title: str`: the net name and date
    - `frequency: str`: `"144.245 MHz"`, the channel, or `""`
    - `controller: ControllerView`
    - `rows: list[NetRow]`, `expected: list[Participant]`
    - `rotator: RotatorProfile | None`
    - `rotate_reason: str | None`: `No rotator for this band`
  - `SortKey = Literal["roster", "bearing", "distance", "callsign"]`.
  - `sort_rows(rows, key: SortKey) -> list[NetRow]`: rows with no bearing or distance go last.
  - `filter_rows(rows, text: str) -> list[NetRow]`: case-insensitive over callsign, name and grid.
  - `LiveNet(conn: sqlite3.Connection, desk: Desk)` with:
    - `view(session_id: int) -> LiveNetView`
    - `announce(session_id: int, sector: str) -> SectorCheck`
    - `set_heard(...)` and `set_substitute(session_id, callsign: str | None, grid: str | None, bearing: float | None)`: pass-throughs; `set_substitute` validates that at least one is given
    - `target(session_id: int, mode: Literal["controller", "station"], checkin_id: int | None) -> tuple[str, float] | None`: the label and bearing Rotate would use, or None
    - `rotate(session_id: int, rotator_id: int, mode, checkin_id) -> RotateOutcome | None`: one `Desk.rotate` call, or None (nothing sent) when there is no target
    - `snap_back(session_id: int, rotator_id: int) -> RotateOutcome | None`: `rotate` with mode `controller`

- [ ] **Step 1: Write the failing tests** (profile FM29pt; W2KV fixture imported to a net with band `2 m`; a simulation rotator serving `2 m` injected through `RotateService`):
  - `test_controller_both_directions` (acceptance 16):
    - `you_to_controller` is about 354
    - `controller_to_you_deg` is within 0.01 of `short_path(grid_center("FN20OK"), grid_center("FM29pt")).bearing_deg`, ≈174, labelled `(S)`
    - `announce(..., "S").up` is True
  - `test_unknown_controller_cant_tell` (acceptance 17): the WA3NUF import has no controller; every sector gives `CANT_TELL`.
  - `test_measured_bearing_only` (Focus 3).
  - `test_rows_use_snapshot_then_saved_grid`.
  - `test_published_column_separate`: N3RG rows' `bearing_text` never equals their `published`.
  - `test_sort_and_filter`.
  - `test_nothing_sent_without_press` (acceptance 18): `view`, `announce` ×8, `set_heard`, `target` in both modes and `set_substitute` give `sim.commands == []`; then `snap_back` gives exactly 1.
  - `test_follow_station_targets_row`.
  - `test_no_rotator_for_band` (Focus 5): a net with band None gives `rotate_reason` set and `rotator` None.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: live net service — controller both ways, sector, follow and snap back (acceptance 16-18)`.

### Task 5: Import screen

**Files:**
- Create: `src/beam_navigator/ui/roster.py`
- Modify: `src/beam_navigator/ui/app.py`: the `/import` page; header links Dashboard, Import, Nets, Settings. `register_pages` builds `RosterReview` and `LiveNet` from the same `Desk`.
- Test: `tests/ui/test_import.py`

**Interfaces:**
- Produces: `ui.roster.import_page(review: RosterReview, nets: NetRepository) -> None`, laid out as in **Design**:
  - marks: `roster-text`, `net`, `date`, `parse`, `save`, `row-include-{index}`, `row-grid-{index}`, `row-controller-{index}`
  - a **New net** dialog with `net-name`, `net-band`, `net-frequency`, `net-channel`
  - after Save, the notification `Saved {n} check-ins` and an **Open live net** link to `/net/{session_id}`

- [ ] **Step 1: Write the failing tests:**
  - `test_import_w2kv`: paste the fixture text, pick the net, set the date, Parse; see `W2KV` and `FN10xi`; Save; see `Saved 17 check-ins`; the store has one session
  - `test_reimport_asks_replace_or_keep` (acceptance 13): a second Save of the same text shows `Replace`; clicking it leaves one session
  - `test_invalid_grid_edit_blocks_save` (Focus 4)
  - `test_import_sends_nothing`: a simulator records zero commands across the whole flow
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: roster import and review screen (spec 4.3)`.

### Task 6: Nets landing and live net screen

**Files:**
- Create: `src/beam_navigator/ui/live_net.py`
- Modify: `src/beam_navigator/ui/app.py`: the `/nets` and `/net/{session_id}` pages
- Test: `tests/ui/test_live_net.py`

**Interfaces:**
- Produces:
  - `ui.live_net.nets_page(nets: NetRepository) -> None`:
    - each net with its sessions (date, status, count, **Open**)
    - **Start session** with a date field, which calls `start_session` and opens it
    - **New net**, reusing the Task 5 dialog
  - `ui.live_net.live_net_page(live: LiveNet, session_id: int) -> None`:
    - **header:** title, frequency, controller callsign, and a rotator select with its Simulation/Live mode
    - **pinned controller row:** the two labelled values
    - **compass rose:** 8 buttons, marks `sector-N` … `sector-NW`
    - **banner:** mark `banner`; large; shows the `announce` message
    - **mode toggle:** `Follow Controller` / `Follow Station`, mark `mode`
    - **Rotate:** mark `rotate`, labelled by `Desk.rotate_label`
    - **Snap back to controller:** mark `snap-back`
    - **substitute controller:** a dialog with callsign, grid and bearing
    - **check-in table:** sortable (mark `sort`) and filterable (mark `filter`); row click selects; a heard-state select per row (mark `heard-{checkin_id}`), with a relay call field when `relay` is chosen
    - **Expected (not checked in):** a list below the table
    - **status line:** uses the 2b page-level timer pattern (`Desk.watch`)

- [ ] **Step 1: Write the failing tests:**
  - `test_live_net_shows_controller_both_ways`: see `You → controller: 35` and `Controller → you: 17`
  - `test_compass_click_sector_up` (acceptance 16): click `sector-S`; see `YOUR SECTOR IS UP` within 1 s
  - `test_unknown_controller` (acceptance 17)
  - `test_selection_mode_sector_send_nothing_snap_back_one` (acceptance 18)
  - `test_new_session_shows_expected` (acceptance 14): see 17 expected
  - `test_substitute_tonight_only` (acceptance 15, via the dialog)
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the suite, ruff and mypy. Expected: PASS. Run the app by hand against scratch data, using simulation rotators only: import the W2KV fixture and open the live net.
- [ ] **Step 5:** Commit `feat: nets landing and live net screen (spec 4.4, acceptance 14-18)`.

### Task 7: Hotkeys

**Files:**
- Create: `src/beam_navigator/hotkeys.py`: pure mapping from a key event description to an action, so it is testable without a browser.
- Modify: `src/beam_navigator/ui/live_net.py` and `src/beam_navigator/ui/lookup.py`: one `ui.keyboard` each, calling `hotkeys.action_for`.
- Modify: `docs/decisions.md`: decision 22.
- Test: `tests/unit/test_hotkeys.py`; add to `tests/ui/test_live_net.py`

**Interfaces:**
- Produces:
  - `Action = Literal["rotate", "snap_back"] | tuple[Literal["sector"], str]`.
  - `action_for(code: str, key: str, ctrl: bool, keydown: bool, repeat: bool, screen: Literal["dashboard", "live_net"]) -> Action | None`, following the **Design** table:
    - None for keyup, for repeats, and for an unknown key
    - `Home` and the number-pad sectors on `live_net` only
    - `Ctrl+Enter` on both screens

- [ ] **Step 1: Write the failing tests.**
  - `test_hotkeys.py`: one case per table row; `repeat=True` gives None (Focus 1); a top-row `"2"` (`code="Digit2"`) gives None; `Home` on `dashboard` gives None.
  - UI tests:
    - `test_home_snaps_back_once`: trigger `Home` keydown, then a repeat; `sim.commands` has 1.
    - `test_numpad_announces`: `Numpad2` shows `YOUR SECTOR IS UP`.
    - `test_keys_ignored_while_typing` (Focus 2): with the filter field focused, `Numpad2` and `Home` change nothing and send nothing. Trigger through the keyboard element's handler with the event `target` set to an input; if the simulated user cannot express focus, test the `ignore` list of the `ui.keyboard` element directly and ledger it.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Add decision 22 (fixed hotkeys; not while typing; no auto-repeat; remapping in Milestone 3). Commit `feat: hotkeys — Ctrl+Enter rotate, Home snap back, number-pad sectors`.
