# Example-Net Participants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the operator adds the example nets, the owner's rosters come with them as past sessions, so their stations become stored records with attendance history, and QRZ then fills, once and in the background, what those records are missing.

**Architecture:** A 14th example net, the Packrat DMR Net, is added from the owner's message of 2026-10-29. The six rosters, one per matching example net, are copied verbatim into package data with a small manifest (file → net name, date). `NetBook.add_examples` imports each one through the existing `RosterReview.parse/save` path, which already creates `roster` station records without overwriting anything. A background pass on the Nets page then asks QRZ about the example stations that are missing a name or grid. Results go to the existing QRZ cache (decision 29), never into station records. The controller and dashboard then use that cache to fill blanks, labelled "from QRZ".

**Tech Stack:** Python 3.14, NiceGUI 3.18, sqlite3, pytest / pytest-asyncio. There are no new dependencies.

**Spec:** `docs/requirements.md` 4.3 (roster import), 4.6 (example nets), 4.9 (QRZ); decisions 27, 29, 30. The owner's requests of 2026-10-29: "when loading the example nets we should load the net participants as stored data augmenting any missing data from QRZ", answered with "Rosters as past sessions too" and "Background after loading".

## Global Constraints

- Invariant 2: nothing here sends a rotator command.
- Invariant 5: never invent a location. A QRZ grid is used only for `station` or `address` precision, and always labelled QRZ.
- Invariant 9 / hard rule 4: the rosters' raw text is copied byte-for-byte from `tests/fixtures/` and never edited.
- Hard rule 7: example data is opt-in. Nothing loads unless the operator presses **Add examples**.
- Decision 29: QRZ answers live in `qrz_record`, never in `station`. A roster or saved value is never overwritten.
- Decision 30: automatic QRZ lookups respect `qrz_auto` = "off", and are silent when no login or credential store exists.
- Network calls run in `run.io_bound`; the database is used only on the event loop (decision 20).
- Tests never reach the network or the real credential store (conftest guards).
- Runtime dependencies are unchanged.

## Review Focus

1. The operator already has their own net with an example name. Its roster must not be attached to the operator's net; the session is skipped (Task 2 test).
2. **Add examples** runs a second time (the offer is gone, but `add_examples` can still be called). No duplicate sessions are created (Task 2 test).
3. QRZ goes offline or refuses partway through the background pass. The pass stops after the first failure with one message, not one per station (Task 4 test).
4. The operator has automatic lookup switched off. The background pass makes no lookups (Task 3 test).
5. A cached QRZ answer with only zip/state/country precision must never fill a grid (Task 5 test).

---

### Task 1: The DMR example net, and the rosters packaged

**Files:**
- Modify: `docs/example-nets-source.txt`. Append these two lines verbatim, under a line `--- Added by the owner, 2026-10-29 ---`:
  - `Packrat DMR Net Monday night 7pm New control george KA3WXV Talkgroup 8803`
  - `sorry 8804`
- Modify: `src/beam_navigator/data/example_nets.beamnet.json`. Append one net:
  `{"name": "Packrat DMR Net", "weekday": "monday", "start_time": "19:00", "timezone": null, "frequency_mhz": null, "channel": "Talkgroup 8804", "mode": "DMR", "band": null, "default_controller_call": "KA3WXV", "default_controller_grid": null, "unverified": true}`
  The grid is null because the owner gave none; never guess one.
- Modify the count assertions from 13 to 14:
  - `tests/unit/test_example_nets.py:38,75,79`
  - `tests/ui/test_nets_page.py:260`
- Add `test_dmr_example_net`, asserting the entry above field by field.
- Create: `src/beam_navigator/data/example_rosters/` holding byte-for-byte copies of six fixtures:
  - `n3rg_50mhz_2026-10-26.txt`
  - `w2kv_144mhz_2026-10-26.txt`
  - `kc3bvl_222mhz_2026-10-19.txt`
  - `wb2rvx_432mhz_2026-10-26.txt`
  - `wa3nuf_222mhz_activity_2026-10-21.txt`
  - `ka3wxv_dmr_2026-10-26.txt`
- Create: `src/beam_navigator/data/example_rosters.json`
- Modify: `src/beam_navigator/nets.py` (constants and loader)
- Test: `tests/unit/test_example_nets.py`

Copy the files with `cp`, never by retyping them.

Manifest (exact content):

```json
{"rosters": [
  {"file": "n3rg_50mhz_2026-10-26.txt", "net": "Pack Rats Monday 50 MHz", "date": "2026-10-26"},
  {"file": "w2kv_144mhz_2026-10-26.txt", "net": "Pack Rats Monday 144 MHz", "date": "2026-10-26"},
  {"file": "kc3bvl_222mhz_2026-10-19.txt", "net": "Pack Rats Monday 222 MHz", "date": "2026-10-19"},
  {"file": "wb2rvx_432mhz_2026-10-26.txt", "net": "Pack Rats Monday 432 MHz", "date": "2026-10-26"},
  {"file": "wa3nuf_222mhz_activity_2026-10-21.txt", "net": "K1WHS 222 MHz Tuesday Activity Night", "date": "2026-10-21"},
  {"file": "ka3wxv_dmr_2026-10-26.txt", "net": "Packrat DMR Net", "date": "2026-10-26"}
]}
```

**Interfaces:**
- Produces:
  - `EXAMPLE_ROSTERS` (resources path to the manifest)
  - `@dataclass(frozen=True) class ExampleRoster: net: str; date: str; text: str`
  - `example_rosters() -> list[ExampleRoster]` in `nets.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_example_rosters_are_the_owner_fixtures() -> None:
    fixtures = Path(__file__).parents[1] / "fixtures"
    rosters = example_rosters()
    assert len(rosters) == 6
    packaged = files("beam_navigator") / "data" / "example_rosters"
    for entry in json.loads(EXAMPLE_ROSTERS.read_text(encoding="utf-8"))["rosters"]:
        assert (packaged / entry["file"]).read_bytes() == (fixtures / entry["file"]).read_bytes()

def test_example_rosters_name_example_nets() -> None:
    names = {n["name"] for n in examples()}  # existing helper in this file
    assert all(r.net in names for r in example_rosters())
    assert [r.date for r in example_rosters()][0] == "2026-10-26"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/unit/test_example_nets.py -k rosters -q`
Expected: FAIL with an ImportError for `example_rosters`.

- [ ] **Step 3: Implement**

Copy the files and write the manifest. `example_rosters()` reads the manifest and each file's text as UTF-8; it keeps a BOM if present, because the parser already handles one.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "feat: owner rosters packaged with the example nets (decision 32)"`

### Task 2: Add examples also imports their rosters

**Files:**
- Modify: `src/beam_navigator/nets.py` (`NetBook.add_examples`, new `NetBook.example_callsigns`)
- Test: `tests/unit/test_example_nets.py`

**Interfaces:**
- Consumes:
  - `example_rosters()` (Task 1)
  - `RosterReview(conn, desk).parse(text) -> Review`
  - `RosterReview.save(net_id, date, review) -> Session`
- Produces:
  - `NetBook.add_examples() -> ImportReport` (unchanged signature). For each net in `report.added`, it imports that net's roster as an `imported` session, with the parser's suggested controller.
  - `NetBook.example_callsigns() -> list[str]`: the normalised callsigns of every parsed roster row with a callsign, de-duplicated, in roster order.

- [ ] **Step 1: Write the failing tests**

```python
def test_add_examples_imports_rosters(book: NetBook) -> None:
    book.add_examples()
    nets = {n.name: n for n in book.pickable()}
    for roster in example_rosters():
        net_id = nets[roster.net].id
        assert net_id is not None
        [(session, count)] = NetRepository(book.desk.conn).sessions(net_id)
        assert (session.date, session.status, session.raw_text) == (roster.date, "imported", roster.text)
        assert count == len([r for r in parse_roster(roster.text).rows if r.callsign])
    calls = book.example_callsigns()
    assert all(book.desk.stations.get(c) is not None for c in calls)
    assert all(book.desk.stations.get(c).source == "roster" for c in calls)

def test_examples_never_overwrite_a_saved_station(book: NetBook) -> None:
    book.desk.stations.save(Station("K1DY", "MINE", "FN20aa", None, None, "saved", ""))
    book.add_examples()
    kept = book.desk.stations.get("K1DY")
    assert kept is not None and (kept.name, kept.grid, kept.source) == ("MINE", "FN20aa", "saved")

def test_rosters_skip_a_net_the_operator_owns(book: NetBook) -> None:
    mine = NetRepository(book.desk.conn).save_net(Net(None, "Pack Rats Monday 50 MHz", None,
        None, None, 50.125, None, None, "6 m", None, None, False))
    book.add_examples()
    assert mine.id is not None
    assert NetRepository(book.desk.conn).sessions(mine.id) == []

def test_second_add_examples_adds_no_sessions(book: NetBook) -> None:
    book.add_examples()
    before = book.desk.conn.execute("SELECT COUNT(*) FROM session").fetchone()[0]
    book.add_examples()
    assert book.desk.conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == before == 6
```

Rename the `"6 m"` band if the fixture's band list names it differently; check `BandRepository`. `test_add_examples_once` stays as it is.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/unit/test_example_nets.py -q`
Expected: the four new tests FAIL (no sessions; no `example_callsigns`).

- [ ] **Step 3: Implement**

Do this in `add_examples`, after `import_beamnet`. If a roster raises `ValueError`, let it propagate: the packaged data is fixed and tested, so an error here is a bug, not operator input.

- [ ] **Step 4: Run the file, then the whole suite**

Run `uv run pytest tests/unit/test_example_nets.py -q`, then `uv run pytest -q`.
Expected: PASS. Check that `tests/ui/test_nets_page.py::test_example_banner_add` still passes.

- [ ] **Step 5: Commit**

`git commit -m "feat: example nets come with their rosters as past sessions (decision 32)"`

### Task 3: Which example stations QRZ should complete

**Files:**
- Modify: `src/beam_navigator/desk.py`
- Test: `tests/unit/test_desk_qrz.py`

**Interfaces:**
- Produces: `Desk.qrz_missing(callsigns: list[str]) -> list[str]`. It returns the calls, in the given order, whose station record lacks a name or a grid and that have no `qrz_record`. It returns `[]` when `qrz_auto` is "off".

- [ ] **Step 1: Write the failing tests**

```python
def test_qrz_missing_picks_incomplete_records(desk: Desk, aa7bq: QrzRecord) -> None:
    desk.stations.add_from_roster("K1AAA", "AL", "FN20aa", None)   # complete
    desk.stations.add_from_roster("K1BBB", None, "FN20aa", None)   # no name
    desk.stations.add_from_roster("K1CCC", "CY", None, None)       # no grid
    desk.stations.add_from_roster("AA7BQ", None, None, None)       # QRZ already answered
    desk.qrz.save(aa7bq, WHEN)
    assert desk.qrz_missing(["K1AAA", "K1BBB", "K1CCC", "AA7BQ"]) == ["K1BBB", "K1CCC"]

def test_qrz_missing_respects_the_switch(desk: Desk) -> None:
    desk.stations.add_from_roster("K1BBB", None, "FN20aa", None)
    desk.settings.set("qrz_auto", "off")
    assert desk.qrz_missing(["K1BBB"]) == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/unit/test_desk_qrz.py -k missing -q`
Expected: FAIL with AttributeError.

- [ ] **Step 3: Implement**

Place `qrz_missing` next to `qrz_auto`.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "feat: list example stations QRZ can complete (decision 32)"`

### Task 4: Background QRZ pass after Add examples

**Files:**
- Modify: `src/beam_navigator/ui/nets.py` (`nets_page` takes `qrz: QrzClient | None = None`; `add_examples` becomes async)
- Modify: `src/beam_navigator/ui/app.py` (pass the shared client to `nets_page`)
- Test: `tests/ui/test_nets_page.py`

**Interfaces:**
- Consumes:
  - `NetBook.example_callsigns()` (Task 2)
  - `Desk.qrz_missing` (Task 3)
  - `QrzClient.lookup`
  - `Desk.qrz_store`
  - `NO_LOGIN`, `NO_STORE`, `QrzError`

Behaviour:
1. The handler first does what it does today: adds the nets, refreshes the page and shows the report.
2. Then, if `qrz` is not None, it looks up each call from `qrz_missing(example_callsigns())` in turn, through `await run.io_bound(qrz.lookup, call)`, and stores each answer with `qrz_store`.
3. If the error is "QRZ has no record for …", it continues with the next call.
4. If the error is `NO_LOGIN` or `NO_STORE`, it stops silently.
5. Any other `QrzError` (offline, refused, login failed) stops the pass with one `ui.notify(str(exc), type="warning")`.
6. At the end, if any were stored, it shows `ui.notify(f"QRZ filled in details for {n} example stations.")` with n ≥ 1.

The whole sequence happens inside the click handler's own task. Nothing is scheduled with a timer.

- [ ] **Step 1: Write the failing tests** (use a `FakeQrz` like the one in `test_dashboard.py`, counting calls)

```python
async def test_examples_then_qrz_fills_missing(user, desk, book, qrz_examples) -> None:
    missing = len(desk_after_examples_missing(...))  # compute: add examples in a scratch Desk
                                                     # (fresh :memory: db) and call qrz_missing
    replies = [qrz_examples[0]] + [qrz_examples[3]] * (missing - 1) + [qrz_examples[1]]
    transport = FakeQrz(replies)
    save_login("xx1xxx", "pw")
    register_pages(lambda: desk, QrzClient(transport=transport))
    await user.open("/nets")
    user.find(marker="add-examples").click()
    await user.should_see("QRZ filled in details for 1 example stations.")
    assert transport.calls == 1 + missing

async def test_examples_qrz_quiet_without_login(user, desk, book) -> None:
    transport = FakeQrz([])
    register_pages(lambda: desk, QrzClient(transport=transport))
    await user.open("/nets")
    user.find(marker="add-examples").click()
    await user.should_see("Example — unverified")
    await asyncio.sleep(0.2)
    await user.should_not_see("Set up your QRZ login")
    assert transport.calls == 0

async def test_examples_qrz_stops_once_offline(user, desk, book) -> None:
    transport = FakeQrz([URLError("offline")])
    save_login("xx1xxx", "pw")
    register_pages(lambda: desk, QrzClient(transport=transport))
    await user.open("/nets")
    user.find(marker="add-examples").click()
    await user.should_see("QRZ can't be reached. Everything else works offline.")
    assert transport.calls == 1
```

The first test's count must be computed, not hard-coded. Write a small helper in the test file that builds a fresh `:memory:` Desk and NetBook, calls `add_examples()`, and returns `len(desk.qrz_missing(book.example_callsigns()))`. Also assert that count is ≥ 2, so the "not found → continue" path is exercised. The message text "1 example stations" is accepted because the copy is fixed in Behaviour step 6; if the implementer wants singular/plural wording, it must change in both places.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/ui/test_nets_page.py -k qrz -q`
Expected: FAIL (`transport.calls == 0`; no message).

- [ ] **Step 3: Implement** as described in Behaviour.

- [ ] **Step 4: Run the nets page tests, then the whole suite**

Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "feat: QRZ completes the example stations in the background (decision 32)"`

### Task 5: Use cached QRZ answers as stored data

**Files:**
- Modify: `src/beam_navigator/ui/control.py` (`autofill`)
- Modify: `src/beam_navigator/desk.py` (`look_up` path used by the dashboard)
- Modify: `src/beam_navigator/ui/lookup.py` (`enter`)
- Test: `tests/ui/test_control.py`, `tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes:
  - `NetControl.qrz_fill(entry, record) -> Entry`
  - `Desk.qrz.get(call) -> tuple[QrzRecord, str] | None`
  - `Desk.look_up_with_qrz(call, band) -> LookupView`
  - `QrzView.can_use`

Behaviour:
- **Controller:** after `autofill` fills from the station record, a cached QRZ answer fills the remaining blank name, grid or QTH (through `qrz_fill`), marked `FROM_QRZ`. A new station with a cached answer no longer shows "New station — name and grid needed"; it shows "Filled from QRZ."
- **Dashboard:** after Enter, if the view asks for a grid (`needs_grid_for`) and the cached QRZ answer `can_use`, the view becomes `desk.look_up_with_qrz(call, band)`. The bearing is labelled "AA7BQ — QRZ". An approximate-only answer still shows only the button.

- [ ] **Step 1: Write the failing tests**

```python
# test_control.py
async def test_controller_fills_blanks_from_cached_qrz(user, desk, tonight, qrz_examples):
    record = parse_response(qrz_examples[1]).record
    desk.stations.add_from_roster("AA7BQ", "FRED", None, None)
    desk.qrz.save(record, "2026-10-29T00:00:00+00:00")
    transport = FakeQrz([])
    await open_control_qrz(user, desk, tonight, transport)
    field(user, "callsign").set_value("AA7BQ")
    key(user, "callsign", " ")
    await user.should_see("Filled from QRZ")
    assert field(user, "name").value == "FRED" and field(user, "grid").value == "DM32af"
    assert "from-qrz" in field(user, "grid").classes and transport.calls == 0

async def test_controller_ignores_approximate_cached_grid(user, desk, tonight, qrz_examples):
    record = replace(parse_response(qrz_examples[1]).record, geoloc="zip")
    desk.qrz.save(record, "2026-10-29T00:00:00+00:00")
    await open_control_qrz(user, desk, tonight, FakeQrz([]))
    field(user, "callsign").set_value("AA7BQ")
    key(user, "callsign", " ")
    await user.should_see("Filled from QRZ")
    assert field(user, "grid").value == ""

# test_dashboard.py
async def test_dashboard_uses_cached_qrz_location(user, desk, sim, qrz_examples):
    desk.qrz.save(parse_response(qrz_examples[1]).record, "2026-10-29T00:00:00+00:00")
    transport = FakeQrz([])
    qrz_pages(desk, transport)
    await user.open("/")
    await look_up(user, "AA7BQ")
    await user.should_see("AA7BQ — QRZ")
    assert transport.threads == [] and sim.commands == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/ui/test_control.py tests/ui/test_dashboard.py -k cached -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

On the dashboard, also apply the same rule after an automatic network lookup stores a usable answer. Add this test to the same file: `test_dashboard_auto_lookup_shows_qrz_bearing` (FakeQrz LOGIN + CALLSIGN; expects "AA7BQ — QRZ"). If the existing `test_dashboard_looks_up_unknown_calls_automatically` still passes unchanged, leave it.

- [ ] **Step 4: Run the whole suite, ruff and mypy**

Run `uv run pytest -q`, then `uv run ruff check .`, then `uv run mypy src/beam_navigator/core`.
Expected: all green.

- [ ] **Step 5: Docs and commit**

- Add decision 32 to `docs/decisions.md`. It covers:
  - example rosters as past sessions
  - the Packrat DMR Net (owner, 2026-10-29)
  - the background QRZ pass
  - cached QRZ answers fill blanks, labelled, never written to `station`
- Add one bullet to requirements 4.9: "After the example nets are added, their example stations missing a name or grid are looked up once, in the background."

`git commit -m "feat: cached QRZ answers fill blanks on the controller and dashboard (decision 32)"`
