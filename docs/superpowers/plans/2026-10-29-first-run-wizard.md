# First-Run Wizard (Plan 4b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Until a station is active, opening the app shows a short Welcome wizard instead of a dashboard that says "Set up your station first". The wizard has three steps: your station, the example nets, and where to go next. What the operator entered before is filled back in.

**Architecture:**
- `Desk` decides when the wizard is due, keeps the operator's last entries as a draft, and saves and activates the station.
- A new page, `ui/welcome.py`, is a three-step `ui.stepper` at `/welcome`.
- The dashboard sends the operator there while no station is active.

**Tech Stack:** Python 3.12+, NiceGUI 3.18 (`ui.stepper`, `ui.navigate`), sqlite3 settings, `zoneinfo`, pytest. No new dependencies.

**Spec:** `docs/requirements.md` section 6 Milestone 4 ("first-run wizard"); 4.6 ("Example nets … are offered at first run, opt-in, labeled unverified"); 4.8; invariants 2, 8 and 10; and the v2 definition of done ("install the app, enter their grid, …").

## Global Constraints

- Invariant 10: no hard-coded station. On a new install the wizard's fields are empty. They are only ever filled from the operator's own earlier entries or saved profiles. N2LQH and FM29pt appear nowhere in its code.
- Invariant 2: nothing in the wizard sends a rotator command. It never creates a rotator profile; it only links to Settings → Rotators.
- Example nets stay opt-in and labelled unverified. The wizard uses the existing `NetBook.add_examples()` and `decline_examples()`, so the Nets page's own offer disappears once answered here.
- No network. The wizard does not run a QRZ lookup; the QRZ step is a link to Settings → QRZ.
- No new dependencies.

## Design (decisions this plan makes; owner, 2026-10-29)

**When the wizard shows:** whenever no operator profile is active. That covers a database with no profiles at all, and one with profiles but none active.
- Opening `/` in that state goes to `/welcome`.
- **Skip for now** [`welcome-skip`] goes to `/?later=1`, which shows the dashboard for that visit only (its "Set up your station first" message stays). The next time `/` is opened, the wizard comes back.
- Once a station is active the wizard never shows. An existing database with an active profile needs no migration.
- After a restore, the restored database decides.

**Draft.** The operator's step-1 entries are kept as JSON in the setting `welcome_draft`:
- Fields: `{"callsign", "grid", "units", "timezone", "profile_id"}`.
- Saved on every Next press, even one that is refused, and on Skip for now.
- Cleared once a station is active.

**What step 1 is filled with, in order:**
1. The draft, if there is one.
2. Otherwise the most recently saved profile (the highest id). Its id goes into `profile_id`, so Next updates that profile instead of making a duplicate.
3. Otherwise empty, with units km and time zone UTC.

**Step 1: Your station** (markers in brackets)
- If saved profiles exist, they are listed first under "Use a saved station", each with a Use button [`welcome-use-{id}`]. Use calls `Desk.use_station(id)`, which activates it and clears the draft, then moves to step 2. The form below is then headed "Or enter a station".
- Fields:
  - Callsign, optional [`welcome-callsign`].
  - Home grid, required [`welcome-grid`].
  - Units, km or mi [`welcome-units`].
  - Time zone, with the hint "For net times, e.g. America/New_York" [`welcome-timezone`].
- Next [`welcome-next-1`] calls `Desk.save_welcome_station(draft)`:
  - It saves through `ProfileRepository.save`, so grid checking is the same as in Settings.
  - With `profile_id` it updates that profile (keeping its name). Without one it inserts a profile named after the callsign, or "Home" without one.
  - It then activates the profile and clears the draft.
- A time zone `ZoneInfo` doesn't know is refused: "{zone!r} is not a time zone. Use a name such as America/New_York, or UTC."
- Errors show under the form [`welcome-error`], and the step does not advance.
- Below the form: "Moving to a new computer? Restore a backup instead" links to `/settings?tab=Data`. That makes the Settings route take an optional `tab`; the `restored` query already selects Data.

**Step 2: Example nets.** The existing offer text (`EXAMPLE_OFFER` from `ui/nets.py`), with two buttons:
- Add examples [`welcome-examples-add`] calls `add_examples()`, then shows "Added N example nets." before moving on.
- No thanks [`welcome-examples-no`] calls `decline_examples()`.
- If the offer was already answered (e.g. after a restore), this step says "Example nets: already set." and has Next only [`welcome-next-2`].

**Step 3: Next steps.** Three links and a Finish button:
- "Set up a rotator (it starts in simulation)" goes to `/settings?tab=Rotators`.
- "Add your QRZ login for name and grid lookups" goes to `/settings?tab=QRZ`.
- "Change keyboard shortcuts" goes to `/settings?tab=Keys`.
- Finish [`welcome-finish`] goes to `/`.

Steps 2 and 3 come after a station is active. If the operator leaves during them, the wizard does not return; the Nets page still makes its own example offer.

**Header.** The Welcome page has the normal header, so the operator is never trapped.

## Review Focus

- Skip for now must show the dashboard once and not loop, and the next plain `/` must show the wizard again.
- A bad grid or time zone in step 1 shows the reason and saves no profile, but the entries are kept in the draft and come back on the next visit.
- A profile filled in from a previous run and saved again updates it: no duplicate profile.
- A corrupt `welcome_draft` setting (not JSON, wrong types) falls back to the next source, never crashes.
- An install with an active profile never sees the wizard; one with profiles but none active does, and can pick one.

---

### Task 1: Desk decides, keeps the draft, and saves the station

**Files:**
- Modify: `src/beam_navigator/desk.py`
- Test: `tests/unit/test_desk_welcome.py`

**Interfaces:**
- Produces:
  - `WELCOME_DRAFT = "welcome_draft"` in `desk.py`
  - a frozen dataclass `WelcomeDraft(callsign: str = "", grid: str = "", units: Literal["km", "mi"] = "km", timezone: str = "UTC", profile_id: int | None = None)`
  - `Desk.needs_welcome() -> bool`, true when no profile is active
  - `Desk.welcome_draft() -> WelcomeDraft`, filled from the draft, then the latest profile, then empty
  - `Desk.keep_welcome_draft(draft: WelcomeDraft) -> None`
  - `Desk.save_welcome_station(draft: WelcomeDraft) -> OperatorProfile`, which keeps the draft first, then validates, saves, activates and clears the draft
  - `Desk.use_station(profile_id: int) -> None`, which activates it and clears the draft

- [ ] **Step 1: Write the failing tests** on an `open_db(":memory:")` desk:
  - `test_new_database_needs_welcome`: True, and `welcome_draft() == WelcomeDraft()`.
  - `test_inactive_profiles_still_need_it`: save a profile without activating it; still True.
  - `test_active_profile_ends_it`: save and activate a profile; False.
  - `test_save_station_inserts_and_activates`:
    - `save_welcome_station(WelcomeDraft("n0call", "FN20", "mi", "America/New_York"))` returns an active profile named "N0CALL" with units "mi"
    - `needs_welcome()` is False
    - `desk.settings.get(WELCOME_DRAFT)` is None
    - without a callsign, the name is "Home"
  - `test_bad_grid_keeps_the_draft`: grid "ZZ99" raises `ValueError`; `desk.profiles.list() == []`; `welcome_draft().grid == "ZZ99"`.
  - `test_bad_zone_keeps_the_draft`: zone "Mars/Base" raises `ValueError` matching "is not a time zone"; no profile; the draft keeps "Mars/Base".
  - `test_draft_from_latest_profile`:
    - save two inactive profiles (FN20 then FN31)
    - `welcome_draft()` has grid "FN31" and that profile's id
    - `save_welcome_station(that draft)` leaves 2 profiles, with FN31's now active
  - `test_kept_draft_wins_over_profile`: with a saved inactive profile, `keep_welcome_draft(WelcomeDraft(grid="FM18"))` makes `welcome_draft().grid == "FM18"`.
  - `test_corrupt_draft_falls_back`, parametrized over `"{not json"`, `"[1]"`, `'{"grid": 5}'`, and `'{"units": "furlongs"}'`: `welcome_draft()` returns the profile fallback, or `WelcomeDraft()` when there is no profile.
  - `test_use_station`: activates the profile and clears the draft.
  - `test_profile_id_that_vanished`: a draft with `profile_id` 999 inserts a new profile instead of failing.

- [ ] **Step 2: Run them to see them fail.** Run: `uv run pytest tests/unit/test_desk_welcome.py -q`. Expected: ImportError or AttributeError.

- [ ] **Step 3: Implement it.**
  - Check the time zone with `zoneinfo.ZoneInfo`. `ZoneInfoNotFoundError` and `ValueError` mean refused.
  - When updating, keep the existing profile's name, region and lat/lon.

- [ ] **Step 4: Run them to see them pass,** then the full suite, `ruff check .` and `mypy src/beam_navigator/core`.

- [ ] **Step 5: Commit**: `feat: desk welcomes an operator until a station is active (Milestone 4)`.

### Task 2: The Welcome page and the redirect

**Files:**
- Create: `src/beam_navigator/ui/welcome.py`
- Modify:
  - `src/beam_navigator/ui/app.py`:
    - the `/welcome` route
    - `/` takes `later: str | None = None`, and redirects with `ui.navigate.to("/welcome")` when `needs_welcome()` and `later` is None
    - `/settings` takes `tab: str | None = None`
  - `src/beam_navigator/ui/settings.py`: `settings_page(..., tab: str | None = None)` selects that tab by its label; an unknown name selects Station.
- Test: `tests/ui/test_welcome.py`

**Interfaces:**
- Consumes: Task 1's methods and `WelcomeDraft`; `NetBook(desk.conn, desk)` with `example_offer`, `add_examples`, `decline_examples`; `EXAMPLE_OFFER` from `ui/nets.py`.
- Produces: `welcome_page(desk: Desk, book: NetBook) -> None`.

- [ ] **Step 1: Write the failing UI tests** with the `user` fixture and `register_pages`:
  - `test_new_install_opens_welcome`: `user.open("/")`, then the user sees "Your station".
  - `test_active_profile_opens_dashboard`: `/` does not show "Your station".
  - `test_inactive_profiles_offer_a_choice`:
    - one saved, inactive profile named "Portable"
    - `/` shows "Use a saved station" and "Portable"
    - clicking `welcome-use-{id}` makes it active, and the user sees "Add example nets?"
  - `test_station_step_creates_and_activates`: type `K2ABC` and `FN20`, click `welcome-next-1`; the user sees "Add example nets?", and the active grid is "FN20".
  - `test_bad_grid_reported_and_remembered`:
    - grid `ZZ99`, click Next; the user sees the grid error (marker `welcome-error`)
    - no profile exists
    - reopening `/welcome` shows `ZZ99` in `welcome-grid`
  - `test_skip_for_now_then_back`:
    - click `welcome-skip`; the user sees "Set up your station first"
    - `user.open("/")` again; the user sees "Your station"
  - `test_examples_add`: complete step 1, click `welcome-examples-add`; the user sees "Added 14 example nets.", and `book.example_offer()` is False.
  - `test_examples_no`: click `welcome-examples-no`; `book.example_offer()` is False, and no nets exist.
  - `test_finish_goes_to_dashboard`: after finishing, `/` shows the dashboard.
  - `test_settings_tab_query`: `user.open("/settings?tab=Rotators")` makes Rotators the selected tab.

- [ ] **Step 2: Run them to see them fail.** Run: `uv run pytest tests/ui/test_welcome.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement the page and routes** to the Design section. No business logic in the page: it calls only `Desk` and `NetBook`.

- [ ] **Step 4: Run them to see them pass,** then the full suite, `ruff check .` and `mypy src/beam_navigator/core`.

- [ ] **Step 5: Commit**: `feat: first-run Welcome wizard (Milestone 4)`.

### Task 3: Decision and requirements note

**Files:** `docs/decisions.md` (decision 35, summarising the Design section and the owner's two requests of 2026-10-29), `docs/requirements.md` 4.6 (add "(the Welcome wizard offers them; decision 35)" after the example-nets line).

- [ ] **Step 1:** Write both and run the full suite.
- [ ] **Step 2: Commit**: `docs: first-run wizard (decision 35)`.
