# CLAUDE.md — Beam Navigator

Beam Navigator tells an amateur radio operator which way to point a directional antenna, and turns the rotator when asked. Full spec: `docs/requirements.md` (v2.0). Deferred ideas: `docs/backlog.md` — do not build backlog items unless asked.

## Hard rules (from requirements section 2)

1. **Never move the rotator without an explicit Rotate press** (or its hotkey). No movement from selection, import, settings, lookups, timers, or announcements. If a change could send a rotator command from anything else, stop and ask.
2. **Offline-first.** No feature may need the network. QRZ lookup (requirements 4.9) is optional and only adds data; credentials live in `keyring`, never in files or the database.
3. **Bearings are from the user's station.** Roster `published_bearing` values are display-only.
4. **Never invent locations, protocol commands, or test data.** If a grid is unknown, it stays unknown. Rotator commands must match `docs/rotator-notes.md` and the documented PstRotator / Hamlib protocols. Fixture files in `tests/fixtures/` must contain the original pasted text; never generate or "fix" them.
5. **Truthful rotator status.** No feedback means "position unverified."
6. **Simulation by default** for every new rotator profile.
7. **No hard-coded stations or nets.** N2LQH / FM29pt and the Pack Rats nets are sample data only.

## Architecture

- `core/` is pure Python: no UI, no network, no database imports. Everything testable here lives here.
- `store/` uses the standard `sqlite3` module and numbered `.sql` migrations. No ORM.
- `rotators/` holds adapters behind the interface in requirements 4.7. New adapters need a test against a simulator or dummy.
- `ui/` (NiceGUI) only renders and calls into `core`/`store`/`rotators`. No business logic in UI files.
- Keep runtime dependencies to NiceGUI, platformdirs, tzdata (approved 2026-10-28, for net time zones on Windows), keyring (approved 2026-10-28, for the QRZ login), and optional pywebview. Ask before adding others.

## How to work

- Follow the milestone order in requirements section 6. Milestone 0 (rotator spike) comes before any UI.
- Small, testable steps. Write or update tests with every change; run `pytest` and `ruff check` before saying something is done.
- The acceptance tests in requirements section 7 are the definition of done. Reference them by number in commit messages when relevant.
- When the spec is ambiguous, choose the conservative, offline, hardware-safe option, note it in `docs/decisions.md`, and continue.
- Must run on Windows, macOS, Linux and Raspberry Pi. Use `platformdirs` and `pathlib`; no OS-specific paths. CI runs on all three desktop OSes.

## Commands

```
uv sync                         # install
uv run pytest                   # tests
uv run ruff check . && uv run mypy src/beam_navigator/core
uv run beamnav bearing FN20ok   # CLI bearing
uv run beamnav-rotor --adapter simulation --az 90
uv run beamnav-ui               # start the web UI
uv run python packaging/build_windows.py   # Windows .exe in dist/ (stop the app first)
```

## Station context (for manual testing only)

The project owner's station: N2LQH, FM29pt (Tabernacle, NJ), rotators via PstRotatorAz on Windows. Use it for local testing; never as a default in code.
