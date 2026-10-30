# Milestone 2a — Rotator Profiles and the Rotate Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rotator profiles that describe each rotor's own travel (north stop, south stop, Yaesu 450° overlap, offset), a move planner that shows direction, long-way and time before anything is sent, and a Rotate service that sends exactly one command per press and logs it.

**Architecture:** `rotators/travel.py` is pure: it turns a true heading into rotor positions inside a profile's travel range and plans the move. Rotor offset is applied there, inside the rotator layer, never in bearings (invariant 4). `store/` gains rotator profiles and a command log (migration 0002). `rotators/service.py` is the only code that sends a move: `rotate()` is called once per Rotate press; `preview()` and `test_connection()` never move anything.

**Tech Stack:** Python 3.12 stdlib, `sqlite3`. No new dependencies. No UI in this plan (plans 2b–2d).

**Spec:** `docs/requirements.md` v2.0 — invariants 2, 4, 6, 7, 8; section 4.7; section 7 tests 25–29. `docs/rotator-notes.md` (PstRotatorAz behaviour). Owner direction 2026-10-27: rotators differ; Yaesu rotors have 450° of travel; each profile describes its own.

## Design

**Travel range.** Each profile has `az_min`, `az_max` in rotor degrees and an `offset` (rotor reading = true heading + offset). Presets: north stop `0–360`, south stop `180–540`, Yaesu 450° `0–450`. A true heading `T` can be reached at every rotor position `T + offset + 360·k` inside `[az_min, az_max]`.

**Choosing a position.** With a known current rotor position, take the reachable position nearest to it (ties: the lower). With no position, take the lowest reachable position and mark the path unverified. No reachable position → rejected, nothing sent (invariant 7).

**Per adapter.**
- `simulation` and `hamlib` take the chosen rotor position directly (`rotctld` accepts e.g. 0–450 when the rotor is set up that way).
- `pstrotator`'s documented command takes 0–359 only, so it is sent `position mod 360` and PstRotatorAz picks the path. The plan says so and marks the path unverified (invariant 6: never claim what we cannot verify).

## Global Constraints

- **No movement without an explicit press** (invariant 2): only `RotateService.rotate()` calls `set_azimuth`/`stop` on an adapter. `preview()`, `test_connection()`, saving profiles, and every store method send nothing.
- **Simulation by default** (invariant 8): a new profile is simulated; live needs a passed connection test and an explicit switch; changing adapter, host or port resets both.
- **Truthful status** (invariant 6): without feedback the status is exactly `"Command sent — position unverified"`.
- **Mechanical limits** (invariant 7): outside travel is rejected with the reason, never wrapped.
- **Timeouts and errors are reported, never retried** (spec 4.7). A failed command is not resent.
- Every command attempt, including rejections, is logged: time, rotator, target, requested heading, what was sent, result, measured heading (spec 4.7).
- Protocol strings stay exactly as in `docs/rotator-notes.md` and the existing adapters (CLAUDE.md rule 4).
- Match the existing code: 4-space indentation, line length 100, `ruff`, `mypy --strict` on `src/beam_navigator`.

## Review Focus

1. **Offset pushes a heading across the stop:** north stop, offset +10°, target 355° → rotor 5°, not 365° (rejected) or a wrapped guess. Test in Task 1.
2. **PstRotatorAz on a 450° rotor reports 0–359:** a reading of 40° may really be 400° → the plan never states a confident direction for PstRotator. Test in Task 1.
3. **Profile edited after a passed test** (host or port changed) → back to simulation, test required again. Test in Task 2.
4. **Adapter fails mid-press** (connect refused, timeout on the position read after the move) → one command at most, reported and logged, not retried. Test in Task 4.
5. **Non-finite numbers** (NaN target, NaN or reversed travel range) → rejected before anything is sent or saved. Tests in Tasks 1 and 2.

---

### Task 1: Travel ranges and move planning

**Files:**
- Create: `src/beam_navigator/rotators/travel.py`
- Test: `tests/unit/test_travel.py`

**Interfaces:**
- Produces:
  - `TravelRange(az_min: float, az_max: float, offset: float = 0.0)` frozen dataclass.
  - `PRESETS: dict[str, TravelRange]` — `"North stop (0–360°)": TravelRange(0, 360)`, `"South stop (180–540°)": TravelRange(180, 540)`, `"Yaesu 450° (0–450°)": TravelRange(0, 450)`.
  - `travel_error(travel: TravelRange) -> str | None` — all values finite; `az_max > az_min`; `az_max - az_min <= 540`; `-180 <= offset <= 180`.
  - `positions(target_true: float, travel: TravelRange) -> list[float]` — ascending.
  - `MovePlan` frozen dataclass: `target_true: float`, `rotor_target: float | None`, `command_deg: float | None` (what the adapter is sent), `rotor_from: float | None`, `direction: Literal["clockwise", "counter-clockwise"] | None`, `travel_deg: float | None`, `long_way: bool`, `seconds: float | None`, `path_verified: bool`, `error: str | None`, `note: str | None`.
  - `plan_move(target_true: float, travel: TravelRange, current_rotor: float | None, speed_deg_per_s: float | None = None, adapter_chooses_path: bool = False) -> MovePlan`.
  - Exact strings: rejection `f"{target:g}° is outside this rotator's travel ({az_min:g}–{az_max:g}°). Nothing was sent."`; note `"PstRotatorAz chooses the path; the direction shown is not guaranteed."`.

- [ ] **Step 1: Write the failing tests.**

| Test | Travel | Current | Target | Expect |
|---|---|---|---|---|
| `test_north_stop_long_way` | 0–360 | 350 | 10 | rotor 10, counter-clockwise, travel 340, long_way, path_verified |
| `test_yaesu_overlap_takes_short_way` | 0–450 | 350 | 10 | positions `[10, 370]`; rotor 370, clockwise, travel 20, not long_way |
| `test_yaesu_unknown_position` | 0–450 | None | 10 | rotor 10, direction None, travel None, not path_verified |
| `test_south_stop` | 180–540 | 190 | 170 | rotor 530, clockwise, travel 340, long_way |
| `test_outside_travel_rejected` | 0–350 | 0 | 355 | error equals the rejection string; rotor_target and command_deg None |
| `test_offset_crosses_stop` (Focus 1) | 0–360, offset 10 | 0 | 355 | rotor 5; command_deg 5 |
| `test_time_estimate` | 0–360 | 0 | 90, speed 2 | seconds 45; speed None → seconds None |
| `test_pstrotator_path_unverified` (Focus 2) | 0–450, chooses path | 40 | 30 | command_deg 30 (in 0–359); path_verified False; note equals the note string |
| `test_pstrotator_command_is_modulo_360` | 0–450, chooses path | 350 | 10 | rotor 370, command_deg 10 |
| `test_non_finite_target_rejected` (Focus 5) | 0–360 | 0 | NaN, inf, -1, 360 | error set, command_deg None |

Plus `test_travel_error` returning a message for `(0, 0)`, `(10, 5)`, `(0, 800)`, `(nan, 360)`, offset 200, and `None` for each preset; and `test_ties_take_the_lower_position` (travel 0–540, current 180, target 0 → positions `[0, 360]`, both 180 away → rotor 0).

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_travel.py -v`. Expected: FAIL, `ModuleNotFoundError`.
- [ ] **Step 3:** Implement. `plan_move` first checks `travel_error` and that `0 <= target_true <= 359.9` (finite), then `positions`, then chooses as in **Design**. `long_way` is `travel_deg > 180`.
- [ ] **Step 4:** Run tests, `uv run ruff check .`, `uv run mypy src/beam_navigator`. Expected: PASS.
- [ ] **Step 5:** Commit `feat: rotor travel ranges and move planning (north, south, 450° overlap)`.

---

### Task 2: Rotator profiles and command log in the store

**Files:**
- Create: `src/beam_navigator/store/migrations/0002_rotators.sql`
- Modify: `src/beam_navigator/core/models.py`, `src/beam_navigator/store/repositories.py`, `tests/unit/test_store_db.py` (`SCHEMA_VERSION == 2`, new tables)
- Test: `tests/unit/test_store_rotators.py`

**Interfaces:**
- Consumes: `TravelRange`, `travel_error`.
- Produces in `core/models.py`:
  - `RotatorProfile(id: int | None, name: str, adapter: Literal["simulation","pstrotator","hamlib"], host: str | None, port: int | None, az_min: float, az_max: float, offset: float, speed_deg_per_s: float | None, bands: tuple[str, ...], live: bool, connection_tested: bool)`.
  - `CommandRecord(id: int, at: str, rotator_id: int, target_label: str | None, requested_true: float | None, sent: str | None, ok: bool, message: str, measured: float | None)`.
- Produces in `store/repositories.py`:
  - `RotatorNotTested(Exception)`.
  - `RotatorRepository(conn)`: `save(profile) -> RotatorProfile` (validates travel and `speed_deg_per_s > 0` when set; `ValueError` otherwise; a new profile is always stored with `live=False, connection_tested=False`; an update that changes `adapter`, `host` or `port` resets both; `live`/`connection_tested` in the argument are ignored), `get(id) -> RotatorProfile`, `list() -> list[RotatorProfile]`, `record_connection_test(id, ok: bool) -> None` (a failed test also clears `live`), `set_live(id, live: bool) -> None` (raises `RotatorNotTested` when switching on without a passed test; `ValueError` for a `simulation`-type profile).
  - `CommandLog(conn)`: `add(rotator_id: int, target_label: str | None, requested_true: float | None, sent: str | None, ok: bool, message: str, measured: float | None) -> None`, `recent(rotator_id: int, limit: int = 50) -> list[CommandRecord]` (newest first).

`0002_rotators.sql`: table `rotator_profile` with the columns above (`bands TEXT NOT NULL DEFAULT ''` stored comma-joined, `live` and `connection_tested INTEGER NOT NULL DEFAULT 0`, `CHECK (adapter IN ('simulation','pstrotator','hamlib'))`, `CHECK (az_max > az_min)`); table `rotator_command` with `rotator_id INTEGER NOT NULL REFERENCES rotator_profile (id) ON DELETE RESTRICT` and an index on `(rotator_id, id)`.

- [ ] **Step 1: Write the failing tests.**
  - Acceptance 25: a saved new PstRotator profile has `live is False`; even when the argument said `live=True`. `set_live(id, True)` raises `RotatorNotTested`; after `record_connection_test(id, True)` it succeeds.
  - Focus 3: after a passed test and `set_live(True)`, saving the profile with a different `port` gives `live is False` and `connection_tested is False`; saving with only a new `name` keeps both.
  - A failed `record_connection_test` clears `live`.
  - `set_live` on a `simulation` profile raises `ValueError`.
  - Focus 5: `save` with travel `(10, 5)`, `(nan, 360)`, or `speed_deg_per_s=0` raises `ValueError`; nothing stored.
  - Yaesu preset round-trips: `az_min 0`, `az_max 450`, `bands ("2 m", "70 cm")`.
  - `CommandLog.recent` returns newest first and keeps a rejected attempt (`ok=False`, `sent=None`).
  - `test_store_db.py`: `SCHEMA_VERSION == 2`; a version-1 database file upgrades to 2 and keeps its aliases.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: rotator profiles start in simulation; command log (acceptance 25)`.

---

### Task 3: Adapters accept the profile's travel

**Files:**
- Modify: `src/beam_navigator/rotators/base.py`, `hamlib.py`, `simulation.py`, `pstrotator.py`
- Test: `tests/unit/test_hamlib.py`, `tests/unit/test_simulation.py`, `tests/unit/test_pstrotator.py`

**Interfaces:**
- Produces:
  - `Capabilities` gains `chooses_path: bool = False`; `PstRotatorAdapter.capabilities()` sets it `True`.
  - `range_error(deg: float, az_min: float, az_max: float) -> str | None` in `base.py`, same wording style as `azimuth_error` (`f"Position {deg:g}° is outside {az_min:g}–{az_max:g}°. Nothing was sent."`); `azimuth_error` stays for PstRotator and the spike CLI.
  - `HamlibAdapter(host, port, timeout_s, az_min: float = 0.0, az_max: float = 359.9)` and `SimulationAdapter(start_azimuth, speed_deg_per_s, clock, az_min: float = 0.0, az_max: float = 359.9)` validate `set_azimuth` with `range_error`. The protocol parameter is renamed `deg` ("degrees in this adapter's command range").

- [ ] **Step 1: Write the failing tests.** `HamlibAdapter(az_min=0, az_max=450)` sends exactly `P 400.0 0.0` for 400 and rejects 451 without sending; default construction still rejects 400 (spike CLI unchanged). `SimulationAdapter(az_max=450)` moves to 400 along the numeric path. `PstRotatorAdapter().capabilities().chooses_path is True`; Hamlib and Simulation `False`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. No change to any protocol string.
- [ ] **Step 4:** Run the full suite (including `test_cli.py` for the spike), ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: Hamlib and simulation adapters accept a 450° travel range`.

---

### Task 4: Rotate service

**Files:**
- Create: `src/beam_navigator/rotators/service.py`
- Modify: `docs/rotator-notes.md` (add live-test row 5: "Yaesu-style overlap: command 10° with the rotor at 350°; which way does PstRotatorAz turn?"), `docs/decisions.md` (decision 15: travel model and PstRotator path note)
- Test: `tests/unit/test_rotate_service.py`

**Interfaces:**
- Consumes: Tasks 1–3; `RotatorRepository`, `CommandLog`.
- Produces:
  - `build_adapter(profile: RotatorProfile) -> RotatorAdapter` — not `live` → `SimulationAdapter(start_azimuth=profile.az_min, speed_deg_per_s=profile.speed_deg_per_s, az_min=..., az_max=...)`; live `pstrotator` → `PstRotatorAdapter(host, port)`; live `hamlib` → `HamlibAdapter(host, port, az_min=..., az_max=...)`.
  - `RotateOutcome` frozen dataclass: `plan: MovePlan`, `sent: bool`, `ok: bool`, `status: str`, `measured: float | None`.
  - `RotateService(conn: sqlite3.Connection, adapter_for: Callable[[RotatorProfile], RotatorAdapter] = build_adapter)`:
    - `preview(rotator_id: int, target_true: float, current_rotor: float | None = None) -> MovePlan` — no adapter is built or connected.
    - `rotate(rotator_id: int, target_label: str, target_true: float) -> RotateOutcome` — connect; read position only if `has_feedback` (a read error leaves it `None`); `plan_move(..., adapter_chooses_path=caps.chooses_path)`; on plan error: log `ok=False, sent=None`, return `sent=False`; else exactly one `set_azimuth(plan.command_deg)`; then one position read if `has_feedback`; log; `disconnect()` in `finally`.
    - Status strings: no feedback → `"Command sent — position unverified"`; read failed → `f"Command sent — position unverified ({reason})"`; measured → `f"Commanded {target:.1f}°, measured {measured:.1f}°"`; command failed → the adapter's message; connect failed → the connection message.
    - `test_connection(rotator_id: int) -> ConnectionResult` — connect, read position if supported, disconnect, `record_connection_test`; never calls `set_azimuth` or `stop`.
    - `stop(rotator_id: int) -> CommandResult` — the explicit Stop press (spec 4.7): `ValueError` when the adapter's `has_stop` is false; otherwise exactly one `stop()`, logged like a rotate (`target_label="Stop"`, `requested_true=None`). The UI text that Stop does not replace the controller's physical stop belongs to plan 2b.

- [ ] **Step 1: Write the failing tests** (a real `SimulationAdapter` captured by an `adapter_for` that returns it; small fakes for no-feedback and failures).
  - Acceptance 26: three `rotate()` calls → `len(sim.commands) == 3`; `preview()` ×5 and `test_connection()` → no further commands; saving a profile → none.
  - Acceptance 27: travel 0–350, `rotate(..., 355)` → `sent is False`, `sim.commands == []`, status is the rejection string, one log row with `ok=False`.
  - Acceptance 28: fake adapter with `has_feedback=False` → status `"Command sent — position unverified"`, `measured is None`.
  - Acceptance 29 / Focus 4: fake whose position read after the move raises `RotatorError("No reply … Not retried.")` → exactly one `set_azimuth` call, status starts with `"Command sent — position unverified ("`, logged once; fake whose `connect` fails → zero `set_azimuth`, status is the connection message.
  - Yaesu 0–450 simulated at 350 → `rotate(..., 10)` sends 370; `outcome.plan.direction == "clockwise"`.
  - A non-live PstRotator profile uses the simulation adapter (`build_adapter(profile)` is a `SimulationAdapter`).
  - Every outcome writes exactly one `CommandLog` row with target label and requested heading.
  - `stop()` on a simulated profile → one `"stop"` in `sim.commands`, one log row; on a fake with `has_stop=False` → `ValueError`, nothing sent.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement; then add the rotator-notes row and decision 15.
- [ ] **Step 4:** Run the full suite, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: one-press Rotate service with preview and command log (acceptance 26-29)`.
