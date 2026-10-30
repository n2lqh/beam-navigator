# Rotator notes — Milestone 0 findings

Real behavior observed on real setups. Adapter code must match this file (CLAUDE.md rule 4). Record what actually happened, including surprises and failures.

---

## PstRotatorAz — N2LQH shack PC (Windows 11)

### Setup observed 2026-10-27 (before any command was sent)

- `PstRotatorAz.exe` installed at `C:\Program Files (x86)\PstRotatorAz\`. Version: _not yet recorded_.
- PstRotatorAz listens on **UDP 0.0.0.0:12000** — matches the requirements default.
- **HRD Logbook listens on UDP `[::]:12001`**, the port PstRotatorAz sends `AZ?` replies to. HRD Logbook's socket is IPv6. It did **not** block the old `127.0.0.1:12001` listener (row 2). Whether it blocks the current `0.0.0.0:12001` listener is **not yet tested**. Milestone 2 must handle this (configurable reply port or a clear "port in use" message — the adapter already reports the latter).

### Owner's answers, 2026-10-29

- **Rotator: Yaesu 450° (overlap).** Use the "Yaesu 450°" travel preset (0–450°) for this rotator's profile.
- **Calibration: accurate.** Asked "When you tell PstRotatorAz to point at 90°, does the beam actually point east?", the owner answered yes. PstRotatorAz's heading matches the beam, so Beam Navigator's Offset stays **0**; no correction is applied twice.
- **Overlap path: not tested, and not needed.** For headings 0–90° the app already does not predict PstRotatorAz's path; it shows that PstRotatorAz chooses its own (decision 15). Test row 5 below stays optional.
- **Version:** still not recorded; optional (Help → About in PstRotatorAz).

### Live test — Session B, 2026-10-27

**Key finding: PstRotatorAz replies on the LAN address, not loopback.** With `beamnav-rotor` and PstRotatorAz on the same PC (host `127.0.0.1`), the reply to `<PST>AZ?</PST>` arrived from `192.168.2.195:12000` addressed to this PC's LAN address, port 12001. Seen with a read-only probe listening on the sender socket, `0.0.0.0:12001` and `[::]:12001`; only `0.0.0.0:12001` got it. The adapter now always listens on `0.0.0.0` (decisions.md, 9).

Reply format: `AZ:85\r` — whole degrees when the heading is whole, carriage return, no line feed, no padding.

Windows Firewall prompted to allow `python` once the listener used `0.0.0.0`. It created two inbound Allow rules (TCP and UDP) for the base interpreter `pythoncore-3.14-64\python.exe`, both on Private and Public networks. The `.venv` launcher and `uv run` both run that interpreter, so `uv run` did not prompt again. Only Private should be needed for a rotator on the home LAN.

Commands were run directly as `.venv\Scripts\beamnav-rotor.exe …` because `uv` was not on PATH on the shack PC.

Run each command yourself, with the beam watched, starting near the current heading.

| # | Command | Sent | Reply / position | Timing | Rotator did |
|---|---|---|---|---|---|
| 1 | `uv run beamnav-rotor --adapter pstrotator --az <near current>` — run as `--az 85`, HRD Logbook closed, old `127.0.0.1` listener | `<PST><AZIMUTH>85</AZIMUTH></PST>`, then `<PST>AZ?</PST>` | None on `127.0.0.1:12001` ("position unverified") | Timed out at 2 s | Already at 85° |
| 1a | Same as 1, after the `0.0.0.0` listener fix | same | `AZ:85` → 85.0° | Reply in 1 ms | Already at 85° |
| 2 | Same, with HRD Logbook still running (expect "port in use") — run first, `--az 85` | `<PST><AZIMUTH>85</AZIMUTH></PST>`, then `<PST>AZ?</PST>` | No "port in use": the `127.0.0.1:12001` listener bound alongside HRD's `[::]:12001`. No reply received. | Timed out at 2 s | Moved to 85° (owner watched) |
| 3 | Decimal heading, e.g. `--az 90.5`, after changing the adapter to send decimals | | | | |
| 4 | Heading that crosses the rotor's stop | | | | |
| 5 | Overlap (450° rotors only): rotor at 350°, command 10°. Does PstRotatorAz go clockwise to 370° or back to 10°? What does `AZ?` report at 370°: 370 or 10? | | | | |

Still to record:
- PstRotatorAz version (Help → About).
- Reply format for a non-whole heading (`AZ:85` seen for a whole one).
- Does it accept decimal headings? Does it answer anything to a set command?
- Does HRD Logbook's `[::]:12001` block the `0.0.0.0:12001` listener?
- Does the stop command `<PST><STOP>1</STOP></PST>` work?
- Rotator speed (seconds per 360°), if measurable — feeds the move-time estimate.

---

## Hamlib rotctld

Not installed on the shack PC. Adapter tested against a fake rotctld in `tests/unit/test_hamlib.py`; acceptance test 30 (`rotctld -m 1`) runs in `tests/integration/` when Hamlib is installed (CI).
