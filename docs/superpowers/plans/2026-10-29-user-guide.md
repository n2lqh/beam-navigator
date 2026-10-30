# User Guide (Plan 4c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user guide, `docs/user-guide.md`, that takes an operator from installing Beam Navigator to working a net and turning the rotator. It opens with a section by the author, Terry, N2LQH, on why Terry wrote it. A short `README.md` points to it. This is the last plan of Milestone 4.

**Architecture:**
- The guide is one Markdown file in `docs/`.
- Its facts come from the spec, the decisions and the code, never from memory. A small test, `tests/unit/test_user_guide.py`, keeps the facts that can drift (key defaults, Settings tab names, commands, the data folder) in step with the code.

**Tech Stack:** Markdown, pytest. No new dependencies. No screenshots in this plan (they can be added later; nothing in the guide depends on them).

**Spec:** `docs/requirements.md` section 6 Milestone 4 ("user guide"), section 1 ("What this is"), 4.1–4.9, invariants (section 2), and the "Definition of done for v2". Also `docs/decisions.md` 1–36 and `docs/rotator-notes.md`.

## Global Constraints

- **The author's own words.** The "Why I wrote Beam Navigator" section states only what Terry says. Nothing in the project records Terry's reasons, so Task 1 gets them from Terry: either text Terry writes, or Terry's answers, drafted into a section Terry approves before it is committed. No motive, history or anecdote is invented.
- **Invariant 10 and decision 27.** N2LQH, FM29pt and the Pack Rats nets appear as the author's own station and example data, labelled as examples. The guide never tells a reader to use them as their settings.
- **Hard rule 4: never invent.** Every behaviour the guide describes must exist in the code or a decision on `master`. Things that don't exist are not described as if they did:
  - no download link, because the project has no published location
  - no installer, signing or auto-update
  - no LAN access, which is off and not built
  - no pywebview window, which is not built
- **Rotator safety reads truthfully.**
  - New rotators start in simulation.
  - Live needs a passed Test connection.
  - Nothing moves without Rotate.
  - "Position unverified" means no feedback.
  - Restore puts rotators back in simulation.
- **Plain language.** Short sentences, operator's terms (beam, rotator, net control, check-in), no developer jargon. UI labels are written exactly as the app shows them.
- **QRZ.** The guide says a QRZ XML Data subscription is needed and the login stays in the computer's credential store. It never shows a real password or login.

## Design

**`docs/user-guide.md` sections, in order:**
1. **Why I wrote Beam Navigator** — by Terry, N2LQH. Its content comes from Task 1.
2. **Features and benefits** (owner request, 2026-10-29). Two tables, one for net attendees and one for net controllers. Each row has a feature and what it does for you. Every feature is one that exists in the code (checked 2026-10-29), and the benefits follow Terry's reasons in section 1.
   - **For attendees:**
     - Bearing and distance from your own station to any call, grid, state or heading: you know where to point without working it out.
     - Live net screen, "You → controller" and "Controller → you (sector)", calculated directly rather than by adding 180°: you know where the controller must point to hear you, even when the controller doesn't say.
     - Announced sector keys and the "YOUR SECTOR IS UP" banner: you can tell when the call is for your direction, even if you aren't a regular.
     - Follow Controller / Follow Station and Snap back to controller: one press turns the beam back to net control.
     - Substitute controller tonight: still works when someone else runs the net.
     - Roster import of the published roll call: the stations and grids are saved, so the next net starts with them known.
     - Nets, history and participants: you see who usually checks in and from where.
     - Optional QRZ lookups: names and grids for calls you don't know.
   - **For net controllers:**
     - The keyboard-first entry line (like contest loggers) with fill from history and QRZ: logging is faster.
     - Partial-call matching ranked by attendance, and the duplicate check: regulars are one or two keys away, with no double logging.
     - Info panel with bearing and distance from net control, attendance and notes: you know where to point for each station.
     - Export of the roll call (text, CSV, JSON) with bearings labelled from net control: a ready-to-publish list that helps everyone next time.
     - Example nets and `*.beamnet.json` sharing: net details are easy to pass around.
   - **For everyone:**
     - Rotate moves the antenna only when you press it; new rotators start in simulation.
     - It works offline.
     - Backup and restore.
3. **What it does and doesn't do.** From spec section 1: bearings from your own station; Rotate turns the antenna only when pressed; net control logging; works offline. What it does not do comes from the "Not in v2" list.
4. **Installing**
   - **Windows:** run `BeamNavigator.exe` (a single file, no Python needed).
     - Windows may show "Windows protected your PC" because the file is not signed: choose More info → Run anyway.
     - The console window is how you stop it.
     - A second copy reports "Port 8080 is already in use…".
     - Building it yourself: `uv run python packaging/build_windows.py`.
   - **macOS, Linux, Raspberry Pi:** install uv, then `uv tool install <path to the beam_navigator folder>`, then run `beamnav-ui`.
   - **Where your data lives:** the `platformdirs` folder for each OS. Windows `%LOCALAPPDATA%\beam-navigator` was checked on the owner's PC. The macOS and Linux paths are written as `platformdirs` gives them for app name `beam-navigator` (`~/Library/Application Support/beam-navigator`, `~/.local/share/beam-navigator`).
   - `--port` and `--data-dir` are explained.
5. **First run: the Welcome wizard** (decision 35): it shows until a station is active, what it remembers, Skip for now, the example nets, and next steps.
6. **The dashboard** (4.1, 4.2):
   - **What you can type:** the shortcode table (heading, compass point, grid, state/province, alias, callsign), the `NE` collision rule and the `st:`/`dir:`/`grid:`/`call:` prefixes.
   - **What you see:**
     - bearing and distance in your units
     - Grid needed
     - the QRZ card (decisions 30 and 31): automatic lookup, Save this station, Look up on QRZ opening QRZ.com, and approximate bearings
     - long path per band
   - **Rotate.**
7. **Importing a roster** (4.3): paste, review, published bearings are display-only (invariant 3), and the raw text is kept (invariant 9).
8. **Nets and history** (4.6, decisions 26, 27, 32): the nets list, search, favourites, example nets (unverified until checked), past sessions, participants, and `*.beamnet.json` export and import.
9. **Following a net (live net screen)** (4.4): You → controller and Controller → you, the announced sector and YOUR SECTOR IS UP, Follow Controller / Follow Station, Snap back to controller, Substitute controller tonight, heard states, and the sector keys.
10. **Running a net (net control)** (4.5, decisions 23, 31):
   - the entry line, Callsign → Name → Grid → QTH → Report → Notes
   - Enter in Callsign fills, and the next Enter logs
   - Space in Callsign and Grid
   - partial-call list, duplicates, the info panel, notes
   - export as text, CSV or JSON, with or without Report and Notes, and the include-heard option, explained in plain words
11. **Rotators** (4.7, decisions 15 and 19, `docs/rotator-notes.md`):
    - adapters (simulation, PstRotator/PstRotatorAz over UDP, Hamlib rotctld over TCP)
    - travel and presets (north stop, south stop, Yaesu 450°), offset, speed, bands
    - Test connection, Live, Test move in simulation
    - "Command sent — position unverified"
    - the Windows Firewall prompt for Python or the exe, as recorded in rotator-notes
12. **QRZ lookups** (4.9, decisions 28–31): the subscription, Save, Test login, Clear, the automatic-lookup switch, and what a lookup never overwrites.
13. **Keyboard shortcuts** (decisions 22, 23, 33): a table of every action and its default key, plus how to change one in Settings → Keys, the rotator-key rule, and the fixed Space.
14. **Backup and restore** (decision 34): Back up; Restore with its checks; the safety copy in `backups`; rotators back in simulation.
15. **Troubleshooting:** port in use; position unverified; Windows Firewall; "Set up your station first"; a restore that is refused; QRZ errors (exact messages from `qrz_client`).

**`README.md`** (the repository layout in spec section 9 lists it):
- what it is, in one paragraph from spec section 1
- the developer commands from CLAUDE.md
- a link to `docs/user-guide.md`

**Facts test (`tests/unit/test_user_guide.py`):**
- `test_shortcut_table_matches_the_keymap`: for every action in `core.keymap.ACTIONS`, the guide has a table row containing `action.label` and `keymap.label(action.default)`.
- `test_settings_tabs_named`: each Settings tab label (Station, Bands, Aliases, Rotators, QRZ, Keys, Data) appears in the guide.
- `test_commands_exist`: every `beamnav…` command named in the guide is a key of `[project.scripts]` in `pyproject.toml`, and `packaging/build_windows.py` exists.
- `test_windows_data_folder`: the guide contains the path `platformdirs.user_data_dir("beam-navigator", False)` gives on Windows, written with `%LOCALAPPDATA%`. Run only on Windows.
- `test_why_section_first`: the first `##` heading is "Why I wrote Beam Navigator", and the section names "Terry" and "N2LQH".
- `test_features_and_benefits_second`: the second `##` heading is "Features and benefits", with "For attendees" and "For net controllers" under it.
- `test_live_net_labels`: the guide contains "You → controller", "Controller → you", "YOUR SECTOR IS UP", "Snap back to controller" and "Substitute controller tonight", each of which is also found in `src/beam_navigator`.

## Review Focus

- Any sentence describing behaviour the code does not have (the most likely failure for a guide).
- Rotator safety wording that overstates or understates what the app does.
- UI labels that don't match the app exactly (button and tab names).
- The "why" section containing anything Terry didn't say.
- Steps a first-time Windows user would get stuck on: SmartScreen, the firewall prompt, the console window, the port in use.

---

### Task 1: The author's section

**Files:** `docs/user-guide.md` (create it, with the title and section 1 only)

Terry's words (2026-10-29), the source for this section:

> As a new weak signal operator I stuggle to follow the nets where many times the net controller knows the "regulars" and might be a little lax in telling others where he is pointing the beam. in addition we need to know our bearing from the net controller. After the nets the controllers publish the roll call and that is helpful for the next time. beam navigator should help attendees and net controllers to have a better more productive net.

Draft shown to Terry (spelling fixed, paragraphs, "they" for the net controller):

> As a new weak-signal operator, I struggle to follow the nets. Many times the net controller knows the "regulars" and might be a little lax in telling others where they are pointing the beam. In addition, we need to know our bearing from the net controller.
>
> After the nets, the controllers publish the roll call, and that is helpful for the next time.
>
> Beam Navigator should help attendees and net controllers have a better, more productive net.
>
> — Terry, N2LQH

- [x] **Step 1: Get Terry's words.** Done 2026-10-29 (above). The earlier questions were:
  1. What problem were you trying to solve on the air?
  2. How did you find bearings and turn the beam before Beam Navigator?
  3. Which nets or activities did you have in mind (for example, the Pack Rats nets)?
  4. Who do you hope will use it?
  5. Anything else readers should know: your station, how long you've been licensed, a thank-you?
- [ ] **Step 2: Write section 1** as the approved draft above (or Terry's corrections to it), from Terry's text verbatim, or a draft built only from Terry's answers. Sign it "Terry, N2LQH".
- [ ] **Step 3: Show it to Terry, and commit only after Terry approves it**: `docs: user guide, why I wrote Beam Navigator`.

### Task 2: The facts test

**Files:** `tests/unit/test_user_guide.py`

- [ ] **Step 1: Write the seven tests above.** Run `uv run pytest tests/unit/test_user_guide.py -q`. Expected: only `test_why_section_first` passes; the others fail because the sections don't exist yet.
- [ ] **Step 2: Commit the failing tests together with Task 3**, not alone, so `master` is never red.

### Task 3: Sections 2–15

**Files:** `docs/user-guide.md`

- [ ] **Step 1: Write sections 2–15** to the Design section. Take each fact from the cited spec section, decision, code constant or rotator note, and copy UI labels from the `ui/` files.
- [ ] **Step 2: Run the facts test and the full suite.** Expected: all pass.
- [ ] **Step 3: Check the uv install command** without installing anything globally: `uvx --from . beamnav-ui --help` prints the usage. If it doesn't, the guide is fixed, not the check.
- [ ] **Step 4: Commit**: `docs: user guide (Milestone 4)`.

### Task 4: README and decision

**Files:** `README.md` (create), `docs/decisions.md` (decision 37: the guide's place, its facts test, the author's section in Terry's own words)

- [ ] **Step 1:** Write both and run the full suite.
- [ ] **Step 2: Commit**: `docs: README and user guide decision (decision 37)`.
