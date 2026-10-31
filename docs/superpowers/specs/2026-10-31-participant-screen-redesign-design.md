# Participant screen redesign — design

Date: 2026-10-31. Owner: Terry Rossi, N2LQH. Status: proposed, waiting for the owner's approval.

## Why

After v1.1/v1.2 the owner reports the live net (participant) screen is still hard to use:

- "the layout is not intuitive"
- "i still don't understand how the follow buttons work"
- "even though the net controller is known for the example nets the participants screen shows the controller as unknown"

What's wrong with the current screen, as found while preparing this design:

1. **Three ways to say "point here", plus a mode switch.** Aim at, the I-hear Aim button, clicking a row, and the Follow Controller / Station / Typed toggle all decide what Rotate turns to. The toggle is the part nobody can predict: clicking a row silently switches the mode, Enter in Aim at switches it to Typed, and the toggle can be moved to a mode with no target, leaving Rotate greyed out with no reason given (the owner's screenshot shows exactly that).
2. **The things you use most are scattered.** Rotate sits in the middle, the lists are below the fold, the I-hear line is under the compass, and the target is only visible inside the Rotate button's label.
3. **Net control "unknown" has no way out.** In the owner's data the net "Chesapeake Bay Mud Toads Net (KD8UD)" has a blank net control (KD8UD is only in its name), so every session from it says "Controller: unknown". The screen offers only "Substitute controller tonight", which never fixes the net, and a callsign without a grid is still "unknown" even when the grid could be found. (The repository has `save_controller_as_default`, but no screen calls it.)

## Goal

One idea the operator never has to learn: **there is one Target. Whatever you last picked is the Target. Rotate turns the antenna to the Target.** The screen always shows the Target in words, and nothing but a Rotate press (or its key) moves the antenna.

## Non-goals

- No change to net control's own screen, beyond what the shared I-hear line already brings.
- No change to what is stored (no migration), to exports, or to the rotator adapters.
- No new dependencies.

## Anti-goals (a failure even if it works)

- Anything other than Rotate, "Rotate to net control", or their keys moving the antenna (invariant 2).
- A Target the screen doesn't show in words.
- A greyed-out Rotate button without a sentence saying why.
- Inventing a grid for a station (invariant 4): a missing grid stays missing until the operator types it, a saved record has it, or the operator presses a QRZ lookup.

## The new screen

Wide window, two columns; on a narrow window the Beam panel comes first and the lists follow.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Chesapeake Bay Mud Toads Net · Thu 2026-10-29 · 144.250 MHz      [Close my session…] │
│ Net control: KD8UD · 214.0° SW · 145 km     [Change…]                            │
│ (Last time 2026-10-22: K3WGR weak from 40°, try 30°)                              │
├───────────────────────────────┬──────────────────────────────────────────────────┤
│ BEAM                          │ FIND OR POINT AT                                 │
│                               │ [ call, grid, alias or direction……… ] (×)        │
│ Target                        │ K3WWT · 342.1° NNW · 75 km   [Add to tonight]    │
│ K3WWT                         │                                                  │
│ 342.1° NNW · 75 km            │ TONIGHT (6)                 Sort: Check-in order │
│ from: Tonight list            │ ▸ 1 W2KV   Bob  FN20ok  342.0° NNW 75 km  Heard  │
│                               │   2 K3WWT  Al   FM29iv  …               Weak     │
│ [  ROTATE TO 342° (K3WWT)  ]  │ …                                                │
│ Ctrl+Enter                    │                                                  │
│ [ Rotate to net control ]     │ REGULARS NOT HEARD YET (11)   Sort: Last check-in │
│ Home                          │   N3RG  …                         [Heard]        │
│                               │ …                                                │
│ Rotator: VHF (Simulation) ▾   │                                                  │
│ Simulated: turned to 342°     │ I HEAR                                           │
│                               │ Callsign  Name            Grid                   │
│ NET CONTROL IS CALLING        │ QTH            Report  Notes                     │
│  NW  N  NE                    │ Direction: 342.1° NNW · 75 km                    │
│  W       E   → "That's you"   │ [Aim to K3WWT] [Look up on QRZ]                  │
│  SW  S  SE                    │                                                  │
└───────────────────────────────┴──────────────────────────────────────────────────┘
```

### 1. Header: the net and net control

- First line: net name, date, frequency, and **Close my session…** (or the Closed badge and **Reopen**), as today.
- Second line, always one of these three:
  - `Net control: KD8UD · 214.0° SW · 145 km` with **Change…**
  - `Net control: KD8UD — location unknown` with **Add grid…**
  - `Net control: not set` with **Set net control…**
- The "You → controller" / "Controller → you" card goes. Its "You → controller" bearing is now on this line. Its "Controller → you" bearing is only used by the compass ("is net control calling toward me?"), which already says so in words.
- **Change… / Add grid… / Set net control…** open one dialog: Callsign, Grid, Measured bearing (optional), and **Look up on QRZ** to fill the grid (only when pressed, only with a saved QRZ login; offline it isn't shown). Two buttons:
  - **Use for tonight**: this session only (today's "Substitute controller tonight").
  - **Save for this net**: this session, and the net's default net control too, so future sessions start with it (wires up the existing `save_controller_as_default`).
- If net control has a callsign but no grid, the saved station record's grid is used (as now). The dialog opens with the callsign already filled.
- **The owner's Mud Toads net:** opening it shows "Net control: not set — Set net control…". Typing KD8UD, pressing Look up on QRZ (or typing the grid) and **Save for this net** fixes it for good.

### 2. Beam panel: Target, Rotate, rotator, compass

- **Target** card, always visible (sticky on a wide window):
  - Callsign or label, in large type.
  - Bearing and distance from the user's station.
  - Where it came from, in words: "Net control", "Tonight list", "Regulars", "Typed", "I hear".
  - With no location: "K9ZZZ — grid needed: type a grid, or pick another station."
- **ROTATE TO 342° (K3WWT)**: the big button, always naming the Target. Ctrl+Enter, as now. When it can't rotate, a sentence under it says why ("No rotator set up: Settings → Rotators", "The target has no location").
- **Rotate to net control**: today's Snap back, renamed for what it does. It makes net control the Target and rotates in one press (Home key, as now).
- Rotator select, Live/Simulation, and the status line, as now.
- **Net control is calling** compass, as now. It says "That's you" or "Not toward you" and never moves anything.

### 3. Find or point at (replaces Aim at)

- The same box and behaviour as today's Aim at, with a clearer name. Typing filters both lists. Enter looks the text up, shows the bearing under the box, and makes it the Target ("Typed"). **Add to tonight** puts a callsign not in tonight's list onto the I-hear line.
- Enter never rotates. Ctrl+Enter straight after rotates, as now.

### 4. Lists: Tonight and Regulars not heard yet

- As today: same columns, sorts and Heard controls. Clicking a row makes that station the Target (highlighted). The Target card and Rotate update at once.
- The highlight follows the Target. Picking anything else clears it, so at most one row is ever highlighted, and only when it is the Target.

### 5. I hear

- As built in v1.2: six fields, then Direction, **Aim to <call>** (makes it the Target, source "I hear") and **Look up on QRZ**.

### What goes away

- **The Follow Controller / Station / Typed toggle.** Picking is the only way to choose the Target, and the Target card says what it is. Net control is the Target when the page opens.
- The separate controller card (folded into the header line).
- "Substitute controller tonight" as its own button (it is now **Use for tonight** in the dialog above).

## Behaviour rules (for tests)

1. Opening the screen: the Target is net control (or "No target yet — pick a station" when net control has no location). No command is sent.
2. Each of these sets the Target and sends nothing: a Tonight row click, a Regulars row click, Enter in Find or point at (when it resolves), Aim to <call>, and Heard on a selected regular (the Target follows them into Tonight, as now).
3. **Rotate** / Ctrl+Enter sends exactly one command, to the Target shown.
4. **Rotate to net control** / Home makes net control the Target and sends exactly one command.
5. Enter in Find or point at that does not resolve clears a Typed Target, so Rotate never turns to an older typed Target (as fixed in v1.1).
6. **Use for tonight** changes only this session. **Save for this net** also sets the net's default, and the next new session of that net starts with it.
7. QRZ is only contacted when **Look up on QRZ** is pressed. With no network, every other part of the screen works.
8. A closed session: the I-hear line, Heard and the heard selects are locked as now. Target, Rotate, Rotate to net control, the compass, and Change… (tonight only) still work. **Save for this net** works too: it changes the net, not the closed session's check-ins.

## Docs to update

Requirements 4.4 and the participant acceptance tests (37–47, reworded where the Follow toggle is named), a decision (46), the user guide's "Following a net" section, and the features table.

## Left to the builder

Exact spacing, colours and font sizes. Whether the Beam panel is sticky with CSS or a layout column. How the Target's "from" label is worded, within the list above.

## Noticed, not included

The owner's data has two Mud Toads sessions and three DVFRC sessions on the same night, probably from pressing Start session more than once. Making Start session open tonight's existing session instead is a separate small change, suggested for after this one.
