"""What the live net screen shows, and what Rotate points at (requirements 4.4).

Bearings are from the operator's station (invariant 3). Controller → you is computed
from the controller's location, never as a reverse bearing plus 180°. Only rotate()
and snap_back() move the rotator, once per press (invariant 2).
"""

import sqlite3
from dataclasses import dataclass
from typing import Literal, Protocol

from beam_navigator.core.callsign import normalize_callsign
from beam_navigator.core.geometry import short_path
from beam_navigator.core.maidenhead import grid_center, is_grid
from beam_navigator.core.models import LatLon, RotatorProfile, Session
from beam_navigator.core.sector import SectorCheck, check_sector, sector_name
from beam_navigator.desk import Bearing, Desk, LookupView
from beam_navigator.rotators.service import RotateOutcome
from beam_navigator.store.repositories import NetRepository, StationRepository

Mode = Literal["controller", "station", "regular", "typed"]
SortKey = Literal["roster", "bearing", "distance", "callsign"]
RegularSort = Literal["callsign", "grid", "direction", "last"]
GRID_NEEDED = "Grid needed"
NO_ROTATOR = "No rotator for this band"


@dataclass(frozen=True)
class ControllerView:
    callsign: str | None
    source: Literal["session grid", "saved", "measured bearing", "unknown"]
    you_to_controller: str | None = None
    controller_to_you: str | None = None
    bearing_deg: float | None = None
    controller_to_you_deg: float | None = None
    toward: Bearing | None = None  # you → controller, with distance


def controller_line(controller: ControllerView) -> tuple[str, str]:
    """The header's net control line and its button (owner, 2026-11-01): never a bare
    "unknown" without a way to fix it."""
    call = controller.callsign
    if controller.source == "measured bearing" and controller.bearing_deg is not None:
        deg = controller.bearing_deg
        return f"Net control: {call or 'call unknown'} · {deg:.1f}° (measured)", "Change…"
    toward = controller.toward
    if toward is not None:
        label = call or "call unknown"
        return f"Net control: {label} · {toward.text} · {toward.distance_text}", "Change…"
    if call is None:
        return "Net control: not set", "Set net control…"
    return f"Net control: {call} — location unknown", "Add grid…"


@dataclass(frozen=True)
class NetRow:
    checkin_id: int
    sequence: int | None
    callsign: str
    name: str | None
    grid_text: str
    bearing_deg: float | None
    bearing_text: str | None
    distance_km: float | None
    distance_text: str | None
    published: str | None
    heard: str | None
    relay_call: str | None


@dataclass(frozen=True)
class RegularRow:
    """A past participant of this net not yet in tonight's list (owner, 2026-10-30)."""

    callsign: str
    name: str | None
    grid_text: str
    bearing_deg: float | None
    bearing_text: str | None
    distance_text: str | None
    attendance_text: str
    last_seen: str


@dataclass(frozen=True)
class LiveNetView:
    title: str
    frequency: str
    controller: ControllerView
    rows: list[NetRow]
    regulars: list[RegularRow]
    rotator: RotatorProfile | None
    rotate_reason: str | None
    last_time: tuple[str, str] | None = None  # (date, notes) of the last closed session
    closed: bool = False


def sort_rows(rows: list[NetRow], key: SortKey) -> list[NetRow]:
    if key == "callsign":
        return sorted(rows, key=lambda r: r.callsign)
    if key == "bearing":
        return sorted(rows, key=lambda r: (r.bearing_deg is None, r.bearing_deg or 0.0))
    if key == "distance":
        return sorted(rows, key=lambda r: (r.distance_km is None, r.distance_km or 0.0))
    return list(rows)  # roster order, as stored


def sort_regulars(rows: list[RegularRow], key: RegularSort) -> list[RegularRow]:
    """Unknown grids and bearings sort last; ties go by callsign."""
    by_call = sorted(rows, key=lambda r: r.callsign)
    if key == "grid":
        return sorted(by_call, key=lambda r: (r.grid_text == GRID_NEEDED, r.grid_text.upper()))
    if key == "direction":
        return sorted(by_call, key=lambda r: (r.bearing_deg is None, r.bearing_deg or 0.0))
    if key == "last":
        return sorted(by_call, key=lambda r: r.last_seen, reverse=True)
    return by_call


class _Filterable(Protocol):
    @property
    def callsign(self) -> str: ...
    @property
    def name(self) -> str | None: ...
    @property
    def grid_text(self) -> str: ...



def filter_rows[Row: _Filterable](rows: list[Row], text: str) -> list[Row]:
    needle = text.strip().lower()
    if not needle:
        return list(rows)
    return [
        row for row in rows
        if needle in " ".join((row.callsign, row.name or "", row.grid_text)).lower()
    ]  # fmt: skip


class LiveNet:
    def __init__(self, conn: sqlite3.Connection, desk: Desk) -> None:
        self.nets = NetRepository(conn)
        self._stations = StationRepository(conn)
        self.desk = desk

    def view(self, session_id: int) -> LiveNetView:
        session = self.nets.get_session(session_id)
        net = self.nets.get_net(session.net_id)
        frequency = f"{net.frequency_mhz:g} MHz" if net.frequency_mhz else (net.channel or "")
        rotator = self._preferred_rotator(net.rotator_id) or self.desk.default_rotator(net.band)
        return LiveNetView(
            title=f"{net.name} · {session.date}",
            frequency=frequency,
            controller=self._controller(session),
            rows=self._rows(session_id),
            regulars=self._regulars(session_id),
            rotator=rotator,
            rotate_reason=None if rotator is not None else NO_ROTATOR,
            last_time=self.nets.last_closing_notes(session.net_id, session_id),
            closed=session.status == "closed",
        )

    def aim(self, session_id: int, text: str) -> tuple[LookupView, tuple[str, float] | None]:
        """What typed text points at, looked up as on the dashboard. Records nothing and
        sends nothing; the second value is the Rotate target, if there is one."""
        net = self.nets.get_net(self.nets.get_session(session_id).net_id)
        view = self.desk.look_up(text, net.band)
        if not view.can_rotate or view.bearing_deg is None:
            return view, None
        label = view.title.split(" — ", 1)[0] if view.title else text.strip()
        return view, (label, view.bearing_deg)

    def heard_aim(self, callsign: str, grid: str) -> tuple[str, Bearing] | None:
        """The I-hear line's direction: the grid typed there, else the saved record's.
        Records nothing and sends nothing; None when there is no call or no location."""
        call = normalize_callsign(callsign) if callsign.strip() else ""
        if not call:
            return None
        found = self.desk.bearing_to(self._grid(call, grid.strip())[0])
        return None if found is None else (call, found)

    def announce(self, session_id: int, sector: str) -> SectorCheck:
        """Records nothing and moves nothing: it only answers "is this call for me?"."""
        controller = self._controller(self.nets.get_session(session_id))
        return check_sector(sector, controller.controller_to_you_deg)

    def set_substitute(
        self, session_id: int, callsign: str | None, grid: str | None, bearing: float | None
    ) -> None:
        call = (callsign or "").strip() or None
        clean_grid = (grid or "").strip() or None
        if call is None and clean_grid is None and bearing is None:
            raise ValueError("Give a callsign, a grid or a measured bearing.")
        self.nets.set_session_controller(session_id, call, clean_grid, bearing=bearing)

    def set_controller(
        self,
        session_id: int,
        callsign: str | None,
        grid: str | None,
        bearing: float | None,
        *,
        save_for_net: bool,
    ) -> None:
        """Use for tonight, or Save for this net: future sessions start with it too."""
        self.set_substitute(session_id, callsign, grid, bearing)
        if save_for_net:
            self.nets.save_controller_as_default(session_id)

    def target(
        self,
        session_id: int,
        mode: Mode,
        checkin_id: int | None,
        *,
        callsign: str | None = None,
        typed: tuple[str, float] | None = None,
    ) -> tuple[str, float] | None:
        """The label and true bearing Rotate would use; None when there is nothing to aim at."""
        if mode == "typed":
            return typed
        if mode == "regular":
            found = next((r for r in self._regulars(session_id) if r.callsign == callsign), None)
            if found is None or found.bearing_deg is None:
                return None
            return found.callsign, found.bearing_deg
        if mode == "controller":
            controller = self._controller(self.nets.get_session(session_id))
            if controller.bearing_deg is None:
                return None
            return controller.callsign or "Controller", controller.bearing_deg
        row = next((r for r in self._rows(session_id) if r.checkin_id == checkin_id), None)
        if row is None or row.bearing_deg is None:
            return None
        return row.callsign, row.bearing_deg

    def rotate(
        self,
        session_id: int,
        rotator_id: int,
        mode: Mode,
        checkin_id: int | None,
        *,
        callsign: str | None = None,
        typed: tuple[str, float] | None = None,
    ) -> RotateOutcome | None:
        """One explicit press: at most one command. None means nothing was sent."""
        aim = self.target(session_id, mode, checkin_id, callsign=callsign, typed=typed)
        if aim is None:
            return None
        label, bearing = aim
        return self.desk.rotate(rotator_id, label, bearing)

    def snap_back(self, session_id: int, rotator_id: int) -> RotateOutcome | None:
        return self.rotate(session_id, rotator_id, "controller", None)

    # -----------------------------------------------------------------------------------

    def _station_location(self, callsign: str) -> LatLon | None:
        found = self._stations.lookup(callsign)
        if found is None:
            return None
        if found.latlon is not None:
            return found.latlon
        if found.grid and is_grid(found.grid):
            return grid_center(found.grid)
        return None

    def controller_location(self, session_id: int) -> LatLon | None:
        """Where tonight's controller is, if known: session grid, then saved record."""
        return self._location(self.nets.get_session(session_id))[0]

    def _location(self, session: Session) -> tuple[LatLon | None, Literal["session grid", "saved"]]:
        if session.controller_grid and is_grid(session.controller_grid):
            return grid_center(session.controller_grid), "session grid"
        if session.controller_call:
            return self._station_location(session.controller_call), "saved"
        return None, "session grid"

    def _preferred_rotator(self, rotator_id: int | None) -> RotatorProfile | None:
        if rotator_id is None:
            return None
        try:
            return self.desk.rotator_profiles.get(rotator_id)
        except ValueError:
            return None

    def _controller(self, session: Session) -> ControllerView:
        call = session.controller_call
        location, source = self._location(session)
        if location is None:
            if session.controller_bearing is not None:
                bearing = session.controller_bearing
                return ControllerView(
                    call, "measured bearing", f"You → controller: {bearing:.1f}°",
                    bearing_deg=bearing,
                )  # fmt: skip
            return ControllerView(call, "unknown")
        home = self.desk.home()
        if home is None:
            return ControllerView(call, source)
        toward = self.desk.bearing_to_location(location)
        back = short_path(location, home).bearing_deg
        return ControllerView(
            call,
            source,
            None if toward is None else f"You → controller: {toward.deg:.1f}°",
            f"Controller → you: {back:.1f}° ({sector_name(back)})",
            None if toward is None else toward.deg,
            back,
            toward,
        )

    def _grid(self, callsign: str, snapshot: str | None) -> tuple[str | None, str]:
        """The grid to aim with and how to show it: the snapshot, else the saved record."""
        if snapshot and is_grid(snapshot):
            return snapshot, snapshot
        saved = self._stations.get(callsign)
        if saved is not None and saved.grid and is_grid(saved.grid):
            return saved.grid, f"{saved.grid} (saved)"
        return None, GRID_NEEDED

    def _regulars(self, session_id: int) -> list[RegularRow]:
        net_id = self.nets.get_session(session_id).net_id
        rows = []
        for participant in self.nets.expected(session_id):
            call = participant.callsign
            grid, grid_text = self._grid(call, participant.last_grid)
            found = self.desk.bearing_to(grid)
            attended, counted = self.nets.attendance(net_id, call)
            record = self._stations.get(call)
            rows.append(
                RegularRow(
                    callsign=call,
                    name=record.name if record else None,
                    grid_text=grid_text,
                    bearing_deg=None if found is None else found.deg,
                    bearing_text=None if found is None else found.text,
                    distance_text=None if found is None else found.distance_text,
                    attendance_text=f"{attended} of last {counted}",
                    last_seen=participant.last_seen,
                )
            )
        return rows

    def _rows(self, session_id: int) -> list[NetRow]:
        rows = []
        for checkin in self.nets.checkins(session_id):
            grid, grid_text = self._grid(checkin.callsign, checkin.grid)
            found = self.desk.bearing_to(grid)
            rows.append(
                NetRow(
                    checkin_id=checkin.id,
                    sequence=checkin.sequence,
                    callsign=checkin.callsign,
                    name=checkin.name,
                    grid_text=grid_text,
                    bearing_deg=None if found is None else found.deg,
                    bearing_text=None if found is None else found.text,
                    distance_km=None if found is None else found.distance_km,
                    distance_text=None if found is None else found.distance_text,
                    published=checkin.published_bearing,
                    heard=checkin.heard_state,
                    relay_call=checkin.relay_call,
                )
            )
        return rows
