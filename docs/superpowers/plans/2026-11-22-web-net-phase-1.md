# Web net, phase 1: the website — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A PHP and MySQL website at `net.n2lqh.com` where any net has a live page: a door that asks for a callsign, a live check-in list with Speaking now and Next, an NJ2US-style map, logging with or without net control, net control's notice, topic and bouncing, and the site owner's Manage nets.

**Architecture:** Plain PHP 8.1 (no framework, no Composer) under `web/`. `web/public/` is the subdomain's document root, with one front controller; logic lives in `web/src/` (one class per concern, all static functions over a `PDO`), above the document root. Pages poll a JSON API every 3 s with a version number, so an unchanged net costs one indexed query. Tests run in Docker (PHP 8.1 CLI and MariaDB 10.6), so nothing is installed on Windows.

**Tech Stack:** PHP 8.1, PDO MySQL, MariaDB 10.6 / MySQL 5.7+, vanilla JavaScript, Leaflet 1.9.4 (bundled), OpenStreetMap tiles, Docker Compose for tests, pytest for the shared Python cases.

**Spec:** `docs/superpowers/specs/2026-11-22-web-net-design.md` (phase 1 only; phases 2 and 3 get their own plans).

## Global Constraints

- No rotator code, no Beam Navigator changes in this phase except the shared-cases pytest (Task 1).
- Plain PHP 8.1+, MySQL 5.7+ / MariaDB 10.3+, no framework, no Composer, no long-running process, no WebSockets. Deploy = upload files and open the install page.
- Never hard-code a domain: every link is built from the request's host and base path.
- Honour system: callsign is identity; the only password is the site owner's.
- Every callsign typed anywhere must pass `Callsign::isCallsign`; every grid must pass `Grid::isGrid` (4 or 6 characters) or be blank.
- Pins sit at grid centres only.
- Topic answers go only to net control and the site owner.
- `web/config.php` (database settings, owner password hash) is never committed; only `web/config.example.php` is.
- SQL only through prepared statements; HTML output only through `h()` (htmlspecialchars); JavaScript writes text with `textContent`, never `innerHTML` with data.
- Every write records a `changes` row (who, what, when).
- Leaflet's licence file ships beside it; the map shows "© OpenStreetMap contributors".
- Times stored in UTC; a net's day is computed in its own IANA time zone.

## Owner approvals needed before Task 1

1. Pull the Docker images `php:8.1-cli` and `mariadb:10.6` (test only; nothing installed on Windows).
2. Add Leaflet 1.9.4 (BSD-2-Clause) as a bundled file under `web/public/assets/leaflet/`.

## Review Focus

1. Two browsers tapping **Speaking now** within the same second with no logger: the last write wins, both pages converge on it within one poll, and two `changes` rows exist. Test in Task 5.
2. A net whose time zone puts "today" on a different date from UTC (e.g. 21:30 Friday in New York): the session opens on Friday's date, not Saturday's. Test in Task 4.
3. Lowercase or padded callsigns (` k3wwt `) at the door and in check-ins: treated as `K3WWT`; `K3WWT/P` counts as net control `K3WWT`. Test in Task 4.
4. A bounced person who keeps polling: polls return the "removed" state and every write is refused with 403, even after reloading the door with the same browser. Test in Task 5.
5. The logger closes their tab mid-net: after 60 s with no poll, participants' additions go straight onto the list again. Test in Task 5.

---

### Task 1: Test harness, and callsign and grid rules in PHP

**Files:**
- Create: `web/tests/compose.yml`, `web/tests/Dockerfile`, `web/tests/run.php`, `web/tests/TestCase.php`
- Create: `web/src/Callsign.php`, `web/src/Grid.php`, `web/tests/CallsignGridTest.php`
- Create: `tests/shared/callsign_grid_cases.json`, `tests/unit/test_shared_cases.py`
- Modify: `.gitignore` (add `web/config.php`)

**Interfaces — Produces:**
- `Callsign::normalize(string $t): string` (trim, uppercase); `Callsign::isCallsign(string $t): bool`; `Callsign::base(string $t): string` (throws `InvalidArgumentException` when not a callsign). Same regex and rules as `src/beam_navigator/core/callsign.py` (a prefix must contain a letter; a grid is never a callsign).
- `Grid::isGrid(string $t): bool` (4 or 6 characters, as `core/maidenhead.py`); `Grid::center(string $g): array{float, float}` (lat, lon of the cell centre, as `core/maidenhead.py`).
- Test runner: `docker compose -f web/tests/compose.yml run --rm php` runs every `web/tests/*Test.php`; each file defines `test_*` functions; helpers `assert_same($expected, $actual, string $msg = '')`, `assert_true(bool $v, string $msg = '')`, `assert_throws(string $class, callable $fn)`. Exit code 1 on any failure; prints `N passed, M failed`.

- [ ] **Step 1:** Write `tests/shared/callsign_grid_cases.json` with keys `callsigns_valid`, `callsigns_invalid`, `grids_valid`, `grids_invalid`, `centers` (list of `[grid, lat, lon]`). Valid callsigns include `N2LQH`, `K3WWT`, `WA3EBS`, `KC3BVL`, `2E0ABC`, `VE3/N2LQH`, `K3WWT/P`, lowercase `n2lqh`. Invalid include `BOB`, `test123`, `123A`, `FM29`, `FM29pt`, empty string. Grids valid: `FM29`, `FM29pt`, `fm29PT`; invalid: `FM2`, `FM29p`, `ZZ99`, `FM29ptx`. Centres: take the values from `beam_navigator.core.maidenhead` for `FM29`, `FM29pt`, `FN20ok`, `JO01`.
- [ ] **Step 2:** Write `tests/unit/test_shared_cases.py` asserting Python's `is_callsign`, `is_grid` and the grid centre function agree with every case (centres to 1e-6). Run `uv run pytest tests/unit/test_shared_cases.py -v`. Expected: PASS (the cases come from Python).
- [ ] **Step 3:** Write `web/tests/CallsignGridTest.php` reading the same JSON (mounted at `/repo/tests/shared/`) and asserting the PHP functions agree with every case; plus `base('VE3/N2LQH/P') === 'N2LQH'` and `normalize(' k3wwt ') === 'K3WWT'`.
- [ ] **Step 4:** Write the harness: `Dockerfile` is `FROM php:8.1-cli` plus `docker-php-ext-install pdo_mysql`; `compose.yml` has `db` (`mariadb:10.6`, root password `test`, healthcheck) and `php` (built from the Dockerfile, mounts `web/` at `/app` and the repo's `tests/shared` at `/repo/tests/shared`, depends on a healthy `db`, command `php /app/tests/run.php`). Run it. Expected: FAIL, `Callsign` not found.
- [ ] **Step 5:** Implement `Callsign.php` and `Grid.php`. Run the harness. Expected: all pass.
- [ ] **Step 6:** Commit `feat(web): test harness; callsign and grid rules shared with Beam Navigator`.

### Task 2: Database, config and migrations

**Files:**
- Create: `web/src/Db.php`, `web/src/Config.php`, `web/src/migrations/001_init.sql`, `web/config.example.php`, `web/tests/DbTest.php`

**Interfaces — Produces:**
- `TestCase::db(): PDO` (in `web/tests/TestCase.php`): a fresh, empty, migrated database per test file.
- `Config::load(string $path): array` (returns `['db' => [host, name, user, pass], 'owner_hash' => string]`); throws `RuntimeException` when missing.
- `Db::connect(array $db): PDO` (exceptions on, UTF8MB4, UTC session time zone); `Db::migrate(PDO $pdo): int` applies `migrations/NNN_*.sql` above `schema_version`, returns the version reached. `Db::now(): string` (UTC `Y-m-d H:i:s`).
- Tables in `001_init.sql` (InnoDB, utf8mb4):
  - `schema_version(version INT)`
  - `nets(id, slug UNIQUE, name, band, frequency_mhz DECIMAL(10,4) NULL, channel, mode, weekday TINYINT NULL (0=Mon), start_time CHAR(5) NULL, timezone, ncs_call, ncs_grid, notice TEXT NULL, notice_until DATE NULL, topic VARCHAR(200) NULL, archived TINYINT, created_by, created_at, last_used DATETIME NULL)`
  - `sessions(id, net_id, date DATE, ncs_call, substitute_call NULL, logger_token NULL, speaking_id NULL, status ENUM('open','closed'), version INT, updated_at, UNIQUE(net_id, date))`
  - `people(id, session_id, token CHAR(32), callsign, mode ENUM('checkin','view'), answer VARCHAR(200) NULL, last_seen, UNIQUE(session_id, token))`
  - `checkins(id, session_id, callsign, name NULL, grid NULL, position INT, state ENUM('suggested','in','out','removed'), how ENUM('self','logger','participant','suggestion'), added_by, created_at, updated_at, UNIQUE(session_id, callsign))`
  - `bans(id, net_id, callsign, token, by_call, at)`
  - `sub_requests(id, session_id, token, callsign, state ENUM('waiting','approved','denied'), at)`
  - `changes(id, session_id NULL, net_id NULL, token, callsign, action, detail JSON, undone TINYINT, at)` with an index on `(token, at)`.

- [ ] **Step 1:** `DbTest.php`: `test_migrate_from_empty_reaches_1`, `test_migrate_twice_is_a_no_op`, `test_config_missing_throws`. Run. Expected: FAIL.
- [ ] **Step 2:** Implement; `TestCase::db()` creates database `t_<random>`, migrates, and drops it at the end of the run. Run. Expected: pass.
- [ ] **Step 3:** Commit `feat(web): database, config and migrations`.

### Task 3: Nets

**Files:** Create `web/src/Nets.php`, `web/tests/NetsTest.php`

**Interfaces — Consumes:** `Callsign`, `Grid`, `Db`. **Produces:**
- `Nets::create(PDO $db, array $f, string $byCall): int`. Fields `name` (required), `band`, `frequency_mhz`, `channel`, `mode`, `weekday`, `start_time` (`HH:MM`), `timezone` (valid IANA, required), `ncs_call` (valid callsign or blank), `ncs_grid` (valid grid or blank). Throws `InvalidArgumentException` with a plain message naming the field.
- `Nets::slug(PDO $db, string $name): string`: lowercase, runs of non-alphanumerics become `-`, trimmed, at most 60 characters, `-2`, `-3`… when taken. Set once at creation; renaming never changes it.
- `Nets::update(PDO, int $id, array $f, string $byCall): void`; `archive`, `restore`, `delete` (`delete` removes the net and its sessions, check-ins, people and bans).
- `Nets::bySlug(PDO, string): ?array`; `Nets::listPublic(PDO): array` (not archived); `Nets::listForOwner(PDO): array` (all, ordered `last_used IS NULL DESC, last_used ASC`, each with `duplicate_of` ids).
- `Nets::duplicates(array $nets): array<int, int[]>`: two nets are likely duplicates when their names, lowercased with non-alphanumerics removed, are within Levenshtein distance 3, and they share a frequency (within 0.0005 MHz) or a channel, or both have neither.
- `Nets::setNotice(PDO, int, ?string $text, ?string $until)`, `Nets::setTopic(PDO, int, ?string)`.

- [ ] **Step 1:** Tests: `test_create_needs_name_and_timezone`, `test_bad_ncs_call_refused` (`BOB`), `test_slug_from_name` (`"DVFRC Friday 50 MHz Net"` becomes `dvfrc-friday-50-mhz-net`), `test_slug_unique_suffix`, `test_rename_keeps_slug`, `test_archived_hidden_from_public`, `test_owner_list_oldest_used_first_never_used_top`, `test_duplicates_flagged` (`"DVFRC Friday 50 MHz"` and `"DVFRC Fridy 50 MHz"` on 50.125 are flagged; same name on 144.200 is not), `test_delete_removes_sessions`. Run. Expected: FAIL.
- [ ] **Step 2:** Implement. Run. Expected: pass.
- [ ] **Step 3:** Commit `feat(web): nets — add, edit, archive, delete, slugs, duplicates`.

### Task 4: Sessions, the door, presence, powers and substitutes

**Files:** Create `web/src/Sessions.php`, `web/src/Door.php`, `web/src/Powers.php`, `web/tests/SessionsDoorTest.php`

**Interfaces — Consumes:** `Nets`, `Callsign`, `Grid`. **Produces:**
- `Sessions::today(array $net, DateTimeImmutable $nowUtc): string` (the date in the net's time zone).
- `Sessions::current(PDO, array $net, DateTimeImmutable $nowUtc, bool $start = false): ?array`. Returns today's session, creating it when today is the net's weekday, when `$start` is true, or when the net has no weekday. It copies `ncs_call` from the net and sets `nets.last_used`. A session open with `updated_at` more than 6 hours ago is closed first. Returns `null` when nothing is scheduled today and `$start` is false.
- `Sessions::bump(PDO, int $sid): int` (version + 1, `updated_at` = now; every state change calls it); `Sessions::close(PDO, int $sid)`.
- `Door::enter(PDO, array $session, string $token, string $callsign, string $mode, ?string $grid, ?string $answer, bool $claimSubstitute, DateTimeImmutable $now): array`, returning `['person' => row, 'role' => string, 'substitute' => 'none'|'granted'|'waiting']`.
  - Refuses an invalid callsign, and a banned token or callsign for the net (`DomainException`, message "You've been removed from this net by net control.").
  - `mode` is `checkin` or `view`; in this task both only record the person. Task 5 makes `checkin` also add the check-in. Entering again with the same token updates the row.
- `Door::seen(PDO, int $personId, DateTimeImmutable $now)`: writes `last_seen` only when it is 15 s or more old.
- `Powers::role(PDO, array $session, array $person, bool $owner): string`, one of `owner`, `ncs`, `logger`, `participant`, `viewer`. A person is `ncs` when `Callsign::base` of their call equals the base of the session's `ncs_call` or `substitute_call`.
- `Powers::online(array $person, DateTimeImmutable $now): bool` (`last_seen` within 20 s).
- `Powers::loggerActive(PDO, array $session, DateTimeImmutable $now): bool` (the logger's person row was seen within 60 s).
- Substitute claim: if a person whose role is `ncs` is online, a `sub_requests` row is created as `waiting`; otherwise `substitute_call` is set at once. `Door::decideSubstitute(PDO, int $requestId, bool $approve, array $byPerson)` (only `ncs` or `owner`).

- [ ] **Step 1:** Tests:
  - `test_today_uses_net_timezone` (2026-11-28 02:30 UTC is Friday 2026-11-27 in `America/New_York`)
  - `test_session_opens_on_scheduled_day_only`
  - `test_start_now_opens_unscheduled`
  - `test_stale_session_closes_after_6h`
  - `test_door_refuses_bad_callsign`
  - `test_door_normalizes_call` (` k3wwt ` becomes `K3WWT`)
  - `test_ncs_by_call_with_suffix` (`K3WWT/P` is `ncs`)
  - `test_view_only_has_no_checkin`
  - `test_banned_token_refused`
  - `test_substitute_granted_when_ncs_offline`
  - `test_substitute_waits_when_ncs_online_then_approved`
  - `test_only_ncs_decides_substitute`

  Run. Expected: FAIL.
- [ ] **Step 2:** Implement. Run. Expected: pass.
- [ ] **Step 3:** Commit `feat(web): sessions, the door, presence and substitutes`.

### Task 5: Check-ins, logging, Speaking/Next, undo, bounce, rate limit

**Files:** Create `web/src/CheckIns.php`, `web/src/Logging.php`, `web/src/Bans.php`, `web/src/RateLimit.php`, `web/tests/CheckInsLoggingTest.php`

**Interfaces — Consumes:** `Sessions::bump`, `Powers`. **Produces:** every function takes `(PDO $db, array $session, array $actor, string $role, …)` and refuses a disallowed action with `DomainException` (shown as 403), then records `changes` and calls `bump`.
- `CheckIns::add(..., string $call, ?string $grid, ?string $name, string $how): array`:
  - The state is `suggested` when a logger is active and the actor isn't the logger, net control or owner; otherwise `in`.
  - An existing call is updated, and an `out` or `removed` one comes back to `in` or `suggested`. A blank name is filled from the newest non-blank name for that call in any session.
  - Position goes to the end.
- `CheckIns::accept`, `dismiss` (logger, net control or owner only); `edit(id, grid, name)`; `move(id, position)`; `out(id)`; `remove(id)`.
  - When a logger is active, these need the logger, net control or owner.
  - When no logger is active, any participant may use them except `move` (my call: order belongs to whoever is in charge).
- `Logging::speaking(..., ?int $checkinId)`: same permission as `edit`; the last write wins. `Logging::next(array $checkins, ?int $speakingId): ?array` is the first `in` check-in after the speaker by position, else null (no wrap-around).
- `Logging::claim` (participant or above, only when no logger is active), `stop` (the logger), `takeOver` (net control or owner). The logger is `sessions.logger_token`.
- `Logging::undo(..., int $changeId)`: reverses the add, edit, out, remove or speaking change recorded in `detail`. Allowed for net control, the logger, or anyone when no logger is active.
- `Bans::bounce(PDO $db, array $session, array $actor, string $role, int $personId, bool $undoTheirs)`: logger, net control or owner. Inserts a ban for the person's token and callsign on the net, and when `$undoTheirs` is set, removes check-ins they added this session. `Bans::isBanned(PDO, int $netId, string $token, string $call): bool`.
- `RateLimit::allow(PDO, string $token, DateTimeImmutable $now): bool`: at most 30 `changes` per token in 60 s.
- Modify `Door::enter`: in `checkin` mode it calls `CheckIns::add(..., $callsign, $grid, null, 'self')`.

- [ ] **Step 1:** Tests:
  - `test_no_logger_participant_add_is_in_and_attributed`
  - `test_logger_active_participant_add_is_suggested`
  - `test_self_checkin_with_logger_is_suggested`
  - `test_logger_accepts_suggestion`
  - `test_duplicate_call_updates_not_duplicates`
  - `test_name_filled_from_earlier_session`
  - `test_next_skips_out_and_does_not_wrap`
  - `test_two_speaking_taps_last_wins_both_logged` (Review Focus 1)
  - `test_logger_gone_60s_falls_back_to_everyone` (Review Focus 5)
  - `test_ncs_takes_over_logging`
  - `test_participant_cannot_move_rows`
  - `test_undo_add_and_speaking`
  - `test_bounced_person_writes_refused_and_entries_undone` (Review Focus 4)
  - `test_rate_limit_31st_change_refused`
  - `test_viewer_cannot_write`
  - `test_door_checkin_adds_self_checkin` (marked `how = self`; with a logger active it's `suggested`)

  Run. Expected: FAIL.
- [ ] **Step 2:** Implement. Run. Expected: pass.
- [ ] **Step 3:** Commit `feat(web): check-ins, logging, Speaking and Next, undo, bounce, rate limit`.

### Task 6: HTTP layer — routing, cookies, the JSON API

**Files:** Create `web/public/index.php`, `web/public/.htaccess`, `web/src/App.php`, `web/src/Api.php`, `web/src/State.php`, `web/tests/ApiTest.php`

**Interfaces — Consumes:** Tasks 2–5. **Produces:**
- Routes:
  - `/` home
  - `/net/{slug}` or `?net={slug}`: the door, or the net page once entered
  - `/net/{slug}/past/{date}`: a read-only past session
  - `/add`: add a net
  - `/net/{slug}/edit`: net control or owner
  - `/admin`: owner sign-in and Manage nets
  - `/api/{slug}/state?v=N`
  - `POST /api/{slug}/{action}`
- `.htaccess` rewrites everything that isn't a file to `index.php`. `index.php` also works as the router for `php -S`.
- `App::base(): string` is the scheme, host and base path, taken from the request (never configured).
- Cookie `bn_token` (32 hex from `random_bytes`, HttpOnly, SameSite=Lax, Secure on HTTPS), set at the door.
- Every POST needs the header `X-BN: 1` and a JSON body, and is refused with 400 otherwise. Errors come back as `{"error": "<plain message>"}` with 400, 403 or 429.
- `State::build(PDO, array $net, array $session, ?array $person, string $role, DateTimeImmutable $now): array` returns:
  - `v`, `net{name, band, frequency_mhz, channel, mode, ncs_call, ncs_grid, notice}` (`notice` is null once `notice_until` is before today in the net's time zone), `session{date, status, substitute_call}`
  - `logging{call|null, active}`, `speaking`, `next`
  - `checkins[{id, call, name, grid, lat, lon, state, how, added_by, position}]`. Suggestions are included only for logger, net control or owner. `lat`/`lon` are null without a grid.
  - `watching[{call}]`: people in `view` mode seen within 60 s, shown as not checked in.
  - `me{call, role, removed}`, `sub_requests` (net control only), `answers[{call, answer}]` (net control and owner only).
- `GET state?v=N`: when the session's version equals N, the reply is `{"v": N}` after reading only `sessions.version` (plus `Door::seen`).
- POST actions map one-to-one onto Task 4–5 functions: `enter`, `add`, `accept`, `dismiss`, `edit`, `move`, `out`, `remove`, `speaking`, `claim`, `stop`, `takeover`, `undo`, `bounce`, `substitute`, `notice`, `topic`, `start`, `close`.

- [ ] **Step 1:** Tests, calling `Api::handle(string $method, string $path, array $headers, array $cookies, string $body): array{status, headers, body}` directly:
  - `test_state_unchanged_returns_only_version`
  - `test_post_without_header_400`
  - `test_answers_only_for_ncs` (a participant's state has no `answers` key)
  - `test_watchers_listed_as_not_checked_in`
  - `test_removed_person_state_says_removed`
  - `test_unknown_slug_404`
  - `test_notice_hidden_after_end_date`
  - `test_query_fallback_route`
  - `test_base_from_host` (`Host: net.example.org` makes links start `https://net.example.org/`)

  Run. Expected: FAIL.
- [ ] **Step 2:** Implement. Run. Expected: pass.
- [ ] **Step 3:** Commit `feat(web): routing, cookies and the JSON API`.

### Task 7: Pages, the map and the live script

**Files:**
- Create: `web/src/Views.php` (page templates, `h()`), `web/public/assets/net.css`, `web/public/assets/net.js`, `web/public/assets/leaflet/` (Leaflet 1.9.4 `leaflet.js`, `leaflet.css`, `images/`, `LICENSE`)
- Create: `web/tests/ViewsTest.php`
- Modify: `web/tests/compose.yml` (add a `web` service: `php -S 0.0.0.0:8080 public/index.php` on port 8080, for browser checks)

**Interfaces — Consumes:** Task 6 routes and `State`. **Produces:** the pages below.
- **Home:** nets live now, then today's nets, then all, with a search box and an **Add a net** link.
- **Door:** the spec's sketch. Callsign (remembered in `localStorage`), grid (check-in only), topic question with an optional answer, **Check in to the net** and **View only**, and a small **I'm standing in as net control** checkbox. Shows the notice, and `Nothing scheduled today` with a **Start a net now** button when there's no session.
- **Net page:**
  - Map on the left, panel on the right (NJ2US style: dark, yellow callsign labels with a black halo); below 800 px the panel goes under the map.
  - Map: Leaflet with OpenStreetMap tiles and attribution. A permanent label at each check-in's grid centre. Net control gets a distinct marker. Speaking is highlighted green, Next amber. Labels at the same grid are offset so none overlap exactly.
  - Panel:
    - net name, net control and notice
    - the logging banner ("No one is logging tonight. Tap I'll log to take charge." or "<call> is logging")
    - **Speaking now** and **Next**
    - the check-in list with a **Net order / Recent Check-Ins** switch
    - **Watching (not checked in)**
    - the add row (callsign, grid, name)
  - Tools for the logger, net control and owner: per-row tap for Speaking now, out, remove, move up and down, edit, and an undo for each recent change; the **Suggestions** queue (accept, dismiss); **Bounce** on a person; **I'll log**, **Stop logging** and **Take over logging**.
  - Net control only: **Topic answers** (callsign, answer), **Notice** and **Topic** editors, and substitute requests (approve, deny).
  - A removed person sees only "You've been removed from this net by net control."
  - Polling: `net.js` fetches `state?v=N` every 3 s (every 15 s while the tab is hidden) and redraws only when `v` changes. It does a full fetch every 30 s for the watching list. On a failed fetch it shows "Connection lost, retrying" and keeps the last list greyed out.
- **Add a net / Edit net:** the `Nets::create` fields, with the time zone defaulted from the browser (`Intl.DateTimeFormat().resolvedOptions().timeZone`). The added-by callsign comes from the door's remembered callsign, or a callsign box.
- **Past session:** a read-only list and map.

- [ ] **Step 1:** `ViewsTest.php` (server-rendered HTML):
  - `test_door_has_callsign_and_both_buttons`
  - `test_notice_and_topic_on_door`
  - `test_html_escaped` (a net named `<b>x</b>` renders escaped)
  - `test_osm_attribution_on_net_page`

  Run. Expected: FAIL.
- [ ] **Step 2:** Implement the views, CSS and JS. Run. Expected: pass.
- [ ] **Step 3:** Browser check with `docker compose -f web/tests/compose.yml up web` and Playwright at 1280 px and 390 px, using two browsers (two Playwright contexts):
  - A enters as `N2LQH` and checks in `FM29pt`; B enters as `K3WWT` and gets the net control tools.
  - B sets a topic; A answers it; only B sees the answer.
  - A adds `WA3EBS FM29` (no logger, so it appears at once in both browsers, attributed to N2LQH).
  - A taps Speaking now on `WA3EBS`; both browsers show it within 5 s, and Next updates.
  - B presses I'll log; A's next addition becomes a suggestion; B accepts it.
  - B bounces A; A's page shows the removed message.
  - At 390 px the panel sits below the map with no sideways scroll.

  Save screenshots to `.playwright-mcp/`.
- [ ] **Step 4:** Commit `feat(web): door, net page, map and live updates`.

### Task 8: Site owner, install page and documentation

**Files:**
- Create: `web/src/Owner.php`, `web/public/install.php`, `web/README.md`, `web/tests/OwnerInstallTest.php`
- Modify: `docs/requirements.md` (section 7: new subsection "Web net" with tests 48–59 below), `docs/decisions.md` (the next free decision number), `docs/user-guide.md` (a "Web net" section), `docs/backlog.md` (mark B5's web check-in entry as phase 1 built, phases 2–3 planned)

**Interfaces — Produces:**
- `Owner::signIn(string $password, string $hash): bool` uses `password_verify`, with the PHP session marked as owner. Five failed tries from one IP in 15 minutes lock sign-in for 15 minutes (counted in `changes` with action `owner_fail`).
- `/admin` is the **Manage nets** screen. It uses `Nets::listForOwner` and shows each net's name, net control, last used ("never" when null), whether it's archived, and a "possible duplicate of …" note. Actions are edit, archive, restore, and delete (with a confirm page that names the net and its number of sessions).
- `install.php`:
  - When `../config.php` exists, it replies "Already installed" and changes nothing.
  - Otherwise it shows a form for database host, name, user and password and the owner password (twice, at least 12 characters). It tests the connection, writes `../config.php` with `password_hash`, runs `Db::migrate`, then links to `/admin`.
- `web/README.md`: a cPanel deploy for `net.n2lqh.com`:
  - create the subdomain with its document root set to `.../web/public`;
  - create the MySQL database and user;
  - upload `web/` except `tests/`;
  - open `/install.php`;
  - point another domain at it (a cPanel alias or addon domain with the same document root);
  - check the PHP version is 8.1 or later.

- [ ] **Step 1:** Tests:
  - `test_install_refuses_when_config_exists`
  - `test_install_writes_hash_not_password` (the written config contains no plain password for the owner)
  - `test_owner_wrong_password_locks_after_5`
  - `test_delete_needs_owner`
  - `test_ncs_can_archive_own_net_not_delete`

  Run. Expected: FAIL.
- [ ] **Step 2:** Implement. Run. Expected: pass.
- [ ] **Step 3:** Write the documentation. The acceptance tests:
  - **48.** A net page can't be entered, even to view, without a valid callsign; `BOB` is refused.
  - **49.** A viewer is listed to everyone as watching, not checked in, and has no pin.
  - **50.** With no one logging, a participant's check-in shows for everyone within 5 s, marked with who added it, and any participant can undo it.
  - **51.** While someone is logging, a participant's addition or a self check-in waits in Suggestions until the logger, or net control, accepts it.
  - **52.** Speaking now shows for everyone within 5 s; Next is the next checked-in station in net order.
  - **53.** When the logger's page has been gone for 60 s, the net falls back to everyone editing.
  - **54.** Entering with the net's net control callsign, with or without a suffix, gives the net control tools; topic answers are visible only to net control and the site owner.
  - **55.** A substitute claim takes effect at once when net control isn't on the page, and waits for net control's approval when they are.
  - **56.** A bounced person can change nothing on that net, from that browser or that callsign, and their entries can be undone.
  - **57.** A net added by anyone opens on its scheduled day in its own time zone, showing the net's saved net control, with no setup by net control.
  - **58.** Pins sit at the centre of the check-in's grid square; a check-in without a grid has no pin.
  - **59.** Manage nets lists never-used and least recently used nets first, flags likely duplicates, archives without losing history, and deletes only for the signed-in site owner after a confirmation. The database and owner passwords are never in the repository, and the install page refuses to run twice.
- [ ] **Step 4:** Run the whole PHP suite, then `uv run pytest -q` and `uv run ruff check .`. Expected: all pass.
- [ ] **Step 5:** Commit `feat(web): site owner, install page; docs and acceptance tests 48–59 (decision N)`.
