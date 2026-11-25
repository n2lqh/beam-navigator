"""Comparing the operator's session with net control's list (owner, 2026-11-24).

After the net, the operator pastes net control's published list on the Import page. The
differences are shown, and the stations net control had that the operator missed can be
added to that night's session. Nothing already logged changes, and nothing here moves a
rotator (invariant 2).
"""

import sqlite3
from dataclasses import dataclass, field

from beam_navigator.core.callsign import base_callsign, is_callsign, normalize_callsign
from beam_navigator.core.maidenhead import is_grid
from beam_navigator.core.models import CheckIn
from beam_navigator.desk import Desk
from beam_navigator.net_control import Entry, NetControl
from beam_navigator.roster_review import Review
from beam_navigator.store.repositories import NetRepository


@dataclass
class Missing:
    """Net control had this station; the operator didn't."""

    callsign: str
    name: str | None
    grid: str | None
    qth: str | None
    add: bool = True


@dataclass(frozen=True)
class OnBoth:
    callsign: str
    differences: list[str] = field(default_factory=list)


@dataclass
class Comparison:
    session_id: int
    raw_text: str
    missing: list[Missing]
    only_mine: list[CheckIn]
    both: list[OnBoth]


def _base(callsign: str) -> str:
    call = normalize_callsign(callsign)
    return base_callsign(call) if is_callsign(call) else call


def _text(value: str | None) -> str:
    return (value or "").strip()


def _differences(mine: CheckIn, name: str | None, grid: str | None) -> list[str]:
    found = []
    if _text(mine.name) and _text(name) and _text(mine.name).casefold() != _text(name).casefold():
        found.append(f"Name: {_text(mine.name)} (you) · {_text(name)} (net control)")
    if _text(mine.grid) and _text(grid) and _text(mine.grid).lower() != _text(grid).lower():
        found.append(f"Grid: {_text(mine.grid)} (you) · {_text(grid)} (net control)")
    return found


class RosterCompare:
    def __init__(self, conn: sqlite3.Connection, desk: Desk) -> None:
        self._nets = NetRepository(conn)
        self._desk = desk

    def compare(self, session_id: int, review: Review) -> Comparison:
        mine = {_base(c.callsign): c for c in self._nets.checkins(session_id)}
        profile = self._desk.profiles.get_active()
        own = _base(profile.callsign) if profile and profile.callsign else None
        seen: set[str] = set()
        missing: list[Missing] = []
        both: list[OnBoth] = []
        for row in review.rows:
            if not (row.include and row.callsign):
                continue
            key = _base(row.callsign)
            # The operator is on net control's list but never logs themself.
            if key in seen or key == own:
                continue
            seen.add(key)
            name, grid, qth = (_text(row.name) or None, _text(row.grid) or None,
                               _text(row.qth) or None)  # fmt: skip
            if key in mine:
                both.append(OnBoth(mine[key].callsign, _differences(mine[key], name, grid)))
            else:
                missing.append(Missing(normalize_callsign(row.callsign), name, grid, qth))
        only_mine = [c for key, c in mine.items() if key not in seen]
        return Comparison(session_id, review.raw_text, missing, only_mine, both)

    def qrz_wanted(self, comparison: Comparison) -> list[str]:
        """Ticked calls with no stored QRZ answer, each once, for the page to look up."""
        wanted: list[str] = []
        for row in comparison.missing:
            if row.add and row.callsign not in wanted and self._desk.qrz.get(row.callsign) is None:
                wanted.append(row.callsign)
        return wanted

    def _filled(self, row: Missing) -> tuple[str, str | None, str | None, str | None, bool]:
        """The list's details, then the saved record's for blanks, then a stored QRZ answer:
        it fills blanks and refines a 4-character grid (owner, 2026-11-24; decision 49)."""
        entry = Entry(row.callsign, row.name or "", row.grid or "", row.qth or "")
        saved = self._desk.stations.get(row.callsign)
        if saved is not None:
            entry.name = entry.name or saved.name or ""
            entry.grid = entry.grid or saved.grid or ""
            entry.qth = entry.qth or saved.qth or ""
        stored = self._desk.qrz.get(row.callsign)
        if stored is not None:
            entry = NetControl.qrz_fill(entry, stored[0])
        grid = entry.grid.strip() or None
        looked_up = grid is not None and grid != row.grid
        return (row.callsign, entry.name.strip() or None, grid, entry.qth.strip() or None,
                looked_up)  # fmt: skip

    def add(self, comparison: Comparison) -> list[CheckIn]:
        ticked = [row for row in comparison.missing if row.add]
        for row in ticked:  # the same check Save makes (final review, 2026-11-24)
            if row.grid and not is_grid(row.grid):
                raise ValueError(f"{row.callsign}: {row.grid!r} is not a grid square.")
        stations = [self._filled(row) for row in ticked]
        if not stations:
            return []
        return self._nets.add_from_list(comparison.session_id, stations, comparison.raw_text)
