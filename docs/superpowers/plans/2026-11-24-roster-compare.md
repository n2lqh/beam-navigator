# Compare My Session with Net Control's List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep to one session per net per night, and let the Import page compare net
control's list with the owner's session for that night, adding the stations the owner
missed, with QRZ details.

**Architecture:**
- `NetRepository` (store) enforces one session per net and date, and gains an explicit
  `add_from_list` that also works on a closed session.
- A new `roster_compare.py`, beside `roster_review.py`, matches the reviewed rows against
  the session's check-ins and fills the stations to add: the list first, then the saved
  record, then QRZ through `NetControl.qrz_fill`.
- `ui/roster.py` only renders the result and runs the QRZ lookups.

**Tech Stack:** Python 3.14, NiceGUI, sqlite3, pytest (`nicegui.testing.User`), ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-11-24-roster-compare-design.md`

## Global Constraints

- Nothing here sends a rotator command (invariant 2). Every UI test asserts `sim.commands == []`.
- QRZ is asked only after the **Add ticked stations** press (offline-first). Calls go one at a time through `run.io_bound(qrz.lookup, call)`, and a stored answer is used first. `NOT_FOUND` skips that call. Any other `QrzError` stops asking QRZ but still adds the stations with what is known. `NO_LOGIN` and `NO_STORE` say nothing.
- QRZ's grid counts only when `record.precision in ("station", "address")`. It fills a blank, or replaces a 4-character grid it lies inside (`finer_grid`, decision 49(b)).
- Comparing never changes or removes a check-in that is already in the session.
- A check-in added from the list has `heard_state = 'not_heard'`, `notes = "From net control's list"`, `logged_at = NULL`, and a sequence after the session's highest.
- Matching is by base callsign (`base_callsign` when `is_callsign`), as `add_checkin`'s duplicate check does.
- Fixtures in `tests/fixtures/` are read, never edited. No new dependencies.
- Decision record: **49(f)** in `docs/decisions.md` (1.5.1 changes).
- Commits go through the /commit flow, with no Co-Authored-By line.

## Review Focus

1. **The net or date changes after Parse.** The Save and Compare buttons must follow the newly picked night, never the one picked at parse time. Pinned by `test_actions_follow_the_picked_night` (Task 4).
2. **The same station twice on net control's list** (a roster typo or a relay). It must be added once. Pinned by `test_duplicate_rows_add_once` (Task 3).
3. **Add pressed twice.** The second press must add nothing. Pinned by `test_add_twice_adds_nothing_more` (Task 3).
4. **A list row the owner unticked in the review table** (`include = False`). It must not count as "net control had". Pinned by `test_excluded_rows_are_not_compared` (Task 3).
5. **No QRZ login.** Adding must still work, quietly, with the list's and the saved record's details. Pinned by `test_add_without_qrz_login` (Task 4).

---

### Task 1: One session per net per night (store)

**Files:**
- Modify: `src/beam_navigator/store/repositories.py`: `start_session` (around line 543), `import_roster` (around line 435), plus a new `session_on`
- Test: `tests/unit/test_store_sessions.py`, `tests/unit/test_store_nets.py:67` (`test_replace_or_keep_both`)
- Docs: `docs/requirements.md:273` (acceptance 13)

**Interfaces:**
- Produces:
  - `NetRepository.session_on(net_id: int, date: str) -> Session | None` returns the newest session of that net on that date, of any status (`ORDER BY id DESC LIMIT 1`).
  - `start_session(net_id, date)` returns `session_on(...)` when there is one, and otherwise creates a session as before.
  - `import_roster(...)` without `replace_session_id` raises `ValueError(f"This net already has a session on {date}.")` when `session_on` finds one.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_store_sessions.py`:

```python
def test_start_session_twice_opens_the_same_session(nets: NetRepository) -> None:
    net_id = ...  # as the file's other tests make a net
    first = nets.start_session(net_id, "2026-11-23")
    nets.close_session(first.id, "")
    again = nets.start_session(net_id, "2026-11-23")
    assert again.id == first.id and again.status == "closed"
    assert nets.start_session(net_id, "2026-11-30").id != first.id

def test_session_on(nets: NetRepository) -> None:
    net_id = ...
    assert nets.session_on(net_id, "2026-11-23") is None
    made = nets.start_session(net_id, "2026-11-23")
    assert nets.session_on(net_id, "2026-11-23") == made
```

Rename `test_replace_or_keep_both` to `test_replace_or_refuse_a_second_session`. Keep its replace half, and change its last part so that importing again without `replace_session_id` raises `ValueError`, matched with `"already has a session on 2026-10-26"`, and `count(conn, "session") == 1`. Add one case: `import_roster` on a date where `start_session` already made a session raises the same error.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/unit/test_store_sessions.py tests/unit/test_store_nets.py -q`
Expected: FAIL. `session_on` doesn't exist, the second `start_session` makes a new id, and the second import creates a second session.

- [ ] **Step 3: Implement** `session_on`, the `start_session` reuse and the `import_roster` guard. The guard runs before the transaction. With `replace_session_id`, the existing check (an import of this net and date) is unchanged.

- [ ] **Step 4: Run the tests again**

Run: `uv run pytest tests/unit -q`
Expected: PASS. Other unit tests that import the same fixture twice on one date must now use different dates. Fix any that do, since those tests broke the rule.

- [ ] **Step 5: Update acceptance 13** in `docs/requirements.md` to: "Re-importing for a net and date that already has an imported session asks Replace or Cancel; a night has one session."

- [ ] **Step 6: Commit** via /commit with `fix: one session per net per night`.

---

### Task 2: Import page offers Replace or Cancel

**Files:**
- Modify: `src/beam_navigator/ui/roster.py`: `save` and `ask_replace` (around lines 101–141)
- Modify: `src/beam_navigator/roster_review.py`: replace `duplicate_of` with `session_for_night`
- Test: `tests/ui/test_import.py` (`test_reimport_asks_replace_or_keep`)

**Interfaces:**
- Consumes: `NetRepository.session_on` (Task 1).
- Produces: `RosterReview.session_for_night(net_id: int, date: str) -> Session | None`, which delegates to `session_on`. Task 4 uses it.

- [ ] **Step 1: Change the test.** Rename it `test_reimport_asks_replace_or_cancel`. After the second Save it sees "already imported for this night", sees "Replace" and "Cancel", and `should_not_see("Keep both")`. Replace still ends with one session. Add `test_reimport_of_different_text_also_asks_replace`: after a W2KV import for 2026-10-26, saving the DMR fixture text for the same net and date also asks Replace, so different text no longer slips through as a second session.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/ui/test_import.py -q`
Expected: FAIL. "Keep both" is still shown, and the different text saves a second session.

- [ ] **Step 3: Implement.**
  - When `session_for_night` returns a session with `status == "imported"`, Save asks: "Net control's list for this night is already imported." with **Replace** (`replace_session_id=existing.id`) and **Cancel**.
  - Remove `keep_both`. `find_identical_import` stays in the repository (its tests still use it) but the page no longer calls it.
  - A night whose session is the owner's (active or closed) is handled by Task 4. Until then, Save shows the repository's `ValueError` through `_error`.

- [ ] **Step 4: Run the tests again**

Run: `uv run pytest tests/ui/test_import.py -q`
Expected: PASS.

- [ ] **Step 5: Update the user guide.** `docs/user-guide.md`, Importing a roster, last sentence: "Importing again for a net and date that already has an imported list asks whether to **Replace** it or **Cancel**."

- [ ] **Step 6: Commit** via /commit with `fix: re-import asks Replace or Cancel; no second session`.

---

### Task 3: Compare and add (logic and store)

**Files:**
- Create: `src/beam_navigator/roster_compare.py`
- Modify: `src/beam_navigator/store/repositories.py`: new `NetRepository.add_from_list`
- Test: `tests/unit/test_roster_compare.py` (new)

**Interfaces:**
- Consumes: `Review` and `ReviewRow` (`roster_review.py`), `NetControl.qrz_fill(entry: Entry, record: QrzRecord) -> Entry`, `Desk.stations.get`, `Desk.qrz.get(call) -> tuple[QrzRecord, str] | None`.
- Produces (`roster_compare.py`):

```python
@dataclass
class Missing:            # net control had it, the owner didn't
    callsign: str
    name: str | None
    grid: str | None
    qth: str | None
    add: bool = True

@dataclass(frozen=True)
class OnBoth:
    callsign: str
    differences: list[str]   # e.g. "Grid: FM29 (you) · FM29pt (net control)"

@dataclass
class Comparison:
    session_id: int
    raw_text: str
    missing: list[Missing]
    only_mine: list[CheckIn]
    both: list[OnBoth]

class RosterCompare:
    def __init__(self, conn: sqlite3.Connection, desk: Desk) -> None: ...
    def compare(self, session_id: int, review: Review) -> Comparison: ...
    def qrz_wanted(self, comparison: Comparison) -> list[str]: ...
    def add(self, comparison: Comparison) -> list[CheckIn]: ...
```

- Produces (store): `NetRepository.add_from_list(session_id: int, stations: list[tuple[str, str | None, str | None, str | None, bool]], raw_text: str) -> list[CheckIn]`. Each tuple is `(callsign, name, grid, qth, grid_looked_up)`. The whole call is one transaction and does **not** call `_check_open`. It skips calls whose base callsign is already in the session. Each new check-in gets the Global Constraints values. `_insert_roster_station` is called with grid `None` when `grid_looked_up`. `raw_text` is set when the session has none, and otherwise appended after a blank line unless that exact text is already there. It returns the check-ins it added.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_roster_compare.py`. Use an in-memory db, a Desk set up as in `tests/ui/test_import.py`, the W2KV fixture parsed with `RosterReview.parse`, and a session started with `start_session(net, "2026-10-26")` where the owner logged `K3WGR` with grid `FN10` and `W1AW`:
  - `test_compare_groups`: `K3WGR` is in `both`, with `differences == ["Grid: FN10 (you) · FN10xi (net control)"]`. `[c.callsign for c in only_mine] == ["W1AW"]`. `missing` holds the other 15 included calls in list order, all with `add=True`.
  - `test_add_marks_not_heard_with_a_note`: untick all but `K4SO` and `KD4AA`, then `add`. Two check-ins with `heard_state == "not_heard"`, `notes == "From net control's list"`, `logged_at is None`, and sequences 3 and 4. The session's `raw_text` is the W2KV text.
  - `test_add_works_on_a_closed_session`: close the session, then `add`. The check-ins are there and the status is still `"closed"`.
  - `test_add_uses_stored_qrz_finer_grid_and_fills_blanks`: store `QrzRecord("K4SO", "MARK SMITH", "FM18ap", "AMISSVILLE, VA", None, None, "user")` (geoloc `"user"` is station precision) with `desk.qrz_store`.
    - (a) The list's `MARK` and `FM18AP` are kept, because QRZ only fills blanks and `finer_grid` only refines a 4-character square.
    - (b) Edit the review row's grid to `FM18`. The check-in's grid becomes `FM18ap`.
    - (c) Edit the row's name and grid to blank. The check-in gets `MARK SMITH` and `FM18ap`, and the new station record's grid is `None` (`grid_looked_up`).
  - `test_qrz_grid_from_a_zip_is_ignored`: a stored answer with geoloc `"zip"` never sets the grid.
  - `test_qrz_wanted`: returns ticked missing calls with no stored QRZ answer, each once.
  - `test_duplicate_rows_add_once` (Review Focus 2): append a second `K4SO` row to the review rows. One check-in is added.
  - `test_add_twice_adds_nothing_more` (Review Focus 3): the second `add` returns `[]`, and the check-in count is unchanged.
  - `test_excluded_rows_are_not_compared` (Review Focus 4): with `include=False` on `K4SO`, it is in no group.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/unit/test_roster_compare.py -q`
Expected: FAIL with `ModuleNotFoundError: beam_navigator.roster_compare`.

- [ ] **Step 3: Implement** `add_from_list`, then `RosterCompare`.
  - `compare` only counts rows with `include` and a callsign, and drops duplicates by base callsign, keeping the first.
  - `differences` compares name (casefold) and grid (case-insensitive), and only when both sides have a value.
  - `add` builds each ticked `Missing` row into an `Entry` from the list. It fills blanks from the saved record. When there is a stored QRZ answer, it applies `NetControl.qrz_fill`. `grid_looked_up` is true when the final grid differs from the list's grid.
  - The UI stores fresh QRZ answers through `desk.qrz_store` before calling `add`, so `add` itself only reads `desk.qrz.get`.

- [ ] **Step 4: Run the tests again**

Run: `uv run pytest tests/unit -q`
Expected: PASS.

- [ ] **Step 5: Commit** via /commit with `feat: compare a session with net control's list and add the missed stations`.

---

### Task 4: Compare with my session on the Import page

**Files:**
- Modify: `src/beam_navigator/ui/roster.py`: `import_page`. The Save button becomes a refreshable `actions()`.
- Modify: `src/beam_navigator/ui/app.py`: pass a `RosterCompare` into `import_page`, the same way `RosterReview` is passed.
- Test: `tests/ui/test_import.py`
- Docs: `docs/user-guide.md` (a new "Comparing with net control's list" section after Importing a roster), `docs/decisions.md` (49(f))

**Interfaces:**
- Consumes: `RosterReview.session_for_night` (Task 2), and `RosterCompare` with `Comparison` and `Missing` (Task 3).
- Produces these marks for the tests:
  - `compare`: the button.
  - `compare-missing`, `compare-only-mine`, `compare-both`: the three group columns.
  - `add-<CALL>`: each checkbox.
  - `add-ticked`: the add button.
  - `compare-status`: the result label.

- [ ] **Step 1: Write the failing tests** in `tests/ui/test_import.py`, using a session started on the W2KV net for 2026-10-26 with `K3WGR` (grid `FN10`) and `W1AW` logged:
  - `test_compare_shows_three_groups`: after Parse, `should_not_see` the Save button (`user.find(marker="save")` finds nothing), and `compare` is there. Clicking it shows "Net control had, you didn't (15)", "You had, net control didn't (1)" with W1AW, and "On both lists (1)" with "Grid: FN10 (you) · FN10xi (net control)".
  - `test_add_ticked_stations`: untick `add-K4SO`, then click `add-ticked`. `should_see("Added 14 stations")` and the "Open live net" link appear. The session has 16 check-ins, K4SO isn't among them, the session's `raw_text` is the W2KV text, and `sim.commands == []`.
  - `test_add_asks_qrz_once_per_call`: with `StubQrz` registered, the added stations get grid `FN10ab` only where the list had none or 4 characters. Here the stub's geoloc is `None`, which gives precision `"none"`, so no grids change. Assert `stub.asked` covers the ticked calls with no stored answer, and that the stub was never asked before the click.
  - `test_add_without_qrz_login` (Review Focus 5): with the real client and no login, Add still adds 15 stations and shows no QRZ warning.
  - `test_actions_follow_the_picked_night` (Review Focus 1): after Parse with date 2026-10-26 (owner's session), change the date to 2026-10-27. Save comes back and Compare goes away. Change it back, and Compare returns.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/ui/test_import.py -q`
Expected: FAIL. There is no `compare` mark.

- [ ] **Step 3: Implement.**
  - `actions()` refreshes on parse and on changes to the net or the date.
  - When `session_for_night` is the owner's session (`status` is `"active"` or `"closed"`), it shows the text "You have your own session for this night." and the **Compare with my session** button. Otherwise it shows **Save**.
  - Compare renders the three groups, with counts in the headings. A highlighted difference uses the `text-warning` class.
  - **Add ticked stations**:
    1. For each call from `qrz_wanted`, run `run.io_bound(qrz.lookup, call)` with the Global Constraints error handling, showing "Looking up on QRZ: <call>…" in `compare-status`.
    2. Store each answer with `desk.qrz_store`.
    3. Call `compare.add`.
    4. Show "Added N stations" and `ui.link("Open live net", f"/net/{session_id}")`.
  - A fresh Parse clears the comparison.

- [ ] **Step 4: Run the tests again**

Run: `uv run pytest tests/ui/test_import.py -q`
Expected: PASS.

- [ ] **Step 5: Write the docs.**
  - User guide section: when to use Compare, the three groups, that added stations are marked Not heard with the note, that QRZ fills missing details and exact grids, that it works on a closed session, and that nothing is removed.
  - Decision 49(f): the owner's words ("highlight the differences and offer to add …", "there should only be one session closed per net per night", "stored with the full 6 digit grid and information from QRZ"), what changed in Tasks 1–4, the removal of Keep both, and that no rotator command is sent (invariant 2).

- [ ] **Step 6: Run the full checks**

Run: `uv run pytest -q; uv run ruff check .; uv run mypy src/beam_navigator/core`
Expected: everything passes. This run takes longer than 120 s, so run it in the background.

- [ ] **Step 7: Commit** via /commit with `feat: Compare with my session on the Import page`.
