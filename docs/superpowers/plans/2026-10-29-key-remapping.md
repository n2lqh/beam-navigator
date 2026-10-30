# Key Remapping (Plan 3d) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every keyboard shortcut can be changed in Settings → Keys: the dashboard and live-net hotkeys, and the net-control entry-line keys. This finishes Milestone 3.

**Architecture:**
- A pure `core/keymap.py` defines the actions, their default key chords, and the rules a new binding must pass.
- The operator's changes are stored as one JSON setting (only the overrides). `Desk` resolves them into the full keymap.
- `hotkeys.action_for` and `entry_keys.key_action` take that keymap instead of fixed keys. The entry line's browser-side key filter is generated from it.
- A Keys tab in Settings records a new chord from one key press.

**Tech Stack:** Python 3.14, NiceGUI 3.18 (`ui.keyboard`, generic `keydown` events), sqlite3 settings table, pytest. No new dependencies.

**Spec:** `docs/requirements.md` 4.4 and 4.5 ("All keys remappable"); decisions 22 and 23, which deferred remapping to this plan.

## Global Constraints

- Invariant 2: the rotator moves only on an explicit press. A remapped Rotate or Snap back is still one fresh keydown. Auto-repeat never sends a second command, and no hotkey acts while a text field, select, textarea or button has focus (decision 22).
- Keys are matched by physical key code (`KeyboardEvent.code`), as the number-pad sectors already are, so the top-row digits never act as sectors.
- Space still moves on only from Callsign and Grid, where a space can never be typed (decision 23). This rule is fixed, not remappable (see Design).
- `core/` stays pure: no UI, no database.
- No new dependencies.

## Design (decisions this plan makes)

**Chord.** A chord is `Chord(code, ctrl=False, alt=False, shift=False)`.
- **Stored form:** modifiers in the order Ctrl, Alt, Shift, then the code, e.g. `"Ctrl+Enter"`, `"Shift+Tab"`, `"Ctrl+KeyN"`, `"Numpad8"`.
- **Display form:** `"Ctrl+N"`, `"Shift+Tab"`, `"Numpad 8"`, `"Enter"`. `Key` and `Digit` prefixes are dropped, and `Numpad` gets a space before the rest.
- **Meta:** Cmd/Meta counts as Ctrl, as it does today.
- **Enter and NumpadEnter:** a chord on `Enter` also matches `NumpadEnter`, as the fixed Rotate key does today.

**Actions and defaults** (ids are stable; labels are what Settings shows):

| scope | id | label | default |
|---|---|---|---|
| screen | `rotate` | Rotate to the target | Ctrl+Enter |
| screen | `snap_back` | Snap back to net control | Home |
| screen | `sector_N`, `sector_NE`, `sector_E`, `sector_SE`, `sector_S`, `sector_SW`, `sector_W`, `sector_NW` | Announce sector N … NW | Numpad8, Numpad9, Numpad6, Numpad3, Numpad2, Numpad1, Numpad4, Numpad7 |
| entry | `next` | Next field | Tab |
| entry | `previous` | Previous field | Shift+Tab |
| entry | `log` | Log the check-in | Enter |
| entry | `clear` | Clear the line | Escape |
| entry | `note` | Add a station note | Ctrl+KeyN |
| entry | `suggest_down` | Next suggestion | ArrowDown |
| entry | `suggest_up` | Previous suggestion | ArrowUp |

"screen" covers the dashboard and the live net screen; "entry" is the net-control entry line.

**Rules for a new binding.** Each refusal leaves the old binding in place, with the exact message shown:
1. **No clashes.** No two actions in the same scope share a chord. Message: `"{chord} is already used for {label}."`
2. **Entry line: no typing keys.** An entry-line chord must not type a character. A chord with no Ctrl or Alt is refused if its code is `Space`, `Key*`, `Digit*`, `Numpad0`–`Numpad9`, `NumpadDecimal`, or one of `Minus Equal BracketLeft BracketRight Backslash Semicolon Quote Comma Period Slash Backquote`. Message: `"{chord} types a character, so it can't be an entry-line key."`
3. **Keep Tab for moving around the screen.** Screen hotkeys can't use Tab or Shift+Tab. Message: `"Tab moves between buttons; choose another key."`
4. **Browser keys.** These are refused everywhere: Ctrl+KeyW, Ctrl+KeyT, Ctrl+Tab, Ctrl+Shift+Tab, Ctrl+KeyL, Ctrl+KeyR, F5, F11, F12, Alt+F4. Message: `"The browser keeps {chord} for itself."`
5. **Modifier keys alone** are refused: codes `ControlLeft`, `ControlRight`, `ShiftLeft`, `ShiftRight`, `AltLeft`, `AltRight`, `MetaLeft`, `MetaRight`. Message: `"Press a key, not just Ctrl, Alt or Shift."`

**Storage.**
- The overrides live in setting `keymap`, as JSON `{action_id: stored chord}`.
- Anything unreadable is ignored, falling back to the defaults: bad JSON, an unknown id, a chord that doesn't parse, or an override that now breaks a rule.
- Settings shows `"Some saved keys were not valid and were reset to their defaults."` when that happened.

**Space** stays a fixed second "next" key in Callsign and Grid. It isn't listed in Settings, so it can't be remapped. Remapping it could make Callsign swallow spaces or stop moving on, and decision 23 rests on contest-logger habit. **This is a ruling for the owner to confirm.**

**Recording a key** (Settings → Keys):
- **Change** opens a dialog: "Press the new key for {label}…". The dialog listens with `ui.keyboard(ignore=[])` and takes the first keydown that isn't just a modifier.
- **Escape** in the dialog cancels, so Escape can only be given back through **Reset**.
- The chord is checked with the rules above. On success it saves and the row updates; on refusal the dialog shows the message and keeps listening.
- Each row also has **Reset**, and there is one **Reset all keys**.

**On-screen hints** that name a key, such as the dashboard's "Ctrl+Enter", must show the current chord's display form.

## Review Focus

1. **A hand-edited or corrupt `keymap` setting** (bad JSON, unknown id, a clash). The app opens with defaults for the bad entries and never crashes. Covered by a Task 2 test.
2. **Remapped Rotate.** After Rotate moves to F9, Ctrl+Enter no longer rotates, F9 rotates once, and a held F9 still sends one command. Covered by a Task 3 test.
3. **Entry line with a remapped Log key**, e.g. F2. Enter must then type nothing and log nothing, and its browser default must not be suppressed. F2 logs, including the "first press fills" behaviour in Callsign (decision 31). Covered by a Task 4 test.
4. **Capture dialog with a refused chord:** Ctrl+R, or a clash. The message is shown, nothing is saved, and the dialog keeps listening. Escape cancels without saving. Covered by a Task 5 test.
5. **Hints after a remap:** the dashboard hint shows the new Rotate key, not "Ctrl+Enter". Covered by a Task 5 test.

---

### Task 1: The keymap model and its rules

**Files:**
- Create: `src/beam_navigator/core/keymap.py`
- Test: `tests/unit/test_keymap.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Chord: code: str; ctrl: bool = False; alt: bool = False; shift: bool = False`, with `matches(code, ctrl, alt, shift) -> bool` (Enter also matches NumpadEnter)
  - `@dataclass(frozen=True) class Action: id: str; scope: Literal["screen", "entry"]; label: str; default: Chord`
  - `ACTIONS: tuple[Action, ...]` in table order
  - `parse_chord(text: str) -> Chord`, raising ValueError
  - `stored(chord: Chord) -> str`
  - `label(chord: Chord) -> str`
  - `Keymap = dict[str, Chord]`
  - `DEFAULTS: Keymap`
  - `check(keymap: Keymap, action_id: str, chord: Chord) -> str | None`, returning the refusal message or None
  - `resolve(overrides: dict[str, str]) -> tuple[Keymap, bool]`, returning the keymap and whether anything was discarded

- [ ] **Step 1: Write the failing tests**

```python
def test_defaults_match_decisions_22_and_23() -> None:
    assert stored(DEFAULTS["rotate"]) == "Ctrl+Enter" and stored(DEFAULTS["snap_back"]) == "Home"
    assert stored(DEFAULTS["sector_NE"]) == "Numpad9" and stored(DEFAULTS["previous"]) == "Shift+Tab"
    assert stored(DEFAULTS["note"]) == "Ctrl+KeyN" and len(DEFAULTS) == 17

@pytest.mark.parametrize("text", ["Ctrl+Enter", "Shift+Tab", "Ctrl+Alt+Shift+F9", "Numpad8", "Ctrl+KeyN"])
def test_parse_and_store_round_trip(text: str) -> None:
    assert stored(parse_chord(text)) == text

@pytest.mark.parametrize("text", ["", "Ctrl+", "Shift+Ctrl+Enter", "Ctrl+Ctrl+Enter", "Hyper+F1"])
def test_bad_chords_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse_chord(text)

def test_labels() -> None:
    assert [label(parse_chord(t)) for t in ("Ctrl+KeyN", "Numpad8", "Digit5", "Ctrl+Enter")] == [
        "Ctrl+N", "Numpad 8", "5", "Ctrl+Enter"]

def test_enter_matches_numpad_enter() -> None:
    assert DEFAULTS["rotate"].matches("NumpadEnter", ctrl=True, alt=False, shift=False)
    assert not DEFAULTS["rotate"].matches("NumpadEnter", ctrl=False, alt=False, shift=False)

@pytest.mark.parametrize(("action", "text", "message"), [
    ("rotate", "Home", "Home is already used for Snap back to net control."),
    ("log", "KeyL", "L types a character, so it can't be an entry-line key."),
    ("log", "Space", "Space types a character, so it can't be an entry-line key."),
    ("rotate", "Tab", "Tab moves between buttons; choose another key."),
    ("rotate", "Ctrl+KeyR", "The browser keeps Ctrl+R for itself."),
    ("note", "ShiftLeft", "Press a key, not just Ctrl, Alt or Shift."),
])
def test_check_refuses(action: str, text: str, message: str) -> None:
    assert check(dict(DEFAULTS), action, parse_chord(text)) == message

def test_check_allows() -> None:
    keymap = dict(DEFAULTS)
    assert check(keymap, "rotate", parse_chord("F9")) is None
    assert check(keymap, "log", parse_chord("Ctrl+KeyL")) is None  # a modifier: types nothing
    assert check(keymap, "rotate", parse_chord("Ctrl+Enter")) is None  # its own chord
    assert check(keymap, "log", parse_chord("Home")) is None  # Home is a screen key; scopes differ

def test_resolve_discards_bad_overrides() -> None:
    keymap, discarded = resolve({"rotate": "F9", "nonsense": "F1", "log": "KeyQ", "clear": "Hyper+F1"})
    assert stored(keymap["rotate"]) == "F9"
    assert keymap["log"] == DEFAULTS["log"] and keymap["clear"] == DEFAULTS["clear"]
    assert discarded
    assert resolve({}) == (DEFAULTS, False)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/unit/test_keymap.py -q`
Expected: collection error, because `beam_navigator.core.keymap` does not exist.

- [ ] **Step 3: Implement `core/keymap.py`**

`resolve` applies overrides one at a time in `ACTIONS` order, each checked against the keymap built so far. Any override that fails `check` or doesn't parse is skipped, and `discarded` is set.

- [ ] **Step 4: Run them to see them pass**, then run `uv run mypy src/beam_navigator/core`.

Expected: PASS; mypy clean.

- [ ] **Step 5: Commit**

`git commit -m "feat: keymap model — actions, default chords, binding rules (spec 4.5)"`

### Task 2: Saving and loading the keymap

**Files:**
- Modify: `src/beam_navigator/desk.py`
- Test: `tests/unit/test_desk_keys.py`

**Interfaces:**
- Consumes: Task 1's `resolve`, `check`, `parse_chord`, `stored`, `DEFAULTS`, `ACTIONS`
- Produces:
  - `KEYMAP_SETTING = "keymap"`
  - `Desk.keymap() -> Keymap`
  - `Desk.keymap_discarded() -> bool`
  - `Desk.set_key(action_id: str, chord: Chord) -> None`, raising ValueError(message) from `check`, or `"Unknown action {id}."`
  - `Desk.reset_key(action_id: str | None) -> None`, where None resets all

- [ ] **Step 1: Write the failing tests**

```python
def test_default_keymap(desk: Desk) -> None:
    assert desk.keymap() == DEFAULTS and not desk.keymap_discarded()

def test_set_key_stores_only_the_override(desk: Desk) -> None:
    desk.set_key("rotate", parse_chord("F9"))
    assert json.loads(desk.settings.get("keymap") or "{}") == {"rotate": "F9"}
    assert stored(desk.keymap()["rotate"]) == "F9"

def test_set_key_refused_keeps_the_old_binding(desk: Desk) -> None:
    with pytest.raises(ValueError, match="already used for Snap back to net control"):
        desk.set_key("rotate", parse_chord("Home"))
    assert desk.keymap()["rotate"] == DEFAULTS["rotate"]

def test_reset(desk: Desk) -> None:
    desk.set_key("rotate", parse_chord("F9"))
    desk.set_key("log", parse_chord("F2"))
    desk.reset_key("rotate")
    assert json.loads(desk.settings.get("keymap") or "{}") == {"log": "F2"}
    desk.reset_key(None)
    assert desk.keymap() == DEFAULTS

@pytest.mark.parametrize("raw", ["{not json", "[1, 2]", '{"rotate": 5}', '{"rotate": "Home"}'])
def test_corrupt_setting_falls_back(desk: Desk, raw: str) -> None:
    desk.settings.set("keymap", raw)
    assert desk.keymap()["rotate"] == DEFAULTS["rotate"]
    assert desk.keymap_discarded()
```

Use the `desk` fixture pattern from `tests/unit/test_desk_qrz.py`.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/unit/test_desk_keys.py -q`
Expected: FAIL with AttributeError.

- [ ] **Step 3: Implement.** Non-dict JSON and non-string values count as discarded.

- [ ] **Step 4: Run them to see them pass.**

- [ ] **Step 5: Commit**

`git commit -m "feat: keymap saved as overrides; corrupt settings fall back to defaults (spec 4.5)"`

### Task 3: Screen hotkeys follow the keymap

**Files:**
- Modify: `src/beam_navigator/hotkeys.py` (`action_for` gains `keymap: Keymap` and `alt: bool`; the fixed constants go)
- Modify: `src/beam_navigator/ui/lookup.py`
- Modify: `src/beam_navigator/ui/live_net.py`. Both pages read `desk.keymap()` once when the page is built.
- Test: `tests/unit/test_hotkeys.py`, `tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes: `Desk.keymap()` (Task 2)
- Produces: `action_for(code: str, ctrl: bool, alt: bool, shift: bool, keydown: bool, repeat: bool, screen: Screen, keymap: Keymap) -> Action | None`. Action values are unchanged: `"rotate"`, `"snap_back"` and `("sector", "NE")`. Snap back and sectors still apply only on `live_net`.

- [ ] **Step 1: Write the failing tests.** Update the existing `test_hotkeys.py` calls to the new signature with `DEFAULTS`, so current behaviour stays pinned. Add:

```python
def test_remapped_rotate() -> None:
    keymap = {**DEFAULTS, "rotate": parse_chord("F9")}
    hit = lambda code, ctrl=False, repeat=False: action_for(code, ctrl, False, False, True, repeat, "dashboard", keymap)
    assert hit("F9") == "rotate"
    assert hit("Enter", ctrl=True) is None  # the old chord is free again
    assert hit("F9", repeat=True) is None  # a held key: one command (invariant 2)

def test_remapped_sector() -> None:
    keymap = {**DEFAULTS, "sector_N": parse_chord("ArrowUp")}
    assert action_for("ArrowUp", False, False, False, True, False, "live_net", keymap) == ("sector", "N")
    assert action_for("Numpad8", False, False, False, True, False, "live_net", keymap) is None
```

In `tests/ui/test_dashboard.py`, add `test_remapped_rotate_key_moves_once`. It sets `desk.set_key("rotate", parse_chord("F9"))` before the page opens, looks up FN20ok, and triggers the keyboard twice with `code: "F9"` (repeat False, then True). Assert `len(sim.commands) == 1`. A Ctrl+Enter trigger then adds nothing. Use the trigger shape of the existing Ctrl+Enter dashboard test.

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_hotkeys.py tests/ui/test_dashboard.py tests/ui/test_live_net_page.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**

`git commit -m "feat: dashboard and live-net hotkeys follow the keymap (spec 4.4, 4.5)"`

### Task 4: The entry line follows the keymap

**Files:**
- Modify: `src/beam_navigator/entry_keys.py` (`key_action` matches codes against the keymap)
- Modify: `src/beam_navigator/ui/control.py`. `_keys_js` is generated from the keymap's entry chords, plus Space in Callsign and Grid. It emits `code`, `ctrlKey` (or metaKey), `altKey` and `shiftKey`, and calls `preventDefault` only for bound chords.
- Test: `tests/unit/test_entry_keys.py`, `tests/ui/test_control.py`

**Interfaces:**
- Consumes: `Desk.keymap()`; the control page reads it once at build
- Produces:
  - `key_action(field: str, code: str, ctrl: bool, alt: bool, shift: bool, keymap: Keymap) -> KeyAction`
  - Space (code `Space`, no modifiers) in a field from `SPACE_ADVANCES` returns `"next"` whatever the keymap says
  - `suggest_down` and `suggest_up` act only in Callsign; elsewhere those chords are `"type"`

- [ ] **Step 1: Write the failing tests.** Update the existing `test_entry_keys.py` cases to codes plus `DEFAULTS`. For example, `("Enter", ...)` keeps `"log"` and `KeyN` with Ctrl gives `"note"`. Add:

```python
def test_remapped_log_key() -> None:
    keymap = {**DEFAULTS, "log": parse_chord("F2")}
    assert key_action("name", "F2", False, False, False, keymap) == "log"
    assert key_action("name", "Enter", False, False, False, keymap) == "type"

def test_space_stays_fixed_in_callsign() -> None:
    keymap = {**DEFAULTS, "next": parse_chord("F3")}
    assert key_action("callsign", "Space", False, False, False, keymap) == "next"
    assert key_action("name", "Space", False, False, False, keymap) == "type"
```

In `test_control.py`:
- Make the `key()` helper send `code` (map `" "` to `Space`, `"n"` to `KeyN`, others unchanged) and `altKey: False`.
- Add `test_remapped_log_key`: set `log` to F2, open the control page, type K9ZZZ, then press F2 twice from Callsign. The first press fills; the second logs, and you should see "Logged K9ZZZ". Pressing Enter adds no check-in.
- Add `test_keys_js_follows_the_keymap`: `_keys_js(keymap, space_advances=False)` contains `'F2'` and not `'Enter'` when log is F2.

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_entry_keys.py tests/ui/test_control.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**

`git commit -m "feat: net-control entry keys follow the keymap; Space stays fixed in Callsign and Grid (spec 4.5)"`

### Task 5: Settings → Keys, and hints that show the current keys

**Files:**
- Modify: `src/beam_navigator/ui/settings.py` (new "Keys" tab, `_keys_panel(desk)`)
- Modify: every UI hint that names a key. Find them with `grep -rn "Ctrl+Enter\|Home\b\|Ctrl+N" src/beam_navigator/ui` and make each one use `label(desk.keymap()[id])`.
- Test: `tests/ui/test_settings.py`, `tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes: Tasks 1–2
- Markers:
  - `keys-row-{id}` and `key-{id}` (shows the display form)
  - `key-change-{id}` and `key-reset-{id}`
  - `keys-reset-all`
  - `key-dialog`, `key-message`
  - `keys-discarded`, for the "Some saved keys…" notice

- [ ] **Step 1: Write the failing tests**

```python
async def test_keys_tab_lists_every_action(user, desk) -> None:
    await open_tab(user, desk, "Keys")
    for action in ACTIONS:
        await user.should_see(marker=f"key-{action.id}")
    await user.should_see("Ctrl+Enter")

async def test_record_a_new_key(user, desk) -> None:
    await open_tab(user, desk, "Keys")
    user.find(marker="key-change-rotate").click()
    press(user, code="F9")  # triggers the dialog's ui.keyboard with a keydown
    await user.should_see("F9")
    assert stored(desk.keymap()["rotate"]) == "F9"

async def test_refused_key_keeps_listening(user, desk) -> None:
    await open_tab(user, desk, "Keys")
    user.find(marker="key-change-rotate").click()
    press(user, code="KeyR", ctrl=True)
    await user.should_see("The browser keeps Ctrl+R for itself.")
    assert desk.keymap()["rotate"] == DEFAULTS["rotate"]
    press(user, code="Escape")
    await user.should_not_see(marker="key-dialog")
    assert desk.keymap()["rotate"] == DEFAULTS["rotate"]

async def test_reset_all(user, desk) -> None:
    desk.set_key("rotate", parse_chord("F9"))
    await open_tab(user, desk, "Keys")
    user.find(marker="keys-reset-all").click()
    await eventually(lambda: desk.keymap() == DEFAULTS)

async def test_discarded_notice(user, desk) -> None:
    desk.settings.set("keymap", "{not json")
    await open_tab(user, desk, "Keys")
    await user.should_see("Some saved keys were not valid and were reset to their defaults.")
```

Write `press(user, code, ctrl=False)` in the test file, triggering the `key` event on the dialog's keyboard element with the same arguments shape as `test_dashboard.py` uses. In `test_dashboard.py`, add `test_hint_shows_remapped_rotate`: after `set_key("rotate", F9)` the dashboard shows "F9" in its hint and does not show "Ctrl+Enter".

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite, ruff and mypy.**

Run `uv run pytest -q`, then `uv run ruff check .`, then `uv run mypy src/beam_navigator/core`. Expected: all green.

- [ ] **Step 5: Docs and commit**

- Add decision 33. It covers:
  - the chord model and the matching by code
  - the five rules
  - Space stays fixed
  - corrupt settings fall back
  - Escape cancels recording
- Edit decisions 22 and 23 so each ends "Remapping: decision 33" instead of "comes with plan 3c".
- In `hotkeys.py`, replace the docstring line "Fixed keys until remapping lands" with "Keys come from the keymap (decision 33)".
- Requirements 4.5: after "All keys remappable." add "(Settings → Keys; decision 33)".

`git commit -m "feat: Settings → Keys records new shortcuts; hints show the current keys (spec 4.5, decision 33)"`
