# Participant screen redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Target, no Follow toggle, a two-column live net screen, and a net control line that can be fixed for tonight or for the net.

**Architecture:** `live_net.py` gains the words for the net control line and a `set_controller(..., save_for_net)` call; `ui/live_net.py` is re-laid out around a Target card. Rotate paths (`LiveNet.target/rotate/snap_back`) are unchanged, so invariant 2 keeps its existing tests.

**Tech Stack:** Python 3.14, NiceGUI, sqlite3, pytest with `nicegui.testing.User`.

**Spec:** `docs/superpowers/specs/2026-10-31-participant-screen-redesign-design.md`

## Global Constraints

- Only Rotate, Rotate to net control, Ctrl+Enter and Home send rotator commands (invariant 2).
- QRZ is contacted only on a button press, and only with a QRZ client (offline-first).
- No migration, no new dependencies, no change to net control's screen.
- A missing grid stays missing (invariant 4).
- Version 1.3.0 in `pyproject.toml`, `src/beam_navigator/__init__.py`, `uv.lock`.

## Review Focus

1. A measured-bearing controller with no callsign: the header must not say "not set".
2. Save for this net on a closed session: works, and touches no check-ins.
3. Dialog opened twice: fields start from tonight's values each time.
4. Typed target then a row click: only one row highlighted, Target card names the row.
5. QRZ lookup failure in the dialog: a notice, the dialog stays open, nothing saved.

---

### Task 1: Core — net control line and set_controller

**Files:** Modify `src/beam_navigator/live_net.py`; Test `tests/unit/test_live_net.py`

**Interfaces — Produces:**
- `ControllerView.toward: Bearing | None = None` (you → controller, with distance).
- `controller_line(c: ControllerView) -> tuple[str, str]` → (text, button label):
  - no call, no bearing: `("Net control: not set", "Set net control…")`
  - call, no location, no measured bearing: `(f"Net control: {call} — location unknown", "Add grid…")`
  - measured: `(f"Net control: {call or 'call unknown'} · {deg:.1f}° (measured)", "Change…")`
  - located: `(f"Net control: {call} · {toward.text} · {toward.distance_text}", "Change…")`
- `LiveNet.set_controller(session_id, callsign, grid, bearing, *, save_for_net: bool) -> None` (set_substitute, then `nets.save_controller_as_default` when asked).

- [ ] Tests: `test_controller_line_states` (four cases above), `test_set_controller_tonight_leaves_net`, `test_save_for_net_starts_next_session_with_it` (start_session after save has the call and grid), `test_save_for_net_on_closed_session` (status stays closed, check-ins unchanged). Run, see FAIL, implement, PASS, commit.

### Task 2: UI — one Target, two columns, net control dialog

**Files:** Modify `src/beam_navigator/ui/live_net.py`; Test `tests/ui/test_live_net_page.py`

- Remove `MODE_OPTIONS`, the toggle, `set_mode`, `station_mode`, the controller card and `_substitute_dialog`.
- `_State.source: str` = "Net control" | "Tonight list" | "Regulars" | "Typed" | "I hear"; set wherever the target is picked.
- Header: title line, net control line (marker `net-control`) + button (marker `net-control-change`), last-time card.
- Left column (marker `beam`, sticky on md+): Target card (marker `target`: label, `°` + compass, "from: <source>"; or "No target yet — pick a station" / "<call> — grid needed: type a grid, or pick another station"), Rotate (marker `rotate`) with reason label (marker `rotate-reason`) when disabled, "Rotate to net control" (marker `snap-back`), rotator select, status, compass + banner.
- Right column: "Find or point at" box (marker `aim`), Tonight, Regulars, I hear.
- Dialog (marker `controller-dialog`): Callsign `nc-call`, Grid `nc-grid`, Measured bearing `nc-bearing`, "Get grid from QRZ" `nc-qrz` (only with a QRZ client), buttons "Use for tonight" `nc-tonight`, "Save for this net" `nc-save`, Cancel. Prefilled from the session on each open.

- [ ] Tests (rewrite the toggle/substitute ones): `test_header_names_net_control_with_bearing`, `test_not_set_offers_set_net_control`, `test_use_for_tonight_leaves_net`, `test_save_for_net_sets_default`, `test_target_card_follows_picks` (row → "Tonight list", aim → "Typed", I-hear aim → "I hear", no commands), `test_row_click_then_snap_back_one_command` (acceptance 18 without the toggle), `test_rotate_reason_when_no_target`, `test_no_follow_toggle`. Update `test_controls_give_focus_back_to_hotkeys` markers. FAIL, implement, PASS, full suite, commit.

### Task 3: Docs and version

Requirements 4.4 + acceptance tests naming Follow, decision 46, user guide "Following a net", version 1.3.0. Full suite, ruff, mypy. Commit.
