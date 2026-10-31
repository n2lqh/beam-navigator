# Beam Navigator — Requirements Specification v2.0

**Date:** 2026-10-27
**Status:** Clean rewrite. Supersedes v1.0–v1.3. Everything cut from v1.3 lives in `docs/backlog.md`.
**Example station:** N2LQH, FM29pt. Sample data only; never a default.

---

## 1. What this is

Beam Navigator tells a directional-antenna operator **which way to point**, and points the rotator when asked.

The operator types a callsign, grid square or shortcode, or pastes a net roster, and gets true bearings and distances **from their own station**. Pressing Rotate turns the antenna. Net controllers use the same app to log check-ins quickly.

**Audience:** amateur operators with beams on any band from 10 m (28 MHz) upward: 10 m, 6 m, 2 m, 222, 432, 902, 1296 MHz and microwave. Weak-signal VHF/UHF nets are the core use case. Operators without a rotator get everything except the Rotate button.

**Not in v2:** CAT/radio control, satellite or Moon tracking, elevation control, cloud accounts or sync, map tiles, automatic movement of any kind. See `docs/backlog.md`.

---

## 2. Invariants

These rules apply everywhere. Every other section assumes them. Any code change that violates one is a bug.

1. **Offline-first.** Every v2 feature works with no network connection. Online callsign lookup (4.9) is optional: it only adds data, nothing waits on it, and without a connection everything else works the same.
2. **No movement without an explicit press.** The rotator moves only when the operator presses Rotate (or its hotkey) for a displayed target and heading. Selecting a row, importing a roster, changing a setting, resolving a callsign, a timer, or any announcement never sends a command.
3. **Bearings are from the user's station.** Headings printed in a roster by a net controller are stored as `published_bearing` and displayed as such. They are never used as the user's heading.
4. **True north, degrees 0–359.9.** 0 = N, 90 = E. Rotor offset is a per-rotator setting applied only inside the adapter.
5. **Never invent a location.** Unknown grid means "grid needed." Every location shows its source (typed, roster, saved, alias, region centroid).
6. **Truthful rotator status.** Without position feedback, the UI says "Command sent — position unverified," never "At heading."
7. **Stay inside mechanical limits.** Commands outside the rotator's configured travel are rejected, not wrapped or guessed.
8. **Simulation by default.** A new rotator profile starts in simulation mode. Live mode requires a passed connection test and an explicit switch.
9. **Source data is never lost.** Raw roster text is stored with each imported session.
10. **No hard-coded stations or nets.** Example data is opt-in and labeled unverified.

---

## 3. Domain model

| Entity | Meaning |
|---|---|
| **Operator profile** | The user's own station: callsign (optional), home grid, optional exact lat/lon, units, timezone. Multiple profiles allowed (home, portable). One is active. |
| **Station** | Any other callsign, with last known name, grid, QTH, source, and persistent station notes. One record per normalized callsign. |
| **Net** | A recurring net: name, weekday, local start time, timezone, frequency (MHz, or null plus a free-text channel such as a DMR talkgroup), mode, band, default controller callsign and grid (both optional), preferred rotator. |
| **Session** | One dated occurrence of a net. Holds the effective controller (copied from the net default, overridable for that night only), status (active / closed / imported), raw roster text if imported. |
| **Check-in** | A station's appearance in a session: sequence, time, callsign, and **snapshots** of name, grid, QTH as given that night, plus report, notes, published bearing (imported only), and heard state. |
| **Rotator profile** | One controllable rotator: name, adapter type, host, port, azimuth min/max, stop position, offset, rotation speed (optional), bands it serves, simulation/live flag. |
| **Alias** | A user-defined shortcode pointing at a grid, coordinates, station, or fixed heading. |

Key rules:
- Check-ins snapshot location. Changing a station's saved grid never rewrites past sessions.
- A session's substitute controller never changes the net's default unless the user explicitly chooses **Save as default**.
- A callsign appears at most once per session unless the controller explicitly chooses to add a second entry.

---

## 4. Features

### 4.1 Bearing lookup (dashboard)

One large input box. Type a target, press Enter, and see:
- Resolved target and its source.
- True bearing (one decimal), compass name (16-point), and distance in miles or km.
- For 10 m and 6 m: long-path bearing and distance as well, labeled. Configurable per band.
- A Rotate button showing the exact heading and rotator ("Rotate VHF to 294.6°"), when a live or simulated rotator is configured for the selected band.

If the grid is unknown, show "Grid needed" with an inline grid field. Saving the typed grid to the station record is optional and asked.

### 4.2 Target input and shortcodes

The same resolver backs every target field in the app. Input is case-insensitive.

| Input | Example | Resolves to |
|---|---|---|
| Heading | `247`, `247°` | That bearing. No distance. `360` becomes 0; values outside 0–359.9 are rejected. |
| Compass point | `N`, `NE`, `NNW` | 16-point bearing (N 0, NNE 22.5, … NNW 337.5). No distance. |
| Grid | `FN20`, `FN20ok`, `FM29pt42` | Center of the grid cell. |
| US state / DC / Canadian province | `NJ`, `PA`, `MD`, `ON` | Precomputed centroid, labeled "centroid." If the user is inside the region: "You are in NJ," no bearing, Rotate disabled. |
| Alias | `CLUB`, `BEACON2M` | Whatever the alias points to. |
| Callsign | `W2KV`, `K1ABC/P` | Station record (section 4.5). |

Collisions: `NE` means Northeast by default, with "Nebraska?" offered as a one-click alternative. Prefixes force a type: `st:NE`, `dir:NE`, `grid:FN20`, `call:W2KV`. A unit test fails the build if a new collision appears in the bundled tables without a rule.

Region centroids ship as a small static table (code, name, lat, lon, source), computed once from public-domain boundary data. No polygons in v2.

### 4.3 Roster import

1. Paste text (or Paste from Clipboard). Pick the net and date.
2. The parser extracts one row per callsign: sequence, callsign, name, QTH, grid, published bearing, controller tag, confidence, warnings.
3. A review table shows parsed rows plus **bearing and distance from the user**. The user can edit cells, exclude rows, pick the controller, and fix missing grids.
4. **Save** commits the session with the raw text. Re-importing identical text for the same net and date asks whether to replace or keep both.

Parser requirements:
- Deterministic and offline. No LLM, no network.
- Handles numbered lists, unnumbered multiline entries, single-line entries, mixed case, non-breaking spaces and other Unicode whitespace.
- Does not mistake frequencies (`50.150`, `144.245`), dates or times for grids or callsigns.
- Handles portable calls (`K1ABC/P`, `EA/K1ABC`) without treating suffixes as grids.
- Recognizes `(Net Control)`, `NC` and similar controller tags. Never assumes the last or first row is the controller without flagging it as a suggestion.
- Preserves grid text exactly as given for display; matches case-insensitively.
- Flags, never drops: duplicate callsigns, missing grids, conflicting grids versus saved records, unparseable fragments (kept as "unparsed text" rows).

### 4.4 Live net screen (participant)

- Header: net, frequency, effective controller, rotator status.
- Pinned controller row with two clearly labeled values: **"You → controller: NNN°"** and **"Controller → you: NNN° (sector)."** The second is calculated directly from controller to user, not by adding 180°.
- Check-in table: callsign, name, grid, bearing from user, distance, heard state. Sort by roster order, bearing, distance or callsign. Filter by text.
- **Announced sector:** the user records the controller's announced sector with one key (number-pad layout: 8 N, 9 NE, 6 E, 3 SE, 2 S, 1 SW, 4 W, 7 NW) or by clicking a compass rose. When it matches the user's sector as seen from the controller (default tolerance ±22.5°), a large banner shows **"YOUR SECTOR IS UP."** If the controller location is unknown: "Controller location unknown — can't tell if this call is for you." The banner never claims the controller can hear the user.
- **Target mode:** Follow Controller or Follow Station. The mode decides what Rotate points at. A **Snap back to controller** button and hotkey (`Home`) target the controller and rotate in one explicit press.
- **Heard state** per row: Heard / Weak / Not heard / Via relay (with relaying callsign). Private to the user.
- **Substitute controller tonight:** enter a different callsign, grid, or just a manually measured bearing. Applies to this session only.
- **Works without a roster (owner, 2026-10-30; decision 42).** A participant usually has no roster during the net:
  - **Aim at:** one box takes a callsign, grid, alias or direction, resolved as on the dashboard. Enter shows the bearing and makes it the Rotate target ("Follow Typed") but never rotates; Ctrl+Enter or Rotate then turns the beam. While typing, the box also filters both lists by callsign, name or grid. A typed callsign not yet in tonight's list offers **Add to tonight**, which puts it on the I-hear line.
  - **Regulars not heard yet:** everyone who has checked in to this net before and is not in tonight's list, with name, grid, bearing and distance from the user, attendance and last check-in. Sort by **Last check-in** (default, newest first), **Callsign**, **Grid** or **Direction**; unknown grids and bearings sort last, ties by callsign. Clicking a row makes it the Rotate target. **Heard** adds the station to tonight.
  - **Tonight** sorts by **Check-in order** (default), **Callsign**, **Direction** or **Distance**. The separate Filter box and the general Sort select are gone.
  - **I hear:** Callsign → Name → Grid, the net control entry line itself (same keys, auto-fill, partial-call matching, duplicate check, session-only or update-record choice, QRZ). Each station is logged to this session as Heard, so it is a regular at the next session.
  - **Close my session…** with **Notes for next time**. The session turns read-only (Aim at, Rotate and Snap back still work) until **Reopen**. The next session of the same net shows the notes as **Last time (date)** on the live net and net control screens; a newest closed session with no notes shows no card. Closing notes are private and never exported.

### 4.5 Net controller screen

Keyboard-first entry line, modeled on contest loggers such as N1MM Logger+:

- Fields: **Callsign → Name → Grid → QTH → Report → Notes.**
- `Space`/`Tab` next field, `Shift+Tab` back, `Enter` logs from any field, `Esc` clears. In Callsign, the first `Enter` fills Name, Grid and QTH and moves to Name; the next `Enter` logs (owner, 2026-10-29; decision 31). Focus returns to Callsign after each entry. All keys remappable (Settings → Keys; decision 33).
- **Auto-fill:** when the callsign is complete, Name, Grid and QTH fill from the station record, shown in a distinct "from history" style until confirmed or overwritten.
- **Unknown station:** the cursor stops on Name and Grid, highlighted as needed. Logging with blanks is allowed; blanks are flagged.
- **Changed details:** a differing name or grid asks **This session only** (default) or **Update station record**.
- **Partial-call matching:** typing `K3W` lists matching stations from local history, ranked by attendance at this net. Arrow keys and Enter select.
- **Duplicate check:** an already-logged callsign shows "Already checked in at 20:07 (#5)" and offers **Update existing**.
- **Info panel** beside the line: last name, grid, QTH and source; bearing and distance from net control; attendance ("12 of last 15"); previous session notes and persistent station notes (`Alt+N` adds one; decision 38).
- Session table below the entry line, editable inline.
- **Export:** plain text, CSV and JSON with date, net, frequency, controller and grid. Bearings are labeled "from net control"; when net control's location is unknown they are from the operator's own station, labeled with its callsign and grid, and distances use the operator's units (owner, 2026-10-29). The user's private heard states are never exported (owner, 2026-10-29; decision 40). Report and notes are included unless unticked; names and QTHs are exported in proper case, changing only words typed all in capitals or all in lower case (owner, 2026-10-29).

### 4.6 Nets and history

- Net list with add, edit, duplicate, archive, import/export (`*.beamnet.json`, schema-versioned).
- Net view: next occurrence, default controller, past sessions, and known participants (callsign, last grid, sessions attended, last seen).
- Participants from history are shown as **expected**, never as checked in, until they check in this session.
- Example nets (Pack Rats schedule) are offered at first run, opt-in, labeled unverified. (The Welcome wizard offers them; decision 35.)

### 4.7 Rotator control

**Adapters** share one interface:

```
connect() -> ConnectionResult
capabilities() -> Capabilities        # has_feedback, has_stop, ...
get_position() -> float | None        # None if no feedback
set_azimuth(deg_true: float) -> CommandResult
stop() -> CommandResult               # only if has_stop
disconnect()
```

v2 ships three adapters:

| Adapter | Platform | Protocol (documented) |
|---|---|---|
| `simulation` | all | Records commands; moves a virtual rotor at the configured speed. |
| `pstrotator` | Windows (PstRotator / PstRotatorAz) | UDP to the configured port (default 12000). Set: `<PST><AZIMUTH>85</AZIMUTH></PST>`. Query: `<PST>AZ?</PST>`, reply `AZ:xxx.x` arrives on port + 1. Stop: `<PST><STOP>1</STOP></PST>`. Verify against the installed version in the spike (section 6). |
| `hamlib` | Windows, macOS, Linux, Raspberry Pi | TCP to `rotctld` (default port 4533). Set: `P <az> <el>` (el = 0.0 for azimuth-only). Get: `p`. Stop: `S`. Set commands answer `RPRT 0` on success, negative code on error. |

Behavior:
- Before sending, the UI shows the planned move: heading, direction, and whether it must go the long way around the stop. With rotation speed set, an estimated time.
- Commands outside az min/max are rejected with the reason.
- With feedback, show commanded and measured heading separately, updating during the move. Without feedback, show the time elapsed against the estimate and "position unverified."
- Timeouts and errors are reported, never silently retried. A failed command is not resent automatically.
- Stop button only when the adapter supports it, with text noting it does not replace the controller's physical stop.
- Every command is logged: time, rotator, target, requested heading, result, measured heading if any.
- Multiple rotator profiles are allowed; each band maps to a default rotator, always visible and changeable before Rotate.
- **Elevation is out of scope in v2.** Rotators used for satellite or Moon tracking should not be configured in Beam Navigator.

### 4.8 Settings and data

- Operator profiles, rotator profiles (with Test connection and Test move in simulation), units, band table (data, not code), aliases, hotkeys.
- Backup and restore of the whole database to a single file. (Settings → Data; decision 34.) Export nets, stations and history as JSON/CSV.
- Data lives in the platform user-data directory (`platformdirs`). Logs rotate.

### 4.9 Online callsign lookup (optional)

Added by the owner on 2026-10-28 (decision 28); previously backlog B4.1.

- **Provider:** QRZ XML Data (needs the operator's own QRZ subscription), through its documented API only. Other providers (HamQTH) stay in the backlog.
- **Off until set up.** The operator enters their QRZ username and password in Settings. They are kept in the operating system's credential store (`keyring`): never in the database, settings files, logs, exports or backups.
- **When it runs:** automatically when the operator enters a callsign on the dashboard (Enter) or the controller screen (Space or Tab out of Callsign) and nothing useful is stored for it: no saved grid and no earlier QRZ answer (owner, 2026-10-29; decision 30). Automatic lookup can be switched off in Settings; **Look up on QRZ** opens the station's QRZ.com page in a new browser tab and sends nothing through the XML service (decision 31); without a saved login it does nothing and says nothing. Never during an import's parse, and never on a schedule.
- **Results** (name, grid, QTH) are saved to the station record with source `QRZ` and the lookup date, and always shown as "from QRZ". A QRZ grid is the station's registered address, not necessarily tonight's location: it never replaces a grid given in a roster or by the controller.
- **Failures** (offline, bad login, not found, timeout) are reported plainly and never retried in a loop. The rest of the app carries on.
- **Using an answer:** an exact QRZ position (station or address) gives the dashboard bearing straight away for a call with no saved location, labelled "QRZ"; **Save this station** copies QRZ's name, grid and QTH into the station record's blank fields. On the controller screen a saved QRZ answer fills blank fields without a new lookup. Approximate positions (zip, state, country) are never used without a press (decision 31).
- After the example nets are added, their example stations missing a name or grid are looked up once, in the background (decision 32).
- A lookup never sends a rotator command (invariant 2).

---

## 5. Geometry

- Maidenhead: validate 4, 6, 8 or 10 characters with correct letter/digit pattern; case-insensitive. Convert to the cell **center**. Reject invalid input with a clear message.
- Bearing and distance: spherical great-circle (Earth radius 6371.0 km). Initial bearing normalized to [0, 360). Reverse bearing calculated independently.
- Long path: bearing = short-path + 180 (normalized); distance = 40,030 km − short-path distance.
- Coincident or near-coincident points (default under 0.5 km): show "Home," no bearing.
- Exact coordinates, when present, override grid centers and are labeled.
- Precision note: when the target is only a 4-character grid and the band is 1296 MHz or above, show "coarse location — ±50 km."
- Tests compare against `geographiclib` (dev-only dependency) within 0.5° and 0.5% of distance for paths under 2,000 km.

---

## 6. Build order

Each milestone ends in something usable. Do them in order.

**Milestone 0 — Rotator spike (first, before any UI).**
A command-line script: `beamnav-rotor --adapter pstrotator --host 127.0.0.1 --port 12000 --az 90`. It sends one command, queries position if supported, and prints the reply. Same for `--adapter hamlib`. Run against Terry's real PstRotatorAz setup. Record exact behavior (replies, timing, errors, firewall needs) in `docs/rotator-notes.md`. This retires the biggest technical risk before anything else is built.

**Milestone 1 — Core library (no UI).**
Maidenhead, geometry, target resolver with shortcodes and region centroids, roster parser, SQLite store with migrations, simulation adapter, all three fixtures passing. Command-line entry: `beamnav bearing FN20ok`, `beamnav parse roster.txt`.

**Milestone 2 — Usable at the desk.**
Web UI: bearing lookup, roster import and review, live net screen with announced sector and Follow/Snap back, rotator settings, live Rotate through the adapters from milestone 0.

**Milestone 3 — Net control.**
Controller entry line, info panel, partial-call matching, duplicates, export. Nets list, history, participants, `*.beamnet.json`.

**Milestone 4 — Packaging.**
Windows single-file executable; `uv tool install` on macOS, Linux and Raspberry Pi; user guide; first-run wizard; backup and restore.

---

## 7. Acceptance tests

### Fixtures
Raw text of six real rosters (supplied by the project owner, 2026-10-27, copied from club emails) lives in `tests/fixtures/` exactly as pasted. Never clean them up or regenerate them. Whitespace may differ slightly from the original emails because they passed through a chat window.

| File | Format | Expected |
|---|---|---|
| `n3rg_50mhz_2026-10-26.txt` | N3RG, 50.150 MHz. Email with intro, numbered one-line rows with published bearings, sign-off. | **22** check-ins; controller N3RG (FM29ki, "(net control)"); N2LQH grid FM29pt, published 35°; N3ITT published 0° stored as printed; N1DSB grid `fm29` (4-char) and no bearing; KF2Z no bearing; `W3CCX` inside the URL is **not** a check-in; sign-off "73 de N3RG" is not a second N3RG row; stated count "22 check-ins" matches. |
| `wb2rvx_432mhz_2026-10-26.txt` | WB2RVX, 432.110 MHz. Numbered rows with no space after the number (`1.K3JJZ`), blank lines between, double spaces. No header. | **10** check-ins; controller WB2RVX (FM29MT, "(Net Control)") with published 0° stored as printed. Net and date come from the import dialog, not the text. |
| `w2kv_144mhz_2026-10-26.txt` | W2KV, 144.245 MHz. Four lines per station (call / name / QTH + grid / blank), no bearings, trailing narrative. | **17** check-ins; controller W2KV (`NC`, FN20OK); K3WGR grid FN10xi preserved; K8RYU in the narrative is not a second row; sign-off "Dave W2KV" is not a second row. Stated count "18 check-ins" does **not** match: show a warning, keep 17, never invent a row. |
| `ka3wxv_dmr_2026-10-26.txt` | KA3WXV, DMR Pack Rats talkgroup. Name first, then callsign, aligned with spaces. No grids, no frequency. | **11** check-ins; controller KA3WXV ("Net Control"); all grids missing and flagged; sign-off "George / ka3wxv" (lowercase) is not a second row. Net has a talkgroup, not a frequency. |
| `wa3nuf_222mhz_activity_2026-10-21.txt` | WA3NUF, 222 MHz activity night (not a controlled net), dated 2026-10-21 by the owner. Narrative first, then comma-separated `CALL GRID` pairs, four per line. Date not in the text; the text says "Tuesday" but 2026-10-21 is a Wednesday, so the import date is whatever the user enters, and the app never derives or "corrects" a date from weekday words. | **16** stations, **12** distinct 4-char grid prefixes, matching the stated "16 stations and 12 Grids"; mixes 4- and 6-char grids; includes Canadian call VE2XX; no controller (do not suggest one); author WA3NUF is the logger, not a station; no false callsigns from "NBA," "LeBron," "76'er," "8:30 PM." |
| `kc3bvl_222mhz_2026-10-19.txt` | KC3BVL, Monday 222 MHz net, 2026-10-19. Starts with a byte-order mark (U+FEFF), stated summary first, `CALL GRID` rows separated by several blank lines. Band and date not in the text; supplied at import. | **8** stations, **3** grids (FM29, FN20, FN31), matching "8 stations from 3 grids"; controller KC3BVL (FM29JW, `NC`); BOM ignored without error. |

Cross-fixture checks (useful for history and change-detection tests):
- K3WGR is FN10xh on 50 MHz and FN10xi on 144 MHz the same night: flag the conflict, keep both snapshots, change no saved record silently.
- Same station, different details: AF3G "GLEN" vs "GLENN"; KA3FQS Horsham vs Ambler; N2DEQ Turnersville vs Blackwood (432 MHz). Each check-in keeps its own snapshot.
- N2LQH appears on 50 and 144 MHz: one station record, two attendances.

Parser rules these fixtures add:
- Exclude callsigns inside URLs, email addresses and sign-off blocks ("73 de …", a name plus call at the end).
- Narrative mentions of callsigns are not check-ins unless they appear in the roster block.
- When the text states a count ("22 check-ins", "16 stations", "12 Grids"), compare it with the parsed result and warn on mismatch. Never add or drop rows to make the numbers agree.
- Accept name-before-callsign layouts and comma-separated `CALL GRID` lists.
- Ignore a leading byte-order mark.
- Distinguish a controlled net from an activity-night log: no controller tag means no controller, not a guess.

> Several fixtures carry no band, net or date in their text (WB2RVX, WA3NUF, KC3BVL). The import dialog must ask for them; tests supply them explicitly from the file names.

### Geometry
1. FM29pt → FN20ok: bearing within 0.5° of geographiclib (about 354°); reverse independently about 174°.
2. FM29pt → FM29pt: "Home," no bearing, Rotate disabled.
3. Grid centers for 4/6/8/10 characters match reference values; `FN2`, `FN20o`, `ZZ99` rejected.
4. Long path on 10 m: short + 180 normalized; distance sums to 40,030 km.

### Shortcodes (user at FM29pt)
5. `N` 0°, `NE` 45°, `SW` 225°, `NNW` 337.5°; no distance.
6. `247°` → 247; `360` → 0; `400` rejected.
7. `PA` → about 295° (±3°), labeled centroid. `MD` → about 243° (±3°).
8. `NJ` → "You are in NJ," Rotate disabled.
9. `NE` → Northeast with Nebraska offered; `st:NE` → Nebraska.
10. Alias `CLUB` → FM29jw gives the same result as typing `FM29jw`.

### Roster and history
11. Each fixture parses to its expected rows, controller and published bearings.
12. Published bearings never appear in the "from you" column.
13. Re-importing the same text for the same net and date prompts replace or keep.
14. Importing the W2KV roster for 2026-10-26 and starting a new session for 2026-11-02 shows its 17 stations as regulars not heard yet, none checked in.
15. A substitute controller in one session leaves the net default and earlier sessions unchanged.

### Live net
16. W2KV at FN20ok, user at FM29pt: controller → user ≈ 174° (S). Pressing number-pad `2` (S) shows "YOUR SECTOR IS UP" within one second.
17. Unknown controller location: any sector shows the "can't tell" message and no banner.
18. Changing sector, mode, or selected row sends zero rotator commands. Snap back sends exactly one.

### Net control
19. Known callsign + `Space` auto-fills name, grid, QTH in history style and shows previous notes.
20. Unknown callsign stops on Name and Grid; `Enter` logs with blanks flagged.
21. A different grid asks session-only or update; session-only leaves the station record unchanged.
22. Duplicate callsign shows the warning and offers Update existing.
23. A full check-in can be logged without the mouse.
24. `K3W` lists K3WGR first when K3WGR has the highest attendance at this net.

### Rotator
25. A new rotator profile is in simulation mode; live mode is unavailable until Test connection passes.
26. Simulation receives exactly one command per Rotate press, zero from any other action.
27. A request outside az min/max is rejected with the reason; nothing is sent.
28. Without feedback, status reads "position unverified."
29. A timeout is reported and not retried.
30. Hamlib adapter against a `rotctld` dummy rotator (`rotctld -m 1`) sets and reads position in CI.

### General
31. Every test above passes with networking disabled.
32. A malformed paste (binary garbage, 1 MB of text) is handled without a crash.
33. A 100-station roster parses and calculates in under 2 seconds.

### Participant (owner, 2026-10-30)
37. Typing a callsign, grid, alias or heading in Aim at and pressing Enter shows its bearing from the user and sends no rotator command.
38. After that, Ctrl+Enter rotates to the typed target with exactly one command.
39. Clicking a Regulars row or pressing its Heard button sends no rotator command.
40. Regulars sort by callsign, grid, direction and last check-in; stations with an unknown grid or bearing sort last.
41. Typing in Aim at narrows both lists and sends no rotator command. Tonight sorts by check-in order, callsign, direction and distance.
42. A station added with the I-hear line on one session appears under Regulars on the next session of the same net, with its grid and bearing.
43. Adding a station whose name or grid differs from its record leaves the record unchanged unless "Update station record" is chosen.
44. Closing a session with notes stores them; the next session of that net shows them under "Last time"; a different net does not.
45. A closed session refuses adds until reopened; Rotate still works.
46. Closing notes never appear in text, CSV or JSON exports.
47. Tests 37–46 pass with networking disabled.

### Online lookup
34. With no network, Look up on QRZ reports that QRZ cannot be reached, and nothing else changes.
35. The QRZ password never appears in the database, settings, logs, exports or backups.
36. A QRZ grid is shown as "from QRZ" and never overwrites a grid from a roster or the controller.

---

## 8. Tech stack

| Part | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | One language for everything. |
| Core | Pure Python package, no UI imports | Testable, reusable from CLI, UI and any future server. |
| UI | NiceGUI, served on `localhost` | Python-only web UI, no JavaScript build. Runs on Windows, macOS, Linux and Raspberry Pi. |
| LAN access | Optional, off by default | Shack PC or Pi runs the app; a tablet next to the radio opens it in a browser. When enabled, require a simple access PIN. |
| Desktop window | Optional `pywebview` wrapper | Native-looking window for users who don't want a browser tab. |
| Database | SQLite via standard `sqlite3` | No ORM. Numbered `.sql` migration files applied at startup. |
| Paths | `platformdirs` | Correct data folder on every OS. |
| Tests | `pytest`, `geographiclib` (dev only), `rotctld` dummy rotator in CI | |
| Quality | `ruff`, `mypy` on the core package | |
| Packaging | `uv` / `pyproject.toml`; PyInstaller single file for Windows (`packaging/build_windows.py`; decision 36) | |
| CI | GitHub Actions on Windows, macOS and Ubuntu | |

Runtime dependencies are limited to NiceGUI, platformdirs, tzdata, keyring (QRZ login, 4.9), and optionally pywebview. Anything else needs a reason in the pull request.

---

## 9. Repository layout

```
beam-navigator/
  CLAUDE.md
  pyproject.toml
  README.md
  docs/
    requirements.md        # this file
    backlog.md             # everything deferred
    rotator-notes.md       # milestone 0 findings
  src/beam_navigator/
    core/
      maidenhead.py
      geometry.py
      targets.py           # input resolver and shortcodes
      regions.py           # loads data/regions.csv
      roster_parser.py
      models.py
    store/
      db.py
      migrations/0001_initial.sql
      repositories.py
    rotators/
      base.py
      simulation.py
      pstrotator.py
      hamlib.py
    ui/                    # NiceGUI pages only; no business logic
      app.py
      lookup.py
      roster.py
      live_net.py
      controller.py
      nets.py
      settings.py
    cli.py                 # beamnav, beamnav-rotor
    data/regions.csv
  tests/
    fixtures/
    unit/
    integration/
```

---

## 10. Open decisions

None of these block milestones 0–2.

- Product name and license (open source or not).
- Whether region data should add ARRL sections in a later release.
- Cloud sharing design (see backlog, section B5).

**Definition of done for v2:** an operator on Windows, macOS, Linux or a Raspberry Pi can install the app, enter their grid, paste a real net list, see correct headings from their own station, log a net as controller, and — if they have a rotator — turn it deliberately with one press and nothing else.
