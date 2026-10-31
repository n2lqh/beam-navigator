# Beam Navigator User Guide

To see every screen with pictures, read the [screen-by-screen walkthrough](https://n2lqh.com/beam-navigator-screen-by-screen/). For the story of how it came to be, read [North From Where? Building Beam Navigator](https://n2lqh.com/projects/beam-navigator/).

## Why I wrote Beam Navigator

As a new weak-signal operator, I struggle to follow the nets. Many times the net controller knows the "regulars" and might be a little lax in telling others where they are pointing the beam. In addition, we need to know our bearing from the net controller.

After the nets, the controllers publish the roll call, and that is helpful for the next time.

Beam Navigator should help attendees and net controllers have a better, more productive net.

— Terry, N2LQH

## Features and benefits

### For attendees

| Feature | What it does for you |
|---|---|
| Bearing and distance from your own station to a callsign with a known location, or any grid, state or heading | You know where to point without working it out. |
| Live net screen: **You → controller** and **Controller → you** (with the sector), calculated directly rather than by adding 180° | You know where the controller must point to hear you, even when the controller doesn't say. |
| Announced sector keys and the **YOUR SECTOR IS UP** banner | You can tell when a call is for your direction, even if you aren't one of the regulars. |
| **Follow Controller** / **Follow Station** and **Snap back to controller** | One press turns the beam back to net control. |
| **Aim at**, **Regulars not heard yet** and **I hear** on the live net screen | Follow a net with no roster: point at anyone you hear, and they are remembered for next time. |
| **Close my session** with notes | Your notes come back at the next session of the same net. |
| **Substitute controller tonight** | Bearings stay right when someone else runs the net. |
| Importing the roll call the controller publishes after a net | The stations and grids are saved, so the next net starts with them known. |
| Nets, past sessions and participants | You see who usually checks in, and from where. |
| Optional QRZ lookups | Names and grids for calls you don't know yet. |

### For net controllers

| Feature | What it does for you |
|---|---|
| A keyboard-first entry line, like a contest logger, that fills in from history and QRZ | Logging is faster. |
| Partial-call matching ranked by attendance, and the duplicate check | Regulars come up after two or three characters, and nobody is logged twice. |
| Info panel with bearing and distance from net control, attendance and notes | You know where to point for each station. |
| Roll-call export (text, CSV, JSON) with bearings labelled "from net control" | A ready-to-publish list that helps everyone next time. |
| Example nets and `*.beamnet.json` sharing | Net details are easy to pass around. |

### For everyone

| Feature | What it does for you |
|---|---|
| The rotator moves only when you press Rotate, Snap back to controller or Stop (or their keys); new rotators start in simulation | No surprises at the tower. |
| Works with no internet connection | Nothing stops when the network does. |
| Backup and restore to one file | Your stations, nets and history are safe and can move to a new computer. |

## What it does and doesn't do

Beam Navigator tells you **which way to point** a directional antenna, and turns the rotator when you ask. Type a callsign, grid square or shortcode, or paste a net roster, and you get true bearings and distances **from your own station**. Net controllers use the same app to log check-ins quickly.

It is for beams on 10 m and up: 10 m, 6 m, 2 m, 222, 432, 902, 1296 MHz and microwave. Weak-signal VHF/UHF nets are the main use. Without a rotator you get everything except the Rotate button.

It does **not** control your radio (no CAT), track satellites or the Moon, control elevation, sync to the cloud, show maps, or move anything by itself. Bearings printed in a roster by a net controller are shown as "Published" for reference; your own heading is always worked out from your station.

## Installing

### Windows

Download `BeamNavigatorSetup.exe` from the release page and run it. No Python is needed, and no administrator password: it installs for your Windows user only.

1. Because the installer is not signed, Windows may say **Windows protected your PC**. Choose **More info**, then **Run anyway**.
2. Accept the licence, choose whether you want a desktop icon, and press **Install**. Leave **Launch Beam Navigator** ticked to start it straight away.
3. From then on, start it from the **Start menu** (type "Beam Navigator") or the desktop icon. The first start takes a few seconds while the program unpacks; wait for the browser rather than starting it again.

Beam Navigator runs quietly in the background and shows itself in your browser; there is no other window. **To stop it, press Quit** at the top right of any page. Closing the browser tab does not stop it. If you start it again while it is already running, your browser simply opens the running copy.

To update, run the new `BeamNavigatorSetup.exe`; it replaces the program (it asks to close a running copy first). To remove it, use **Settings → Apps → Installed apps → Beam Navigator → Uninstall**. Updating and uninstalling never touch your stations, nets and history, which live in your data folder (below).

The release also has the plain program, `BeamNavigator.exe`, for running without installing: put it anywhere and double-click it. It has no Start menu entry.

To give the program options such as `--port` (below), open a Command Prompt in the folder where `BeamNavigator.exe` is (the installer puts it in `%LOCALAPPDATA%\Programs\Beam Navigator`) and type, for example, `BeamNavigator.exe --port 8090`. What the server would have printed goes to `beamnav.log` in the data folder.

To build the program and installer yourself from the project folder (with the app stopped, and Inno Setup 6 installed once with `winget install --id JRSoftware.InnoSetup --exact --scope user`): `uv run python packaging/build_windows.py`. The files appear in `dist`.

### macOS, Linux and Raspberry Pi

1. Install uv from https://docs.astral.sh/uv/.
2. Install Beam Navigator from a copy of the project folder: `uv tool install <path to the beam_navigator folder>`.
3. Run `beamnav-ui`. Your browser opens Beam Navigator. Press Ctrl+C in the terminal to stop it. If the command isn't found, run `uv tool update-shell` and open a new terminal.

### Options

- `--port 8090` runs on another port, for example to run a second copy.
- `--data-dir <folder>` keeps the data somewhere else, for example a test copy.
- `--no-browser` starts without opening a browser tab.

### Where your data lives

Everything is in one database file, `beamnav.db`, in your user data folder:

- Windows: `%LOCALAPPDATA%\beam-navigator`
- macOS: `~/Library/Application Support/beam-navigator`
- Linux and Raspberry Pi: `~/.local/share/beam-navigator`

The Windows program and `beamnav-ui` use the same folder, so they see the same data. Your QRZ login is not in this folder (see QRZ lookups).

## First run: the Welcome wizard

Until a station is active, opening Beam Navigator shows **Welcome to Beam Navigator**, in three steps.

1. **Your station.** Enter your callsign (optional), home grid, units (km or mi) and time zone (for net times, for example `America/New_York`). Press **Next**. If you already have saved stations, they are listed under **Use a saved station**; press **Use** on one instead. If the form was filled from a saved station it says **Editing** and the station's name, with **New station instead** to enter a different one. Moving to a new computer? Use **Restore a backup instead** (see Backup and restore).
2. **Example nets.** Beam Navigator offers example nets from a published Pack Rats schedule. They are marked **Example — unverified** until you check them. Choose **Add examples** or **No thanks**. They include past rosters, so their stations are known from the start.
3. **Next steps.** Links to set up a rotator, add your QRZ login and change keyboard shortcuts. Press **Finish**.

**Skip for now** opens the dashboard for this visit only; the wizard comes back next time until a station is active. What you typed is remembered, even if it was refused (for example a grid that isn't valid).

## The dashboard

Type a target in the big **Target** box and press Enter. You see what it resolved to and where that came from, the **true bearing** (one decimal place), the 16-point compass name, and the **distance** in your units. On bands set to long path (10 m and 6 m by default; Settings → Bands), the long-path bearing and distance are shown too.

### What you can type

Input is not case-sensitive.

| Type | Example | Gives |
|---|---|---|
| Heading | `247`, `247°` | That bearing, no distance. `360` becomes 0. |
| Compass point | `N`, `NE`, `NNW` | The 16-point bearing (N 0, NNE 22.5 … NNW 337.5), no distance. |
| Grid | `FN20`, `FN20ok`, `FM29pt42` | The centre of that grid square. |
| US state, DC or Canadian province | `NJ`, `PA`, `ON` | The centre of the state or province, labelled "centroid". If you set your home state or province in Settings → Station, typing it says you are in it, with nothing to turn to. |
| Alias | `CLUB` | Whatever you set the alias to (Settings → Aliases). |
| Callsign | `W2KV`, `K1ABC/P` | The station's saved location. |

`NE` means Northeast; Nebraska is offered as a one-click alternative. To force a type, start with `st:`, `dir:`, `grid:` or `call:` (for example `st:NE`, `call:W2KV`).

### When a grid isn't known

Beam Navigator never guesses a location. For a callsign with no known grid it shows **Grid needed** with a **Grid** box: type the grid and press **Use grid** to see the bearing. Saving that grid to the station is your choice (**Save grid to …**).

If you have a QRZ login (see QRZ lookups), the call is looked up automatically ("Looking up … on QRZ…"). An exact QRZ location gives the bearing, labelled QRZ; **Save this station** keeps it. If QRZ only knows roughly where the station is (a ZIP code or state), you get **Show approximate bearing** instead. **Look up on QRZ** opens the station's page on QRZ.com in your browser.

### Rotate

With a rotator set up for the selected band (Settings → Rotators), the button shows exactly what will happen, for example "Rotate VHF to 294.6°", with the planned move above it. While the rotator is in simulation the button ends with "(simulated)". Nothing turns until you press it, or press Ctrl+Enter after clicking outside the Target box (keys do nothing while you are typing in a box). **Read position** asks the rotator where it is. **Stop** appears when the rotator supports it; it does not replace the stop on your rotator controller.

## Importing a roster

After a net, the controller usually publishes the roll call. Choose **Import**, paste the list (or **Paste from clipboard**), choose the net and date, and press **Parse**. No net yet? **New net** on the same page creates one.

The review table shows each station with its bearing and distance **from you**. A bearing printed in the roster is shown as **Published** for reference only. You can fix names and grids, leave rows out and pick the net controller. Anything Beam Navigator can't read is kept as an "Unparsed text" row, never thrown away. Press **Save**.

The stations and grids are saved for next time (a roster never overwrites a station you saved yourself), and the original text is kept with the session. If a station's grid came from an earlier roster and this roster gives a different one, the row shows **Replace earlier roster grid …**: tick it to use the new grid, or leave it to keep the old one. Importing the same text again for the same net and date asks whether to **Replace** it or **Keep both**.

## Nets and history

**Nets** lists your nets. Use **Search nets** (name, frequency, band or controller), the star to mark favourites, and **Favourites only** to show just those. Each net has **Edit**, **Duplicate** and **Export**; **New net** adds one, and **Import nets (\*.beamnet.json)** adds nets from a file someone shared. Importing never overwrites a net with the same name.

Open a net to see its next occurrence, default controller, past **Sessions** and **Participants** (callsign, last grid, sessions attended, last seen). **Start session** begins tonight's session; each session has **Open** (the live net screen) and **Net control**.

Example nets are labelled **Example — unverified**. When you have checked one, open **Edit**, tick **I've checked these details** and press **Save**.

## Following a net (live net screen)

Open a session to follow the net.

- **You → controller** is where you point to work net control. **Controller → you** is where the controller must point to hear you, with its sector. It is worked out directly from the controller's location, not by adding 180°.
- When the controller announces a direction ("anyone to the northeast?"), press its number-pad key (8 N, 9 NE, 6 E, 3 SE, 2 S, 1 SW, 4 W, 7 NW) or click it under **Announced sector: press a direction**. If it is your sector, a large **YOUR SECTOR IS UP** banner appears. It never claims the controller can hear you. If the controller's location is unknown, it says "Controller location unknown — can't tell if this call is for you."
- **Follow Controller**, **Follow Station** or **Follow Typed** decides what Rotate points at. **Snap back to controller** (or Home) points at net control and turns the beam in one press.
- **Aim at**: type a callsign, grid, alias or direction (`270`, `W`) and press Enter. The bearing appears and Rotate points there, but nothing turns until you press Rotate (or Ctrl+Enter, which works straight after Enter). While you type, both lists below narrow to matching stations; clear the box to see everyone. A callsign not yet in tonight's list offers **Add to tonight**.
- **I hear**: the same boxes as the net control entry line (Callsign → Name → Grid → QTH → Report → Notes). Type the callsign of a station you hear, Enter to fill its details from what Beam Navigator knows, Enter again to log it. The station is marked Heard and remembered for the next net. **Direction** beside the line shows which way they are as soon as there is a grid; press **Aim** and Rotate points at them (nothing turns until you press Rotate or Ctrl+Enter).
- **Substitute controller tonight**: someone else is running the net? Enter their callsign, grid, or a bearing you measured. It applies to this session only.
- Mark each station **Heard**, **Weak**, **Not heard** or **Via relay**. These are private to you.
- **Tonight** lists the stations in this session; sort it by **Check-in order**, **Callsign**, **Direction** or **Distance**.
- **Regulars not heard yet** lists everyone who has checked in to this net before, with bearing, distance, attendance and last check-in. Sort by **Last check-in**, **Callsign**, **Grid** or **Direction**. Click a regular to point Rotate at them; press **Heard** to add them to tonight.
- **Close my session…** when the net ends. Add **Notes for next time** ("K3WGR weak from 40°, try 30°") and they appear as **Last time** at the top of the next session of this net, on both screens. A closed session is read-only, but you can still aim and rotate; **Reopen** makes it editable again. Closing notes are private: they are never exported.

## Running a net (net control)

Open **Net control** for a session. Type in the entry line, left to right: **Callsign → Name → Grid → QTH → Report → Notes**.

- In Callsign, the first **Enter** fills in Name, Grid and QTH from history (or from QRZ, marked "Filled from QRZ.") and moves to Name; the next **Enter** logs the check-in. In other fields, Enter logs.
- **Tab** and **Shift+Tab** move between fields. **Space** moves on from Callsign and Grid (a space can't be typed there); in the other fields it types a space. **Escape** clears the line.
- While you type a callsign, matching stations are listed, the most regular first; the arrow keys choose one.
- A new station shows "New station — name and grid needed". Logging with blanks is allowed.
- If the name or grid differs from what's saved, choose **This session only** or **Update station record**.
- A callsign already logged offers **Update existing** instead of logging it twice.
- The info panel shows the station's details, bearing and distance from net control, attendance and notes. **Station note** (or Alt+N) adds a note that stays with the station.

**Export** the roll call as **Text**, **CSV** or **JSON**. Bearings are labelled "from net control"; if net control's location isn't known, they are from your own station and say so. Distances use your units. Names and QTHs are tidied into proper case. **Include report** and **Include notes** are on unless you untick them. Your private heard marks are never exported.

## Rotators

Set rotators up in Settings → Rotators. **A new rotator always starts in simulation**: Rotate moves a pretend rotor so you can try everything safely.

- **Adapter:** `simulation` (no hardware), `pstrotator` (PstRotator or PstRotatorAz on Windows, over UDP, usually port 12000; replies come back on the next port up), or `hamlib` (Hamlib's rotctld, over TCP, usually port 4533).
- **Host:** the computer running PstRotator or rotctld; `127.0.0.1` means this computer.
- **Travel preset, Travel start and Travel end:** the rotor's mechanical range. A north-stop rotor turns 0–360°, a south-stop rotor 180–540°, a Yaesu 450° rotor 0–450°. Headings outside the range are refused, never wrapped. With a 450° rotor, Beam Navigator shows which way it plans to go; PstRotatorAz chooses its own path.
- **Offset:** rotor heading = true bearing + offset. If the beam points at true north when the rotor reads 5°, enter 5.
- **Speed** (optional) gives a time estimate. **Bands it serves** makes it the default rotator for those bands. On the live net screen, a net's **Preferred rotator** (set in the net's Edit dialog) is used instead.

Changing a rotator's adapter, host or port puts it back in simulation until it passes again. To go live, press **Test connection**. Only after it passes can you turn on the **Simulation** switch; it then reads **Live: Rotate turns the real antenna**. **Test move in simulation** always uses a pretend rotor.

If the rotator reports no position, Beam Navigator says **"Command sent — position unverified"** rather than claiming the beam got there. Errors and timeouts are reported and never retried by themselves.

On Windows, the first time Beam Navigator listens for PstRotator's replies, Windows Firewall may ask whether to allow it. Allow it. Windows often marks a new home network as **Public**: if Test connection still fails, set your home network to **Private** (Windows Settings → Network & internet → your connection → Network profile type), or allow Beam Navigator on Public networks too. If you pressed Cancel at the prompt, allow it later in Windows Security → Firewall & network protection → Allow an app through firewall.

## QRZ lookups

QRZ lookups are optional; everything else works without them. They need a QRZ.com login with an **XML Data subscription**. Enter your username and password in Settings → QRZ and press **Save**. Your login is kept in your computer's credential store (Windows Credential Manager, macOS Keychain or the Linux keyring), never in Beam Navigator's files or backups. **Test login** checks it; **Clear** removes it.

With **Look up calls automatically when nothing is saved for them** on, a callsign with no saved grid is looked up when you enter it. QRZ only fills blanks: it never overwrites a grid from a roster or one you typed. On screen, QRZ details are marked as from QRZ; once you save the station or log the check-in, they are kept like your other station details.

## Keyboard shortcuts

### Dashboard and live net

| Action | Default key |
|---|---|
| Rotate to the target | Ctrl+Enter |
| Snap back to net control | Home |
| Announce sector N | Numpad 8 |
| Announce sector NE | Numpad 9 |
| Announce sector E | Numpad 6 |
| Announce sector SE | Numpad 3 |
| Announce sector S | Numpad 2 |
| Announce sector SW | Numpad 1 |
| Announce sector W | Numpad 4 |
| Announce sector NW | Numpad 7 |

The sector keys and Snap back work on the live net screen. These keys do nothing while you are typing in a box.

### Net control entry line

| Action | Default key |
|---|---|
| Next field | Tab |
| Previous field | Shift+Tab |
| Log the check-in | Enter |
| Clear the line | Escape |
| Add a station note | Alt+N |
| Next suggestion | ArrowDown |
| Previous suggestion | ArrowUp |

### Changing a key

In Settings → Keys, press **Change** next to an action, then press the new key; Escape cancels. **Reset** puts one back, **Reset all keys** puts them all back. Some keys are refused, with the reason: keys the browser keeps for itself (such as Ctrl+W, Ctrl+N or F5), a key already used in the same group, and keys that would type a character on the entry line. Keys that move the rotator (Rotate and Snap back) need Ctrl or Alt, or a key that never types, such as F9, Home or a number-pad key. Space always moves on from Callsign and Grid. If you change keys while the net control screen is open, reload that page to use them.

## Backup and restore

In Settings → Data:

- **Back up** downloads everything (stations, nets, history, rotators and settings) as one file, named like `beamnav-backup-2026-10-29-1507.db`. Your QRZ login is not in it.
- **Restore from a backup (.db)** checks the file first. If it isn't a Beam Navigator backup, is damaged, or comes from a newer version, it says so and nothing changes. Otherwise it asks you to confirm. Your current data is saved first in the `backups` folder inside your data folder, then the backup replaces it.
- **After a restore, every rotator is in simulation.** Run Test connection and switch Live back on. Reload any other open Beam Navigator pages.

## About and licence

Settings → About shows the version, the copyright, the licence, and links to the screen-by-screen walkthrough and the story behind Beam Navigator. Beam Navigator is free software under the GNU General Public License, version 3 or later, and comes with no warranty. The source code is at https://github.com/n2lqh/beam-navigator. The libraries it is built on are listed, with their own licences, in `THIRD_PARTY_NOTICES.txt`, published with each release.

## Troubleshooting

- **"Port 8080 is already in use…"** Another program is using port 8080 (a running Beam Navigator would simply open in your browser instead). Start Beam Navigator with `--port` and another number (on Windows, from a Command Prompt: `BeamNavigator.exe --port 8090`).
- **Beam Navigator seems to be running but no window is open.** Start it again: your browser opens the running copy. Press **Quit** there to stop it.
- **"Command sent — position unverified"** The rotator doesn't report its position, so Beam Navigator can't confirm where the beam is. Watch your rotator controller.
- **The rotator doesn't respond (PstRotator).** Check PstRotator is running and its UDP port matches the Port in Settings → Rotators, and that Windows Firewall allows Beam Navigator on your home network (see Rotators).
- **"Set up your station first: Settings → Station."** No station is active. Finish the Welcome wizard, or activate a station in Settings → Station.
- **"This is not a Beam Navigator backup."**, **"This backup is damaged and can't be restored."** or **"This backup is from a newer Beam Navigator…"** Nothing was changed. Check you chose the right file, or update Beam Navigator first.
- **"Cannot listen for the reply on UDP port 12001; another program may be using it"** Another program (HRD Logbook, for example) is using PstRotator's reply port. Close it and try again.
- **QRZ messages:**
  - "QRZ can't be reached. Everything else works offline." No connection; try later.
  - "Set up your QRZ login in Settings → QRZ."
  - "Your QRZ login has no XML Data subscription, so QRZ sends limited data."
  - "QRZ refused service for this login; try again tomorrow."
  - "This computer has no credential store, so QRZ lookup is unavailable." Common on a Raspberry Pi with no desktop keyring. Everything else works.
