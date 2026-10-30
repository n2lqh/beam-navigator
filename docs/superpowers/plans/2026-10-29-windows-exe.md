# Windows Executable (Plan 4d) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command builds `dist/BeamNavigator.exe`, a single-file Windows program that starts Beam Navigator in the browser, with no Python install needed. A second copy started by mistake says so clearly instead of crashing.

**Architecture:**
- `packaging/beamnav_entry.py` is the frozen program's entry point.
- `packaging/build_windows.py` runs PyInstaller with the exact options proven by the trial build (2026-10-29).
- `ui/app.main` checks the port before starting.
- An opt-in smoke test runs the built `.exe` against a throwaway data folder.

**Tech Stack:** PyInstaller 6.22.3 (dev dependency, owner approved 2026-10-29), NiceGUI 3.18, pytest. No new runtime dependencies.

**Spec:** `docs/requirements.md` section 6 Milestone 4 ("Windows single-file executable"), section 8 ("PyInstaller single file for Windows"); invariants 1, 2 and 8.

## Trial build findings (2026-10-29, on the owner's PC; recorded so the plan does not guess)

Command:

```
pyinstaller --onefile --name BeamNavigator --collect-all nicegui --collect-data beam_navigator --collect-data tzdata --hidden-import keyring.backends.Windows beamnav_entry.py
```

Results:
- The build takes about 70 s and gives a 37 MB `.exe`, which starts serving in about 2 s.
- With an empty `--data-dir`, it:
  - created the database at schema 8
  - sent `/` to `/welcome`
  - added the 14 example nets with 6 sessions and 54 stations, so the packaged rosters, manifest and beamnet file are included
  - read the saved QRZ login from Windows Credential Manager, so keyring works frozen
  - showed no browser console errors
- `uv add --dev` failed while `beamnav-ui.exe` was running (a Windows file lock). Builds and installs need the app stopped.

## Global Constraints

- Invariants 1, 2 and 8 are unchanged. The `.exe` is the same app: offline, simulation by default, no movement without Rotate.
- The `.exe` keeps its console window. It shows the "ready" line and is how the operator stops the app (close it, or Ctrl+C). `--windowed` is for pywebview only (NiceGUI docs), and pywebview is not in use.
- Data stays in the `platformdirs` user-data folder, as `beamnav-ui` uses. The `.exe` never writes beside itself.
- No icon: there is no approved artwork, and none is invented.
- No runtime dependency is added. PyInstaller stays in the `dev` group.
- Builds go to the git-ignored `build/` and `dist/` folders; `*.spec` is already ignored.

## Design (decisions this plan makes)

**Port already in use.**
- `main()` checks the port before `ui.run` by binding `127.0.0.1:<port>` for a moment.
- If the port is taken, it prints: "Port {port} is already in use. Beam Navigator may already be running: open http://127.0.0.1:{port} in your browser. To run a second copy, start it with --port and another number."
- It then exits with code 1.
- When frozen (`sys.frozen`), it first waits for Enter ("Press Enter to close."), so the message can be read before the console closes. Unfrozen, it exits at once, so tests and the terminal never wait.

**Entry point.**
- `packaging/beamnav_entry.py` calls `multiprocessing.freeze_support()`, then `beam_navigator.ui.app.main()`, under `if __name__ in {"__main__", "__mp_main__"}` as NiceGUI requires.

**Build script.**
- `uv run python packaging/build_windows.py` calls `PyInstaller.__main__.run([...])` with the trial options above, plus `--noconfirm --clean`.
- `--distpath dist`, `--workpath build`, `--specpath build`.
- It prints the path and size of the `.exe`. On a non-Windows OS it exits with "Build the Windows executable on Windows."

**Smoke test.**
- `tests/packaging/test_exe_smoke.py` is skipped unless the environment variable `BEAMNAV_EXE` names a built `.exe`.
- It starts the `.exe` with a `tmp_path` data folder on a free port and waits up to 30 s for `/welcome` to answer 200.
- It checks that `beamnav.db` exists with `PRAGMA user_version == SCHEMA_VERSION`, then stops the process.
- It never sets a QRZ login and never opens Nets, so no lookup can start.

## Review Focus

- A second double-click while the first copy runs: a readable message, not a traceback flashing past.
- The port check must not hold the port, or `ui.run` would fail on a free port.
- The frozen app must find every packaged data file. The smoke test checks migrations; the trial checked the rosters.
- The `.exe` must not change the data folder: the same database as `beamnav-ui`.
- The build must fail loudly if PyInstaller fails, never leaving an old `.exe` reported as new.

---

### Task 1: The port check in `main()`

**Files:**
- Modify: `src/beam_navigator/ui/app.py`
- Test: `tests/unit/test_app_port.py`

**Interfaces:**
- Produces:
  - `port_free(host: str, port: int) -> bool`
  - `PORT_IN_USE: str`, a format string with `{port}`
  - `main()` exits with `SystemExit(1)` after printing that message when the port is taken

- [ ] **Step 1: Write the failing tests:**
  - `test_port_free_on_an_unused_port`: bind a socket to port 0, read the port, close it; `port_free("127.0.0.1", port)` is True.
  - `test_port_taken`: hold a listening socket on a port; `port_free` is False.
  - `test_main_reports_a_taken_port`: hold a port, then call `main(["--data-dir", str(tmp_path), "--port", str(port)])`.
    - It raises `SystemExit` with code 1.
    - `capsys` output contains "is already in use" and `f"http://127.0.0.1:{port}"`.
    - No `beamnav.db` was created, because the check comes before opening the database.
- [ ] **Step 2: Run them to see them fail.** Run: `uv run pytest tests/unit/test_app_port.py -q`. Expected: ImportError.
- [ ] **Step 3: Implement it.** Check the port first in `main()`, before `mkdir` and `open_db`. Wait for Enter only when `getattr(sys, "frozen", False)`.
- [ ] **Step 4: Run them to see them pass,** then the full suite and ruff.
- [ ] **Step 5: Commit**: `feat: a second copy says the port is in use instead of crashing (Milestone 4)`.

### Task 2: Entry point, build script, smoke test

**Files:**
- Create: `packaging/beamnav_entry.py`, `packaging/build_windows.py`, `tests/packaging/__init__.py` (if the other test folders have one), `tests/packaging/test_exe_smoke.py`
- Modify: `pyproject.toml` (PyInstaller is already in the dev group from setup; commit it with this task), `uv.lock`, `CLAUDE.md` (Commands: `uv run python packaging/build_windows.py  # Windows .exe in dist/ (stop the app first)`)

- [ ] **Step 1: Write the smoke test** to the Design section. Run `uv run pytest tests/packaging -q`. Expected: 1 skipped, because `BEAMNAV_EXE` is not set.
- [ ] **Step 2: Write the entry and the build script.** Run `uv run python packaging/build_windows.py`. Expected: "Build complete", and the path and size of `dist\BeamNavigator.exe` printed.
- [ ] **Step 3: Run the smoke test against the build.** Set `BEAMNAV_EXE=dist/BeamNavigator.exe` and run `uv run pytest tests/packaging -q`. Expected: 1 passed.
- [ ] **Step 4: Check the port message by hand.**
  - Start the `.exe` on a throwaway data folder and port 8094, then start a second copy on the same port.
  - Expected: the second copy prints the in-use message and waits for Enter.
  - Stop both.
- [ ] **Step 5: Run the full suite and ruff, then commit**: `feat: build a single-file Windows executable (Milestone 4, spec 8)`.

### Task 3: Decision note

**Files:** `docs/decisions.md` (decision 36: the trial findings, the build command, console kept, no icon, the port check, the smoke test's opt-in variable), and `docs/requirements.md` section 8 Packaging row (add "(packaging/build_windows.py; decision 36)").

- [ ] **Step 1:** Write both and run the full suite.
- [ ] **Step 2: Commit**: `docs: Windows executable (decision 36)`.

`uv tool install` for macOS, Linux and Raspberry Pi needs no code. Plan 4c (the user guide) documents it.
