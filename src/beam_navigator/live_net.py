"""What the live net screen shows, and what Rotate points at (requirements 4.4).

Bearings are from the operator's station (invariant 3). Controller → you is computed
from the controller's location, never as a reverse bearing plus 180°. Only rotate()
and snap_back() move the rotator, once per press (invariant 2).
"""

import sqlite3
from dataclasses import dataclass
from typing import Literal

from beam_navigator.core.geometry import short_path
from beam_navigator.core.maidenhead import grid_center, is_grid
from beam_navigator.core.models import LatLon, Participant, RotatorProfile, Session
from beam_navigator.core.sector import SectorCheck, check_sector, sector_name
from beam_navigator.desk import Desk
from beam_navigator.rotators.service import RotateOutcome
from beam_navigator.store.repositories import NetRepository, StationRepository

Mode = Literal["controller", "station"]
SortKey = Literal["roster", "bearing", "distance", "callsign"]
NO_ROTATOR = "No rotator for this band"


@dataclass(frozen=True)
class ControllerView:
    callsign: str | None
    source: Literal["session grid", "saved", "measured bearing", "unknown"]
    you_to_controller: str | None = None
    controller_to_you: str | None = None
    bearing_deg: float | None = None
    controller_to_you_deg: float | None = None


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
class LiveNetView:
    title: str
    frequency: str
    controller: ControllerView
    rows: list[NetRow]
    expected: list[Participant]
    rotator: RotatorProfile | None
    rotate_reason: str | None


def sort_rows(rows: list[NetRow], key: SortKey) -> list[NetRow]:
    if key == "callsign":
        return sorted(rows, key=lambda r: r.callsign)
    if key == "bearing":
        return sorted(rows, key=lambda r: (r.bearing_deg is None, r.bearing_deg or 0.0))
    if key == "distance":
        return sorted(rows, key=lambda r: (r.distance_km is None, r.distance_km or 0.0))
    return list(rows)  # roster order, as stored


def filter_rows(rows: list[NetRow], text: str) -> list[NetRow]:
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
            expected=self.nets.expected(session_id),
            rotator=rotator,
            rotate_reason=None if rotator is not None else NO_ROTATOR,
        )

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

    def target(
        self, session_id: int, mode: Mode, checkin_id: int | None
    ) -> tuple[str, float] | None:
        """The label and true bearing Rotate would use; None when there is nothing to aim at."""
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
        self, session_id: int, rotator_id: int, mode: Mode, checkin_id: int | None
    ) -> RotateOutcome | None:
        """One explicit press: at most one command. None means nothing was sent."""
        aim = self.target(session_id, mode, checkin_id)
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
        )

    def _rows(self, session_id: int) -> list[NetRow]:
        rows = []
        for checkin in self.nets.checkins(session_id):
            grid_text = "Grid needed"
            grid = None
            if checkin.grid and is_grid(checkin.grid):
                grid = grid_text = checkin.grid
            else:
                saved = self._stations.get(checkin.callsign)
                if saved is not None and saved.grid and is_grid(saved.grid):
                    grid = saved.grid
                    grid_text = f"{saved.grid} (saved)"
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
