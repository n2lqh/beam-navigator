# Web net: check-in page and live net map — design

Status: draft for the owner's approval (2026-11-22). Backlog item B5 "Web check-in page and live net map".

## Why

On the nets the owner follows, net control logs on a spreadsheet or a pad of paper, so nobody else can see who has checked in, who is speaking, who is next, or where they are. Participants on weak-signal nets need exactly that to turn their beams in time; on repeater and HF nets it still helps people follow along and join in. The owner likes the NJ2US Live Net Map (https://map.nj2us.org/map) for its function, look and feel, NetLogger's shared check-in list and Station Highlighter, and the live path lines of CoreScope and PSKReporter.

Success: on a Friday night net, anyone following opens the net's link, sees the check-ins on a map with who is speaking and who is next, and the list stays right whether or not net control takes part.

## Goals

1. A website, hosted on the owner's shared cPanel hosting (n2lqh.com, web-host.com), where any net can have a live page.
2. Everyone following sees, live: the check-in list, **Speaking now**, **Next**, and each check-in as a pin on a map at its grid.
3. It works with no net control taking part (owner: "if the net control doesn't login and setup the net it is not usable, not sure I like that").
4. Beam Navigator can publish its nets to the site and follow a web net, filling **Speaking** and **Next** on the live net screen.

## Non-goals (for this version)

- Accounts or passwords per callsign. Reserved for a later version, or "if it gets out of control" (owner). The sign-in must be built so a password can be added later without redesign.
- Net audio streaming, weather radar, NWS warnings, chat (NetLogger's AIM), contact logging, ADIF.
- The path line from net control to the speaker: **revision 2**, see below.
- QRZ lookups on the website (QRZ credentials are personal to each Beam Navigator user).
- Pushing Beam Navigator's net control screen log to the web (a later step; this version's logging happens on the web page).

## Anti-goals (a failure even if it works)

- Anything that moves a rotator. Following a web net, publishing, and every web event never send a rotator command (hard rule 1). Turning stays the operator's Rotate press or its hotkey.
- The desktop app needing the network. Beam Navigator stays fully usable offline; the web net is an optional extra like QRZ (hard rule 2).
- A page that is unusable until net control sets it up.
- Showing exact home locations. Pins sit at the centre of the station's grid square, never an address.
- Copying NJ2US's code or design, or scraping or claiming integration with NetLogger. Take the ideas only.
- Database passwords or the site-owner password in the git repository (owner's security rules).

## Constraints

- **Hosting:** shared cPanel hosting with LiteSpeed. PHP and MySQL/MariaDB are certain; Python, SSH, WebSockets and long-running processes are not. So: plain PHP and MySQL, no long-running server process, no WebSockets.
- **Live updates by polling:** pages ask the server "anything new since version N?" about every 3 seconds (NetLogger polls every 20 s). The reply is tiny when nothing changed.
- **Portable:** must run on any ordinary cPanel host if the owner moves. Target PHP 8.1+ and MySQL 5.7+ / MariaDB 10.3+, no framework and no Composer packages on the server, deployable by uploading files and running an install page.
- **Beam Navigator:** no new runtime dependencies (talks to the site with the standard library, like the QRZ client). The site address is a setting, never hard-coded (hard rule 7; n2lqh.com is the owner's site, not a default).
- **Offline-first and truthful:** when the site can't be reached, Beam Navigator says so plainly and carries on; it never shows stale Speaking/Next as current.

## Approaches considered

1. **PHP and MySQL on n2lqh.com — chosen** (owner, 2026-11-22). Runs on the owner's plan today and almost any host later. Cost: the callsign check and grid maths exist twice (Python and PHP); shared test cases keep them in agreement.
2. **Python on n2lqh.com** (cPanel "Setup Python App"). Reuses Beam Navigator's code, but the host's page doesn't say it supports Python apps, and cPanel Python apps are fussier to keep running and to move.
3. **A hosted live-data service (e.g. Supabase) plus pages on the site.** Instant updates, but the data lives in someone else's service, against "host it on n2lqh.com".

## What the owner decided

**Who it's for:** both net control and participants: "both could benefit from being able to know who is speaking, up next and their location on a map and grid."

**Logging without net control:**
- Net controls today use paper or a spreadsheet; a web page is an easier sell than installing a program, so net control logs on the web page.
- If net control won't take part, participants keep the log. One person can press **I'll log** and take charge; others' additions then become suggestions the logger accepts.
- If nobody is logging, everyone can add check-ins and tap **Speaking now** directly; each change shows who made it, the last tap wins, anyone can undo. A banner says "No one is logging tonight. Tap I'll log to take charge." If the logger leaves, it falls back to everyone editing.

**Trust:**
- Honour system. A valid callsign is required to enter, even to view.
- Check-ins must be valid callsigns.
- Net control can bounce a person out of the tool for that net.
- A password tied to a callsign is reserved for a later version.

**The door (entry screen):** callsign, then net control's **topic of the night** question, then **Check in to the net** or **View only**. The topic is a conversation starter (any answer is fine, "a topic of the night"), not a gate. Net control's screen shows the answers by callsign, ready to discuss on the air.

**Net control's extras:** each net control sets their own topic question and a **notice** (e.g. "The net will not be on next Friday due to Thanksgiving").

**Nets exist without net control:** "with the demo data we already know who the net control should be and have the ability to specify a substitute." Anyone can add a net. Net control claims their powers on the honour system by entering with the net's net control callsign or tonight's substitute.

**Tidying:** net control or the site owner can edit, archive or delete nets, guided by last date used and likely typos.

**Substitute net control:** "Anyone but if the sub is online he must approve." Anyone can claim to be tonight's substitute at the door. If the net's net control, or a substitute already named for tonight, is on the net page at that moment, the claim waits until they approve it; if neither is online, it takes effect at once. (Reading of the owner's words, to confirm in review: "the sub" is taken to mean whoever currently holds net control for tonight.)

**Where it lives:** the subdomain `net.n2lqh.com`, "with the ability to point another domain to it". The site never hard-codes its domain.

**Who sees what:** topic answers are seen only by net control. Everyone sees the people watching, listed as **not checked in**. Past nets stay public "for now".

**Size:** about 30 people following one net at once.

**Map:** NJ2US look and feel. Revision 2 adds a toggleable line from net control to the current speaker (CoreScope / PSKReporter style), "a cool effect which could be toggled on or off."

## The design

### People and powers

| Who | How they get it | Can |
|---|---|---|
| Viewer | valid callsign at the door, **View only** | watch the map and list |
| Participant | valid callsign, **Check in** | everything a viewer can; add a check-in they heard and tap Speaking now when no one is logging; suggest them when someone is |
| Logger | a participant presses **I'll log** (one at a time per session) | add, edit, reorder, remove check-ins; set Speaking now; accept or dismiss suggestions; bounce |
| Net control | enters with the net's net control call or tonight's substitute (honour system; a substitute claim needs approval while net control is online, see above) | everything a logger can; take over logging; set the notice and the topic; see topic answers (only net control and the site owner see them); approve a substitute; edit or archive the net |
| Site owner | a real password, set at install (the only password in this version) | everything; edit, archive, restore and permanently delete any net; Manage nets screen |

Every change records who made it (callsign) and when. My call: the logger can also bounce, because on many nights they will be the only one in charge.

### Nets and sessions

- A **net** has: name, band, frequency (MHz) or channel, mode, weekday and start time, time zone (IANA name), net control callsign and grid, notice (with optional end date), topic question, archived flag, created by (callsign), created and last-used dates, and a short permanent address (`/net/dvfrc-friday-50`), made from the name and kept unique.
- A **session** is one night's net: net + date (in the net's time zone), tonight's net control and substitute, the current logger (if any), Speaking now, and status. Field names follow Beam Navigator's `Net` and `Session` models where they overlap.
- My call: a session opens the first time anyone enters the net's page on a scheduled day (or presses **Start a net now** on an unscheduled day), and is closed by net control or the logger, or automatically 6 hours after the last change. Past sessions stay readable.
- **Adding a net:** an **Add a net** form on the site (for net controls who never install Beam Navigator), and **Publish to web** from Beam Navigator's Nets page (below). Both ask for the same fields.

### Check-ins

- Fields: callsign (must pass the callsign check), name (optional), grid (optional, 4 or 6 characters, must pass the grid check), topic answer (optional), order in the list, status (**checked in**, **checked out**), who added it, how (self check-in, added by logger, added by participant, accepted suggestion).
- **Next** is the first checked-in station after the one speaking, in list order. The logger or net control can reorder the list.
- Name: my call, filled from the same callsign's earlier check-ins on the site, if any (no QRZ on the site).
- A station that checks in twice is one check-in; the later details update it.
- With a logger, a participant's addition is a **suggestion** in a queue the logger accepts with one tap or dismisses. A self check-in also goes to that queue.

### Bouncing

- Bouncing removes a person (their callsign and their browser) from the tool for that net. Their page drops to a "You've been removed from this net by net control" notice. Net control or the logger can choose to undo what they added.
- Honest limit: on the honour system a determined person can return under another call or browser. Bouncing stops casual mischief; a callsign password (later version) is the real fix.
- My call: the site also limits how fast one browser can make changes (spam guard), and every bounce is logged.

### Pages

- **Home:** nets with a session live now, then today's nets, then all nets; search by name or frequency.
- **The door:** see the owner's sketch below. The browser remembers the callsign (and the topic answer, per session) so returning is one tap.

```
┌─────────────────────────────────────────┐
│  DVFRC Friday 50 MHz Net                │
│  ⚠ No net next Friday (Thanksgiving)    │  ← notice
│                                         │
│  Your callsign  [ N2LQH        ]        │  ← must be a valid call
│  Your grid      [ FM29pt       ]        │  ← for your pin (check-in only)
│                                         │
│  What is your favourite radio club?     │  ← topic of the night
│  [ Pack Rats                   ]        │
│                                         │
│  [ Check in to the net ]  [ View only ] │
└─────────────────────────────────────────┘
```

- **The net page** (NJ2US style: a large map, a panel on the right, dark theme):
  - Map: callsign labels at each check-in's grid centre, net control's pin marked differently, **Speaking** and **Next** highlighted, crowded labels grouped.
  - Panel: net name, net control, notice, logging banner (who is logging, or "No one is logging tonight"), **Speaking now** and **Next**, the check-in list (newest first as **Recent Check-Ins**, or in net order), the people watching marked **not checked in** (owner), and the participant/logger controls.
  - Time view: **Live**, plus past sessions of this net to replay.
  - Phone width: the panel goes below the map.
- **Net control / logger tools** on the same page: add a check-in (callsign, grid, name), tap a row for Speaking now, reorder, check out, remove, the suggestions queue, topic answers by callsign, bounce, notice and topic editing (net control only), **I'll log** / **Stop logging** / **Take over logging**.
- **Manage nets** (site owner): all nets sorted by last used (oldest first, so dead and never-used nets surface), likely duplicates flagged (near-identical names on the same frequency), edit, archive, restore, delete permanently (with a confirmation).

### Beam Navigator side

1. **Settings → Web net:** the site address (blank by default) and the callsign to use (defaults to the active profile's).
2. **Publish to web** on a net in the Nets page: sends name, schedule, time zone, frequency or channel, mode, band, and net control's call and grid (for their pin) to the site and shows the net's link. The site returns a private edit key, kept in the OS credential store like the QRZ login; publishing again with that key updates the net, and without it is refused (my call, so nobody can overwrite another's net; net control and the site owner still edit on the web). Example nets marked unverified can't be published until checked.
3. **Follow web net** on the live net screen, off by default. The screen gains new **Speaking** and **Next** lines (it has neither today). It polls the site and lights the compass for the speaker (the same "Net control is pointing" display as a typed call). It never rotates.
   - My call, for hardware safety: the speaker shown from the web **never becomes the Rotate target by itself**. The target changes only when the operator taps the speaker (or types a call), so a mistaken or mischievous tap on the website can't line up a beam.
   - My call: web check-ins are shown, not saved. While following, they appear in a **From the web** list; one tap adds one to Tonight. A web grid never replaces a saved station's grid (backlog B5, hard rule 4); a call already in Tonight keeps the operator's details.
   - If the site can't be reached it says "Web net unreachable" and clears Speaking/Next rather than showing stale ones.
4. All network calls use the standard library, with timeouts, and never block the screen.

### Map

- Leaflet (BSD-2) bundled in the site's files rather than loaded from a CDN, with OpenStreetMap tiles and the required "© OpenStreetMap contributors" attribution.
- Grid centres are computed in PHP and in Beam Navigator from the same Maidenhead rules.
- **Revision 2:** **Show path** toggle (off by default) draws a great-circle line from net control to the speaker, moving as each station is called; optionally a faint line from the viewer to the speaker.

### Shared rules in two languages

The callsign check (`core/callsign.py`) and the grid check and grid centre (`core/maidenhead.py`) are ported to PHP. One file of shared test cases (valid and invalid callsigns, grids and their centres) is read by both the pytest suite and the PHP tests, so the two can never disagree.

### Where it lives and how it's deployed

- In this repository under `web/` (GPL-3.0-or-later like the rest).
- Served at `net.n2lqh.com` (a cPanel subdomain). Links are built from the address the page was opened on, so another domain can be pointed at the same site. Short addresses (`/net/<slug>`) use `.htaccess` rewriting; my call: if a host lacks it, `?net=<slug>` works too.
- **Load (owner: about 30 following at once):** a 3-second poll from 30 browsers is about 10 requests a second. My call: each poll first checks a small per-session version number (a file, or one indexed row) and returns at once when nothing changed; the full state is sent only after a change, and hidden browser tabs poll every 15 seconds.
- Database settings and the site-owner password hash live in a config file **outside** the public web folder, created by the install page; only an example config file is committed.
- Deploy: create a MySQL database and user in cPanel, upload `web/` with File Manager or FTP, open the install page once, which creates the tables and asks for the site-owner password, then removes or locks itself.
- The user guide gets a **Web net** section; `docs/decisions.md` gets a decision for this design.

## Phases

1. **The website:** nets, the door, check-ins, live list and map, Speaking/Next, I'll log and everyone-edits, net control tools, topic and notice, bouncing, Manage nets, install page.
2. **Beam Navigator:** Settings → Web net, Publish to web, Follow web net.
3. **Revision 2:** the path line toggle.

Each phase is usable on its own. My call: each phase gets numbered acceptance tests added to `docs/requirements.md` section 7 for the owner's approval, as the definition of done. Running the PHP tests in CI, or installing PHP locally, needs the owner's approval and is asked at planning time.

## Left to the builder

- Table design, the polling API's shape, page styling within "NJ2US-like, dark, map-first".
- How the short address is made from the net name.
- Label grouping on the map.
- PHP test approach (needs PHP available locally to run; installing it needs the owner's approval).
