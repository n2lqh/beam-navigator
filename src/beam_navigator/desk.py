"""What one screen needs: lookups, bands and Rotate, joined from core, store and rotators.

The UI renders what this module returns and calls it on presses; every rule and every
piece of displayed text is decided here, where it can be tested without a browser.
"""

import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from beam_navigator.backup import BackupError, backup_bytes, backup_filename, restore
from beam_navigator.core import keymap as keys
from beam_navigator.core.callsign import normalize_callsign
from beam_navigator.core.geometry import compass_name, is_home, short_path
from beam_navigator.core.keymap import Chord, Keymap
from beam_navigator.core.lookup import lookup
from beam_navigator.core.maidenhead import GridError, grid_center, is_grid
from beam_navigator.core.models import (
    CommandRecord,
    LatLon,
    OperatorProfile,
    RotatorProfile,
    Station,
)
from beam_navigator.core.qrz import Precision, QrzRecord
from beam_navigator.core.regions import load_regions
from beam_navigator.core.targets import Resolution, TargetError, resolve
from beam_navigator.rotators.service import (
    ARRIVED_WITHIN_DEG,
    PositionReading,
    RotateOutcome,
    RotateService,
)
from beam_navigator.store.repositories import (
    AliasRepository,
    BandRepository,
    CommandLog,
    ProfileRepository,
    QrzRepository,
    RotatorRepository,
    SettingRepository,
    StationRepository,
)

NO_PROFILE = "Set up your station first: Settings → Station."
MAX_TARGET_LENGTH = 100
KM_PER_MILE = 1.609344
BAND_SETTING = "dashboard_band"
DEFAULT_BAND = "2 m"
# Without feedback or an estimate, stop watching a move after this long.
WATCH_LIMIT_S = 90.0
WATCH_MARGIN_S = 30.0


@dataclass(frozen=True)
class LookupView:
    title: str | None = None
    bearing_deg: float | None = None
    bearing_text: str | None = None
    distance_text: str | None = None
    reverse_text: str | None = None
    long_path_text: str | None = None
    message: str | None = None
    coarse_note: str | None = None
    alternative: str | None = None
    alternative_label: str | None = None
    needs_grid_for: str | None = None
    can_rotate: bool = False
    error: str | None = None


KEYMAP_SETTING = "keymap"  # JSON {action id: chord}: the operator's changes only
WELCOME_DRAFT = "welcome_draft"  # setting: the first-run wizard's last entries (decision 35)


@dataclass(frozen=True)
class WelcomeDraft:
    """What the operator typed in the wizard's station step."""

    callsign: str = ""
    grid: str = ""
    units: Literal["km", "mi"] = "km"
    timezone: str = "UTC"
    profile_id: int | None = None  # set when the entries came from a saved profile


def _parse_draft(raw: str | None) -> WelcomeDraft | None:
    """None for a missing or unreadable draft, so the next source is used."""
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    texts = [data.get(key, default) for key, default in
             (("callsign", ""), ("grid", ""), ("timezone", "UTC"))]  # fmt: skip
    units = data.get("units", "km")
    profile_id = data.get("profile_id")
    if not all(isinstance(text, str) for text in texts) or units not in ("km", "mi"):
        return None
    if profile_id is not None and (isinstance(profile_id, bool) or not isinstance(profile_id, int)):
        return None
    return WelcomeDraft(texts[0], texts[1], units, texts[2], profile_id)


QRZ_AUTO = "qrz_auto"  # setting: "off" stops automatic QRZ lookups; on by default
# How sure QRZ is of a position (its geoloc field; requirements 4.9, invariant 5).
QRZ_PRECISION_TEXT: dict[Precision, str] = {
    "station": "Location entered by the station on QRZ.",
    "address": "Location from the station's postal address; may not be where they operate.",
    "approximate": "Approximate: QRZ only knows the zip code, state or country.",
    "none": "QRZ has no location for this station.",
}


@dataclass(frozen=True)
class QrzView:
    """A QRZ answer, always labelled as such. A grid is offered only when QRZ's position
    came from the station or its address, never from a zip, state or country centre."""

    callsign: str
    name: str | None
    grid: str | None
    qth: str | None
    source_text: str
    precision: Precision
    precision_text: str
    can_use: bool
    notice: str | None = None


@dataclass(frozen=True)
class Bearing:
    """From the operator's station to a place (invariant 3)."""

    deg: float
    text: str  # "354.2° N"
    distance_km: float
    distance_text: str


def _arc(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _home(profile: OperatorProfile) -> LatLon:
    return profile.latlon if profile.latlon is not None else grid_center(profile.home_grid)


def progress_text(
    outcome: RotateOutcome, elapsed_s: float, reading: PositionReading | None
) -> tuple[str, bool]:
    """Status while a move is watched, and whether to stop watching. reading is None for
    a rotator without feedback (invariant 6: then the position stays unverified)."""
    if not (outcome.sent and outcome.ok) or outcome.measured is not None:
        return outcome.status, True
    seconds = outcome.plan.seconds
    limit = seconds + WATCH_MARGIN_S if seconds else WATCH_LIMIT_S
    target = outcome.plan.target_true
    if reading is None:
        text = f"Command sent — position unverified · {elapsed_s:.0f} s"
        if seconds:
            text += f" of about {seconds:.0f} s"
        return text, elapsed_s >= limit
    if reading.true is None:
        return f"Commanded {target:.1f}° — {reading.message}", True
    commanded = f"Commanded {target:.1f}°, measured {reading.true:.1f}°"
    if _arc(reading.true, target) <= ARRIVED_WITHIN_DEG:
        return commanded, True
    if elapsed_s >= limit:
        return f"{commanded} — not there after {elapsed_s:.0f} s; check the rotator", True
    return f"{commanded} — moving", False


class Desk:
    def __init__(self, conn: sqlite3.Connection, service: RotateService) -> None:
        self.conn = conn
        self.service = service
        self.profiles = ProfileRepository(conn)
        self.aliases = AliasRepository(conn)
        self.stations = StationRepository(conn)
        self.bands = BandRepository(conn)
        self.settings = SettingRepository(conn)
        self.rotator_profiles = RotatorRepository(conn)
        self.command_log = CommandLog(conn)
        self.qrz = QrzRepository(conn)

    # Lookup ---------------------------------------------------------------------------

    def look_up(self, text: str, band: str | None) -> LookupView:
        if len(text) > MAX_TARGET_LENGTH:
            return LookupView(error="That is too long to be a target.")
        try:
            target = resolve(text, self.aliases.get, self.stations.lookup)
        except (TargetError, GridError) as exc:
            return LookupView(error=str(exc))
        return self._view(target, band)

    def look_up_with_grid(self, callsign: str, grid: str, band: str | None) -> LookupView:
        """The inline "Grid needed" field: uses the typed grid, saves nothing."""
        clean = grid.strip()
        if not is_grid(clean):
            return LookupView(error=f"{clean!r} is not a grid square.")
        target = Resolution(
            "callsign",
            normalize_callsign(callsign),
            "typed",
            location=grid_center(clean),
            grid_text=clean,
        )
        return self._view(target, band)

    # QRZ (requirements 4.9): the network call happens elsewhere; these only read and write
    # the cache, so they stay on the event loop with the database (decision 20).

    def qrz_view(self, callsign: str, notice: str | None = None) -> QrzView | None:
        cached = self.qrz.get(callsign)
        if cached is None:
            return None
        record, when = cached
        precision = record.precision
        usable = precision in ("station", "address")
        return QrzView(
            callsign=record.call,
            name=record.name,
            grid=record.grid if usable else None,
            qth=record.qth,
            source_text=f"from QRZ, {when[:10]}",
            precision=precision,
            precision_text=QRZ_PRECISION_TEXT[precision],
            can_use=usable,
            notice=notice,
        )

    def qrz_auto(self, callsign: str) -> bool:
        """Look up on QRZ without a press: on unless switched off, and only when nothing
        useful is stored for the call (owner, 2026-10-29)."""
        if self.settings.get(QRZ_AUTO) == "off" or self.qrz.get(callsign) is not None:
            return False
        record = self.stations.get(normalize_callsign(callsign))
        return record is None or not record.grid

    def qrz_missing(self, callsigns: list[str]) -> list[str]:
        """Of these calls, the ones QRZ could complete: no name or no grid stored, and no
        QRZ answer yet (decision 32). None while automatic lookup is switched off."""
        if self.settings.get(QRZ_AUTO) == "off":
            return []
        wanted = []
        for callsign in callsigns:
            record = self.stations.get(normalize_callsign(callsign))
            incomplete = record is None or not record.name or not record.grid
            if incomplete and self.qrz.get(callsign) is None:
                wanted.append(callsign)
        return wanted

    def qrz_store(self, record: QrzRecord, notice: str | None) -> QrzView:
        self.qrz.save(record, datetime.now(UTC).isoformat(timespec="seconds"))
        view = self.qrz_view(record.call, notice)
        assert view is not None
        return view

    def look_up_with_qrz(self, callsign: str, band: str | None) -> LookupView:
        """The bearing to QRZ's position for the call, labelled QRZ; saves nothing."""
        call = normalize_callsign(callsign)
        cached = self.qrz.get(call)
        if cached is None:
            return LookupView(error=f"No QRZ result for {call} yet.")
        record = cached[0]
        precision = record.precision
        location: LatLon | None = None
        if record.lat is not None and record.lon is not None:
            location = LatLon(record.lat, record.lon)
        elif record.grid is not None:
            location = grid_center(record.grid)
        if precision == "none" or location is None:
            return LookupView(error=QRZ_PRECISION_TEXT["none"])
        source = "QRZ (approximate)" if precision == "approximate" else "QRZ"
        view = self._view(Resolution("callsign", call, source, location=location), band)
        if precision in ("address", "approximate"):
            view = replace(view, coarse_note=QRZ_PRECISION_TEXT[precision])
        return view

    def look_up_or_qrz(self, text: str, band: str | None) -> LookupView:
        """A call with no stored location uses QRZ's, when QRZ has an exact one (owner,
        2026-10-29). A saved or roster grid always wins; an approximate answer never does."""
        view = self.look_up(text, band)
        call = view.needs_grid_for
        if call is None or not self._qrz_usable(call):
            return view
        return self.look_up_with_qrz(call, band)

    def can_save_qrz(self, callsign: str) -> bool:
        record = self.stations.get(normalize_callsign(callsign))
        return self._qrz_usable(callsign) and (record is None or not record.grid)

    def save_qrz_station(self, callsign: str) -> Station:
        """Save this station: QRZ's name, grid and QTH fill the record's blanks only."""
        call = normalize_callsign(callsign)
        cached = self.qrz.get(call)
        if cached is None or not self._qrz_usable(call):
            raise ValueError(f"QRZ has no exact location for {call}.")
        found = cached[0]
        existing = self.stations.get(call)
        if existing is None:
            existing = Station(call, None, None, None, None, "saved", "")
        latlon = existing.latlon
        no_grid = found.grid is None and latlon is None
        if no_grid and found.lat is not None and found.lon is not None:
            latlon = LatLon(found.lat, found.lon)  # QRZ gave a position but no grid
        station = replace(
            existing,
            name=existing.name or found.name,
            grid=existing.grid or found.grid,
            qth=existing.qth or found.qth,
            latlon=latlon,
            source="saved",
        )
        self.stations.save(station)
        saved = self.stations.get(call)
        assert saved is not None
        return saved

    def _qrz_usable(self, callsign: str) -> bool:
        view = self.qrz_view(callsign)
        return view is not None and view.can_use

    def bearing_to(self, grid: str | None) -> Bearing | None:
        """None without an active profile, for a missing or invalid grid, or at home."""
        clean = (grid or "").strip()
        profile = self.profiles.get_active()
        if profile is None or not is_grid(clean):
            return None
        return self.bearing_to_location(grid_center(clean))

    def bearing_to_location(self, location: LatLon) -> Bearing | None:
        profile = self.profiles.get_active()
        if profile is None:
            return None
        home = _home(profile)
        if is_home(home, location):
            return None
        path = short_path(home, location)
        return Bearing(
            path.bearing_deg,
            f"{path.bearing_deg:.1f}° {compass_name(path.bearing_deg)}",
            path.distance_km,
            self._distance(path.distance_km, profile.units),
        )

    def home(self) -> LatLon | None:
        profile = self.profiles.get_active()
        return None if profile is None else _home(profile)

    def save_station_grid(self, callsign: str, grid: str) -> None:
        """Only on the operator's explicit Save (spec 4.1)."""
        clean = grid.strip()
        grid_center(clean)  # raises GridError (a ValueError)
        call = normalize_callsign(callsign)
        existing = self.stations.get(call)
        if existing is None:
            self.stations.save(Station(call, None, clean, None, None, "saved", ""))
        else:
            # Exact coordinates described the old location; drop them with it.
            self.stations.save(replace(existing, grid=clean, latlon=None))

    def _view(self, target: Resolution, band: str | None) -> LookupView:
        profile = self.profiles.get_active()
        if profile is None:
            return LookupView(error=NO_PROFILE)
        band_row = self.bands.get(band) if band else None
        result = lookup(
            _home(profile),
            target,
            home_region=profile.home_region,
            include_long_path=band_row.long_path if band_row else False,
            freq_mhz=band_row.mhz if band_row else None,
        )
        view = LookupView(
            title=f"{target.label} — {target.source}",
            message=result.message,
            coarse_note=result.coarse_note,
            alternative=target.alternative,
            alternative_label=self._alternative_label(target.alternative),
            needs_grid_for=target.label if target.needs_grid else None,
            can_rotate=result.can_rotate,
        )
        if result.bearing_deg is None:
            return view
        units = profile.units
        long_text = None
        if result.long_path is not None:
            long_text = (
                f"Long path {result.long_path.bearing_deg:.1f}° · "
                f"{self._distance(result.long_path.distance_km, units)}"
            )
        return replace(
            view,
            bearing_deg=result.bearing_deg,
            bearing_text=f"{result.bearing_deg:.1f}° {result.compass}",
            distance_text=(
                None if result.distance_km is None else self._distance(result.distance_km, units)
            ),
            reverse_text=(
                None if result.reverse_deg is None else f"Reverse {result.reverse_deg:.1f}°"
            ),
            long_path_text=long_text,
        )

    def own_station(self) -> tuple[LatLon, str] | None:
        """The active profile's location and a label for it, e.g. "N2LQH (FM29pt)"."""
        profile = self.profiles.get_active()
        if profile is None:
            return None
        name = profile.callsign or "your station"
        return _home(profile), f"{name} ({profile.home_grid})"

    # Keys (decision 33) ---------------------------------------------------------------

    def _key_overrides(self) -> tuple[dict[str, str], bool]:
        """The saved changes, and whether the saved text itself was unreadable."""
        try:
            raw = json.loads(self.settings.get(KEYMAP_SETTING) or "{}")
        except json.JSONDecodeError:
            return {}, True
        if not isinstance(raw, dict):
            return {}, True
        kept = {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}
        return kept, len(kept) != len(raw)

    def keymap(self) -> Keymap:
        overrides, _ = self._key_overrides()
        return keys.resolve(overrides)[0]

    def keymap_discarded(self) -> bool:
        overrides, unreadable = self._key_overrides()
        return unreadable or keys.resolve(overrides)[1]

    def set_key(self, action_id: str, chord: Chord) -> None:
        if action_id not in keys.DEFAULTS:
            raise ValueError(f"Unknown action {action_id}.")
        refusal = keys.check(self.keymap(), action_id, chord)
        if refusal is not None:
            raise ValueError(refusal)
        overrides, _ = self._key_overrides()
        overrides.pop(action_id, None)
        if chord != keys.DEFAULTS[action_id]:
            overrides[action_id] = keys.stored(chord)
        if keys.resolve(overrides)[0][action_id] != chord:  # what is saved must be what runs
            raise ValueError(f"{keys.label(chord)} could not be saved; try Reset all keys.")
        self._save_overrides(overrides)

    def reset_key(self, action_id: str | None) -> None:
        """One action back to its default, or every action when action_id is None."""
        overrides, _ = self._key_overrides()
        if action_id is None:
            overrides = {}
        else:
            refusal = keys.check(self.keymap(), action_id, keys.DEFAULTS[action_id])
            if refusal is not None:  # its default is now another action's key
                raise ValueError(refusal)
            overrides.pop(action_id, None)
        self._save_overrides(overrides)

    def _save_overrides(self, overrides: dict[str, str]) -> None:
        order = [action.id for action in keys.ACTIONS]
        ordered = {k: overrides[k] for k in sorted(overrides, key=order.index)}
        self.settings.set(KEYMAP_SETTING, json.dumps(ordered))

    def distance_units(self) -> str:
        profile = self.profiles.get_active()
        return profile.units if profile is not None else "km"

    def distance_text(self, km: float) -> str:
        """In the active profile's units (km without a profile)."""
        profile = self.profiles.get_active()
        return self._distance(km, profile.units if profile is not None else "km")

    @staticmethod
    def _distance(km: float, units: str) -> str:
        value = km / KM_PER_MILE if units == "mi" else km
        return f"{value:,.0f} {units}" if value >= 10 else f"{value:.1f} {units}"

    @staticmethod
    def _alternative_label(alternative: str | None) -> str | None:
        if alternative is None:
            return None
        kind, _, code = alternative.partition(":")
        if kind == "st":
            region = load_regions().get(code)
            if region is not None:
                return f"{region.name}?"
        return f"{alternative}?"

    # First-run wizard (decision 35) ---------------------------------------------------

    def needs_welcome(self) -> bool:
        return self.profiles.get_active() is None

    def welcome_draft(self) -> WelcomeDraft:
        """The operator's last entries, else the latest saved profile, else empty."""
        draft = _parse_draft(self.settings.get(WELCOME_DRAFT))
        if draft is not None:
            return draft
        profiles = self.profiles.list()
        if not profiles:
            return WelcomeDraft()
        latest = max(profiles, key=lambda profile: profile.id or 0)
        return WelcomeDraft(
            latest.callsign or "", latest.home_grid, latest.units, latest.timezone, latest.id
        )

    def keep_welcome_draft(self, draft: WelcomeDraft) -> None:
        fields = {"callsign": draft.callsign, "grid": draft.grid, "units": draft.units,
                  "timezone": draft.timezone, "profile_id": draft.profile_id}  # fmt: skip
        self.settings.set(WELCOME_DRAFT, json.dumps(fields))

    def save_welcome_station(self, draft: WelcomeDraft) -> OperatorProfile:
        """Saves and activates the station; a refused entry stays in the draft."""
        self.keep_welcome_draft(draft)
        zone = draft.timezone.strip() or "UTC"
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"{zone!r} is not a time zone. Use a name such as America/New_York, or UTC."
            ) from exc
        callsign = draft.callsign.strip() or None
        existing = next((p for p in self.profiles.list() if p.id == draft.profile_id), None)
        grid = draft.grid.strip()
        if existing is not None:
            moved = grid.upper() != existing.home_grid.strip().upper()
            # A new grid drops the old exact position and state: bearings must come from
            # where the operator says the station is (invariant 3; final review I1).
            profile = replace(
                existing, callsign=callsign, home_grid=grid, units=draft.units, timezone=zone,
                latlon=None if moved else existing.latlon,
                home_region=None if moved else existing.home_region,
            )  # fmt: skip
        else:
            name = normalize_callsign(callsign) if callsign else "Home"
            if any(p.name.casefold() == name.casefold() for p in self.profiles.list()):
                raise ValueError(  # final review I2: the name is UNIQUE in the database
                    f"A station named {name!r} already exists. Use it above, or enter a"
                    " callsign."
                )
            profile = OperatorProfile(None, name, callsign, grid, None, draft.units, zone,
                                      None, False)  # fmt: skip
        saved = self.profiles.save(profile)
        assert saved.id is not None
        self.use_station(saved.id)
        active = self.profiles.get_active()
        assert active is not None
        return active

    def use_station(self, profile_id: int) -> None:
        self.profiles.activate(profile_id)
        self.settings.set(WELCOME_DRAFT, None)

    # Backup and restore (decision 34) -------------------------------------------------

    def backup(self) -> tuple[str, bytes]:
        return backup_filename(datetime.now()), backup_bytes(self.conn)

    def data_dir(self) -> Path | None:
        for row in self.conn.execute("PRAGMA database_list"):
            if row[1] == "main":
                return Path(row[2]).parent if row[2] else None
        return None

    def restore_backup(self, data: bytes, now: datetime | None = None) -> Path:
        """Replaces all data with the backup; returns the copy kept of the old data.
        Sends no rotator command, and forgets every remembered rotor position."""
        folder = self.data_dir()
        if folder is None:
            raise BackupError("Restore needs a database file.")
        kept = restore(self.conn, data, folder / "backups", now or datetime.now())
        self.service.forget()
        return kept

    # Bands and rotators ---------------------------------------------------------------

    def selected_band(self) -> str | None:
        stored = self.settings.get(BAND_SETTING)
        if stored is not None and self.bands.get(stored) is not None:
            return stored
        names = [band.name for band in self.bands.list()]
        if DEFAULT_BAND in names:
            return DEFAULT_BAND
        return names[0] if names else None

    def select_band(self, name: str) -> None:
        if self.bands.get(name) is None:
            raise ValueError(f"Unknown band {name!r}.")
        self.settings.set(BAND_SETTING, name)

    def rotators(self) -> list[RotatorProfile]:
        return self.rotator_profiles.list()

    def default_rotator(self, band: str | None) -> RotatorProfile | None:
        return self.bands.rotator_for(band) if band else None

    @staticmethod
    def rotate_label(rotator: RotatorProfile, bearing_deg: float) -> str:
        label = f"Rotate {rotator.name} to {bearing_deg:.1f}°"
        return label if rotator.live else f"{label} (simulated)"

    def plan_text(self, rotator_id: int, bearing_deg: float) -> str:
        """The planned move, shown before Rotate (spec 4.7). Sends nothing."""
        plan = self.service.preview(rotator_id, bearing_deg)
        if plan.error is not None:
            return plan.error
        if plan.note is not None:
            return plan.note
        if plan.direction is None:
            if plan.path_verified:
                return "Already there"
            return "Path unverified (position unknown)"
        text = f"{plan.direction.capitalize()} {plan.travel_deg:.1f}°"
        if plan.long_way:
            text = f"Long way round: {plan.direction} {plan.travel_deg:.1f}°"
        if plan.seconds is not None:
            text += f" · about {plan.seconds:.0f} s"
        return text

    def rotate(self, rotator_id: int, label: str, bearing_deg: float) -> RotateOutcome:
        """The one call a Rotate press makes."""
        outcome = self.service.rotate(rotator_id, label, bearing_deg)
        return replace(outcome, status=self._mode_prefix(rotator_id) + outcome.status)

    def watch(self, rotator_id: int, outcome: RotateOutcome, elapsed_s: float) -> tuple[str, bool]:
        """One progress tick after a press: reads the position if the rotator reports it,
        never moves it."""
        reading = None
        if self.service.capabilities(rotator_id).has_feedback:
            reading = self.service.read_position(rotator_id)
        text, stop = progress_text(outcome, elapsed_s, reading)
        prefix = self._mode_prefix(rotator_id)
        return (text if text.startswith(prefix) else prefix + text), stop

    def read_position(self, rotator_id: int) -> str:
        """The explicit Read position press. Never moves."""
        reading = self.service.read_position(rotator_id)
        return self._mode_prefix(rotator_id) + reading.message

    def stop(self, rotator_id: int) -> str:
        """The explicit Stop press."""
        return self._mode_prefix(rotator_id) + self.service.stop(rotator_id).message

    def recent_commands(self, rotator_id: int, limit: int) -> list[CommandRecord]:
        return self.command_log.recent(rotator_id, limit)

    def _mode_prefix(self, rotator_id: int) -> str:
        return "" if self.rotator_profiles.get(rotator_id).live else "Simulated: "
