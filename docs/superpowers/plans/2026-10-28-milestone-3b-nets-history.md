# Milestone 3b — Nets, History and `*.beamnet.json` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The operator can manage their nets: add, edit, duplicate, archive, and share them as `*.beamnet.json` files. Each net has a page showing its next occurrence, default controller, past sessions and known participants.

**Architecture:** The pattern stays the same.
- `core/schedule.py` is pure: weekdays, start times, time zones and the next occurrence.
- `nets.py` holds the net rules: validation, duplicate, archive, listing and the net view.
- `beamnet.py` reads and writes the file format.
- `ui/nets.py` only renders and calls these. It replaces `nets_page` in `ui/live_net.py`.
- Nothing on these pages moves a rotator.

**Tech Stack:** Python 3.12+, NiceGUI 3.18 (`ui.upload`, `ui.download`), `sqlite3`, standard `json` and `zoneinfo` (with `tzdata`). No new dependencies.

**Spec:** `docs/requirements.md` v2.0.
- Section 3: Net entity and key rules.
- Section 4.6.
- Section 6: Milestone 3.
- Section 7: test 32 (malformed input).
- `docs/decisions.md` 24 (time zone order).

**Out of scope:**
- Key remapping (4.5 "All keys remappable"). It moves to plan 3c, and decisions 22 and 23 are updated to say so.
- Whole-database backup and the JSON/CSV export of everything (4.8). These are Milestone 4.

## Design

**Weekday** is stored as 0–6 with 0 = Monday, matching Python's `date.weekday()`. In files it is written as a lowercase English day name (`"tuesday"`), so no other tool has to guess the numbering.

**Start time** is `HH:MM`, 24-hour, in the net's time zone. Blank means not scheduled.

**Time zone** order is decision 24: the net's zone, then the active profile's, then this PC's. Saving a net with a zone name that is not real is refused with the reason. A bad zone that is already stored is skipped at display, as decision 24 says.

**Next occurrence** is the first moment at or after now that falls on the net's weekday at its start time. If today is the net's day but the start time has passed, it is next week. Text: `Tue 3 Nov 2026, 20:00 EST`. When the weekday or start time is missing: `Not scheduled`.

**Preferred rotator** is the domain model's per-net rotator (spec 3), stored as `net.rotator_id`. The live net screen offers it first, then the band's default rotator. Choosing it never sends a command.

**Net names** are unique ignoring case and surrounding spaces.

**Duplicate** copies every field except id and archived into a new net named `<name> (copy)`, then `(copy 2)` and so on. Sessions are not copied.

**Archive** hides a net from the nets list (unless **Show archived** is on) and from the import page's net picker. Its history page and its sessions still open. Unarchive brings it back.

**Editing a net** changes only the net. Past sessions keep their own controller and check-ins (spec 3: a session's controller is copied, not linked).

**`*.beamnet.json`, schema 1:**
```json
{"format": "beamnet", "schema": 1, "nets": [
  {"name": "...", "weekday": "tuesday", "start_time": "20:00", "timezone": "America/New_York",
   "frequency_mhz": 144.245, "channel": null, "mode": "FM", "band": "2 m",
   "default_controller_call": "...", "default_controller_grid": "..."}]}
```
- **Left out:** id, archived, rotator (local hardware), sessions and check-ins (history is private; backup is Milestone 4).
- **Refused, whole file:** larger than 1,000,000 bytes, not UTF-8, not JSON, not an object, `format` is not `"beamnet"`, `schema` is not an integer, or `nets` is not a list. A schema above 1 gives `This file was made by a newer Beam Navigator (schema N).`
- **Refused, one net:** the same validation as saving a net in the form. The other nets still import.
- **Existing name:** the net is skipped and the existing net is left untouched. Import never overwrites.
- **Unknown keys** are ignored, so later versions can add fields.
- **Result:** a report listing each added name and each skipped `name: reason`.
- **Filenames:** `<slug>.beamnet.json` for one net (slug = lowercase letters, digits and `-`), `nets-YYYY-MM-DD.beamnet.json` for **Export all** (all nets that are not archived).

**Example nets** (spec 4.6: offered at first run, opt-in, labelled unverified). The source is the owner's schedule, saved word for word in `docs/example-nets-source.txt` (2026-10-28). The data is `src/beam_navigator/data/example_nets.beamnet.json`, read with the Task 4 reader. Only what the source states goes in; everything else stays blank.

| Name | Day | Start | Zone | MHz | Band | Controller |
|---|---|---|---|---|---|---|
| Pack Rats Monday 50 MHz | Mon | 19:30 | — | 50.150 | 6 m | N3RG · FM29ki |
| Pack Rats Monday 144 MHz | Mon | 20:00 | — | 144.245 | 2 m | W2KV · FN20ok |
| Pack Rats Monday 222 MHz | Mon | 20:30 | — | 222.125 | 1.25 m | KC3BVL · FM29jw |
| Pack Rats Monday 432 MHz | Mon | 21:00 | — | 432.110 | 70 cm | WB2RVX · FM29mt |
| K1WHS 222 MHz Tuesday Activity Night | Tue | 19:00 | America/New_York | — | 1.25 m | — |
| Chesapeake Bay Mud Toads Net (KD8UD) | Tue | 20:00 | — | 144.250 | 2 m | — |
| DVFRC Friday 144 MHz | Fri | 19:30 | — | 144.160 | 2 m | — |
| DVFRC Friday 50 MHz | Fri | 20:00 | — | 50.160 | 6 m | — |
| DVFRC Friday 222 MHz | Fri | 20:30 | — | 222.150 | 1.25 m | — |
| DVFRC Friday 1296 MHz | Fri | 20:45 | — | 1296.160 | 23 cm | — |
| DVFRC Friday 432 MHz | Fri | 21:00 | — | 432.160 | 70 cm | — |
| DVFRC Friday 2304 MHz | Fri | 21:15 | — | 2304.100 | — | — |
| DVFRC Friday 903 MHz | Fri | 21:30 | — | 903.100 | 33 cm | — |

- **Zone** is set only where the source says "Eastern Time". The other rows use the profile's zone (decision 24).
- **Controller** is set only where the source pairs a call with a net. KD8UD and K1WHS stay in the names, because the source does not say they run the net. The Friday nets name no controller; Jim only says he enjoys them.
- **Not stored:** mode and duration (the model has no duration field). There is no band for 2304 MHz, because 13 cm is not in the band table.
- **Unverified flag:** a new `net.unverified` column (migration 0006), shown as an `Example — unverified` badge. Saving the net from the form with **I've checked these details** ticked clears it. The beamnet field is `"unverified": true` (optional; when absent, false).
- **The offer:** until the operator chooses, the nets page shows a banner, `Add example nets? Pack Rats and Friday night nets, from a published schedule. Unverified — check before use.`, with **Add examples** and **No thanks**. The choice is stored in the `example_nets` setting (`added` or `declined`), and the banner never returns after either. The first-run wizard (Milestone 4) will reuse it. Nets whose names already exist are skipped (Task 4 rule).

## Global Constraints

- **No rotator commands** from any page in this plan (invariant 2). Choosing a preferred rotator sends nothing.
- **Never invent locations or data** (invariant 4). A missing grid or schedule stays blank. Tests use clearly made-up nets ("Test net"), not real schedules.
- **Offline.** Import and export are local files only.
- **History is never lost.** Archive replaces delete in the UI. `NetRepository.delete_net` keeps refusing nets with sessions.
- **Session snapshots.** Editing a net never rewrites past sessions (spec 3).
- **Logic stays out of `ui/`.** `mypy --strict` covers `core/`. `ruff` line length is 100.

## Review Focus

1. **A file holding a net whose name already exists** (any case): skipped, and the existing net is unchanged. Task 4 `test_import_never_overwrites`.
2. **Garbage files:** binary, 1 MB+, a JSON list, a wrong format, or schema 2. Each gives a clear error and imports nothing. Task 4 `test_bad_files_refused` (parametrised).
3. **Today is net day but the start time has passed,** or the next date crosses a DST change. Task 2 `test_next_occurrence_after_start_is_next_week` and `test_next_occurrence_across_dst`.
4. **An archived net with past sessions:** hidden from the list and the import picker, while its history page still opens. Task 3 `test_archived_hidden_but_history_kept` and Task 6 `test_archived_net_page_opens`.
5. **Editing the default controller** leaves earlier sessions' controllers unchanged. Task 3 `test_edit_does_not_rewrite_sessions`.

---

### Task 1: Preferred rotator on the net

**Files:**
- Create: `src/beam_navigator/store/migrations/0005_net_rotator.sql`
- Modify: `src/beam_navigator/core/models.py` (`Net`), `src/beam_navigator/store/repositories.py` (`save_net`, `get_net`), `src/beam_navigator/live_net.py` (`LiveNet.view`)
- Test: `tests/unit/test_store_nets.py`, `tests/unit/test_live_net.py`

**Interfaces:**
- Produces: `Net.rotator_id: int | None = None`, the last field with a default, so existing positional constructors still work. `NetRepository.save_net`/`get_net` round-trip it.

- [ ] **Step 1: Write the failing tests**
  - `test_net_keeps_preferred_rotator`: save a rotator profile, then save a net with `rotator_id` set. `get_net(...).rotator_id == profile.id`.
  - `test_deleting_rotator_clears_net_preference`: delete that rotator (raw `DELETE FROM rotator_profile` is fine in the test). Then `get_net(...).rotator_id is None`.
  - In `test_live_net.py`, `test_preferred_rotator_offered_first`: the band has rotator A and the net prefers rotator B, so `view(...).rotator.id == B`. A recording simulator gets zero commands from `view`.
- [ ] **Step 2: Run them.** `uv run pytest tests/unit/test_store_nets.py tests/unit/test_live_net.py -q`. Expected: FAIL (`Net` has no `rotator_id`).
- [ ] **Step 3: Implement.**
  - Migration: `ALTER TABLE net ADD COLUMN rotator_id INTEGER REFERENCES rotator_profile (id) ON DELETE SET NULL;`
  - Add the field to `Net` and to both SQL statements in `save_net`.
  - In `LiveNet.view`: if `net.rotator_id` is set, use that profile; otherwise use `self.desk.default_rotator(net.band)`. A missing profile falls back as well.
- [ ] **Step 4: Run.** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `feat: a net's preferred rotator (spec 3)`

### Task 2: Schedule rules (pure)

**Files:**
- Create: `src/beam_navigator/core/schedule.py`, `tests/unit/test_schedule.py`
- Modify: `src/beam_navigator/net_control.py` (`_zone` uses `zone_for`), `docs/decisions.md` (decision 25)

**Interfaces:**
- Produces:
  - `WEEKDAYS: tuple[str, ...] = ("monday", …, "sunday")`
  - `parse_start_time(text: str) -> str | None`: blank gives `None`; `"8:05"` gives `"08:05"`; anything else raises `ValueError("Start time must be HH:MM, 24-hour.")`
  - `zone_for(*names: str | None) -> tzinfo | None`: the first real zone, as in decision 24
  - `check_zone(name: str) -> str | None`: blank gives `None`; an unknown zone raises `ValueError("Unknown time zone 'X'. Use a name like America/New_York.")`
  - `next_occurrence(weekday: int, start_time: str, zone: tzinfo | None, now: datetime) -> datetime`: `now` is aware; the result is aware in `zone` (local when `None`)
  - `occurrence_text(when: datetime | None) -> str`: `"Tue 3 Nov 2026, 20:00 EST"` or `"Not scheduled"`

- [ ] **Step 1: Write the failing tests** in `test_schedule.py`. `now` is always passed in.
  - `test_next_occurrence_later_today`: weekday 1 (Tue), `"20:00"`, New York zone, now = Tue 2026-11-03 18:00 New York. Result is 2026-11-03 20:00.
  - `test_next_occurrence_after_start_is_next_week`: same, but now = 20:01. Result is 2026-11-10 20:00.
  - `test_next_occurrence_across_dst`: weekday 6 (Sun), `"20:00"`, New York, now = Sat 2026-10-31 12:00 EDT. Result is 2026-11-01 20:00 with `utcoffset() == -5h` (EST).
  - `test_occurrence_text`: the New York 2026-11-03 20:00 result gives `"Tue 3 Nov 2026, 20:00 EST"`, and `occurrence_text(None) == "Not scheduled"`.
  - `test_parse_start_time`, parametrised: `"20:00"`, `"8:05"`→`"08:05"`, `""`→`None`. `"24:00"`, `"8pm"` and `"2000"` raise.
  - `test_zone_for_skips_unknown`: `zone_for("Not/AZone", "Asia/Tokyo")` is Tokyo, and `zone_for(None, " ")` is `None`.
  - `test_check_zone`: `"America/NewYork"` raises, and the message contains `America/New_York`.
- [ ] **Step 2: Run.** `uv run pytest tests/unit/test_schedule.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `core/schedule.py`.** Build the result with `datetime.combine(day, time, tzinfo=zone)`; `ZoneInfo` handles DST. Day names come from `WEEKDAYS` and month names from a fixed English tuple, so the output does not depend on the PC's locale. Replace the body of `NetControl._zone` with `zone_for(net.timezone, profile.timezone if profile else None)`.
- [ ] **Step 4: Run.** `uv run pytest -q && uv run mypy src/beam_navigator/core`. Expected: all pass, mypy clean.
- [ ] **Step 5: Decision 25 and commit.** Add to `docs/decisions.md`: `25. **Net schedules.** Weekday 0 = Monday (Python's numbering); files use day names. Start time is HH:MM in the net's zone (decision 24 order). An unknown zone is refused when a net is saved. Next occurrence is the first weekday-and-time at or after now.` Commit: `feat: net schedules and next occurrence (spec 4.6)`

### Task 3: Net rules — form, save, duplicate, archive, view

**Files:**
- Create: `src/beam_navigator/nets.py`, `tests/unit/test_nets.py`

**Interfaces:**
- Consumes: Task 1 `Net.rotator_id`; Task 2 `parse_start_time`, `check_zone`, `zone_for`, `next_occurrence`, `occurrence_text`, `WEEKDAYS`.
- Produces:
  - `NetForm`, a dataclass of what the form holds:
    - `name: str`
    - `weekday: int | None`
    - `start_time: str`, `timezone: str`, `frequency: str`, `channel: str`, `mode: str`
    - `band: str | None`
    - `controller_call: str`, `controller_grid: str`
    - `rotator_id: int | None`
  - `NetSummary(net: Net, next_text: str, session_count: int)`
  - `NetView(net: Net, next_text: str, controller_text: str, sessions: list[tuple[Session, int]], participants: list[Participant])`
  - `NetBook(conn: sqlite3.Connection, desk: Desk)` with:
    - `form_for(net_id: int) -> NetForm`
    - `save(form: NetForm, net_id: int | None = None) -> Net`
    - `duplicate(net_id: int) -> Net`
    - `set_archived(net_id: int, archived: bool) -> None`
    - `listing(now: datetime, show_archived: bool = False) -> list[NetSummary]`
    - `view(net_id: int, now: datetime) -> NetView`
    - `pickable() -> list[Net]` (not archived, for the import page)

**Save rules, in order (first failure raises `ValueError` with this text):**
1. Name blank: `A net needs a name.`
2. Name taken by another net, ignoring case: `A net called X already exists.`
3. Start time is checked with `parse_start_time`, and the zone with `check_zone`.
4. A weekday without a start time, or the reverse: `Give both a weekday and a start time, or neither.`
5. Frequency must be blank or a positive finite number: `Frequency must be a positive number of MHz.`
6. Band must be `None` or a band in the band table: `Unknown band 'X'. Add it in Settings → Bands first.`
7. Controller call must be blank or a callsign after `normalize_callsign`: `'X' is not a callsign.`
8. Controller grid must be blank or a grid: `'X' is not a grid square.`
9. Rotator must be `None` or an existing profile.

Blanks are stored as `None`. Editing keeps `archived` as it was.

- [ ] **Step 1: Write the failing tests** in `test_nets.py`, using an in-memory db, the bands seeded by migration 0003, and the `now` passed in.
  - `test_save_and_form_round_trip`: save a form with every field set, then `form_for` returns the same values (call upper-cased).
  - `test_save_rules`, parametrised over each rule above. Each asserts the exact message and that `list_nets()` is unchanged.
  - `test_name_unique_ignoring_case`: `"Test net"` exists, so saving `" test NET "` as a new net raises. Re-saving the same net under its own name works.
  - `test_duplicate_names_copies`: duplicate twice gives `"Test net (copy)"` and `"Test net (copy 2)"`. The fields match, `archived` is False, and the copies have no sessions.
  - `test_archived_hidden_but_history_kept`: archive a net that has a session. It is missing from `listing(now)` and from `pickable()`, present in `listing(now, show_archived=True)`, and `view` still lists its session.
  - `test_edit_does_not_rewrite_sessions`: start a session with controller K1ABC, then change the net's default controller. `get_session` still says K1ABC.
  - `test_view_participants_and_controller`: import the W2KV fixture into a test net. `view` lists 17 participants, ordered by sessions attended then callsign. `controller_text` is `"No default controller"` with nothing set, `"W2KV · FN20ok"` with both set, and `"W2KV · grid unknown"` with only the call.
  - `test_listing_next_text`: a scheduled net shows the `occurrence_text` value; an unscheduled one shows `"Not scheduled"`.
- [ ] **Step 2: Run.** `uv run pytest tests/unit/test_nets.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `nets.py`.** The zone for `next_text` is `zone_for(net.timezone, active profile timezone)`. Participants come from `NetRepository.participants`, sorted with `(-sessions_attended, callsign)`.
- [ ] **Step 4: Run.** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `feat: net rules — edit, duplicate, archive, history view (spec 4.6)`

### Task 4: `*.beamnet.json` read and write

**Files:**
- Create: `src/beam_navigator/beamnet.py`, `tests/unit/test_beamnet.py`

**Interfaces:**
- Consumes: Task 3 `NetForm`, `NetBook.save`, `NetBook.pickable`; `NetRepository.get_net`.
- Produces:
  - `SCHEMA = 1`, `MAX_BYTES = 1_000_000`
  - `class BeamnetError(ValueError)`
  - `write_beamnet(nets: list[Net]) -> bytes`: UTF-8 JSON with `indent=2` and keys in the Design order
  - `read_beamnet(data: bytes) -> list[tuple[str, NetForm | str]]`: each entry is (name, form) or (name or `"net N"`, reason)
  - `ImportReport(added: list[str], skipped: list[str])`
  - `import_beamnet(book: NetBook, data: bytes) -> ImportReport`
  - `beamnet_filename(nets: list[Net], today: date) -> str`

- [ ] **Step 1: Write the failing tests.**
  - `test_round_trip`: write two saved nets (one with a channel and no frequency), delete them from a fresh db (or use a second in-memory db), and import. Both are added and `form_for` matches the originals. The written JSON has `"weekday": "tuesday"` and no `id`, `archived` or `rotator_id`.
  - `test_import_never_overwrites`: the db has `"Test net"` with frequency 144.2, and the file has `"TEST NET"` with 432.1. The report reads `skipped == ["TEST NET: a net with this name already exists; not changed"]`, and the stored frequency is still 144.2.
  - `test_bad_net_skipped_others_added`: one net has grid `"ZZ99"`, the other is fine. One is added, and the skipped one names `ZZ99`.
  - `test_bad_files_refused`, parametrised. Each raises `BeamnetError` with a message, and no nets are added:
    - `b"\x00\xff" * 10`
    - `b" " * 1_000_001`
    - `b"[]"`
    - `b'{"format": "other", "schema": 1, "nets": []}'`
    - `b'{"format": "beamnet", "schema": 2, "nets": []}'`, whose message contains `newer Beam Navigator (schema 2)`
    - `b'{"format": "beamnet", "schema": "1", "nets": []}'`
    - `b'{"format": "beamnet", "schema": 1, "nets": {}}'`
  - `test_unknown_keys_ignored`: an extra top-level key and an extra net key still import.
  - `test_wrong_field_type_skips_net`: `"frequency_mhz": "fast"` or `"weekday": "funday"` skips that net with a reason.
  - `test_filenames`: one net `"W2KV 2 m"` gives `"w2kv-2-m.beamnet.json"`; several give `"nets-2026-10-28.beamnet.json"`.
- [ ] **Step 2: Run.** `uv run pytest tests/unit/test_beamnet.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `beamnet.py`.** The name-exists check runs before `book.save`, so the reason text is the fixed one above. Every other per-net reason is the `ValueError` text from `save`.
- [ ] **Step 4: Run.** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Decision 26 and commit.** Add: `26. **\`*.beamnet.json\` shares net definitions only** (schema 1, Design section of plan 3b): no ids, archive flag, rotator or history. Import adds new nets and never overwrites one with the same name (ignoring case); a bad net is skipped with its reason; a bad file imports nothing.` Commit: `feat: *.beamnet.json import and export (spec 4.6)`

### Task 5: Nets list page

**Files:**
- Create: `src/beam_navigator/ui/nets.py`, `tests/ui/test_nets_page.py`
- Modify: `src/beam_navigator/ui/live_net.py` (remove `nets_page`), `src/beam_navigator/ui/app.py` (`/nets` uses `ui/nets.nets_page(book, bands, rotators)`), `src/beam_navigator/ui/roster.py` (the net picker uses `NetBook.pickable()`)

**Interfaces:**
- Consumes: Tasks 3 and 4.
- Produces:
  - `nets_page(book: NetBook, band_names: list[str], rotators: list[RotatorProfile]) -> None`
  - `net_form_dialog(book, band_names, rotators, on_saved: Callable[[Net], object]) -> Callable[[int | None], None]`, which opens the dialog for a new net (`None`) or fills it for an edit

**The page:**
- Top row: **New net**, **Import nets** (`ui.upload`, auto-upload, accepts `.json`), **Export all**, and a **Show archived** switch.
- One card per net:
  - the name (linked to `/nets/{id}`), the next occurrence, the frequency or channel, and the band
  - the existing session rows and the date + **Start session** controls, with markers `start-date-{id}` and `start-{id}` unchanged
  - buttons **Edit**, **Duplicate**, **Export**, and **Archive** or **Unarchive**
- Markers: `net-card-{id}`, `edit-{id}`, `duplicate-{id}`, `archive-{id}`, `export-{id}`, `import-nets`, `export-all`, `show-archived`.
- Form inputs use markers `form-name`, `form-weekday`, `form-start`, `form-zone`, `form-frequency`, `form-channel`, `form-mode`, `form-band`, `form-call`, `form-grid` and `form-rotator`, plus a `form-save` button.
- The import report shows in a dialog: an `Added: …` line and one line per skipped net.
- Buttons use the existing `BLUR` handler.

- [ ] **Step 1: Write the failing tests** in `test_nets_page.py`. Use the `user` fixture, `register_pages(lambda: desk)` and a simulator desk, as in `test_control.py`.
  - `test_new_net_from_form`: open `/nets`, click **New net**, fill the name, weekday Tuesday, `20:00`, `America/New_York`, and click save. The card shows `Tue`, and the stored net has weekday 1.
  - `test_form_error_shown`: zone `America/NewYork` shows `Unknown time zone` and nothing is saved.
  - `test_duplicate_and_archive`: **Duplicate** shows `Test net (copy)`. **Archive** on the copy hides it, and **Show archived** shows it again.
  - `test_import_file_reports`: `await upload.handle_uploads([ui.upload.SmallFileUpload("x.beamnet.json", "application/json", data)])` with one new and one existing net. The page shows `Added: New net` and `already exists`.
  - `test_export_one_downloads`: **Export** gives `user.download.next()` with `"format": "beamnet"` and the net name.
  - `test_import_page_hides_archived`: an archived net is not among the `/import` net select's options.
  - The existing `tests/ui/test_live_net_page.py` start-session test still passes unchanged.
- [ ] **Step 2: Run.** `uv run pytest tests/ui/test_nets_page.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `ui/nets.py`** and wire it into `app.py` and `roster.py`. `ui.download.content(bytes, filename)` serves exports. `now` is `datetime.now(UTC)` at render.
- [ ] **Step 4: Run.** `uv run pytest -q && uv run ruff check .` Expected: all pass, ruff clean.
- [ ] **Step 5: Commit.** `feat: nets page — add, edit, duplicate, archive, import, export (spec 4.6)`

### Task 6: Net history page

**Files:**
- Modify: `src/beam_navigator/ui/nets.py` (`net_page`), `src/beam_navigator/ui/app.py` (route `/nets/{net_id}`)
- Test: `tests/ui/test_nets_page.py`

**Interfaces:**
- Consumes: `NetBook.view`, `net_form_dialog`.
- Produces: `net_page(book: NetBook, net_id: int, band_names, rotators) -> None`

**The page shows:**
- the net's name, with an `Archived` badge when archived
- the next occurrence
- the default controller text
- the frequency or channel, and the preferred rotator's name
- **Edit** (the same dialog) and date + **Start session**
- the past sessions table: date, status, check-ins, **Open** (`/net/{session}`) and **Net control** (`/control/{session}`)
- the participants table: callsign, last grid (`—` when unknown, never guessed), sessions attended, last seen

An unknown id shows `No net with id N.`, the same way the `/net/{id}` route does.

- [ ] **Step 1: Write the failing tests.**
  - `test_net_page_shows_history`: import the W2KV fixture into a test net with default controller W2KV/FN20ok, then open `/nets/{id}`. It shows `W2KV · FN20ok`, `2026-10-26`, `17` and `K3WGR`, and the participant row for K3WGR shows `FN10xi`.
  - `test_archived_net_page_opens`: archive the net. The page shows `Archived` and its session.
  - `test_unknown_net_page`: `/nets/999` shows `No net with id 999.`
  - `test_no_rotator_command_from_nets_pages`: use a recording simulator, open both pages, edit, duplicate, archive and export. The simulator has received zero commands.
- [ ] **Step 2: Run.** `uv run pytest tests/ui/test_nets_page.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `net_page` and the route.
- [ ] **Step 4: Run.** `uv run pytest -q && uv run ruff check . && uv run mypy src/beam_navigator/core`. Expected: all clean.
- [ ] **Step 5: Docs and commit.**
  - In decisions 22 and 23, change "remapping comes in Milestone 3" and "with plan 3b" to "with plan 3c".
  - Commit: `feat: net history page — sessions and participants (spec 4.6)`

### Task 7: Example nets (opt-in, unverified)

**Files:**
- Create: `src/beam_navigator/store/migrations/0006_net_unverified.sql`, `src/beam_navigator/data/example_nets.beamnet.json`, `tests/unit/test_example_nets.py`
- Modify:
  - `core/models.py`: `Net.unverified: bool = False`, after `rotator_id`
  - `store/repositories.py`: save and get the new field
  - `nets.py`: `NetForm.unverified`; `NetBook.example_offer() -> bool`, `add_examples() -> ImportReport`, `decline_examples() -> None`
  - `beamnet.py`: the optional `unverified` key
  - `ui/nets.py`: the banner, the badge and the form checkbox
- Test: also `tests/ui/test_nets_page.py`

**Interfaces:**
- Consumes: Task 4 `import_beamnet`, `read_beamnet`; `SettingRepository` (`desk.settings`).
- Produces: `EXAMPLE_NETS: Path` (the packaged file, located with `importlib.resources` as `regions.csv` is); `EXAMPLE_SETTING = "example_nets"`.

- [ ] **Step 1: Write the failing tests.**
  - `test_examples_match_source`: read `example_nets.beamnet.json` and `docs/example-nets-source.txt`. For every net, its frequency (written as in the source, e.g. `50.150`) appears in the source text. Its controller call and grid, when set, appear in the source text on the same line. Its timezone is set only for the K1WHS net. There are 13 nets, and every one is `unverified`.
  - `test_examples_match_plan_table`: spot-check the table. Pack Rats Monday 144 MHz is Monday (0), `20:00`, 144.245, `2 m`, W2KV, FN20ok. DVFRC Friday 2304 MHz has band `None` and no controller.
  - `test_add_examples_once`: on a fresh db, `example_offer()` is True. `add_examples()` adds 13, and after it `example_offer()` is False. A second `add_examples()` skips all 13 (names exist).
  - `test_decline_examples`: `decline_examples()` makes `example_offer()` False, and no nets are added.
  - `test_checked_clears_unverified`: saving an example net's form with `unverified=False` stores False. Saving it unchanged keeps True.
  - `test_export_keeps_unverified_flag`: a written beamnet contains `"unverified": true` only for flagged nets.
  - UI, `test_example_banner`:
    - `/nets` on a fresh db shows `Add example nets?`; **Add examples** gives 13 cards and an `Example — unverified` badge.
    - Reopening the page shows no banner.
    - **No thanks** on a fresh desk hides the banner, and it stays hidden.
- [ ] **Step 2: Run.** `uv run pytest tests/unit/test_example_nets.py tests/ui/test_nets_page.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Migration: `ALTER TABLE net ADD COLUMN unverified INTEGER NOT NULL DEFAULT 0;`
  - Write the JSON from the Design table exactly.
  - The form checkbox `I've checked these details` (marker `form-checked`) shows only for an unverified net.
  - The banner shows when `example_offer()` is True: no `example_nets` setting yet.
- [ ] **Step 4: Run.** `uv run pytest -q && uv run ruff check . && uv run mypy src/beam_navigator/core`. Expected: all clean.
- [ ] **Step 5: Decision 27 and commit.**
  - Add: `27. **Example nets come from the owner's schedule (docs/example-nets-source.txt, 2026-10-28)** and hold only what it states: no guessed zones, controllers, modes or durations. They are offered once on the nets page, opt-in, and flagged unverified until the operator ticks "I've checked these details".`
  - Commit: `feat: opt-in example nets from the Pack Rats schedule, labelled unverified (spec 4.6)`
