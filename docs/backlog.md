# Beam Navigator — Backlog

Everything from spec v1.0–v1.3 that is **not** in `requirements.md` v2.0. Nothing here is lost; it is just not first. Every item must still obey the invariants in `requirements.md` section 2, especially: no movement without an explicit press.

Each item lists what it is, why it matters, and what has to exist first.

---

## B1. Weak-signal operating aids

**B1.1 Sweep-order prediction.** Learn each controller's usual order of announced sectors from session history. Show "Likely next: E" and "Your sector is usually 6th." Only after 3+ sessions with that controller; labeled with its basis. *Needs:* announced sectors stored per session (already captured in v2).

**B1.2 Observed best heading.** Operator records "peaked at 42°" per station and band. Show "GC 35° · best 42° (3 obs.)" with median and spread; flag observations far from great-circle as possible scatter paths. Rotate uses great-circle unless the operator picks the learned heading. Local data only, never exported as a universal heading.

**B1.3 Path reliability.** From heard states (captured in v2): "Heard in 4 of 6 sessions on 144 MHz." Sort and filter by it.

**B1.4 Beamwidth awareness.** Per-band −3 dB beamwidth on rotator profiles. Mark stations "in beam" or "edge of beam" at the current heading; group check-ins into beamwidth arcs; offer "rotate to cluster center."

**B1.5 Pre-position suggestions.** Suggest the next likely heading (next sector, next callback, next net). Always a button.

**B1.6 Joining-late panel.** On opening a session well after its start: sectors already announced, expected stations not yet heard, Point at controller button.

**B1.7 Relay records.** Link "relayed by" and "relayed for" in session history. (Heard-via-relay state is in v2.)

**B1.8 Net Night plan.** Chain an evening's nets (Monday Pack Rats: 6 m 19:30, 2 m 20:00, 222 20:30, 432 21:00) with per-net rotator and controller. "Ready for next net" card with a pre-position button. Never opens sessions or rotates on a timer.

**B1.9 Big-heading mode.** Full-screen target, heading and sector banner, readable at 3 m.

**B1.10 Back-channel notes.** Timestamped session notes for coordination from chat ("NC try 40° for me"). No chat integration.

**B1.11 Audible sector cue.** Optional tone when "YOUR SECTOR IS UP" appears. Off by default.

## B2. Net control extras

**B2.1 Sector board.** Check-in counts per sector and when each sector was last called.

**B2.2 Heading-ordered callback queue.** Stations not yet called back, ordered to sweep around from the controller's current heading, honoring the controller's rotor stop.

**B2.3 Needs-repeat flag.** Keeps a partial copy at the top of its sector until cleared.

**B2.4 Club-ready export.** Formatted roster for groups.io, email or a club website.

## B3. Targets and geometry

**B3.1 ARRL/RAC sections** as shortcodes (`SNJ`, `EPA`, `WPA`, `MDC`). Needs a documented boundary source per section; mark approximate ones.

**B3.2 Region bearing span and edge distances.** From simplified boundary polygons: "PA 295° centroid · spans …," nearest and farthest edge. Note when a region is wider than one heading can cover.

**B3.3 Grid fields** (`FN`, `FM`) as regions.

**B3.4 DXCC prefixes** (`JA`, `VK`, `G`) for 10 m and 6 m DX, with short and long path. Needs a licensed prefix table and collision rules for single-letter prefixes versus compass points.

**B3.5 Region reference-point override.** Point `PA` at a chosen city or hilltop instead of the centroid.

**B3.6 Sharable alias files.** Export aliases as JSON for club members, warning if one points at a private QTH.

**B3.7 Rotor calibration helper.** Check the offset against a known beacon or the sun's azimuth.

**B3.8 Beacon list** as pointable targets.

## B4. Integrations

**B4.1 Online callsign lookup.** QRZ XML moved into requirements 4.9 on 2026-10-28 (decision 28). HamQTH remains here: documented API only, opt-in, cached, provenance shown, never treated as the on-air location.

**B4.2 WSJT-X UDP.** Select the station currently being worked as the target.

**B4.3 N1MM Logger+ interoperability.** Exchange target or log data through documented interfaces.

**B4.4 ADIF export.**

**B4.5 Master call list import** for partial-call matching (a Super Check Partial–style file the user supplies).

**B4.6 Grids-per-band tracking** toward VUCC from net history.

**B4.7 Audio callsign extraction.** Feed callsigns and grids recognized from SDR or receiver audio into the same review queue the roster parser uses. Never moves the rotator.

**B4.8 Pre-net reminders.** OS notification before a favorite net with frequency and controller heading.

**B4.9 Offline azimuthal plot.** Polar chart of check-ins centered on the user's QTH. No map tiles needed.

**B4.10 Elevation and AZ/EL rotators,** including a monitor-only mode for rotators shared with satellite or Moon tracking.

## B5. Cloud knowledge sharing and reporting

**Goal:** a shared repository that makes every operator's app smarter, plus reports for nets and clubs. The desktop app stays fully usable offline; the cloud is a sync and publish target, never a dependency.

**Shared knowledge**
- **Community station directory:** grids confirmed from real on-air operation, each with who confirmed it, when, and on which net.
- **Net directory:** schedules, frequencies and default controllers maintained by controllers or club admins.
- **Published rosters:** controllers publish each session after the net.
- **Aggregated path reports (opt-in):** for example, "stations near FM29 hear K3WGR on 2 m in 70% of sessions." Individual heard states and exact coordinates never upload by default.
- **Live shared session** (NetLogger-style): one authoritative session per net and date, controller writes, participants read. Do not scrape or claim integration with NetLogger; compatibility means text/CSV import and export only.

**Reporting**
- Per net: attendance trends, new versus returning stations, activity by band and month.
- Per operator: own attendance, grids heard per band, path reliability over time.
- Per club: summaries for newsletters and meetings, PDF or CSV.
- Activity snapshots: nights with unusually long paths flagged from shared data.

**Architecture**
- Because v2 uses a web UI, the cloud version is the same app deployed on a server with a server database, plus accounts and permissions. Not a rewrite.
- Define provider interfaces in the core: `StationDirectoryProvider`, `NetDirectoryProvider`, `SessionSyncProvider`, `ReportingProvider`. Local SQLite implements them first.
- Sync must handle offline edits, replay, duplicate events, and conflicts with clear provenance.

**Decisions needed before design** (suggested defaults in brackets):
1. Hosting: one central service, per-club self-hosting, or both? [central service]
2. Who can write station grids and net data? [net controllers and club admins]
3. How are callsigns verified? [email plus callsign at first; LoTW certificate later]
4. Rosters and reports public or members-only? [members-only, per-net opt-in to public]

## B6. Distribution

- Signed Windows installer.
- macOS signed and notarized app bundle.
- Raspberry Pi image or one-line install script.
- Auto-backup schedule.
