# QRZ Callsign Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optional online lookup of name, grid and QTH from QRZ's XML Data service (requirements 4.9). It runs only when the operator presses **Look up on QRZ**, or automatically for unknown calls on the controller screen if they turn that on. The login lives in the operating system's credential store.

**Architecture:**
- `core/qrz.py` is pure. It parses responses into dataclasses and grades each location by QRZ's `geoloc`.
- `qrz_login.py` wraps `keyring`.
- `qrz_client.py` does the HTTPS POSTs, the session key and the error mapping. Its transport is injected, so tests never touch the network.
- The QRZ cache is its own table (migration 0008), so QRZ data never overwrites a station record.
- `desk.py` and `net_control.py` add the rules. `ui/` renders them.
- Network calls run in a worker thread (`nicegui.run.io_bound`). The database is touched only on the event loop, so decision 20 stands.

**Tech Stack:** stdlib `urllib.request`, `xml.etree.ElementTree` and `importlib.metadata`; `keyring` 25.7 (approved 2026-10-28); NiceGUI 3.18.

**Spec:** `docs/requirements.md` 4.9 and acceptance 34–36; invariants 1, 2 and 5. Decision 28. QRZ XML spec 1.34, saved word for word in `tests/fixtures/qrz_xml_spec_1.34.txt` (owner-supplied 2026-10-28). Tests take the five example responses from that file and never write their own XML.

## Design

**Requests** go to `https://xmldata.qrz.com/xml/current/` by HTTPS POST. The body is form-encoded, so the password is never in a URL.
- Login sends `username`, `password` and `agent=BeamNav<version>`.
- A lookup sends `s=<key>` and `callsign=<CALL>`.
- The timeout is 5 s. Responses over 200,000 bytes are refused.
- The session key is kept in memory only, never on disk.

**Parsing** follows the spec's rule: match by local tag name and ignore unknown nodes and attributes. A record holds:
- `call`
- `name`: `name_fmt` if present, else `fname` + `name`
- `grid`: kept only if `is_grid`
- `qth`: `addr2`, then `state` if present, else `country`
- `lat` and `lon`
- `geoloc`

**Location precision** comes from `geoloc` (spec, "About Lat/Long and Grid Data"):
- `user` or `grid` → **station**: the operator entered it on QRZ.
- `geocode` → **address**: geocoded from the postal address.
- `zip`, `state` or `dxcc` → **approximate**: shown with a note, like a region centroid (invariant 5). It is never offered as a grid.
- `none` or missing → **no location**.

**Errors** are each a `QrzError` with a plain message that never contains the password:

| QRZ reply | What the operator sees |
|---|---|
| no network, timeout, DNS failure | `QRZ can't be reached. Everything else works offline.` |
| no saved login | `Set up your QRZ login in Settings → QRZ.` |
| login Error, e.g. `password incorrect` | `QRZ login failed: password incorrect` |
| `Not found: CALL` | `QRZ has no record for CALL.` |
| `Session Timeout`, or no `Key` | log in again **once** and repeat the lookup once; if that fails too, show its message |
| `Connection refused` | `QRZ refused service for this login; try again tomorrow.` No more attempts until the app restarts. |
| `SubExp` = `non-subscriber` | the record is used, plus `Your QRZ login has no XML Data subscription, so QRZ sends limited data.` |
| any other Error or Message | shown as QRZ wrote it |

**Credentials:**
- Service name `beam-navigator-qrz`; entries `username` and `password`.
- Tests install an in-memory keyring backend in `tests/conftest.py` (autouse), so no test can ever write to Windows Credential Manager.

**Cache:** table `qrz_record`, with these columns:
- callsign (primary key)
- name, grid, qth
- lat, lon
- geoloc
- looked_up_at (UTC)

A new lookup replaces the cached row. The cached row is shown offline as `from QRZ, 2026-10-28`.

**Dashboard:**
- When the target is a callsign, a **Look up on QRZ** button appears.
- The result card shows the name, grid and QTH, `from QRZ, <date>`, and the precision text.
- For station or address precision there is **Use this location**. It shows the bearing with source `QRZ` and does not save it to the station record.
- Approximate shows the bearing with a note that it is approximate. No location shows no bearing.

**Controller screen:**
- A **Look up on QRZ** button sits in the info panel.
- It fills only **blank** Name, Grid and QTH fields, in the "from QRZ" style (italic with a QRZ tag). A grid is filled only for station or address precision.
- Logging works as now: a new station is created by the existing gap-fill rule (decision 13).
- If `qrz_auto` is on and auto-fill finds no record, the same lookup runs by itself.

**Settings → QRZ tab:**
- username and password (`password=True`); the password is never shown back
- **Save**, **Test login** (shows `Logged in. Subscription until …` or the error) and **Clear**
- an **Auto-look up unknown calls on the controller screen** switch (setting `qrz_auto`, off by default)

## Global Constraints

- Offline-first (invariant 1): every existing test passes with no network. QRZ only adds data.
- No rotator command from any lookup (invariant 2).
- Never invent a location (invariant 5): approximate QRZ positions are labelled, and `none` gives no bearing.
- The password is never in the database, settings, logs, exports, notifications or exception text (acceptance 35).
- No new dependencies beyond `keyring`. `ruff` line length 100; `mypy --strict` on `core`.

## Review Focus

1. **A QRZ grid when a roster or saved grid exists:** the station record is unchanged, and the dashboard still uses the saved grid unless the operator presses **Use this location**. Task 5 `test_qrz_never_overwrites_saved_grid` (acceptance 36).
2. **`geoloc` = `state` or `dxcc`:** never offered as a grid, and the bearing is labelled approximate. Task 1 `test_precision_from_geoloc`, Task 5 `test_approximate_location_labelled`.
3. **The session expires mid-session:** exactly one re-login and one repeat, never a loop. Task 3 `test_session_timeout_relogs_once`.
4. **Password leakage:** after a failed and a successful login, the password string is absent from the db file, settings rows, captured logs, notifications and exception text. Task 3 `test_password_never_in_errors`, Task 7 `test_password_never_persisted`.
5. **The UI stays responsive while QRZ is slow:** the lookup runs in `run.io_bound`, and the database is written only after it returns. Task 6 `test_lookup_runs_off_the_event_loop`.

---

### Task 1: Parse QRZ responses (pure)

**Files:** Create `src/beam_navigator/core/qrz.py` and `tests/unit/test_qrz_parse.py`.

**Interfaces:**
- Produces:
  - `Precision = Literal["station", "address", "approximate", "none"]`
  - `QrzSession(key: str | None, count: int | None, sub_exp: str | None, message: str | None, error: str | None)`
  - `QrzRecord(call: str, name: str | None, grid: str | None, qth: str | None, lat: float | None, lon: float | None, geoloc: str | None)`, with a `precision` property
  - `QrzResponse(session: QrzSession, record: QrzRecord | None)`
  - `parse_response(data: bytes) -> QrzResponse`, which raises `ValueError("QRZ sent a reply Beam Navigator cannot read.")` for non-XML, a missing `<QRZDatabase>` or more than 200,000 bytes
  - `MAX_REPLY = 200_000`

- [ ] **Step 1: Write the failing tests.** A helper `spec_examples() -> list[bytes]` takes the five `<?xml … </QRZDatabase>` blocks, in order, from `tests/fixtures/qrz_xml_spec_1.34.txt`.
  - `test_login_example`: key `2331uf894c4bd29f3923f3bacf02c532d7bd9`, count 123, sub_exp `Wed Jan 1 12:34:03 2013`, record `None`.
  - `test_callsign_example`:
    - call `AA7BQ`
    - name `FRED "The Boss" LLOYD`
    - grid `DM32af`
    - qth `SCOTTSDALE, AZ`
    - lat 34.23456, lon −112.34356
    - geoloc `user`, precision `station`
  - `test_dxcc_example_has_no_record`: the DXCC reply gives `record is None` and the session key `d0cf…122d`.
  - `test_not_found_example`: error `Not found: g1srdd`, key present.
  - `test_session_timeout_example`: error `Session Timeout`, key `None`.
  - `test_precision_from_geoloc`, parametrised over the seven spec values plus missing: user/grid → station, geocode → address, zip/state/dxcc → approximate, none/missing → none. Built by `replace` on the parsed AA7BQ record, not new XML.
  - `test_unreadable_replies`: `b""`, `b"<html>"`, a 200,001-byte reply and `b"\x00"` each raise the plain ValueError.
- [ ] **Step 2: Run.** `uv run pytest tests/unit/test_qrz_parse.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement.** Use `ElementTree.fromstring`, with each tag compared after `split("}")[-1]`. Python 3.12+ ships expat ≥ 2.4, whose amplification limits stop entity bombs, and the 200 KB cap bounds the input. When `name_fmt` is missing, the name is fname and name joined with a space, ignoring blanks.
- [ ] **Step 4: Run.** `uv run pytest -q && uv run mypy src/beam_navigator/core`. Expected: all pass.
- [ ] **Step 5: Commit.** `feat: parse QRZ XML replies, graded by geoloc (spec 4.9)`

### Task 2: QRZ login in the credential store

**Files:**
- Create `src/beam_navigator/qrz_login.py` and `tests/unit/test_qrz_login.py`.
- Modify `tests/conftest.py`: an autouse fixture that sets an in-memory `keyring` backend for every test and restores the old one afterwards.

**Interfaces:**
- Produces:
  - `SERVICE = "beam-navigator-qrz"`
  - `save_login(username: str, password: str) -> None`, which raises `ValueError` on a blank username or password
  - `load_login() -> tuple[str, str] | None`
  - `saved_username() -> str | None`
  - `clear_login() -> None`

- [ ] **Step 1: Write the failing tests.**
  - round trip
  - blank refused
  - clear removes both entries
  - `load_login()` is `None` when only one of the two is saved
  - the conftest backend is the one in use (assert `keyring.get_keyring()` is the test class), so tests can never reach the real vault
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** with `keyring.get_password`, `set_password` and `delete_password`. Treat `keyring.errors.PasswordDeleteError` on clear as already clear.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit.** `feat: QRZ login kept in the OS credential store (spec 4.9)`

### Task 3: QRZ client

**Files:** Create `src/beam_navigator/qrz_client.py` and `tests/unit/test_qrz_client.py`.

**Interfaces:**
- Consumes: Task 1 `parse_response`; Task 2 `load_login`.
- Produces:
  - `URL = "https://xmldata.qrz.com/xml/current/"`
  - `Transport = Callable[[str, dict[str, str]], bytes]`
  - `https_post(url, fields) -> bytes`, the default: `urllib.request.urlopen` with POST, a 5 s timeout and a read limit of `MAX_REPLY + 1`
  - `class QrzError(Exception)`
  - `QrzClient(transport: Transport = https_post, agent: str = default_agent())` with:
    - `login() -> QrzSession`
    - `lookup(callsign: str) -> tuple[QrzRecord, str | None]`, where the second value is the notice to show, e.g. the non-subscriber text

The client is safe to call from a worker thread: it holds no database connection.

- [ ] **Step 1: Write the failing tests.** A fake transport replays spec examples and records `(url, fields)`.
  - `test_login_posts_fields`: one POST to `URL` with username, password and an agent starting `BeamNav`. The URL contains no password.
  - `test_lookup_reuses_key`: two lookups make one login and two lookups.
  - `test_session_timeout_relogs_once`: replies are login, timeout, login, callsign, so the lookup succeeds after exactly four calls. With login, timeout, login, timeout, it raises after four calls with the timeout message.
  - `test_not_found_message`: `QRZ has no record for G1SRDD.`
  - `test_login_failed_message`: an Error of `password incorrect` gives `QRZ login failed: password incorrect`. This reuses the timeout example's Session node with its Error text changed to `password incorrect`, built with ElementTree from the example, not handwritten. Ledger it as a derived example.
  - `test_offline_message`: the transport raises `URLError` and then `TimeoutError`; both give `QRZ can't be reached. Everything else works offline.`
  - `test_no_login_message`: with nothing saved, the message is the Settings hint.
  - `test_connection_refused_stops`: after a `Connection refused` Error, the next lookup raises at once with no transport call.
  - `test_password_never_in_errors`: for every case above, the password is not in `str(exc)` or `repr(exc)`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** `default_agent()` is `f"BeamNav{importlib.metadata.version('beam-navigator')}"`, falling back to `"BeamNav"`. URLError and OSError are caught by type, never by matching message text.
- [ ] **Step 4: Run** the full suite. Expected: pass, with no real network calls (the default transport is never used in tests).
- [ ] **Step 5: Commit.** `feat: QRZ XML client — one login per session, one retry on timeout (spec 4.9)`

### Task 4: QRZ cache

**Files:**
- Create `src/beam_navigator/store/migrations/0008_qrz_record.sql`.
- Modify `store/repositories.py` (`QrzRepository`) and `desk.py` (`self.qrz = QrzRepository(conn)`).
- Test: `tests/unit/test_store_qrz.py` and the schema-version pins (7 → 8).

**Interfaces:**
- Produces `QrzRepository.save(record: QrzRecord, when: str) -> None` and `QrzRepository.get(callsign: str) -> tuple[QrzRecord, str] | None` (the record and its date).

- [ ] **Step 1: Write the failing tests.**
  - Save AA7BQ, then get it back with its date.
  - A second save replaces the first.
  - The station table is untouched.
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS).
- [ ] **Step 5: Commit.** `feat: QRZ results cached apart from station records (spec 4.9)`

### Task 5: Dashboard rules

**Files:**
- Modify `desk.py`:
  - `QrzView`, a dataclass with fields `name, grid, qth, source_text, precision_text, can_use, notice, error`
  - `Desk.qrz_view(callsign) -> QrzView | None`, which reads the cache
  - `Desk.qrz_store(record, notice) -> QrzView`
  - `Desk.look_up_with_qrz(callsign, band) -> LookupView`
- Modify `core/targets.py` only if `Resolution.source` needs a `"QRZ"` literal.
- Test: `tests/unit/test_desk_qrz.py`.

The precision texts are:

| Precision | Text |
|---|---|
| station | `Location entered by the station on QRZ.` |
| address | `Location from the station's postal address; may not be where they operate.` |
| approximate | `Approximate: QRZ only knows the zip code, state or country.` |
| none | `QRZ has no location for this station.` |

- [ ] **Step 1: Write the failing tests.**
  - `test_qrz_view_reads_cache`: source text `from QRZ, 2026-10-28`.
  - `test_look_up_with_qrz_labels_source`: the bearing view's source is QRZ, and nothing is saved to stations.
  - `test_qrz_never_overwrites_saved_grid`: a station saved with FN20ok and a cached QRZ DM32af. The station record and `look_up("AA7BQ")` still use FN20ok (acceptance 36).
  - `test_approximate_location_labelled`: geoloc `state` gives `can_use` False for the grid, and `look_up_with_qrz` carries the approximate note in `coarse_note`.
  - `test_no_location_no_bearing`.
- [ ] **Steps 2–5:** RED, implement, GREEN, commit `feat: QRZ results on the dashboard, labelled and never overwriting (spec 4.9)`.

### Task 6: UI — dashboard and controller

**Files:**
- Modify `ui/lookup.py`, `ui/control.py` and `net_control.py` (`NetControl.qrz_fill(entry: Entry, record: QrzRecord) -> Entry`, which fills blanks only, and the grid only for station or address precision).
- Modify `ui/app.py`, so `register_pages` takes an optional `qrz_factory: Callable[[], QrzClient]` (default `QrzClient`). Tests pass a fake.
- Test: `tests/ui/test_dashboard.py`, `tests/ui/test_control.py`, `tests/unit/test_net_control.py`.

The UI pattern is `record, notice = await run.io_bound(client.lookup, call)`, then `desk.qrz_store(...)` on the loop. Errors become notifications.

- [ ] **Step 1: Write the failing tests.**
  - `test_dashboard_qrz_button`: K9ZZZ is unknown, so **Look up on QRZ** (marker `qrz-lookup`) shows `from QRZ` and **Use this location** (marker `qrz-use`) gives a bearing with `QRZ`.
  - `test_dashboard_qrz_offline`: a transport raising URLError shows `QRZ can't be reached`, and the page still works.
  - `test_controller_qrz_fills_blanks`: the name is typed, so it is kept, and the grid and QTH fill with the `from-qrz` class.
  - `test_controller_auto_lookup`: with `qrz_auto` on and an unknown call plus Space, the lookup runs once. With it off, it makes zero transport calls.
  - `test_lookup_runs_off_the_event_loop`: the fake transport records `threading.get_ident()`, which differs from the test's thread.
  - `test_no_rotator_command_from_lookup`: the simulator gets zero commands.
- [ ] **Steps 2–5:** RED, implement, GREEN, commit `feat: Look up on QRZ on the dashboard and controller screen (spec 4.9)`.

### Task 7: Settings → QRZ tab, acceptance 34–36, docs

**Files:** Modify `ui/settings.py`, `docs/decisions.md` (decision 29) and `docs/user-notes` if one exists, otherwise nothing. Test `tests/ui/test_settings.py` and `tests/unit/test_qrz_acceptance.py`.

- [ ] **Step 1: Write the failing tests.**
  - `test_qrz_tab_save_and_test_login`: save, then **Test login** with a fake client shows `Logged in. Subscription until Wed Jan 1 12:34:03 2013`. The password field is empty after saving.
  - `test_qrz_tab_clear`.
  - `test_auto_switch_persists`.
  - `test_offline_lookup_changes_nothing` (acceptance 34): the counts in the stations, qrz_record and checkin tables are unchanged after an offline failure.
  - `test_password_never_persisted` (acceptance 35): run a failed and a successful login, then a lookup, then export a session. Read the raw bytes of a file database (in `tmp_path`), every `setting` row, captured `caplog` text and the export text. None contains the password.
  - `test_qrz_grid_never_overwrites` (acceptance 36): the end-to-end version of the Task 5 test through the dashboard.
- [ ] **Steps 2–4:** RED, implement, GREEN. Run `uv run pytest -q && uv run ruff check . && uv run mypy src/beam_navigator/core`.
- [ ] **Step 5: Decision 29 and commit.** Decision 29: `QRZ lookups follow spec 1.34 (tests/fixtures/qrz_xml_spec_1.34.txt): HTTPS POST, one cached session key in memory, one re-login on Session Timeout, no retry loop; location precision from geoloc; results cached apart from station records; the login lives only in keyring.` Commit: `feat: Settings → QRZ; acceptance 34–36 (spec 4.9)`.

**After the plan, with the owner's consent only:** one live check, in which the owner enters their own login in Settings and looks up a known call. Nothing in the tests or the build contacts QRZ.
