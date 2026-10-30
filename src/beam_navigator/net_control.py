"""The net controller's operations (requirements 4.5). Nothing here moves a rotator.

Check-ins are snapshots (spec 3): logging never changes a station record unless the
controller explicitly chooses Update station record.
"""

import sqlite3
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, tzinfo

from beam_navigator.core.callsign import base_callsign, is_callsign, normalize_callsign
from beam_navigator.core.geometry import compass_name, short_path
from beam_navigator.core.maidenhead import grid_center, is_grid
from beam_navigator.core.models import CheckIn, Station
from beam_navigator.core.qrz import QrzRecord
from beam_navigator.core.schedule import zone_for
from beam_navigator.desk import Desk
from beam_navigator.live_net import LiveNet
from beam_navigator.store.repositories import NetRepository, StationRepository

PREVIOUS_NOTES = 5


@dataclass
class Entry:
    callsign: str
    name: str = ""
    grid: str = ""
    qth: str = ""
    report: str = ""
    notes: str = ""


@dataclass(frozen=True)
class Autofill:
    callsign: str
    known: bool
    name: str | None
    grid: str | None
    qth: str | None
    source: str | None


@dataclass(frozen=True)
class InfoPanel:
    callsign: str
    last: str
    from_net_control: str | None
    attendance: str
    previous_notes: list[str]
    station_notes: str


@dataclass(frozen=True)
class Suggestion:
    callsign: str
    attended: int
    last_grid: str | None


@dataclass(frozen=True)
class ControlRow:
    checkin_id: int
    sequence: int | None
    time: str
    callsign: str
    name: str | None
    grid: str | None
    qth: str | None
    report: str | None
    notes: str | None
    flags: list[str] = field(default_factory=list)


def _base(callsign: str) -> str:
    call = normalize_callsign(callsign)
    return base_callsign(call) if is_callsign(call) else call


def _clean(text: str) -> str | None:
    return text.strip() or None


class NetControl:
    def __init__(self, conn: sqlite3.Connection, desk: Desk) -> None:
        self.conn = conn
        self.nets = NetRepository(conn)
        self.stations = StationRepository(conn)
        self.desk = desk
        self.live = LiveNet(conn, desk)

    # Looking a station up -----------------------------------------------------------------

    def autofill(self, callsign: str) -> Autofill:
        call = normalize_callsign(callsign)
        record = self.stations.get(call)
        if record is None:
            return Autofill(call, False, None, None, None, None)
        return Autofill(call, True, record.name, record.grid, record.qth, record.source)

    def info(self, session_id: int, callsign: str) -> InfoPanel:
        call = normalize_callsign(callsign)
        session = self.nets.get_session(session_id)
        record = self.stations.get(call)
        last = "No record"
        from_nc = None
        if record is not None:
            parts = [record.name or "—", record.grid or "—", record.qth or "—"]
            last = f"{' · '.join(parts)} ({record.source})"
            controller = self.live.controller_location(session_id)
            if controller is not None and record.grid and is_grid(record.grid):
                path = short_path(controller, grid_center(record.grid))
                distance = self.desk.distance_text(path.distance_km)
                from_nc = (
                    f"From net control: {path.bearing_deg:.1f}° "
                    f"{compass_name(path.bearing_deg)} · {distance}"
                )
        attended, counted = self.nets.attendance(session.net_id, call)
        notes = self.nets.previous_notes(session.net_id, call, session_id, PREVIOUS_NOTES)
        return InfoPanel(
            call,
            last,
            from_nc,
            f"{attended} of last {counted}",
            [f"{when}: {text}" for when, text in notes],
            record.notes if record is not None else "",
        )

    def suggest(self, session_id: int, fragment: str, limit: int = 8) -> list[Suggestion]:
        """Known calls containing the typed text, most regular at this net first."""
        text = fragment.strip().upper()
        if len(text) < 2:
            return []
        net_id = self.nets.get_session(session_id).net_id
        counts = self.nets.call_counts(net_id)
        calls = set(self.stations.callsigns_containing(text))
        calls.update(call for call in counts if text in call)
        ranked = sorted(calls, key=lambda call: (-counts.get(_base(call), 0), call))
        found = []
        for call in ranked[:limit]:
            record = self.stations.get(call)
            grid = record.grid if record else None
            found.append(Suggestion(call, counts.get(_base(call), 0), grid))
        return found

    # Duplicates and changes -----------------------------------------------------------

    def duplicate(self, session_id: int, callsign: str) -> CheckIn | None:
        key = _base(callsign)
        return next((c for c in self.nets.checkins(session_id) if _base(c.callsign) == key), None)

    def duplicate_text(self, session_id: int, checkin: CheckIn) -> str:
        number = f"#{checkin.sequence}" if checkin.sequence is not None else "#?"
        time = self._local_time(session_id, checkin.logged_at)
        if not time:
            return f"Already checked in ({number})"
        return f"Already checked in at {time} ({number})"

    def changes(self, entry: Entry) -> list[str]:
        """What the typed details would change in the station record (spec 4.5)."""
        record = self.stations.get(normalize_callsign(entry.callsign))
        if record is None:
            return []
        found = []
        name, grid = entry.name.strip(), entry.grid.strip()
        if name and record.name and name.casefold() != record.name.casefold():
            found.append(f"Name: {record.name} → {name}")
        if grid and record.grid and grid.lower() != record.grid.lower():
            found.append(f"Grid: {record.grid} → {grid}")
        return found

    # Logging ----------------------------------------------------------------------------

    def _check(self, entry: Entry) -> str:
        call = normalize_callsign(entry.callsign)
        if not call:
            raise ValueError("Enter a callsign.")
        if not is_callsign(call):
            raise ValueError(f"{call} is not a callsign.")
        grid = entry.grid.strip()
        if grid and not is_grid(grid):
            raise ValueError(f"{grid!r} is not a grid square.")
        return call

    def log(self, session_id: int, entry: Entry, update_record: bool = False) -> CheckIn:
        call = self._check(entry)
        logged = self.nets.add_checkin(
            session_id, call, name=_clean(entry.name), grid=_clean(entry.grid),
            qth=_clean(entry.qth), report=_clean(entry.report), notes=_clean(entry.notes),
        )  # fmt: skip
        # A station first heard tonight gets a record that later rosters may fill in
        # (decision 13); an existing record changes only on Update station record.
        self.stations.add_from_roster(call, _clean(entry.name), _clean(entry.grid),
                                      _clean(entry.qth))  # fmt: skip
        if update_record:
            self._update_record(call, entry)
        return logged

    def update_existing(self, checkin_id: int, entry: Entry) -> CheckIn:
        grid = entry.grid.strip()
        if grid and not is_grid(grid):
            raise ValueError(f"{grid!r} is not a grid square.")
        return self.nets.update_checkin(
            checkin_id, name=entry.name, grid=entry.grid, qth=entry.qth, report=entry.report,
            notes=entry.notes,
        )  # fmt: skip

    def merge_into_existing(self, checkin_id: int, entry: Entry) -> CheckIn:
        """Update existing, from the duplicate warning: only the fields typed now change;
        anything left blank keeps the earlier value from tonight."""
        grid = entry.grid.strip()
        if grid and not is_grid(grid):
            raise ValueError(f"{grid!r} is not a grid square.")
        session_id = self.nets.get_checkin_session(checkin_id)
        current = next(c for c in self.nets.checkins(session_id) if c.id == checkin_id)
        return self.nets.update_checkin(
            checkin_id,
            name=_clean(entry.name) or current.name,
            grid=_clean(entry.grid) or current.grid,
            qth=_clean(entry.qth) or current.qth,
            report=_clean(entry.report) or current.report,
            notes=_clean(entry.notes) or current.notes,
        )

    def _update_record(self, call: str, entry: Entry) -> None:
        record = self.stations.get(call)
        grid = _clean(entry.grid)
        keep_latlon = record is not None and (grid is None or grid == record.grid)
        self.stations.save(
            Station(
                call,
                _clean(entry.name) or (record.name if record else None),
                grid or (record.grid if record else None),
                _clean(entry.qth) or (record.qth if record else None),
                record.latlon if record is not None and keep_latlon else None,
                "saved",
                record.notes if record else "",
            )
        )

    def add_station_note(self, callsign: str, text: str) -> None:
        self.stations.add_note(callsign, text, date.today().isoformat())

    def rows(self, session_id: int) -> list[ControlRow]:
        rows = []
        for checkin in self.nets.checkins(session_id):
            flags = []
            if not checkin.name:
                flags.append("name missing")
            if not checkin.grid:
                flags.append("grid missing")
            rows.append(
                ControlRow(
                    checkin.id, checkin.sequence, self._local_time(session_id, checkin.logged_at),
                    checkin.callsign, checkin.name, checkin.grid, checkin.qth, checkin.report,
                    checkin.notes, flags,
                )
            )  # fmt: skip
        return rows

    @staticmethod
    def qrz_fill(entry: Entry, record: QrzRecord) -> Entry:
        """QRZ fills only blank fields (requirements 4.9). Its grid is used only when QRZ's
        position came from the station or its address, never a zip, state or country."""
        grid = record.grid if record.precision in ("station", "address") else None
        return replace(
            entry,
            name=entry.name.strip() or record.name or "",
            grid=entry.grid.strip() or grid or "",
            qth=entry.qth.strip() or record.qth or "",
        )

    def _zone(self, session_id: int) -> tzinfo | None:
        """The net's time zone, else the active profile's, else None for this computer's
        own (decision 24). A name that is not a real zone is skipped, never guessed."""
        net = self.nets.get_net(self.nets.get_session(session_id).net_id)
        profile = self.desk.profiles.get_active()
        return zone_for(net.timezone, profile.timezone if profile else None)

    def _local_time(self, session_id: int, logged_at: str | None) -> str:
        if not logged_at:
            return ""
        moment = datetime.fromisoformat(logged_at)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return f"{moment.astimezone(self._zone(session_id)):%H:%M}"
