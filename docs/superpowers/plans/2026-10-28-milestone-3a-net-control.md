# Milestone 3a — Net Controller Screen and Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A net controller can log a whole net from the keyboard. The screen fills in known stations, offers partial-call matches ranked by attendance, catches duplicates and changed details, shows an info panel, allows inline edits to the session table, and exports the session as text, CSV or JSON.

**Architecture:** As before, every rule lives outside `ui/`.
- `net_control.py` holds the controller's operations.
- `entry_keys.py` is a pure key-to-action table for the entry line.
- `export.py` writes the three formats.
- `ui/control.py` only renders and calls these.
- The controller screen never moves a rotator: it has no Rotate button.

**Tech Stack:** Python 3.12+, NiceGUI 3.18, `sqlite3`, standard `csv`/`json`/`zoneinfo`. No new dependencies.

**Spec:** `docs/requirements.md` v2.0 — section 3 key rules, section 4.5, section 7 tests 19–24. `docs/decisions.md` 13, 22.

**Out of scope (plan 3b):** the nets list and history screens with add, edit, duplicate, archive and `*.beamnet.json` (4.6); example nets (they need the owner's real schedule; never invented); remapping keys (spec 4.5 "All keys remappable", 4.8).

## Design

**Entry line keys.** These follow spec 4.5, applied as contest loggers do. Decision 23 records them.
- Fields in order: Callsign → Name → Grid → QTH → Report → Notes.
- `Tab` moves to the next field and `Shift+Tab` to the previous one.
- `Space` moves on only from **Callsign** and **Grid**. Neither can contain a space; in Name, QTH, Report and Notes a space is typed.
- `Enter` logs from any field.
- `Esc` clears the line.
- Focus returns to Callsign after logging or clearing.
- `ArrowDown`/`ArrowUp` in Callsign move through the partial-call list. `Enter` on a highlighted match picks it (and auto-fills) instead of logging.
- `Ctrl+N` adds a persistent station note for the callsign on the line.

**Auto-fill** happens when the callsign is complete: on leaving Callsign with Space or Tab, or picking a match.
- Name, Grid and QTH fill from the station record.
- Each filled field is marked *from history* (italic, grey) until the controller types in it or the entry is logged.
- With no record, the line shows `New station — name and grid needed`, focus moves to Name, and Name and Grid are highlighted.

**Logging.**
- **Callsign:** a blank callsign logs nothing.
- **Grid:** a non-blank invalid grid refuses the log with the reason. Blanks are allowed and flagged in the table (`name missing`, `grid missing`).
- **Duplicate:** an already-logged callsign (same base call, existing rule) shows `Already checked in at 20:07 (#5)` and offers **Update existing**. The time is in the net's time zone, else the profile's, else UTC. An imported check-in has no time: `Already checked in (#5)`.
- **Changed details:** a name or grid that differs from the station record asks **This session only** (the default, Enter) or **Update station record**. Grids compare case-insensitively.
- **New station:** logging a callsign with no record creates one using the roster's gap-fill rule (decision 13), not as `saved`.

**Info panel** for the callsign on the line:
- last name, grid, QTH and source
- bearing and distance **from net control**, using the 2c controller location
- attendance `12 of last 15` at this net
- previous session notes at this net, newest first, up to 5
- persistent station notes

**Export.** Every format has a header: date, net, frequency or channel, controller and controller grid. Bearings are labelled `from net control`. Heard states are excluded unless the controller ticks **Include my heard states**.
- **Text:** one line per check-in.
- **CSV:** `sequence,time,callsign,name,grid,qth,report,notes,bearing_from_net_control,distance_km`, plus `heard` when included.
- **JSON:** `{"schema": 1, "net": …, "date": …, "frequency": …, "controller": …, "controller_grid": …, "checkins": [...]}`.

## Global Constraints

- **No rotator commands** from this screen; it has no Rotate button (invariant 2).
- **Check-ins snapshot location.** Updating a station record never rewrites past check-ins (spec 3).
- **Never invent a location** (invariant 5). Blanks stay blank and are flagged.
- **Heard states are private** (spec 4.4). They are excluded from exports unless chosen.
- `ui/` holds no business logic. Match the existing code: 4-space indentation, line length 100, `ruff`, `mypy --strict` on `src/beam_navigator`.
- Fixture files are read, never written. UI tests use simulators only.

## Review Focus

1. **Space in Name, QTH or Notes** ("MARY ANN", "CHERRY HILL") types a space and does not jump fields. Test in Task 4.
2. **A portable call** `K1ABC/P` logged after `K1ABC` gives the duplicate warning (base call), with no silent second row. Test in Task 2.
3. **A grid that differs only in case** (`FN20OK` against `fn20ok`) is not a change and gives no dialog. Test in Task 2.
4. **Commas, quotes and newlines** in names or notes still give valid CSV and JSON. Heard states stay out by default. Test in Task 3.
5. **Enter with an empty callsign**, or Esc mid-entry, logs nothing, raises no error, and returns focus to Callsign. Test in Task 5.

---

### Task 1: Store — check-in details, edits, attendance, history notes

**Files:**
- Modify: `src/beam_navigator/core/models.py`: `CheckIn` gains `report: str | None = None`, `notes: str | None = None`, `logged_at: str | None = None`
- Modify: `src/beam_navigator/store/repositories.py`
- Test: `tests/unit/test_store_net_control.py`

**Interfaces:**
- Produces (`NetRepository`):
  - `update_checkin(checkin_id: int, *, name, grid, qth, report, notes: str | None) -> CheckIn`: replaces those fields. A non-blank invalid grid raises `GridError`. A blank becomes None.
  - `attendance(net_id: int, callsign: str, last: int = 15) -> tuple[int, int]`: (sessions attended among the net's last `last` sessions by date, number of those sessions). Matched by base call.
  - `previous_notes(net_id: int, callsign: str, before_session_id: int, limit: int = 5) -> list[tuple[str, str]]`: (date, notes) from earlier sessions of this net, newest first, non-blank only.
  - `call_counts(net_id: int) -> dict[str, int]`: sessions attended per callsign at this net.
- Produces (`StationRepository`): `add_note(callsign: str, text: str, when: str) -> None`. It appends `f"{when}: {text}"` on its own line to the persistent notes, creating a gap-fill record if none exists. Blank text raises `ValueError`.

- [ ] **Step 1: Write the failing tests:**
  - `test_checkin_carries_report_notes_time`
  - `test_update_checkin` (bad grid refused; blank → None)
  - `test_attendance_last_15` (16 sessions, attended 12 of the last 15)
  - `test_attendance_base_call` (`K1ABC/P` counts for `K1ABC`)
  - `test_previous_notes_newest_first`
  - `test_call_counts`
  - `test_add_station_note` (appends on a new line; creates a record; blank refused)
  - `test_update_record_leaves_snapshots` (spec 3: `StationRepository.save` with a new grid leaves earlier check-ins unchanged)
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_store_net_control.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: check-in edits, attendance and history notes in the store`.

### Task 2: Net control service

**Files:**
- Create: `src/beam_navigator/net_control.py`
- Modify: `src/beam_navigator/live_net.py`: make the controller location public as `LiveNet.controller_location(session_id: int) -> LatLon | None` (same rules as `_controller`)
- Test: `tests/unit/test_net_control.py`

**Interfaces:**
- Consumes: Task 1, `LiveNet.controller_location`, `StationRepository`, `Desk` (profile time zone, units, `_distance` formatting via a new public `Desk.distance_text(km: float) -> str`).
- Produces:
  - `Entry(callsign: str, name: str = "", grid: str = "", qth: str = "", report: str = "", notes: str = "")`, a dataclass.
  - `Autofill(callsign: str, known: bool, name: str | None, grid: str | None, qth: str | None, source: str | None)`.
  - `InfoPanel(callsign: str, last: str, from_net_control: str | None, attendance: str, previous_notes: list[str], station_notes: str)`:
    - `last` is `"Bob · FN20ok · Cherry Hill (saved)"` or `"No record"`
    - `from_net_control` is `"From net control: 174.2° S · 43 mi"` or None
    - `attendance` is `"12 of last 15"`
  - `Suggestion(callsign: str, attended: int, last_grid: str | None)`.
  - `NetControl(conn: sqlite3.Connection, desk: Desk)` with:
    - `autofill(callsign: str) -> Autofill` (normalizes the call)
    - `info(session_id: int, callsign: str) -> InfoPanel`
    - `suggest(session_id: int, fragment: str, limit: int = 8) -> list[Suggestion]`: case-insensitive substring of known callsigns (station records plus this net's history). Ranked by attendance at this net (descending), then callsign. A fragment under 2 characters gives `[]`.
    - `duplicate(session_id: int, callsign: str) -> CheckIn | None` (base-call rule)
    - `duplicate_text(session_id: int, checkin: CheckIn) -> str`
    - `changes(entry: Entry) -> list[str]`: e.g. `["Name: BOB → ROBERT", "Grid: FN20ok → FN20pk"]`; empty when unknown, when blank, or when equal ignoring case for the grid
    - `log(session_id: int, entry: Entry, update_record: bool = False) -> CheckIn`:
      - a blank callsign or a bad grid raises `ValueError`
      - a duplicate raises `DuplicateCheckIn`
      - an unknown station gets a gap-fill record
      - `update_record` saves the entry's name, grid and QTH to the station record (`source='saved'`) and keeps the notes
    - `update_existing(checkin_id: int, entry: Entry) -> CheckIn`
    - `add_station_note(callsign: str, text: str) -> None`: timestamped with today's date
    - `rows(session_id: int) -> list[ControlRow]`, where `ControlRow(checkin_id, sequence, time, callsign, name, grid, qth, report, notes, flags: list[str])`; flags are `name missing` and `grid missing`

- [ ] **Step 1: Write the failing tests** (profile FM29pt; net "W2KV 2 m", time zone `America/New_York`; W2KV fixture imported for 2026-10-26 to build history; a new session 2026-11-02 started; controller W2KV FN20OK):
  - `test_autofill_known` (acceptance 19): `K3WGR` gives name, grid and QTH, with source `roster`.
  - `test_autofill_unknown` (acceptance 20): `known` False.
  - `test_info_panel`:
    - `from_net_control` uses `short_path(FN20OK, K3WGR grid)`
    - attendance `1 of last 2`
    - previous notes include a note from an earlier session
    - station notes shown
  - `test_suggest_ranked_by_attendance` (acceptance 24): give K3WGR the most sessions at this net, plus a less-attended `K3WXX`; `suggest(..., "K3W")[0].callsign == "K3WGR"`.
  - `test_duplicate_base_call` (Focus 2): log `K1ABC`, then `log` `K1ABC/P` raises `DuplicateCheckIn`. `duplicate_text` is `Already checked in at HH:MM (#1)` in America/New_York; for an imported row it is `Already checked in (#n)`.
  - `test_changes_and_case` (Focus 3, acceptance 21): different name gives one change; `fn20ok` against `FN20OK` gives no change.
  - `test_log_session_only_leaves_record` (acceptance 21).
  - `test_log_update_record`.
  - `test_unknown_logged_with_blanks_flagged` (acceptance 20).
  - `test_update_existing` (acceptance 22).
  - `test_bad_grid_refused_nothing_logged`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: net control service — auto-fill, matches, duplicates, changes (acceptance 19-22, 24)`.

### Task 3: Export

**Files:**
- Create: `src/beam_navigator/export.py`
- Test: `tests/unit/test_export.py`

**Interfaces:**
- Consumes: `NetControl.rows`, the session, the net, `LiveNet.controller_location`, `Desk.bearing_to`-style math through `short_path` from the controller location.
- Produces: `export_session(conn: sqlite3.Connection, desk: Desk, session_id: int, fmt: Literal["text", "csv", "json"], include_heard: bool = False) -> str`, and `export_filename(session: Session, net: Net, fmt) -> str`, e.g. `w2kv-2-m_2026-11-02.csv` (slugged net name).

- [ ] **Step 1: Write the failing tests:**
  - `test_header_fields_every_format`
  - `test_bearings_labelled_from_net_control`
  - `test_heard_excluded_by_default`, then included when asked
  - `test_csv_and_json_survive_awkward_text` (Focus 4): a name `O'Brien, "Bob"` and notes with a newline. `csv.reader` round-trips each field exactly, and `json.loads` gives the same strings.
  - `test_filename`
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: export a session as text, CSV or JSON (spec 4.5)`.

### Task 4: Entry-line keys (pure)

**Files:**
- Create: `src/beam_navigator/entry_keys.py`
- Modify: `docs/decisions.md`: decision 23
- Test: `tests/unit/test_entry_keys.py`

**Interfaces:**
- Produces:
  - `FIELDS = ("callsign", "name", "grid", "qth", "report", "notes")`.
  - `KeyAction = Literal["next", "previous", "log", "clear", "suggest_down", "suggest_up", "note", "type"]`.
  - `key_action(field: str, key: str, shift: bool, ctrl: bool) -> KeyAction`:
    - `Tab` gives next, or previous with Shift
    - `" "` gives next in callsign or grid, else type
    - `Enter` gives log
    - `Escape` gives clear
    - `ArrowDown`/`ArrowUp` give suggest_* in callsign, else type
    - Ctrl+`n`/`N` gives note
    - anything else gives type
  - `next_field(field: str) -> str` and `previous_field(field: str) -> str`: they stop at the ends, Notes and Callsign.

- [ ] **Step 1: Write the failing tests:** one per rule, plus `test_space_types_in_free_text_fields` (Focus 1: name, qth, report, notes give `type`) and `test_ends_do_not_wrap`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the suite, ruff and mypy. Expected: PASS.
- [ ] **Step 5:** Add decision 23 (the entry-line keys as in **Design**; Space advances only where a space cannot be typed). Commit `feat: entry-line key table (spec 4.5)`.

### Task 5: Net controller screen

**Files:**
- Create: `src/beam_navigator/ui/control.py`
- Modify:
  - `src/beam_navigator/ui/app.py`: a `/control/{session_id}` page
  - `src/beam_navigator/ui/live_net.py`: links from the live net screen and the nets page
- Test: `tests/ui/test_control.py`

**Interfaces:**
- Produces: `ui.control.control_page(control: NetControl, session_id: int) -> None`:
  - **Entry line:** six inputs, marks `entry-callsign` … `entry-notes`. Each input has a `keydown` listener whose `js_handler` calls `preventDefault()` for keys `key_action` does not map to `type`, then emits `{key, shiftKey, ctrlKey}`. Focus moves with `run_method("focus")`.
  - **From history:** fields get the class `italic text-grey` until edited.
  - **Suggestion list:** mark `suggestions`; the highlighted item has the class `bg-blue-2`.
  - **Info panel:** mark `info`.
  - **Dialogs:** a changes dialog (buttons `This session only`, `Update station record`), a duplicate dialog (`Update existing`, `Cancel`) and a station-note dialog (Ctrl+N).
  - **Session table:** inline-editable name, grid, QTH, report and notes, saved on blur through `update_existing`. Rows with flags show badges.
  - **Export:** buttons `Text`, `CSV`, `JSON` with an **Include my heard states** checkbox. They use `ui.download.content(...)`.

- [ ] **Step 1: Write the failing tests.** Drive keys with `trigger("keydown", {...})` on the inputs, as Task 7 of plan 2c did for `ui.keyboard`.
  - `test_known_call_space_autofills` (acceptance 19): type `K3WGR`, then Space; see the name, grid and QTH, the *from history* class, and previous notes in the info panel.
  - `test_unknown_stops_on_name_and_grid` (acceptance 20): Enter logs with blanks; see the `grid missing` badge.
  - `test_changed_grid_session_only` (acceptance 21): the station record is unchanged.
  - `test_duplicate_update_existing` (acceptance 22).
  - `test_full_checkin_without_mouse` (acceptance 23): keys only, then one row logged and focus back on Callsign (the last `run_method` target).
  - `test_partial_list_ranked` (acceptance 24): type `K3W`; the first suggestion is K3WGR; ArrowDown then Enter picks it.
  - `test_empty_enter_and_esc` (Focus 5).
  - `test_export_downloads`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the suite, ruff and mypy. Expected: PASS. Run the app by hand against scratch data and log three stations using only the keyboard.
- [ ] **Step 5:** Commit `feat: net controller screen (spec 4.5, acceptance 19-24)`.
