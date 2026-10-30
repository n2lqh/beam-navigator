# Milestone 3c — Rotator Field Help, Net Search and Favourites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three owner requests from 2026-10-28:
- the rotator settings explain every field
- the nets page can be searched
- nets can be starred as favourites, which sort first and can be shown on their own

**Architecture:**
- Help copy lives in one table, `ROTATOR_HELP`, in `ui/settings.py`. Each field shows its line as a Quasar `hint` under the input, and an "About travel and stops" panel explains the range in more depth.
- Search and favourites are rules in `nets.py` (`NetBook.listing`). `ui/nets.py` only renders them.
- Migration 0007 adds `net.favourite`.

**Tech Stack:** NiceGUI 3.18, `sqlite3`. No new dependencies.

**Spec:** `docs/requirements.md` 4.6 (nets list), 4.7 (rotator profiles), 4.8 (settings). Owner requests 2026-10-28. Decisions 25–27.

**Out of scope:** QRZ lookup (requirements 4.9, its own plan) and key remapping (plan 3d).

## Design

**Rotator help** (exact copy; every claim matches requirements 4.7 and `docs/rotator-notes.md`):

| Field | Hint |
|---|---|
| Rotator name | Your own label, e.g. VHF or 432 beam. |
| Adapter | simulation: no hardware, commands are only recorded. pstrotator: PstRotator or PstRotatorAz on Windows, over UDP. hamlib: Hamlib's rotctld, over TCP. |
| Host | The computer running PstRotator or rotctld. 127.0.0.1 means this computer. Not used in simulation. |
| Port | PstRotator: the UDP port set in PstRotator (usually 12000); its replies come back on the next port up. rotctld: its TCP port (usually 4533). |
| Travel preset | Fills in travel start and end for common rotators. Check them against your rotator's manual. |
| Speed | Degrees per second, used only for the time estimate. Leave blank if unknown. |
| Travel start / Travel end | The rotor's mechanical range in rotor degrees. Headings outside it are refused, never wrapped. |
| Offset | Rotor heading = true bearing + offset. If the beam points at true north when the rotor reads 5°, enter 5. Leave 0 if calibrated. |
| Bands it serves | Bands this antenna is used on. Each band has one rotator, which becomes the default on the dashboard and live net screen. |

**"About travel and stops"** is a `ui.expansion` under the form (marker `rotator-about`). It covers:
- A north-stop rotor turns 0–360°.
- A south-stop rotor turns 180–540°, because rotor degrees past 360 are the same compass heading again.
- A Yaesu 450° rotor turns 0–450°, so headings 0–90° can be reached two ways. Beam Navigator shows which way it plans to go. PstRotatorAz chooses its own path.
- **Live** turns the real antenna. It unlocks only after **Test connection** passes. New rotators start in simulation.

**Search** is one box above the list (marker `net-search`). It matches case-insensitively on:
- name
- channel
- frequency, as text in MHz (`144.2` matches 144.245)
- band
- default controller call

Blank shows everything. Search combines with **Show archived** and **Favourites only**. When nothing matches: `No nets match "<text>".`

**Favourites:**
- A star button on each card (marker `favourite-{id}`, icon `star` or `star_border`). Clicking it sends nothing to the rotator.
- Favourites sort first, then by name.
- A **Favourites only** switch (marker `favourites-only`) shows just favourites.
- The favourite flag is personal, so `*.beamnet.json` leaves it out (decision 26 stands).
- Duplicating a net does not copy the star.

## Global Constraints

- No rotator command from any of this (invariant 2).
- Help copy states only documented behaviour; no invented protocol details (invariant 4).
- Logic stays out of `ui/`. `ruff` line length is 100. `mypy --strict` stays clean on `core`.

## Review Focus

1. **A search typed with spaces or capitals** (`" PACK rats "`) still matches. Task 2 `test_search_matches_fields`.
2. **A favourite that is also archived:** hidden unless **Show archived** is on. Task 2 `test_favourite_archived_hidden`.
3. **Exporting a starred net** leaves the star out of the file. Task 2 `test_favourite_not_exported`.
4. **Starring while a search is active** keeps the search text and the filtered list. Task 3 `test_star_keeps_search`.
5. **Help hints present on every rotator field,** including when editing an existing rotator. Task 1 `test_every_rotator_field_has_help`.

---

### Task 1: Rotator field help

**Files:** Modify `src/beam_navigator/ui/settings.py`. Test `tests/ui/test_settings.py`.

**Interfaces:** Produces `ROTATOR_HELP: dict[str, str]`, keyed by the field markers `rotator-name`, `rotator-adapter`, `rotator-host`, `rotator-port`, `rotator-preset`, `rotator-speed`, `rotator-min`, `rotator-max` and `rotator-bands`, plus `rotator-offset`. `rotator-min` and `rotator-max` share the travel line.

- [ ] **Step 1: Write the failing tests.**
  - `test_every_rotator_field_has_help`: on `/settings`, every key of `ROTATOR_HELP` has exactly one element whose `props["hint"]` equals its text. This still holds after clicking an existing rotator's Edit.
  - `test_about_travel_panel`: marker `rotator-about` exists and contains `180–540` and `Test connection`.
  - `test_help_copy`: the offset line contains `true bearing + offset`, and the port line contains `12000` and `4533`.
- [ ] **Step 2: Run.** `uv run pytest tests/ui/test_settings.py -q`. Expected: FAIL (`ROTATOR_HELP` missing).
- [ ] **Step 3: Implement.** Add the table, `.props(f'hint="{text}"')` (or `.props({"hint": text})`) on each field, and the expansion with the Design text.
- [ ] **Step 4: Run.** `uv run pytest -q && uv run ruff check .` Expected: all pass.
- [ ] **Step 5: Commit.** `feat: rotator settings explain every field (owner request)`

### Task 2: Search and favourites rules

**Files:**
- Create: `src/beam_navigator/store/migrations/0007_net_favourite.sql`
- Modify: `core/models.py` (`Net.favourite: bool = False`, last field), `store/repositories.py`, `nets.py`
- Test: `tests/unit/test_nets.py`, `tests/unit/test_beamnet.py`, plus the two schema-version pins (6 → 7)

**Interfaces:**
- Produces:
  - `NetBook.listing(now, show_archived=False, query="", favourites_only=False) -> list[NetSummary]`
  - `NetBook.set_favourite(net_id: int, favourite: bool) -> None`
- `NetBook.save` keeps the stored `favourite` when editing. A new net, or a duplicate, starts unstarred.

- [ ] **Step 1: Write the failing tests.**
  - `test_search_matches_fields`, parametrised. Queries: `" PACK rats "` (name), `"tg 31"` (channel), `"144.2"` (frequency), `"70 cm"` (band), `"w2kv"` (controller). Each returns exactly the net it should. `"zzz"` returns none, and `""` returns all.
  - `test_favourites_first_then_name`: B is starred and A and C are not. Listing order is B, A, C, and `favourites_only=True` gives just B.
  - `test_favourite_archived_hidden`: a starred, archived net is missing unless `show_archived=True`.
  - `test_edit_keeps_favourite_duplicate_does_not`.
  - `test_favourite_not_exported` (in `test_beamnet.py`): there is no `favourite` key in the written JSON.
- [ ] **Step 2: Run.** `uv run pytest tests/unit/test_nets.py tests/unit/test_beamnet.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Migration: `ALTER TABLE net ADD COLUMN favourite INTEGER NOT NULL DEFAULT 0;`. Matching uses `casefold()` on the stripped query against each field. Frequency text is `f"{mhz:g}"`.
- [ ] **Step 4: Run.** `uv run pytest -q && uv run ruff check . && uv run mypy src/beam_navigator/core`. Expected: all clean.
- [ ] **Step 5: Commit.** `feat: net search and favourites (owner request)`

### Task 3: Nets page search box and stars

**Files:** Modify `src/beam_navigator/ui/nets.py`. Test `tests/ui/test_nets_page.py`.

**Interfaces:** Consumes the Task 2 `listing` and `set_favourite`.

- [ ] **Step 1: Write the failing tests.**
  - `test_search_filters_cards`: with two nets, typing `other` in `net-search` shows only that card. `zzz` shows `No nets match "zzz".`
  - `test_star_sorts_first`: clicking `favourite-{id}` on the second net puts its card first, and the icon becomes `star`.
  - `test_favourites_only_switch`.
  - `test_star_keeps_search`: with a search active, starring keeps the search box text and the filtered list.
  - `test_no_rotator_command_from_star_or_search`: a recording simulator gets zero commands.
- [ ] **Step 2: Run.** `uv run pytest tests/ui/test_nets_page.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Search is a `ui.input` with `on_change` refreshing the list (no debounce needed for a handful of nets). The star is a flat round `ui.button(icon=...)` with the `BLUR` handler. Page state holds the query and both switches.
- [ ] **Step 4: Run.** `uv run pytest -q && uv run ruff check . && uv run mypy src/beam_navigator/core`. Expected: all clean.
- [ ] **Step 5: Commit.** `feat: nets page search and favourite stars (owner request)`
