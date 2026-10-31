"""Repositories: one small class per entity over a sqlite3 connection.

Each method commits its own change, so a caller never leaves half a write behind.
"""

import math
import re
import sqlite3
from datetime import UTC, date, datetime
from typing import Literal, cast

from beam_navigator.core.callsign import base_callsign, is_callsign, normalize_callsign
from beam_navigator.core.maidenhead import grid_center
from beam_navigator.core.models import (
    Band,
    CheckIn,
    CommandRecord,
    LatLon,
    Net,
    OperatorProfile,
    Participant,
    RotatorProfile,
    Session,
    Station,
)
from beam_navigator.core.qrz import QrzRecord
from beam_navigator.core.regions import load_regions
from beam_navigator.core.roster_parser import ParseResult, RosterRow
from beam_navigator.core.targets import AliasTarget, StationLocation, validate_alias
from beam_navigator.rotators.travel import TravelRange, travel_error


class DuplicateCheckIn(Exception):
    """The callsign is already checked in to this session (spec 3)."""

    def __init__(self, callsign: str, existing: CheckIn) -> None:
        super().__init__(f"{callsign} already checked in (#{existing.sequence}).")
        self.callsign = callsign
        self.existing = existing


class SessionClosed(ValueError):
    """A closed session takes no new or changed check-ins until it is reopened."""

    def __init__(self) -> None:
        super().__init__("This session is closed. Reopen it to make changes.")


def _latlon(row: sqlite3.Row) -> LatLon | None:
    if row["lat"] is None or row["lon"] is None:
        return None
    return LatLon(row["lat"], row["lon"])


class ProfileRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, profile: OperatorProfile) -> OperatorProfile:
        """Insert or update. Activation is separate: see activate()."""
        grid_center(profile.home_grid)  # raises GridError (a ValueError)
        region = profile.home_region.strip().upper() if profile.home_region else None
        if region is not None and region not in load_regions():
            raise ValueError(f"Unknown state or province {profile.home_region!r}.")
        if profile.latlon is not None and not (
            -90 <= profile.latlon.lat <= 90 and -180 <= profile.latlon.lon <= 180
        ):  # also False for NaN
            raise ValueError(f"Home coordinates {profile.latlon} are not a place on Earth.")
        callsign = normalize_callsign(profile.callsign) if profile.callsign else None
        lat = profile.latlon.lat if profile.latlon else None
        lon = profile.latlon.lon if profile.latlon else None
        values = (profile.name, callsign, profile.home_grid.strip(), lat, lon, profile.units,
                  profile.timezone, region)  # fmt: skip
        with self._conn:
            if profile.id is None:
                cursor = self._conn.execute(
                    "INSERT INTO operator_profile (name, callsign, home_grid, lat, lon, units,"
                    " timezone, home_region) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
                profile_id = cast(int, cursor.lastrowid)
            else:
                self._conn.execute(
                    "UPDATE operator_profile SET name = ?, callsign = ?, home_grid = ?, lat = ?,"
                    " lon = ?, units = ?, timezone = ?, home_region = ? WHERE id = ?",
                    (*values, profile.id),
                )
                profile_id = profile.id
        return self._get(profile_id)

    def _get(self, profile_id: int) -> OperatorProfile:
        row = self._conn.execute(
            "SELECT * FROM operator_profile WHERE id = ?", (profile_id,)
        ).fetchone()
        return self._from_row(row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> OperatorProfile:
        return OperatorProfile(
            id=row["id"],
            name=row["name"],
            callsign=row["callsign"],
            home_grid=row["home_grid"],
            latlon=_latlon(row),
            units=row["units"],
            timezone=row["timezone"],
            home_region=row["home_region"],
            is_active=bool(row["is_active"]),
        )

    def activate(self, profile_id: int) -> None:
        with self._conn:
            self._conn.execute("UPDATE operator_profile SET is_active = 0 WHERE is_active = 1")
            cursor = self._conn.execute(
                "UPDATE operator_profile SET is_active = 1 WHERE id = ?", (profile_id,)
            )
            if cursor.rowcount != 1:
                raise ValueError(f"No operator profile with id {profile_id}.")

    def get_active(self) -> OperatorProfile | None:
        row = self._conn.execute("SELECT * FROM operator_profile WHERE is_active = 1").fetchone()
        return None if row is None else self._from_row(row)

    def list(self) -> list[OperatorProfile]:
        rows = self._conn.execute("SELECT * FROM operator_profile ORDER BY name").fetchall()
        return [self._from_row(row) for row in rows]


class AliasRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, name: str, target: AliasTarget) -> None:
        clean = validate_alias(name, target)
        with self._conn:
            self._conn.execute(
                "INSERT INTO alias (name, kind, value) VALUES (?, ?, ?)"
                " ON CONFLICT (name) DO UPDATE SET kind = excluded.kind, value = excluded.value",
                (name.strip().upper(), clean.kind, clean.value),
            )

    def delete(self, name: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM alias WHERE name = ?", (name.strip().upper(),))

    def get(self, name: str) -> AliasTarget | None:
        """Matches core.targets.AliasLookup."""
        row = self._conn.execute(
            "SELECT kind, value FROM alias WHERE name = ?", (name.strip().upper(),)
        ).fetchone()
        return None if row is None else AliasTarget(row["kind"], row["value"])

    def list(self) -> list[tuple[str, AliasTarget]]:
        rows = self._conn.execute("SELECT name, kind, value FROM alias ORDER BY name").fetchall()
        return [(row["name"], AliasTarget(row["kind"], row["value"])) for row in rows]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _insert_roster_station(
    conn: sqlite3.Connection, callsign: str, name: str | None, grid: str | None, qth: str | None
) -> bool:
    """Insert without committing, so a roster import stays one transaction.

    An existing record learned from a roster gets its empty fields filled; nothing
    already known is overwritten, and a record the operator saved is never touched."""
    call = normalize_callsign(callsign)
    cursor = conn.execute(
        "INSERT INTO station (callsign, name, grid, qth, source, updated_at)"
        " VALUES (?, ?, ?, ?, 'roster', ?) ON CONFLICT (callsign) DO NOTHING",
        (call, name, grid, qth, _now()),
    )
    if cursor.rowcount == 1:
        return True
    conn.execute(
        "UPDATE station SET name = COALESCE(name, ?), grid = COALESCE(grid, ?),"
        " qth = COALESCE(qth, ?), updated_at = ? WHERE callsign = ? AND source = 'roster'"
        " AND ((name IS NULL AND ? IS NOT NULL) OR (grid IS NULL AND ? IS NOT NULL)"
        " OR (qth IS NULL AND ? IS NOT NULL))",
        (name, grid, qth, _now(), call, name, grid, qth),
    )
    return False


class StationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, callsign: str) -> Station | None:
        row = self._conn.execute(
            "SELECT * FROM station WHERE callsign = ?", (normalize_callsign(callsign),)
        ).fetchone()
        if row is None:
            return None
        return Station(
            callsign=row["callsign"],
            name=row["name"],
            grid=row["grid"],
            qth=row["qth"],
            latlon=_latlon(row),
            source=row["source"],
            notes=row["notes"],
        )

    def save(self, station: Station) -> None:
        """The operator's explicit save: every field is replaced."""
        lat = station.latlon.lat if station.latlon else None
        lon = station.latlon.lon if station.latlon else None
        with self._conn:
            self._conn.execute(
                "INSERT INTO station (callsign, name, grid, qth, lat, lon, source, notes,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?, 'saved', ?, ?)"
                " ON CONFLICT (callsign) DO UPDATE SET name = excluded.name,"
                " grid = excluded.grid, qth = excluded.qth, lat = excluded.lat,"
                " lon = excluded.lon, source = 'saved', notes = excluded.notes,"
                " updated_at = excluded.updated_at",
                (normalize_callsign(station.callsign), station.name, station.grid, station.qth,
                 lat, lon, station.notes, _now()),
            )  # fmt: skip

    def add_from_roster(
        self, callsign: str, name: str | None, grid: str | None, qth: str | None
    ) -> bool:
        """Create a record for a station first seen in a roster; returns whether it did.
        A roster never changes a known value (spec 7); see _insert_roster_station."""
        with self._conn:
            return _insert_roster_station(self._conn, callsign, name, grid, qth)

    def callsigns_containing(self, fragment: str, limit: int = 200) -> list[str]:
        """Known callsigns containing the text, for partial-call matching (spec 4.5)."""
        rows = self._conn.execute(
            "SELECT callsign FROM station WHERE instr(callsign, ?) > 0 ORDER BY callsign LIMIT ?",
            (fragment.strip().upper(), limit),
        ).fetchall()
        return [row["callsign"] for row in rows]

    def add_note(self, callsign: str, text: str, when: str) -> None:
        """Append one dated line to the persistent station notes (spec 4.5, Alt+N)."""
        clean = " ".join(text.split())
        if not clean:
            raise ValueError("The note is empty.")
        call = normalize_callsign(callsign)
        with self._conn:
            _insert_roster_station(self._conn, call, None, None, None)
        existing = self.get(call)
        notes = existing.notes if existing is not None else ""
        line = f"{when}: {clean}"
        self.set_notes(call, f"{notes}\n{line}" if notes else line)

    def set_notes(self, callsign: str, notes: str) -> None:
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE station SET notes = ?, updated_at = ? WHERE callsign = ?",
                (notes, _now(), normalize_callsign(callsign)),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"No station record for {normalize_callsign(callsign)}.")

    def lookup(self, callsign: str) -> StationLocation | None:
        """Matches core.targets.StationLookup."""
        station = self.get(callsign)
        if station is None:
            return None
        return StationLocation(station.callsign, station.grid, station.latlon, station.source)


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _base(callsign: str) -> str:
    call = normalize_callsign(callsign)
    return base_callsign(call) if is_callsign(call) else call


def _check_date(text: str) -> str:
    """Session dates come from the caller as YYYY-MM-DD, never from roster words."""
    if not _ISO_DATE.fullmatch(text):
        raise ValueError(f"Date {text!r} must be YYYY-MM-DD.")
    date.fromisoformat(text)  # raises for 2026-13-01
    return text


def _canonical(text: str) -> str:
    """Raw text as compared for re-import: what mail clients change does not count."""
    lines = text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def _grids_disagree(a: str, b: str) -> bool:
    # Compare over the shorter grid: fm29 agrees with FM29pt; FN10xi differs from FN10xh.
    length = min(len(a), len(b))
    return a[:length].upper() != b[:length].upper()


class NetRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # Nets -----------------------------------------------------------------------------

    def save_net(self, net: Net) -> Net:
        values = (net.name, net.weekday, net.start_time, net.timezone, net.frequency_mhz,
                  net.channel, net.mode, net.band, net.default_controller_call,
                  net.default_controller_grid, int(net.archived), net.rotator_id,
                  int(net.unverified), int(net.favourite))  # fmt: skip
        with self._conn:
            if net.id is None:
                cursor = self._conn.execute(
                    "INSERT INTO net (name, weekday, start_time, timezone, frequency_mhz,"
                    " channel, mode, band, default_controller_call, default_controller_grid,"
                    " archived, rotator_id, unverified, favourite)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
                net_id = cast(int, cursor.lastrowid)
            else:
                self._conn.execute(
                    "UPDATE net SET name = ?, weekday = ?, start_time = ?, timezone = ?,"
                    " frequency_mhz = ?, channel = ?, mode = ?, band = ?,"
                    " default_controller_call = ?, default_controller_grid = ?, archived = ?,"
                    " rotator_id = ?, unverified = ?, favourite = ?"
                    " WHERE id = ?",
                    (*values, net.id),
                )
                net_id = net.id
        return self.get_net(net_id)

    def get_net(self, net_id: int) -> Net:
        row = self._conn.execute("SELECT * FROM net WHERE id = ?", (net_id,)).fetchone()
        if row is None:
            raise ValueError(f"No net with id {net_id}.")
        return Net(
            id=row["id"],
            name=row["name"],
            weekday=row["weekday"],
            start_time=row["start_time"],
            timezone=row["timezone"],
            frequency_mhz=row["frequency_mhz"],
            channel=row["channel"],
            mode=row["mode"],
            band=row["band"],
            default_controller_call=row["default_controller_call"],
            default_controller_grid=row["default_controller_grid"],
            archived=bool(row["archived"]),
            rotator_id=row["rotator_id"],
            unverified=bool(row["unverified"]),
            favourite=bool(row["favourite"]),
        )

    def delete_net(self, net_id: int) -> None:
        """Raises sqlite3.IntegrityError when the net has sessions: history is never lost."""
        with self._conn:
            self._conn.execute("DELETE FROM net WHERE id = ?", (net_id,))

    # Sessions and roster import ---------------------------------------------------------

    def get_session(self, session_id: int) -> Session:
        row = self._conn.execute("SELECT * FROM session WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise ValueError(f"No session with id {session_id}.")
        return Session(
            id=row["id"],
            net_id=row["net_id"],
            date=row["date"],
            controller_call=row["controller_call"],
            controller_grid=row["controller_grid"],
            status=row["status"],
            raw_text=row["raw_text"],
            controller_bearing=row["controller_bearing"],
            closing_notes=row["closing_notes"],
            closed_at=row["closed_at"],
        )

    def _check_open(self, session_id: int) -> None:
        if self.get_session(session_id).status == "closed":
            raise SessionClosed()

    def close_session(self, session_id: int, notes: str) -> Session:
        self.get_session(session_id)
        with self._conn:
            self._conn.execute(
                "UPDATE session SET status = 'closed', closing_notes = ?, closed_at = ?"
                " WHERE id = ?",
                ((notes or "").strip() or None, _now(), session_id),
            )
        return self.get_session(session_id)

    def reopen_session(self, session_id: int) -> Session:
        """Back to active; the notes and closing time are kept."""
        self.get_session(session_id)
        with self._conn:
            self._conn.execute("UPDATE session SET status = 'active' WHERE id = ?", (session_id,))
        return self.get_session(session_id)

    def last_closing_notes(self, net_id: int, before_session_id: int) -> tuple[str, str] | None:
        """The date and notes of this net's latest closed session before this one (by date,
        then id). Empty notes there mean nothing to show, never an older session's notes."""
        this = self.get_session(before_session_id)
        row = self._conn.execute(
            "SELECT date, closing_notes FROM session WHERE net_id = ? AND status = 'closed'"
            " AND (date < ? OR (date = ? AND id < ?)) ORDER BY date DESC, id DESC LIMIT 1",
            (net_id, this.date, this.date, this.id),
        ).fetchone()
        if row is None or not row["closing_notes"]:
            return None
        return row["date"], row["closing_notes"]

    def find_identical_import(self, net_id: int, date: str, raw_text: str) -> int | None:
        wanted = _canonical(raw_text)
        rows = self._conn.execute(
            "SELECT id, raw_text FROM session WHERE net_id = ? AND date = ?"
            " AND raw_text IS NOT NULL ORDER BY id",
            (net_id, date),
        ).fetchall()
        return next((row["id"] for row in rows if _canonical(row["raw_text"]) == wanted), None)

    def import_roster(
        self,
        net_id: int,
        date: str,
        raw_text: str,
        result: ParseResult,
        replace_session_id: int | None = None,
        controller: RosterRow | None | Literal["from rows"] = "from rows",
        replace_grids: dict[str, str] | None = None,
    ) -> Session:
        """controller: the session's controller when the caller knows it, e.g. a row the
        operator left out of the check-ins (the NCS often is); by default, the kept row
        marked as controller. replace_grids: callsign to grid, where the operator chose to
        replace a grid learned from an earlier roster (decision 40); a saved record is
        never changed."""
        _check_date(date)
        chosen: RosterRow | None = (
            next((row for row in result.rows if row.is_controller), None)
            if controller == "from rows"
            else controller
        )
        with self._conn:  # one transaction: all of it or none of it
            if replace_session_id is not None:
                # Only an earlier import of this same net and date may be replaced; a
                # wrong id must never delete other history (invariant 9).
                found = self._conn.execute(
                    "SELECT 1 FROM session WHERE id = ? AND net_id = ? AND date = ?"
                    " AND status = 'imported'",
                    (replace_session_id, net_id, date),
                ).fetchone()
                if found is None:
                    raise ValueError(
                        f"Session {replace_session_id} is not an import of this net on {date}."
                    )
                self._conn.execute(
                    "DELETE FROM checkin WHERE session_id = ?", (replace_session_id,)
                )
                self._conn.execute("DELETE FROM session WHERE id = ?", (replace_session_id,))
            cursor = self._conn.execute(
                "INSERT INTO session (net_id, date, controller_call, controller_grid, status,"
                " raw_text, created_at) VALUES (?, ?, ?, ?, 'imported', ?, ?)",
                (net_id, date, chosen.callsign if chosen else None,
                 chosen.grid if chosen else None, raw_text, _now()),
            )  # fmt: skip
            session_id = cast(int, cursor.lastrowid)
            for position, row in enumerate(result.checkins, start=1):
                call = cast(str, row.callsign)  # checkins only holds rows with a callsign
                sequence = row.sequence if row.sequence is not None else position
                self._conn.execute(
                    "INSERT INTO checkin (session_id, sequence, callsign, name, grid, qth,"
                    " published_bearing) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (session_id, sequence, call, row.name, row.grid, row.qth,
                     row.published_bearing),
                )  # fmt: skip
                _insert_roster_station(self._conn, call, row.name, row.grid, row.qth)
            for call, grid in (replace_grids or {}).items():
                self._conn.execute(
                    "UPDATE station SET grid = ?, lat = NULL, lon = NULL, updated_at = ?"
                    " WHERE callsign = ? AND source = 'roster'",
                    (grid, _now(), normalize_callsign(call)),
                )
        return self.get_session(session_id)

    def checkins(self, session_id: int) -> list[CheckIn]:
        rows = self._conn.execute(
            "SELECT * FROM checkin WHERE session_id = ? ORDER BY sequence, id", (session_id,)
        ).fetchall()
        return [
            CheckIn(
                id=row["id"],
                session_id=row["session_id"],
                sequence=row["sequence"],
                callsign=row["callsign"],
                name=row["name"],
                grid=row["grid"],
                qth=row["qth"],
                published_bearing=row["published_bearing"],
                heard_state=row["heard_state"],
                relay_call=row["relay_call"],
                report=row["report"],
                notes=row["notes"],
                logged_at=row["logged_at"],
            )
            for row in rows
        ]

    def saved_grid_conflicts(self, result: ParseResult) -> dict[int, str]:
        stations = StationRepository(self._conn)
        conflicts: dict[int, str] = {}
        for index, row in enumerate(result.rows):
            if row.callsign is None or row.grid is None:
                continue
            station = stations.get(row.callsign)
            if station is not None and station.grid and _grids_disagree(row.grid, station.grid):
                conflicts[index] = f"Saved grid {station.grid} differs"
        return conflicts

    # Live sessions ----------------------------------------------------------------------

    def start_session(self, net_id: int, date: str) -> Session:
        _check_date(date)
        net = self.get_net(net_id)
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO session (net_id, date, controller_call, controller_grid, status,"
                " created_at) VALUES (?, ?, ?, ?, 'active', ?)",
                (net_id, date, net.default_controller_call, net.default_controller_grid,
                 _now()),
            )  # fmt: skip
        return self.get_session(cast(int, cursor.lastrowid))

    def set_session_controller(
        self,
        session_id: int,
        callsign: str | None,
        grid: str | None,
        bearing: float | None = None,
    ) -> None:
        """Tonight only: the net's default controller is not touched (spec 3). A
        measured bearing stands in when the controller's location is unknown (spec 4.4)."""
        clean_grid = grid.strip() if grid and grid.strip() else None
        if clean_grid is not None:
            grid_center(clean_grid)  # raises GridError (a ValueError)
        if bearing is not None and not (math.isfinite(bearing) and 0 <= bearing <= 359.9):
            raise ValueError(f"Bearing {bearing:g}° is outside 0–359.9°.")
        call = normalize_callsign(callsign) if callsign else None
        with self._conn:
            self._conn.execute(
                "UPDATE session SET controller_call = ?, controller_grid = ?,"
                " controller_bearing = ? WHERE id = ?",
                (call, clean_grid, bearing, session_id),
            )

    def set_heard(
        self,
        checkin_id: int,
        state: Literal["heard", "weak", "not_heard", "relay"] | None,
        relay_call: str | None = None,
    ) -> None:
        """The operator's private heard state for one check-in (spec 4.4)."""
        relay = None
        if state == "relay":
            if not (relay_call and is_callsign(relay_call)):
                raise ValueError("Via relay needs the relaying station's callsign.")
            relay = normalize_callsign(relay_call)
        self._check_open(self.get_checkin_session(checkin_id))
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE checkin SET heard_state = ?, relay_call = ? WHERE id = ?",
                (state, relay, checkin_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"No check-in with id {checkin_id}.")

    def update_checkin(
        self,
        checkin_id: int,
        *,
        name: str | None,
        grid: str | None,
        qth: str | None,
        report: str | None,
        notes: str | None,
    ) -> CheckIn:
        """The controller's edit of one row. The check-in is a snapshot (spec 3): this
        never touches the station record."""
        values = [(value or "").strip() or None for value in (name, grid, qth, report, notes)]
        if values[1] is not None:
            grid_center(values[1])  # raises GridError (a ValueError)
        row = self._conn.execute(
            "SELECT session_id FROM checkin WHERE id = ?", (checkin_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"No check-in with id {checkin_id}.")
        self._check_open(row["session_id"])
        with self._conn:
            self._conn.execute(
                "UPDATE checkin SET name = ?, grid = ?, qth = ?, report = ?, notes = ?"
                " WHERE id = ?",
                (*values, checkin_id),
            )
        return next(c for c in self.checkins(row["session_id"]) if c.id == checkin_id)

    def get_checkin_session(self, checkin_id: int) -> int:
        row = self._conn.execute(
            "SELECT session_id FROM checkin WHERE id = ?", (checkin_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"No check-in with id {checkin_id}.")
        return int(row["session_id"])

    def attendance(self, net_id: int, callsign: str, last: int = 15) -> tuple[int, int]:
        """(sessions attended, sessions counted) over the net's last `last` sessions."""
        key = _base(callsign)
        recent = self._conn.execute(
            "SELECT id FROM session WHERE net_id = ? ORDER BY date DESC, id DESC LIMIT ?",
            (net_id, last),
        ).fetchall()
        attended = 0
        for session in recent:
            calls = self._conn.execute(
                "SELECT callsign FROM checkin WHERE session_id = ?", (session["id"],)
            ).fetchall()
            if any(_base(row["callsign"]) == key for row in calls):
                attended += 1
        return attended, len(recent)

    def previous_notes(
        self, net_id: int, callsign: str, before_session_id: int, limit: int = 5
    ) -> list[tuple[str, str]]:
        """Notes from this station's earlier sessions of this net, newest first."""
        key = _base(callsign)
        rows = self._conn.execute(
            "SELECT s.date, c.callsign, c.notes FROM checkin c JOIN session s"
            " ON s.id = c.session_id WHERE s.net_id = ? AND s.id != ?"
            " AND c.notes IS NOT NULL AND TRIM(c.notes) != '' ORDER BY s.date DESC, s.id DESC",
            (net_id, before_session_id),
        ).fetchall()
        found = [(row["date"], row["notes"].strip()) for row in rows
                 if _base(row["callsign"]) == key]  # fmt: skip
        return found[:limit]

    def call_counts(self, net_id: int) -> dict[str, int]:
        """Sessions attended at this net, per base callsign."""
        rows = self._conn.execute(
            "SELECT DISTINCT c.session_id, c.callsign FROM checkin c JOIN session s"
            " ON s.id = c.session_id WHERE s.net_id = ?",
            (net_id,),
        ).fetchall()
        seen: dict[str, set[int]] = {}
        for row in rows:
            seen.setdefault(_base(row["callsign"]), set()).add(row["session_id"])
        return {call: len(sessions) for call, sessions in sorted(seen.items())}

    def list_nets(self) -> list[Net]:
        rows = self._conn.execute("SELECT id FROM net ORDER BY archived, name").fetchall()
        return [self.get_net(row["id"]) for row in rows]

    def sessions(self, net_id: int) -> list[tuple[Session, int]]:
        """Each session of the net with its check-in count, newest first."""
        rows = self._conn.execute(
            "SELECT s.id, COUNT(c.id) AS checkins FROM session s"
            " LEFT JOIN checkin c ON c.session_id = s.id WHERE s.net_id = ?"
            " GROUP BY s.id ORDER BY s.date DESC, s.id DESC",
            (net_id,),
        ).fetchall()
        return [(self.get_session(row["id"]), row["checkins"]) for row in rows]

    def save_controller_as_default(self, session_id: int) -> None:
        """The operator's explicit "Save as default"."""
        session = self.get_session(session_id)
        with self._conn:
            self._conn.execute(
                "UPDATE net SET default_controller_call = ?, default_controller_grid = ?"
                " WHERE id = ?",
                (session.controller_call, session.controller_grid, session.net_id),
            )

    def add_checkin(
        self,
        session_id: int,
        callsign: str,
        *,
        allow_duplicate: bool = False,
        name: str | None = None,
        grid: str | None = None,
        qth: str | None = None,
        report: str | None = None,
        notes: str | None = None,
    ) -> CheckIn:
        call = normalize_callsign(callsign)
        self._check_open(session_id)
        existing = self.checkins(session_id)
        if not allow_duplicate:
            key = base_callsign(call) if is_callsign(call) else call
            for checkin in existing:
                other = checkin.callsign
                if (base_callsign(other) if is_callsign(other) else other) == key:
                    raise DuplicateCheckIn(call, checkin)
        sequence = max((c.sequence or 0 for c in existing), default=0) + 1
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO checkin (session_id, sequence, logged_at, callsign, name, grid, qth,"
                " report, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, sequence, _now(), call, name, grid, qth, report, notes),
            )
        checkin_id = cast(int, cursor.lastrowid)
        return next(c for c in self.checkins(session_id) if c.id == checkin_id)

    def participants(self, net_id: int) -> list[Participant]:
        rows = self._conn.execute(
            "SELECT c.callsign, c.grid, s.id AS session_id, s.date FROM checkin c"
            " JOIN session s ON s.id = c.session_id WHERE s.net_id = ?"
            " ORDER BY s.date, s.id",
            (net_id,),
        ).fetchall()
        sessions: dict[str, set[int]] = {}
        last_grid: dict[str, str | None] = {}
        last_seen: dict[str, str] = {}
        for row in rows:  # oldest first, so later sessions overwrite
            call = row["callsign"]
            sessions.setdefault(call, set()).add(row["session_id"])
            last_seen[call] = row["date"]
            if row["grid"] or call not in last_grid:
                last_grid[call] = row["grid"] or last_grid.get(call)
        return [
            Participant(call, last_grid[call], len(sessions[call]), last_seen[call])
            for call in sorted(sessions)
        ]

    def expected(self, session_id: int) -> list[Participant]:
        """Known participants of this net who have not checked in to this session.
        They are shown as expected, never as checked in (spec 4.6)."""
        session = self.get_session(session_id)
        # By base call, as the duplicate check does: W1ABC/M tonight means W1ABC is here.
        present = {_base(c.callsign) for c in self.checkins(session_id)}
        return [p for p in self.participants(session.net_id) if _base(p.callsign) not in present]


class RotatorNotTested(Exception):
    """Live mode needs a passed connection test first (invariant 8)."""


class RotatorRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, profile: RotatorProfile) -> RotatorProfile:
        """Insert or update. live and connection_tested in the argument are ignored:
        a new profile is simulated, and changing how it connects needs a new test."""
        if not profile.name.strip():
            raise ValueError("A rotator needs a name.")
        problem = travel_error(TravelRange(profile.az_min, profile.az_max, profile.offset))
        if problem is not None:
            raise ValueError(problem)
        speed = profile.speed_deg_per_s
        if speed is not None and not (math.isfinite(speed) and speed > 0):
            raise ValueError("Rotation speed must be a positive number of degrees per second.")
        if profile.adapter != "simulation":
            if not (profile.host and profile.host.strip()):
                raise ValueError(f"{profile.adapter} rotators need a host.")
            if profile.port is None or not 1 <= profile.port <= 65535:
                raise ValueError(f"Port {profile.port} must be between 1 and 65535.")
        bands = tuple(dict.fromkeys(band.strip() for band in profile.bands if band.strip()))
        self._check_bands(profile.id, bands)
        values = (profile.name.strip(), profile.adapter, profile.host, profile.port,
                  profile.az_min, profile.az_max, profile.offset, speed,
                  ",".join(bands))  # fmt: skip
        with self._conn:
            if profile.id is None:
                cursor = self._conn.execute(
                    "INSERT INTO rotator_profile (name, adapter, host, port, az_min, az_max,"
                    " offset, speed_deg_per_s, bands) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
                rotator_id = cast(int, cursor.lastrowid)
            else:
                before = self.get(profile.id)
                reconnect = (before.adapter, before.host, before.port) != (
                    profile.adapter, profile.host, profile.port
                )
                self._conn.execute(
                    "UPDATE rotator_profile SET name = ?, adapter = ?, host = ?, port = ?,"
                    " az_min = ?, az_max = ?, offset = ?, speed_deg_per_s = ?, bands = ?"
                    " WHERE id = ?",
                    (*values, profile.id),
                )
                if reconnect:
                    self._conn.execute(
                        "UPDATE rotator_profile SET live = 0, connection_tested = 0 WHERE id = ?",
                        (profile.id,),
                    )
                rotator_id = profile.id
        return self.get(rotator_id)

    def _check_bands(self, rotator_id: int | None, bands: tuple[str, ...]) -> None:
        """Each band names a row of the band table and is served by one rotator at most,
        so a band's default rotator is never ambiguous."""
        for band in bands:
            if BandRepository(self._conn).get(band) is None:
                raise ValueError(f"Unknown band {band!r}.")
            other = BandRepository(self._conn).rotator_for(band)
            if other is not None and other.id != rotator_id:
                raise ValueError(f"{band} is already served by {other.name}.")

    def get(self, rotator_id: int) -> RotatorProfile:
        row = self._conn.execute(
            "SELECT * FROM rotator_profile WHERE id = ?", (rotator_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"No rotator with id {rotator_id}.")
        return self._from_row(row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> RotatorProfile:
        return RotatorProfile(
            id=row["id"],
            name=row["name"],
            adapter=row["adapter"],
            host=row["host"],
            port=row["port"],
            az_min=row["az_min"],
            az_max=row["az_max"],
            offset=row["offset"],
            speed_deg_per_s=row["speed_deg_per_s"],
            bands=tuple(band for band in row["bands"].split(",") if band),
            live=bool(row["live"]),
            connection_tested=bool(row["connection_tested"]),
        )

    def list(self) -> list[RotatorProfile]:
        rows = self._conn.execute("SELECT * FROM rotator_profile ORDER BY name").fetchall()
        return [self._from_row(row) for row in rows]

    def record_connection_test(self, rotator_id: int, ok: bool) -> None:
        """A failed test also takes the rotator out of live mode."""
        self.get(rotator_id)
        with self._conn:
            if ok:
                self._conn.execute(
                    "UPDATE rotator_profile SET connection_tested = 1 WHERE id = ?", (rotator_id,)
                )
            else:
                self._conn.execute(
                    "UPDATE rotator_profile SET connection_tested = 0, live = 0 WHERE id = ?",
                    (rotator_id,),
                )

    def set_live(self, rotator_id: int, live: bool) -> None:
        profile = self.get(rotator_id)
        if live and profile.adapter == "simulation":
            raise ValueError(f"{profile.name} is a simulated rotator; it has no live mode.")
        if live and not profile.connection_tested:
            raise RotatorNotTested(f"Test the connection to {profile.name} before going live.")
        with self._conn:
            self._conn.execute(
                "UPDATE rotator_profile SET live = ? WHERE id = ?", (int(live), rotator_id)
            )


class CommandLog:
    """Every Rotate or Stop attempt, including ones rejected before sending (spec 4.7)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(
        self,
        rotator_id: int,
        target_label: str | None,
        requested_true: float | None,
        sent: str | None,
        ok: bool,
        message: str,
        measured: float | None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO rotator_command (at, rotator_id, target_label, requested_true, sent,"
                " ok, message, measured) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (_now(), rotator_id, target_label, requested_true, sent, int(ok), message,
                 measured),
            )  # fmt: skip

    def recent(self, rotator_id: int, limit: int = 50) -> list[CommandRecord]:
        rows = self._conn.execute(
            "SELECT * FROM rotator_command WHERE rotator_id = ? ORDER BY id DESC LIMIT ?",
            (rotator_id, limit),
        ).fetchall()
        return [
            CommandRecord(
                id=row["id"],
                at=row["at"],
                rotator_id=row["rotator_id"],
                target_label=row["target_label"],
                requested_true=row["requested_true"],
                sent=row["sent"],
                ok=bool(row["ok"]),
                message=row["message"],
                measured=row["measured"],
            )
            for row in rows
        ]


class BandRepository:
    """The band table: data the operator can edit, not code (spec 4.8)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Band:
        return Band(row["name"], row["mhz"], bool(row["long_path"]))

    def list(self) -> list[Band]:
        rows = self._conn.execute("SELECT * FROM band ORDER BY mhz, name").fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, name: str) -> Band | None:
        row = self._conn.execute("SELECT * FROM band WHERE name = ?", (name.strip(),)).fetchone()
        return None if row is None else self._from_row(row)

    def add(self, name: str, mhz: float) -> Band:
        clean = name.strip()
        if not clean:
            raise ValueError("A band needs a name.")
        if "," in clean:
            raise ValueError("A band name cannot contain a comma.")
        if not (math.isfinite(mhz) and mhz > 0):
            raise ValueError("Band frequency must be a positive number of MHz.")
        if self.get(clean) is not None:
            raise ValueError(f"Band {clean} already exists.")
        with self._conn:
            self._conn.execute("INSERT INTO band (name, mhz) VALUES (?, ?)", (clean, mhz))
        return Band(clean, mhz, False)

    def set_long_path(self, name: str, on: bool) -> None:
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE band SET long_path = ? WHERE name = ?", (int(on), name.strip())
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Unknown band {name!r}.")

    def delete(self, name: str) -> None:
        serving = self.rotator_for(name)
        if serving is not None:
            raise ValueError(
                f"{name.strip()} is served by {serving.name}; remove it from that rotator first."
            )
        with self._conn:
            self._conn.execute("DELETE FROM band WHERE name = ?", (name.strip(),))

    def rotator_for(self, name: str) -> RotatorProfile | None:
        """The band's default rotator: the one that lists it."""
        band = name.strip()
        for profile in RotatorRepository(self._conn).list():
            if band in profile.bands:
                return profile
        return None


class SettingRepository:
    """Small app settings such as the dashboard's selected band."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def set(self, key: str, value: str | None) -> None:
        with self._conn:
            if value is None:
                self._conn.execute("DELETE FROM setting WHERE key = ?", (key,))
            else:
                self._conn.execute(
                    "INSERT INTO setting (key, value) VALUES (?, ?)"
                    " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )


class QrzRepository:
    """The latest QRZ answer per callsign, with its date (requirements 4.9)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, record: QrzRecord, when: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO qrz_record (callsign, name, grid, qth, lat, lon, geoloc,"
                " looked_up_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (callsign) DO UPDATE SET name = excluded.name,"
                " grid = excluded.grid, qth = excluded.qth, lat = excluded.lat,"
                " lon = excluded.lon, geoloc = excluded.geoloc,"
                " looked_up_at = excluded.looked_up_at",
                (normalize_callsign(record.call), record.name, record.grid, record.qth,
                 record.lat, record.lon, record.geoloc, when),
            )  # fmt: skip

    def get(self, callsign: str) -> tuple[QrzRecord, str] | None:
        row = self._conn.execute(
            "SELECT * FROM qrz_record WHERE callsign = ?", (normalize_callsign(callsign),)
        ).fetchone()
        if row is None:
            return None
        record = QrzRecord(row["callsign"], row["name"], row["grid"], row["qth"], row["lat"],
                           row["lon"], row["geoloc"])  # fmt: skip
        return record, str(row["looked_up_at"])
