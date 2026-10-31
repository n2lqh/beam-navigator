# Participant net screen, usable without a roster — design

Owner request, 2026-10-30, after the first real net with the app: "Not usable."
The live net screen (`/net/{session_id}`, requirements 4.4) assumes a pasted
roster. A participant listening to a net has no roster: they hear stations one
at a time and want to point at them.

## What the owner asked for

1. A list of previous participants of this net.
2. Type a callsign, grid, alias or direction and move the rotator to it.
3. Add stations they hear, like the net control screen, saved for future nets.
4. Close out their session with closing comments, shown at the next session.

## Hard rules that shape this

- **Invariant 2:** nothing here moves the rotator except Rotate, Snap back and
  their hotkeys. Typing, Enter, picking a row, adding a station, closing a
  session: none of them send a command.
- Offline. Everything comes from the local database.
- Bearings are from the user's station.
- Unknown grids stay unknown.

## Layout

```
 Pack Rats 2 m Net · 144.250 · Controller N3RG
 ┌ Last time (2026-10-26) ───────────────────────────────┐
 │ "K3WGR weak from 40°, try 30° next week."             │  ← closing notes
 └───────────────────────────────────────────────────────┘
 You → controller 245°   Controller → you 64° (NE)
 Aim at: [ K3WGR______ ]  → 212° SW · 85 km · K3WGR (FN10)
 [ Rotate to 212° (K3WGR) ]  [ Snap back to controller ]   Simulation
 Announced sector: (compass)      YOUR SECTOR IS UP

 I hear: [Call] [Name] [Grid]  Enter adds        (suggestions ▾)
 ┌ Tonight (6) ──────────────────┐ ┌ Regulars not heard yet (14) ──┐
 │ 1 N3RG  Bob  FM29ki 245° …    │ │ K3WGR FN10 212° 85 km  12/15  │
 │ 2 K3WGR …   heard ▾           │ │ W2KV  FN20 30°  60 km   9/15  │
 └───────────────────────────────┘ └───────────────────────────────┘
                                         [ Close my session… ]
```

## 1. Previous participants ("Regulars not heard yet")

- Replaces today's grey "Expected" labels. Same data as
  `NetRepository.expected()`: everyone who has checked in to this net before
  and isn't in tonight's list.
- Each row shows callsign, name, grid, bearing and distance from the user,
  attendance ("12 of last 15") and last check-in date.
- Regulars has its own Sort select (owner, 2026-10-30): **Callsign** (A→Z),
  **Grid** (A→Z, unknown grids last), **Direction** (bearing from the user,
  0→359°, unknown bearings last), **Last check-in** (most recent first, the
  default).

## Filter and sort (owner, 2026-10-30)

The old separate Filter box and the general "Sort" select ("Roster order")
are removed. They confused the owner at the first net.

- **Aim at is also the filter.** As the user types, both Tonight and
  Regulars narrow to rows whose callsign, name or grid contains the text.
  Clearing the box shows everything. Enter aims at what was typed. Clicking a
  narrowed row aims at that station. Typing never moves the rotator.
- **Each list has its own sort, in its heading:**
  - **Tonight — sort by:** Check-in order (default; formerly "Roster
    order"), Callsign, Direction, Distance.
  - **Regulars — sort by:** Last check-in (default), Callsign, Grid,
    Direction.
- **Click a row:** it becomes the Rotate target ("Follow Station"). Nothing is
  sent.
- **"Heard" button on a row:** adds the station to tonight's list (see 3) with
  heard state Heard. The station moves from Regulars to Tonight.

## 2. Aim box: type a call, grid, alias or direction

- One text box, "Aim at". It uses the same resolver as the dashboard
  (`Desk.look_up`), so it accepts a callsign, a grid, a saved alias or a
  heading (`270`, `W`).
- **Enter** shows the bearing, distance and what it resolved to, makes it the
  Rotate target, and drops focus from the box. It never rotates. Because focus
  has left the box, `Ctrl+Enter` (Rotate) works right after, so the keyboard
  flow is: type → Enter → Ctrl+Enter.
- A callsign with no known grid shows "Grid needed". Rotate stays disabled.
- If the typed callsign isn't in tonight's list, an **"Add to tonight"** link
  sits next to the result.
- Target modes become Controller / Station / Typed. Picking a row selects
  Station. Pressing Enter in the aim box selects Typed. Snap back selects
  Controller. The Rotate button label always names the target, as it does now.

## 3. Add stations I hear ("I hear" line)

- A short entry line: **Callsign → Name → Grid**, with the net control
  screen's behavior. Same keys, partial-call matching ranked by attendance at
  this net, autofill from station records in the "from history" style, the
  duplicate check, and the "This session only / Update station record" choice
  when a name or grid differs. It reuses `NetControl` (autofill, suggest,
  duplicate, log), not a copy of it.
- Logging adds a check-in to this session with heard state Heard. Future
  sessions of this net then list the station under Regulars automatically,
  because participants are built from past check-ins.
- A new station follows the same rules as on the net control screen. A saved
  grid is never overwritten without the user choosing "Update station record".
- QRZ autofill works here when it's set up, the same way as on the net control
  screen. Without it, nothing changes.

## 4. Close my session, with closing notes

- **"Close my session…"** opens a dialog with a notes box ("Notes for next
  time") and Close / Cancel.
- Close sets the session's status to `closed`, stores the notes and the time,
  and returns to the net's page.
- The **next session of the same net**, on both the participant and the net
  control screens, shows a "Last time (date)" card with the most recent
  closed session's notes. If those notes are empty, no card appears.
- A closed session opens read-only. The aim box, Rotate and Snap back still
  work, because pointing isn't recording. Adding and editing are off. A
  **Reopen** button switches them back on and keeps the notes.
- Closing notes are private, like heard states (decision 40). They are not in
  exports. They are in backups, because a backup copies the whole database.
- Nets page and net view: closed sessions show their notes' first line.

## Data

Migration `0009_session_close.sql`:

```sql
ALTER TABLE session ADD COLUMN closing_notes TEXT;
ALTER TABLE session ADD COLUMN closed_at TEXT;
```

New repository methods:

- `close_session(session_id, notes)`
- `reopen_session(session_id)`
- `last_closing_notes(net_id, before_session_id)` → `(date, notes) | None`

## Smaller calls (mine, for the owner to check)

- Regulars open sorted by Last check-in. Ties break by callsign.
- "Last time" means the latest *closed* session before this one. Open or
  imported sessions without notes are skipped.
- Read-only when closed, with Reopen, rather than locked forever.

## New acceptance tests (requirements section 7)

- A. Typing a callsign, grid, alias or heading in Aim at and pressing Enter
  shows its bearing from the user and sends no rotator command.
- B. After A, Ctrl+Enter rotates to the typed target with exactly one command.
- C. Clicking a Regulars row or pressing its Heard button sends no rotator
  command.
- C3. Typing in Aim at narrows both lists and sends no rotator command.
  Tonight sorts by check-in order, callsign, direction and distance.
- C2. Regulars sort by callsign, grid, direction and last check-in. Stations
  with an unknown grid or bearing sort last.
- D. A station added with the I-hear line on session 1 appears under Regulars
  on session 2 of the same net, with its grid and bearing.
- E. Adding a station whose name or grid differs from its record leaves the
  record unchanged unless "Update station record" is chosen.
- F. Closing a session with notes stores them. The next session of that net
  shows them under "Last time". A different net does not.
- G. A closed session refuses adds until reopened. Rotate still works.
- H. Closing notes never appear in text, CSV or JSON exports.
- I. All of the above pass with networking disabled.

## Not in scope

- Web check-ins, shared live sessions, maps (backlog).
- Any automatic rotation when a station is heard or announced.
- Changing the net control screen beyond showing the "Last time" card.

## Docs to update when built

- `docs/requirements.md` 4.4: add the aim box, I-hear line, Regulars and Close.
  Section 7: add tests A–I.
- `docs/decisions.md`: one entry for the four smaller calls above.
- `docs/user-guide.md`: "Following a net as a participant".
