# Participant Net Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live net screen (`/net/{session_id}`) usable by a participant with no roster. Add a Regulars list, an Aim at box, an "I hear" entry line, and Close my session with notes shown at the next session.

**Architecture:** Store gets migration 0009 and close/reopen/last-notes methods, and refuses writes to a closed session. `live_net.py` gains Regulars rows, sorting, typed and regular targets, and the Aim lookup. `net_control.py` gains `log_heard`. The net control entry line moves out of `ui/control.py` into a reusable `ui/entry_line.py` so both screens share one implementation. `ui/live_net.py` puts it all together.

**Tech Stack:** Python 3, NiceGUI, sqlite3, pytest with `nicegui.testing.User`.

**Spec:** `docs/superpowers/specs/2026-10-30-participant-net-screen-design.md`

## Global Constraints

- Invariant 2: only Rotate, Snap back and their hotkeys send a rotator command. Typing, Enter in any box, clicking a row, Heard, logging, Close and Reopen send nothing.
- Offline: no new network use. QRZ on the I-hear line behaves exactly as on the net control screen: it fills in data when available and never blocks.
- Bearings are from the user's station. Unknown grids stay unknown ("Grid needed").
- No new dependencies. `core/` stays free of UI, store and network imports.
- Closing notes are private: never in text, CSV or JSON exports.
- Run `uv run pytest`, `uv run ruff check .` and `uv run mypy src/beam_navigator/core` before each commit.

## Review Focus

1. **Enter in the Aim box while a rotator is live.** Expected: no command. Pinned in Task 3 (`test_aim_enter_sends_nothing`).
2. **Closed session opened on the net control screen and logging attempted.** Expected: a clear "This session is closed" message, nothing logged. Pinned in Task 4 (`test_control_closed_session_refuses_log`).
3. **A regular with no grid anywhere.** Expected: listed with "Grid needed", sorted last by grid and direction, and Rotate disabled when it's selected. Pinned in Task 2 (`test_regular_without_grid`).
4. **Logging a call that's already tonight from the I-hear line.** Expected: the "Already checked in" dialog, and no second row. Pinned in Task 4 (`test_i_hear_duplicate_asks`).
5. **Last time across nets, and when the newest closed session has empty notes.** Expected: only this net's notes show, and an empty newest note means no card rather than an older note. Pinned in Task 1 (`test_last_closing_notes_scope`).

---

### Task 1: Store — close, reopen, last notes, closed-session guard

**Files:**
- Create: `src/beam_navigator/store/migrations/0009_session_close.sql`
- Modify: `src/beam_navigator/core/models.py` (`Session`)
- Modify: `src/beam_navigator/store/repositories.py` (`get_session`, `add_checkin`, `update_checkin`, `set_heard`, new methods)
- Test: `tests/unit/test_store_session_close.py`

**Interfaces:**
- Produces:
  - `Session.closing_notes: str | None = None`, `Session.closed_at: str | None = None` (new trailing defaulted fields)
  - `class SessionClosed(ValueError)` in `repositories.py`, message `"This session is closed. Reopen it to make changes."`
  - `NetRepository.close_session(session_id: int, notes: str) -> Session`: sets status `closed`, `closing_notes` (stripped, `None` if empty) and `closed_at = _now()`
  - `NetRepository.reopen_session(session_id: int) -> Session`: sets status `active` and keeps the notes and `closed_at`
  - `NetRepository.last_closing_notes(net_id: int, before_session_id: int) -> tuple[str, str] | None`: `(date, notes)` of the latest closed session of this net other than `before_session_id`, by `closed_at`. `None` if that session's notes are empty.
  - `add_checkin`, `update_checkin` and `set_heard` raise `SessionClosed` when the session's status is `closed`. Check this first, before the duplicate check.

- [ ] **Step 1: Write the failing tests** (fixtures copied from `tests/unit/test_store_live_net.py`: `conn`, `add_net`, `import_w2kv`)

```python
def test_close_and_reopen_keep_notes(conn):
    nets = NetRepository(conn); s = nets.start_session(add_net(conn), "2026-10-30")
    closed = nets.close_session(s.id, "  K3WGR weak from 40°  ")
    assert closed.status == "closed" and closed.closing_notes == "K3WGR weak from 40°"
    assert closed.closed_at is not None
    again = nets.reopen_session(s.id)
    assert again.status == "active" and again.closing_notes == "K3WGR weak from 40°"

def test_closed_session_refuses_writes(conn):
    nets = NetRepository(conn); s = nets.start_session(add_net(conn), "2026-10-30")
    c = nets.add_checkin(s.id, "K3WGR"); nets.close_session(s.id, "")
    with pytest.raises(SessionClosed): nets.add_checkin(s.id, "W2KV")
    with pytest.raises(SessionClosed): nets.set_heard(c.id, "heard", None)
    with pytest.raises(SessionClosed): nets.update_checkin(c.id, name="Bob")  # match its real signature
    nets.reopen_session(s.id); nets.add_checkin(s.id, "W2KV")

def test_last_closing_notes_scope(conn):
    nets = NetRepository(conn); a, b = add_net(conn, "A"), add_net(conn, "B")
    s1 = nets.start_session(a, "2026-10-19"); nets.close_session(s1.id, "first")
    other = nets.start_session(b, "2026-10-20"); nets.close_session(other.id, "other net")
    s2 = nets.start_session(a, "2026-10-26")
    assert nets.last_closing_notes(a, s2.id) == ("2026-10-19", "first")
    nets.close_session(s2.id, "")
    s3 = nets.start_session(a, "2026-11-02")
    assert nets.last_closing_notes(a, s3.id) is None  # newest closed has no notes
    assert nets.last_closing_notes(b, s3.id) == ("2026-10-20", "other net")
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_store_session_close.py -v`. Expected: FAIL (`close_session` missing).
- [ ] **Step 3: Implement.** The migration body is the two `ALTER TABLE session ADD COLUMN` lines in the spec, with a one-line comment above in the style of 0004. Then add the model fields, read them in `get_session`, add the three methods and the guard.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass, including `tests/unit/test_store_db.py`, which checks migrations.
- [ ] **Step 5: Commit** `feat: sessions close with notes and refuse changes while closed`

---

### Task 2: Live net logic — Regulars, sorting, typed and regular targets, Aim, last time

**Files:**
- Modify: `src/beam_navigator/live_net.py`
- Test: `tests/unit/test_live_net.py` (add tests; keep existing ones passing)

**Interfaces:**
- Consumes: `NetRepository.expected`, `.attendance`, `.last_closing_notes` (Task 1); `Desk.look_up(text, band) -> LookupView`; `Desk.bearing_to(grid)`.
- Produces:
  - `Mode = Literal["controller", "station", "regular", "typed"]`
  - `RegularSort = Literal["callsign", "grid", "direction", "last"]`
  - `@dataclass(frozen=True) class RegularRow: callsign: str; name: str | None; grid_text: str; bearing_deg: float | None; bearing_text: str | None; distance_text: str | None; attendance_text: str; last_seen: str`
  - `LiveNetView.expected` is replaced by `regulars: list[RegularRow]`, plus `last_time: tuple[str, str] | None` and `closed: bool`.
  - `sort_regulars(rows: list[RegularRow], key: RegularSort) -> list[RegularRow]`
  - `filter_rows` becomes generic over any row with `callsign`, `name` and `grid_text` (a `Protocol` plus a `TypeVar`). Same behavior.
  - `LiveNet.aim(session_id: int, text: str) -> tuple[LookupView, tuple[str, float] | None]`: the lookup, done with the net's band, and the rotate target `(view.title or text, view.bearing_deg)` when `view.can_rotate` and the bearing isn't `None`. Records nothing and sends nothing.
  - `LiveNet.target(session_id, mode, checkin_id, *, callsign: str | None = None, typed: tuple[str, float] | None = None)`. `"regular"` finds the regular by callsign. `"typed"` returns `typed`. `rotate()` gets the same keyword arguments and passes them through.

Row rules: name from the station record. Grid is the participant's `last_grid` when it's a valid grid, otherwise the saved station grid shown as `"{grid} (saved)"`, otherwise `"Grid needed"`, matching `_rows`. `attendance_text` is `f"{attended} of last {counted}"` from `nets.attendance`. Sorting: callsign A→Z. Grid A→Z, case-insensitive, with "Grid needed" last. Direction by `bearing_deg` with `None` last. Last check-in by `last_seen`, newest first. Every sort breaks ties by callsign.

- [ ] **Step 1: Write the failing tests**

```python
def test_regulars_from_past_sessions(conn, live, w2kv):
    net_id = NetRepository(conn).get_session(w2kv).net_id
    tonight = NetRepository(conn).start_session(net_id, "2026-11-02").id
    view = live.view(tonight)
    assert view.rows == [] and len(view.regulars) == len(NetRepository(conn).checkins(w2kv))
    row = next(r for r in view.regulars if r.callsign == "W2KV")
    assert row.attendance_text == "1 of last 1" and row.last_seen == "2026-10-26"
    assert row.bearing_deg == pytest.approx(354, abs=1)

def test_sort_regulars_each_key():  # acceptance 40; build 3 RegularRow by hand: one with grid None/"Grid needed"
    # callsign A→Z; grid A→Z, missing last; direction ascending, None last; last newest first

def test_regular_without_grid(conn, live):  # Review Focus 3
    # past session with a check-in "K1ABC" and no grid, no station grid
    # → grid_text == "Grid needed", bearing None; target(..., "regular", None, callsign="K1ABC") is None

def test_aim_resolves_and_sends_nothing(live, w2kv, sim):
    view, aim = live.aim(w2kv, "FN20")
    assert aim is not None and aim[1] == pytest.approx(view.bearing_deg)
    assert live.aim(w2kv, "W")[1] == ("W", 270.0)  # match the label the resolver actually gives
    assert live.aim(w2kv, "K9ZZZ")[1] is None       # unknown call → no target
    assert sim.commands == []

def test_rotate_typed_and_regular_one_command_each(live, w2kv, desk, sim):
    rotator = desk.rotators()[0].id
    live.rotate(w2kv, rotator, "typed", None, typed=("W", 270.0))
    assert len(sim.commands) == 1

def test_view_last_time_and_closed(conn, live, w2kv):
    nets = NetRepository(conn); nets.close_session(w2kv, "try 30°")
    nxt = nets.start_session(nets.get_session(w2kv).net_id, "2026-11-02").id
    assert live.view(nxt).last_time == ("2026-10-26", "try 30°")
    assert live.view(w2kv).closed is True
```

Fill in the two sketched tests with real rows and assertions matching the sort rules above.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_live_net.py -v`. Expected: the new tests fail.
- [ ] **Step 3: Implement** the interfaces above in `live_net.py`. In `ui/live_net.py`, temporarily switch its `view.expected` loop to `view.regulars` (same grey text) so the page still loads. Task 3 replaces it.
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check . && uv run mypy src/beam_navigator/core`. Expected: all pass.
- [ ] **Step 5: Commit** `feat: live net regulars, sorting and typed targets`

---

### Task 3: Participant screen — Aim box, Regulars list, Last time card

**Files:**
- Modify: `src/beam_navigator/ui/live_net.py`
- Modify: `src/beam_navigator/ui/app.py` (`/net/{id}` passes a `NetControl` and `qrz`)
- Test: `tests/ui/test_live_net_page.py`

**Interfaces:**
- Consumes: Task 2's `LiveNet.aim`, `target`/`rotate` keywords, `RegularRow`, `sort_regulars`, `view.last_time`.
- Produces: `live_net_page(control: NetControl, session_id: int, qrz: QrzClient | None = None) -> None`, which uses `control.live` for everything `LiveNet` does today. Markers: `aim`, `aim-result`, `add-tonight`, `regular-{CALL}`, `heard-regular-{CALL}`, `regular-sort`, `last-time`.

UI rules (spec sections 1, 2 and 4):
- The Aim box sits above the Rotate controls. Its `keydown.enter` handler calls `live.aim`, shows the title, bearing text, distance and message in `aim-result`, sets `state.mode = "typed"` and `state.typed`, refreshes controls, then blurs (`BLUR_ACTIVE`) so Ctrl+Enter works next. If the target is a callsign that isn't in tonight's rows, show the `add-tonight` link. Task 4 wires it to the I-hear line. For now it only fills the I-hear callsign.
- The mode toggle gets the options Controller / Station / Typed. Clicking a Tonight row sets `"station"`. Clicking a Regulars row sets `"regular"` with `state.callsign`. Snap back sets `"controller"`.
- The Regulars section is titled `Regulars not heard yet (N)`. Each row shows callsign, name, grid_text, `From you: …`, distance, attendance and last seen, and is clickable, selected style `bg-blue-1` like Tonight. The `heard-regular-{CALL}` button is wired in Task 4. Its own `regular-sort` select has the options `{"last": "Last check-in", "callsign": "Callsign", "grid": "Grid", "direction": "Direction"}` and defaults to `"last"`.
- Filter and sort (spec "Filter and sort"): remove the old `filter` input and the general `sort` select. The Aim box's value change sets `state.filter_text`, and `filter_rows` applies it to both lists. Tonight's heading has its own `tonight-sort` select, `{"roster": "Check-in order", "callsign": "Callsign", "bearing": "Direction", "distance": "Distance"}`, defaulting to `"roster"`. The `SortKey` values stay the same and only the labels change.
- The `last-time` card goes above the controller card, `Last time ({date})`, with the notes. It's absent when `view.last_time` is `None`.

- [ ] **Step 1: Write the failing UI tests** (reuse the file's `desk`, `sim`, `open_net` fixtures; start a second session of the W2KV net for "tonight")

```python
async def test_aim_enter_sends_nothing(user, desk, w2kv, sim):  # acceptance 37
    await open_net(user, desk, w2kv)
    user.find(marker="aim").type("FN20").trigger("keydown.enter")
    await user.should_see("Rotate VHF to")
    assert sim.commands == []

async def test_regular_click_sends_nothing_then_rotate_once(user, desk, conn, w2kv, sim):  # 39
    tonight = NetRepository(conn).start_session(NetRepository(conn).get_session(w2kv).net_id,
                                                "2026-11-02").id
    await open_net(user, desk, tonight)
    await user.should_see("Regulars not heard yet")
    user.find(marker="regular-W2KV").click()
    assert sim.commands == []
    user.find(marker="rotate").click()
    await user.should_see("Simulated:")
    assert len(sim.commands) == 1

async def test_last_time_card(user, desk, conn, w2kv):  # acceptance 44 (UI half)
    nets = NetRepository(conn); nets.close_session(w2kv, "try 30°")
    nxt = nets.start_session(nets.get_session(w2kv).net_id, "2026-11-02").id
    await open_net(user, desk, nxt)
    await user.should_see("Last time (2026-10-26)")
    await user.should_see("try 30°")
```

Acceptance 38 (after Enter in Aim, Ctrl+Enter sends exactly one command) is covered by `test_rotate_typed_and_regular_one_command_each` in Task 2 plus the existing hotkey tests. If `User` can send Ctrl+Enter to `ui.keyboard`, add a UI version too.

- [ ] **Step 2: Run** `uv run pytest tests/ui/test_live_net_page.py -v`. Expected: the new tests fail. The existing ones still pass after the `app.py` signature change.
- [ ] **Step 3: Implement** per the UI rules.
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check .`. Then start the app (`uv run beamnav-ui`), start a session of an example net, and check the Aim box, the Regulars sorts and Rotate in Simulation by hand.
- [ ] **Step 5: Commit** `feat: participant screen aim box, regulars list and last time card`

---

### Task 4: Shared entry line — "I hear" on the participant screen

**Files:**
- Create: `src/beam_navigator/ui/entry_line.py`
- Modify: `src/beam_navigator/ui/control.py` (use the shared entry line; no behavior change)
- Modify: `src/beam_navigator/entry_keys.py` (`next_field`/`previous_field` take `fields`)
- Modify: `src/beam_navigator/net_control.py` (`log_heard`)
- Modify: `src/beam_navigator/ui/live_net.py`
- Test: `tests/ui/test_live_net_page.py`, `tests/unit/test_net_control.py`, `tests/unit/test_entry_keys.py`; `tests/ui/test_control.py` must pass unchanged.

**Interfaces:**
- Produces:
  - `next_field(field: str, fields: tuple[str, ...] = FIELDS) -> str`, `previous_field(...)` the same
  - `NetControl.log_heard(session_id: int, entry: Entry, update_record: bool = False) -> CheckIn` = `log(...)` followed by `nets.set_heard(id, "heard", None)`; returns the check-in re-read
  - `NetControl.merge_into_existing` unchanged
  - `entry_line(control: NetControl, session_id: int, *, fields: tuple[str, ...], qrz: QrzClient | None, on_logged: Callable[[], None], on_callsign: Callable[[str], None] = lambda _: None, on_note: Callable[[str], None] | None = None, heard: bool = False) -> EntryLine`
  - `EntryLine` exposes `fill_callsign(call: str) -> None` (sets the callsign, runs autofill and focuses the next field) and `set_enabled(on: bool) -> None`.
  - `heard=True` logs through `log_heard`, otherwise through `log`.
  - Markers stay `entry-{field}`, `suggestions`, `qrz-lookup`, so the control tests keep passing.

Move everything in `control_page` from `entry()` through `update_existing()`, plus the duplicate and changes dialogs and the suggestions list, into `entry_line`. It keeps its own `_State`. The control page passes `fields=FIELDS`, `on_logged=table.refresh`, `on_callsign=lambda _: info.refresh()` and `on_note=open note dialog`. The note dialog and info panel stay in `control.py`. With `on_note=None` the note key does nothing. The participant screen passes `fields=("callsign", "name", "grid")` and `heard=True`, and its `on_logged` refreshes Tonight and Regulars. The Regulars Heard button calls `control.log_heard(session_id, Entry(callsign=call, name=record name, grid=record grid))` using `control.autofill(call)`. It never asks about changes, because it copies the record.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_entry_keys.py
def test_next_field_within_given_fields():
    three = ("callsign", "name", "grid")
    assert next_field("grid", three) == "grid" and previous_field("callsign", three) == "callsign"

# tests/unit/test_net_control.py
def test_log_heard_marks_heard_and_saves_for_next_session(...):  # acceptance 42
    # start s1, log_heard(Entry("K3WGR", name="Pete", grid="FN10")) → heard_state "heard"
    # start s2 of same net → LiveNet.view(s2).regulars has K3WGR with grid FN10 and a bearing

def test_log_heard_keeps_record_unless_asked(...):  # acceptance 43
    # station K3WGR saved with grid FN10; log_heard(..., grid="FN11") → record still FN10;
    # log_heard(..., update_record=True) on a new session → record FN11

# tests/ui/test_live_net_page.py
async def test_i_hear_logs_and_moves_regular(user, desk, conn, w2kv, sim):
    # tonight session; type "W2KV" in entry-callsign, Enter, Enter → W2KV in Tonight,
    # gone from Regulars; sim.commands == []

async def test_i_hear_duplicate_asks(user, ...):  # Review Focus 4
    # log W2KV, then type W2KV again and Enter twice → should_see("Already checked in")

async def test_heard_button_sends_nothing(user, ...):  # acceptance 39
    # click heard-regular-W2KV → W2KV under Tonight; sim.commands == []

# tests/ui/test_control.py (new test; existing tests unchanged)
async def test_control_closed_session_refuses_log(user, ...):  # Review Focus 2
    # close the session; type a call, Enter twice → should_see("This session is closed")
```

Fill in each sketched test with the real fixture calls from its file.

- [ ] **Step 2: Run** the four test files. Expected: the new tests fail, and `tests/ui/test_control.py`'s existing tests pass.
- [ ] **Step 3: Implement** `entry_keys` and `log_heard`, then extract `entry_line`, then use it in both pages. Run `tests/ui/test_control.py` after the extraction and before touching the participant screen.
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check . && uv run mypy src/beam_navigator/core`. Expected: all pass.
- [ ] **Step 5: Commit** `feat: I hear entry line on the participant screen, shared with net control`

---

### Task 5: Close my session, read-only when closed, Reopen

**Files:**
- Modify: `src/beam_navigator/ui/live_net.py`
- Modify: `src/beam_navigator/ui/control.py` (Last time card; entry line disabled when closed)
- Modify: `src/beam_navigator/ui/nets.py` (session rows show the first line of the notes)
- Test: `tests/ui/test_live_net_page.py`, `tests/ui/test_nets_page.py`, `tests/unit/test_export.py`

**Interfaces:**
- Consumes: Task 1's `close_session`/`reopen_session`, Task 2's `view.closed`/`last_time`, and Task 4's `EntryLine.set_enabled`.
- Markers: `close-session`, `close-notes`, `close-confirm`, `reopen`, `closed-badge`.

Rules: **Close my session…** opens a dialog with a textarea labeled "Notes for next time", plus Close and Cancel buttons. Close calls `close_session` and navigates to `/nets/{net_id}`. A closed session shows a `Closed` badge and a Reopen button. The entry line is disabled and the heard selects and Heard buttons are disabled. Aim, Rotate and Snap back still work. Reopen calls `reopen_session` and refreshes. The net control page shows the same `last-time` card using `control.live.view(session_id).last_time`, and disables its entry line when closed. On the Nets page, each session row adds `· {first line of notes}` when there are notes.

- [ ] **Step 1: Write the failing tests**

```python
async def test_close_with_notes_then_next_session_shows_them(user, desk, conn, w2kv):  # 44
    await open_net(user, desk, w2kv)
    user.find(marker="close-session").click()
    user.find(marker="close-notes").type("try 30° for K3WGR")
    user.find(marker="close-confirm").click()
    assert NetRepository(conn).get_session(w2kv).status == "closed"
    # next session of same net shows it; a session of another net does not

async def test_closed_session_read_only_rotate_works(user, desk, conn, w2kv, sim):  # 45
    NetRepository(conn).close_session(w2kv, "")
    await open_net(user, desk, w2kv)
    await user.should_see("Closed")
    # entry-callsign disabled; rotate click → exactly one command
    user.find(marker="reopen").click()
    # entry-callsign enabled again

def test_closing_notes_never_exported(conn, ...):  # acceptance 46, in tests/unit/test_export.py
    # close a W2KV session with notes "SECRET-NOTE"; export text, csv, json;
    # assert "SECRET-NOTE" not in any output
```

- [ ] **Step 2: Run** the three files. Expected: the new tests fail.
- [ ] **Step 3: Implement** per the rules.
- [ ] **Step 4: Run** `uv run pytest -q && uv run ruff check .`. Then by hand in the app: close a session with notes, start the next one, and see the card.
- [ ] **Step 5: Commit** `feat: close my session with notes for next time (acceptance 44-46)`

---

### Task 6: Docs

**Files:**
- Modify: `docs/requirements.md` (4.4 and section 7)
- Modify: `docs/decisions.md`
- Modify: `docs/user-guide.md`

- [ ] **Step 1:** In requirements 4.4, add bullets for the Aim at box, Regulars with its four sorts, the I-hear line and Close my session, each worded as in the spec. In section 7, add a "Participant" group with tests **37–47**, mapped from spec A, B, C, C2, C3, D, E, F, G, H, I in that order. Renumber nothing else.
- [ ] **Step 2:** Add decision 42 (owner, 2026-10-30). It covers: the participant screen works without a roster; Regulars default to Last check-in with ties by callsign; Last time means the latest closed session of the same net, and empty notes show no card; a closed session is read-only with Reopen, and pointing still works; closing notes are private and not exported; the entry line is shared with net control.
- [ ] **Step 3:** Add a "Following a net as a participant" section to the user guide covering Start session, Regulars, Aim at, I hear, Rotate, and Close my session.
- [ ] **Step 4:** Make sure every test cited as acceptance 37–47 in Tasks 2–5 has its number in a comment. Run `uv run pytest -q` and `uv run ruff check .` one last time.
- [ ] **Step 5: Commit** `docs: participant net screen in requirements, decisions and user guide`
