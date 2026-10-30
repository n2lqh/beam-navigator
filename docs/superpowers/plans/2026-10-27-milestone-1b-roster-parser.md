# Milestone 1b — Roster Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `parse_roster(text)` turns any of the six real rosters into check-in rows with the expected callsigns, grids, controller and published bearings, and `beamnav parse roster.txt --from FM29pt` prints them with bearings from the user.

**Architecture:** One pure module, `core/roster_parser.py`. Text is normalized, then each line is matched against a small set of line formats seen in the fixtures. Records are only accepted in the shapes below; everything else is narrative. Lines inside the roster block that match no format become "unparsed text" rows, never dropped.

**Tech Stack:** Python 3.12 stdlib (`re`, `dataclasses`). Reuses `core/callsign.py`, `core/maidenhead.py`, `core/lookup.py` from plan 1a.

**Spec:** `docs/requirements.md` v2.0 — sections 2 (invariants 3, 5, 9), 4.3, 7 (fixtures table, cross-fixture notes, parser rules, tests 11, 12, 32, 33).

## Global Constraints

- `core/` stays pure: stdlib plus other `core` modules only. No new dependencies.
- Deterministic and offline. No LLM, no network (spec 4.3).
- **Fixture files are never edited, regenerated or "fixed"** (CLAUDE.md rule 4). Tests read them with `Path.read_text(encoding="utf-8")`.
- Never invent a row, grid or controller. Never add or drop rows to make a stated count agree (spec 7).
- Grid text is kept exactly as printed (`FN20LE`, `fm29`); matching is case-insensitive.
- Published bearings are kept as the printed text (`"0°"`), display-only (invariant 3). Nothing in this plan computes a heading from them.
- No date, net, band or frequency is read from the text; the import dialog supplies them (spec 7 note). The parser output has no date field.
- Match the existing code: 4-space indentation, line length 100, `ruff`, `mypy --strict`.

## Line formats

Each record shape seen in the fixtures. `CALL` = `is_callsign`, `GRID` = `is_grid`, `TAG` = controller tag.

| Id | Shape | Fixtures |
|---|---|---|
| A | `N[.)] CALL NAME QTH… [GRID] [B°] [TAG]` on one line; space after the number optional | N3RG, WB2RVX |
| B/C | one or more `CALL GRID [TAG]` items separated by commas | KC3BVL (one per line), WA3NUF (four per line) |
| D | `NAME CALL [TAG]` — only in a run of 2+ consecutive D lines | KA3WXV |
| E | three lines: `CALL [TAG]` / `NAME` / `QTH GRID` | W2KV |

- **TAG**: `(net control)`, `Net Control`, `NC`, case-insensitive, at the end of the record. A bare `NC` directly after a comma (`RALEIGH, NC`) is a state, not a tag.
- **NAME** is one word in A and E; in D it is everything before the call.
- **Trailer**: every line after a line starting with `73` is excluded (sign-offs "73 de / N3RG Ray G", "73 and CU next week, / Dave W2KV").
- **Roster block**: from the first record line to the last. A non-blank line inside it that is not part of a record becomes an unparsed row. Lines outside it are narrative and ignored (the raw text is kept by the store, invariant 9).
- URLs (`\S+://\S+`) and email addresses are removed from a line before matching.

## Review Focus

1. **State abbreviation NC vs net-control tag:** `1 W4XX BOB RALEIGH, NC` → not controller, QTH `RALEIGH, NC`. Test in Task 1.
2. **Mixed-case calls in rows:** `3 k3wgr AL WERNERSVILLE, PA FN10xh` → callsign `K3WGR`, grid text unchanged. Test in Task 1.
3. **Paste damage:** CRLF, non-breaking spaces, tabs, a leading BOM → same rows as the clean text. Test in Task 4.
4. **Roster pasted twice:** every row from the second copy is kept and flagged as a duplicate, none dropped. Test in Task 4.
5. **Garbage and huge pastes:** NUL and control characters, 1 MB of prose → no exception, finishes under 2 s, zero rows. Test in Task 4.

---

### Task 1: Data model, normalization and numbered rows (N3RG, WB2RVX)

**Files:**
- Create: `src/beam_navigator/core/roster_parser.py`
- Test: `tests/unit/test_roster_parser.py`

**Interfaces:**
- Consumes: `is_callsign`, `normalize_callsign`, `base_callsign` (`core/callsign.py`); `is_grid` (`core/maidenhead.py`).
- Produces:
  - `RosterRow` frozen dataclass: `line: int` (1-based, first line of the record), `text: str` (source lines joined by `"\n"`), `sequence: int | None`, `callsign: str | None` (normalized; `None` for unparsed), `name: str | None`, `qth: str | None`, `grid: str | None` (as printed), `published_bearing: str | None` (as printed, e.g. `"35°"`), `is_controller: bool`, `confidence: Literal["high", "medium", "low"]` (high = call + grid, medium = call without grid, low = unparsed), `warnings: tuple[str, ...]`.
  - `ParseResult` frozen dataclass: `rows: tuple[RosterRow, ...]`, `controller: str | None`, `stated_checkins: int | None`, `stated_grids: int | None`, `warnings: tuple[str, ...]`; property `checkins -> tuple[RosterRow, ...]` (rows with a callsign).
  - `parse_roster(text: str) -> ParseResult`.
  - `controller` is the callsign of the first row with a tag; later tagged rows keep `is_controller=True` and add the result warning.
  - Exact warning strings: row `"Grid missing"`, `"Duplicate of row {n}"` (`n` = 1-based position in `rows`), `"Unparsed text"`; result `"Text says {n} check-ins; {m} parsed."`, `"Text says {n} grids; {m} parsed."`, `"More than one controller tag."`.

- [ ] **Step 1: Write the failing tests.** Helper `load(name) -> ParseResult` reads `tests/fixtures/<name>` and parses it.

```python
N3RG_CALLS = ["K1DY", "AF3G", "K3WGR", "N3ITT", "N3FTI", "K3JJZ", "N2DEQ", "KC2PHM", "N2QVY",
              "N1DSB", "KE2IVT", "KA3WXV", "N2SCJ", "KA3FQS", "W2KV", "KF2Z", "KC3ZZU", "W1XR",
              "K4SO", "KD4AA", "N2LQH", "N3RG"]

def test_n3rg_fixture():  # acceptance 11
    result = load("n3rg_50mhz_2026-10-26.txt")
    assert [r.callsign for r in result.checkins] == N3RG_CALLS
    assert [r.sequence for r in result.checkins] == list(range(1, 23))
    assert result.controller == "N3RG"
    row = {r.callsign: r for r in result.checkins}
    assert row["N3RG"].grid == "FM29ki" and row["N3RG"].is_controller
    assert row["N2LQH"].grid == "FM29pt" and row["N2LQH"].published_bearing == "35°"
    assert row["N3ITT"].published_bearing == "0°"
    assert row["N1DSB"].grid == "fm29" and row["N1DSB"].published_bearing is None
    assert row["KF2Z"].published_bearing is None
    assert row["K1DY"].name == "BILL" and row["K1DY"].qth == "TROY, ME"
    assert row["N2SCJ"].qth == "MAPLE SHADE, NJ"
    assert "W3CCX" not in row                       # inside the URL
    assert result.stated_checkins == 22
    assert result.warnings == ()                     # 22 matches 22; sign-off is not a 2nd N3RG

def test_wb2rvx_fixture():  # acceptance 11
    result = load("wb2rvx_432mhz_2026-10-26.txt")
    assert len(result.checkins) == 10
    assert result.checkins[0].callsign == "K3JJZ" and result.checkins[0].sequence == 1
    assert result.controller == "WB2RVX"
    last = result.checkins[-1]
    assert last.grid == "FM29MT" and last.published_bearing == "0°" and last.is_controller
    assert {r.callsign: r for r in result.checkins}["KO4YC"].qth == "RUTHER GLEN, VA"

def test_state_nc_is_not_a_controller_tag():  # Review Focus 1
    row = parse_roster("1 W4XX BOB RALEIGH, NC\n2 K1DY BILL TROY, ME FN54jq").checkins[0]
    assert not row.is_controller and row.qth == "RALEIGH, NC" and row.grid is None

def test_mixed_case_call_normalized_grid_kept():  # Review Focus 2
    row = parse_roster("3 k3wgr AL WERNERSVILLE, PA FN10xh").checkins[0]
    assert row.callsign == "K3WGR" and row.grid == "FN10xh"

def test_frequencies_and_dates_are_not_rows():  # spec 4.3
    assert parse_roster("50 mhz Check-ins for 10-26-26\n50.150 net\n144.245").checkins == ()
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_roster_parser.py -v`. Expected: FAIL, `ModuleNotFoundError`.
- [ ] **Step 3:** Implement normalization (strip `﻿`, `splitlines()`, map every `str.isspace()` character except newline to a space), URL/email removal, trailer cut at `^73\b`, format A, controller tags, stated counts (`(\d+)\s+(?:check-?ins|stations)\b` and `(\d+)\s+grids\b`, case-insensitive, first match each), roster block, result warnings.
- [ ] **Step 4:** Run tests, `uv run ruff check .`, `uv run mypy src/beam_navigator/core`. Expected: PASS.
- [ ] **Step 5:** Commit `feat: roster parser for numbered rows (N3RG, WB2RVX fixtures)`.

---

### Task 2: Multi-line and name-first rows (W2KV, KA3WXV)

**Files:**
- Modify: `src/beam_navigator/core/roster_parser.py`
- Test: `tests/unit/test_roster_parser.py`

**Interfaces:**
- Consumes/produces: Task 1's types unchanged; adds formats D and E.

- [ ] **Step 1: Write the failing tests.**

```python
def test_w2kv_fixture():  # acceptance 11
    result = load("w2kv_144mhz_2026-10-26.txt")
    calls = [r.callsign for r in result.checkins]
    assert len(calls) == 17
    assert calls[0] == "K4SO" and calls[-1] == "W2KV"
    assert calls.count("K8RYU") == 1 and calls.count("W2KV") == 1   # narrative, sign-off
    assert result.controller == "W2KV"
    row = {r.callsign: r for r in result.checkins}
    assert row["W2KV"].grid == "FN20OK" and row["W2KV"].name == "DAVE"
    assert row["K3WGR"].grid == "FN10xi"
    assert row["AF3G"].name == "GLENN" and row["KA3FQS"].qth == "AMBLER, PA"
    assert result.stated_checkins == 18
    assert "Text says 18 check-ins; 17 parsed." in result.warnings

def test_ka3wxv_fixture():  # acceptance 11
    result = load("ka3wxv_dmr_2026-10-26.txt")
    assert len(result.checkins) == 11
    assert result.checkins[0].callsign == "K3JJZ" and result.checkins[0].name == "El"
    assert [r.callsign for r in result.checkins].count("KA3WXV") == 1   # sign-off "George / ka3wxv"
    assert result.controller == "KA3WXV"
    assert all(r.grid is None and "Grid missing" in r.warnings for r in result.checkins)
    assert all(r.confidence == "medium" for r in result.checkins)

def test_single_name_call_line_is_not_a_checkin():
    assert parse_roster("Phil WA3NUF").checkins == ()
```

- [ ] **Step 2:** Run. Expected: FAIL (0 rows for W2KV and KA3WXV).
- [ ] **Step 3:** Implement E (call line, then a one-word name line that is not a callsign, then a line ending in a grid; QTH is the text before the grid) and D (run rule from the format table).
- [ ] **Step 4:** Run the whole test file, ruff, mypy. Expected: PASS, Task 1 tests still green.
- [ ] **Step 5:** Commit `feat: roster parser for multi-line and name-first rows (W2KV, KA3WXV)`.

---

### Task 3: Call-grid lists, BOM and grid counts (WA3NUF, KC3BVL)

**Files:**
- Modify: `src/beam_navigator/core/roster_parser.py`
- Test: `tests/unit/test_roster_parser.py`

**Interfaces:**
- Consumes/produces: unchanged; adds format B/C and the grid-count check (distinct upper-cased first four characters of each row's grid).

- [ ] **Step 1: Write the failing tests.**

```python
def test_wa3nuf_fixture():  # acceptance 11
    result = load("wa3nuf_222mhz_activity_2026-10-21.txt")
    calls = [r.callsign for r in result.checkins]
    assert len(calls) == 16 and calls[0] == "KA3FQS" and "VE2XX" in calls
    assert "WA3NUF" not in calls                          # the logger
    assert len({r.grid[:4].upper() for r in result.checkins if r.grid}) == 12
    assert {len(r.grid) for r in result.checkins if r.grid} == {4, 6}
    assert result.controller is None and not any(r.is_controller for r in result.checkins)
    assert (result.stated_checkins, result.stated_grids) == (16, 12)
    assert result.warnings == ()

def test_kc3bvl_fixture():  # acceptance 11
    result = load("kc3bvl_222mhz_2026-10-19.txt")      # starts with U+FEFF
    assert len(result.checkins) == 8
    assert result.checkins[0].callsign == "W3JG"
    assert {r.grid[:4].upper() for r in result.checkins if r.grid} == {"FM29", "FN20", "FN31"}
    assert result.controller == "KC3BVL"
    assert result.checkins[-1].grid == "FM29JW"
    assert (result.stated_checkins, result.stated_grids) == (8, 3)
    assert result.warnings == ()

def test_grid_count_mismatch_warns():
    result = parse_roster("We logged 2 stations and 2 grids\nW1AW FN31, K1ABC FN31")
    assert "Text says 2 grids; 1 parsed." in result.warnings
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement B/C.
- [ ] **Step 4:** Run the whole test file, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: roster parser for call-grid lists (WA3NUF, KC3BVL)`.

---

### Task 4: Flags, robustness and speed

**Files:**
- Modify: `src/beam_navigator/core/roster_parser.py`
- Test: `tests/unit/test_roster_parser.py`

**Interfaces:** unchanged.

- [ ] **Step 1: Write the failing tests.**

```python
def test_roster_pasted_twice_flags_duplicates():  # spec 4.3, Review Focus 4
    text = (FIXTURES / "wb2rvx_432mhz_2026-10-26.txt").read_text(encoding="utf-8")
    result = parse_roster(text + "\n" + text)
    assert len(result.checkins) == 20
    assert result.checkins[10].warnings == ("Duplicate of row 1",)
    assert "More than one controller tag." in result.warnings

def test_unparsed_line_inside_block_is_kept():  # spec 4.3
    result = parse_roster("1 K1DY BILL TROY, ME FN54jq\n?? smudge ??\n2 AF3G GLEN HOLLAND, PA FN20LE")
    assert [r.callsign for r in result.rows] == ["K1DY", None, "AF3G"]
    assert result.rows[1].warnings == ("Unparsed text",) and result.rows[1].confidence == "low"

def test_paste_damage_gives_same_rows():  # Review Focus 3
    clean = (FIXTURES / "n3rg_50mhz_2026-10-26.txt").read_text(encoding="utf-8")
    damaged = "﻿" + clean.replace("\n", "\r\n").replace("  ", "\t").replace(" ", " ")
    assert [(r.callsign, r.grid) for r in parse_roster(damaged).checkins] == \
           [(r.callsign, r.grid) for r in parse_roster(clean).checkins]

def test_garbage_and_huge_paste():  # acceptance 32, Review Focus 5
    garbage = "".join(chr(c) for c in range(0, 0x3000, 7)) * 20
    huge = ("Conditions were average and the band was quiet tonight. " * 20 + "\n") * 900
    for text in (garbage, huge):
        start = time.perf_counter()
        result = parse_roster(text)
        assert time.perf_counter() - start < 2.0
        assert result.checkins == ()
    assert len(huge) > 1_000_000

def test_hundred_station_roster_parses_and_calculates_fast():  # acceptance 33
    rows = [l for l in (FIXTURES / "n3rg_50mhz_2026-10-26.txt").read_text(encoding="utf-8").splitlines()
            if l[:1].isdigit() and not l.startswith("50 ")]
    text = "\n".join(rows * 5)                              # 110 rows of real data
    home = grid_center("FM29pt")
    start = time.perf_counter()
    result = parse_roster(text)
    for row in result.checkins:
        if row.grid:
            lookup(home, resolve(f"grid:{row.grid}"))
    assert time.perf_counter() - start < 2.0
    assert len(result.checkins) == 110
```

- [ ] **Step 2:** Run. Expected: the duplicate and unparsed tests FAIL; the others may already pass — if so, note it in the ledger (they are guards, not new behaviour).
- [ ] **Step 3:** Implement duplicate flags (by `base_callsign`, the later row points at the earlier one) and unparsed rows.
- [ ] **Step 4:** Run the whole suite, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: roster parser flags duplicates and unparsed text (acceptance 32, 33)`.

---

### Task 5: `beamnav parse` CLI

**Files:**
- Modify: `src/beam_navigator/cli.py` (add `parse` subcommand to `main`)
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `parse_roster`, `grid_center`, `resolve`, `lookup`.
- Produces: `beamnav parse FILE [--from GRID] [--units {km,mi}]`. Exit 0 after printing; 2 if the file cannot be read or `--from` is invalid. Reads with `encoding="utf-8", errors="replace"`.

Output: one line per row, columns `#`, `CALL`, `NAME`, `QTH`, `GRID`, `FROM YOU`, `DIST`, `PUBLISHED`, `NOTES`. `FROM YOU` and `DIST` come only from `lookup()` on `grid:<grid>` and are blank without `--from` or without a grid. `PUBLISHED` shows `published_bearing` and its header reads `PUBLISHED (theirs)`. `NOTES` lists `NC` for the controller, then row warnings. After the table: `Check-ins: N`, `Controller: CALL` or `Controller: none`, then each result warning on a `Warning:` line.

- [ ] **Step 1: Write the failing tests.**
  - `main(["parse", <n3rg path>, "--from", "FM29pt"])` returns 0; output has 22 data rows, `Controller: N3RG`, header `PUBLISHED (theirs)`.
  - Acceptance 12: on the N3ITT line the `FROM YOU` field equals `f"{lookup(grid_center('FM29pt'), resolve('grid:FN20kl')).bearing_deg:.1f}°"` and is not `0°`; `0°` appears only in the `PUBLISHED` field.
  - Without `--from`, the `FROM YOU` column is empty on every row.
  - W2KV file prints `Warning:   Text says 18 check-ins; 17 parsed.`
  - Missing file → returns 2, prints `Rejected:`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement with fixed-width f-string columns.
- [ ] **Step 4:** Run the full suite, ruff, mypy. Then by hand: `uv run beamnav parse tests/fixtures/w2kv_144mhz_2026-10-26.txt --from FM29pt`. Expected: 17 rows, W2KV marked NC, the count warning.
- [ ] **Step 5:** Commit `feat: beamnav parse command (acceptance 11, 12)`.

---

## Deferred to plan 1c (needs the store)

- Conflicting grids versus saved records (spec 4.3) and the cross-fixture checks: K3WGR FN10xh vs FN10xi, AF3G GLEN vs GLENN, KA3FQS Horsham vs Ambler, N2DEQ Turnersville vs Blackwood, N2LQH one station with two attendances.
- Re-import prompt (acceptance 13) and stored raw text (invariant 9).
- KA3WXV net having a talkgroup instead of a frequency (net record).
