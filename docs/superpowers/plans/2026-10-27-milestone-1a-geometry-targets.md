# Milestone 1a — Geometry and Targets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `beamnav bearing FN20ok --from FM29pt` prints the true bearing, compass point, distance and reverse bearing, resolving any target the spec allows (heading, compass point, grid, region, alias, callsign).

**Architecture:** Pure functions in `src/beam_navigator/core/` with no UI, network or database imports. The resolver turns text into a `Resolution`; `lookup.py` turns a home location plus a `Resolution` into a `BearingResult`. Aliases and stations come in through lookup callables, so the store (plan 1c) plugs in later without changing core.

**Tech Stack:** Python 3.12, stdlib only at runtime. Dev: pytest, ruff, mypy, `geographiclib` (new, dev only).

**Spec:** `docs/requirements.md` v2.0 — sections 2, 4.1, 4.2, 5, 7 (tests 1–10).

**Milestone 1 is split into three plans** (requirements section 6 lists three independent subsystems):
- **1a (this plan):** Maidenhead, geometry, target resolver, regions, `beamnav bearing`.
- **1b:** roster parser, all six fixtures, `beamnav parse`. (Section 6 says "all three fixtures"; section 7 has six. Plan 1b targets six.)
- **1c:** SQLite store, migrations, repositories; wires aliases and stations into the resolver.
The simulation adapter already exists from Milestone 0.

## Global Constraints

- Python `>=3.12`. Match the existing code: 4-space indentation, line length 100, `ruff` rules from `pyproject.toml`, `mypy --strict`.
- `core/` imports nothing from `ui/`, `store/`, `rotators/`, sockets or `sqlite3`.
- No new runtime dependencies. `geographiclib` is **dev only** and needs the owner's approval before Task 2 (CLAUDE.md: ask before modifying `pyproject.toml`).
- Earth radius `6371.0` km. Long-path total `40030` km. "Home" radius `0.5` km. Bearings normalized to `[0, 360)`.
- Headings accepted `0`–`359.9`; `360` becomes `0`; anything else outside is rejected, never wrapped (invariants 4, 7).
- Never invent a location (invariant 5). Every `Resolution` carries a `source` from: `typed`, `roster`, `saved`, `alias`, `region centroid`.
- No hard-coded stations or home location (invariant 10). The CLI's `--from` is required.
- `uv run pytest`, `uv run ruff check .`, `uv run mypy src/beam_navigator/core` pass after every task.
- Every test passes with networking disabled (acceptance 31).

## Review Focus

1. **Messy typing:** `" fn20OK "`, `"247 °"`, non-breaking space, lower-case compass `nnw` → same result as the clean form. Test in Task 5.
2. **Junk and partial prefixes:** `""`, `"   "`, `"st:"`, `"foo:NE"`, `"FN2"`, `"???"` → a `TargetError` with a readable message, never a crash or a guessed target. Test in Task 5.
3. **Odd numbers:** `"nan"`, `"inf"`, `"-0"`, `"1e2"`, `"359.95"`, `"-5"` → rejected except `-0` (→ 0). Test in Task 5.
4. **Grid/callsign look-alikes:** `FN20ok` is a grid, `W2KV` and `K1ABC/P` are callsigns, `EA/K1ABC` is a callsign, `AB12` is a grid. Test in Task 5.
5. **Extreme paths:** antipodal points, a path across the antimeridian (`AA00` → `RR99xx`), a pole-adjacent cell → finite bearing in `[0, 360)`, no exception. Test in Task 2.

---

### Task 1: LatLon model and Maidenhead grids

**Files:**
- Create: `src/beam_navigator/core/__init__.py` (empty), `src/beam_navigator/core/models.py`, `src/beam_navigator/core/maidenhead.py`
- Test: `tests/unit/test_maidenhead.py`

**Interfaces:**
- Produces: `models.LatLon(lat: float, lon: float)` frozen dataclass. `maidenhead.GridError(ValueError)`. `maidenhead.grid_center(grid: str) -> LatLon` (raises `GridError` with a message naming the bad character or length). `maidenhead.is_grid(text: str) -> bool`.

- [ ] **Step 1: Write the failing tests** (acceptance 3). Reference centres are computed from the Maidenhead definition (field 20°×10°, square /10, subsquare /24, extended square /10, extended subsquare /24; centre = corner + half a cell):

```python
@pytest.mark.parametrize(("grid", "lat", "lon"), [
    ("FN20", 40.5, -75.0),
    ("FN20ok", 40.4375, -74.791667),
    ("FM29pt", 39.8125, -74.708333),
    ("FM29pt42", 39.802083, -74.7125),
    ("FM29pt42ab", 39.800260, -74.716493),
    ("AA00", -89.5, -179.0),
    ("RR99xx", 89.979167, 179.958333),
])
def test_grid_center(grid, lat, lon):
    center = grid_center(grid)
    assert center.lat == pytest.approx(lat, abs=1e-6)
    assert center.lon == pytest.approx(lon, abs=1e-6)

def test_case_insensitive():
    assert grid_center("fn20OK") == grid_center("FN20ok")

@pytest.mark.parametrize("bad", ["FN2", "FN20o", "ZZ99", "FN20ok4", "SA00", "FN20yz", "", "F N20"])
def test_invalid_grid_rejected(bad):
    with pytest.raises(GridError):
        grid_center(bad)
```

- [ ] **Step 2:** Run `uv run pytest tests/unit/test_maidenhead.py -v`. Expected: FAIL, `ModuleNotFoundError: beam_navigator.core`.
- [ ] **Step 3:** Implement. Field letters `A`–`R`, subsquare letters `A`–`X`, lengths 4/6/8/10 only. Strip surrounding whitespace; do not accept inner spaces.
- [ ] **Step 4:** Run the tests. Expected: PASS. Run ruff and mypy.
- [ ] **Step 5:** Commit `feat: Maidenhead grid validation and cell centres (acceptance 3)`.

---

### Task 2: Great-circle geometry and compass names

**Files:**
- Modify: `pyproject.toml` (add `"geographiclib>=2"` to `[dependency-groups] dev`) — **owner approval required**, then `uv sync`.
- Create: `src/beam_navigator/core/geometry.py`
- Test: `tests/unit/test_geometry.py`

**Interfaces:**
- Consumes: `LatLon`, `grid_center`.
- Produces: `EARTH_RADIUS_KM = 6371.0`, `LONG_PATH_TOTAL_KM = 40030.0`, `HOME_RADIUS_KM = 0.5`. `Path(bearing_deg: float, distance_km: float)` frozen dataclass. `short_path(origin: LatLon, target: LatLon) -> Path`. `long_path(short: Path) -> Path`. `is_home(origin: LatLon, target: LatLon, radius_km: float = HOME_RADIUS_KM) -> bool`. `compass_name(bearing_deg: float) -> str` (16-point). `COMPASS_POINTS: dict[str, float]` (`"N": 0.0, "NNE": 22.5, … "NNW": 337.5`). `coarse_location_note(grid_text: str, freq_mhz: float | None) -> str | None`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_fm29pt_to_fn20ok_matches_geographiclib():  # acceptance 1
    home, target = grid_center("FM29pt"), grid_center("FN20ok")
    ref = Geodesic.WGS84.Inverse(home.lat, home.lon, target.lat, target.lon)
    path = short_path(home, target)
    assert path.bearing_deg == pytest.approx(ref["azi1"] % 360, abs=0.5)
    assert path.distance_km == pytest.approx(ref["s12"] / 1000, rel=0.005)
    assert 353 < path.bearing_deg < 355

def test_reverse_is_computed_not_added():  # acceptance 1
    home, target = grid_center("FM29pt"), grid_center("FN20ok")
    reverse = short_path(target, home)
    ref = Geodesic.WGS84.Inverse(target.lat, target.lon, home.lat, home.lon)
    assert reverse.bearing_deg == pytest.approx(ref["azi1"] % 360, abs=0.5)
    assert 173 < reverse.bearing_deg < 175

def test_same_grid_is_home():  # acceptance 2
    assert is_home(grid_center("FM29pt"), grid_center("FM29pt"))

def test_long_path():  # acceptance 4
    short = Path(354.2, 120.0)
    long = long_path(short)
    assert long.bearing_deg == pytest.approx(174.2)
    assert short.distance_km + long.distance_km == pytest.approx(40030.0)
    assert long_path(Path(270.0, 1.0)).bearing_deg == pytest.approx(90.0)

@pytest.mark.parametrize(("bearing", "name"), [(0, "N"), (11.2, "N"), (11.3, "NNE"), (174, "S"),
                                                 (337.5, "NNW"), (348.8, "N"), (359.9, "N")])
def test_compass_name(bearing, name):
    assert compass_name(bearing) == name

@pytest.mark.parametrize(("a", "b"), [("AA00", "RR99xx"), ("FM29pt", "RR99xx"), ("AA00", "AR09")])
def test_extreme_paths_are_finite(a, b):  # Review Focus 5
    path = short_path(grid_center(a), grid_center(b))
    assert 0 <= path.bearing_deg < 360 and math.isfinite(path.distance_km)

def test_antipodal_does_not_crash():  # Review Focus 5
    path = short_path(LatLon(40.0, -75.0), LatLon(-40.0, 105.0))
    assert 0 <= path.bearing_deg < 360

def test_coarse_note_only_for_4_char_grid_at_1296_and_up():
    assert coarse_location_note("FN20", 1296.1) == "coarse location — ±50 km"
    assert coarse_location_note("FN20", 432.1) is None
    assert coarse_location_note("FN20ok", 1296.1) is None
    assert coarse_location_note("FN20", None) is None
```

Plus a parametrized check of five more grid pairs under 2,000 km against geographiclib (0.5°, 0.5%), using the grids above.

- [ ] **Step 2:** Run. Expected: FAIL, `ModuleNotFoundError: beam_navigator.core.geometry`.
- [ ] **Step 3:** Implement with haversine distance and the standard initial-bearing `atan2` formula on the sphere. Compass sectors are 22.5° wide centred on each point (N covers 348.75–11.25).
- [ ] **Step 4:** Run tests, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: great-circle bearing, distance, long path (acceptance 1, 2, 4)`.

---

### Task 3: Callsign recognition

**Files:**
- Create: `src/beam_navigator/core/callsign.py`
- Test: `tests/unit/test_callsign.py`

**Interfaces:**
- Produces: `normalize_callsign(text: str) -> str` (upper-case, stripped). `is_callsign(text: str) -> bool`. `base_callsign(text: str) -> str` (`K1ABC/P` → `K1ABC`, `EA/K1ABC` → `K1ABC`). Plan 1b's parser reuses all three.

- [ ] **Step 1: Write the failing tests.** True: `W2KV`, `n2lqh`, `K1ABC/P`, `EA/K1ABC`, `VE2XX`, `KA3WXV`, `2E0ABC`. False: `FN20ok`, `FN20`, `AB12`, `50.150`, `NE`, `247`, `NBA`, `76'ER`, `""`. `base_callsign` cases as above.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement: optional `PREFIX/`, a base call matching `[A-Z0-9]{1,3}[0-9][A-Z]{1,4}`, optional `/SUFFIX` of 1–4 alphanumerics. A string that `is_grid` accepts is never a callsign.
- [ ] **Step 4:** Run tests, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: callsign recognition shared by resolver and parser`.

---

### Task 4: Region centroids — BLOCKED on data source

**Files:**
- Create: `src/beam_navigator/data/regions.csv`, `src/beam_navigator/core/regions.py`, `tools/build_regions.py` (dev-time script, not shipped logic)
- Test: `tests/unit/test_regions.py`

**Interfaces:**
- Produces: `Region(code: str, name: str, lat: float, lon: float, source: str)` frozen dataclass. `load_regions() -> dict[str, Region]` reading the packaged CSV via `importlib.resources`, keyed by upper-case code. `RegionDataError(ValueError)`.

- [ ] **Step 0: Owner chooses the public-domain source** for US states, DC and Canadian provinces (spec 4.2 says provinces; territories are left out). Nothing in this task may contain a coordinate typed from memory (CLAUDE.md rule 4). The script downloads the source once at dev time, computes each centroid, and writes `code,name,lat,lon,source`. The CSV and the script are committed; the app never downloads anything.
- [ ] **Step 1: Write the failing tests.** CSV has header `code,name,lat,lon,source`; 51 US codes (50 states + DC) and 10 Canadian province codes; codes unique; every lat in [-90, 90] and lon in [-180, 180]; every `source` non-empty. `load_regions()["NJ"].name == "New Jersey"`. A malformed CSV passed through a `tmp_path` loader (`load_regions_from(path)`) raises `RegionDataError` naming the line.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement the loader; run the build script to produce the CSV.
- [ ] **Step 4:** Run tests, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: region centroid table from <source>`, naming the source.

---

### Task 5: Target resolver

**Files:**
- Create: `src/beam_navigator/core/targets.py`
- Test: `tests/unit/test_targets.py`

**Interfaces:**
- Consumes: `grid_center`, `is_grid`, `COMPASS_POINTS`, `is_callsign`, `normalize_callsign`, `load_regions`, `LatLon`.
- Produces:
  - `TargetError(ValueError)`.
  - `AliasTarget(kind: Literal["grid", "coords", "station", "heading"], value: str)` frozen dataclass.
  - `StationLocation(callsign: str, grid: str | None, latlon: LatLon | None, source: Literal["saved", "roster"])` frozen dataclass.
  - `AliasLookup = Callable[[str], AliasTarget | None]`, `StationLookup = Callable[[str], StationLocation | None]`.
  - `Resolution(kind: Literal["heading", "compass", "grid", "region", "callsign"], label: str, source: str, location: LatLon | None, fixed_bearing: float | None, grid_text: str | None, alternative: str | None, needs_grid: bool)` frozen dataclass. `alternative` is the prefixed input for the one-click other reading (`"st:NE"`).
  - `resolve(text: str, aliases: AliasLookup | None = None, stations: StationLookup | None = None) -> Resolution`.
  - `COLLISION_DEFAULTS: dict[str, tuple[str, str]]` — `{"NE": ("dir", "st")}` (default kind, alternative prefix).

Order without a prefix: heading → compass (subject to `COLLISION_DEFAULTS`) → grid → region → alias → callsign → `TargetError("Not recognized: …")`. Prefixes `dir:`, `st:`, `grid:`, `call:` force a type. An alias resolves to its target with `source="alias"` and its own label; an alias may not point at another alias. A callsign with no known grid returns `needs_grid=True`, `location=None` — never a guess.

- [ ] **Step 1: Write the failing tests.**

```python
@pytest.mark.parametrize(("text", "bearing"), [("N", 0), ("NE", 45), ("SW", 225), ("NNW", 337.5), ("nnw", 337.5)])
def test_compass(text, bearing):  # acceptance 5
    r = resolve(text)
    assert r.fixed_bearing == bearing and r.location is None

@pytest.mark.parametrize(("text", "bearing"), [("247°", 247), ("247", 247), ("247 °", 247), ("360", 0), ("-0", 0), ("0", 0)])
def test_heading(text, bearing):  # acceptance 6, Review Focus 3
    assert resolve(text).fixed_bearing == bearing

@pytest.mark.parametrize("text", ["400", "-5", "359.95", "nan", "inf", "1e2"])
def test_bad_heading_rejected(text):  # acceptance 6, Review Focus 3
    with pytest.raises(TargetError):
        resolve(text)

def test_ne_defaults_to_northeast_and_offers_nebraska():  # acceptance 9
    r = resolve("NE")
    assert r.kind == "compass" and r.alternative == "st:NE"
    assert resolve("st:NE").kind == "region" and resolve("st:NE").source == "region centroid"

def test_every_collision_has_a_rule():  # spec 4.2
    collisions = set(COMPASS_POINTS) & set(load_regions())
    assert collisions <= set(COLLISION_DEFAULTS)

def test_alias_matches_typed_grid():  # acceptance 10
    aliases = {"CLUB": AliasTarget("grid", "FM29jw")}.get
    via_alias, typed = resolve("club", aliases=aliases), resolve("FM29jw")
    assert via_alias.location == typed.location and via_alias.source == "alias"

def test_unknown_station_needs_grid():  # invariant 5
    r = resolve("W2KV", stations=lambda call: None)
    assert r.needs_grid and r.location is None

def test_messy_input_normalized():  # Review Focus 1
    assert resolve(" fn20OK ").location == resolve("FN20ok").location
    assert resolve(" NNW").fixed_bearing == 337.5

@pytest.mark.parametrize("text", ["", "   ", "st:", "foo:NE", "FN2", "???", "st:XX", "grid:W2KV"])
def test_junk_rejected(text):  # Review Focus 2
    with pytest.raises(TargetError):
        resolve(text)

@pytest.mark.parametrize(("text", "kind"), [("FN20ok", "grid"), ("AB12", "grid"), ("W2KV", "callsign"),
                                            ("K1ABC/P", "callsign"), ("EA/K1ABC", "callsign"), ("PA", "region")])
def test_kind_detection(text, kind):  # Review Focus 4
    assert resolve(text, stations=lambda call: None).kind == kind
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Normalize with `str.split()`/`" ".join` (handles all Unicode whitespace), strip a trailing `°`, upper-case for matching but keep the original grid text in `grid_text` and `label`. Headings parse only `^-?\d+(\.\d+)?$`.
- [ ] **Step 4:** Run tests, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Commit `feat: target resolver with shortcodes and collisions (acceptance 5, 6, 9, 10)`.

---

### Task 6: Bearing lookup result

**Files:**
- Create: `src/beam_navigator/core/lookup.py`
- Test: `tests/unit/test_lookup.py`

**Interfaces:**
- Consumes: `Resolution`, `short_path`, `long_path`, `is_home`, `compass_name`, `coarse_location_note`.
- Produces: `BearingResult(target: Resolution, bearing_deg: float | None, compass: str | None, distance_km: float | None, reverse_deg: float | None, long_path: Path | None, message: str | None, can_rotate: bool, coarse_note: str | None)` frozen dataclass. `lookup(home: LatLon, target: Resolution, home_region: str | None = None, include_long_path: bool = False, freq_mhz: float | None = None) -> BearingResult`.

Rules: fixed headings → bearing only, no distance, no reverse. `is_home` → `message="Home"`, no bearing, `can_rotate=False`. Region whose code equals `home_region` → `message="You are in NJ"`, no bearing, `can_rotate=False`. `needs_grid` → `message="Grid needed"`, `can_rotate=False`. `reverse_deg` from `short_path(target, home)`.

`home_region` is explicit: without polygons (spec 4.2) "the user is inside NJ" cannot be computed, so the operator states it (operator profile in plan 1c; `--home-region` on the CLI). Record as a decision.

- [ ] **Step 1: Write the failing tests.** Acceptance 2 (`FM29pt`→`FM29pt`: `message == "Home"`, `bearing_deg is None`, `not can_rotate`). Acceptance 7 (`PA` ≈ 295° ±3, `MD` ≈ 243° ±3, both `source == "region centroid"`) — runs once Task 4's data exists. Acceptance 8 (`NJ` with `home_region="NJ"` → `"You are in NJ"`, `not can_rotate`). Fixed heading `247` → `distance_km is None`. Unknown station → `"Grid needed"`. Long path only when `include_long_path=True`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run tests, ruff, mypy. Expected: PASS.
- [ ] **Step 5:** Add decision 10 to `docs/decisions.md` (explicit home region). Commit `feat: bearing lookup with Home, region and grid-needed rules (acceptance 2, 7, 8)`.

---

### Task 7: `beamnav bearing` CLI

**Files:**
- Modify: `src/beam_navigator/cli.py` (add `bearing_main`), `pyproject.toml` (`[project.scripts] beamnav = "beam_navigator.cli:main"`) — **owner approval required** (same approval as Task 2 if given together).
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `resolve`, `lookup`, `grid_center`.
- Produces: `main(argv: Sequence[str] | None = None) -> int` with subcommand `bearing TARGET --from GRID [--units {km,mi}] [--long-path] [--mhz F] [--home-region CODE]`. Plan 1b adds `parse` to the same `main`. Exit 0 on a result, 2 on a rejected target or bad `--from`.

Output (bearing to one decimal, same label column style as `beamnav-rotor`):

```
Target:    FN20ok (grid, typed)
Bearing:   354.x° N
Distance:  nnn.n km
Reverse:   174.x° (from the target to you)
```

- [ ] **Step 1: Write the failing tests.** `main(["bearing", "FN20ok", "--from", "FM29pt"])` returns 0 and prints `Bearing:   354.` and `Reverse:   174.`. `--from` missing → argparse exit 2. `bearing 400 --from FM29pt` → returns 2, prints `Rejected:`. `bearing W2KV --from FM29pt` → prints `Grid needed`. `--units mi` prints `mi`. No test or output contains a default home station.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Callsign targets have no station store yet (plan 1c), so `stations` is `None` and they print "Grid needed".
- [ ] **Step 4:** Run the full suite, ruff, mypy. Then `uv run beamnav bearing FN20ok --from FM29pt` by hand. Expected: bearing ≈354°, reverse ≈174°.
- [ ] **Step 5:** Commit `feat: beamnav bearing command`.
